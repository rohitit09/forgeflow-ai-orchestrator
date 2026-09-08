---
name: create-jira-bug
description: Creates a new Jira Bug ticket from analysis/diagnosis files (Sentry source), or posts a start-comment on an existing ticket (Jira source). Resolves project key, maps severity to priority, builds the 4-section ADF description. Invoked by fix-bug Step 3 — never directly.
---

# Skill: Create Jira Bug

## 1. Purpose

Given a bug record and its analysis files, either create a new Jira Bug ticket with a 4-section ADF description (Description, Root Cause, Diagnostic, Source) or post a start-comment on the existing ticket. Return the Jira issue key so `fix-bug` can write it to `status.jira_ticket`.

## 2. When Invoked

Invoked by `fix-bug` Step 3 (status `JIRA_CREATING`), after syncing is complete and analysis files exist. Never invoked directly by the user.

## 3. Inputs

- `bug_id` — the bug directory name (e.g. `sentry-abc123`)
- `bug` — the parsed `bugs/<bug_id>/bug.json` object; key fields:
  - `title` — bug title
  - `source` — `"sentry"` or `"jira"`
  - `severity` — `fatal | critical | error | warning | info`
  - `description` — raw description text
  - `source_url` — link back to Sentry/Jira source
- `project_slug` — the repo slug used to look up `jira.projects` (e.g. `"jarvis"`)
- `session_id` — `ORCHESTRATOR_SESSION_ID` value (used in the start comment for Jira source)
- `confirmed_repos` — list of repo names being fixed (used in the start comment)

## 4. Workflow

### Step 1 — Resolve Jira Configuration

Read `config/integrations.json` → `jira`:

| Field | Key | Required |
|---|---|---|
| Instance URL | `jira.base_url` | Yes |
| Auth email | `jira.email` | Yes (REST fallback) |
| Auth token | `jira.api_token` | Yes (REST fallback) |
| Default project | `jira.default_project` | Yes |
| Per-repo project map | `jira.projects` | Optional |
| Default assignee | `jira.default_assignee` | Optional |
| Component name | `jira.default_component` | Optional |

**Resolve project key:**
1. Check env var `JIRA_PROJECT_KEY` — use if set.
2. Else check `jira.projects.<project_slug>` in `config/integrations.json`.
3. Else use `jira.default_project`.
4. If none found: return `{key: null, reason: "no_project_key", available: [keys from jira.projects]}` — `fix-bug` will set status `BLOCKED`.

If `jira.base_url` or `jira.api_token` is missing after env-var substitution: return `{key: null, reason: "jira_not_configured"}`.

---

### Step 2 — Map Severity to Priority

| `bug.severity` | Jira priority |
|---|---|
| `fatal` or `critical` | `"High"` |
| `error` or `warning` | `"Medium"` |
| anything else | `"Low"` |

---

### Step 3 — Build ADF Payload (Sentry source only)

Read analysis and diagnosis files — prefer the most complete source available:

| Content | Primary source | Fallback |
|---|---|---|
| Bug Summary | `bugs/<bug_id>/analysis-backend.md` or `analysis-frontend.md` → "Bug Summary" section | `bug.description` |
| Root Cause | `bugs/<bug_id>/diagnosis.md` → "Root Cause" section | analysis file → "Root Cause" section |
| Diagnostic | `bugs/<bug_id>/diagnosis.md` → "Affected Code" table | analysis file → "Affected Files" section |
| Source line | `bug.source`, `bug.severity`, `bug.source_url` | — |

Build the ADF description (see §5 for full JSON):

| Section | Content |
|---|---|
| **Description** | Plain-language summary of what the bug is |
| **Root Cause** | Technical explanation verbatim |
| **Diagnostic** | `Exception : <type>\nLocation  : <file>:<line>\nEndpoint  : <endpoint or screen>` |
| **Source** | `Source: <source> \| Severity: <severity>\nLink: <url>` |

---

### Step 4 — Create or Comment

#### Case A — `bug.source = "jira"` (ticket already exists)

Post a start-comment on the existing ticket:

**MCP first:**
```
mcp__atlassian__create_comment(
  issue_key = bug_id,
  body      = <ADF start-comment — see §5>
)
```

**REST fallback:**
```
POST {jira.base_url}/rest/api/3/issue/{bug_id}/comment
Authorization: Basic <base64(jira.email:jira.api_token)>
Content-Type: application/json
{ "body": <ADF start-comment> }
```

Return `{key: bug_id, method: "comment"}`.

---

#### Case B — `bug.source = "sentry"` (create new Bug ticket)

**MCP first:**
```
mcp__atlassian__create_issue(
  project_key  = <resolved project key>,
  summary      = "[BugFixer] <bug.title>",
  issue_type   = "Bug",
  priority     = "<mapped priority>",
  labels       = ["bugfixer", "<bug_id>"],
  description  = <ADF description — see §5>
  /* assignee_account_id = jira.default_assignee   — only if configured */
  /* component_name      = jira.default_component  — only if configured */
)
```

**REST fallback:**
```
POST {jira.base_url}/rest/api/3/issue
Authorization: Basic <base64(jira.email:jira.api_token)>
Content-Type: application/json

{
  "fields": {
    "project":   { "key": "<resolved project key>" },
    "summary":   "[BugFixer] <bug.title>",
    "issuetype": { "name": "Bug" },
    "priority":  { "name": "<mapped priority>" },
    "labels":    ["bugfixer", "<bug_id>"],
    "description": <ADF description object>
    /* "assignee":   {"accountId": "<jira.default_assignee>"}   — only if configured */
    /* "components": [{"name": "<jira.default_component>"}]     — only if configured */
  }
}
```

Return `{key: "<returned issue key>", method: "created"}`.

---

### Step 5 — Return

Return to `fix-bug`:
```json
{
  "key":    "<jira key or null>",
  "method": "created | comment | null",
  "reason": "<error reason if key is null>"
}
```

`fix-bug` uses the return to:
- Write `status.jira_ticket = key`
- Update status `JIRA_CREATED` and append the event
- Set status `BLOCKED` if `key` is null and `reason` is `"no_project_key"`

---

## 5. ADF Objects

### Description — new Bug ticket (Case B)

```json
{
  "type": "doc",
  "version": 1,
  "content": [
    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [{ "type": "text", "text": "Description" }]
    },
    {
      "type": "paragraph",
      "content": [{ "type": "text", "text": "<Bug Summary from analysis or bug.description>" }]
    },

    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [{ "type": "text", "text": "Root Cause" }]
    },
    {
      "type": "paragraph",
      "content": [{ "type": "text", "text": "<Root Cause verbatim from diagnosis.md or analysis file>" }]
    },

    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [{ "type": "text", "text": "Diagnostic" }]
    },
    {
      "type": "paragraph",
      "content": [{ "type": "text", "text": "Exception : <exception type>\nLocation  : <file>:<line>\nEndpoint  : <endpoint or screen/route>" }]
    },

    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [{ "type": "text", "text": "Source" }]
    },
    {
      "type": "paragraph",
      "content": [{ "type": "text", "text": "Source: <bug.source> | Severity: <bug.severity>\nLink: <bug.source_url>" }]
    }
  ]
}
```

---

### Start-comment ADF — existing ticket (Case A)

```json
{
  "type": "doc",
  "version": 1,
  "content": [
    {
      "type": "paragraph",
      "content": [{ "type": "text",
        "text": "AI agent starting fix for <bug_id>.\nSession: <session_id>\nStarted: <ISO 8601 timestamp>\nRepos: <confirmed_repos joined by ', '>"
      }]
    }
  ]
}
```

---

## 6. Files Read

- `config/integrations.json` — Jira config
- `bugs/<bug_id>/analysis-backend.md` — Bug Summary, Root Cause, Affected Files (if present)
- `bugs/<bug_id>/analysis-frontend.md` — Bug Summary, Root Cause, Affected Files (if present)
- `bugs/<bug_id>/diagnosis.md` — Root Cause, Affected Code (preferred over analysis files if present)

## 7. Files Written

None — returns the Jira key to `fix-bug`, which writes it to `status.jira_ticket`.

## 8. State Changes

None — all status transitions (`JIRA_CREATING` → `JIRA_CREATED`, `BLOCKED`) are managed by `fix-bug`.

## 9. Failure Handling

- **No project key found**: return `{key: null, reason: "no_project_key", available: [...]}` — `fix-bug` sets status `BLOCKED` and prints the available keys.
- **Jira not configured**: return `{key: null, reason: "jira_not_configured"}` — `fix-bug` sets status `FAILED`.
- **MCP + REST both fail**: return `{key: null, reason: "api_error", detail: "<HTTP status and body>"}` — `fix-bug` sets status `FAILED`.
- Never retry more than once — a second failure means Jira is unavailable.

## 10. Output

```json
{
  "key":    "<JAR-42 or null>",
  "method": "created | comment | null",
  "reason": "<only present if key is null>"
}
```

## 11. Rules and Constraints

- Never invoked directly — always through `fix-bug` Step 3.
- Do not write any files.
- Do not update `status.json` — that is `fix-bug`'s responsibility.
- Do not transition the Jira issue status — only create or comment.
- MCP is always tried first; REST is the fallback.
- Read `diagnosis.md` in preference to analysis files when it exists — it is the synthesized, more accurate source.
