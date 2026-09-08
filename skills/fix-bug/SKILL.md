---
description: End-to-end bug fix orchestrator — diagnosis, plan, implement, test, PR
argument-hint: <bug-id>
---

# Fix Bug Skill

Main orchestrator for end-to-end bug fixes. Identifies repos, fires the appropriate
analysis sub-skills, synthesizes their output into a diagnosis and plan, then
implements the fix, runs tests, creates the PR, and updates Jira.

## Invocation

```
/fix-bug JAR-1234
/fix-bug SENTRY-5234891
```

The bug must already exist in `bugs/<bug_id>/bug.json` (created by `/list-bugs`).

## Sub-Skills Called by This Skill

| Sub-skill | When invoked | Output file |
|-----------|-------------|-------------|
| `bug-analysis-backend` | Any `backend`-type repo is involved | `bugs/<bug_id>/analysis-backend.md` |
| `bug-analysis-frontend` | Any `frontend`-type repo is involved | `bugs/<bug_id>/analysis-frontend.md` |

These are NOT invoked by typing slash commands. Instead, after identifying the repos
in Step 1, read the relevant SKILL.md file(s) and execute their instructions inline
before continuing to Step 3.

## Directory Layout

```
bugs/<bug_id>/
    bug.json               ← bug metadata (read-only)
    status.json            ← workflow state (update after every step)
    analysis-backend.md    ← written by bug-analysis-backend sub-skill
    analysis-frontend.md   ← written by bug-analysis-frontend sub-skill
    diagnosis.md           ← synthesized from analysis outputs (written by fix-bug)
    plan.md                ← fix plan (written by fix-bug)
    plan_summary.json      ← structured plan data for UI (written by fix-bug Step 6)
    events.jsonl           ← append-only event log (every event has a "summary" field)
    result.json            ← written when DONE or FAILED
    worktree/
        <repo-name>/       ← one worktree per affected repo

workspace/
    <repo-name>/           ← cloned repos (read for analysis; branched for fixes)
```

## Configuration

`config/repositories.json` — each repo has:

```json
{
  "id":                   "frontend",
  "name":                 "Frontend App",
  "type":                 "frontend",
  "path":                 "workspace/frontend",
  "git_url":              "git@github.com:your-org/frontend.git",
  "base_branch":          "staging",
  "protected_branches":   ["main", "staging", "production"],
  "dependent_repos":      ["backend"],
  "dependency_evidence":  {"backend": "src/services/api.ts:12"},
  "_rejected_dependencies": {},
  "runtime": {
    "test":               true,
    "test_cmd":           "pytest tests/ -x -q",
    "test_env_path":      ". .venv/bin/activate",
    "lint_command":       "ruff check .",
    "venv":               "workspace/frontend/.venv",
    "setup":              null,
    "copy_files":         [{ "from": "workspace/frontend/.env", "to": ".env" }],
    "external_services":  ["postgres", "redis"],
    "analyzed_at":        "2024-01-01T00:00:00Z"
  }
}
```

- **`type`** — `"backend"` or `"frontend"`. Determines which analysis sub-skill runs.
- **`dependent_repos`** — repos this one calls/imports. Analysis sub-skills scan these too.
- **`dependency_evidence`** — maps repo-id to the exact file:line of the API call.
- **`runtime.test`** — boolean. **MUST be checked first in Step 9.** `false` = skip tests entirely, do not run any test command regardless of what other fields say.
- **`runtime.test_cmd`** — full test command including env activation (e.g. `. env/bin/activate && python manage.py test`). Only used when `runtime.test == true`.

`config/integrations.json` — Jira and GitHub credentials.

**`JIRA_PROJECT_KEY` resolution** (used in Step 3):
1. Check env var `JIRA_PROJECT_KEY` first.
2. If unset, read `config/integrations.json` → `jira.projects.<project-slug>`.
3. If neither is set, print the project keys available in `config/integrations.json` and set
   status to `BLOCKED`.

**`ORCHESTRATOR_SESSION_ID`** — read from env var `ORCHESTRATOR_SESSION_ID`. If not set,
use `"unknown-session"`.

## Status Values

```
FETCHED        → just fetched, not started
QUEUED         → fix started, reading bug
SYNCING        → syncing base branch(es)
SYNCED         → base branch(es) up to date
JIRA_CREATING  → creating Jira ticket (Sentry bugs only)
JIRA_CREATED   → Jira ticket exists
DIAGNOSING     → analysis sub-skills running
DIAGNOSED      → diagnosis.md written (all analysis complete)
PLANNING       → writing fix plan
PLANNED        → plan.md saved
BRANCHING      → creating feature branch(es)
BRANCHED       → branch(es) created
WORKTREE_READY → worktrees set up
IMPLEMENTING   → writing code fix
IMPLEMENTED    → changes committed
TESTING        → running tests
TESTED         → all tests passing
TEST_SKIPPED   → tests skipped (test=false or test_cmd missing in repositories.json)
PR_CREATING    → creating pull request
PR_CREATED     → PR open on GitHub
JIRA_UPDATING  → posting update to Jira
JIRA_UPDATED   → Jira updated
DONE           → everything complete
FAILED         → unrecoverable error
BLOCKED        → needs human input
```

## Heartbeat Rule

Update `last_heartbeat` (and `updated_at`) in `status.json` at least every **5 minutes** during any
long-running work. For steps that involve reading many files, calling external APIs, or running
tests, write a mid-step heartbeat **before** you start the work and another one **after each
sub-task** completes — do not wait until the full step finishes.

Critical checkpoints that MUST write a heartbeat immediately before starting:
- Before dispatching analysis sub-skills (Step 1)
- Before each repo's analysis read (when scanning many files)
- Before running tests (Step 9)
- Before creating the PR (Step 10)

The UI marks a session STALE after **30 minutes** of no heartbeat. Writing a heartbeat every
5 minutes gives a 6× safety margin — use it.

## Event Summary Rule

**Every event appended to `events.jsonl` MUST include a `summary` field** — a single sentence describing what happened. This is shown directly in the UI timeline and is the only way operators know what each step did.

The `summary` must be specific: include repo names, file paths, error messages, Jira keys, HTTP status codes — never write "step completed" or leave it blank.

For BLOCKED events, also include:
- `"error"` — the exact failure (HTTP code, missing env var name, command output)
- `"action"` — what the human must do to resume (e.g. `"Set JIRA_API_TOKEN env var and re-run /fix-bug {bug_id}"`)

For FAILED events, also include:
- `"error"` — the exact failure message and command that failed

The `error` field in `status.json` must contain the same specific message — never a generic label.

## Resume Behaviour

On `/fix-bug <bug_id>` when `status.json` already exists:
1. Read current `status`.
2. If `DONE` or `FAILED` → report result and stop.
3. If `BLOCKED` → print the error message and the action needed from `status.json`, then
   wait for the user to respond before continuing.
4. Otherwise → use the table below to resume at the correct step. Do NOT restart from scratch.
5. Update `session_id` in `status.json` to `ORCHESTRATOR_SESSION_ID`.

### STATUS → Resume Step Mapping

| Status | Resume at |
|--------|-----------|
| `FETCHED` | Step 0 — Read Bug |
| `QUEUED` | Step 1 — Identify Repos (run fetch first) |
| `SYNCING` | Step 2 — Sync Base Branches (re-run sync) |
| `SYNCED` | Step 3 — Create / Confirm Jira Ticket |
| `JIRA_CREATING` | Step 3 — Create / Confirm Jira Ticket |
| `JIRA_CREATED` | Step 1 — Identify Repos / re-dispatch sub-skills (if analysis files missing), else Step 4 — Synthesize Diagnosis |
| `DIAGNOSING` | Step 1 — Identify Repos / re-dispatch analysis sub-skills |
| `DIAGNOSED` | Step 5 — Print the Diagnostic |
| `PLANNING` | Step 6 — Print the Fix Plan |
| `PLANNED` | Step 7 — Create Feature Branch and Worktree |
| `BRANCHING` | Step 7 — Create Feature Branch and Worktree |
| `BRANCHED` | Step 7 — Create Feature Branch and Worktree (worktree step) |
| `WORKTREE_READY` | Step 8 — Implement the Fix |
| `IMPLEMENTING` | Step 8 — Implement the Fix |
| `IMPLEMENTED` | Step 9 — Run Tests |
| `TESTING` | Step 9 — Run Tests |
| `TESTED` | Step 10 — Create Pull Request |
| `TEST_SKIPPED` | Step 10 — Create Pull Request |
| `PR_CREATING` | Step 10 — Create Pull Request |
| `PR_CREATED` | Step 11 — Update Jira |
| `JIRA_UPDATING` | Step 11 — Update Jira |
| `JIRA_UPDATED` | Step 12 — Mark Done |

---

## Full Workflow

### Step 0 — Read Bug

Read `bugs/<bug_id>/bug.json`. If missing → print error "Run /list-bugs first" and stop.

Update status: `QUEUED`, step: `reading_bug`, next_step: `identifying_repos`.

Append event:
```json
{"timestamp": "...", "event": "FIX_STARTED", "bug_id": "...",
 "summary": "Starting fix for {bug_id} — {title}. Source: {source}, severity: {severity}."}
```

---

### Step 1 — Identify Repos, Fetch, and Dispatch Analysis

Read `config/repositories.json`. Match `bug.json.project` against repo `id` or `name`.

If the repo cannot be determined, ask the user:
```
Which repository does this bug belong to? (check config/repositories.json)
```

**Check for pre-built repo context:**

For each candidate repo, check whether `repo-context/<repo-id>/` exists and contains
`context.md`, `structure.json`, `conventions.md`, and `patterns.json`. If any repo is missing
context, print a warning:
```
No context for <repo-id>. Run /repo-context <repo-id> first for faster, more accurate analysis.
```
Continue regardless — the analysis sub-skills will fall back to direct scanning.

**Build the candidate set:**
- Start with the primary repo
- Add every repo listed in `primary.dependent_repos`
- For each of those, also add their `dependent_repos` (one level deep)

**Partition by type:**
- Backend candidates: repos where `type == "backend"`
- Frontend candidates: repos where `type == "frontend"`

**Fetch before analysis** — analysis reads from `origin/<base_branch>` via `git show`, so
a fresh fetch ensures the sub-skills see the latest code. Run for each candidate repo:

```bash
git -C workspace/<repo-id> fetch origin
```

If fetch fails, print a warning but continue — analysis will use whatever is cached locally.

Update status: `DIAGNOSING`, step: `dispatching_analysis`, next_step: `syncing_branches`.

Set `status.repos` to the full candidate set (confirmed after analysis in Step 4).

**Invoke analysis sub-skills in this order:**

#### If any backend candidates exist:
Read `skills/bug-analysis-backend/SKILL.md` and execute its full instructions for this bug.
The skill will load `repo-context/<repo-id>/` for each backend repo before scanning code.
Wait until `bugs/<bug_id>/analysis-backend.md` is written before continuing.

#### If any frontend candidates exist:
Read `skills/bug-analysis-frontend/SKILL.md` and execute its full instructions for this bug.
The skill will load `repo-context/<repo-id>/` for each frontend repo and backend context for
API contract cross-checking. It will also read `analysis-backend.md` if it exists.
Wait until `bugs/<bug_id>/analysis-frontend.md` is written before continuing.

Append event:
```json
{"timestamp": "...", "event": "ANALYSIS_DISPATCHED", "repos": ["..."],
 "summary": "Dispatching analysis for {repos}. Backend: {list}. Frontend: {list}. Context available: {yes/no per repo}."}
```

---

### Step 2 — Sync Base Branches

After analysis is complete, sync the base branch for each **confirmed affected repo**
(those where analysis found actual code to change). This full checkout-and-pull makes the
main clone current so the worktree branch created in Step 7 starts from the right base.

```bash
BASE_BRANCH=<repo.base_branch>   # from repositories.json per repo
REPO_PATH=workspace/<repo-name>

git -C $REPO_PATH checkout $BASE_BRANCH
git -C $REPO_PATH pull origin $BASE_BRANCH
```

Update status: `SYNCING` → `SYNCED`, next_step: `jira_ticket`.

Append event:
```json
{"timestamp": "...", "event": "BRANCH_SYNCED", "repos": ["..."],
 "summary": "Synced {base_branch} in {repos} — worktree base is up to date."}
```

If sync fails → status: `FAILED`, error: git output.

---

### Step 3 — Create / Confirm Jira Ticket

Update status: `JIRA_CREATING`, step: `creating_jira_ticket`.

Invoke `skills/create-jira-bug/SKILL.md` inline, passing:
- `bug_id` — the current bug ID
- `bug` — the parsed `bugs/<bug_id>/bug.json` object
- `project_slug` — the primary repo slug (first entry in the confirmed repo list)
- `session_id` — `ORCHESTRATOR_SESSION_ID`
- `confirmed_repos` — the confirmed repo list from Step 1

The skill resolves the Jira project key, maps severity to priority, reads analysis/diagnosis files, builds the ADF payload, and calls the Jira API (MCP first, REST fallback).

**Handle the return value:**

| `result.reason` | Action |
|---|---|
| — (key present) | Write `status.jira_ticket = result.key`. Update status: `JIRA_CREATED`, `next_step: synthesizing_diagnosis`. |
| `"no_project_key"` | Print available keys from `result.available`. Set status: `BLOCKED`. Stop. |
| `"jira_not_configured"` or `"api_error"` | Set status: `FAILED`, error: `result.reason`. Stop. |

Append event after success:

If `bug.source = "jira"` (ticket linked):
```json
{"timestamp": "...", "event": "JIRA_TICKET_LINKED", "jira_key": "...",
 "summary": "Linked to existing {jira_key}. Posted start comment (session: {session_id})."}
```

If `bug.source = "sentry"` (ticket created):
```json
{"timestamp": "...", "event": "JIRA_TICKET_CREATED", "jira_key": "...",
 "summary": "Created {jira_key} in {project_key} (priority: {priority}). Method: {result.method}."}
```

---

### Step 4 — Synthesize Diagnosis

Read the analysis output files:
- `bugs/<bug_id>/analysis-backend.md` (if exists)
- `bugs/<bug_id>/analysis-frontend.md` (if exists)

Synthesize them into a single `bugs/<bug_id>/diagnosis.md`.

Use the pointer-based format below — no long paragraphs. Every field must be filled from
actual analysis output; never write a plausible guess. Use `unknown` only if genuinely absent.

```markdown
# Diagnosis — {bug_id}

> {one-sentence user-visible symptom — what a user or operator sees, e.g. "GET /garage/team-points returns HTTP 500 whenever loc_id is omitted"}

**Root cause** → `{file}:{line}` — {one sentence: what is broken and why}  
**Why it breaks** — {2–3 sentences: the exact mechanism — which call path reaches the broken line, what precondition must be true, why the error propagates the way it does instead of being caught}  
**Fix lives in** — `{backend | frontend | both}`  
**Frequency** — {N occurrences | first {YYYY-MM-DD} | last {YYYY-MM-DD}}  *(omit line if unknown)*

---

### Affected repos
- `{repo-id}` — {one phrase: what is broken here}
- `{repo-id}` — {one phrase}  *(add line per confirmed repo; omit unconfirmed candidates)*

### Affected code

**REQUIRED:** line numbers must be exact — read the source file to confirm before writing.
Do not write "else branch" or "inside function" — write the actual line number.

| Repo | File | Line | Issue |
|------|------|------|-------|
| `{repo}` | `{file}` | **{exact line number}** | {one phrase — what is wrong at this exact line} |
| `{repo}` | `{file}` | **{exact line number}** | {one phrase} |

### Broken code

For each affected line, quote the exact code that is wrong:

```
{file}:{line}
{exact line of code as it appears in the file}
```

*(one block per broken location; repeat for each affected file)*

### Reproduction
1. {concrete step — include actual endpoint, params, or user action where known}
2. {next step}
→ `{ErrorType: message}` or `{observed failure / HTTP status}`

### Implicated commits
- `{hash}` · {YYYY-MM-DD} · {author} — {one phrase: why suspicious}
*(omit this section if no suspicious commits found)*

### API / contract impact
`{none}` — or one sentence describing the mismatch if a backend contract change affects frontend

### Coverage gaps
- {one phrase per gap: missing test, missing guard, untested edge case — reference the specific test file and method that should exist}
*(omit this section if no gaps found)*
```

Update `status.repos` to only the **confirmed** repos (remove candidates that analysis
found to be uninvolved).

Update status: `DIAGNOSED`, step: `diagnosis_complete`, next_step: `printing_diagnostic`.

Append event:
```json
{"timestamp": "...", "event": "DIAGNOSIS_COMPLETE", "repos": ["..."],
 "summary": "{root cause one sentence}. Affected: {file:line list}. Confirmed repos: {list}."}
```

---

### Step 5 — Print the Diagnostic

Build the diagnostic block for each confirmed repo in scope, drawn from `diagnosis.md` (and from
`analysis-backend.md` / `analysis-frontend.md` for fields not yet in diagnosis.md).
For a cross-repo bug build both blocks back to back, primary repo first.

Every field must come from a file you actually read. Never fill a field with a plausible guess —
write `unknown` and say why.

**REQUIRED — rewrite `bugs/<bug_id>/diagnosis.md` with the diagnostic block at the very top.**

Read the existing `diagnosis.md` content first. Then overwrite the entire file so its new
content is:

1. A `## Quick Diagnostic` heading
2. A plain code block (three backticks, no language tag) containing the filled-in diagnostic block
3. A blank line
4. The original `diagnosis.md` content (starting with `# Diagnosis — {bug_id}`) appended verbatim after

The diagnostic block inside the code fence looks like this (fill in real values for every field).
Every field must come from analysis output you actually read — never guess:

~~~
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUG DIAGNOSTIC — <repo-id> (<backend | frontend>)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Exception : <ExceptionType: message — or "none" for logic/UI bugs>
  Endpoint  : <METHOD /path — or screen/component for frontend>
  Frequency : <N occurrences | first YYYY-MM-DD | last YYYY-MM-DD>

  Location
    File   : <repo>/path/to/file.py:<line>
    Code   : <offending line quoted exactly from the source file>

  Analysis
    Root cause : <one sentence — what is wrong and why>
    Layer      : <view | service | model | celery | component | state | integration | ...>
    Blast      : <Low | Medium | High>
    Fix        : <one phrase — what needs to change, e.g. "add loc_id guard before dict access">

  Commits implicated
    <hash> · <YYYY-MM-DD> · <author> — <one phrase>
    (write "none identified" if no suspicious commits found)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
~~~

For a cross-repo bug, include one block per repo inside the same code fence, separated by a blank line.

After writing the file, print the same diagnostic block to the terminal so the user can see it.

Update `status.json`: step: `diagnostic_printed`, next_step: `creating_fix_plan`. Update `last_heartbeat`.
Append event:
```json
{"timestamp": "...", "event": "DIAGNOSTIC_PRINTED",
 "summary": "Diagnostic printed. Exception: {type}. Location: {file}:{line}. Endpoint: {endpoint}. Blast: {level}."}
```

---

### Step 6 — Write the Fix Plan

Update status: `PLANNING`, step: `creating_fix_plan`.

**REQUIRED — write `bugs/<bug_id>/plan.md` in two parts, in this order:**

**Part 1 — Summary block at the very top of the file.**

The file must begin with a `## Fix Plan Summary` heading, followed by a plain code block
(three backticks, no language tag) containing the filled-in fix plan block. Use real values —
`BEFORE` must be quoted exactly from the analysis file, `AFTER` is the literal replacement:

~~~
╔══════════════════════════════════════════════════════════════╗
║  FIX PLAN                                                    ║
╚══════════════════════════════════════════════════════════════╝

  Bug       : <one-sentence>
  Layer     : <layer>   Blast: <Low | Medium | High>
  Root cause: <file:line>

  Proposed fix
    File: <file>:<line>
    BEFORE: <exact old code>
    AFTER : <exact new code>
    Why   : <one sentence>

  What this fix does NOT do
    · <explicit non-goal 1>
    · <explicit non-goal 2>

  Remaining steps:
    Create worktree     [auto]
    Apply fix           [auto]
    Self-review         [auto]
    Data fix (if any)   [HALT — needs human sign-off before continuing]
    Commit              [auto]
    Run tests           [auto]
    Code review         [auto]
    Push + open PR      [auto]
    Update Jira         [auto]
    Completion summary  [auto]

  Files that will change: <list>
══════════════════════════════════════════════════════════════
~~~

For a cross-repo bug, include one fix block per repo inside the same code fence, separated by a blank line.

Rules:
- `BEFORE` must be quoted exactly from `analysis-backend.md` or `analysis-frontend.md`.
- "What this fix does NOT do" is mandatory — at least one real non-goal.
- If the fix requires a data migration or database change: set status to `BLOCKED`, print
  "Data fix required — please review and reply 'approved' to continue", and wait.

After writing the summary block, print it to the terminal so the user can see it. Then proceed
immediately — no user confirmation needed (unless data fix, as above).

**Part 2 — Detailed plan content appended after the summary block.**

Append the following markdown immediately after the closing code fence of Part 1:

Write `bugs/<bug_id>/plan.md`:

```markdown
# Fix Plan — {bug_id}

**Jira:** [{JIRA_KEY}]({JIRA_BASE_URL}/browse/{JIRA_KEY}) — {title}  
**Risk:** {Low | Medium | High} · **Repos:** {comma-separated repo list}

---

## Root Cause

> {one sentence — the concrete file:line and what is broken, from diagnosis.md}

**Why it breaks:** {2–3 sentences explaining the mechanism — which call path reaches the broken line, what invariant is violated, why it manifests under the described conditions}

---

## Changes

For each file changed, write a sub-section with the exact line(s) and BEFORE/AFTER code
quoted directly from the analysis file. Do not describe the change in prose — show the code.

### `{repo-id}`

**`{path/to/file.py}:{line}` — {one phrase: what this change fixes}**

~~~python
# BEFORE (line {N}, quoted exactly from the source file)
{exact old code — copy from analysis-backend.md or analysis-frontend.md Fix section}
~~~

~~~python
# AFTER
{exact replacement code}
~~~

*(one BEFORE/AFTER block per changed hunk; if the same file has multiple hunks, list them in order)*
*(repeat sub-section header for each additional repo)*

---

## Tests to Add

For each test, write the class name, method name, and a concrete skeleton showing
what to set up, what to call, and what to assert. Do not write prose — write code.

**`{path/to/tests.py}` — `{TestClass}.{test_method_name}`**

~~~python
def {test_method_name}(self):
    # Arrange: {what state to create — DB records, mocks, env}
    {setup lines}

    # Act
    response = self.client.{method}('{endpoint}', {params})

    # Assert
    self.assertEqual(response.status_code, {expected_code})
    self.assertEqual({actual_value}, {expected_value})
~~~

*(one skeleton per new test method; if multiple tests needed, repeat the block)*

---

## Risk

| | |
|--|--|
| **Risk level** | {Low · Medium · High} |
| **Side effects** | {any side effects, or "none"} |
| **API contract** | {No change · Yes — describe impact} |
| **Rollback** | {exact revert steps — file names and what to undo} |

---

## Implementation Steps

Each step that changes code must show the exact before → after inline.
Steps that are commands must show the exact command.

1. `{file:line}` — {what to change}  
   **Before:** `{old line quoted exactly}`  
   **After:** `{new line}`  
   *(for multi-line hunks, reference the BEFORE/AFTER block in ## Changes above)*

2. `{file:line}` — {next change}  
   **Before:** `{old line}`  
   **After:** `{new line}`

3. Add test `{TestClass}.{test_method_name}` in `{test file}` *(see skeleton in ## Tests to Add)*

4. Stage and commit:
   ~~~bash
   git add {file1} {file2}
   git commit -m "fix({JIRA_KEY}): {short description of what was fixed}"
   ~~~

5. Run `{test_cmd from runtime.test_cmd}` — all tests must pass before pushing

6. `git push origin {branch_name}` and open PR targeting `{base_branch}`
```

Post plan to Jira after printing and after writing `plan.md` using **MCP first, REST fallback**:

**Try MCP:**
```
mcp__atlassian__create_comment(
  issue_key = JIRA_KEY,
  body      = "Fix Plan ready. Root cause: {root_cause}. Repos: {repo list}. Branch: {branch}."
)
```

**If MCP unavailable, fall back to REST:**
```
POST {JIRA_BASE_URL}/rest/api/3/issue/{JIRA_KEY}/comment
Authorization: Basic <base64(JIRA_EMAIL:JIRA_API_TOKEN)>
Content-Type: application/json
{
  "body": {
    "type": "doc", "version": 1,
    "content": [{"type": "paragraph", "content": [{"type": "text",
      "text": "Fix Plan ready. Root cause: {root_cause}. Repos: {repo list}. Branch: {branch}."}]}]
  }
}
```

After writing `plan.md`, write `bugs/<bug_id>/plan_summary.json` with the structured plan data for the UI:

```json
{
  "root_cause": "{one sentence from diagnosis — the concrete file:line and what was wrong}",
  "risk_level": "Low|Medium|High",
  "risk_explanation": "{one sentence — side effects, API contract impact, rollback approach}",
  "repos_changes": {
    "{repo_id}": ["{file:line} — {what changes and why}"]
  },
  "tests": [
    "{test file path} — {what the test covers}"
  ],
  "implementation_steps": [
    "1. {specific step — names the file and exact change}",
    "2. {step 2}",
    "..."
  ]
}
```

Update status: `PLANNED`, step: `plan_saved`, next_step: `creating_branch`.

Append events:
```json
{"timestamp": "...", "event": "PLAN_CREATED",
 "summary": "Fix plan written. Risk: {level}. Files to change: {list}. Root cause: {one sentence}."}
{"timestamp": "...", "event": "JIRA_PLAN_POSTED", "jira_key": "...",
 "summary": "Plan comment posted to {jira_key}."}
```

---

### Step 7 — Create Feature Branch and Worktree (per repo)

For each confirmed affected repo:

**Branch name — read the template from `config/repositories.json.branch_naming`, never hardcode.**

- `JIRA_KEY` set (normal path — Step 3 resolved it) → template `branch_naming.bug_with_jira`, substitute `{jira_key} = JIRA_KEY` and `{description} = <short-description>`.
- `JIRA_KEY` unset (defensive — Step 3 should have BLOCKED before here) → template `branch_naming.bug_no_jira`, substitute `{bug_id}` and `{description}`.

`<short-description>` = kebab-case of the bug title (2–5 words, lowercase, punctuation → `-`).

With the default config, that produces `bug-JAR-1234-login-endpoint-500`. Same branch name is used across every affected repo.

**Safety check:** Resolved branch name must NOT be in `protected_branches` (read from this repo's
entry in `config/repositories.json`). If it is, abort immediately — never push to a
protected branch.

**Sync-then-worktree** — same discipline as `/execute-plan` Step 2b. Never cut a worktree from a stale base clone:

```bash
# 1. Ensure workspace clone is on the fresh base branch
git -C workspace/<repo> fetch origin --prune
git -C workspace/<repo> checkout <repo.base_branch>
git -C workspace/<repo> pull --ff-only origin <repo.base_branch>

# 2. Remove stale worktree if it exists
WORKTREE_PATH=bugs/{bug_id}/worktree/<repo-name>
git -C workspace/<repo> worktree remove $WORKTREE_PATH --force 2>/dev/null || true

# 3. Cut the worktree AND create the branch atomically from origin/<base_branch>
git -C workspace/<repo> worktree add $WORKTREE_PATH -b <resolved-branch-name> origin/<repo.base_branch>
```

If checkout fails on a dirty workspace clone or `pull --ff-only` fails: status `BLOCKED` with the exact git error and a note telling the user to fix the workspace clone's state, then re-run `/fix-bug {bug_id}`. Never `stash`, `checkout -f`, or force-pull.

Save `status.branch = "<resolved-branch-name>"`.

Update status: `BRANCHING` → `BRANCHED` → `WORKTREE_READY`, next_step: `implementing_fix`.

Append events:
```json
{"timestamp": "...", "event": "BRANCH_CREATED", "branch": "...",
 "summary": "Branch {branch_name} created in {repos} from origin/{base_branch}."}
{"timestamp": "...", "event": "WORKTREE_CREATED", "branch": "...",
 "summary": "Worktrees ready at bugs/{bug_id}/worktree/<repo> for each affected repo."}
```

**Provision each worktree immediately after creation:**

For each affected repo, read `config/repositories.json` → `runtime` and run these three steps in order:

1. **Symlink venv** — if `runtime.venv` is set and non-null:
   ```bash
   # absolute path (starts with /): use directly
   ln -sfn /abs/path/to/venv <worktree>/$(basename /abs/path/to/venv)

   # relative path: prepend project root
   ln -sfn <project_root>/<runtime.venv> <worktree>/$(basename <runtime.venv>)
   ```
   Skip if `runtime.venv` is null. The venv is already fully set up — do not run pip install unless `runtime.setup` explicitly says so.

2. **Run setup in worktree** — if `runtime.setup` is set and non-null:
   ```bash
   cd <worktree> && <runtime.setup>
   ```
   Skip if `runtime.setup` is null (the common case when the venv is pre-built).

3. **Copy env files** — for each `{ "from": "...", "to": "..." }` in `runtime.copy_files`:
   ```bash
   mkdir -p <worktree>/$(dirname <to>)
   cp <project_root>/<from> <worktree>/<to>
   ```
   Skip any entry whose source file does not exist — record the skip, do not fail.

---

### Step 8 — Implement the Fix

Work in each `bugs/{bug_id}/worktree/<repo-name>/`. Follow `plan.md` exactly.

Rules:
- Only change what the plan specifies
- Do not modify unrelated code
- Add a regression test per repo that would have caught this bug
- Never commit to a `protected_branch`

**Self-review before committing:** After writing changes, re-read each modified file and verify:
- The change matches the `AFTER` block from the fix plan exactly
- No unintended lines were changed
- The regression test exercises the broken code path

Commit per repo — stage only the files listed in `plan.md` under "Files that will change".

**Commit subject template comes from `config/repositories.json.commit_message`**, never hardcoded here:

- `JIRA_KEY` set (normal path) → template `commit_message.bug_fix_with_jira`.
- `JIRA_KEY` unset (defensive) → template `commit_message.bug_fix_no_jira`.

Substitute `{type} = fix` (bug fixes are always `fix`), `{scope}` = the repo id or the primary module changed, `{summary}` = a one-line description of what was repaired, `{jira_key} = JIRA_KEY`.

With the default config that produces the subject: `fix(everest_jarvis): repair login endpoint 500 JAR-1234`.

Then append a structured body describing root cause, fix, and tests. `git commit -m` takes the subject on line 1 and body starting on line 3 (blank separator on line 2):

```bash
# Stage each file explicitly — never use 'git add -p' (interactive) or 'git add .' (too broad)
git -C bugs/{bug_id}/worktree/<repo-name> add <file1> <file2> ... <fileN>

git -C bugs/{bug_id}/worktree/<repo-name> commit -m "<subject from template>

- Root cause: {one sentence}
- Fix: {one sentence}
- Tests: {what was added}

Jira: {JIRA_KEY}
"
```

The `Jira: {JIRA_KEY}` trailer line is kept in the body for tools (Jira Smart Commits, GitHub Jira integration) that scrape trailers even when the key is already inline in the subject — redundant but harmless.

Update status: `IMPLEMENTED`, step: `fix_committed`, next_step: `running_tests`.

Append event:
```json
{"timestamp": "...", "event": "IMPLEMENTATION_COMPLETE", "commits": {"repo": "hash"},
 "summary": "Fix committed in {repos}. Files: {list}. Test added: {test name or 'none'}."}
```

---

### Step 9 — Run Tests

> **Gate:** Before doing anything else, read `runtime.test` for every confirmed repo.
> If `runtime.test == false` for a repo, **do not run any test command for that repo** — not `test_cmd`, not `test_command_full`, not any fallback default. Skip directly.
> Do NOT infer test commands from the codebase or run ad-hoc commands like `pytest` or `npm test` unless `runtime.test == true` and `runtime.test_cmd` is set.

For each confirmed affected repo, read `config/repositories.json` → `runtime` block and check:

| Field | Required | Purpose |
|-------|----------|---------|
| `test` | yes | `true` = run tests, `false` = skip |
| `test_cmd` | yes (if test=true) | full command including env activation (e.g. `. env/bin/activate && python manage.py test`) |

#### If `runtime.test == false` OR `runtime.test_cmd` is missing/empty for ALL repos:

Update status: `TEST_SKIPPED`, step: `tests_skipped`, next_step: `creating_pr`.

Append event:
```json
{"timestamp": "...", "event": "TESTS_SKIPPED", "reason": "test=false or test_cmd not set",
 "summary": "Tests skipped for {repos} — runtime.test=false or test_cmd not configured in repositories.json."}
```

Print:
```
⚠  Tests skipped for <repo> — test=false or test_cmd not configured in repositories.json
```

Proceed directly to Step 10.

#### If `runtime.test == true` AND `runtime.test_cmd` is set (for at least one repo):

Update status: `TESTING`, step: `running_tests`.

Append event: `TESTS_STARTED`.

For each repo where `test == true` and `test_cmd` is set, run from the worktree directory
`bugs/{bug_id}/worktree/<repo-name>/`:

```bash
# test_cmd already includes activation — run it directly
<runtime.test_cmd>    # e.g. ". env/bin/activate && python manage.py test"
```

For repos where `test == false` or `test_cmd` is missing, print a skip notice and continue:
```
⚠  Tests skipped for <repo> — test=false or test_cmd not set
```

If tests fail: append `TEST_FAILED` event, then retry up to 3 times; append `TEST_RETRIED`
before each retry. After 3 failures → status: `BLOCKED`,
error: "Tests failing after 3 attempts. Review output above." Print the last test output and
wait for the user to respond before continuing.

If all runnable repos pass → status: `TESTED`, step: `tests_passing`, next_step: `creating_pr`.

Append event:
```json
{"timestamp": "...", "event": "TESTS_PASSED",
 "summary": "All tests passing in {repos}. Command: {test_cmd}. Result: {N passed, 0 failed}."}
```

---

### Step 10 — Create Pull Request (per repo)

Update status: `PR_CREATING`, step: `creating_pr`.

One PR per affected repo. PR target is `bug_merge_dest_branch` if set in `repositories.json`, otherwise falls back to `base_branch`.

**Push the branch first** — before creating any PR:
```bash
git -C workspace/<repo> push -u origin {status.branch}
```

(The push is run against the main clone because the worktree shares the same `.git` directory.)

If push fails because the remote branch already exists → continue (use `--force-with-lease` only
if the remote branch was created by a previous run of this same fix session).

#### Method A — gh CLI (preferred)

```bash
gh auth status 2>&1   # check if authenticated
```

If exit code 0:
```bash
gh pr create \
  --title "fix({JIRA_KEY}): {short description}" \
  --body "..." \
  --base <repo.bug_merge_dest_branch ?? repo.base_branch> \
  --head {status.branch}
```

If `gh auth status` exits non-zero (not authenticated), print:
```
gh CLI not authenticated — falling back to GitHub REST API.
To use gh in future runs: gh auth login
```
Then proceed to Method B.

#### Method B — GitHub REST API fallback

When `gh` is not installed or not authenticated, try REST with `GITHUB_TOKEN`:

```
POST https://api.github.com/repos/{owner}/{repo}/pulls
Authorization: Bearer $GITHUB_TOKEN
{
  "title": "fix({JIRA_KEY}): {short description}",
  "body": "...",
  "head": "{status.branch}",
  "base": "{bug_merge_dest_branch ?? base_branch}"
}
```

If the REST call returns 401 Unauthorized or 422 Unprocessable Entity (token invalid/expired):
- Check if `gh` is installed: `which gh`
- If `gh` is installed: set status `BLOCKED`, print:
  ```
  GITHUB_TOKEN is invalid or expired.
  Fix option A (recommended): run `gh auth login` in your terminal, then resume this bug fix.
  Fix option B: set a valid GITHUB_TOKEN with `repo` scope in your .ENV file and restart.
  ```
- If `gh` is not installed: set status `BLOCKED`, print:
  ```
  GITHUB_TOKEN is invalid or expired and gh CLI is not installed.
  Fix option A: install gh CLI (brew install gh) then run `gh auth login`, and resume.
  Fix option B: set a valid GITHUB_TOKEN with `repo` scope in your .ENV file and restart.
  ```

PR body template:
```
## What
{root cause paragraph}

## Fix
{what changed and why}

## Tests
{what tests were added/updated}

## Jira
[{JIRA_KEY}]({JIRA_BASE_URL}/browse/{JIRA_KEY})

## Related PRs
{link other repo PRs if this is a multi-repo fix}

---
Generated by AI Bug Fix Orchestrator
```

Save each PR URL to `status.pr_url` (if multiple, use the primary repo's PR).

Update status: `PR_CREATED`, step: `pr_open`, next_step: `updating_jira`.

Append event:
```json
{"timestamp": "...", "event": "PR_CREATED", "pr_urls": {"repo": "url"},
 "summary": "PR opened in {repos} targeting {base_branch}. Method: {gh CLI or REST API}."}
```

---

### Step 11 — Update Jira

Update status: `JIRA_UPDATING`, step: `updating_jira`.

Post a fix-complete comment using **MCP first, REST fallback**.

Build the comment text:
```
Fix Complete

Root Cause : {one sentence from diagnosis.md}
Repos Fixed: {repo list}
Branch     : {branch name}
PRs        :
  backend  : {pr_url}
  frontend : {pr_url}
Tests      : All passing
Commits    : {repo: hash map}
Session    : {ORCHESTRATOR_SESSION_ID}
```

**Try MCP:**
```
mcp__atlassian__create_comment(
  issue_key = JIRA_KEY,
  body      = "<comment text above>"
)
```

**If MCP unavailable, fall back to REST:**
```
POST {JIRA_BASE_URL}/rest/api/3/issue/{JIRA_KEY}/comment
Authorization: Basic <base64(JIRA_EMAIL:JIRA_API_TOKEN)>
Content-Type: application/json
{
  "body": {
    "type": "doc", "version": 1,
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "<comment text above>"}]}]
  }
}
```

Transition ticket to "In Review" using **MCP first, REST fallback**.

**Try MCP:**
```
mcp__atlassian__transition_issue(
  issue_key       = JIRA_KEY,
  transition_name = "In Review"
)
```

**If MCP unavailable, fall back to REST:**
```
GET  {JIRA_BASE_URL}/rest/api/3/issue/{JIRA_KEY}/transitions
     Authorization: Basic <base64(JIRA_EMAIL:JIRA_API_TOKEN)>
     → find transition id where name == "In Review"

POST {JIRA_BASE_URL}/rest/api/3/issue/{JIRA_KEY}/transitions
     Authorization: Basic <base64(JIRA_EMAIL:JIRA_API_TOKEN)>
     Content-Type: application/json
     { "transition": { "id": "<id>" } }
```

Update status: `JIRA_UPDATED`, next_step: `marking_done`.

Append events:
```json
{"timestamp": "...", "event": "JIRA_UPDATED", "jira_key": "...",
 "summary": "{jira_key} updated with fix details — root cause, repos, PR links posted as comment."}
{"timestamp": "...", "event": "JIRA_TRANSITIONED", "jira_key": "...",
 "summary": "{jira_key} transitioned to In Review. Result: {success or HTTP error code}."}
```

---

### Step 12 — Mark Done

Write `bugs/{bug_id}/result.json`:
```json
{
  "bug_id":        "{bug_id}",
  "jira_ticket":   "{JIRA_KEY}",
  "source":        "sentry|jira",
  "status":        "DONE",
  "root_cause":    "{one sentence}",
  "repos":         ["backend", "frontend"],
  "branch":        "{status.branch}",
  "commits":       {"backend": "{hash}", "frontend": "{hash}"},
  "files_changed": ["backend/path/file.py", "frontend/src/file.ts"],
  "tests_added":   ["backend/tests/test_xyz.py", "frontend/src/__tests__/api.test.ts"],
  "pr_urls":       {"backend": "{url}", "frontend": "{url}"},
  "completed_at":  "{now ISO}"
}
```

Update status: `DONE`, next_step: null.

Append event:
```json
{"timestamp": "...", "event": "BUG_COMPLETED",
 "summary": "Fix complete. Jira: {jira_key}. Branch: {branch}. PRs: {repo: url}. Files: {list}."}
```

Print summary:
```
╔═══════════════════════════════════════════════════════════════╗
║  Bug Fix Complete                                             ║
╠═══════════════════════════════════════════════════════════════╣
║  Jira:    JAR-1234                                            ║
║  Branch:  bug-JAR-1234-login-endpoint-500                     ║
║  Repos:   backend, frontend                                   ║
║  PRs:     github.com/org/backend/pull/123                     ║
║           github.com/org/frontend/pull/456                    ║
║  Tests:   All passing                                         ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Error Handling

| Failure | Action |
|---------|--------|
| Bug not in `bugs/` | Print "Run /list-bugs first" and stop |
| Repo not in config | Ask user which repo, wait for answer |
| Repo not cloned | Print: `git clone {git_url} workspace/{repo_name}` and wait |
| Analysis sub-skill fails | status: `FAILED`, preserve partial analysis files |
| git sync fails | status: `FAILED`, error: git output |
| MCP unavailable | Fall back to REST automatically — no status change needed |
| Jira auth fails (both MCP and REST) | status: `BLOCKED`, print which env var is missing |
| JIRA_PROJECT_KEY not resolvable | status: `BLOCKED`, print available keys from integrations.json |
| Branch targets protected branch | Abort — never push to protected branches |
| Branch already exists | Reuse if same base, else fail |
| Worktree already exists | Reuse it |
| Tests fail after 3 retries | status: `BLOCKED`, print test output, wait for human response |
| Data fix required | status: `BLOCKED`, print "Data fix required — please review and reply 'approved' to continue" |
| PR already exists | Use existing PR URL, skip creation, continue |
| gh not authenticated | Print advisory ("run gh auth login"), fall back to Method B (REST) |
| gh not installed | Skip Method A, fall back to Method B (REST) |
| GITHUB_TOKEN missing | status: `BLOCKED`, print: "Set GITHUB_TOKEN or run gh auth login" |
| GITHUB_TOKEN invalid/expired | status: `BLOCKED`, print options: run `gh auth login` (recommended) or set a valid token |

When setting status to `BLOCKED`, append event:
```json
{"timestamp": "...", "event": "BUG_BLOCKED",
 "summary": "Blocked at {step name} — {one-line reason}",
 "error": "{exact error: HTTP status, missing env var name, command output, config key}",
 "action": "{exact human action to resume, e.g. set JIRA_API_TOKEN and re-run /fix-bug {bug_id}}"}
```

When setting status to `FAILED`, append event:
```json
{"timestamp": "...", "event": "BUG_FAILED",
 "summary": "Failed at {step name} — {one-line error}",
 "error": "{exact command that failed + its stderr output, truncated to 20 lines}"}
```

## Events Reference

```
FIX_STARTED
ANALYSIS_DISPATCHED
BACKEND_ANALYSIS_STARTED       (written by bug-analysis-backend)
BACKEND_ANALYSIS_COMPLETE      (written by bug-analysis-backend)
FRONTEND_ANALYSIS_STARTED      (written by bug-analysis-frontend)
FRONTEND_ANALYSIS_COMPLETE     (written by bug-analysis-frontend)
BRANCH_SYNCED
JIRA_TICKET_CREATED
JIRA_TICKET_LINKED
DIAGNOSIS_COMPLETE
DIAGNOSTIC_PRINTED
PLAN_CREATED
JIRA_PLAN_POSTED
BRANCH_CREATED
WORKTREE_CREATED
IMPLEMENTATION_COMPLETE
TESTS_STARTED
TEST_FAILED
TEST_RETRIED
TESTS_PASSED
TESTS_SKIPPED
PR_CREATED
JIRA_UPDATED
JIRA_TRANSITIONED
BUG_COMPLETED
BUG_FAILED
BUG_BLOCKED
```
