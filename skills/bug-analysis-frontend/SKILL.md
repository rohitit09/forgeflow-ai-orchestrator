---
description: Deep frontend/mobile investigation — called automatically by /fix-bug
argument-hint: <bug-id>
---

# Bug Analysis — Frontend

Deep investigation of a bug across frontend/mobile repositories.

**Called by `fix-bug` automatically** after it identifies that one or more `frontend`-type repos
are involved. Do NOT invoke this directly unless you are debugging the analysis step.

## What This Skill Does

- Loads pre-built repo context from `repo-context/<repo-id>/` for each involved frontend repo
- Also loads context for each dependent backend repo to check API contracts
- Scans frontend repos for the bug with context-guided targeting
- Cross-references the API contracts / interfaces exposed by dependent backend repos
- Writes findings to `bugs/<bug_id>/analysis-frontend.md`
- Does NOT create branches, worktrees, or modify any code

## Step 0 — Update Status

At the very start, update `bugs/<bug_id>/status.json`:
- Set `current_step` to `"frontend_analysis"`
- Append event: `{"timestamp": "...", "event": "FRONTEND_ANALYSIS_STARTED", "repos": [...]}`

Do NOT change the top-level `status` field — that is managed by `fix-bug`.

## Step 1 — Load Repo Context

Before reading any source code, load the pre-built context for all involved repos.

**For each frontend repo in the candidate set:**
```
repo-context/<repo-id>/context.md      → purpose, entry points, external services
repo-context/<repo-id>/structure.json  → entry_points, api_dirs, test_dirs, file_counts
repo-context/<repo-id>/conventions.md → naming, error handling, async style
repo-context/<repo-id>/patterns.json  → event_driven, monorepo, etc.
```

**For each backend repo in `dependent_repos`:**
```
repo-context/<backend-id>/context.md   → API Contract Files location (openapi.yaml / swagger.json)
repo-context/<backend-id>/structure.json → api_dirs — where backend routes/serializers live
```

Also read this frontend repo's entry in `config/repositories.json` → `dependent_repos` and
`dependency_evidence` — these tell you exactly which files contain the API calls to backend repos.
`dependency_evidence` maps each dependent repo id to the file:line of the API call; go directly
to that file instead of searching the whole codebase.

Also read this repo's `runtime` block from `config/repositories.json`:
- `runtime.test_cmd` — referenced in the Fix Recommendation section (do not run it here)
- `runtime.external_services` — tells you which backend services this frontend depends on

**If `bugs/<bug_id>/analysis-backend.md` already exists**, read it first — especially the
**API / Contract Impact** and **Affected Files** sections — before scanning any code.

**If `repo-context/<repo-id>/` does not exist for any repo:** warn in the output:
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

Limit primary analysis to repos where `type == "frontend"`.

For each frontend repo, also read its `dependent_repos` from `config/repositories.json`
and scan those backend repos for the API/contract side of the bug.

## Output

Write `bugs/<bug_id>/analysis-frontend.md` with the following structure.
Use real values for every field — write `unknown` only if genuinely absent, never guess.

```markdown
# Frontend Analysis — {bug_id}

> {one-sentence symptom — what a user sees, e.g. "Checkout page crashes with 'Cannot read properties of undefined' when the cart is empty"}

**Error** · `{JS error type: message — or "none" for UI/logic bugs}` · **Screen/Route** · `{page name or /path}` · **Frequency** · {N occurrences | first YYYY-MM-DD | last YYYY-MM-DD}

---

## Stack Trace / Console Error

```
{paste the JS stack trace or console error verbatim}
```
→ `{frame}` — {what this frame means in the component/service tree}  
→ `{frame}` — **crash point** — {why it fails here}

*(omit section if no stack trace or console error)*

## Entry Point

`{src/path/to/Component.tsx:line}` — {one phrase: what user action or lifecycle event triggers this}

## Execution Path

1. {User action} → `{handler()}` in `{Component.tsx}`
2. `{handler()}` → calls `{service.method()}` in `{services/api.ts}`
3. `{service.method()}` → HTTP {METHOD} to `{/backend/endpoint}` → {what the response looks like}
4. `{file:line}` → **`{ErrorType}`** — {why it fails here}

## Root Cause

`{file:line}` — {one or two sentences: what is broken and why — call out if it is (a) pure frontend logic, (b) backend API mismatch, or (c) backend bug surfacing as a frontend error}

## Backend API Mismatch

| | Backend | Frontend expects |
|--|---------|-----------------|
| Field | `{actual field name or shape}` | `{expected field name or shape}` |

*(omit section if no API contract mismatch)*

## Affected Files

| File | Lines | Issue |
|------|-------|-------|
| `{src/path/to/file.tsx}` | {line(s)} | {one phrase — what is wrong here} |

## Implicated Commits

- `{hash}` · {YYYY-MM-DD} · {author} — {one phrase: why suspicious}

*(omit section if no suspicious commits found)*

## Test Gaps

- `{src/__tests__/file.test.tsx}` — {what coverage is missing}
- Missing: {exact scenario that would have caught this bug}

*(omit section if no gaps found)*

## Fix

**REQUIRED:** for every changed line or block, quote the code exactly as it appears in the file.
If multiple hunks change, write one BEFORE/AFTER block per hunk — never collapse them into
a single description.

`{file}:{line}` — {one phrase: what this change does}  
**Before:**
```typescript
{exact old code copied verbatim from the source}
```
**After:**
```typescript
{exact replacement}
```

*(repeat for each additional hunk or file; list frontend and backend hunks separately if fix spans both)*

Verify: `{test command from runtime.test_cmd}`

## Risk

| | |
|--|--|
| **Scope** | {N files, N components affected} |
| **Regression** | {Low · Medium · High} — {one phrase why} |
| **Backend change required** | {No · Yes — describe what backend change is also needed} |
```

## Investigation Checklist

Work from `workspace/<repo>/` (read-only scan — do not modify files here).

Use loaded context to focus the search — `structure.json.api_dirs` shows where API calls live.
`dependency_evidence` in this frontend repo's `config/repositories.json` entry maps each backend
repo id to the exact file:line of the API call; go directly there instead of searching the whole tree.

1. **Read the error / stack trace** — identify whether it is a JS runtime error, a network error, or a rendering error.
   Use `structure.json.entry_points` to orient yourself in the component tree.
2. **Go directly to the known API call layer**:
   - This repo's entry in `config/repositories.json` → `dependency_evidence["<backend-id>"]` gives the exact file and line of the backend call
   - Start there instead of searching the whole codebase
3. **Apply patterns from `patterns.json`**:
   - `event_driven: true` → check if the bug is a missed event or stale subscription, not a bad API call
   - `monorepo: true` → check which package in the monorepo owns the failing component
4. **Read the response mapper / type definition** — check how the API response is parsed.
   Look for TypeScript interfaces or PropTypes that define the expected shape.
5. **Cross-check backend API contract** using the backend repo's context:
   - Check `repo-context/<backend-id>/context.md` → **API Contract Files** for the OpenAPI/swagger path
   - Read that spec file from `workspace/<backend-repo>/` for the failing endpoint
   - If `analysis-backend.md` exists, read **API / Contract Impact** — the answer may already be there
   - Compare actual backend response shape vs what the frontend type definition expects
6. **Check state management** (Redux, Zustand, Context) if the bug involves stale or incorrect data.
   Use `conventions.md` → **Async Style** to know the correct pattern for this repo.
7. **Check recent git history** for affected frontend files:
   ```bash
   git -C workspace/<frontend-repo> log --oneline -20 -- src/path/to/file.tsx
   ```
8. **Check dependent backend repo** for recent changes to the affected API using backend's `structure.json.api_dirs`:
   ```bash
   git -C workspace/<backend-repo> log --oneline -20 -- <api_dir>/path/to/handler.py
   ```

## Heartbeat

Frontend analysis can be long-running. Update `last_heartbeat` in `bugs/<bug_id>/status.json` at
least every 2 minutes while the investigation is in progress.

## Status Updates

On completion, update `bugs/<bug_id>/status.json`:
- Append event: `{"timestamp": "...", "event": "FRONTEND_ANALYSIS_COMPLETE", "output": "bugs/{bug_id}/analysis-frontend.md"}`

Do NOT change the top-level `status` field — that is managed by `fix-bug`.
