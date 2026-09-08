---
description: List open bugs locally, or fetch from Sentry/Jira and save them locally
argument-hint: [source=sentry|jira[,sentry|jira] project=<name> top=<n>|all days=<n>]
---

# List Bugs Skill

With **no arguments**: display all open bugs already saved in `bugs/` — **do not ask for any arguments, just list local bugs immediately**. With arguments: fetch from one or more external sources and save them locally for the `/fix-bug` workflow.

## Invocation

```
/list-bugs                                             → list all local open bugs
/list-bugs source=sentry                               → fetch from Sentry (top=10)
/list-bugs source=jira project=jarvis                  → fetch from Jira (top=10)
/list-bugs source=sentry,jira project=jarvis,hawkeye top=20    → fetch from both sources
/list-bugs source=sentry top=all                       → fetch all from Sentry
/list-bugs source=sentry days=2                        → fetch only last 2 days
```

### Arguments

| Arg | Required | Values | Default |
|-----|----------|--------|---------|
| `source` | no | `sentry`, `jira`, or comma-separated e.g. `sentry,jira` | — (local list mode) |
| `project` | conditional | project key or slug | required when `source=jira`; optional for `sentry` |
| `top` | no | positive integer or `all` | `10` |
| `days` | no | positive integer (max 30) | — (no date filter) |

**`top` validation:** If `top` is provided and is not a positive integer and not the string `"all"`, print an error and stop:
```
Error: 'top' must be a positive integer or "all". Got: {value}
```

**`days` validation:** If `days` is provided and is not a positive integer ≤ 30, print an error and stop:
```
Error: 'days' must be a positive integer between 1 and 30. Got: {value}
```

When `days=N` is given, compute:
- `end_date` = today in UTC (ISO 8601, e.g. `2025-08-25T23:59:59Z`)
- `start_date` = N days ago at midnight UTC (e.g. `days=2` → yesterday at `00:00:00Z`)

Apply this date filter to all API calls for the selected sources (see per-source details below).

## Configuration

Read credentials from environment variables (set via `.env`):

```
SENTRY_AUTH_TOKEN   → Bearer token for Sentry API
SENTRY_ORG          → Organisation slug

JIRA_BASE_URL       → https://your-org.atlassian.net
JIRA_USERNAME       → your.email@company.com
JIRA_API_TOKEN      → Jira personal access token
```

The project key mapping is in `config/integrations.json`:
```json
{
  "jira": {
    "projects": {
      "jarvis":   "JAR",
      "hawkeye":  "HAW",
      "frontend": "FE"
    }
  }
}
```

Repository metadata (used to annotate fetched bugs with branch and dependency info) is in `config/repositories.json`. The full schema for each entry is:
```json
{
  "id":                    "hawkeye",
  "name":                  "Hawkeye",
  "type":                  "frontend",
  "path":                  "workspace/hawkeye",
  "git_url":               "git@github.com:EverestFleetOrg/hawkeye.git",
  "base_branch":           "staging",
  "protected_branches":    ["main", "staging", "production"],
  "dependent_repos":       ["everest_jarvis"],
  "dependency_evidence":   {},
  "_rejected_dependencies": {},
  "runtime":               {}
}
```

- **`dependent_repos`** — repo IDs this repo depends on. When `/fix-bug` diagnoses a bug in this repo, it will also scan the listed repos to find cross-repo root causes.
- **`dependency_evidence`** — maps repo IDs to the specific files/lines in this repo that contain calls to that dependency. Used by analysis sub-skills to jump directly to the relevant code.
- **`_rejected_dependencies`** — repo IDs that were considered but ruled out as dependencies. Informational only.

**Repo matching:** When saving a bug, match the `project` argument against each repo's `id` field in `config/repositories.json`. If a match is found, include `base_branch`, `dependent_repos`, `dependency_evidence`, and `_rejected_dependencies` in `bug.json` (under `"repo_base_branch"`, `"repo_dependent_repos"`, `"repo_dependency_evidence"`, and `"repo_rejected_dependencies"`). This lets `/fix-bug` load repo context without re-reading config. If no repo matches, omit these fields (they are optional).

## Workflow

### 1. Parse and Validate Arguments

Extract `source`, `project`, and `top` from the command. All arguments are optional.

**NEVER ask the user for missing arguments. If no arguments are given → immediately go to Step 1a (local list mode). Do not make any API calls. Do not prompt for source or project.**

If `source` is provided, split on commas and trim whitespace. Each value must be `sentry` or `jira`; if any value is invalid, print error and stop:
```
Error: 'source' must be "sentry", "jira", or a comma-separated combination. Got: {value}
```

If `top` is provided and is not the string `"all"` and is not a positive integer, print error and stop.

If no `top` is given, use `10` as the default.

---

### 1a. Local List Mode (no arguments)

Read every subdirectory in `bugs/`. For each, load `bug.json` and `status.json`. A bug is **open** if its `status.json` → `status` field is NOT one of: `DONE`, `FAILED`.

Display a formatted table of open bugs:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Open Bugs (local)  —  {N} found                                                │
├────────────────┬──────────────────────────────────┬──────────┬──────────────────┤
│ ID             │ Title                            │ Severity │ Status           │
├────────────────┼──────────────────────────────────┼──────────┼──────────────────┤
│ SENTRY-5234891 │ Login endpoint returns 500        │ error    │ FETCHED          │
│ JAR-1234       │ Payment API timeout               │ High     │ DIAGNOSED        │
│ ...            │ ...                              │ ...      │ ...              │
└────────────────┴──────────────────────────────────┴──────────┴──────────────────┘
```

Sort by `status.json` → `updated_at` descending (most recently updated first). If `bugs/` is empty or has no open bugs, print:
```
No open bugs found locally. Run /list-bugs source=sentry or /list-bugs source=jira to fetch.
```

After displaying the table, print:
```
To fix a bug, type:
  /fix-bug {bug_id}
```

**Stop here. Do not proceed to Step 2.**

---

### 1.5. Initialize Sync State

Before making any API calls, write the initial sync state file so the system knows a sync is in progress.

**Sync key** — derive a slug from the arguments:
- `source_slug` = sources joined by `-` (e.g. `sentry`, `sentry-jira`)
- `project_slug` = project name if provided, else `all`
- Final key: `{source_slug}_{project_slug}` (e.g. `sentry_jarvis`, `sentry-jira_all`)

**Create directory (if not exists):** `bugs/_sync/`

**Write `bugs/_sync/{key}.json`:**
```json
{
  "key":          "{source_slug}_{project_slug}",
  "source":       "{comma-separated sources}",
  "project":      "{project or null}",
  "top":          {top},
  "days":         {days or null},
  "status":       "RUNNING",
  "started_at":   "{now ISO 8601 UTC}",
  "completed_at": null,
  "bugs_fetched": null,
  "bugs_new":     null,
  "bugs_updated": null,
  "error":        null
}
```

---

### 2. Fetch Bugs

For each source in the (now split) `source` list, run the corresponding fetch below. Collect all results together before saving (Step 3). If multiple sources are specified, deduplicate by `bug_id` — keep the most recently fetched copy.

#### Sentry

**Project validation:** Sentry uses the project slug directly in the URL — no lookup in `integrations.json` is needed. If no `project` argument is given for Sentry, omit the project filter and fetch org-wide issues (replace `{SENTRY_ORG}/{project}/issues/` with `{SENTRY_ORG}/issues/` in the URL). The Sentry API will return 404 if the slug is invalid (handled in Step 5).

**Fetching issues:**

Use the Sentry Issues API with `limit` capped at 100 (the Sentry maximum per page):

```
GET https://sentry.io/api/0/projects/{SENTRY_ORG}/{project}/issues/
    ?query=is:unresolved
    &limit=100
    &sort=date
    [&start={start_date}&end={end_date}]   ← include when days= is provided
Authorization: Bearer $SENTRY_AUTH_TOKEN
```

When `days=N` is given, add `start={start_date}` and `end={end_date}` query parameters (ISO 8601 UTC). Sentry accepts these as `firstSeen` filter bounds — only issues **last seen** within the window will be returned.

**Pagination (required when `top=all` or `top > 100`):**

Sentry uses cursor-based pagination. After each response, check the `Link` response header for a `rel="next"` cursor:

```
Link: <url>; rel="previous"; ..., <url?cursor=...>; rel="next"; results="true"
```

- If `rel="next"` has `results="true"`, fetch the next page by appending `&cursor=<cursor_value>` to the request URL.
- Stop paginating when:
  - `rel="next"` has `results="false"` or is absent, OR
  - The total collected count reaches `top` (when `top` is a finite integer).

When `top` is a finite integer, set `limit=min(top, 100)` on the first request. On subsequent pages, set `limit=min(remaining_needed, 100)`.

**Fetching the stack trace for each issue:**

After collecting the issue list, for each issue make a secondary request to fetch the latest event:

```
GET https://sentry.io/api/0/issues/{issue.id}/events/latest/
Authorization: Bearer $SENTRY_AUTH_TOKEN
```

Extract the stack trace from the event. The stack trace is in `event.entries` — find the entry where `type == "exception"`. The frames are in `entry.data.values[0].stacktrace.frames` (array of frame objects). Format the stack trace as a readable string:

```
{exception_type}: {exception_value}
  File "{frame.filename}", line {frame.lineNo}, in {frame.function}
  ...
```

List frames from outermost to innermost (reverse the array if needed). If the event fetch fails, set `stack_trace` to `null` and continue — do not abort the whole fetch.

**Map each Sentry issue to this bug record:**

```json
{
  "bug_id":      "SENTRY-{issue.id}",
  "source":      "sentry",
  "source_id":   "{issue.id}",
  "source_url":  "https://sentry.io/organizations/{SENTRY_ORG}/issues/{issue.id}/",
  "title":       "{issue.title}",
  "description": "{issue.title}\n\nException: {issue.metadata.value}\nCulprit: {issue.culprit}\nPlatform: {issue.platform}",
  "stack_trace": "{formatted stack trace string from latest event, or null if unavailable}",
  "severity":    "{issue.level}",
  "project":     "{project}",
  "first_seen":  "{issue.firstSeen}",
  "last_seen":   "{issue.lastSeen}",
  "event_count": "{issue.count}",
  "user_count":  "{issue.userCount}",
  "platform":    "{issue.platform}",
  "fetched_at":  "{now ISO 8601 UTC}",
  "updated_at":  "{now ISO 8601 UTC}"
}
```

#### Jira

**Project key lookup (required):**

Look up the Jira project key from `config/integrations.json` → `jira.projects` using the `project` argument as the key. Example: `"jarvis"` → `"JAR"`.

If the `project` argument is not found in `integrations.json`, print an error and stop:
```
Error: Project "{project}" not found in config/integrations.json.
Available projects: jarvis (JAR), hawkeye (HAW), frontend (FE)
```
(List the actual keys from the config file.)

**Fetching issues:**

Use the Jira REST API v3. The `maxResults` field must be an integer — the string `"all"` is not valid. Cap each request at 100:

```
GET {JIRA_BASE_URL}/rest/api/3/search
    ?jql=project={PROJECT_KEY} AND issuetype=Bug AND status != Done [AND created >= "{start_date_yyyy-mm-dd}"] ORDER BY created DESC
    &maxResults=100
    &startAt=0
    &fields=summary,description,status,priority,assignee,reporter,created,updated,labels,components
Authorization: Basic base64({JIRA_USERNAME}:{JIRA_API_TOKEN})
Content-Type: application/json
```

When `days=N` is given, append `AND created >= "{start_date}"` to the JQL, where `start_date` is formatted as `YYYY-MM-DD` (the date N days ago in UTC).

**Pagination (required when `top=all` or `top > 100`):**

The response contains `total`, `startAt`, and `maxResults`. After each page:

- Increment `startAt` by the number of issues received in this page.
- Stop paginating when:
  - `startAt >= total` (no more results), OR
  - The total collected count reaches `top` (when `top` is a finite integer).

When `top` is a finite integer, set `maxResults=min(top, 100)` on the first request. On subsequent pages, set `maxResults=min(remaining_needed, 100)`.

**Extracting plain text from ADF description:**

Jira's `description` field is in Atlassian Document Format (ADF), a nested JSON structure — not plain text. To extract plain text:

1. If `issue.fields.description` is `null` or missing, use `""`.
2. Otherwise, recursively walk the ADF `content` array.
3. Collect the `text` value from every node where `"type": "text"`.
4. Join collected text values with `"\n"` when transitioning between block-level nodes (`paragraph`, `heading`, `bulletList`, `orderedList`, `listItem`, `blockquote`, `codeBlock`).
5. Join inline text nodes within the same block with `""` (no separator).

Example: `{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Login fails"}]}]}` → `"Login fails"`.

**Map each Jira issue:**

```json
{
  "bug_id":       "{issue.key}",
  "source":       "jira",
  "source_id":    "{issue.key}",
  "source_url":   "{JIRA_BASE_URL}/browse/{issue.key}",
  "title":        "{issue.fields.summary}",
  "description":  "{plain text extracted from issue.fields.description ADF}",
  "severity":     "{issue.fields.priority.name}",
  "project":      "{project}",
  "priority":     "{issue.fields.priority.name}",
  "status":       "{issue.fields.status.name}",
  "labels":       "{issue.fields.labels}",
  "components":   "{[c.name for c in issue.fields.components]}",
  "reporter":     "{issue.fields.reporter.displayName}",
  "created":      "{issue.fields.created}",
  "updated":      "{issue.fields.updated}",
  "last_seen":    "{issue.fields.updated}",
  "fetched_at":   "{now ISO 8601 UTC}",
  "updated_at":   "{now ISO 8601 UTC}"
}
```

Note: `last_seen` is set to `updated` to provide a normalized `last_seen` field across both sources.

### 3. Save Each Bug

For each fetched bug, attempt to match the `project` argument to a repo entry in `config/repositories.json` by comparing against the `id` field. If matched, merge repo fields into the bug record:

```json
{
  "repo_base_branch":           "{repo.base_branch}",
  "repo_dependent_repos":       "{repo.dependent_repos}",
  "repo_dependency_evidence":   "{repo.dependency_evidence}",
  "repo_rejected_dependencies": "{repo._rejected_dependencies}"
}
```

**Handling existing bug directories:**

- If the bug directory (`bugs/<bug_id>/`) does **not** exist: create it with all three files (`bug.json`, `status.json`, `events.jsonl`) as described below.
- If the bug directory **already exists** (bug was previously fetched):
  - Print a notice: `Notice: {bug_id} already fetched. Updating volatile fields.`
  - Update only these fields in the existing `bug.json`: `event_count`, `last_seen`, `updated_at`, `fetched_at`.
  - Do **not** overwrite `status.json` or other fields in `bug.json`.
  - Append a new `BUG_REFETCHED` event to `events.jsonl`.
  - Skip creating `status.json` again.

**`bugs/<bug_id>/bug.json`** — the full metadata dict above (with repo fields if matched).

**`bugs/<bug_id>/status.json`** (created only on first fetch):
```json
{
  "bug_id":         "{bug_id}",
  "source":         "sentry|jira",
  "source_id":      "{source_id}",
  "severity":       "{severity}",
  "status":         "FETCHED",
  "current_step":   "fetched",
  "next_step":      "run /fix-bug {bug_id}",
  "branch":         null,
  "repos":          [],
  "jira_ticket":    null,
  "pr_url":         null,
  "session_id":     null,
  "last_heartbeat": "{now ISO 8601 UTC}",
  "updated_at":     "{now ISO 8601 UTC}",
  "error":          null
}
```

Set `jira_ticket` to `{bug_id}` if source is `jira`. Set `next_step` using the actual bug_id value (e.g. `"run /fix-bug SENTRY-5234891"`).

**`bugs/<bug_id>/events.jsonl`** — append one line:
```json
{"timestamp": "{now ISO 8601 UTC}", "event": "BUG_FETCHED", "bug_id": "{bug_id}", "source": "sentry|jira"}
```

For re-fetched bugs, append:
```json
{"timestamp": "{now ISO 8601 UTC}", "event": "BUG_REFETCHED", "bug_id": "{bug_id}", "source": "sentry|jira", "fields_updated": ["event_count", "last_seen", "fetched_at"]}
```

### 4. Display Summary

After saving all bugs, display a formatted table. If multiple sources were fetched, print one table per source. Use separate formats depending on source:

**Sentry:**
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Fetched 10 bugs from Sentry / project: jarvis                                  │
├────────────────┬──────────────────────────────────┬──────────┬──────────────────┤
│ ID             │ Title                            │ Severity │ Last Seen        │
├────────────────┼──────────────────────────────────┼──────────┼──────────────────┤
│ SENTRY-5234891 │ Login endpoint returns 500        │ error    │ 2 hours ago      │
│ SENTRY-5198234 │ Payment API timeout               │ fatal    │ 1 day ago        │
│ SENTRY-5102938 │ Dashboard blank for new users     │ warning  │ 3 days ago       │
│ ...            │ ...                              │ ...      │ ...              │
└────────────────┴──────────────────────────────────┴──────────┴──────────────────┘
```

**Jira:**
```
┌──────────────┬──────────────────────────────────┬──────────┬──────────────────┐
│ ID           │ Title                            │ Priority │ Last Updated     │
├──────────────┼──────────────────────────────────┼──────────┼──────────────────┤
│ JAR-1234     │ Login endpoint returns 500        │ High     │ 2 hours ago      │
│ HAW-567      │ Dashboard blank for new users     │ Medium   │ 3 days ago       │
│ ...          │ ...                              │ ...      │ ...              │
└──────────────┴──────────────────────────────────┴──────────┴──────────────────┘
```

After the table, print:
```
To fix a bug, type:
  /fix-bug {bug_id}
```

**Write sync output files:**

Count results:
- `bugs_fetched` = total bugs returned (new + updated)
- `bugs_new` = bugs whose directory did not exist before this run
- `bugs_updated` = bugs that already existed and had volatile fields updated

**Update `bugs/_sync/{key}.json`** (overwrite with completed state):
```json
{
  "key":          "{source_slug}_{project_slug}",
  "source":       "{comma-separated sources}",
  "project":      "{project or null}",
  "top":          {top},
  "days":         {days or null},
  "status":       "COMPLETED",
  "started_at":   "{started_at from Step 1.5}",
  "completed_at": "{now ISO 8601 UTC}",
  "bugs_fetched": {total count},
  "bugs_new":     {new count},
  "bugs_updated": {updated count},
  "error":        null
}
```

**Write `bugs/_sync/{key}.md`** (overwrite with formatted output):

```markdown
# Sync: {source} / {project or "all projects"}

**Synced at:** {completed_at}  
**Period:** last {days} days  
**Fetched:** {bugs_fetched} bugs ({bugs_new} new, {bugs_updated} updated)

{paste the exact formatted table(s) printed above}

---
*Next: run `/fix-bug <bug_id>` to start fixing a bug.*
```

### 5. Error Handling

| Failure | Behaviour |
|---------|-----------|
| Auth failure (401) | Print clear error with which env var to set; update sync JSON with `status: FAILED, error: "Auth failed"` |
| Project not found (404) | Print error; for Sentry list available projects; for Jira list keys from config; update sync JSON with `status: FAILED` |
| Rate limited (429) | Wait and retry once |
| Network error | Print error, show partial results if any; update sync JSON with `status: FAILED, error: "{message}"` |
| No bugs found | Print "No open bugs found for project {project}"; still write COMPLETED sync JSON with `bugs_fetched: 0` |
| Sentry latest-event fetch fails | Set `stack_trace: null`, log a warning, continue |
| `top` is invalid | Print error and stop (see Step 1); no sync JSON written (validation failed before Step 1.5) |
| Jira project not in `integrations.json` | Print error listing available project keys and stop; no sync JSON written |

**On any fatal error that aborts after Step 1.5:** update `bugs/_sync/{key}.json` setting `status: "FAILED"`, `completed_at: now`, and `error: "{error message}"` before exiting.

## Notes

- Do NOT begin fixing. This skill only fetches and saves.
- All timestamps in ISO 8601 UTC format.
- The `bugs/` directory is at the project root (same level as `workspace/`).
- `bugs/_sync/` is a reserved subdirectory — never treat it as a bug directory. The `_` prefix ensures no real bug ID can collide with it.
- Each `bugs/_sync/{key}.json` is always overwritten by the latest sync for that source+project combination — it reflects the most recent run only.
- `stack_trace` in `bug.json` is used directly by the `bug-analysis-backend` and `bug-analysis-frontend` sub-skills — do not omit it when available.
- `severity` in `bug.json` is used by `/fix-bug` when creating a Jira ticket from a Sentry issue (to set priority).
