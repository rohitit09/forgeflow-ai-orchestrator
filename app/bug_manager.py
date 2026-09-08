from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import settings
from .filesystem import append_jsonl, atomic_write_json, read_json_safe, read_jsonl
from .models import BugStatus, BugStatusData


def _bug_dir(bug_id: str) -> Path:
    """bugs/<bug-id>/ lives at project root, NOT inside workspace/."""
    return settings.bugs_dir / bug_id


def _worktree_dir(bug_id: str) -> Path:
    """bugs/<bug-id>/worktree/"""
    return _bug_dir(bug_id) / "worktree"


# ── Read helpers ──────────────────────────────────────────────────────────────

def get_bug(bug_id: str) -> Optional[dict]:
    d = _bug_dir(bug_id)
    bug = read_json_safe(d / "bug.json")
    if not bug:
        return None
    status = read_json_safe(d / "status.json", {})
    result = read_json_safe(d / "result.json")
    plan_summary = read_json_safe(d / "plan_summary.json")

    def _md(name: str) -> Optional[str]:
        p = d / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    return {
        **bug,
        "status_data": status,
        "result": result,
        "plan": _md("plan.md"),
        "plan_summary": plan_summary,
        "diagnosis": _md("diagnosis.md"),
        "analysis_backend": _md("analysis-backend.md"),
        "analysis_frontend": _md("analysis-frontend.md"),
    }


def get_bug_status(bug_id: str) -> Optional[BugStatusData]:
    raw = read_json_safe(_bug_dir(bug_id) / "status.json")
    if not raw:
        return None
    try:
        return BugStatusData(**raw)
    except Exception:
        return None


def list_bugs() -> list[dict]:
    if not settings.bugs_dir.exists():
        return []
    result = []
    for d in sorted(settings.bugs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        bug = read_json_safe(d / "bug.json")
        if bug:
            status = read_json_safe(d / "status.json", {})
            result.append({**bug, "status_data": status})
    return result


def touch_heartbeat(bug_id: str) -> None:
    """Reset last_heartbeat to now so a freshly created session isn't immediately STALE."""
    path = _bug_dir(bug_id) / "status.json"
    status = read_json_safe(path)
    if not status:
        return
    now = datetime.now(timezone.utc).isoformat()
    status["last_heartbeat"] = now
    status["updated_at"] = now
    atomic_write_json(path, status)


def _auto_summary(ev: dict) -> str:
    """Generate a human-readable summary from event fields when agent didn't write one."""
    name = ev.get("event", "")
    repos = ", ".join(ev.get("repos") or [])
    branch = ev.get("branch", "")
    jira = ev.get("jira_key") or ev.get("key", "")
    error = ev.get("error", "")
    reason = ev.get("reason", "")
    output = ev.get("output", "")
    commits = ev.get("commits") or {}
    pr_urls = ev.get("pr_urls") or {}

    commit_str = ", ".join(f"{r}: {h[:8]}" for r, h in commits.items()) if commits else ""
    pr_str = ", ".join(f"{r}" for r in pr_urls) if pr_urls else ""

    summaries: dict[str, str] = {
        "BUG_FETCHED":               f"Bug fetched from {ev.get('source','source')} and saved.",
        "BUG_REFETCHED":             f"Bug metadata refreshed ({', '.join(ev.get('fields_updated') or [])}).",
        "FIX_STARTED":               f"Fix workflow started for {ev.get('bug_id', '')}.",
        "ANALYSIS_DISPATCHED":       f"Analysis dispatched for {repos or 'repos'}.",
        "BACKEND_ANALYSIS_STARTED":  f"Backend analysis running on {repos or 'repo'}.",
        "BACKEND_ANALYSIS_COMPLETE": f"Backend analysis complete — written to {output or 'analysis-backend.md'}.",
        "FRONTEND_ANALYSIS_STARTED": f"Frontend analysis running on {repos or 'repo'}.",
        "FRONTEND_ANALYSIS_COMPLETE":f"Frontend analysis complete — written to {output or 'analysis-frontend.md'}.",
        "BRANCH_SYNCED":             f"Base branch synced for {repos or 'repos'} — ready for worktree.",
        "JIRA_TICKET_CREATED":       f"Jira ticket {jira} created.",
        "JIRA_TICKET_LINKED":        f"Linked to existing Jira ticket {jira}.",
        "DIAGNOSIS_COMPLETE":        f"Diagnosis complete — root cause identified in {repos or 'repo'}.",
        "DIAGNOSTIC_PRINTED":        "Diagnostic block written to diagnosis.md.",
        "PLAN_CREATED":              "Fix plan written to plan.md.",
        "JIRA_PLAN_POSTED":          f"Plan comment posted to {jira or 'Jira'}.",
        "BRANCH_CREATED":            f"Branch '{branch}' created.",
        "WORKTREE_CREATED":          f"Worktree ready at {ev.get('path', 'bugs/<id>/worktree/')}.",
        "IMPLEMENTATION_COMPLETE":   f"Code committed ({commit_str or 'see commits'}).",
        "TESTS_STARTED":             f"Running tests in {repos or 'repo'}.",
        "TEST_FAILED":               "Tests failed — will retry.",
        "TEST_RETRIED":              "Retrying tests.",
        "TESTS_PASSED":              f"All tests passing in {repos or 'repo'}.",
        "TESTS_SKIPPED":             f"Tests skipped — {reason or 'not configured in repositories.json'}.",
        "PR_CREATED":                f"PR opened for {pr_str or repos or 'repo'}.",
        "JIRA_UPDATED":              f"Jira {jira or 'ticket'} updated with fix details.",
        "JIRA_TRANSITIONED":         f"Jira {jira or 'ticket'} transitioned to In Review.",
        "BUG_COMPLETED":             "Fix complete — all steps done.",
        "BUG_FAILED":                f"Failed: {error or 'see error field'}.",
        "BUG_BLOCKED":               f"Blocked: {error or 'see error field'}.",
    }
    return summaries.get(name, name.replace("_", " ").title())


def get_bug_events(bug_id: str) -> list[dict]:
    events = read_jsonl(_bug_dir(bug_id) / "events.jsonl")
    for ev in events:
        if not ev.get("summary"):
            ev["summary"] = _auto_summary(ev)
    return events


def build_workflow_steps(
    events: list[dict],
    status_data: dict,
    plan_summary: Optional[dict] = None,
    result: Optional[dict] = None,
) -> dict:
    """Return 13 workflow steps (0–12) with status and rich per-step data for the UI."""
    em: dict = {}
    for ev in events:
        n = ev.get("event", "")
        if n:
            em.setdefault(n, ev)          # first occurrence
            em[f"_last_{n}"] = ev         # last occurrence

    STATUS_ORDER = [
        "FETCHED", "QUEUED", "SYNCING", "SYNCED", "JIRA_CREATING", "JIRA_CREATED",
        "DIAGNOSING", "DIAGNOSED", "PLANNING", "PLANNED", "BRANCHING", "BRANCHED",
        "WORKTREE_READY", "IMPLEMENTING", "IMPLEMENTED", "TESTING", "TESTED",
        "TEST_SKIPPED", "PR_CREATING", "PR_CREATED", "JIRA_UPDATING", "JIRA_UPDATED", "DONE",
    ]

    def _rank(s: str) -> int:
        try:
            return STATUS_ORDER.index(s)
        except ValueError:
            return -1

    cur = status_data.get("status", "FETCHED")
    cur_rank = _rank(cur)

    def _ts(ev: dict) -> str:
        return (ev.get("timestamp") or "")[:16].replace("T", " ")

    def _ev(*names: str) -> dict:
        for n in names:
            if n in em:
                return em[n]
        return {}

    fx  = _ev("FIX_STARTED")
    ad  = _ev("ANALYSIS_DISPATCHED")
    bas = _ev("BACKEND_ANALYSIS_STARTED")
    bac = _ev("BACKEND_ANALYSIS_COMPLETE")
    fas = _ev("FRONTEND_ANALYSIS_STARTED")
    fac = _ev("FRONTEND_ANALYSIS_COMPLETE")
    bs  = _ev("BRANCH_SYNCED")
    jte = _ev("JIRA_TICKET_CREATED", "JIRA_TICKET_LINKED")
    dc  = _ev("DIAGNOSIS_COMPLETE")
    dp  = _ev("DIAGNOSTIC_PRINTED")
    pc  = _ev("PLAN_CREATED")
    jp  = _ev("JIRA_PLAN_POSTED")
    bc  = _ev("BRANCH_CREATED")
    wc  = _ev("WORKTREE_CREATED")
    ic  = _ev("IMPLEMENTATION_COMPLETE")
    tst = _ev("TESTS_STARTED")
    tf  = _ev("TEST_FAILED")
    tpass = em.get("TESTS_PASSED", {})
    tskip = em.get("TESTS_SKIPPED", {})
    pr  = _ev("PR_CREATED")
    ju  = _ev("JIRA_UPDATED")
    jtr = _ev("JIRA_TRANSITIONED")
    done = _ev("BUG_COMPLETED")
    blocked_ev = _ev("BUG_BLOCKED", "BUG_FAILED")

    jira_key   = jte.get("jira_key") or jte.get("key") or status_data.get("jira_ticket") or ""
    branch_name = bc.get("branch") or status_data.get("branch") or ""
    ps  = plan_summary or {}
    res = result or {}

    def _state(done_ev: dict, active_rank: int, done_rank: int) -> str:
        if done_ev:
            return "done"
        if cur_rank == active_rank:
            return "active"
        if cur_rank > done_rank:
            return "done"
        return "pending"

    steps = [
        # Step 0 — Read Bug
        {
            "num": 0, "name": "Read Bug",
            "statuses": ["QUEUED"],
            "state": "done" if fx else ("active" if cur == "QUEUED" else "pending"),
            "ts": _ts(fx),
            "data": {
                "summary": fx.get("summary", ""),
                "bug_id": fx.get("bug_id") or status_data.get("bug_id", ""),
            },
        },
        # Step 1 — Identify Repos & Dispatch Analysis
        {
            "num": 1, "name": "Identify Repos & Dispatch Analysis",
            "statuses": ["DIAGNOSING"],
            "state": _state(bac or fac, _rank("DIAGNOSING"), _rank("JIRA_CREATED")),
            "ts": _ts(bac or fac or ad),
            "data": {
                "repos": ad.get("repos") or [],
                "backend_state": "done" if bac else ("active" if bas else "pending"),
                "frontend_state": "done" if fac else ("active" if fas else "pending"),
                "backend_summary": bac.get("summary", ""),
                "frontend_summary": fac.get("summary", ""),
                "has_backend": bool(bac or bas),
                "has_frontend": bool(fac or fas),
            },
        },
        # Step 2 — Sync Base Branches
        {
            "num": 2, "name": "Sync Base Branches",
            "statuses": ["SYNCING", "SYNCED"],
            "state": _state(bs, _rank("SYNCING"), _rank("SYNCED")),
            "ts": _ts(bs),
            "data": {
                "repos": bs.get("repos") or [],
                "summary": bs.get("summary", ""),
            },
        },
        # Step 3 — Create / Confirm Jira Ticket
        {
            "num": 3, "name": "Create / Confirm Jira Ticket",
            "statuses": ["JIRA_CREATING", "JIRA_CREATED"],
            "state": _state(jte, _rank("JIRA_CREATING"), _rank("JIRA_CREATED")),
            "ts": _ts(jte),
            "data": {
                "jira_key": jira_key,
                "action": "Created" if em.get("JIRA_TICKET_CREATED") else ("Linked" if em.get("JIRA_TICKET_LINKED") else ""),
                "summary": jte.get("summary", ""),
            },
        },
        # Step 4 — Synthesize Diagnosis
        {
            "num": 4, "name": "Synthesize Diagnosis",
            "statuses": ["DIAGNOSING", "DIAGNOSED"],
            "state": _state(dc, _rank("DIAGNOSING"), _rank("DIAGNOSED")),
            "ts": _ts(dc),
            "data": {
                "repos": dc.get("repos") or [],
                "root_cause": ps.get("root_cause", "") or dc.get("summary", ""),
                "summary": dc.get("summary", ""),
            },
        },
        # Step 5 — Print Diagnostic
        {
            "num": 5, "name": "Print Diagnostic",
            "statuses": ["DIAGNOSED"],
            "state": _state(dp, _rank("DIAGNOSED"), _rank("DIAGNOSED")),
            "ts": _ts(dp),
            "data": {
                "summary": dp.get("summary", ""),
            },
        },
        # Step 6 — Write Fix Plan
        {
            "num": 6, "name": "Write Fix Plan",
            "statuses": ["PLANNING", "PLANNED"],
            "state": _state(pc, _rank("PLANNING"), _rank("PLANNED")),
            "ts": _ts(pc),
            "data": {
                "root_cause": ps.get("root_cause", ""),
                "risk_level": ps.get("risk_level", ""),
                "risk_explanation": ps.get("risk_explanation", ""),
                "repos_changes": ps.get("repos_changes") or {},
                "implementation_steps": ps.get("implementation_steps") or [],
                "tests": ps.get("tests") or [],
                "jira_key": jira_key,
                "jira_posted": bool(jp),
                "summary": pc.get("summary", ""),
            },
        },
        # Step 7 — Create Branch & Worktree
        {
            "num": 7, "name": "Create Branch & Worktree",
            "statuses": ["BRANCHING", "BRANCHED", "WORKTREE_READY"],
            "state": _state(wc or bc, _rank("BRANCHING"), _rank("WORKTREE_READY")),
            "ts": _ts(wc or bc),
            "data": {
                "branch": branch_name,
                "repos": bc.get("repos") or wc.get("repos") or [],
                "path": wc.get("path", ""),
            },
        },
        # Step 8 — Implement the Fix
        {
            "num": 8, "name": "Implement the Fix",
            "statuses": ["IMPLEMENTING", "IMPLEMENTED"],
            "state": _state(ic, _rank("IMPLEMENTING"), _rank("IMPLEMENTED")),
            "ts": _ts(ic),
            "data": {
                "commits": ic.get("commits") or res.get("commits") or {},
                "files_changed": ic.get("files_changed") or res.get("files_changed") or [],
                "repos": ic.get("repos") or list((ic.get("commits") or {}).keys()),
                "summary": ic.get("summary", ""),
            },
        },
        # Step 9 — Run Tests
        {
            "num": 9, "name": "Run Tests",
            "statuses": ["TESTING", "TESTED", "TEST_SKIPPED"],
            "state": _state(tpass or tskip, _rank("TESTING"), _rank("TESTED")),
            "ts": _ts(tpass or tskip or tf or {}),
            "data": {
                "result": "Passed" if tpass else ("Skipped" if tskip else ("Failed" if tf else "")),
                "repos": (tpass or tskip or {}).get("repos") or [],
                "summary": (tpass or tskip or {}).get("summary", ""),
                "fail_summary": tf.get("summary", "") if tf else "",
                "skipped_reason": tskip.get("reason", "") if tskip else "",
            },
        },
        # Step 10 — Create Pull Request
        {
            "num": 10, "name": "Create Pull Request",
            "statuses": ["PR_CREATING", "PR_CREATED"],
            "state": _state(pr, _rank("PR_CREATING"), _rank("PR_CREATED")),
            "ts": _ts(pr),
            "data": {
                "pr_urls": pr.get("pr_urls") or res.get("pr_urls") or {},
                "branch": branch_name,
                "summary": pr.get("summary", ""),
            },
        },
        # Step 11 — Update Jira
        {
            "num": 11, "name": "Update Jira",
            "statuses": ["JIRA_UPDATING", "JIRA_UPDATED"],
            "state": _state(ju, _rank("JIRA_UPDATING"), _rank("JIRA_UPDATED")),
            "ts": _ts(ju or jtr),
            "data": {
                "jira_key": jira_key,
                "updated": bool(ju),
                "transitioned": bool(jtr),
                "transition_summary": jtr.get("summary", "") if jtr else "",
            },
        },
        # Step 12 — Mark Done
        {
            "num": 12, "name": "Mark Done",
            "statuses": ["DONE"],
            "state": "done" if done else ("active" if cur == "DONE" else "pending"),
            "ts": _ts(done),
            "data": {
                "jira_key": res.get("jira_ticket") or jira_key,
                "branch": res.get("branch") or branch_name,
                "repos": res.get("repos") or [],
                "pr_urls": res.get("pr_urls") or pr.get("pr_urls") or {},
                "commits": res.get("commits") or ic.get("commits") or {},
                "files_changed": res.get("files_changed") or [],
                "completed_at": res.get("completed_at", ""),
            },
        },
    ]

    block = None
    if cur in ("BLOCKED", "FAILED"):
        block = {
            "status": cur,
            "step": status_data.get("current_step", "").replace("_", " ").title(),
            "error": status_data.get("error", "") or blocked_ev.get("error", ""),
            "action": blocked_ev.get("action", ""),
            "ts": _ts(blocked_ev),
            "summary": blocked_ev.get("summary", ""),
        }

    return {"steps": steps, "block": block}


def build_pipeline_stages(events: list[dict], status_data: dict) -> list[dict]:
    """Return ordered pipeline stages with status + detail fields for the UI."""
    # Index by event name — last occurrence wins (handles retries)
    em: dict = {}
    for ev in events:
        em[ev.get("event", "")] = ev

    current = status_data.get("status", "FETCHED")
    error = status_data.get("error") or ""
    branch = status_data.get("branch") or ""

    # States that mean "this stage is complete"
    _done_statuses = {
        "FETCHED", "QUEUED", "SYNCING", "SYNCED", "JIRA_CREATING", "JIRA_CREATED",
        "DIAGNOSING", "DIAGNOSED", "PLANNING", "PLANNED", "BRANCHING", "BRANCHED",
        "WORKTREE_READY", "IMPLEMENTING", "IMPLEMENTED", "TESTING", "TESTED",
        "TEST_SKIPPED", "PR_CREATING", "PR_CREATED", "JIRA_UPDATING", "JIRA_UPDATED",
        "DONE",
    }

    def _ts(ev: dict) -> str:
        return (ev.get("timestamp") or "")[:16].replace("T", " ")

    def _stage(key: str, name: str, done_at: list[str], active_at: list[str],
               details: list[tuple[str, str]], ev_key: str = "") -> dict:
        """Build one stage dict."""
        ev = em.get(ev_key or done_at[0] if done_at else "", {})
        is_done = current in done_at or current in (
            {"QUEUED", "SYNCING", "SYNCED", "JIRA_CREATING", "JIRA_CREATED",
             "DIAGNOSING", "DIAGNOSED", "PLANNING", "PLANNED", "BRANCHING", "BRANCHED",
             "WORKTREE_READY", "IMPLEMENTING", "IMPLEMENTED", "TESTING", "TESTED",
             "TEST_SKIPPED", "PR_CREATING", "PR_CREATED", "JIRA_UPDATING", "JIRA_UPDATED",
             "DONE"} if key == "fetched" else set()
        )
        is_active = current in active_at
        is_blocked = current in ("BLOCKED", "FAILED")
        matched_ev = {}
        for ek in (done_at + active_at):
            if ek in em:
                matched_ev = em[ek]
                break
        return {
            "key": key,
            "name": name,
            "done": bool(matched_ev) and current not in active_at,
            "active": is_active,
            "ts": _ts(matched_ev),
            "details": [(label, val) for label, val in details if val],
            "ev": matched_ev,
        }

    # ── helpers to extract clean detail values ──
    def _repos(ev: dict) -> str:
        return ", ".join(ev.get("repos") or [])

    def _commits(ev: dict) -> str:
        c = ev.get("commits") or {}
        return "  ".join(f"{r}: {h[:8]}" for r, h in c.items())

    def _pr_links(ev: dict) -> list[tuple[str, str]]:
        urls = ev.get("pr_urls") or {}
        return [(repo, url) for repo, url in urls.items()]

    fe = em.get("BUG_FETCHED", {})
    fx = em.get("FIX_STARTED", {})
    ad = em.get("ANALYSIS_DISPATCHED", {})
    bac = em.get("BACKEND_ANALYSIS_COMPLETE", {})
    fac = em.get("FRONTEND_ANALYSIS_COMPLETE", {})
    bs = em.get("BRANCH_SYNCED", {})
    jtc = em.get("JIRA_TICKET_CREATED", em.get("JIRA_TICKET_LINKED", {}))
    dc = em.get("DIAGNOSIS_COMPLETE", {})
    dp = em.get("DIAGNOSTIC_PRINTED", {})
    pc = em.get("PLAN_CREATED", {})
    bc = em.get("BRANCH_CREATED", {})
    wc = em.get("WORKTREE_CREATED", {})
    ic = em.get("IMPLEMENTATION_COMPLETE", {})
    tp = em.get("TESTS_PASSED", em.get("TESTS_SKIPPED", em.get("TEST_FAILED", {})))
    pr = em.get("PR_CREATED", {})
    ju = em.get("JIRA_UPDATED", {})
    jt = em.get("JIRA_TRANSITIONED", {})
    done_ev = em.get("BUG_COMPLETED", {})
    blocked_ev = em.get("BUG_BLOCKED", em.get("BUG_FAILED", {}))

    jira_key = (jtc.get("jira_key") or jtc.get("key")
                or status_data.get("jira_ticket") or "")
    branch_name = bc.get("branch") or branch

    _all_after_fetch = {
        "QUEUED", "SYNCING", "SYNCED", "JIRA_CREATING", "JIRA_CREATED",
        "DIAGNOSING", "DIAGNOSED", "PLANNING", "PLANNED", "BRANCHING", "BRANCHED",
        "WORKTREE_READY", "IMPLEMENTING", "IMPLEMENTED", "TESTING", "TESTED",
        "TEST_SKIPPED", "PR_CREATING", "PR_CREATED", "JIRA_UPDATING", "JIRA_UPDATED",
        "DONE", "BLOCKED", "FAILED",
    }

    def _ev_done(ev: dict) -> bool:
        return bool(ev)

    stages = []

    # 1 – Bug Fetched
    stages.append({
        "key": "fetched", "name": "Bug Fetched",
        "done": bool(fe),
        "active": current == "FETCHED" and not fx,
        "ts": _ts(fe),
        "details": [
            ("Source", fe.get("source", "").title()),
            ("Occurrences", str(status_data.get("event_count", "") or "")),
            ("Severity", (status_data.get("severity") or "").title()),
        ],
        "pr_links": [],
    })

    # 2 – Fix Started
    stages.append({
        "key": "started", "name": "Fix Started",
        "done": bool(fx) and current != "QUEUED",
        "active": current == "QUEUED",
        "ts": _ts(fx),
        "details": [("Session", fx.get("bug_id", ""))],
        "pr_links": [],
    })

    # 3 – Analysis
    analysis_details = [("Repos", _repos(ad))]
    if bac:
        analysis_details.append(("Backend", "Complete"))
    if fac:
        analysis_details.append(("Frontend", "Complete"))
    stages.append({
        "key": "analysis", "name": "Analysis",
        "done": bool(bac or fac),
        "active": current == "DIAGNOSING",
        "ts": _ts(bac or fac or ad),
        "details": analysis_details,
        "pr_links": [],
    })

    # 4 – Branch Synced
    stages.append({
        "key": "synced", "name": "Branch Synced",
        "done": bool(bs),
        "active": current == "SYNCING",
        "ts": _ts(bs),
        "details": [
            ("Repos", _repos(bs)),
            ("Base", status_data.get("repos") and "staging" or ""),
        ],
        "pr_links": [],
    })

    # 5 – Jira Ticket
    stages.append({
        "key": "jira_ticket", "name": "Jira Ticket",
        "done": bool(jtc),
        "active": current == "JIRA_CREATING",
        "ts": _ts(jtc),
        "jira_key": jira_key,
        "details": [
            ("Ticket", jira_key),
            ("Action", "Created" if "CREATED" in (jtc.get("event") or "") else "Linked"),
        ],
        "pr_links": [],
    })

    # 6 – Diagnosis
    stages.append({
        "key": "diagnosis", "name": "Diagnosis",
        "done": bool(dc),
        "active": False,
        "ts": _ts(dp or dc),
        "details": [
            ("Summary", (dc.get("summary") or "").replace("Diagnosis complete — root cause identified in ", "Identified in ")),
        ],
        "pr_links": [],
    })

    # 7 – Fix Plan
    ps = status_data.get("_plan_summary") or {}
    stages.append({
        "key": "plan", "name": "Fix Plan",
        "done": bool(pc),
        "active": current == "PLANNING",
        "ts": _ts(pc),
        "details": [
            ("Risk", ps.get("risk_level", "") if ps else ""),
            ("Summary", (pc.get("summary") or "").replace("Fix plan written to plan.md. ", "")),
        ],
        "pr_links": [],
    })

    # 8 – Branch & Worktree
    stages.append({
        "key": "branch", "name": "Branch & Worktree",
        "done": bool(bc),
        "active": current in ("BRANCHING", "BRANCHED"),
        "ts": _ts(wc or bc),
        "details": [
            ("Branch", branch_name),
            ("Worktree", wc.get("path", "") if wc else ""),
        ],
        "pr_links": [],
    })

    # 9 – Implementation
    stages.append({
        "key": "impl", "name": "Implementation",
        "done": bool(ic),
        "active": current == "IMPLEMENTING",
        "ts": _ts(ic),
        "details": [
            ("Commits", _commits(ic)),
            ("Summary", (ic.get("summary") or "").replace("Code committed ", "")),
        ],
        "pr_links": [],
    })

    # 10 – Tests
    test_ev = em.get("TESTS_PASSED") or em.get("TESTS_SKIPPED") or em.get("TEST_FAILED")
    skipped = "TESTS_SKIPPED" in em
    failed_ev = em.get("TEST_FAILED")
    stages.append({
        "key": "tests", "name": "Tests",
        "done": bool(test_ev) and current not in ("TESTING",),
        "active": current == "TESTING",
        "ts": _ts(test_ev or {}),
        "details": [
            ("Result", "Skipped" if skipped else ("Failed" if failed_ev and not em.get("TESTS_PASSED") else "Passed" if em.get("TESTS_PASSED") else "")),
            ("Reason", (em.get("TESTS_SKIPPED") or {}).get("reason", "") if skipped else ""),
        ],
        "pr_links": [],
    })

    # 11 – Pull Request
    pr_links = _pr_links(pr)
    stages.append({
        "key": "pr", "name": "Pull Request",
        "done": bool(pr),
        "active": current == "PR_CREATING",
        "ts": _ts(pr),
        "details": [("Repos", ", ".join(r for r, _ in pr_links))],
        "pr_links": pr_links,
    })

    # 12 – Jira Updated
    stages.append({
        "key": "jira_updated", "name": "Jira Updated",
        "done": bool(ju),
        "active": current == "JIRA_UPDATING",
        "ts": _ts(jt or ju),
        "jira_key": jira_key,
        "details": [
            ("Ticket", jira_key),
            ("Transition", (jt.get("transition") or "In Review") if jt else ""),
        ],
        "pr_links": [],
    })

    # 13 – Done
    stages.append({
        "key": "done", "name": "Done",
        "done": current == "DONE",
        "active": False,
        "ts": _ts(done_ev),
        "details": [("Completed", _ts(done_ev))],
        "pr_links": [],
    })

    # Blocked / Failed card (separate, shown at top)
    block_stage = None
    if current in ("BLOCKED", "FAILED") or blocked_ev:
        block_stage = {
            "status": current,
            "step": status_data.get("current_step", "").replace("_", " ").title(),
            "error": error or blocked_ev.get("error", ""),
            "action": blocked_ev.get("action", ""),
            "ts": _ts(blocked_ev),
            "summary": blocked_ev.get("summary", ""),
        }

    return {"stages": stages, "block": block_stage}


# ── Write helpers (used by FastAPI to seed a bug record if needed) ────────────

def ensure_bug_dir(bug_id: str, source: str, source_id: str, title: str,
                   repository: str, project: str, description: str = "",
                   metadata: Optional[dict] = None) -> dict:
    """Create bug.json + status.json if not already present. Idempotent."""
    d = _bug_dir(bug_id)
    d.mkdir(parents=True, exist_ok=True)
    _worktree_dir(bug_id).mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()

    bug_path = d / "bug.json"
    if not bug_path.exists():
        bug_data = {
            "bug_id":      bug_id,
            "source":      source,
            "source_id":   source_id,
            "title":       title,
            "description": description,
            "repository":  repository,
            "project":     project,
            "created_at":  now,
            **(metadata or {}),
        }
        atomic_write_json(bug_path, bug_data)
        atomic_write_json(d / "status.json", {
            "bug_id":         bug_id,
            "source":         source,
            "source_id":      source_id,
            "status":         BugStatus.FETCHED.value,
            "current_step":   "fetched",
            "next_step":      "sync_base_branch",
            "branch":         None,
            "repos":          [],
            "jira_ticket":    bug_id if source == "jira" else None,
            "pr_url":         None,
            "session_id":     None,
            "last_heartbeat": now,
            "updated_at":     now,
            "error":          None,
        })
        append_jsonl(d / "events.jsonl", {"timestamp": now, "event": "BUG_FETCHED", "bug_id": bug_id})
        return read_json_safe(bug_path)
    return read_json_safe(bug_path)
