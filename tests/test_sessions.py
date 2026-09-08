"""Tests for session registry — filesystem persistence and concurrent safety."""
import json
import threading

import pytest

from app.config import settings
from app.models import SessionStatus
from app.session_manager import (
    create_session, get_session, list_sessions, remove_session, update_session,
)


@pytest.fixture(autouse=True)
def clean_registry(tmp_path):
    """Redirect session registry to a temp directory for each test."""
    old_base = settings._base_dir
    old_config = settings.config_dir

    settings._base_dir = tmp_path
    settings._init_derived()
    settings._bootstrap()

    yield

    settings._base_dir = old_base
    settings._init_derived()


def test_create_session_returns_record():
    s = create_session("backend", "claude")
    assert s.session_id.startswith("sess-")
    assert s.tmux_session.startswith("bugfix-")
    assert s.repository == "backend"
    assert s.agent == "claude"
    assert s.status == SessionStatus.CREATED


def test_create_session_persists():
    s = create_session("frontend", "opencode")
    data = json.loads(settings.sessions_file.read_text())
    ids = [r["session_id"] for r in data["sessions"]]
    assert s.session_id in ids


def test_get_session_returns_record():
    s = create_session("backend", "claude")
    fetched = get_session(s.session_id)
    assert fetched is not None
    assert fetched.session_id == s.session_id


def test_get_session_unknown_returns_none():
    assert get_session("sess-doesnotexist") is None


def test_list_sessions_empty():
    assert list_sessions() == []


def test_list_sessions_multiple():
    create_session("backend", "claude")
    create_session("frontend", "opencode")
    assert len(list_sessions()) == 2


def test_update_session_status():
    s = create_session("backend", "claude")
    updated = update_session(s.session_id, status=SessionStatus.ACTIVE.value)
    assert updated is not None
    assert updated.status == SessionStatus.ACTIVE


def test_remove_session():
    s = create_session("backend", "claude")
    assert remove_session(s.session_id) is True
    assert get_session(s.session_id) is None


def test_remove_nonexistent_session():
    assert remove_session("sess-ghost") is False


def test_session_with_bug_id():
    s = create_session("backend", "claude", bug_id="bug-abc123")
    fetched = get_session(s.session_id)
    assert fetched.bug_id == "bug-abc123"


def test_concurrent_session_creation():
    """Multiple threads must not corrupt sessions.json."""
    results = []
    errors = []

    def worker():
        try:
            s = create_session("backend", "claude")
            results.append(s.session_id)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == 10
    assert len(set(results)) == 10  # All IDs unique
    data = json.loads(settings.sessions_file.read_text())
    assert len(data["sessions"]) == 10


def test_registry_survives_unknown_extra_fields():
    """Extra fields in sessions.json are silently ignored."""
    data = {
        "sessions": [
            {
                "session_id": "sess-abc123",
                "repository": "backend",
                "agent": "claude",
                "tmux_session": "bugfix-sess-abc123",
                "created_at": "2026-01-01T00:00:00+00:00",
                "extra_field": "ignored",
            }
        ]
    }
    settings.sessions_file.write_text(json.dumps(data), encoding="utf-8")
    sessions = list_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "sess-abc123"
