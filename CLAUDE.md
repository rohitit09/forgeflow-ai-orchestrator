# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run (auto-creates venv + installs deps)
./run.sh

# Run with hot-reload (development)
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Tests
source .venv/bin/activate
pytest tests/ -v

# Single test file
pytest tests/test_api.py -v

# Single test
pytest tests/test_api.py::test_get_repositories -v
```

No lint command is configured. No type-check command is configured.

## Architecture

```
Browser (xterm.js)
      ↕ WebSocket (/ws/sessions/<id>)
FastAPI  ←── UI + session control only (app/)
      ↕ PTY / tmux attach-session
tmux  ←── persistent terminal layer
      ↕
Claude Code  ←── reads SKILL.md files, executes them
      ↕ reads/writes
Filesystem
  sessions.json          ← session registry (project root)
  bugs/<id>/             ← one directory per bug
  workspace/<repo>/      ← cloned repos
  repo-context/<id>/     ← pre-built repo knowledge
  config/                ← repositories, integrations, agents
```

**FastAPI is a proxy and UI layer only.** All bug-fix workflow logic lives in `skills/*/SKILL.md`. The agent reads those files at runtime and drives everything from the terminal.

## Key Invariants

**Two-layer command structure:** `commands/<name>.md` are thin wrappers that reference `skills/<name>/SKILL.md`. Both `.claude/commands/` and `.opencode/commands/` contain symlinks pointing to `commands/`. This lets Claude Code and OpenCode share the same command definitions with a single source of truth in `skills/`.

To recreate symlinks after a fresh clone: `./setup.sh`. To make commands available globally, symlink each file from `commands/` into `~/.claude/commands/` as well.

**`fix-bug` invokes sub-skills by reading their SKILL.md file inline**, not via slash commands. When editing `fix-bug/SKILL.md`, references to `bug-analysis-backend` and `bug-analysis-frontend` mean "read that file and follow its instructions."

**No `config/dependencies.json`.** All dependency data lives in `config/repositories.json` per repo entry:
- `dependent_repos` — list of repo IDs this repo calls (user-managed)
- `dependency_evidence` — auto-filled by `/repo-context` → `{"repo-id": "file:line — explanation"}`
- `_rejected_dependencies` — auto-filled by `/repo-context` → `{"repo-id": "reason"}`
- `feature_merge_dest_branch` — PR target branch for `/execute-plan` feature work (falls back to `base_branch`)
- `bug_merge_dest_branch` — PR target branch for `/fix-bug` bug fixes (falls back to `base_branch`)
- `runtime` — auto-filled by `/repo-context` → framework, language, test fields, and worktree provisioning fields (see below)

**Session status is derived at request time**, never stored directly. `reconciliation.py` checks tmux liveness + `bugs/<id>/status.json` heartbeat to produce `ACTIVE | STALE | INTERRUPTED | COMPLETED | DISCONNECTED`.

**`bugs/<id>/` lives at project root** (same level as `workspace/`, `config/`), not inside `workspace/`.

## `app/` Module Map

| File | Responsibility |
|------|---------------|
| `main.py` | All FastAPI routes + WebSocket endpoint |
| `config.py` | `Settings` singleton — all paths derived here |
| `models.py` | Pydantic models: `SessionRecord`, `BugStatusData`, `BugStatus` enum (22 values), `SessionStatus` enum |
| `session_manager.py` | CRUD on `sessions.json` with `FileLock` |
| `bug_manager.py` | Read/write `bugs/<id>/` directory |
| `reconciliation.py` | Derives live session status from tmux + filesystem |
| `tmux_manager.py` | Thin subprocess wrapper around tmux CLI |
| `websocket_terminal.py` | PTY bridge: `tmux attach-session` ↔ WebSocket |
| `filesystem.py` | `atomic_write_json` (mkstemp+rename), `FileLock` (fcntl), `read_json_safe`, `append_jsonl` |
| `agent_manager.py` | Reads `config/agents.json` → resolves agent commands |

## Bug Pipeline

23 status values in order:

`FETCHED` → `QUEUED` → `SYNCING` → `SYNCED` → `JIRA_CREATING` → `JIRA_CREATED` → `BRANCHING` → `BRANCHED` → `WORKTREE_READY` → `DIAGNOSING` → `DIAGNOSED` → `PLANNING` → `PLANNED` → `IMPLEMENTING` → `IMPLEMENTED` → `TESTING` → `TESTED` | `TEST_SKIPPED` → `PR_CREATING` → `PR_CREATED` → `JIRA_UPDATING` → `JIRA_UPDATED` → `DONE`

`TEST_SKIPPED` is written instead of `TESTED` when `test=false` or no `test_cmd` is set in `repositories.json`.

Terminal failure states: `FAILED`, `BLOCKED` (BLOCKED needs human input, then resumes).

`bugs/<id>/status.json` is the source of truth for pipeline position. `fix-bug` resumes from the last written `status` field when restarted.

## Skills Reference

| Command | What it does |
|---------|-------------|
| `/repo-context [repo-id]` | Builds `repo-context/<id>/` + fills `runtime` block in `repositories.json` |
| `/list-bugs source=sentry\|jira project=X top=N\|all` | Fetches bugs → `bugs/<id>/` |
| `/fix-bug <bug-id>` | Full 13-step orchestrator (Steps 0–12) |
| `/create-plan <requirement> [--jira KEY]` | Interactive planner → `plans/<slug>/plan.json` + `plan.md` + `state.json` (status `approved`) |
| `/execute-plan <plan-id>` | Runs an approved plan through the DAG loop. Skill does pre-flight + delivery; orchestrator agent owns the loop; specialists (backend-developer, frontend-developer, tester, debugger, reviewer) do the work. Crash-safe end-to-end. |
| `/resume-plan <plan-id>` | Rebuilds truth from `state.json` + `git log` and re-dispatches. Same skill as `/execute-plan` — the skill picks resume vs fresh from `state.status`. |
| `/code-review <pr-url>` | Reviews a GitHub PR, writes output to `reviews/` |
| `/plans` | Interactive plan builder, writes output to `plans/` |

Run `/repo-context` before fixing any bugs. It writes `context.md`, `structure.json`, `testing.md`, `conventions.md`, `patterns.json` under `repo-context/<id>/` — these are loaded by the analysis sub-skills to avoid full-tree scanning.

## Non-Obvious Implementation Details

- **`_repos()` in `main.py`** always creates a copy of each repo dict (`r = dict(r)`) before adding `abs_path`. Mutating the list item in-place would silently drop `abs_path` for relative-path repos on the first return.

- **`atomic_write_json`** uses `tempfile.mkstemp` + `os.replace` (atomic rename). `FileLock` uses `fcntl.LOCK_EX` on a `.lock` sidecar file. Both are required because multiple browser sessions can write `sessions.json` concurrently.

- **WebSocket terminal** spawns `tmux attach-session` as a subprocess with a PTY. Resize events are sent as JSON text frames `{"type":"resize","cols":N,"rows":N}`; keystrokes are sent as raw bytes.

- **STALE detection**: a session with a live tmux process whose `last_heartbeat` in `status.json` is older than 30 minutes (`STALE_MINUTES` in `reconciliation.py`) is classified STALE. The heartbeat is updated by the skill every 2 minutes during long-running steps.

- **`git worktree add <path> -b <branch> origin/<base_branch>`** — skills use this atomic form (branch + worktree in one command). Never checkout on the main workspace clone.

- **Jira descriptions** are ADF (Atlassian Document Format) JSON, not markdown. The `fix-bug` skill Step 3 constructs the full ADF object with Description, Root Cause, Diagnostic, and Source sections.

- **`runtime` worktree provisioning fields** in `repositories.json`:
  - `venv` — path to the shared dependency directory (workspace-relative or absolute). Skills symlink it into each worktree at `$(basename venv)`. Absolute paths (starting with `/`) are used directly; relative paths are prefixed with project root. `null` if no shared venv.
  - `setup` — command to run inside the worktree after the venv is symlinked. `null` when the venv is pre-built and complete — no install step needed. Only set when the worktree needs extra steps.
  - `copy_files` — list of `{ "from": "<project-root-relative>", "to": "<worktree-relative>" }` entries. Files are copied once at provisioning time and shared by both setup and test runs. Empty array `[]` if nothing to copy.
  - `test_cmd` — full test command **including** env activation prefix (e.g. `. env/bin/activate && python manage.py test`). Run directly in the worktree — no separate activation step. `null` if `test=false`.

- **Shell activation** in skills uses `. /path/bin/activate` (POSIX dot operator), never `source`.

- **Session types**: valid values are `empty`, `list-bugs`, `fix-bug`, `fix-bugs`, `sync-bugs`, `code-review`, `plans`. If `session_type` is not set on the request, it is auto-derived from the first word of `start_command`. The API rejects unknown types and falls back to the raw value.

- **`_delayed_send`** fires a tmux `send-keys` after a delay to let Claude Code start up before the slash command arrives — 4 s for most sessions, 7 s for `code-review`. Resume sessions use 6 s.

- **`config/integrations.json`** uses `${ENV_VAR}` placeholders that are substituted from `.env` at startup (`config.py`). The `.env` file itself is also forwarded into every tmux session via `_env_for_tmux()` so skills see the same credentials.

- **`sessions_history.json`** at project root receives completed/failed sessions when they are pruned from the active `sessions.json` registry.

## Tests

Tests redirect `settings._base_dir` to `tmp_path` via an `autouse` fixture — no real `sessions.json` or `bugs/` is touched. tmux calls are mocked with `unittest.mock.patch`. Add new tests following this pattern; do not hit the real filesystem or start real processes in tests.

## Project Structure

```
ai_orch_new/
├── app/                        ← FastAPI (UI + API only)
│   ├── main.py                    routes + WebSocket endpoint
│   ├── config.py                  Settings singleton (paths, env)
│   ├── models.py                  Pydantic models, BugStatus / SessionStatus enums
│   ├── session_manager.py         atomic sessions.json CRUD
│   ├── bug_manager.py             bugs/<id>/ helpers
│   ├── tmux_manager.py            tmux CLI wrapper
│   ├── websocket_terminal.py      PTY ↔ WebSocket bridge
│   ├── reconciliation.py          derives session status from tmux + filesystem
│   ├── agent_manager.py           config/agents.json → CLI command
│   └── filesystem.py              atomic_write_json, FileLock, append_jsonl
│
├── commands/                   ← slash command wrappers (source of truth)
│   ├── fix-bug.md · list-bugs.md · repo-context.md · code-review.md
│   ├── create-plan.md · execute-plan.md · resume-plan.md
│   └── bug-analysis-backend.md · bug-analysis-frontend.md
│
├── skills/                     ← all workflow logic
│   ├── fix-bug/SKILL.md               13-step orchestrator
│   ├── list-bugs/SKILL.md             Sentry/Jira → bugs/<id>/
│   ├── repo-context/SKILL.md          writes repo-context/<id>/*
│   ├── code-review/SKILL.md
│   ├── create-plan/                   (implicit — logic in commands/create-plan.md)
│   ├── brainstorming/SKILL.md         invoked by /create-plan Step 2a
│   ├── planning/SKILL.md              Step 2b
│   ├── planning-backend/SKILL.md      Step 2d
│   ├── planning-frontend/SKILL.md     Step 2e
│   ├── create-jira-story/SKILL.md     Step 2f
│   ├── create-jira-bug/SKILL.md       used by /fix-bug for Jira linking
│   ├── execute-plan/SKILL.md          pre-flight + DAG loop
│   ├── bug-analysis-backend/SKILL.md  deep backend investigation
│   └── bug-analysis-frontend/SKILL.md deep frontend investigation
│
├── agents/                     ← custom agent definitions (symlinked into .claude/agents/)
│   ├── orchestrator.md            drives the DAG loop in /execute-plan
│   ├── backend-developer.md · frontend-developer.md
│   └── tester.md · debugger.md · reviewer.md
│
├── config/
│   ├── repositories.json          repos + branch_naming + commit_message
│   ├── integrations.json          Sentry / Jira / GitHub (${ENV_VAR} placeholders)
│   └── agents.json                agent id → CLI command
│
├── .claude/
│   ├── commands/                  symlinks → ../../commands/*.md
│   ├── agents/                    symlinks → ../../agents/*.md
│   └── settings.local.json
│
├── .opencode/
│   ├── commands/                  symlinks → ../../commands/*.md
│   └── opencode.jsonc
│
├── repo-context/               ← pre-built repo knowledge (from /repo-context)
│   └── <repo-id>/                 context.md · structure.json · testing.md · conventions.md · patterns.json
│
├── bugs/                       ← one dir per bug (written by skills)
│   └── <bug-id>/                  bug.json · status.json · diagnosis.md · plan.md · events.jsonl · result.json · worktree/<repo-id>/
│
├── plans/                      ← one dir per plan (reserved by POST /api/plans/reserve)
│   └── <YYYYMMDD-slug>/           status.json (seed) · partial.json (on pause) · plan.json · plan.md · state.json
│
├── workspace/                  ← cloned repos (git clone → workspace/<repo-id>)
├── reviews/                    ← output of /code-review
│
├── static/ · templates/        ← UI assets (Jinja2 + xterm.js)
├── tests/                      ← pytest suite
│
├── CLAUDE.md
├── AGENTS.md                   ← symlink → CLAUDE.md (OpenCode reads this)
├── setup.sh                    ← creates symlinks + scaffolds config
├── run.sh
├── sessions.json               ← active session registry
├── sessions_history.json       ← pruned completed/failed sessions
├── requirements.txt
└── .env / .env.example
```
