---
name: execution
description: Drive an approved plan to completion by dispatching tasks to specialist agents in dependency order, persisting state before and after every transition. Use for /execute-plan.
---

# Skill: Execution

## 1. Purpose

Execute an approved plan through the orchestrator and specialised agents, maintaining durable state at every transition so execution can survive any crash or interruption.

## 2. When Invoked

Invoked by `/execute-plan <PLAN-ID>`.

### Who runs what

This skill does **pre-flight only**, then hands the plan to the Orchestrator agent, which owns the execution loop. The two never both run the loop.

| Stage | Who | What |
|---|---|---|
| Steps 1–1c | **This skill**, in the invoking session | Load and validate plan state, resolve the branch, create and provision a worktree per repo, dispatch the Orchestrator agent |
| Steps 2–9 | **The Orchestrator agent** | The whole loop: identify ready tasks from the DAG, persist state, assign work to specialist agents, commit their results, route failures, stop safely or complete |
| Step 10 | **This skill**, on return | Surface the orchestrator's final report to the user and name the next command |

The orchestrator is a **delegator**: it decides *what work is ready and who does it*, persists state around every transition so a crash is recoverable, and routes failures. It never writes application code, never runs tests or builds, and never creates worktrees — those exist and are provisioned before it is dispatched.

This skill drives plans only. `/fix-bug` is an independent, autonomous flow owned by `bug-management/SKILL.md` — it has no task graph, no `plan.json`/`state.json`, and never runs through this skill or the orchestrator.

## 3. Inputs

- `PLAN-ID` — identifies the plan directory under `plans/`.
- `--repos <name1>[,<name2>]` — optional. Binds repositories to a plan that was created without one; each name must already exist under `workspace/repos/`. This skill writes them into `plan.json` and into every task — the user never edits plan files by hand.

## 4. Workflow

### Step 1 — Load Plan

Read:
- `plans/<PLAN-ID>/plan.json` — task graph
- `plans/<PLAN-ID>/state.json` — current execution state

If either file is missing or unparseable: stop immediately and report the error. Do not attempt to reconstruct state from memory.

**Repository gate.** A plan may be *created* without a repository (new work), but it can never be *executed* without one: a worktree is cut per repository and agents write only inside a worktree, so with none there is nowhere for the work to land.

Resolve the repositories in this order:

1. **`plan.json.repositories` is non-empty** → use it. Validate every name resolves to a directory under `workspace/repos/`; if one doesn't, halt (below).
2. **Empty, and `--repos <name1>[,<name2>]` was passed** → this is the user binding a repo to a repo-less plan. Validate every name against `workspace/repos/`, then **bind it into the plan yourself** (below). The user never hand-edits `plan.json`.
3. **Empty, and no `--repos`** → halt.

**Binding (`--repos` on a repo-less plan)** — this skill does the writing:

- Validate each name is an existing directory under `workspace/repos/`. If one isn't, halt and say which; do not create it.
- Write the names into `plan.json.repositories`.
- Set every task's `repository` — in `plan.json` **and** in each `tasks/<TASK-ID>/task.json`:
  - **One repo** → every task gets it.
  - **Several repos** → map by role from **`repository-context/repos.json`** (`repos.<name>.role`, written by `/analyze-repos`): `backend-developer` tasks go to the `backend` repo, `frontend-developer` tasks to the `frontend` one; `tester` / `reviewer` / `debugger` tasks inherit the repository of the task they depend on.
  - **Ask once when the mapping isn't clear** — the index has no entry for a repo, two repos share a role, a repo is `full-stack`, or a task's agent matches no repo. List exactly those tasks with the candidate repos and ask the user to assign them, in one question. Never guess, and never spread the question across several turns.
- Append one event per repo: `{"ts":"…","event":"plan_repositories_bound","plan_id":"…","repo":"<repo>","source":"--repos"}`.
- Persist `plan.json` and every touched `task.json` **before** Step 1b cuts anything.
- If `repository-context/repos/<repo>/` is missing (a freshly created repo that was never analysed): warn that agents will work without repo context and that provisioning will likely be `skipped` for lack of an `AGENTS.md` `setup:` command, recommend `/analyze-repos <repo>`, and continue if the user confirms.

**Halt (no repository, and none supplied)** — report exactly this and stop:

```
Plan <PLAN-ID> has no repository, so there is nowhere for its work to land.

  1. Put the repository under workspace/repos/<name>
  2. (recommended) /analyze-repos <name>
  3. /execute-plan <PLAN-ID> --repos <name>

Execution will record it in the plan for you.
```

Halt means *halt*: change no state, write no file, create no branch or worktree, dispatch nothing. Never create the repository, never fall back to `workspace/repos/` itself or the orchestrator's own directory, and never let an agent write outside a worktree.

Validate `state.json` status:
- `approved` → first execution: transition to `running`, record `started_at`, append `execution_started` event, persist before proceeding.
- `running` → continue from current state.
- `completed` → report already finished, exit.
- `blocked` / `failed` → report blocking tasks, suggest `/resume-plan`.

### Step 1b — Sync Repos and Prepare Worktrees

Before dispatching any agent, resolve the plan's feature branch once, then prepare a worktree per repository listed in `plan.json` `repositories`. All git mechanics here go through `git-ops/SKILL.md` — this step never runs a raw `git` command itself.

**1. Resolve the branch name (once per plan, first time only).**

If `plan.json` `branch` is already set: skip to Step 2, reusing that name for every repo. Otherwise resolve the ticket in this order: `plan.json.jira_story` (created by `create-jira-story`), else `plan.json.jira_issue` (an existing key the user passed as `/create-plan --jira`), else the plan's own `<PLAN-ID>`. Checking only `jira_story` would strand a plan created against an existing ticket on a PLAN-ID branch, and the branch is write-once — every commit, PR, and Jira link would inherit the wrong name.

When the ticket is a real Jira key, derive a 2–4 word kebab-case description from `plan.json.title` and build `feature-<KEY>-<description>`. In the `<PLAN-ID>` fallback, append no description — per `repo-policy.json`'s `branch_naming`, the PLAN-ID already carries a slug.

**2. Sync and prepare a worktree for each repository.**

For every repository listed in `plan.json` `repositories`:

- If `plan.json.worktrees.<repo>` is already set and the path exists on disk: reuse it as-is, skip to the next repo. This is the normal case on every loop iteration after the first, and after `/resume-plan`.
- Otherwise, invoke `git-ops`'s `create_branch` operation: `kind=feature`, this repo, `worktree_path=plans/<PLAN-ID>/worktrees/<repo>`, and either the ticket/description from Step 1 (first repo) or the already-resolved `plan.json.branch` passed as the explicit `branch` param (every repo after the first) — so a multi-repo plan lands on the identical branch name everywhere. `create_branch` syncs `workspace/repos/<repo>` to its `base_branch` internally before branching; nothing in this skill touches `workspace/repos/<repo>` directly.
- Record the returned branch name into `plan.json.branch` (first repo only) and the worktree path into `plan.json.worktrees.<repo>`, persisting the file before moving to the next repo or dispatching anything.

**3. Provision each worktree the first time it is created.**

A fresh worktree carries only tracked files. The dependency directory and environment files are git-ignored and must be provisioned before any agent can lint, build, or run tests. Provision once, immediately after `create_branch` returns, before any dispatch:

- **Symlink the dependency directory** — if `runtime.venv` is set and non-null: create a symlink at `<worktree>/$(basename runtime.venv)` pointing to the venv. If `runtime.venv` starts with `/` it is an absolute path — use it directly. Otherwise prepend project root. The venv must already exist and be fully set up (user manages it). Skip if `runtime.venv` is null.

- **Run setup in the worktree** — only if `runtime.setup` is set and non-null: `cd <worktree> && <runtime.setup>`. Skip if `runtime.setup` is null (the common case when the venv is pre-built and no extra steps are needed).

- **Copy environment files** — for each `{ "from": "...", "to": "..." }` entry in `runtime.copy_files`: copy `<project_root>/<from>` to `<worktree>/<to>`, creating parent directories as needed. If the source file does not exist, skip that entry and record it. Never invent values, never read secrets out of a running process, and never copy an env file into `plans/`, `bugs/`, or `reviews/` metadata.

- **Record the outcome** in `plan.json` under `provisioning.<repo>`: `"provisioned"` (all steps ran clean), `"partial"` (one step failed — include the error), or `"skipped"` (nothing to run). Append `{"ts":"…","event":"worktree_provisioned","plan_id":"…","repo":"…","result":"provisioned|partial|skipped"}` to `events.jsonl`.

Provisioning failure is **not** a plan failure — continue and dispatch. Pass `provisioning.<repo>` to every agent dispatched against that repo so it knows which checks are actually available.

Re-provision only when the worktree is created or recreated — never on a loop iteration that reuses an existing one.

This worktree — never `workspace/repos/<repo>` — is the only directory any specialist agent reads from or writes to for this repository.

### Step 1c — Dispatch the Orchestrator

Pre-flight is done. Dispatch the **Orchestrator agent** once, passing:

- `PLAN-ID` and the plan directory (`plans/<PLAN-ID>/`)
- `plan.json.branch` — already resolved and persisted
- `plan.json.worktrees` and `plan.json.provisioning` — the worktree path and provisioning status per repo
- The instruction to follow **Steps 2–9 of this file** for the full loop

The orchestrator drives from here and returns one final report: plan status, per-task outcomes, and the reason if it stopped. Do not run Steps 2–9 in this session, and do not dispatch a second orchestrator — two drivers writing `plan.json` lose each other's updates.

---

### Step 2 — Determine Ready Tasks

**Steps 2 through 9 are executed by the Orchestrator agent**, which reads them here. They are written as instructions to that agent.

A task is **READY** when:
- Its `status` is `pending`, AND
- Every task in its `dependencies` list has `status: completed`.

Group READY tasks by `parallel_group`. Within a group, two tasks may be dispatched concurrently only when their `file_scope` entries do not intersect — compare the declared paths/globs, do not infer scope from `description` prose. Tasks in different repos never intersect. On any doubt, or if a task has an empty `file_scope`, dispatch it alone.

If no tasks are READY and incomplete tasks remain: the plan is blocked — go to Step 8 (Stop Safely).

### Step 3 — Persist Before Dispatch

For each task about to be dispatched, before invoking the agent:

0. If this is an ad-hoc task created during execution (tester, reviewer, debug, or fix), first create `plans/<PLAN-ID>/tasks/<TASK-ID>/task.json` with the full task schema (`status: pending`, resolved `dependencies`, `parallel_group`, `file_scope` inherited from the task it serves, `origin_task` set to that task's ID, `blocked_by: []`, `attempts: 0`, `failure_kind: null`, `checkpoints: []`) and add the matching entry to `plan.json`. A task that lives only in `plan.json` has no checkpoint trail, so `/resume-plan` cannot classify it. Task IDs continue the plan's numbering with a role suffix: `task-0NN-test-<scope>`, `-review-`, `-debug-`, `-fix-`.
1. Set task `status` to `in_progress`, record `started`, and increment `attempts` — in `task.json` first, then `plan.json` (`task.json` is authoritative; `plan.json` is the index).
2. Add task ID to `current_tasks` in `state.json`.
3. Write a checkpoint entry to `plans/<PLAN-ID>/tasks/<TASK-ID>/task.json` under `checkpoints`:

```json
{
  "ts": "<ISO 8601>",
  "event": "dispatched",
  "agent": "<agent>",
  "git_sha": "<HEAD SHA of this repo's worktree, from git-ops status>",
  "note": "dispatched to agent"
}
```

4. Append to `events.jsonl`:

```jsonl
{"ts":"<ISO 8601>","event":"task_started","plan_id":"<PLAN-ID>","task_id":"<id>","agent":"<agent>"}
```

5. Write all files to disk. Only then invoke the agent.

### Step 4 — Dispatch Tasks to Agents

Delegate each READY task to its assigned agent. Pass:
- The full `task.json` content (description, repository, acceptance criteria)
- The repository's **worktree path** from `plan.json` `worktrees.<repo>` (e.g. `plans/<PLAN-ID>/worktrees/<repo>/`) — never `workspace/repos/<repo>/`
- That worktree's `AGENTS.md`, read from inside it
- That repo's `provisioning.<repo>` value from Step 1b, so the agent knows whether dependencies and env files are actually present

Agent routing:

| `agent` value | Delegate to |
|---|---|
| `backend-developer` | Backend Developer agent |
| `frontend-developer` | Frontend Developer agent |
| `tester` | Tester agent |
| `debugger` | Debugger agent |
| `reviewer` | Reviewer agent |

Independent tasks (same `parallel_group`, non-intersecting `file_scope`) may be dispatched concurrently.

**Expected return from every agent** (agents write no orchestrator file — this skill persists what they return):

| Field | Content |
|---|---|
| `status` | `success` or `failure` |
| `files_changed` | Repo-relative paths the agent wrote |
| `verification` | Exact commands run inside the worktree and their outcome |
| `summary` | One or two lines: what was implemented and how — becomes the task `result` and the commit message body |
| `deviations` | Assumptions made, or anything the task specified that was not done |
| `blockers` | Why it failed, with the relevant error output — handed to the debugger on failure |
| `failure_kind` | On failure only: `code` (a real defect in the change or the codebase) or `environment` (the worktree can't run the check — missing dependencies, env file, database, network) |

If an agent returns without `status` or `files_changed`, treat the task as failed rather than guessing at its outcome. A `failure` with no `failure_kind` is treated as `code`.

Do not implement application code, write source files, or run test commands directly.

### Step 5 — Persist After Each Task

When an agent returns:

1. **Commit the agent's work first, before persisting the result.** Specialist agents write files but never run `git` (see rule 25) — so for any **successfully** returning `backend-developer`, `frontend-developer`, `debugger`, or `reviewer` (fix task) task — the tester never writes files, so it is never committed for, invoke `git-ops`'s `commit` operation for that repo with `branch=plan.json.branch`, the repo's worktree path, `files=` the agent's returned `files_changed`, and a message that references the task ID:

   ```
   <type>(<scope>): <summary from the agent's result> (<TASK-ID>, <TICKET-or-PLAN-ID>)
   ```

   Passing `files` is not optional either: `commit` stages exactly that list, so a tool the agent ran (a repo-wide formatter, a lint autofix) cannot smuggle unrelated rewrites into this task's commit. If `commit` reports leftover unstaged paths, record them in the task `result` — they mean something wrote outside the task's scope.

   The task ID in the message is not optional — `create-pr`'s commits check and `resume-plan`'s completion evidence both attribute commits by it. A clean worktree returns `null` (nothing to commit) and is not an error: record that the task produced no changes. Use the returned SHA as the `git_sha` in the completion checkpoint below.

   For a **failed** task, do not commit — leave the partial changes uncommitted in the worktree so the debugger inspects exactly what the agent left behind, and note in the failure checkpoint that the work is uncommitted.

2. Set task `status` to `completed` or `failed`, record `finished`, and write the result summary — in `task.json` first, then `plan.json`.
3. Remove task ID from `current_tasks` in `state.json`.
4. Append a completion checkpoint to `task.json` `checkpoints`:

```json
{
  "ts": "<ISO 8601>",
  "event": "completed | failed",
  "git_sha": "<commit SHA returned by git-ops commit, else current worktree HEAD>",
  "note": "<brief result or failure reason>"
}
```

5. Append to `events.jsonl`:

```jsonl
{"ts":"<ISO 8601>","event":"task_completed","plan_id":"<PLAN-ID>","task_id":"<id>","status":"completed|failed"}
```

6. Write all files immediately — do not batch with other task updates.

**With concurrent agents, run this sequence once per returning task, start to finish, before starting it for the next.** `current_tasks`, `plan.json`, and `state.json` are read-modify-write: folding two returns into one write set loses whichever was written first.

### Step 6 — Post-Task Routing

**After an implementation task completes (`backend-developer` / `frontend-developer`):**
- If a `tester` task for this scope exists in the plan and its dependencies are now met: it becomes READY — dispatch normally.
- If no tester task exists, decide in this order:
  1. **Does the repo have a test framework?** Read `repos.<name>.test_framework` in `repository-context/repos.json` (falling back to the repo's `summary.md` / `AGENTS.md`). A `null` there means none is configured. If none is configured: **create no tester task**, note `no test framework in <repo> — tester task skipped` in the implementation task's `result`, and let downstream tasks proceed. Dispatching a tester at a repo with nothing to run burns an attempt and returns a failure that isn't one.
  2. **Otherwise create the tester task** (with its own `task.json`, per Step 3) and dispatch it before downstream tasks proceed — including when `provisioning.<repo>` is `partial` or `skipped`. Say so in the task description: the tester will return `failure_kind: environment`, which Step 7 handles without a debug cycle, and that is the correct, recorded outcome rather than a silent skip.

**After all implementation and testing tasks for a repository complete:**
- If a `reviewer` task exists and its dependencies are met: dispatch it.
- If no reviewer task exists and the change is non-trivial: create an ad-hoc reviewer task.

A reviewer task dispatched here runs in **Mode A** (`reviewer.md`): it reviews the worktree, writes one plan-based markdown at `reviews/<PLAN-ID>-<repo>-<TASK-ID>.md`, and returns `verdict` plus `findings`. It produces no HTML and no PR artifacts — `/review-pr` is a separate, standalone flow that never runs from here. Record the review file path in the task's `result`.

**After a reviewer returns `changes required`:**
- Create fix tasks for each blocking finding — one per finding, each with its own `task.json` (per Step 3), with the finding's `file:line` in `file_scope` and its "Required change" line as the task description.
- Dispatch them to the appropriate developer agent.
- Re-run the affected tester task after fixes, then the reviewer task again.

**Attempt limits — this loop is bounded, and both limits are countable.** Every re-dispatch increments the task's `attempts`; a task is dispatched at most 3 times (initial + 2 retries). A *fix cycle* is one fix→test→review round created for the same `origin_task`: every ad-hoc task sets `origin_task` to the implementation task it serves, so counting the fix tasks that share an `origin_task` gives the cycle count directly. At most 2 per `origin_task`. On hitting either limit, stop creating follow-up tasks and go to Step 8 with reason `attempt_limit_reached` — never let a flapping reviewer or a fix that won't land spin indefinitely.

### Step 7 — Handle Failures

**First, split by `failure_kind`.**

An `environment` failure is not a code defect: a missing `node_modules`, an absent `settings_local.py`, no test database, no network. Dispatching a debugger at it wastes the task's whole attempt budget and ends with the plan blocked anyway. For `failure_kind: environment`:
- Record the failure and its `blockers` in `task.json` / `plan.json` as usual.
- Do **not** create a debug task, a fix task, or a retry.
- Go straight to Step 8 (Stop Safely) with reason `environment_not_provisioned`, naming the repo, what was missing, and the `provisioning.<repo>` value from Step 1b, so the user can fix the workspace and re-run `/execute-plan`.

For `failure_kind: code` (or an unlabelled failure):
- Set `status: failed` in `task.json` and `plan.json`.
- Mark dependent tasks `blocked_by: [<failed-task-id>]` in `task.json` and `plan.json`; their `status` stays `pending` (`blocked` is a derived bucket, never a persisted status).
- Create a debugger task (with its own `task.json`, per Step 3) referencing the failed task ID and its `blockers` output, and dispatch it.
- Leave the failed agent's partial changes uncommitted in the worktree so the debugger sees exactly what was left behind.
- The debugger **returns** `root_cause`, `fix_summary`, and `validation`; this skill records them in the debug task's `result`. Nothing is written under `bugs/` — that directory belongs to the independent `/fix-bug` flow.
- Based on the finding:
  - **Fixable**: create a fix task for the developer agent, follow with a tester task.
  - **Fundamental blocker**: stop execution (Step 8).

Never attempt to fix failures directly.

### Step 8 — Stop Safely

Stop and do not continue when:

| Reason string | Trigger |
|---|---|
| `no_repository` | Step 1's repository gate failed — the plan has no repository and none was supplied via `--repos`, or a named repo is absent from `workspace/repos/`. Nothing was started; no state changed |
| `environment_not_provisioned` | An agent returned `failure_kind: environment` (Step 7) |
| `attempt_limit_reached` | A task hit 3 dispatches, or a scope hit 2 fix cycles (Step 6) |
| `unresolvable_failure` | A debugger reported a fundamental blocker, or a failure is outside the plan's scope |
| `requires_replanning` | A reviewer finding can't be fixed within the plan as written |
| `no_ready_work` | Tasks remain incomplete but none is READY — every remaining task is blocked behind a failed dependency, so the loop would spin forever |
| `user_interrupted` | The user stopped execution |

`no_ready_work` is the one to watch for: a plan whose last failure left every survivor `blocked_by` something never satisfies Step 9's completion test and never trips an attempt limit either. Detect it in Step 2 — incomplete tasks, zero READY, nothing `in_progress` — and stop here rather than rescanning.

On safe stop:
1. Let already-dispatched parallel agents finish their current work.
2. Set `state.json` status to `blocked` or `failed` with a `blocked_by` or `failed_reason` field.
3. Append to `events.jsonl`:

```jsonl
{"ts":"<ISO 8601>","event":"execution_stopped","plan_id":"<PLAN-ID>","reason":"<reason>"}
```

4. Persist all files.
5. Report clearly what blocked execution.
6. Suggest `/resume-plan <PLAN-ID>` once the blocker is resolved.

### Step 9 — Plan Complete

When all tasks are `completed`:
1. Set `state.json` `status: completed`, record `finished_at`.
2. Append to `events.jsonl`:

```jsonl
{"ts":"<ISO 8601>","event":"execution_completed","plan_id":"<PLAN-ID>"}
```

3. Persist all files.
4. Return the final report to the `execution` skill (Step 10) — the orchestrator's work ends here.

A plan is complete only when every task is `completed`. A task left `failed` means the plan stops via Step 8, not Step 9 — never report completion over a failed task.

### Step 10 — Report to the User

Back in the invoking session, take the orchestrator's final report and surface it:

- **Completed** — print the task counts and suggest `/create-pr <PLAN-ID>`.
- **Stopped** — print the reason string, the blocking task(s), and what the user must fix. For `environment_not_provisioned`, name the repo, the missing dependency or env file, and point at `workspace/env/<repo>/`. Suggest `/resume-plan <PLAN-ID>` once resolved.
- **No report, a truncated one, or an orchestrator that died** — never read this as completion, and never guess at task outcomes. Re-read `state.json` and `plan.json` from disk, report the last persisted state exactly as written, and tell the user to run `/resume-plan <PLAN-ID>`, which reconstructs the truth from checkpoints and git rather than from anything this session remembers.

This skill writes no plan file of its own at this point — the orchestrator already persisted everything.

## 5. Files Read

- `repository-context/repos.json` — per-repo `role` (task binding), `test_framework` (tester decision), `setup` / `env_files` (provisioning)
- `repo-policy.json` — base branch per repo
- `plans/<PLAN-ID>/plan.json`
- `plans/<PLAN-ID>/state.json`
- `plans/<PLAN-ID>/tasks/<TASK-ID>/task.json`

## 6. Files Written

- `plans/<PLAN-ID>/plan.json` — `repositories` and per-task `repository` bound in Step 1 when `--repos` is given; task statuses updated; `worktrees.<repo>` and `provisioning.<repo>` populated in Step 1b
- `plans/<PLAN-ID>/state.json` — execution state updated
- `plans/<PLAN-ID>/events.jsonl` — events appended
- `plans/<PLAN-ID>/tasks/<TASK-ID>/task.json` — status, result, `blocked_by`, `attempts`, checkpoints updated; created outright for ad-hoc tasks

## 7. State Changes

Task status transitions:

```
pending → in_progress → completed
                      → failed → (debugger dispatched)
pending (blocked_by set)   — dependency failed; `blocked` is derived at scan time, never written as a status
```

Plan status transitions:

```
approved → running → completed
                   → blocked
                   → failed
```

## 8. Failure Handling

- Never dispatch a task without first persisting `in_progress` state and checkpoint.
- Never batch state writes — persist after every individual task state change.
- Never mark a task `completed` without a recorded result.
- Never mark an implementation task `completed` without first attempting the `git-ops` `commit` — an uncommitted "completed" task is invisible to `/create-pr` and reads as STALE to `/resume-plan`.
- Never assume an agent completed work because its process disappeared — use the resume-plan skill.
- `events.jsonl` is append-only — never delete or overwrite existing lines.

## 9. Output

Continuous status updates during execution. Final report on completion or block:

```
Plan <PLAN-ID> complete.
  Tasks: <n> completed, <n> skipped
  Run /create-pr <PLAN-ID> to open a pull request.
```

## 10. Rules and Constraints

- Never implement application code, write source files, or run test/build commands directly.
- Never skip a dependency — dispatch only when all dependencies are `completed`.
- All decisions about implementation, testing, debugging, and review are delegated to specialist agents.
- Execution must remain recoverable at every point — if interrupted, `/resume-plan` must be able to continue from the last persisted state.
- Never dispatch an agent against `workspace/repos/<repo>` directly — always the plan's own worktree.
- Never write anything under `bugs/` — `/fix-bug` is independent of this flow and owns that directory.
- Specialist agents never run `git` and never write `plan.json`, `state.json`, `task.json`, or `events.jsonl` — this skill commits their work via `git-ops` and persists their returned result. Only `bugs/` and `reviews/` output files belong to the agents themselves.
- Worktrees are not removed automatically on completion; cleanup (`git worktree remove`) is left to the user.
