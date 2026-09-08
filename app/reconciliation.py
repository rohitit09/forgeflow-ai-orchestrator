import re
from datetime import datetime, timedelta, timezone

from . import tmux_manager
from .bug_manager import get_bug_status
from .models import BugStatus, SessionRecord, SessionStatus

STALE_MINUTES = 30
ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

_TERMINAL_STATUSES = {BugStatus.DONE, BugStatus.FAILED}


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _is_stale(heartbeat_iso: str) -> bool:
    try:
        hb = datetime.fromisoformat(heartbeat_iso.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - hb > timedelta(minutes=STALE_MINUTES)
    except (ValueError, AttributeError):
        return False


def derive_session_status(session: SessionRecord) -> SessionStatus:
    tmux_alive = tmux_manager.has_session(session.tmux_session)

    bug_status: BugStatus | None = None
    last_heartbeat: str | None = None
    if session.bug_id:
        bsd = get_bug_status(session.bug_id)
        if bsd:
            bug_status = bsd.status
            last_heartbeat = bsd.last_heartbeat

    if tmux_alive:
        if bug_status in _TERMINAL_STATUSES:
            return SessionStatus.COMPLETED
        if last_heartbeat and _is_stale(last_heartbeat):
            return SessionStatus.STALE
        return SessionStatus.ACTIVE

    # tmux is dead — respect explicitly stored terminal statuses
    if session.session_status == SessionStatus.COMPLETED.value:
        return SessionStatus.COMPLETED

    if bug_status in _TERMINAL_STATUSES:
        return SessionStatus.COMPLETED

    if bug_status is not None:
        return SessionStatus.INTERRUPTED

    return SessionStatus.DISCONNECTED


def reconcile_sessions(sessions: list[SessionRecord]) -> list[dict]:
    result = []
    for s in sessions:
        status = derive_session_status(s)
        tmux_alive = tmux_manager.has_session(s.tmux_session)

        bug_data: dict | None = None
        if s.bug_id:
            bsd = get_bug_status(s.bug_id)
            bug_data = bsd.model_dump() if bsd else None

        preview = ""
        if tmux_alive:
            raw = tmux_manager.capture_pane(s.tmux_session, lines=15)
            preview = _strip_ansi(raw).strip()

        result.append({
            **s.model_dump(),
            "session_status": status.value,
            "tmux_exists": tmux_alive,
            "bug_data": bug_data,
            "terminal_preview": preview,
            "repository": ", ".join(s.repositories) if s.repositories else "",
        })
    return result
