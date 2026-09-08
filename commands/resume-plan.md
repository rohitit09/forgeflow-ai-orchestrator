---
description: Resume an interrupted or blocked plan. Invokes the same execute-plan skill as /execute-plan — the skill reads state.status and takes the resume path automatically.
argument-hint: "<plan-id>"
---

# Command: resume-plan

Thin entrypoint. Invokes `skills/execute-plan/SKILL.md` — the same skill `/execute-plan` uses. The skill decides fresh flow vs resume flow from `state.status` (`approved` → fresh; `running` / `blocked` / `delivery_pending` → resume). Do not re-describe the logic here.

**Arguments:** $ARGUMENTS  ·  `<plan-id>` = directory name under `plans/`

## When to use

Any time an `/execute-plan` run didn't reach `completed`. Common causes:

- Server or process crash mid-run
- Token / auth expired mid-agent
- A specialist agent died or hung
- A safe-stop the user has now fixed (missing `.env`, missing dependency, protected-branch collision resolved, base branch re-synced)
- Delivery (PR push / `gh pr create` / Jira) crashed after the DAG landed — resume picks up from `state.status == "delivery_pending"`

Nothing depends on the invoking conversation surviving — disk is the source of truth. Resume reads it and picks up.

## What the skill does on resume (summary)

1. Read `plans/<plan-id>/state.json`, `plan.json`, `events.jsonl` — never trust conversation memory.
2. If `state.status == "blocked"`, ask the user to confirm the blocker is fixed (per the specific `stop_reason`).
3. Reconcile every `in_progress` task against `git log --grep="(<task-id>)"` in that repo's worktree — if the commit landed, mark `completed` and extract the SHA; otherwise reset to `pending`.
4. Re-cut any missing or divergent worktrees.
5. Re-dispatch the orchestrator (which re-scans READY tasks).
6. On orchestrator returning `delivery_pending`, run PR + Jira.
7. On orchestrator returning `blocked` / `failed`, print the reason and exit.

`state.attempts[<id>]` is not decremented — a task that crashed mid-run still counted its attempt. That's what keeps a permanently-failing task from spinning.

## Constraints

- Never `git reset --hard`, never force-push, never delete a worktree with uncommitted changes.
- Never overwrite `state.json` with a value that isn't backed by disk or observable git state.
- Never re-run pre-flight branch/protected-branch check for a plan that already has `state.branch` set unless the branch is missing on disk.
- Every reconciliation write is atomic-rename; `events.jsonl` is append-only.
