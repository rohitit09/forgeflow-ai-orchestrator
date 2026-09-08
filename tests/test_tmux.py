"""Tests for tmux manager — mocked so tmux need not be installed."""
from unittest.mock import MagicMock, patch

import pytest

from app import tmux_manager


@patch("app.tmux_manager._run")
def test_is_installed_true(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert tmux_manager.is_installed() is True


@patch("app.tmux_manager._run")
def test_is_installed_false(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    assert tmux_manager.is_installed() is False


@patch("app.tmux_manager._run")
def test_has_session_true(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert tmux_manager.has_session("bugfix-sess-abc") is True


@patch("app.tmux_manager._run")
def test_has_session_false(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    assert tmux_manager.has_session("bugfix-missing") is False


@patch("app.tmux_manager._run")
def test_create_session_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert tmux_manager.create_session("bugfix-sess-test", "/tmp") is True


@patch("app.tmux_manager._run")
def test_create_session_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    assert tmux_manager.create_session("bugfix-sess-fail") is False


@patch("app.tmux_manager._run")
def test_kill_session(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert tmux_manager.kill_session("bugfix-sess-test") is True


@patch("app.tmux_manager._run")
def test_send_keys(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert tmux_manager.send_keys("bugfix-sess-test", "claude", enter=True) is True
    args = mock_run.call_args[0][0]
    assert "send-keys" in args
    assert "Enter" in args


@patch("app.tmux_manager._run")
def test_list_sessions(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="sess-a\nbugfix-sess-b\n")
    result = tmux_manager.list_sessions()
    assert "sess-a" in result
    assert "bugfix-sess-b" in result


@patch("app.tmux_manager._run")
def test_list_sessions_empty_on_error(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    assert tmux_manager.list_sessions() == []


@patch("app.tmux_manager._run")
def test_capture_pane(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="some terminal output\n")
    out = tmux_manager.capture_pane("bugfix-sess-test", lines=20)
    assert "some terminal output" in out
