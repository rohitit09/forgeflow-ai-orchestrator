import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import settings
from .filesystem import FileLock, atomic_write_json, read_json_safe
from .models import SessionRecord, SessionStatus


def _new_session_id() -> str:
    return f"sess-{uuid.uuid4().hex[:6]}"


def _tmux_name(session_id: str) -> str:
    return f"bugfix-{session_id}"


def _load_registry() -> dict:
    data = read_json_safe(settings.sessions_file, {"sessions": []})
    if not isinstance(data, dict) or "sessions" not in data:
        return {"sessions": []}
    return data


def _save_registry(reg: dict) -> None:
    atomic_write_json(settings.sessions_file, reg)


def get_session_by_tmux(tmux_name: str) -> Optional[SessionRecord]:
    reg = _load_registry()
    for s in reg["sessions"]:
        if s.get("tmux_session") == tmux_name:
            try:
                return SessionRecord(**s)
            except Exception:
                return None
    return None


def create_session(
    repositories: list[str],
    agent: str,
    bug_id: Optional[str] = None,
    session_type: Optional[str] = None,
    start_command: Optional[str] = None,
    tmux_session: Optional[str] = None,
) -> SessionRecord:
    session_id = _new_session_id()
    tmux_session = tmux_session or _tmux_name(session_id)
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "session_id": session_id,
        "repositories": repositories,
        "agent": agent,
        "tmux_session": tmux_session,
        "created_at": now,
        "bug_id": bug_id,
        "session_type": session_type,
        "start_command": start_command,
        "status": SessionStatus.CREATED.value,
    }

    with FileLock(settings.sessions_file):
        reg = _load_registry()
        reg["sessions"].append(record)
        _save_registry(reg)

    return SessionRecord(**record)


def get_session(session_id: str) -> Optional[SessionRecord]:
    reg = _load_registry()
    for s in reg["sessions"]:
        if s.get("session_id") == session_id:
            try:
                return SessionRecord(**s)
            except Exception:
                return None
    return None


def update_session(session_id: str, **kwargs) -> Optional[SessionRecord]:
    with FileLock(settings.sessions_file):
        reg = _load_registry()
        for i, s in enumerate(reg["sessions"]):
            if s.get("session_id") == session_id:
                reg["sessions"][i].update(kwargs)
                _save_registry(reg)
                try:
                    return SessionRecord(**reg["sessions"][i])
                except Exception:
                    return None
    return None


def list_sessions() -> list[SessionRecord]:
    reg = _load_registry()
    result = []
    for s in reg["sessions"]:
        try:
            result.append(SessionRecord(**s))
        except Exception:
            pass
    return result


def remove_session(session_id: str) -> bool:
    with FileLock(settings.sessions_file):
        reg = _load_registry()
        before = len(reg["sessions"])
        reg["sessions"] = [s for s in reg["sessions"] if s.get("session_id") != session_id]
        if len(reg["sessions"]) < before:
            _save_registry(reg)
            return True
    return False


def _load_history() -> dict:
    data = read_json_safe(settings.sessions_history_file, {"sessions": []})
    if not isinstance(data, dict) or "sessions" not in data:
        return {"sessions": []}
    return data


def _save_history(reg: dict) -> None:
    atomic_write_json(settings.sessions_history_file, reg)


def archive_session(session_id: str, status: str = SessionStatus.COMPLETED.value) -> bool:
    """Move a session from sessions.json to sessions_history.json."""
    with FileLock(settings.sessions_file):
        reg = _load_registry()
        target = next((s for s in reg["sessions"] if s.get("session_id") == session_id), None)
        if not target:
            return False
        reg["sessions"] = [s for s in reg["sessions"] if s.get("session_id") != session_id]
        _save_registry(reg)

    record = dict(target)
    record["session_status"] = status
    with FileLock(settings.sessions_history_file):
        hist = _load_history()
        hist["sessions"].append(record)
        _save_history(hist)
    return True


def list_closed_sessions() -> list[dict]:
    hist = _load_history()
    return hist.get("sessions", [])
