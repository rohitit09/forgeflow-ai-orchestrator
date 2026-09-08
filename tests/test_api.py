"""Integration tests for the REST API (no real tmux or agent required)."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    old_base = settings._base_dir
    settings._base_dir = tmp_path
    settings._init_derived()
    settings._bootstrap()
    yield
    settings._base_dir = old_base
    settings._init_derived()


def test_get_repositories():
    r = client.get("/api/repositories")
    assert r.status_code == 200
    assert "repositories" in r.json()


def test_get_agents():
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert "agents" in r.json()


def test_get_sessions_empty():
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json()["sessions"] == []


_MOCK_REPO = {"id": "backend", "name": "Backend", "path": "workspace/backend", "abs_path": "/tmp/backend"}


@patch("app.main.tmux_manager.is_installed", return_value=True)
@patch("app.main.tmux_manager.create_session", return_value=True)
@patch("app.main.tmux_manager.send_keys", return_value=True)
@patch("app.main.tmux_manager.has_session", return_value=True)
@patch("app.main._get_repo", return_value=_MOCK_REPO)
@patch("app.main.validate_agent", return_value=True)
@patch("app.main.get_agent_command", return_value="claude")
def test_create_session(mock_cmd, mock_val, mock_repo, mock_has, mock_keys, mock_create, mock_inst):
    r = client.post("/api/sessions", json={"repository": "backend", "agent": "claude"})
    assert r.status_code == 201
    data = r.json()
    assert "session_id" in data
    assert data["status"] == "ACTIVE"


@patch("app.main.tmux_manager.is_installed", return_value=True)
@patch("app.main.tmux_manager.create_session", return_value=False)
@patch("app.main._get_repo", return_value=_MOCK_REPO)
@patch("app.main.validate_agent", return_value=True)
def test_create_session_tmux_failure(mock_val, mock_repo, mock_create, mock_inst):
    r = client.post("/api/sessions", json={"repository": "backend", "agent": "claude"})
    assert r.status_code == 500


def test_create_session_unknown_repository():
    r = client.post("/api/sessions", json={"repository": "nonexistent", "agent": "claude"})
    assert r.status_code == 400


def test_create_session_unknown_agent():
    with patch("app.main._get_repo", return_value=_MOCK_REPO):
        r = client.post("/api/sessions", json={"repository": "backend", "agent": "badagent"})
    assert r.status_code == 400


def test_get_session_not_found():
    r = client.get("/api/sessions/sess-doesnotexist")
    assert r.status_code == 404


@patch("app.main.tmux_manager.is_installed", return_value=True)
@patch("app.main.tmux_manager.create_session", return_value=True)
@patch("app.main.tmux_manager.send_keys", return_value=True)
@patch("app.main.tmux_manager.has_session", return_value=True)
@patch("app.main._get_repo", return_value=_MOCK_REPO)
@patch("app.main.validate_agent", return_value=True)
@patch("app.main.get_agent_command", return_value="claude")
def test_close_session(mock_cmd, mock_val, mock_repo, mock_has, mock_keys, mock_create, mock_inst):
    r = client.post("/api/sessions", json={"repository": "backend", "agent": "claude"})
    assert r.status_code == 201
    sid = r.json()["session_id"]
    with patch("app.main.tmux_manager.kill_session", return_value=True):
        close_r = client.post(f"/api/sessions/{sid}/close")
    assert close_r.status_code == 200


def test_index_page():
    r = client.get("/")
    assert r.status_code == 200
    assert b"Orchestrator" in r.content


def test_session_page_not_found():
    r = client.get("/sessions/sess-ghost")
    assert r.status_code == 404


def test_bugs_api_empty():
    r = client.get("/api/bugs")
    assert r.status_code == 200
    assert r.json()["bugs"] == []


def test_bug_not_found():
    r = client.get("/api/bugs/bug-notexist")
    assert r.status_code == 404
