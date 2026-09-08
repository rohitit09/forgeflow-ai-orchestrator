from enum import Enum
from typing import Optional

from pydantic import BaseModel, model_validator


class SessionStatus(str, Enum):
    CREATED     = "CREATED"
    ACTIVE      = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED   = "COMPLETED"
    FAILED      = "FAILED"
    STALE       = "STALE"


class BugStatus(str, Enum):
    # ── Fetch phase ───────────────────────────────────────────────────────────
    FETCHED          = "FETCHED"          # pulled from Sentry/Jira, saved to bugs/
    QUEUED           = "QUEUED"           # waiting to be fixed

    # ── Setup phase ──────────────────────────────────────────────────────────
    SYNCING          = "SYNCING"          # syncing base branch (staging)
    SYNCED           = "SYNCED"           # base branch is up to date
    JIRA_CREATING    = "JIRA_CREATING"    # creating Jira ticket (for Sentry bugs)
    JIRA_CREATED     = "JIRA_CREATED"     # Jira ticket exists
    BRANCHING        = "BRANCHING"        # creating feature branch
    BRANCHED         = "BRANCHED"         # branch bug-JAR-XXXX-desc created
    WORKTREE_READY   = "WORKTREE_READY"   # git worktree inside bugs/<id>/worktree/

    # ── Analysis phase ───────────────────────────────────────────────────────
    DIAGNOSING       = "DIAGNOSING"       # investigating root cause
    DIAGNOSED        = "DIAGNOSED"        # diagnosis.md written

    # ── Planning phase ───────────────────────────────────────────────────────
    PLANNING         = "PLANNING"         # creating fix plan
    PLANNED          = "PLANNED"          # plan.md saved, Jira updated

    # ── Fix phase ────────────────────────────────────────────────────────────
    IMPLEMENTING     = "IMPLEMENTING"     # writing the fix
    IMPLEMENTED      = "IMPLEMENTED"      # code changes committed

    # ── Verification phase ───────────────────────────────────────────────────
    TESTING          = "TESTING"          # running tests
    TESTED           = "TESTED"           # all tests passing
    TEST_SKIPPED     = "TEST_SKIPPED"     # test=false or test_cmd missing in repositories.json

    # ── Delivery phase ───────────────────────────────────────────────────────
    PR_CREATING      = "PR_CREATING"      # running gh pr create
    PR_CREATED       = "PR_CREATED"       # PR open on GitHub
    JIRA_UPDATING    = "JIRA_UPDATING"    # posting PR link + summary to Jira
    JIRA_UPDATED     = "JIRA_UPDATED"     # Jira updated

    # ── Terminal states ──────────────────────────────────────────────────────
    DONE             = "DONE"             # everything complete
    FAILED           = "FAILED"           # unrecoverable failure
    BLOCKED          = "BLOCKED"          # needs human intervention



class BugSource(str, Enum):
    SENTRY = "sentry"
    JIRA   = "jira"


class SessionRecord(BaseModel):
    session_id:    str
    repositories:  list[str] = []
    agent:         str
    tmux_session:  str
    created_at:    str
    bug_id:        Optional[str] = None
    session_type:  Optional[str] = None
    start_command: Optional[str] = None
    status:        SessionStatus = SessionStatus.CREATED
    session_status: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_repository(cls, data: dict) -> dict:
        if isinstance(data, dict) and "repositories" not in data:
            r = data.get("repository") or ""
            data["repositories"] = [r] if r else []
        return data

    @property
    def repository(self) -> Optional[str]:
        return self.repositories[0] if self.repositories else None


class BugStatusData(BaseModel):
    bug_id:         str
    source:         Optional[str] = None
    source_id:      Optional[str] = None
    severity:       Optional[str] = None
    status:         BugStatus = BugStatus.FETCHED
    current_step:   Optional[str] = None
    next_step:      Optional[str] = None
    branch:         Optional[str] = None
    repos:          list[str] = []
    jira_ticket:    Optional[str] = None
    pr_url:         Optional[str] = None
    session_id:     Optional[str] = None
    last_heartbeat: Optional[str] = None
    updated_at:     Optional[str] = None
    error:          Optional[str] = None


class CreateSessionRequest(BaseModel):
    repositories:  list[str] = []
    agent:         str
    bug_id:        Optional[str] = None
    session_type:  Optional[str] = None
    start_command: Optional[str] = None


class ResumeSessionRequest(BaseModel):
    agent: Optional[str] = None
