---
description: AI-powered code review for any GitHub PR (backend, frontend, any language)
argument-hint: <PR-URL>
---

# Code Review

Performs a thorough, language-agnostic code review for a GitHub Pull Request and writes a self-contained HTML report to `reviews/<review_id>/`.

## Usage

```
/code-review https://github.com/org/repo/pull/123
```

---

## Step 0 — Verify GitHub CLI Auth

Before doing anything else, run:

```bash
gh auth status
```

**If the command fails or prints "not logged in":**

1. Print this message to the user:
   ```
   ✗ GitHub CLI is not authenticated in this terminal session.

   This happens because gh stores tokens in the macOS Keychain by default,
   which is not accessible from tmux sessions started by the orchestrator.

   Fix (one-time): run this in the terminal below, then retry /code-review <PR-URL>

     gh auth login

   Choose: GitHub.com → HTTPS → Login with a web browser (or paste token).
   After logging in once here, all future reviews will work automatically.
   ```

2. Stop — do not proceed to Step 1.

**If `gh auth status` succeeds**, continue to Step 1.

---

## Step 1 — Parse PR URL and Initialize

**Parse the PR URL** to extract `owner`, `repo`, and `pr_number`.

Derive `review_id` from the URL:
- Pattern: `<owner>-<repo>-<pr_number>` — all lowercase, non-alphanumeric characters → `-`
- Example: `everestfleet/jarvis` PR `#42` → `everestfleet-jarvis-42`

**Create the review directory:**
```bash
mkdir -p reviews/<review_id>
```

**Write initial `reviews/<review_id>/status.json`:**
```json
{
  "review_id": "<review_id>",
  "pr_url": "<PR-URL>",
  "pr_title": null,
  "pr_number": <number>,
  "repo": "<owner>/<repo>",
  "author": null,
  "base_branch": null,
  "additions": null,
  "deletions": null,
  "changed_files": null,
  "status": "RUNNING",
  "verdict": null,
  "created_at": "<ISO-8601 timestamp>",
  "updated_at": "<ISO-8601 timestamp>"
}
```

---

## Step 2 — Fetch PR Metadata

```bash
gh pr view <PR-URL> --json title,body,author,baseRefName,headRefName,number,additions,deletions,changedFiles,labels,state,mergeable,url,createdAt
```

Save the JSON output to `reviews/<review_id>/pr_metadata.json`.

Update `reviews/<review_id>/status.json` with:
- `pr_title` ← `title`
- `author` ← `author.login`
- `base_branch` ← `baseRefName`
- `additions` ← `additions`
- `deletions` ← `deletions`
- `changed_files` ← `changedFiles`

---

## Step 3 — Fetch the Diff

```bash
gh pr diff <PR-URL>
```

Save the diff output to `reviews/<review_id>/diff.txt`.

Also fetch the list of changed files:
```bash
gh pr view <PR-URL> --json files --jq '.files[] | "\(.additions)+\(.deletions)-\t\(.path)"'
```

---

## Step 4 — Analyze Changes

Read `diff.txt` and `pr_metadata.json`. Build a mental model of the PR:

1. **Identify languages and frameworks** from file extensions and import statements
2. **Categorize changed files:**
   - Source code (business logic, models, services, controllers, components, hooks)
   - Tests (unit, integration, e2e)
   - Configuration (CI, env, Docker, package.json, pyproject.toml, etc.)
   - Database / schema migrations
   - Documentation / README
   - Infrastructure / deployment
3. **Identify risk areas:**
   - Authentication / authorization changes
   - Database schema or query changes
   - Public API contract changes (endpoints, response shapes, breaking changes)
   - Dependency version changes
   - Security-sensitive code paths
   - Files with no accompanying tests

---

## Step 5 — Perform the Code Review

Read the full diff carefully. Evaluate every changed hunk against the following criteria.

### 5a — Code Quality

For each changed file:
- Naming: are variables, functions, classes named clearly and consistently with the existing codebase?
- Complexity: are functions doing too much? Is there deep nesting that should be extracted?
- Duplication: is there copy-paste that could be a shared helper?
- Dead code: are there commented-out blocks, unused imports, or unreachable branches?
- Readability: will a new team member understand this code in 6 months?

### 5b — Security

- **Input validation**: is all external input (request bodies, query params, URL params, file uploads) validated before use?
- **Authorization**: is every endpoint / action protected by the appropriate role/permission check? Are there missing auth guards?
- **Secrets**: are credentials, API keys, tokens, or passwords hardcoded or committed? Should they use environment variables?
- **Injection risks**: SQL injection (raw queries), XSS (unescaped output), command injection, path traversal
- **Sensitive data exposure**: is PII or sensitive data logged, returned in API responses, or serialized unnecessarily?
- **Dependency vulnerabilities**: do any newly added packages have known CVEs?

### 5c — Testing

- Are there tests for the new or changed behaviour?
- Do tests cover both the happy path and key failure / edge cases?
- Are assertions strong enough (not just `assert response.status_code == 200` without checking the body)?
- If a bug was fixed, is there a regression test?
- What would have caught this bug earlier — what test is missing?

### 5d — Performance and Reliability

- **N+1 queries**: does any loop issue a DB query per iteration without eager loading?
- **Blocking I/O on the main thread**: synchronous network/disk calls in an async context?
- **Large data**: does the code load unbounded result sets into memory?
- **Retry / timeout**: are external service calls wrapped with timeouts and retries?
- **Race conditions**: shared mutable state with no locking?
- **Error handling**: are exceptions caught at the right level? Are errors propagated properly vs. swallowed?

### 5e — Observability and Documentation

- Are meaningful log statements added for important state changes or errors?
- Is log level appropriate (debug/info/warning/error)?
- Are metrics, traces, or spans added where needed?
- Are public APIs (REST, GraphQL, SDK) documented (docstring, OpenAPI annotation)?
- Does the PR description explain the *why* — not just the *what*?
- Does the CHANGELOG or migration guide need updating?

---

## Step 6 — Write the HTML Review

Write a **self-contained** HTML file to `reviews/<review_id>/review.html`.

Use **exactly** the template below. Replace every `{PLACEHOLDER}` with real values from your analysis.

For checklist rows use one of these status values:
- `pass` — criterion met
- `fail` — criterion not met (usually a finding)
- `warn` — partially met or needs attention
- `na` — not applicable to this PR

For findings use severity: `critical`, `high`, `medium`, `low`, `info`

For verdict use: `APPROVE`, `REQUEST_CHANGES`, or `COMMENT`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Review — {PR_TITLE}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;line-height:1.6;padding:0}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}

.review-header{background:linear-gradient(135deg,#1a2332 0%,#0d1117 60%,#1a1f2e 100%);border-bottom:1px solid #30363d;padding:32px 40px 28px}
.pr-meta{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.pr-repo{font-size:13px;color:#8b949e;font-weight:500}
.pr-num{font-size:13px;font-weight:700;color:#58a6ff;background:rgba(88,166,255,.1);padding:2px 8px;border-radius:12px;border:1px solid rgba(88,166,255,.25)}
.pr-title{font-size:24px;font-weight:700;color:#f0f6fc;margin-bottom:14px;line-height:1.3}
.pr-info{display:flex;flex-wrap:wrap;gap:16px}
.pr-info-item{display:flex;align-items:center;gap:5px;font-size:12px;color:#8b949e}
.pr-info-item svg{opacity:.7}
.pr-info-val{color:#c9d1d9;font-weight:500}
.pr-stat-add{color:#3fb950}
.pr-stat-del{color:#f85149}

.container{max-width:1100px;margin:0 auto;padding:32px 40px}
.section{margin-bottom:40px}
.section-title{font-size:16px;font-weight:700;color:#f0f6fc;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:8px}
.section-title svg{opacity:.7}

.summary-box{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:18px 20px;font-size:14px;color:#c9d1d9;line-height:1.7}
.summary-box p{margin-bottom:10px}
.summary-box p:last-child{margin-bottom:0}

/* Checklist table */
.checklist-table{width:100%;border-collapse:collapse;border:1px solid #30363d;border-radius:8px;overflow:hidden;font-size:13px}
.checklist-table thead tr{background:#161b22}
.checklist-table th{padding:10px 14px;text-align:left;font-weight:600;color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #30363d}
.checklist-table td{padding:10px 14px;border-bottom:1px solid #21262d;vertical-align:top}
.checklist-table tbody tr:last-child td{border-bottom:none}
.checklist-table tbody tr:hover{background:#161b22}
.cat-label{font-weight:600;color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding-top:14px}

.status-pill{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;letter-spacing:.04em;white-space:nowrap}
.status-pass{background:rgba(63,185,80,.12);color:#3fb950;border:1px solid rgba(63,185,80,.25)}
.status-fail{background:rgba(248,81,73,.12);color:#f85149;border:1px solid rgba(248,81,73,.25)}
.status-warn{background:rgba(210,153,34,.12);color:#d2993c;border:1px solid rgba(210,153,34,.25)}
.status-na{background:rgba(139,148,158,.1);color:#8b949e;border:1px solid rgba(139,148,158,.2)}
.notes-cell{color:#8b949e;font-size:12px}

/* Findings */
.findings-list{display:flex;flex-direction:column;gap:12px}
.finding-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:0;overflow:hidden}
.finding-card.sev-critical{border-left:3px solid #f85149}
.finding-card.sev-high{border-left:3px solid #ff7b72}
.finding-card.sev-medium{border-left:3px solid #d29922}
.finding-card.sev-low{border-left:3px solid #388bfd}
.finding-card.sev-info{border-left:3px solid #8b949e}
.finding-header{display:flex;align-items:flex-start;gap:10px;padding:14px 16px 10px}
.finding-sev{font-size:10px;font-weight:800;padding:3px 8px;border-radius:10px;letter-spacing:.08em;white-space:nowrap;margin-top:2px}
.sev-critical .finding-sev{background:rgba(248,81,73,.18);color:#f85149}
.sev-high .finding-sev{background:rgba(255,123,114,.12);color:#ff7b72}
.sev-medium .finding-sev{background:rgba(210,153,34,.15);color:#d29922}
.sev-low .finding-sev{background:rgba(56,139,253,.12);color:#388bfd}
.sev-info .finding-sev{background:rgba(139,148,158,.12);color:#8b949e}
.finding-title{font-size:14px;font-weight:600;color:#f0f6fc;flex:1}
.finding-body{padding:0 16px 14px;font-size:13px;color:#c9d1d9;line-height:1.65}
.finding-location{font-family:'SF Mono',Consolas,'Liberation Mono',Menlo,monospace;font-size:12px;color:#58a6ff;background:rgba(88,166,255,.07);padding:6px 10px;border-radius:6px;margin-bottom:10px;word-break:break-all}
.finding-rec{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px 12px;margin-top:10px;font-size:12px;color:#8b949e}
.finding-rec strong{color:#c9d1d9;display:block;margin-bottom:4px}
code{font-family:'SF Mono',Consolas,'Liberation Mono',Menlo,monospace;font-size:12px;background:#0d1117;padding:2px 5px;border-radius:4px;border:1px solid #30363d;color:#79c0ff}
pre{font-family:'SF Mono',Consolas,'Liberation Mono',Menlo,monospace;font-size:12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;overflow-x:auto;margin:8px 0;color:#e6edf3}
.no-findings{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:24px;text-align:center;color:#8b949e;font-size:13px}

/* Impact table */
.impact-table{width:100%;border-collapse:collapse;font-size:13px}
.impact-table th{text-align:left;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:.06em;padding:8px 12px;border-bottom:1px solid #30363d}
.impact-table td{padding:10px 12px;border-bottom:1px solid #21262d;color:#c9d1d9;vertical-align:top}
.impact-table tr:last-child td{border-bottom:none}
.impact-table .dim{color:#8b949e;font-size:12px}

/* Verdict */
.verdict-block{border-radius:10px;padding:24px 28px;margin-bottom:40px;display:flex;align-items:flex-start;gap:20px}
.verdict-approve{background:rgba(63,185,80,.08);border:2px solid rgba(63,185,80,.35)}
.verdict-changes{background:rgba(248,81,73,.08);border:2px solid rgba(248,81,73,.35)}
.verdict-comment{background:rgba(56,139,253,.08);border:2px solid rgba(56,139,253,.35)}
.verdict-icon{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:22px}
.verdict-approve .verdict-icon{background:rgba(63,185,80,.2)}
.verdict-changes .verdict-icon{background:rgba(248,81,73,.2)}
.verdict-comment .verdict-icon{background:rgba(56,139,253,.2)}
.verdict-content{flex:1}
.verdict-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px}
.verdict-approve .verdict-label{color:#3fb950}
.verdict-changes .verdict-label{color:#f85149}
.verdict-comment .verdict-label{color:#388bfd}
.verdict-title{font-size:20px;font-weight:700;color:#f0f6fc;margin-bottom:8px}
.verdict-reason{font-size:13px;color:#c9d1d9;line-height:1.65}

/* Stats row */
.stats-row{display:flex;gap:12px;margin-bottom:32px;flex-wrap:wrap}
.stat-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 18px;flex:1;min-width:120px}
.stat-value{font-size:22px;font-weight:700;color:#f0f6fc}
.stat-label{font-size:11px;color:#8b949e;margin-top:2px}

footer{text-align:center;padding:24px 40px;border-top:1px solid #21262d;font-size:12px;color:#484f58;margin-top:20px}
</style>
</head>
<body>

<!-- ── Header ── -->
<div class="review-header">
  <div class="pr-meta">
    <span class="pr-repo">{REPO}</span>
    <span class="pr-num">#{PR_NUMBER}</span>
  </div>
  <h1 class="pr-title">{PR_TITLE}</h1>
  <div class="pr-info">
    <span class="pr-info-item">
      <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor"><path d="M8 0a8 8 0 100 16A8 8 0 008 0zm0 14A6 6 0 118 2a6 6 0 010 12z"/><path d="M8 4a1 1 0 011 1v3.586l2.207 2.207a1 1 0 01-1.414 1.414l-2.5-2.5A1 1 0 017 9V5a1 1 0 011-1z"/></svg>
      <span class="pr-info-val">{REVIEWED_AT}</span>
    </span>
    <span class="pr-info-item">
      <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor"><path d="M10.5 5a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0zm.061 3.073a4 4 0 10-5.123 0 6.004 6.004 0 00-3.431 5.142.75.75 0 001.498.07 4.5 4.5 0 018.99 0 .75.75 0 001.498-.07 6.004 6.004 0 00-3.432-5.142z"/></svg>
      Author: <span class="pr-info-val">{AUTHOR}</span>
    </span>
    <span class="pr-info-item">
      Base: <span class="pr-info-val">{BASE_BRANCH}</span>
    </span>
    <span class="pr-info-item">
      <span class="pr-stat-add">+{ADDITIONS}</span>&nbsp;/&nbsp;<span class="pr-stat-del">-{DELETIONS}</span>
      <span style="margin-left:4px">in {CHANGED_FILES} files</span>
    </span>
  </div>
</div>

<div class="container">

<!-- ── Stats ── -->
<div class="stats-row">
  <div class="stat-card">
    <div class="stat-value">{CHANGED_FILES}</div>
    <div class="stat-label">Files Changed</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color:#3fb950">+{ADDITIONS}</div>
    <div class="stat-label">Lines Added</div>
  </div>
  <div class="stat-card">
    <div class="stat-value" style="color:#f85149">-{DELETIONS}</div>
    <div class="stat-label">Lines Deleted</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{TOTAL_FINDINGS}</div>
    <div class="stat-label">Findings</div>
  </div>
</div>

<!-- ── Verdict ── -->
<div class="verdict-block verdict-{VERDICT_CLASS}">
  <div class="verdict-icon">{VERDICT_EMOJI}</div>
  <div class="verdict-content">
    <div class="verdict-label">Verdict</div>
    <div class="verdict-title">{VERDICT}</div>
    <div class="verdict-reason">{VERDICT_REASON}</div>
  </div>
</div>

<!-- ── Summary ── -->
<div class="section">
  <div class="section-title">
    <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor"><path d="M0 2.75A2.75 2.75 0 012.75 0h10.5A2.75 2.75 0 0116 2.75v10.5A2.75 2.75 0 0113.25 16H2.75A2.75 2.75 0 010 13.25V2.75zm2.75-.25c-.69 0-1.25.56-1.25 1.25v10.5c0 .69.56 1.25 1.25 1.25h10.5c.69 0 1.25-.56 1.25-1.25V2.75c0-.69-.56-1.25-1.25-1.25H2.75z"/><path d="M3.5 5.5A.5.5 0 014 5h8a.5.5 0 010 1H4a.5.5 0 01-.5-.5zm0 3A.5.5 0 014 8h8a.5.5 0 010 1H4a.5.5 0 01-.5-.5zm0 3A.5.5 0 014 11h5a.5.5 0 010 1H4a.5.5 0 01-.5-.5z"/></svg>
    What Does This PR Do
  </div>
  <div class="summary-box">{SUMMARY_HTML}</div>
</div>

<!-- ── Review Checklist ── -->
<div class="section">
  <div class="section-title">
    <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor"><path d="M2.5 1.75v11.5c0 .138.112.25.25.25h10.5a.25.25 0 00.25-.25V1.75a.25.25 0 00-.25-.25H2.75a.25.25 0 00-.25.25zM2.75 0h10.5A1.75 1.75 0 0115 1.75v11.5A1.75 1.75 0 0113.25 15H2.75A1.75 1.75 0 011 13.25V1.75A1.75 1.75 0 012.75 0z"/><path d="M10.583 4.021a.75.75 0 01.171 1.045l-3.5 5a.75.75 0 01-1.156.1L4.73 8.398a.75.75 0 011.04-1.08l.944.91 2.99-4.273a.75.75 0 011.879.066z"/></svg>
    Review Checklist
  </div>
  <table class="checklist-table">
    <thead>
      <tr>
        <th style="width:160px">Category</th>
        <th>Criterion</th>
        <th style="width:90px">Status</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
      <!-- CODE QUALITY -->
      <tr><td colspan="4" class="cat-label" style="background:#0d1117">Code Quality</td></tr>
      <tr>
        <td></td>
        <td>Naming is clear and consistent with codebase conventions</td>
        <td><span class="status-pill status-{CQ_NAMING}">{CQ_NAMING_LABEL}</span></td>
        <td class="notes-cell">{CQ_NAMING_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Functions/classes have single responsibility; no excessive complexity</td>
        <td><span class="status-pill status-{CQ_COMPLEXITY}">{CQ_COMPLEXITY_LABEL}</span></td>
        <td class="notes-cell">{CQ_COMPLEXITY_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>No dead code, unused imports, or commented-out blocks</td>
        <td><span class="status-pill status-{CQ_DEAD_CODE}">{CQ_DEAD_CODE_LABEL}</span></td>
        <td class="notes-cell">{CQ_DEAD_CODE_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>No unnecessary duplication — shared helpers used where appropriate</td>
        <td><span class="status-pill status-{CQ_DUPLICATION}">{CQ_DUPLICATION_LABEL}</span></td>
        <td class="notes-cell">{CQ_DUPLICATION_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Error handling: exceptions caught at the right level, not swallowed</td>
        <td><span class="status-pill status-{CQ_ERRORS}">{CQ_ERRORS_LABEL}</span></td>
        <td class="notes-cell">{CQ_ERRORS_NOTES}</td>
      </tr>

      <!-- SECURITY -->
      <tr><td colspan="4" class="cat-label" style="background:#0d1117">Security</td></tr>
      <tr>
        <td></td>
        <td>All external inputs validated/sanitized before use</td>
        <td><span class="status-pill status-{SEC_INPUT}">{SEC_INPUT_LABEL}</span></td>
        <td class="notes-cell">{SEC_INPUT_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Auth / permission checks present on every protected action</td>
        <td><span class="status-pill status-{SEC_AUTH}">{SEC_AUTH_LABEL}</span></td>
        <td class="notes-cell">{SEC_AUTH_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>No secrets, keys, or credentials in code</td>
        <td><span class="status-pill status-{SEC_SECRETS}">{SEC_SECRETS_LABEL}</span></td>
        <td class="notes-cell">{SEC_SECRETS_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>No injection risks (SQL, XSS, command, path traversal)</td>
        <td><span class="status-pill status-{SEC_INJECTION}">{SEC_INJECTION_LABEL}</span></td>
        <td class="notes-cell">{SEC_INJECTION_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Sensitive data not exposed in logs, responses, or serializers</td>
        <td><span class="status-pill status-{SEC_DATA}">{SEC_DATA_LABEL}</span></td>
        <td class="notes-cell">{SEC_DATA_NOTES}</td>
      </tr>

      <!-- TESTING -->
      <tr><td colspan="4" class="cat-label" style="background:#0d1117">Testing</td></tr>
      <tr>
        <td></td>
        <td>Tests added / updated for all new or changed behaviour</td>
        <td><span class="status-pill status-{TEST_COVERAGE}">{TEST_COVERAGE_LABEL}</span></td>
        <td class="notes-cell">{TEST_COVERAGE_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Failure / edge-case paths tested, not just the happy path</td>
        <td><span class="status-pill status-{TEST_EDGE}">{TEST_EDGE_LABEL}</span></td>
        <td class="notes-cell">{TEST_EDGE_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Assertions are meaningful (verify data shape, not just status codes)</td>
        <td><span class="status-pill status-{TEST_ASSERT}">{TEST_ASSERT_LABEL}</span></td>
        <td class="notes-cell">{TEST_ASSERT_NOTES}</td>
      </tr>

      <!-- PERFORMANCE & RELIABILITY -->
      <tr><td colspan="4" class="cat-label" style="background:#0d1117">Performance &amp; Reliability</td></tr>
      <tr>
        <td></td>
        <td>No N+1 queries or unnecessary repeated DB calls</td>
        <td><span class="status-pill status-{PERF_N1}">{PERF_N1_LABEL}</span></td>
        <td class="notes-cell">{PERF_N1_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>No blocking I/O or expensive ops in loops / hot paths</td>
        <td><span class="status-pill status-{PERF_BLOCKING}">{PERF_BLOCKING_LABEL}</span></td>
        <td class="notes-cell">{PERF_BLOCKING_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>External calls have timeouts and reasonable retry handling</td>
        <td><span class="status-pill status-{PERF_TIMEOUT}">{PERF_TIMEOUT_LABEL}</span></td>
        <td class="notes-cell">{PERF_TIMEOUT_NOTES}</td>
      </tr>

      <!-- OBSERVABILITY & DOCS -->
      <tr><td colspan="4" class="cat-label" style="background:#0d1117">Observability &amp; Documentation</td></tr>
      <tr>
        <td></td>
        <td>Meaningful logs at the right level (info/warning/error)</td>
        <td><span class="status-pill status-{OBS_LOGS}">{OBS_LOGS_LABEL}</span></td>
        <td class="notes-cell">{OBS_LOGS_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>Public API / interface changes are documented</td>
        <td><span class="status-pill status-{OBS_DOCS}">{OBS_DOCS_LABEL}</span></td>
        <td class="notes-cell">{OBS_DOCS_NOTES}</td>
      </tr>
      <tr>
        <td></td>
        <td>PR description explains the WHY, not just the what</td>
        <td><span class="status-pill status-{OBS_PR_DESC}">{OBS_PR_DESC_LABEL}</span></td>
        <td class="notes-cell">{OBS_PR_DESC_NOTES}</td>
      </tr>
    </tbody>
  </table>
</div>

<!-- ── Findings ── -->
<div class="section">
  <div class="section-title">
    <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor"><path d="M8.22 1.754a.25.25 0 00-.44 0L1.698 13.132a.25.25 0 00.22.368h12.164a.25.25 0 00.22-.368L8.22 1.754zm-1.763-.707c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0114.082 15H1.918a1.75 1.75 0 01-1.543-2.575L6.457 1.047zM9 11a1 1 0 11-2 0 1 1 0 012 0zm-.25-5.25a.75.75 0 00-1.5 0v2.5a.75.75 0 001.5 0v-2.5z"/></svg>
    Findings
  </div>
  <div class="findings-list">
    {FINDINGS_HTML}
  </div>
</div>

<!-- ── Impact ── -->
<div class="section">
  <div class="section-title">
    <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor"><path d="M1.5 1.75V13.5h13.75a.75.75 0 010 1.5H.75a.75.75 0 01-.75-.75V1.75a.75.75 0 011.5 0z"/><path d="M9.22 10.22L7.75 8.75 5.28 11.22a.75.75 0 01-1.06-1.06l3-3a.75.75 0 011.06 0l1.47 1.47 2.97-4.454a.75.75 0 111.247.832l-3.5 5.25a.75.75 0 01-1.253-.034z"/></svg>
    Impact Assessment
  </div>
  <table class="impact-table">
    <thead>
      <tr><th>Area</th><th>Assessment</th></tr>
    </thead>
    <tbody>
      <tr>
        <td style="font-weight:600;color:#c9d1d9;white-space:nowrap">API Contract</td>
        <td>{IMPACT_API}</td>
      </tr>
      <tr>
        <td style="font-weight:600;color:#c9d1d9;white-space:nowrap">Database / Schema</td>
        <td>{IMPACT_DB}</td>
      </tr>
      <tr>
        <td style="font-weight:600;color:#c9d1d9;white-space:nowrap">Performance</td>
        <td>{IMPACT_PERF}</td>
      </tr>
      <tr>
        <td style="font-weight:600;color:#c9d1d9;white-space:nowrap">Security</td>
        <td>{IMPACT_SEC}</td>
      </tr>
      <tr>
        <td style="font-weight:600;color:#c9d1d9;white-space:nowrap">Rollback Risk</td>
        <td>{IMPACT_ROLLBACK}</td>
      </tr>
    </tbody>
  </table>
</div>

</div><!-- /container -->

<footer>
  AI Code Review · {REPO} #{PR_NUMBER} · Reviewed {REVIEWED_AT} · Generated by AI Orchestrator
</footer>

</body>
</html>
```

**Filling in finding cards** — for each finding, use this HTML snippet:

```html
<!-- replace SEVERITY with: critical | high | medium | low | info -->
<div class="finding-card sev-SEVERITY">
  <div class="finding-header">
    <span class="finding-sev">SEVERITY</span>
    <span class="finding-title">Finding Title</span>
  </div>
  <div class="finding-body">
    <div class="finding-location">path/to/file.py · line N</div>
    <p>Description of the issue — what is wrong, why it matters.</p>
    <pre>// problematic code snippet (optional)</pre>
    <div class="finding-rec">
      <strong>Recommendation</strong>
      What to do to fix it.
    </div>
  </div>
</div>
```

When there are no findings in a severity category, omit cards for that level.  
If there are zero findings total, replace the findings list with:

```html
<div class="no-findings">✓ No significant findings — code looks clean.</div>
```

**Verdict mapping:**
- `APPROVE` → `verdict-class=approve`, emoji=`✓`
- `REQUEST_CHANGES` → `verdict-class=changes`, emoji=`✗`
- `COMMENT` → `verdict-class=comment`, emoji=`◎`

---

## Step 7 — Write Review Markdown

Write `reviews/<review_id>/review.md` with this structure:

```markdown
# Code Review — {PR_TITLE}

**Repo:** {REPO} · **PR:** #{PR_NUMBER} · **Author:** {AUTHOR} · **Base:** {BASE_BRANCH}  
**Changes:** +{ADDITIONS} / -{DELETIONS} across {CHANGED_FILES} files · **Reviewed:** {REVIEWED_AT}

---

## Verdict: {VERDICT}

{VERDICT_REASON}

---

## Summary

{SUMMARY}

---

## Review Checklist

| Category | Criterion | Status | Notes |
|----------|-----------|--------|-------|
| Code Quality | Naming clear and consistent | {STATUS} | {NOTES} |
... (all rows) ...

---

## Findings

### {SEVERITY}: {TITLE}

**Location:** `{file}:{line}`

{description}

**Recommendation:** {recommendation}

---

## Impact Assessment

| Area | Assessment |
|------|-----------|
| API Contract | {value} |
| Database / Schema | {value} |
| Performance | {value} |
| Security | {value} |
| Rollback Risk | {value} |
```

---

## Step 8 — Update Status

Update `reviews/<review_id>/status.json`:
- `status` → `"COMPLETED"`
- `verdict` → `"APPROVE"` | `"REQUEST_CHANGES"` | `"COMMENT"`
- `updated_at` → current ISO-8601 timestamp

If any step fails (gh CLI error, network issue), set `status` → `"FAILED"` and write the error message to `reviews/<review_id>/error.txt`.

---

## Heartbeat

Update `updated_at` in `reviews/<review_id>/status.json` every 2 minutes while the review is running.
