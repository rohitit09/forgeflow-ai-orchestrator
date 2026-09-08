import asyncio
import json as _json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import tmux_manager
from .agent_manager import get_agent_command, list_agents, validate_agent
from .bug_manager import build_pipeline_stages, build_workflow_steps, get_bug, get_bug_events, get_bug_status, list_bugs, touch_heartbeat
from .config import settings
from .filesystem import atomic_write_json, read_json_safe
from pydantic import BaseModel
from .models import (
    BugStatus, CreateSessionRequest, ResumeSessionRequest, SessionStatus,
)
from .reconciliation import derive_session_status, reconcile_sessions
from .session_manager import (
    archive_session, create_session, get_session, get_session_by_tmux, list_closed_sessions,
    list_sessions, remove_session, update_session,
)
from .websocket_terminal import handle_direct_websocket, handle_terminal_websocket

BASE_DIR = Path(__file__).resolve().parent.parent


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # On startup: archive every session whose tmux process is dead so the UI
    # never shows ghost ACTIVE entries after a server restart.
    for s in list_sessions():
        if not tmux_manager.has_session(s.tmux_session):
            archive_session(s.session_id, status=SessionStatus.DISCONNECTED.value)
    yield


app = FastAPI(title="AI Bug Fix Orchestrator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["tojson"] = lambda x, **kw: Markup(_json.dumps(x, default=str))


async def _delayed_send(
    tmux_session: str,
    command: str,
    delay: float = 4.0,
    enter_delay: float = 0.3,
    double_enter: bool = False,
) -> None:
    await asyncio.sleep(delay)
    tmux_manager.send_keys(tmux_session, command, enter=False)
    await asyncio.sleep(enter_delay)
    tmux_manager.send_keys(tmux_session, "", enter=True)
    if double_enter:
        # OpenCode shows a slash-command dropdown on "/" input; first Enter selects
        # from the picker, second Enter submits the completed command.
        await asyncio.sleep(0.5)
        tmux_manager.send_keys(tmux_session, "", enter=True)


def _resolve_env(value: str) -> str:
    """Expand ${VAR} placeholders using os.environ."""
    import os, re
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), value)


def _env_for_tmux() -> dict:
    """Return env vars to forward into every tmux session.

    Merges two sources:
    1. Keys listed in .ENV that are present in os.environ (project secrets)
    2. AI provider API keys always included if present (so agents can reach their APIs)
    """
    import os
    result = {}

    # AI provider keys — always forward if set, regardless of .ENV listing
    _AI_KEYS = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    for key in _AI_KEYS:
        if key in os.environ:
            result[key] = os.environ[key]

    env_file = BASE_DIR / ".ENV"
    if env_file.exists():
        with env_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.partition("=")[0].strip()
                if key and key in os.environ:
                    result[key] = os.environ[key]

    return result


def _jira_base_url() -> str:
    data = read_json_safe(settings.integrations_config, {})
    raw = data.get("jira", {}).get("base_url", "")
    return _resolve_env(raw).rstrip("/")


def _sync_sources() -> list[dict]:
    data = read_json_safe(settings.integrations_config, {})
    result = []
    for name, cfg in data.items():
        if cfg.get("sync_bug_source"):
            result.append({
                "id": name,
                "label": name.title(),
                "projects": cfg.get("projects", {}),
                "sync_days": cfg.get("sync_days", 2),
            })
    return result


def _last_sync_states() -> list[dict]:
    sync_dir = settings.bugs_dir / "_sync"
    if not sync_dir.exists():
        return []
    states = []
    for f in sorted(sync_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = read_json_safe(f)
        if data:
            states.append(data)
    return states


def _list_coding_agents() -> list[dict]:
    agents_dir = BASE_DIR / "agents"
    result = []
    if not agents_dir.exists():
        return result
    for agent_file in sorted(agents_dir.iterdir()):
        if not agent_file.is_file() or agent_file.suffix != ".md":
            continue
        content = agent_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        fm_description = ""
        fm_tools = ""
        body_start = 0
        if lines and lines[0].strip() == "---":
            end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
            if end:
                for fl in lines[1:end]:
                    if fl.startswith("description:"):
                        fm_description = fl.split(":", 1)[1].strip()
                    elif fl.startswith("tools:"):
                        fm_tools = fl.split(":", 1)[1].strip()
                body_start = end + 1
        body_lines = lines[body_start:]
        agent_id = agent_file.stem
        name = next((l.lstrip("#").strip() for l in body_lines if l.startswith("#")), agent_id.replace("-", " ").title())
        result.append({
            "id": agent_id,
            "name": name,
            "description": fm_description,
            "tools": fm_tools,
            "content": content,
        })
    return result


def _list_commands() -> list[dict]:
    commands_dir = BASE_DIR / "commands"
    result = []
    if not commands_dir.exists():
        return result
    for cmd_file in sorted(commands_dir.iterdir()):
        if not cmd_file.is_file() or cmd_file.suffix != ".md":
            continue
        content = cmd_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        fm_description = ""
        fm_argument_hint = ""
        body_start = 0
        if lines and lines[0].strip() == "---":
            end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
            if end:
                for fl in lines[1:end]:
                    if fl.startswith("description:"):
                        fm_description = fl.split(":", 1)[1].strip()
                    elif fl.startswith("argument-hint:"):
                        fm_argument_hint = fl.split(":", 1)[1].strip()
                body_start = end + 1
        cmd_id = cmd_file.stem
        name = cmd_id.replace("-", " ").title()
        result.append({
            "id": cmd_id,
            "name": name,
            "description": fm_description,
            "argument_hint": fm_argument_hint,
            "content": content,
        })
    return result


def _list_skills() -> list[dict]:
    skills_dir = BASE_DIR / "skills"
    result = []
    if not skills_dir.exists():
        return result
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        content = skill_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        # extract frontmatter fields if present
        fm_description = ""
        body_start = 0
        if lines and lines[0].strip() == "---":
            end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
            if end:
                for fl in lines[1:end]:
                    if fl.startswith("description:"):
                        fm_description = fl.split(":", 1)[1].strip()
                body_start = end + 1

        body_lines = lines[body_start:]
        name = next((l.lstrip("#").strip() for l in body_lines if l.startswith("#")), skill_dir.name)
        description = fm_description or next(
            (l.strip() for l in body_lines if l.strip() and not l.startswith("#")), ""
        )
        result.append({
            "id": skill_dir.name,
            "name": name,
            "description": description,
            "content": content,
        })
    return result


# ── helpers ───────────────────────────────────────────────────────────────────

def _repos() -> list[dict]:
    data = read_json_safe(settings.repositories_config, {"repositories": []})
    result = []
    for r in data.get("repositories", []):
        r = dict(r)  # always copy — never mutate the cached list item
        p = Path(r.get("path", ""))
        r["abs_path"] = str(BASE_DIR / p) if not p.is_absolute() else str(p)
        result.append(r)
    return result


def _get_repo(repo_id: str) -> Optional[dict]:
    return next((r for r in _repos() if r["id"] == repo_id), None)


def _stats(sessions: list[dict]) -> dict:
    active = sum(1 for s in sessions if s.get("session_status") == SessionStatus.ACTIVE.value)
    completed = sum(1 for s in sessions if s.get("session_status") == SessionStatus.COMPLETED.value)
    interrupted = sum(1 for s in sessions if s.get("session_status") == SessionStatus.INTERRUPTED.value)
    stale = sum(1 for s in sessions if s.get("session_status") == SessionStatus.STALE.value)
    ai_sessions = sum(1 for s in sessions if s.get("session_status") == SessionStatus.ACTIVE.value and s.get("agent") == "claude")
    return {
        "total": len(sessions),
        "active": active,
        "ai_sessions": ai_sessions,
        "manual_sessions": active - ai_sessions,
        "completed": completed,
        "interrupted": interrupted,
        "stale": stale,
        "healthy": tmux_manager.is_installed(),
    }


# ── UI routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    sessions = list_sessions()
    reconciled = reconcile_sessions(sessions)
    # Auto-close: kill tmux + archive for COMPLETED sessions still holding a tmux process
    for s in reconciled:
        if s["session_status"] == SessionStatus.COMPLETED.value and s.get("tmux_exists"):
            tmux_manager.kill_session(s["tmux_session"])
            archive_session(s["session_id"], status=SessionStatus.COMPLETED.value)
    # Auto-archive sessions that are DISCONNECTED (tmux dead, no bug, not explicitly closed)
    for s in reconciled:
        if s["session_status"] == SessionStatus.DISCONNECTED.value:
            archive_session(s["session_id"], status=SessionStatus.DISCONNECTED.value)
    reconciled = [s for s in reconciled if s["session_status"] not in (
        SessionStatus.DISCONNECTED.value, SessionStatus.COMPLETED.value
    )]
    closed = list_closed_sessions()
    bugs = list_bugs()
    repos = _repos()
    agents = list_agents()
    active_workspaces = [s for s in reconciled if s["session_status"] == SessionStatus.ACTIVE.value and s.get("bug_id")]
    running_bug_ids = {
        s["bug_id"] for s in reconciled
        if s.get("bug_id") and s.get("session_status") in (SessionStatus.ACTIVE.value, SessionStatus.STALE.value)
    }
    running_session_by_bug = {
        s["bug_id"]: s for s in reconciled
        if s.get("bug_id") and s.get("session_status") in (SessionStatus.ACTIVE.value, SessionStatus.STALE.value)
    }
    pipeline_bugs = []
    for b in bugs:
        bid = b.get("bug_id", "")
        if bid in running_bug_ids:
            pipeline_bugs.append({**b, "active_session": running_session_by_bug[bid]})

    running_syncs = [
        s for s in reconciled
        if s.get("session_type") == "sync-bugs"
        and s.get("session_status") in (SessionStatus.ACTIVE.value, SessionStatus.STALE.value)
    ]

    exec_sessions = {
        s.get("start_command", "").replace("/execute-plan ", "").strip(): s
        for s in reconciled
        if s.get("session_type") == "execute-plan"
        and s.get("session_status") in (SessionStatus.ACTIVE.value, SessionStatus.STALE.value)
    }
    all_plans = _list_plans()
    pipeline_plans = []
    for p in all_plans:
        sess = exec_sessions.get(p["plan_id"])
        if sess:
            p["active_session"] = sess
            pipeline_plans.append(p)

    return templates.TemplateResponse(request, "index.html", {
        "sessions": reconciled,
        "closed_sessions": closed,
        "bugs": bugs,
        "pipeline_bugs": pipeline_bugs,
        "pipeline_plans": pipeline_plans,
        "running_syncs": running_syncs,
        "repositories": repos,
        "agents": agents,
        "stats": _stats(reconciled),
        "active_workspaces": active_workspaces,
        "jira_base_url": _jira_base_url(),
        "sync_sources": _sync_sources(),
        "active_page": "overview",
    })


@app.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_page(request: Request, session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    all_sessions = list_sessions()
    rec_map = {s["session_id"]: s for s in reconcile_sessions(all_sessions)}
    session_data = rec_map.get(session_id, session.model_dump())

    bug = None
    events = []
    if session.bug_id:
        bug = get_bug(session.bug_id)
        events = get_bug_events(session.bug_id)[-30:]

    return templates.TemplateResponse(request, "session.html", {
        "session": session_data,
        "bug": bug,
        "events": events,
        "repositories": _repos(),
        "agents": list_agents(),
        "active_page": "sessions",
    })


def _list_plans() -> list[dict]:
    plans_dir = BASE_DIR / "plans"
    if not plans_dir.exists():
        return []
    result = []
    for d in sorted(plans_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        status_file  = d / "status.json"
        plan_json    = d / "plan.json"
        plan_md      = d / "plan.md"
        state_json   = d / "state.json"
        partial_json = d / "partial.json"

        # Any dir without a marker file is not a plan (may be stray)
        if not (status_file.exists() or plan_json.exists() or partial_json.exists()):
            continue

        seed = read_json_safe(status_file, {}) or {}

        # Derive status:
        #  - plan.json exists → look at state.json
        #  - else partial.json exists → PARTIAL
        #  - else status.json alone (reserved) → PARTIAL (user can resume/discard)
        if plan_json.exists():
            state = read_json_safe(state_json, {}) or {}
            raw_st = (state.get("status") or "APPROVED").upper()
            if raw_st == "COMPLETED":
                raw_st = "DONE"
            status = raw_st if raw_st in {"APPROVED", "DRAFT", "RUNNING", "DONE", "FAILED"} else "DRAFT"
        else:
            status = "PARTIAL"

        pj = read_json_safe(plan_json, {}) if plan_json.exists() else {}
        partial = read_json_safe(partial_json, {}) if partial_json.exists() else {}

        tasks = pj.get("tasks", [])
        repos = pj.get("repos", [])
        context = pj.get("context", {})
        task_counts: dict = {}
        for t in tasks:
            r = t.get("repo", "unknown")
            task_counts[r] = task_counts.get(r, 0) + 1

        state = (read_json_safe(state_json, {}) or {}) if state_json.exists() else {}
        exec_summary_json = d / "execution_summary.json"
        exec_summary = read_json_safe(exec_summary_json, None) if exec_summary_json.exists() else None
        designs = sorted(f.name for f in d.glob("design-mockup*.html"))
        result.append({
            "plan_id": d.name,
            "name": pj.get("title") or partial.get("title") or seed.get("title") or d.name,
            "status": status,
            "created_at": pj.get("created") or seed.get("updated_at") or partial.get("saved_at") or "",
            "plan_content": plan_md.read_text(encoding="utf-8") if plan_md.exists() else (
                (d / "partial.md").read_text(encoding="utf-8", errors="replace") if (d / "partial.md").exists() else (
                    (d / "log.md").read_text(encoding="utf-8", errors="replace") if (d / "log.md").exists() else ""
                )
            ),
            "is_draft_log": not plan_md.exists() and ((d / "partial.md").exists() or (d / "log.md").exists()),
            "has_plan_json": plan_json.exists(),
            "has_partial":   partial_json.exists(),
            "resumed_phase": partial.get("resumed_phase") if partial else None,
            "task_count": len(tasks),
            "task_counts_by_repo": task_counts,
            "repos": [{"name": r.get("name", ""), "kind": r.get("kind", "")} for r in repos],
            "problem": context.get("problem", ""),
            "success_criteria": context.get("success_criteria", []),
            "constraints": context.get("constraints", []),
            "agent": state.get("agent", ""),
            "execution_summary": exec_summary,
            "designs": designs,
        })
    return result


@app.get("/plans", response_class=HTMLResponse)
async def plans_page(request: Request):
    sessions = list_sessions()
    reconciled = reconcile_sessions(sessions)
    exec_session_by_plan: dict = {}
    for s in reconciled:
        if s.get("session_type") == "execute-plan" and s.get("session_status") in (
            SessionStatus.ACTIVE.value, SessionStatus.STALE.value
        ):
            plan_id = (s.get("start_command") or "").replace("/execute-plan ", "").strip()
            if plan_id:
                exec_session_by_plan[plan_id] = s

    plans = _list_plans()
    for p in plans:
        p["active_session"] = exec_session_by_plan.get(p["plan_id"])

    return templates.TemplateResponse(request, "plans.html", {
        "plans": plans,
        "repositories": _repos(),
        "agents": list_agents(),
        "active_page": "plans",
        "active_workspaces": [],
    })


@app.get("/plan", response_class=HTMLResponse)
async def plan_redirect():
    return RedirectResponse(url="/plans", status_code=301)


@app.get("/api/plans/{plan_slug}/designs/{filename}", response_class=HTMLResponse)
async def get_plan_design(plan_slug: str, filename: str):
    import re
    if not re.match(r'^design-mockup[\w-]*\.html$', filename):
        raise HTTPException(status_code=404, detail="Not found")
    path = BASE_DIR / "plans" / plan_slug / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Design not found")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {
        "skills": _list_skills(),
        "agents": list_agents(),
        "commands": _list_commands(),
        "coding_agents": _list_coding_agents(),
        "repositories": _repos(),
        "active_page": "settings",
        "active_workspaces": [],
    })


# Legacy redirects so old bookmarks keep working
from fastapi.responses import RedirectResponse

@app.get("/agents", response_class=HTMLResponse)
async def agents_page():
    return RedirectResponse(url="/settings?tab=agents", status_code=301)

@app.get("/repositories", response_class=HTMLResponse)
async def repositories_page():
    return RedirectResponse(url="/settings?tab=repositories", status_code=301)

@app.get("/skills", response_class=HTMLResponse)
async def skills_page():
    return RedirectResponse(url="/settings", status_code=301)


@app.get("/bugs/{bug_id}", response_class=HTMLResponse)
async def bug_detail_page(request: Request, bug_id: str):
    bug = get_bug(bug_id)
    if not bug:
        raise HTTPException(status_code=404, detail="Bug not found")
    events = get_bug_events(bug_id)
    sd = bug.get("status_data") or {}
    workflow = build_workflow_steps(
        events, sd,
        plan_summary=bug.get("plan_summary"),
        result=bug.get("result"),
    )
    bug_sessions = [s for s in list_sessions() if s.bug_id == bug_id]
    reconciled_sessions = reconcile_sessions(bug_sessions)
    active_workspaces = [s for s in reconcile_sessions(list_sessions())
                         if s["session_status"] == SessionStatus.ACTIVE.value and s.get("bug_id")]
    return templates.TemplateResponse(request, "bug_detail.html", {
        "bug": bug,
        "events": events[-50:],
        "workflow": workflow,
        "bug_sessions": reconciled_sessions,
        "jira_base_url": _jira_base_url(),
        "repositories": _repos(),
        "agents": list_agents(),
        "active_page": "bugs",
        "active_workspaces": active_workspaces,
    })


@app.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    sessions = list_sessions()
    reconciled = reconcile_sessions(sessions)
    bugs = list_bugs()
    bug_map = {b["bug_id"]: b for b in bugs}

    running = []
    for s in reconciled:
        if s.get("session_status") not in (SessionStatus.ACTIVE.value, SessionStatus.STALE.value):
            continue
        if s.get("bug_id"):
            bug = bug_map.get(s["bug_id"], {})
            running.append({**s, "bug": bug, "review": None})
        elif s.get("session_type") == "code-review":
            # parse PR URL from start_command: "/code-review <url>"
            parts = (s.get("start_command") or "").strip().split(None, 1)
            pr_url = parts[1] if len(parts) > 1 else ""
            running.append({**s, "bug": None, "review": {"pr_url": pr_url}})

    active_workspaces = [s for s in reconciled if s["session_status"] == SessionStatus.ACTIVE.value and s.get("bug_id")]

    # plans for the pipeline — only those with an active execute-plan session
    exec_session_by_plan = {}
    for s in reconciled:
        if s.get("session_type") == "execute-plan" and s.get("session_status") in (
            SessionStatus.ACTIVE.value, SessionStatus.STALE.value
        ):
            plan_id = (s.get("start_command") or "").replace("/execute-plan ", "").strip()
            if plan_id:
                exec_session_by_plan[plan_id] = s

    pipeline_plans = []
    for p in _list_plans():
        sess = exec_session_by_plan.get(p["plan_id"])
        if sess:
            p["active_session"] = sess
            pipeline_plans.append(p)

    return templates.TemplateResponse(request, "pipeline.html", {
        "running": running,
        "plans": pipeline_plans,
        "repositories": _repos(),
        "agents": list_agents(),
        "jira_base_url": _jira_base_url(),
        "active_page": "pipeline",
        "active_workspaces": active_workspaces,
    })


def _list_reviews() -> list[dict]:
    reviews_dir = BASE_DIR / "reviews"
    if not reviews_dir.exists():
        return []
    result = []
    for d in sorted(reviews_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        status_file = d / "status.json"
        if not status_file.exists():
            continue
        data = read_json_safe(status_file, {})
        if data:
            data.setdefault("review_id", d.name)
            result.append(data)
    return result


@app.get("/reviews", response_class=HTMLResponse)
async def reviews_page(request: Request):
    reviews = _list_reviews()
    running_reviews = [r for r in reviews if r.get("status") not in ("COMPLETED", "FAILED")]
    completed_reviews = [r for r in reviews if r.get("status") == "COMPLETED"]
    failed_reviews = [r for r in reviews if r.get("status") == "FAILED"]
    return templates.TemplateResponse(request, "reviews.html", {
        "running_reviews": running_reviews,
        "completed_reviews": completed_reviews,
        "failed_reviews": failed_reviews,
        "repositories": _repos(),
        "agents": list_agents(),
        "sync_sources": _sync_sources(),
        "active_page": "reviews",
        "active_workspaces": [],
    })


@app.get("/reviews/{review_id}/html", response_class=HTMLResponse)
async def review_html_file(review_id: str):
    review_file = BASE_DIR / "reviews" / review_id / "review.html"
    if not review_file.exists():
        raise HTTPException(status_code=404, detail="Review HTML not found")
    return HTMLResponse(content=review_file.read_text(encoding="utf-8"))


@app.get("/api/reviews")
async def api_reviews():
    return {"reviews": _list_reviews()}


@app.get("/bugs", response_class=HTMLResponse)
async def bugs_page(request: Request):
    bugs = list_bugs()
    sessions = list_sessions()
    reconciled = reconcile_sessions(sessions)
    active_by_bug: dict[str, dict] = {}
    for s in reconciled:
        bid = s.get("bug_id")
        if bid and s.get("session_status") in (SessionStatus.ACTIVE.value, SessionStatus.STALE.value):
            active_by_bug[bid] = s

    open_bugs, running_bugs, done_bugs, failed_bugs = [], [], [], []
    for bug in bugs:
        bid = bug.get("bug_id", "")
        bug_status = (bug.get("status_data") or {}).get("status", "FETCHED")
        if bid in active_by_bug:
            bug["active_session"] = active_by_bug[bid]
            running_bugs.append(bug)
        elif bug_status == "DONE":
            done_bugs.append(bug)
        elif bug_status == "FAILED":
            failed_bugs.append(bug)
        else:
            open_bugs.append(bug)

    return templates.TemplateResponse(request, "bugs.html", {
        "open_bugs": open_bugs,
        "running_bugs": running_bugs,
        "done_bugs": done_bugs,
        "failed_bugs": failed_bugs,
        "repositories": _repos(),
        "agents": list_agents(),
        "sync_sources": _sync_sources(),
        "jira_base_url": _jira_base_url(),
        "last_syncs": _last_sync_states(),
        "active_page": "bugs",
        "active_workspaces": [s for s in reconciled if s.get("session_status") == SessionStatus.ACTIVE.value and s.get("bug_id")],
    })


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/repositories")
async def api_repositories():
    return {"repositories": _repos()}


@app.get("/api/agents")
async def api_agents():
    return {"agents": list_agents()}


@app.get("/api/sessions")
async def api_sessions():
    sessions = list_sessions()
    return {"sessions": reconcile_sessions(sessions)}


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    all_sessions = list_sessions()
    rec = {s["session_id"]: s for s in reconcile_sessions(all_sessions)}
    data = rec.get(session_id, session.model_dump())
    if session.bug_id:
        data["bug"] = get_bug(session.bug_id)
    return data


@app.post("/api/sessions", status_code=201)
async def api_create_session(req: CreateSessionRequest):
    repos = []
    for r in req.repositories:
        found = _get_repo(r)
        if not found:
            raise HTTPException(status_code=400, detail=f"Unknown repository: {r}")
        repos.append(found)

    if not validate_agent(req.agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent}")

    if not tmux_manager.is_installed():
        raise HTTPException(status_code=500, detail="tmux is not installed")

    bug_id = req.bug_id
    if bug_id:
        if not get_bug(bug_id):
            raise HTTPException(status_code=404, detail=f"Bug not found: {bug_id}")

    _VALID_SESSION_TYPES = {"empty", "list-bugs", "fix-bug", "fix-bugs", "sync-bugs", "code-review", "plans", "execute-plan"}
    raw_type = (req.session_type or "").strip().lower().replace(" ", "-")
    session_type = raw_type if raw_type in _VALID_SESSION_TYPES else req.session_type

    if not session_type and req.start_command:
        cmd_word = req.start_command.strip().lstrip("/").split()[0].lower()
        if cmd_word in _VALID_SESSION_TYPES:
            session_type = cmd_word

    work_dir = repos[0]["abs_path"] if repos else str(BASE_DIR)
    session = create_session(req.repositories, req.agent, bug_id, session_type, req.start_command)

    if not tmux_manager.create_session(session.tmux_session, work_dir, _env_for_tmux()):
        remove_session(session.session_id)
        raise HTTPException(status_code=500, detail="Failed to create tmux session")

    try:
        cmd = get_agent_command(req.agent)
    except ValueError as e:
        tmux_manager.kill_session(session.tmux_session)
        remove_session(session.session_id)
        raise HTTPException(status_code=400, detail=str(e))

    if not tmux_manager.send_keys(session.tmux_session, cmd, enter=True):
        tmux_manager.kill_session(session.tmux_session)
        remove_session(session.session_id)
        raise HTTPException(status_code=500, detail="Failed to start agent")

    update_session(session.session_id, session_status=SessionStatus.ACTIVE.value)

    if bug_id:
        touch_heartbeat(bug_id)

    # Persist agent into state.json for execute-plan sessions so Resume can restore it
    if session_type == "execute-plan" and req.start_command:
        parts = req.start_command.strip().split(None, 1)
        if len(parts) == 2:
            plan_id = parts[1].strip()
            plan_state_path = BASE_DIR / "plans" / plan_id / "state.json"
            if plan_state_path.parent.exists():
                existing = read_json_safe(plan_state_path, {}) or {}
                existing["agent"] = req.agent
                atomic_write_json(plan_state_path, existing)

    if req.start_command:
        delay = 7.0 if session_type == "code-review" else 4.0
        is_opencode = req.agent == "opencode"
        enter_delay = 1.5 if is_opencode else 0.3
        asyncio.create_task(_delayed_send(
            session.tmux_session, req.start_command,
            delay=delay, enter_delay=enter_delay, double_enter=is_opencode,
        ))

    return {
        "session_id": session.session_id,
        "repositories": session.repositories,
        "agent": session.agent,
        "tmux_session": session.tmux_session,
        "bug_id": bug_id,
        "status": SessionStatus.ACTIVE.value,
    }


@app.post("/api/sessions/{session_id}/resume", status_code=201)
async def api_resume_session(session_id: str, req: ResumeSessionRequest):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.bug_id:
        raise HTTPException(status_code=400, detail="Session has no associated bug")

    agent = req.agent or session.agent
    if not validate_agent(agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent}")

    primary_repo = _get_repo(session.repository) if session.repository else None
    work_dir = primary_repo["abs_path"] if primary_repo else str(BASE_DIR)

    new_sess = create_session(session.repositories, agent, session.bug_id)

    if not tmux_manager.create_session(new_sess.tmux_session, work_dir, _env_for_tmux()):
        remove_session(new_sess.session_id)
        raise HTTPException(status_code=500, detail="Failed to create tmux session")

    try:
        cmd = get_agent_command(agent)
    except ValueError as e:
        tmux_manager.kill_session(new_sess.tmux_session)
        remove_session(new_sess.session_id)
        raise HTTPException(status_code=400, detail=str(e))

    if not tmux_manager.send_keys(new_sess.tmux_session, cmd, enter=True):
        tmux_manager.kill_session(new_sess.tmux_session)
        remove_session(new_sess.session_id)
        raise HTTPException(status_code=500, detail="Failed to start agent")

    update_session(new_sess.session_id, session_status=SessionStatus.ACTIVE.value)
    touch_heartbeat(session.bug_id)

    # Replay the original start_command so the skill resumes automatically
    resume_cmd = req.start_command or session.start_command
    if resume_cmd:
        is_opencode = agent == "opencode"
        enter_delay = 1.5 if is_opencode else 0.3
        asyncio.create_task(_delayed_send(
            new_sess.tmux_session, resume_cmd,
            delay=6.0, enter_delay=enter_delay, double_enter=is_opencode,
        ))

    return {
        "new_session_id": new_sess.session_id,
        "original_session_id": session_id,
        "bug_id": session.bug_id,
        "start_command": resume_cmd,
        "status": SessionStatus.ACTIVE.value,
    }


@app.post("/api/sessions/{session_id}/close")
async def api_close_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    tmux_manager.kill_session(session.tmux_session)
    archive_session(session_id)
    return {"ok": True, "session_id": session_id}


@app.get("/api/bugs")
async def api_bugs():
    return {"bugs": list_bugs()}


@app.get("/api/bugs/{bug_id}")
async def api_get_bug(bug_id: str):
    bug = get_bug(bug_id)
    if not bug:
        raise HTTPException(status_code=404, detail="Bug not found")
    return bug


@app.get("/api/bugs/{bug_id}/status")
async def api_bug_status(bug_id: str):
    status = get_bug_status(bug_id)
    if not status:
        raise HTTPException(status_code=404, detail="Bug not found")
    return {"status": status.status, "current_step": status.current_step, "updated_at": status.updated_at}


@app.get("/api/bugs/{bug_id}/sessions")
async def api_bug_sessions(bug_id: str):
    bug_sessions = [s for s in list_sessions() if s.bug_id == bug_id]
    return {"sessions": reconcile_sessions(bug_sessions)}


class SyncBugsRequest(BaseModel):
    sources: list[str]
    project: Optional[str] = None
    top: int = 10
    agent: Optional[str] = None


@app.post("/api/bugs/sync", status_code=201)
async def api_sync_bugs(req: SyncBugsRequest):
    integrations = read_json_safe(settings.integrations_config, {})
    top = max(1, min(100, req.top))

    sync_days = 0
    for src in req.sources:
        cfg = integrations.get(src, {})
        if not cfg.get("sync_bug_source"):
            raise HTTPException(status_code=400, detail=f"Source '{src}' is not enabled for sync")
        sync_days = max(sync_days, cfg.get("sync_days", 2))

    parts = [f"/list-bugs source={','.join(req.sources)}"]
    if req.project:
        parts.append(f"project={req.project}")
    parts.append(f"top={top}")
    if sync_days:
        parts.append(f"days={sync_days}")
    command = " ".join(parts)

    agents = list_agents()
    agent_id = req.agent or next(
        (a["id"] for a in agents if a["id"] == "claude"),
        agents[0]["id"] if agents else "claude",
    )
    if not validate_agent(agent_id):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_id}")
    if not tmux_manager.is_installed():
        raise HTTPException(status_code=500, detail="tmux is not installed")

    session = create_session([], agent_id, None, "sync-bugs")
    if not tmux_manager.create_session(session.tmux_session, str(BASE_DIR), _env_for_tmux()):
        remove_session(session.session_id)
        raise HTTPException(status_code=500, detail="Failed to create tmux session")

    try:
        agent_cmd = get_agent_command(agent_id)
    except ValueError as e:
        tmux_manager.kill_session(session.tmux_session)
        remove_session(session.session_id)
        raise HTTPException(status_code=400, detail=str(e))

    if not tmux_manager.send_keys(session.tmux_session, agent_cmd, enter=True):
        tmux_manager.kill_session(session.tmux_session)
        remove_session(session.session_id)
        raise HTTPException(status_code=500, detail="Failed to start agent")

    update_session(session.session_id, session_status=SessionStatus.ACTIVE.value)
    asyncio.create_task(_delayed_send(session.tmux_session, command))

    return {"sessions": [session.session_id]}


@app.get("/api/sessions/{session_id}/preview")
async def api_session_preview(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    from .reconciliation import _strip_ansi
    preview = ""
    if tmux_manager.has_session(session.tmux_session):
        preview = _strip_ansi(tmux_manager.capture_pane(session.tmux_session, 20)).strip()
    return {"preview": preview}


# ── WebSocket ─────────────────────────────────────────────────────────────────

_SLUG_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def _derive_plan_slug(title: str) -> str:
    """`YYYYMMDD-<3-6 kebab words>`, with a `-N` counter appended on collision."""
    import re
    from datetime import date

    words = re.findall(r"[a-zA-Z0-9]+", (title or "").lower())[:6] or ["plan"]
    base = f"{date.today().strftime('%Y%m%d')}-{'-'.join(words)}"[:80]
    plans_dir = BASE_DIR / "plans"
    candidate = base
    i = 2
    while (plans_dir / candidate).exists():
        candidate = f"{base}-{i}"[:80]
        i += 1
    return candidate


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _ReservePlanReq(BaseModel):
    title: str


@app.post("/api/plans/reserve")
async def reserve_plan_slug(req: _ReservePlanReq):
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    slug = _derive_plan_slug(title)
    plan_dir = BASE_DIR / "plans" / slug
    plan_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(plan_dir / "status.json", {
        "phase": 0,
        "phase_label": "Reserved",
        "sub_status": "running",
        "plan_slug": slug,
        "title": title,
        "updated_at": _now_iso(),
    })
    return {"plan_slug": slug}


@app.get("/api/plans/{plan_slug}/status")
async def get_plan_status(plan_slug: str):
    """Filesystem-inferred status. No skill heartbeat required — we look at what
    files exist under plans/<slug>/ and derive done vs. in-progress from that."""
    if not _SLUG_RE.match(plan_slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    plan_dir = BASE_DIR / "plans" / plan_slug
    if not plan_dir.exists():
        raise HTTPException(status_code=404, detail="Plan not reserved")

    seed = read_json_safe(plan_dir / "status.json", {}) or {}
    plan_json_exists  = (plan_dir / "plan.json").exists()
    plan_md_exists    = (plan_dir / "plan.md").exists()
    state_json_exists = (plan_dir / "state.json").exists()
    all_files_written = plan_json_exists and plan_md_exists and state_json_exists

    if all_files_written:
        phase, phase_label, sub_status = 6, "Assembly", "done"
    else:
        phase = int(seed.get("phase") or 0)
        phase_label = seed.get("phase_label") or "Reserved"
        sub_status = seed.get("sub_status") or "running"

    return {
        "plan_slug": plan_slug,
        "title": seed.get("title", ""),
        "phase": phase,
        "phase_label": phase_label,
        "sub_status": sub_status,
        "files": {
            "plan_json": plan_json_exists,
            "plan_md": plan_md_exists,
            "state_json": state_json_exists,
        },
        "checked_at": _now_iso(),
    }


@app.get("/api/plans/{plan_slug}/log")
async def get_plan_log(plan_slug: str):
    if not _SLUG_RE.match(plan_slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    plan_dir = BASE_DIR / "plans" / plan_slug
    log_file = plan_dir / "log.md"
    if not log_file.exists():
        return {"content": None, "exists": False}
    content = log_file.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "exists": True}


@app.websocket("/ws/plan-terminal")
async def ws_plan_terminal(websocket: WebSocket, agent: str = "claude", plan_slug: str = "", mode: str = "tmux"):
    import shlex
    try:
        cmd_str = get_agent_command(agent)
    except ValueError:
        cmd_str = get_agent_command("claude") or "claude --dangerously-skip-permissions"
    if mode == "tmux" and plan_slug and _SLUG_RE.match(plan_slug):
        plan_dir = BASE_DIR / "plans" / plan_slug
        if plan_dir.exists():
            # Use a persistent tmux session so WebSocket reconnects reattach rather than
            # killing and restarting Claude Code mid-plan.
            tmux_name = f"plan-{plan_slug}"
            plan_env = {
                **_env_for_tmux(),
                "AI_ORCH_PLAN_SLUG": plan_slug,
                "AI_ORCH_PLAN_DIR": str(plan_dir),
            }
            if not tmux_manager.has_session(tmux_name):
                # First connect: create tmux session, register in sessions.json, start agent
                tmux_manager.create_session(tmux_name, str(BASE_DIR), plan_env)
                existing = get_session_by_tmux(tmux_name)
                if not existing:
                    sess = create_session(
                        repositories=[],
                        agent=agent,
                        session_type="plans",
                        start_command=f"/create-plan",
                        tmux_session=tmux_name,
                    )
                    update_session(sess.session_id, session_status=SessionStatus.ACTIVE.value)
                tmux_manager.send_keys(tmux_name, cmd_str, enter=True)
            await handle_terminal_websocket(websocket, tmux_name)
            return

    # Direct PTY: ephemeral, full scrollback, no reconnect
    extra_env: dict = {}
    if plan_slug and _SLUG_RE.match(plan_slug):
        plan_dir = BASE_DIR / "plans" / plan_slug
        if plan_dir.exists():
            extra_env["AI_ORCH_PLAN_SLUG"] = plan_slug
            extra_env["AI_ORCH_PLAN_DIR"] = str(plan_dir)
    await handle_direct_websocket(
        websocket, shlex.split(cmd_str), str(BASE_DIR), extra_env=extra_env or None,
    )


@app.websocket("/ws/sessions/{session_id}")
async def ws_terminal(websocket: WebSocket, session_id: str):
    session = get_session(session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        return
    if not tmux_manager.has_session(session.tmux_session):
        await websocket.close(code=1008, reason="tmux session not found")
        return
    await handle_terminal_websocket(websocket, session.tmux_session)
