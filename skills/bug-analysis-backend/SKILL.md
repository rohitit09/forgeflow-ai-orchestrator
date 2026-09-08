---
description: Deep backend investigation — called automatically by /fix-bug
argument-hint: <bug-id>
---

# Bug Analysis — Backend

Deep investigation of a bug across backend repositories.

**Called by `fix-bug` automatically** after it identifies that one or more `backend`-type repos
are involved. Do NOT invoke this directly unless you are debugging the analysis step.

## What This Skill Does

- Loads pre-built repo context from `repo-context/<repo-id>/`
- Uses that context to target the investigation (entry points, API dirs, model dirs, patterns)
- Scans all `backend`-type repos involved in the bug
- Also reads API contracts / shared types that frontend repos consume
- Writes findings to `bugs/<bug_id>/analysis-backend.md`
- Does NOT create branches, worktrees, or modify any code

## Step 0 — Update Status

At the very start, update `bugs/<bug_id>/status.json`:
- Set `current_step` to `"backend_analysis"`
- Append event: `{"timestamp": "...", "event": "BACKEND_ANALYSIS_STARTED", "repos": [...]}`

Do NOT change the top-level `status` field — that is managed by `fix-bug`.

## Step 1 — Load Repo Context

Before reading any source code, load the pre-built context for each backend repo involved.

For each backend repo ID in the candidate set:

```
repo-context/<repo-id>/context.md      → purpose, entry points, external services, API contract files
repo-context/<repo-id>/structure.json  → entry_points, api_dirs, model_dirs, test_dirs, file_counts
repo-context/<repo-id>/conventions.md → error handling style, base classes, naming rules
repo-context/<repo-id>/patterns.json  → soft_delete, repository_pattern, event_driven, etc.
```

Also read `config/repositories.json` → this repo's entry → `runtime` block:
- `runtime.test_cmd` — referenced in the Fix Recommendation section (do not run it here)
- `runtime.lint_command` — referenced in the Fix Recommendation section (do not run it here)
- `runtime.external_services` — tells you which infrastructure is in play (DB, cache, queues)

Also read this repo's entry in `config/repositories.json` → `dependent_repos` and
`dependency_evidence` — to understand which other services this repo calls and from where.
`dependency_evidence` maps each dependent repo id to the file:line that makes the call;
use this to go directly to the relevant code instead of searching the whole tree.

**If `repo-context/<repo-id>/` does not exist:** warn in the output:
```
WARNING: repo-context/<repo-id>/ not found. Run /repo-context <repo-id> first for faster analysis.
Proceeding with direct scan.
```
Continue with a direct scan of the workspace directory.

## Input

Read from `bugs/<bug_id>/bug.json` and `bugs/<bug_id>/status.json`.

The relevant fields:
- `bug.json` → `title`, `description`, `stack_trace` (if present), `project`
- `status.json` → `repos` (list of confirmed repo IDs for this bug)

Limit analysis to repos where `type == "backend"` plus their `dependent_repos`.

## Output

Write `bugs/<bug_id>/analysis-backend.md` with the following structure.
Use real values for every field — write `unknown` only if genuinely absent, never guess.

```markdown
# Backend Analysis — {bug_id}

> {one-sentence symptom — what a user or operator sees, e.g. "POST /payment/webhook returns HTTP 500 when Razorpay delivers the same event twice"}

**Exception** · `{ExceptionType: message — or "none" for logic bugs}` · **Endpoint** · `{METHOD /path}` · **Frequency** · {N occurrences | first YYYY-MM-DD | last YYYY-MM-DD}

---

## Stack Trace

```
{paste the stack trace verbatim}
```
→ `{library frame}` — {what this frame means}  
→ `{org code frame}` — **crash point** — {why it crashes here}

*(omit section if no stack trace)*

## Entry Point

`{file:line}` — {one phrase: what this code does and how execution enters it}

## Execution Path

1. `{Function.method()}` → {what happens}
2. `{file:line}` → {what happens}
3. `{file:line}` → **`{ErrorType}`** — {why it fails here}

## Root Cause

`{file:line}` — {one or two sentences: what is broken and why it breaks under the conditions described in the bug report}

## Affected Files

| File | Lines | Issue |
|------|-------|-------|
| `{path/to/file.py}` | {line(s)} | {one phrase — what is wrong here} |

## API / Contract Impact

`{none}` — or one sentence describing what public API, schema, or message format changes (read by fix-bug to detect if a frontend fix is also needed)

## Implicated Commits

- `{hash}` · {YYYY-MM-DD} · {author} — {one phrase: why suspicious}

*(omit section if no suspicious commits found)*

## Test Gaps

- `{tests/test_file.py}` — {what coverage is missing}
- Missing: {exact test case that would have caught this bug}

*(omit section if no gaps found)*

## Fix

**REQUIRED:** for every changed line or block, quote the code exactly as it appears in the file.
If multiple hunks change (e.g. 4 logger calls, or 2 separate functions), write one BEFORE/AFTER
block per hunk — never collapse them into a single description.

`{file}:{line}` — {one phrase: what this change does}  
**Before:**
```python
{exact old code copied verbatim from the source — include surrounding context if needed for clarity}
```
**After:**
```python
{exact replacement}
```

*(repeat for each additional hunk in the same file, or for each additional file)*

Verify: `{test command from runtime.test_cmd}`

## Risk

| | |
|--|--|
| **Scope** | {N files, N lines changed} |
| **Regression** | {Low · Medium · High} — {one phrase why} |
| **Downstream** | {none · or describe contract/API impact on dependent repos} |
```

## Investigation Checklist

Work from `workspace/<repo>/` (read-only scan — do not modify files here).

Use the loaded context to focus the search — `structure.json.api_dirs` tells you where routes live,
`structure.json.model_dirs` tells you where models live; start there instead of grepping the whole tree.

1. **Read the stack trace** — identify the innermost frame that is in the org's own code (not a library frame).
   Use `structure.json.entry_points` to orient yourself on how execution enters the app.
2. **Narrow search space using context**:
   - Stack trace hits an API frame? → look in `structure.json.api_dirs` first
   - Stack trace hits a model or ORM frame? → look in `structure.json.model_dirs`
   - Error is async or queue-related? → `patterns.json.event_driven` was `true` — check workers/consumers
3. **Use `dependency_evidence`** from this repo's entry in `config/repositories.json`:
   - Each key is a dependent repo id; the value is the file:line that calls it
   - Go directly to that file instead of searching the whole codebase
4. **Search for the error message**: `grep -r "error text" workspace/<repo>/`
5. **Read the failing function** and its callers up the stack
6. **Apply known patterns from `patterns.json`**:
   - `soft_delete: true` → check if a deleted-record filter is the missing guard
   - `repository_pattern: true` → the data access bug is in a `*Repository` class, not a view
   - `base_model_inheritance: true` → the root cause may be in the shared base class, not a leaf model
7. **Check API route handlers** using `structure.json.api_dirs` paths — look for the route matching
   the stack trace endpoint. Also check `context.md` → **API Contract Files** for OpenAPI/swagger location.
8. **Check recent git history** for the affected files:
   ```bash
   git -C workspace/<repo> log --oneline -20 -- path/to/affected/file.py
   ```
9. **Check external services** from `runtime.external_services` — if postgres/redis/etc. is listed,
   the bug may be a connection or query issue, not application logic.
10. **Check shared interfaces** that frontend repos consume (from `context.md` → API Contract Files).
    Note any breaking changes.
11. **Check test coverage** — use `structure.json.test_dirs` to locate tests:
    ```bash
    pytest --collect-only -q   # (do not run the full suite here — just list what exists)
    ```

## Heartbeat

Backend analysis can be long-running. Update `last_heartbeat` in `bugs/<bug_id>/status.json` at
least every 2 minutes while the investigation is in progress.

## Status Updates

On completion, update `bugs/<bug_id>/status.json`:
- Append event: `{"timestamp": "...", "event": "BACKEND_ANALYSIS_COMPLETE", "output": "bugs/{bug_id}/analysis-backend.md"}`

Do NOT change the top-level `status` field — that is managed by `fix-bug`.
