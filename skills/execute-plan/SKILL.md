---
name: execute-plan
description: Drive a plan produced by /create-plan from approved to completed. Handles both fresh execution and resume — decides which from state.status. Owns pre-flight, worktree provisioning, delivery (PR + Jira). Dispatches the Orchestrator agent to run the DAG loop. Crash-safe end-to-end.
---

# Skill: execute-plan

## 1. Purpose

Single skill, two entrypoints:

- `/execute-plan <plan-id>` — start a fresh run.
- `/resume-plan <plan-id>` — pick up where a crashed / blocked / interrupted run left off.

The skill reads `state.status` and decides **fresh flow** vs **resume flow** itself. The commands are thin wrappers; they do not branch — they just invoke this skill.

Layers:

| Layer | Owns |
|---|---|
| This skill | **Pre-flight** (branch, worktrees, provisioning), **resume reconciliation** (from disk + git), **delivery** (PR push, `gh pr create`, Jira comment), **the final report**. |
| `agents/orchestrator.md` | **The DAG loop only** — READY scan, specialist dispatch, per-task commits, persist BEFORE and AFTER every transition, autonomous failure routing. Marks `state.status = "delivery_pending"` when every task lands and returns. Never touches PR or Jira. |

Crash safety comes from the orchestrator's Persistence contract (`agents/orchestrator.md`) and this skill's atomic-rename writes for its own persistence points.

## 2. When invoked

Only by `/execute-plan <plan-id>` or `/resume-plan <plan-id>`. Nothing else calls this skill.

## 3. Inputs

- `<plan-id>` — directory name under `plans/`.

The invoking command (`/execute-plan` or `/resume-plan`) is not passed and does not matter — `state.status` on disk decides the mode. That way the commands stay pure shells and a mistaken `/resume-plan` on a fresh plan just proceeds as fresh, without a fragile "wrong command" branch.

## 4. Files read

- `plans/<plan-id>/plan.json` — task DAG (schema in `commands/create-plan.md`), immutable spec
- `plans/<plan-id>/state.json` — durable truth (the skill's decisions come from here)
- `plans/<plan-id>/worktrees/<repo>/` — via `git log` during resume reconciliation
- `config/repositories.json` — per-repo `path`, `base_branch`, `feature_merge_dest_branch`, `protected_branches`, `runtime.test_cmd`, `git_url`; plus top-level `branch_naming` and `commit_message` templates
- `config/integrations.json` — Jira base URL, project map, credentials
- `repo-context/<repo>/testing.md` — provisioning install command (optional)

`events.jsonl` is written but never read — every decision comes from `state.json`.

## 5. Files written

- `plans/<plan-id>/state.json` — pre-flight, reconciliation, and delivery transitions (atomic-rename via `mv -f`)
- `plans/<plan-id>/events.jsonl` — append-only
- `plans/<plan-id>/worktrees/<repo>/` — created / re-cut / provisioned
- `plans/<plan-id>/execution_summary.json` — structured execution result for UI (written at Step 5c)
- `plans/<plan-id>/execution_summary.md` — human-readable execution summary (written at Step 5c)

The orchestrator writes `state.json`, `events.jsonl`, and specialist agents' work commits — this skill writes pre-flight, reconciliation, and delivery.

## 6. state.json — full schema (shared with the orchestrator)

Seeded by `/create-plan` with `plan_id`, `status: approved`, timestamps, `current_tasks: []`, `blocked_by: {}`. Extended in place. Note the **notation**: expressions like `config.repositories[<id>].base_branch` are shorthand for "find the entry in `config.repositories` array where `id` equals the value, then read `base_branch`". The config's `repositories` field is an array, not a dict — every lookup is a find, not a key access.

```json
{
  "plan_id": "<plan-id>",
  "status": "approved | running | delivery_pending | completed | blocked | failed",
  "created_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",
  "started_at": "<ISO 8601 | null>",
  "finished_at": "<ISO 8601 | null>",
  "branch": "<resolved once, reused across repos>",
  "worktrees":    { "<repo>": "plans/<plan-id>/worktrees/<repo>" },
  "provisioning":       { "<repo>": "provisioned | partial | skipped" },
  "provisioning_notes": { "<repo>": "error output when result is partial" },
  "task_states":  { "<task-id>": "pending | in_progress | completed | failed | skipped" },
  "task_results": { "<task-id>": { "status": "...", "agent": "...", "finished_at": "...",
                                    "summary": "...", "commit_sha": "...", "files_changed": [...],
                                    "blockers": "...", "failure_kind": "code | environment | null",
                                    "recovered": true } },
  "attempts":     { "<task-id>": 0 },
  "fix_cycles":   { "<origin-task-id>": 0 },
  "adhoc_tasks":  { "<task-id>": { /* full task schema — debug, fix, retest, rereview */ } },
  "current_tasks": [],
  "blocked_by":    { "<blocked-task-id>": "<blocking-failed-task-id>" },
  "prs":           { "<repo>": "<PR URL>" },
  "jira_updated":  ["<KEY>"],
  "stop_reason":   null,
  "stop_task_id":  null
}
```

`delivery_pending` is the intermediate state the orchestrator sets when every task landed but PR + Jira are still owed. This skill picks it up in Step 5.

**Write rules — applies to every `state.json` mutation in this skill:**
1. Atomic-rename: read → mutate in memory → write to `state.json.tmp` → `mv -f state.json.tmp state.json`. Never write in place.
2. Set `state.updated_at = <ISO now>` on every mutation before writing. The step text below may not repeat this every time — the rule stands globally.
3. Emit the corresponding event to `events.jsonl` after the state write, with `ts`, `event`, and `plan_id` at minimum.

`events.jsonl` is append-only. See the orchestrator's Persistence contract for the loop-side equivalent.

---

## 7. Workflow

### Step 1 — Load & mode decision

Read `plan.json` and `state.json` from disk. If either is missing or unparseable, stop and print exactly what's wrong. Never reconstruct from memory. `events.jsonl` is append-only history — this skill writes to it but never reads it for decisions; every decision comes from `state.json`. Also capture `<project-root>` once with `pwd` — every path computation below uses it.

Decide mode from `state.status`:

| `state.status`         | Mode        | Next |
|------------------------|-------------|---|
| `approved`             | **Fresh**   | Step 2 (pre-flight) → Step 4 → Step 5 |
| `running`              | **Resume**  | Previous run crashed mid-loop. Step 3 (reconcile) → Step 4 → Step 5 |
| `blocked`              | **Resume**  | Previous safe-stop. Step 3, gated on the user having fixed the blocker (Step 3a) |
| `delivery_pending`     | **Resume**  | Loop completed, delivery didn't. Skip Steps 2–4, go straight to Step 5 |
| `completed`            | Exit        | Say so and stop |
| `failed`               | Exit        | Not automatically resumable — print `stop_reason`, exit |

For **Fresh** mode only, before Step 2:
- If `plan.repos` is empty (greenfield), halt with the message `/create-plan` prints on completion — do not create anything.
- If any `repo.name` doesn't resolve to an entry in `config/repositories.json` by `id`, halt and say which.
- Structural sanity: every `task.depends_on` id must exist in `plan.tasks`; every `task.repo` must exist in `plan.repos`; every task must have non-empty `files_touched`. On any violation, halt and print the offending task id + field.
- **Jira gate.** Check `plan.delivery.jira_tickets`. If empty, prompt the user once:
  ```
  Plan <plan-id> has no Jira key attached. Provide one to link the branch and commits, or press Enter to skip.
  Jira key (e.g. JAR-1234) [skip]:
  ```
  - If they enter a key: write it back to `plan.json` under `plan.delivery.jira_tickets = ["<KEY>"]` (atomic-rename), then persist. This is the only mutation this skill makes to `plan.json` — the plan gains a Jira key it was created without. Append `{"ts": "<ISO>", "event": "jira_bound", "plan_id": "<plan-id>", "jira_key": "<KEY>", "source": "prompt"}` to `events.jsonl`.
  - If they skip: proceed with the no-jira branch fallback in Step 2a. Do not prompt again on resume.
- Transition `state.status = "running"`, `state.started_at = now`, persist. Append `{"ts": "<ISO>", "event": "execution_started", "plan_id": "<plan-id>"}` to `events.jsonl`.

**All events written by this skill include a `ts` field** (ISO 8601, e.g. `2026-08-26T14:32:01Z`). Same convention as the orchestrator's events — see `agents/orchestrator.md`.

For **Resume** mode only:
- Do not re-prompt for Jira. If `plan.delivery.jira_tickets` was empty at first run and the user skipped, the branch is already `feature-<plan-id>` on disk — a new Jira key can't retroactively change it.
- Append `{"ts": "<ISO>", "event": "execution_resumed", "plan_id": "<plan-id>"}` to `events.jsonl`.

### Step 2 — Fresh pre-flight (Fresh mode only)

**2a. Resolve feature branch from config.**

Templates come from `config/repositories.json.branch_naming`. Never hardcode the format in this skill — read it fresh each time so the config stays authoritative.

- If `plan.delivery.jira_tickets[0]` is set → template `branch_naming.feature_with_jira` with `{jira_key} = plan.delivery.jira_tickets[0]` and `{description} = <title-slug>`.
- Else → template `branch_naming.feature_no_jira` with `{plan_id} = <plan-id>`.

`<title-slug>` = kebab-case of `plan.title` (2–5 words, lowercase, spaces and punctuation → `-`). Never re-prefix the plan's date.

Applied to the default config, that produces:
- with Jira: `feature-JAR-1234-add-driver-tracking`
- without Jira: `feature-20260826-add-driver-tracking` (plan_id already carries the date + slug)

For every repo in `plan.repos`: find the entry in `config.repositories` where `id == repo.name`, read its `protected_branches`. If the resolved branch matches any of them, set `state.status = "failed"`, `state.stop_reason = "branch_collision"`, persist, exit.

Persist `state.branch`. Emit `{"ts": "<ISO>", "event": "branch_resolved", "plan_id": "<plan-id>", "branch": "<state.branch>", "jira_key": "<key or null>"}`.

**2b. Per repo: sync base clone → then worktree → then feature branch.**

Each repo has its own independent workspace clone (`workspace/<repo>/`). The within-repo sequence (steps 1–5 below) must remain strict — worktree is only safe to cut once that repo's clone is cleanly synced. But **different repos share no state and must be processed concurrently**; running them one at a time is the same scheduling gap that caused task-007 to start 36 minutes late in the DAG.

**Concurrency model for this step:**
- Fire all repos' sequences in parallel (background processes or parallel tool calls, one per repo).
- Each repo independently runs steps 1–5 in order.
- **On `workspace_dirty` or `base_branch_diverged` in any repo:** halt, set `state.status = "blocked"`, `state.stop_reason = <reason>`, persist, exit — do not proceed with other repos.
- **State.json writes are serialized, not concurrent.** After each repo's full sequence (steps 1–5) finishes, do one atomic read-modify-write to add that repo's `state.worktrees` and `state.provisioning` entries. Never attempt two simultaneous writes — the last writer wins and the earlier write is lost. Emit per-repo events (`worktree_created`, `worktree_provisioned`) immediately after each repo's write lands.

Find the repo's entry in `config.repositories` (where `id == repo.name`) and read its `path` (e.g. `workspace/hawkeye`), `git_url`, `base_branch`. Call the resolved path `<path>` for the steps below.

1. **Ensure the base clone exists.** If `<path>` is not a git repo: create the parent (`mkdir -p "$(dirname <path>)"`), then `git clone <git_url> <path>`. Otherwise proceed.

2. **Checkout the base branch on the workspace clone.**
   ```
   git -C <path> fetch origin --prune
   git -C <path> checkout <base_branch>
   ```
   If the workspace clone has uncommitted local changes on another branch, checkout will fail — do not `stash` or `checkout -f`; set `state.status = "blocked"`, `state.stop_reason = "workspace_dirty"`, persist, exit. The user resolves their local state first.

3. **Sync the base branch.**
   ```
   git -C <path> pull --ff-only origin <base_branch>
   ```
   Not fast-forward → set `state.status = "blocked"`, `state.stop_reason = "base_branch_diverged"`, persist, exit. Never force.

4. **Cut the worktree AND create the feature branch in one atomic operation.**

   Assume this skill is invoked from the project root (the directory containing `plans/`, `workspace/`, `config/`, `agents/`). Compute `WT_PATH = "<project-root>/plans/<plan-id>/worktrees/<repo.name>"` — capture `<project-root>` with `pwd` once at Step 1 and reuse; do not recompute inside subshells.

   Check whether the local branch already exists (a previous run may have created it before crashing at a later sub-step):
   ```
   git -C <path> show-ref --verify --quiet refs/heads/<state.branch>
   ```
   - **Exit 0** (branch exists) → attach the worktree to it without `-b`:
     ```
     git -C <path> worktree add <WT_PATH> <state.branch>
     ```
   - **Exit non-zero** (branch does not exist) → cut worktree AND create branch atomically:
     ```
     git -C <path> worktree add <WT_PATH> -b <state.branch> origin/<base_branch>
     ```
     `git worktree add -b` atomically creates the branch off `origin/<base_branch>` at the moment the worktree is cut, so a crash between "cut worktree" and "create branch" is not possible.

   Record the **project-root-relative** path in `state.worktrees[<repo>] = "plans/<plan-id>/worktrees/<repo.name>"` (not the absolute `WT_PATH` — storing relative keeps `state.json` portable if the project is moved). Every subsequent `git -C` call resolves it by running from the project-root cwd. Persist, emit `{"ts": "<ISO>", "event": "worktree_created", "plan_id": "<plan-id>", "repo": "<repo>", "path": "plans/<plan-id>/worktrees/<repo.name>", "branch": "<state.branch>", "base": "<base_branch>"}`.

5. **Provision the worktree.**
   - **Dependencies**: look for an `install:` line in `repo-context/<repo>/testing.md` (convention: a fenced code block or explicit "Install: `<command>`" line — the `/repo-context` skill produces this). If found, run it with cwd set to the worktree (`bash -c "<cmd>"` from `<WT_PATH>`). Otherwise skip — never guess a package manager.
   - **Env files**: if `workspace/env/<repo>/` exists, copy its contents into the worktree root, preserving relative paths (`cp -R workspace/env/<repo>/. <WT_PATH>/`). Never invent secrets.
   - Record `state.provisioning[<repo>]`:
     - `"provisioned"` — install command ran clean AND env files were copied (or one of the two was skipped for a legitimate reason: no `install:` line, or no `workspace/env/<repo>/` dir).
     - `"partial"` — one step ran and the other failed. Include the error output under `state.provisioning_notes[<repo>]`.
     - `"skipped"` — both steps had nothing to do. Not an error.
   - Persist. Emit `{"ts": "<ISO>", "event": "worktree_provisioned", "plan_id": "<plan-id>", "repo": "<repo>", "result": "<provisioned|partial|skipped>"}`.

Provisioning failure is **not** a plan failure — continue. The orchestrator passes the value to specialists so they know what they can honestly verify.

**Never** cut a worktree from a base clone that has not just completed steps 2 and 3 for this repo in this run. Skipping the sync is the single most common cause of "my agent worked off stale code and the merge fails" — the whole point of pre-flight is that every worktree starts from a freshly-pulled `origin/<base_branch>`.

### Step 3 — Resume reconciliation (Resume mode only)

**3a. Confirm blocker resolution when resuming from `blocked`.**

If `state.status` was `blocked`, inspect `state.stop_reason`:

- `environment_not_provisioned` → identify the repo. Look up `state.stop_task_id` in `plan.tasks` (or `state.adhoc_tasks` if it's an ad-hoc id) and read its `repo` field. If `stop_task_id` is null (defensive), fall back to parsing the failed task's `blockers` text from `state.task_results`. Ask the user to confirm the fix is in place under `workspace/env/<repo>/` and/or dependencies are installed. On `yes`: **re-run provisioning** (Step 2b sub-step 5 — install + env-copy) for the affected repo, update `state.provisioning[<repo>]`, emit a fresh `worktree_provisioned` event. If the re-provisioning result is still `partial` (with an error under `state.provisioning_notes[<repo>]`) or `skipped` with the same missing piece, keep `state.status = "blocked"` with a new stop_reason `environment_still_missing` and exit — a claim isn't a check; the provisioning re-run is what determines whether the environment actually works now. If it comes back `provisioned`, clear `state.stop_reason`, `state.stop_task_id`, and delete `state.provisioning_notes[<repo>]` (stale error text from the previous failed attempt would confuse future readers); then proceed to Step 3b.
- `environment_still_missing` → same handling as `environment_not_provisioned` above. The user has had another chance to fix the workspace since the previous re-provisioning attempt.
- `attempt_limit_reached`, `unresolvable_failure`, `no_ready_work` → the offending task is `state.stop_task_id` (for `no_ready_work` it may be null; then enumerate the blocked survivors from `state.blocked_by` and ask which to act on). Ask what the user wants: `retry` (reset that task to `pending`, decrement its `state.attempts` by 1 down to a floor of 0, clear `state.fix_cycles` for its `origin_task`, proceed), `skip` (mark it `skipped`, proceed), `abort` (exit). No other options.
- `workspace_dirty` or `base_branch_diverged` (pre-flight errors — no worktree was cut for the affected repo yet, no `stop_task_id`) → tell the user exactly what to fix on the workspace clone (`git status`/`git stash`/`git reset` at the workspace path; or `git pull` to resync). Ask for confirmation. On `yes`: clear `state.stop_reason`, re-run **Step 2b** (sync + worktree + provision) for **every repo in `plan.repos`** — not only repos missing a worktree. In concurrent pre-flight, some repos may have had their worktrees cut before the failure was detected; their base clones still need the sync steps (fetch + checkout + pull) to pick up any commits that landed on `origin/<base_branch>` since the halt. For repos whose worktree path already exists on the correct branch, skip only the worktree-cut sub-step (Step 2b step 4) — still run the sync (steps 1–3) and re-provisioning (step 5). Step 2a is not re-run — `state.branch` is already resolved. Once all worktrees exist and are synced, drop into Step 3b for any in-flight residuals.
- `unknown_task_type` → the plan has a task whose `type` maps to no specialist. Tell the user to fix `plan.json`, exit.
- **Any other `stop_reason`** (unknown to this table — a future orchestrator version added a reason we don't recognise): print the raw `stop_reason`, `stop_task_id`, `blocked_by`, and the `blockers` text from the offending task's `task_results`. Ask the user to fix the underlying issue and re-run resume; do not proceed automatically.

`branch_collision` never appears here because it sets `state.status = "failed"` (not `blocked`), so Step 1's mode table exits at the top. That plan is not resumable — the user must create a new plan with a different title.

**3b. Reconcile `in_progress` tasks against git.**

`git log --grep` is read-only. All `in_progress` tasks can be inspected concurrently — run all git checks in parallel, then serialize the state.json writes as each result arrives.

**Concurrency model for this step:**
- Fire all `git log --all --grep="(<task-id>)" --format='%H %s' -n 5` commands simultaneously (parallel tool calls or background processes), one per `in_progress` task.
- As each result arrives, immediately process it and do one atomic read-modify-write to `state.json` for that task — do not wait for all checks to finish before writing. Recording each recovery/reset as it lands means a crash mid-3b only loses the tasks not yet written, not all of them.

For every task where `state.task_states[<id>] == "in_progress"`:

1. Look up its worktree: for the task's `repo` (find it in `plan.tasks[<id>].repo` or `state.adhoc_tasks[<id>].repo`), read `state.worktrees[<repo>]`. Missing on disk → will be re-cut in 3c; leave state as-is for this task, it will be reset once the worktree returns.
2. Inspect git inside the worktree (run in parallel with all other in_progress tasks):
   ```
   git log --all --grep="(<task-id>)" --format='%H %s' -n 5
   ```
   - **A commit landed** → the specialist finished; state didn't get written before the crash. Reconstruct:
     - `state.task_states[<id>] = "completed"`
     - `state.task_results[<id>] = { status: "success", agent: <inferred from task.type>, finished_at: <commit date>, summary: <commit subject minus (task-id)>, commit_sha: <hash>, files_changed: [<git show --name-only>], blockers: null, failure_kind: null, recovered: true }`
     - Remove `<id>` from `state.current_tasks`.
     - Append `{"ts": "<ISO>", "event": "task_recovered", "plan_id": "<plan-id>", "task_id": "<id>", "commit_sha": "<hash>"}`.
   - **No commit** → the specialist was dispatched (attempts was incremented before dispatch, per orchestrator's Persistence contract) but never returned or its return wasn't persisted. Treat as awaiting re-dispatch:
     - `state.task_states[<id>] = "pending"`
     - Remove `<id>` from `state.current_tasks`.
     - Leave `state.attempts[<id>]` **unchanged** — the dispatch already burned a slot; on the next scan the orchestrator will re-dispatch and bump attempts again. A permanently-crashing task eventually hits `attempts >= 3` and safe-stops (see orchestrator's attempt-limit rule).
     - Append `{"ts": "<ISO>", "event": "task_reset", "plan_id": "<plan-id>", "task_id": "<id>", "reason": "no completion event"}`.
     - Any uncommitted changes for the task's `files_touched` stay in the worktree — the re-dispatched developer sees them and reconciles (per developer agent's "Before Writing Code" step 4).

Persist `state.json` after each reconciled task — one atomic write per task, not batched. Serialized writes, parallel reads.

**3c. Verify worktrees on disk.**

Worktree validity checks are read-only. Run all repos' checks in parallel; re-cut invalid worktrees concurrently (following Step 2b's concurrency model — each repo's re-cut is independent).

**Concurrency model for this step:**
- Fire all validity checks simultaneously (parallel tool calls or background processes), one per repo: `directory exists` + `git -C <path> status` + `git -C <path> symbolic-ref --short HEAD`.
- Collect results. Split repos into two groups: **valid** (reuse) and **invalid** (re-cut).
- Emit `worktree_recovered result:reused` events for valid repos immediately.
- For invalid repos: run all re-cuts concurrently (same model as Step 2b — each repo's full sync+worktree+provision sequence in parallel, state.json writes serialized as each finishes).

For each repo in `plan.repos`:
- Check the path in `state.worktrees[<repo>]`. It's valid when: the directory exists, `git -C <path> status` exits 0, AND `git -C <path> symbolic-ref --short HEAD` returns `<state.branch>`. All three must hold — a worktree on the wrong branch is not reusable; a `git status` success only proves it's a git dir.
- Valid → reuse. Emit `{"ts": "<ISO>", "event": "worktree_recovered", "plan_id": "<plan-id>", "repo": "<repo>", "result": "reused"}`.
- Not valid (missing, wrong branch, git broken) → re-run the Step 2b sequence for this repo only (sync base clone, `git worktree add`, provision). Emit `{"ts": "<ISO>", "event": "worktree_recovered", "plan_id": "<plan-id>", "repo": "<repo>", "result": "recut"}`.

**3d. Reset transient state.**

- `state.status = "running"`, `state.updated_at = now`, persist.
- Clear `state.current_tasks` if any residuals remain.
- If `state.stop_reason` was set for a resumable reason, clear it.

### Step 4 — Dispatch the Orchestrator

Dispatch the `orchestrator` agent via the Task tool, once. Pass:

- `plan_id`
- The paths `plans/<plan-id>/plan.json`, `plans/<plan-id>/state.json`, `plans/<plan-id>/events.jsonl`
- Confirmation that `state.branch`, `state.worktrees`, `state.provisioning` are populated on disk
- The instruction to follow `agents/orchestrator.md` verbatim

Do not run the loop in this session. Do not dispatch a second orchestrator concurrently — two drivers writing `state.json` lose each other's updates.

The orchestrator returns one final report. Possible orchestrator terminal states:

- `state.status = "delivery_pending"` → every task landed; delivery still owed. Go to Step 5.
- `state.status = "blocked"` → safe-stop; delivery not owed. Go to Step 6 (surface the report). The orchestrator never sets `failed` — that's this skill's pre-flight-only outcome (`branch_collision`).
- Orchestrator returned nothing / truncated / died mid-loop → re-read `state.json` from disk, report last persisted status, tell the user to run `/resume-plan <plan-id>`. Go to Step 6.

### Step 5 — Delivery (only when `state.status == "delivery_pending"`)

**5a. PR per repo.** Push and PR creation are independent across repos — run them concurrently. Do not wait for repo A's PR before pushing repo B.

**Concurrency model for this step:**
1. **Commit-count check** (parallel, all repos at once): for each repo, check `git -C <WT> rev-list --count origin/<BASE>..HEAD`. Repos with zero commits are skipped; repos already in `state.prs` are skipped. Collect the list of repos that need pushing.
2. **Push** (parallel, all qualifying repos at once): fire `git push` for every repo that needs a PR. Each push is a separate remote and does not affect the others.
3. **PR creation** (parallel, all pushed repos at once): after all pushes land, fire `gh pr create` for each repo in a single batch response. PR creation for repo A does not depend on repo B.
4. **State.json writes are serialized**: as each PR URL returns, do an atomic read-modify-write to record `state.prs[<repo>] = <URL>` and emit the `pr_opened` event. Do not batch PR URLs into a single write — record each as it arrives so a crash mid-delivery leaves the already-created PRs recorded and idempotently skipped on resume.

For each repo in `plan.repos`. Let `WT = state.worktrees[<repo>]` (an absolute or project-root-relative path) and `BASE = config.repositories[<repo>].feature_merge_dest_branch ?? config.repositories[<repo>].base_branch` — use `feature_merge_dest_branch` if set, fall back to `base_branch`.

Check whether this repo has anything to push:
```
git -C <WT> rev-list --count origin/<BASE>..HEAD
```
Zero commits → skip this repo (nothing to PR). Non-zero → proceed.

If `state.prs[<repo>]` is already set from a previous run (delivery restarted after a crash mid-push): skip that repo, its PR already exists.

Otherwise:
```
git -C <WT> push -u origin <state.branch>
```

**gh auth check — run once before any `gh pr create` call.** `GITHUB_TOKEN` in the environment overrides keyring credentials and may be stale:
```bash
GH_STATUS=$(gh auth status 2>&1)
if echo "$GH_STATUS" | grep -q "Failed to log in.*GITHUB_TOKEN"; then
  unset GITHUB_TOKEN
  GH_STATUS=$(gh auth status 2>&1)
fi
GH_READY=$(echo "$GH_STATUS" | grep -q "Logged in" && echo yes || echo no)
```

**PR body** (build inline — no scratch file per repo):
```
## Summary
<plan.context.problem>

## Success criteria
- [ ] <criterion 1>

## Tasks (this repo)
| ID | Task | Status |
|----|------|--------|
| task-001 | <title> | completed |

## Plan
plans/<plan-id>/plan.md

<if plan.delivery.jira_tickets non-empty: "Closes <KEY>">
```
Task table lists tasks whose `repo == <repo>` — one PR per repo. Include plan and ad-hoc tasks; note failed/skipped rows as such.

**Detect GitHub vs non-GitHub.** Check `config.repositories[<repo>].git_url`:
- Contains `github.com` → GitHub repo → proceed with `gh pr create` and REST fallback below. Derive `OWNER_REPO`:
  - SSH `git@github.com:Org/repo.git` → `Org/repo`
  - HTTPS `https://github.com/Org/repo.git` → `Org/repo`
- Does **not** contain `github.com` (AWS CodeCommit, Bitbucket, GitLab, internal git, etc.) → push only; record `state.prs[<repo>] = null`; print "Non-GitHub remote for `<repo>` — open PR via that platform's console"; add the manual push command to `manual_pr_commands[<repo>]` in the execution summary. Skip all `gh` and REST API calls for this repo.

**Attempt 1 — `gh` CLI** (when `GH_READY == yes`):
```bash
PR_URL=$(gh -R <OWNER_REPO> pr create \
  --base <BASE> --head <state.branch> \
  --title "<plan.title> <jira_key>" \
  --body "<PR body>" 2>&1)
```
If the output starts with `https://`, it succeeded. Record and continue.

**Attempt 2 — REST API fallback** (when `gh` fails or `GH_READY == no`):
```bash
TOKEN=$(gh auth token 2>/dev/null)
[ -z "$TOKEN" ] && TOKEN=$(python3 -c "
import json, os
cfg = json.load(open('config/integrations.json'))
val = cfg['github']['token']
print(os.environ.get(val.strip('\${}'), '') if val.startswith('\${') else val)
")
if [ -z "$TOKEN" ]; then
  echo "⚠ No GitHub token available for <repo> — manual PR command:"
  echo "  gh pr create --repo <OWNER_REPO> --base <BASE> --head <state.branch> --title \"<title>\" --body \"<PR body>\""
  PR_URL=""
else
  PR_URL=$(curl -s -X POST \
    -H "Authorization: token $TOKEN" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/<OWNER_REPO>/pulls" \
    -d "{\"title\":\"<plan.title> <jira_key>\",\"body\":\"<PR body>\",\"head\":\"<state.branch>\",\"base\":\"<BASE>\"}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('html_url',''))")
fi
```

If both attempts fail or TOKEN was empty: warn in the final report, populate `manual_pr_commands[<repo>]` in the execution summary with the exact `gh pr create` command for manual execution — do not fail the plan. PR failure is non-fatal at delivery.

Record `state.prs[<repo>] = <returned URL>`, persist, emit `{"ts": "<ISO>", "event": "pr_opened", "plan_id": "<plan-id>", "repo": "<repo>", "url": "<url>"}`.

**5b. Jira comment (skip if `plan.delivery.jira_tickets` empty).**

For each key not already in `state.jira_updated`: post a comment listing the PR URLs. Try MCP first (`mcp__atlassian__create_comment` with an ADF body). Fall back to REST (`POST /rest/api/3/issue/{key}/comment`, ADF body, credentials from `config/integrations.json`). On success, append the key to `state.jira_updated`, persist, emit `{"ts": "<ISO>", "event": "jira_updated", "plan_id": "<plan-id>", "jira_key": "<KEY>"}`. On failure: warn, continue. Never fail the plan on Jira failure.

**5c. Mark complete.** `state.status = "completed"`, `state.finished_at = now`, persist. Emit `{"ts": "<ISO>", "event": "execution_completed", "plan_id": "<plan-id>"}`.

**Write execution summary files.** These are the UI data source — the FleetView dashboard reads `execution_summary.json` to display plan status, links, and task outcomes.

Write `plans/<plan-id>/execution_summary.json`:
```json
{
  "plan_id": "<plan-id>",
  "title": "<plan.title>",
  "plan_status": "<state.status>",
  "branch": "<state.branch>",
  "started_at": "<state.started_at>",
  "finished_at": "<state.finished_at or null>",
  "duration_minutes": "<(finished_at - started_at) in minutes, rounded to 1 decimal, or null if not yet finished>",
  "jira_key": "<plan.delivery.jira_tickets[0] or null>",
  "jira_url": "<config.integrations.jira.base_url>/browse/<jira_key> or null",
  "prs": { "<repo>": "<state.prs[repo] or null>" },
  "manual_pr_commands": {
    "<repo>": "<full gh pr create command string, for repos where PR creation failed or was skipped (CodeCommit/non-GitHub)>"
  },
  "failed_tasks": "<count of tasks where status == 'failed' across plan.tasks + adhoc_tasks>",
  "resumable": "<true if plan_status == 'blocked', false if 'completed'>",
  "stop_reason": "<state.stop_reason or null>",
  "stop_task_id": "<state.stop_task_id or null>",
  "repos": [
    {
      "name": "<repo>",
      "kind": "<plan.repos[repo].kind>",
      "base_branch": "<config.repositories[repo].base_branch>",
      "pr_url": "<state.prs[repo] or null>",
      "task_count": "<n>",
      "completed": "<n>",
      "failed": "<n>",
      "skipped": "<n>"
    }
  ],
  "tasks": [
    {
      "id": "<task-id>",
      "title": "<task.title>",
      "repo": "<task.repo>",
      "type": "<task.type>",
      "status": "<completed|failed|skipped|in_progress|pending>",
      "agent": "<state.task_results[id].agent or null>",
      "commit_sha": "<state.task_results[id].commit_sha or null>",
      "summary": "<state.task_results[id].summary or null>",
      "files_changed": ["<path>"]
    }
  ],
  "adhoc_tasks": [ /* same shape, for debug/fix/retest/rereview tasks */ ]
}
```
Include both `plan.tasks` and `state.adhoc_tasks` in the `tasks` and `adhoc_tasks` arrays respectively. Populate from `state.task_results`. Set `jira_url` to `null` when no Jira key exists. Omit repos from `manual_pr_commands` where the PR was created successfully.

Write `plans/<plan-id>/execution_summary.md` — human-readable version of the same data:
```markdown
# Execution Summary: <plan.title>

**Plan**: <plan-id>  
**Status**: completed *(or "blocked — <stop_reason>")*  
**Branch**: `<state.branch>`  
**Jira**: [<jira_key>](<jira_url>) *(or "none")*  
**Started**: <started_at> · **Finished**: <finished_at> · **Duration**: <duration_minutes> min

## Pull Requests
| Repo | Kind | PR | Base |
|---|---|---|---|
| everest_jarvis | backend | [#1234](<url>) | staging |
*(for non-GitHub repos: "*(CodeCommit — open via platform console)*")*
*(for failed PR creation: print the manual command)*

## Tasks
| ID | Repo | Title | Status | Agent | Commit |
|---|---|---|---|---|---|
| task-001 | everest_jarvis | Create scheduler app | completed | backend-developer | `e24a71c` |

## Ad-hoc Tasks
*(same table — debug, fix, retest, rereview tasks)*

## Post-Merge Steps
*(if any — ordered list of manual steps required after the PRs are merged)*
```

### Step 6 — Surface the report

**Write execution summary files** (for all terminal states — `completed`, `blocked`, and orchestrator-died). Use the same schema as Step 5c but with fields reflecting current state:
- For `blocked`: `plan_status: "blocked"`, `resumable: true`, `finished_at: null`, `duration_minutes: null`, `stop_reason` and `stop_task_id` from `state`; include tasks in whatever state they are (some may be `in_progress`, `pending`, or `completed`)
- For `completed`: same as Step 5c (already written there — do not re-write if Step 5c already ran)
- For orchestrator-died: `plan_status` = last persisted value from `state.json`, all task statuses as they are on disk

Always write both `execution_summary.json` and `execution_summary.md` before printing — the UI reads these files even when the plan is blocked or incomplete.

Print:

- **Completed** — task counts, PR URLs per repo (or "PR command printed above" if `gh` failed), Jira keys updated.
- **Blocked / failed** — `state.stop_reason`, `state.stop_task_id`, `state.blocked_by`, and the fix needed. For `environment_not_provisioned` / `environment_still_missing`: name the repo, the missing piece (from `state.task_results[<stop_task_id>].blockers`), and point at `workspace/env/<repo>/` for env files or `repo-context/<repo>/testing.md` for the install command. Suggest `/resume-plan <plan-id>` once the blocker is resolved.
- **Orchestrator died / returned nothing** — re-read `state.json`, report the last persisted status verbatim, tell the user `/resume-plan <plan-id>`.

---

## 8. Rules

- One skill, two flows — `state.status` on disk decides the mode; the invoking command name is not consulted.
- Never dispatch a second orchestrator concurrently.
- Never write outside the skill's scope (pre-flight, reconciliation, delivery) — task-level writes belong to the orchestrator.
- Never `git worktree add` on a branch matching `protected_branches`.
- Never rewrite `state.json` on resume beyond what disk + git observably support.
- Never decrement `state.attempts[<id>]` automatically — only via the explicit user `retry` in Step 3a, and only by 1 (floor 0), targeting `state.stop_task_id`.
- Never overwrite an existing PR — `state.prs[<repo>]` gates re-creation.
- All `state.json` writes atomic-rename; `events.jsonl` append-only.
- PR failure and Jira failure are non-fatal at delivery — warn and continue.
- Never delete a worktree; only re-cut a missing one.

**Stop reasons this skill sets** (in addition to the ones the orchestrator sets):

| stop_reason                    | Set by | Trigger                                                                       |
|--------------------------------|--------|-------------------------------------------------------------------------------|
| `branch_collision`             | Step 2a | resolved branch matches a repo's `protected_branches` (state → `failed`)     |
| `workspace_dirty`              | Step 2b | workspace clone had uncommitted changes on another branch (state → `blocked`) |
| `base_branch_diverged`         | Step 2b | `git pull --ff-only` failed (state → `blocked`)                              |
| `environment_still_missing`    | Step 3a | user confirmed the env fix but re-provisioning still returned partial/skipped |

## 9. Output

Terse status per transition (pre-flight / reconciliation / delivery), then the orchestrator's final report. On resume, prefix reconciliation lines with what disk revealed (`recovered from <sha>` / `reset to pending` / `worktree recut`).
