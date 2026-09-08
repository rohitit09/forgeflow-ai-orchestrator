"""Tests for session reconciliation logic."""
from unittest.mock import MagicMock, patch

import pytest

from app.models import BugStatus, SessionRecord, SessionStatus
from app.reconciliation import derive_session_status


def _session(**kwargs) -> SessionRecord:
    defaults = dict(
        session_id="sess-test",
        repository="backend",
        agent="claude",
        tmux_session="bugfix-sess-test",
        created_at="2026-01-01T00:00:00+00:00",
        bug_id=None,
        status=SessionStatus.CREATED,
    )
    defaults.update(kwargs)
    return SessionRecord(**defaults)


@patch("app.reconciliation.tmux_manager.has_session", return_value=True)
@patch("app.reconciliation.get_bug_status", return_value=None)
def test_active_when_tmux_alive_no_bug(mock_bug, mock_tmux):
    s = _session()
    assert derive_session_status(s) == SessionStatus.ACTIVE


@patch("app.reconciliation.tmux_manager.has_session", return_value=False)
@patch("app.reconciliation.get_bug_status", return_value=None)
def test_disconnected_when_tmux_missing_no_bug(mock_bug, mock_tmux):
    s = _session()
    assert derive_session_status(s) == SessionStatus.DISCONNECTED


@patch("app.reconciliation.tmux_manager.has_session", return_value=False)
@patch("app.reconciliation.get_bug_status")
def test_completed_when_tmux_missing_bug_done(mock_bug, mock_tmux):
    mock_bug.return_value = MagicMock(
        status=BugStatus.DONE, last_heartbeat="2026-01-01T00:00:00+00:00"
    )
    s = _session(bug_id="bug-abc")
    assert derive_session_status(s) == SessionStatus.COMPLETED


@patch("app.reconciliation.tmux_manager.has_session", return_value=False)
@patch("app.reconciliation.get_bug_status")
def test_interrupted_when_tmux_missing_bug_in_progress(mock_bug, mock_tmux):
    mock_bug.return_value = MagicMock(
        status=BugStatus.TESTING, last_heartbeat="2026-01-01T00:00:00+00:00"
    )
    s = _session(bug_id="bug-abc")
    assert derive_session_status(s) == SessionStatus.INTERRUPTED


@patch("app.reconciliation.tmux_manager.has_session", return_value=True)
@patch("app.reconciliation.get_bug_status")
def test_stale_when_tmux_alive_but_heartbeat_old(mock_bug, mock_tmux):
    mock_bug.return_value = MagicMock(
        status=BugStatus.IMPLEMENTING,
        last_heartbeat="2020-01-01T00:00:00+00:00",  # Very old
    )
    s = _session(bug_id="bug-abc")
    assert derive_session_status(s) == SessionStatus.STALE


@patch("app.reconciliation.tmux_manager.has_session", return_value=False)
@patch("app.reconciliation.get_bug_status")
def test_completed_on_failed_bug(mock_bug, mock_tmux):
    mock_bug.return_value = MagicMock(
        status=BugStatus.FAILED, last_heartbeat=None
    )
    s = _session(bug_id="bug-abc")
    assert derive_session_status(s) == SessionStatus.COMPLETED
