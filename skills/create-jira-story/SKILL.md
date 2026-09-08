---
name: create-jira-story
description: Creates a new Jira Story from an approved plan using a 9-section description with full technical detail (models, serializers, endpoints with request/response schemas, component hierarchy, UX states, impact/blast-radius, integration contract). Markdown-first assembly with a hard completeness gate that refuses to drop tasks, models, fields, endpoints, or FE functions present in the plan. Supports multiple backend repos. Invoked by /create-plan Step 2f (assembly) — never directly.
---

# Skill: Create Jira Story

## 1. Purpose

Given an approved plan and its implementation units, either create a new Jira Story with a comprehensive 9-section description or append a plan-summary comment to an existing ticket.

The description must be **complete enough for an engineer to implement without opening any other document.** It is a faithful projection of the plan — every model, every field, every endpoint, every task, every FE function, and every serializer that exists in the plan MUST appear in the Story. Dropping content is the primary failure mode this skill exists to prevent (see §4a Completeness Gate).

Return the Jira issue key so the assembly step can populate `delivery.jira_tickets`.

## 2. When Invoked

Invoked by `/create-plan` Step 2f assembly Step 7, after the user approves the task DAG and the slug is derived. Never invoked directly.

## 3. Inputs

- `plan_title` — the 3–5 word noun phrase derived in 2f Step 1
- `plan_id` — the slug from 2f Step 6 (e.g. `20260828-jarvis-schedule-management`)
- `context` — from the approved brainstorming summary: `problem`, `user`, `success_criteria` (list), `scope`, `constraints` (list)
- `open_risks` — the "Open risks" field (list)
- `repos` — list of repos from 2c, each `{name, kind}` where `kind ∈ {backend, frontend, full-stack, lambda, lambda-layer}`
- `backend_units` — ordered implementation units from 2d, grouped by repo
- `frontend_units` — ordered implementation units from 2e
- `task_dag` — the full ordered task list (ID, title, repo, type, depends-on) — the authoritative task count
- `plan_data` — the plan's Data section: every model with every column (authoritative field list)
- `plan_endpoints` — every API path in the plan (authoritative endpoint list)
- `plan_fe_functions` — every FE API-client function named in the plan (authoritative FE list)
- `jira_key` — the `--jira` value if provided, otherwise `null`

> If any of `task_dag`, `plan_data`, `plan_endpoints`, `plan_fe_functions` is not passed explicitly, derive it by re-reading `plans/<plan_id>/plan.md` before assembly. The Completeness Gate depends on these being the *plan's* authoritative lists, not the unit summaries — unit summaries are where content silently narrows.

## 4. Workflow

The order is deliberate: **build the ledger → write markdown → run the gate → convert to ADF → create.** Do not author ADF directly from the units. ADF is generated only in Step 3, from finished markdown that has already passed the gate.

### Step 0 — Resolve Jira Configuration

Read `config/integrations.json` → `jira`:

| Field | Key | Required |
|---|---|---|
| Instance URL | `jira.base_url` | Yes |
| Auth email | `jira.email` | Yes (REST fallback) |
| Auth token | `jira.api_token` | Yes (REST fallback) |
| Default project | `jira.default_project` | Yes |
| Per-repo project map | `jira.projects` | Optional |
| Default assignee | `jira.default_assignee` | Optional |
| Default epic key | `jira.default_epic_key` | Optional |

**Resolve project key:**
1. If `repos[0].name` is a key in `jira.projects`, use that value.
2. Otherwise use `jira.default_project`.
3. If neither is set, or `base_url` / `api_token` are missing after env-var substitution: warn and return `null` — do not block plan creation.

---

### Step 1 — Build the Coverage Ledger

Before writing anything, enumerate — from the **plan**, not the unit summaries — the exact things the Story must contain. Hold these counts; the gate in §4a checks against them.

```
LEDGER
  tasks_expected        = count(task_dag)                       e.g. 15
  models_expected       = list of model names in plan_data      e.g. [Schedule, ScheduleExecution, ScheduleGroup,
                                                                       ScheduleTag, ScheduleScheduleGroup,
                                                                       ScheduleScheduleTag, ScheduleDeleteRule]
  fields_expected[M]    = column list per model from plan_data   (Schedule → 17 columns incl. sync_error)
  endpoints_expected    = every path in plan_endpoints           (incl. /<id>/sync/ and /sync-all/)
  serializers_expected  = 1+ if any unit is "add serializers"    (task-002 present → serializer block REQUIRED)
  fe_funcs_expected     = list from plan_fe_functions            e.g. 26 functions incl. sync{,All}ScheduleApi
  impact_targets        = existing files/tables/shared components the plan modifies
```

The ledger is the contract. If the plan says 15 tasks, the Story has 15 rows — no exceptions, no "representative subset."

---

### Step 2 — Write the Story in Markdown

Assemble the full description in human-readable markdown first. Nine sections, in order. Derive each from the inputs — never invent content not in the plan, and never omit content that is.

**Section map:**

| # | Section | Source |
|---|---------|--------|
| 1 | Background & Problem | `context.problem` + `context.user` |
| 2 | User Story | `context.user` (role) + `context.problem` + `context.success_criteria` |
| 3 | Scope (In / Out) | `context.scope` + `context.success_criteria` / `context.constraints` |
| 4 | Acceptance Criteria | `context.success_criteria` — one checkable item each |
| 5 | **Impact & Affected Areas** | `impact_targets` — see template below |
| 6 | Risks & Assumptions | `open_risks` |
| 7 | Definition of Done | standard items + layer-specific + migration/seed conditionals |
| 8 | Implementation Units | **all** `task_dag` rows as a table |
| 9 | Technical Notes | 9a backend (per repo) · 9b frontend (per repo) · 9c integration |

#### Section 5 template — Impact & Affected Areas (NEW)

This is the blast-radius analysis. For anything the plan **modifies** (as opposed to newly creates), state what breaks if it's wrong and who else depends on it. Populate every subsection that applies; omit only those with genuinely nothing.

```
h2. 5. Impact & Affected Areas

*Modified existing code:*
· <file/function> — <what changes> — <other callers affected>
  e.g. be-driver-operations lambda_function.py: handle_queue_message(event, config)
       → (event, config, context=None). Any other invoker of this function breaks
       unless updated; context is now threaded through for timeout detection.

*Shared components touched:*
· <component> — <blast radius across consumers>
  e.g. be-common-utils-layer: new schedule_tracker.py module. Other Lambdas on the
       Layer are unaffected until they adopt on_start/on_finish, but a Layer publish
       bumps the version every attached Lambda references.

*Database impact:*
· New tables: <list> — no contention with existing schema.
· Modified tables: <list or "none">.
· Write-load / shared-DB notes: <e.g. Lambdas now write ScheduleExecution rows directly
  to shared MySQL on every fire — sizing note for 100+ schedules>.

*Deployment coupling & ordering:*
· <what must deploy together or in a fixed order — cross-repo>
  e.g. Layer must be published & attached BEFORE be-driver-operations code deploy,
       or cold start fails on import.

*Backwards compatibility & rollout:*
· <what must keep working during rollout>
  e.g. All 100–110 schedules keep firing throughout. Lambdas without the Layer execute
       correctly and simply write no history — graceful degradation, not an error.

*Out-of-scope follow-ups this creates:*
· <delivery notes that become future tickets>
  e.g. Attaching the Layer to the remaining 100+ Lambdas — per-Lambda: attach ARN +
       confirm schedule_id in payload. Track separately.
```

#### Sections 1–4, 6–8 (unchanged structure)

```
h2. 1. Background & Problem
[2–4 sentences: what is broken/missing, who is affected and how often, why now.]

h2. 2. User Story
As a <role>, I want to <capability>, so that <benefit>.

h2. 3. Scope
h3. In Scope   — numbered; one item per scope item + success criterion
h3. Out of Scope — bulleted; one item per constraint

h2. 4. Acceptance Criteria — bulletList, "AC-n — <criterion>" (NEVER taskList)

h2. 6. Risks & Assumptions — bulletList, one per open_risk

h2. 7. Definition of Done — bulletList (NEVER taskList):
· Code reviewed and approved
· Deployed to staging and smoke-tested
· Jira story moved to Done
· [both BE+FE] BE–FE API contract verified end-to-end on staging
· [schema migration] Migrations applied on staging; rollback verified; manual partition/raw-SQL steps run
· [data migration] Migration run on staging; record count verified vs source; flagged records reviewed
· [seed/mgmt command] Command run on staging; feature visible to test user
· [shared layer/lambda] Layer attached on staging; test invocation writes expected row

h2. 8. Implementation Units — table with EVERY task_dag row:
| ID | Title | Repo | Type | Depends On |
```

#### Section 9 — Technical Notes (the reference layer)

One `9a. Backend: <repo>` per backend/full-stack/lambda/lambda-layer repo; one `9b. Frontend: <repo>` per frontend/full-stack repo; `9c. Integration` only when both BE and FE are in scope.

```
h3. 9a. Backend: <repo>

*New Models:* — for EVERY model in models_expected, EVERY field in fields_expected[M]:
  <Model> (db_table='<t>', inherits <Base>):
    <field>: <Type>(<constraints>) — <note if non-obvious>
    Meta: indexes=[...], unique_together=[...]
  # Every column from the plan's Data table appears here. A field like sync_error that
  # drives downstream UX is exactly the kind that gets dropped — it MUST be present.

*Serializers / Validation:* — REQUIRED whenever a serializer unit exists. Not optional.
  <Serializer>: <read|write|both>
    required: [...]  optional: [...]
    cross-field: <constraints>
    M2M handling: <clear-and-re-add | delta patch> for group_ids / tag_ids

*API Endpoints:* — for EVERY path in endpoints_expected, the full contract:
  <METHOD> <path>
  Auth: <mechanism>
  Query/Body: { "<field>": "<type> (required|optional, default) — <desc>" }
  Response 200/201: { ... }
  Response 400/403: { "message": "<error>" }
  Notes: <rollback / idempotency key / pagination>
  # List list, create, retrieve, update, delete, AND every custom action separately —
  # pause, resume, trigger, executions, sync, sync-all are each their own entry.

*Lambda Layer integration (if applicable):* execution flow, hook points, DB-write pattern, dedup.
*Management commands (if applicable):* name — what it does, when to run, idempotency.
*Schema migration notes:* reversible? zero-downtime? post-migration manual steps (raw-SQL partitions).
*Data migration (if plan imports/backfills/seeds):* command, what, online/offline, idempotency,
  rollback, when-to-run, verification.

h3. 9b. Frontend: <repo>

*Page / Route Registration:* dashboard uri, role, sidebar parent_uri, User_Module, router entry,
  post-deploy seed command.
*Component Hierarchy:* shell → screen → tabs/drawer tree (actual file paths).
*API Client (src/services/api/<module>.js):* EVERY function in fe_funcs_expected —
  <fn>(<params>) → <METHOD> <path> [SERVER.<KEY>]. Count MUST match fe_funcs_expected.
*Tab / Screen structure:* per tab — fetches, components, key state.
*UX States:* per major flow — loading, success, validation error, network error, blocked action,
  empty state. Include states tied to model fields (e.g. sync_error → "Sync Error" badge + banner).
*Design system:* reference screen path, primary button style, badge tokens, form-card className.

h3. 9c. Integration (only if BE and FE both in scope)

*FE↔BE Contract Table:* one row per FE function — | FE fn | Method | Path | Server | Key req | Key resp |
*Auth convention:* how the header is attached.
*Error-code handling:* 400 validation / 400 blocked / 401 / 403 / 500 — each with FE display behaviour.
*Order of work:* what lands first, what parallelizes against a contract, what deploys together.
```

---

### Step 2a — Completeness Gate  ⛔ (hard stop)

**Before converting to ADF, audit the finished markdown against the ledger. Emit the counts. If any line fails, the content was dropped — regenerate that section and re-run the gate. Do not proceed on a failing gate.**

```
GATE
  [ ] Section 8 row count            == tasks_expected           (15 == 15)
  [ ] 9a model blocks                == models_expected          (7 models present)
  [ ] each model's field count       == fields_expected[M]       (Schedule has sync_error? y/n)
  [ ] every endpoint in plan present in 9a                       (/sync/ and /sync-all/ present? y/n)
  [ ] serializer block present       iff serializers_expected>0  (task-002 exists → block present? y/n)
  [ ] 9b API-client fn count         == fe_funcs_expected        (26 == 26; sync fns present? y/n)
  [ ] Section 5 impact populated     for every impact_target     (handle_queue_message change listed? y/n)
  [ ] no "<placeholder>" / "<title>" / "..." angle-bracket stubs remain in final text
  [ ] depends-on edges in Section 8 match task_dag exactly       (task-008 → 004 AND 015? y/n)
```

A short subset is never acceptable in place of the full list. "Representative examples" is the failure this gate exists to stop. If the plan has 15 tasks and the draft has 14, find the missing one (it is usually a late-wave task whose downstream artifacts — an endpoint, a field, an FE function — also vanished) and restore the whole chain.

---

### Step 3 — Convert Markdown → ADF

Only now, mechanically convert the gate-passed markdown into the ADF `content` array. Node mapping:

- `h2.` → `heading` level 2 · `h3.` → `heading` level 3 · `----` → `rule`
- prose → `paragraph`
- In Scope → `orderedList`; every other list → `bulletList` (**never `taskList` in a description**)
- code/tables/tree blocks → `codeBlock` with `attrs.language` (`python` | `javascript` | `text`)
- inline emphasis → `marks: [{type:"strong"}]` / `{type:"em"}`

Preserve every list item and every code block from the markdown — the conversion is 1:1, not a re-summarization. Section 9's model/endpoint/component blocks are `codeBlock`s so long technical content survives intact.

---

### Step 4 — Create or Update

**Field mapping:**

| Jira Field | Source | Notes |
|---|---|---|
| `summary` | `plan_title` | Required |
| `description` | ADF from Step 3 | see §5 |
| `issuetype` | `"Story"` | Fixed |
| `project.key` | Step 0 | Required |
| `labels` | `["planner", plan_id]` | Always |
| `assignee.accountId` | `jira.default_assignee` | Omit if unset |
| `customfield_10014` | `jira.default_epic_key` | Epic link — omit if unset |

#### Case A — `--jira` provided (existing ticket): post a plan-summary comment (§5 Comment ADF), return `jira_key`.

**MCP first:** `mcp__atlassian__create_comment(issue_key=<jira_key>, body=<ADF comment>)`
**REST fallback:** `POST {base_url}/rest/api/3/issue/{jira_key}/comment` with Basic auth, `{ "body": <ADF> }`.

#### Case B — no `--jira` (create new Story):

**MCP first:**
```
mcp__atlassian__create_issue(
  project_key=<resolved>, summary="<plan_title>", issue_type="Story",
  labels=["planner","<plan_id>"], description=<ADF description>,
  assignee_account_id=<jira.default_assignee if set>,
  customfield_10014=<jira.default_epic_key if set>)
```
**REST fallback:** `POST {base_url}/rest/api/3/issue` with Basic auth and the `fields` object (project, summary, issuetype, labels, description; assignee/epic only if configured).

Capture and return the issue key (e.g. `"JAR-42"`).

### Step 5 — Return

Return the Jira key to `/create-plan` assembly, which writes `delivery.jira_tickets: ["<key>"]` into plan.json.

---

## 5. ADF Objects

### ⚠️ Critical ADF Rules

1. **NEVER `taskList`/`taskItem` in the `description` field** — Jira returns `400: not valid ADF`. Use `bulletList`/`listItem` for Acceptance Criteria and Definition of Done. (`taskList` IS allowed in comments — Case A only.)
2. **`codeBlock` needs `"attrs": {"language": "<lang>"}`** — omitting `attrs` causes a 400. Use `"text"` when no language fits.
3. **`localId` values in any `taskList`/`taskItem` must be unique** within the document — sequential IDs.
4. **Never nest `paragraph` inside `paragraph`.**

### Description ADF — new Story (Case B)

Build the `content` array in section order 1→9, following the node mapping in Step 3. Each section's lists expand to one `listItem` per ledger entry; each Section 9 technical block is a `codeBlock`. No angle-bracket placeholders survive into the payload.

```json
{ "type": "doc", "version": 1, "content": [
  {"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"1. Background & Problem"}]},
  {"type":"paragraph","content":[{"type":"text","text":"<actual problem + user + why now>"}]},
  {"type":"rule"},
  {"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"5. Impact & Affected Areas"}]},
  {"type":"paragraph","content":[{"type":"text","text":"Modified existing code:","marks":[{"type":"strong"}]}]},
  {"type":"bulletList","content":[
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"<file/fn — change — other callers affected>"}]}]}
  ]},
  {"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"8. Implementation Units"}]},
  {"type":"codeBlock","attrs":{"language":"text"},"content":[{"type":"text","text":"ID       Title                          Repo             Type          Depends On\n<ALL task_dag rows — count must equal tasks_expected>"}]},
  {"type":"heading","attrs":{"level":3},"content":[{"type":"text","text":"9a. Backend: <repo>"}]},
  {"type":"paragraph","content":[{"type":"text","text":"New Models:","marks":[{"type":"strong"}]}]},
  {"type":"codeBlock","attrs":{"language":"python"},"content":[{"type":"text","text":"<ALL models, ALL fields — including fields that drive UX like sync_error>"}]},
  {"type":"paragraph","content":[{"type":"text","text":"Serializers / Validation:","marks":[{"type":"strong"}]}]},
  {"type":"codeBlock","attrs":{"language":"text"},"content":[{"type":"text","text":"<serializer block — REQUIRED when a serializer unit exists>"}]},
  {"type":"paragraph","content":[{"type":"text","text":"API Endpoints:","marks":[{"type":"strong"}]}]},
  {"type":"codeBlock","attrs":{"language":"text"},"content":[{"type":"text","text":"<EVERY endpoint incl. /sync/ and /sync-all/ — full contracts>"}]}
]}
```
(Sections 2–4, 6–7, 9b, 9c follow the same node patterns; expand every list against the ledger.)

### Comment ADF — existing ticket (Case A)

```json
{ "type":"doc","version":1,"content":[
  {"type":"heading","attrs":{"level":3},"content":[{"type":"text","text":"Plan Linked"}]},
  {"type":"paragraph","content":[{"type":"text","text":"Plan: ","marks":[{"type":"strong"}]},{"type":"text","text":"<plan_title>"}]},
  {"type":"paragraph","content":[{"type":"text","text":"Plan ID: ","marks":[{"type":"strong"}]},{"type":"text","text":"<plan_id> · plans/<plan_id>/plan.md"}]},
  {"type":"heading","attrs":{"level":3},"content":[{"type":"text","text":"Acceptance Criteria"}]},
  {"type":"taskList","attrs":{"localId":"comment-ac"},"content":[
    {"type":"taskItem","attrs":{"localId":"cac-1","state":"TODO"},"content":[{"type":"paragraph","content":[{"type":"text","text":"AC-1 — <success_criteria[0]>"}]}]}
  ]},
  {"type":"heading","attrs":{"level":3},"content":[{"type":"text","text":"Implementation Summary"}]},
  {"type":"bulletList","content":[
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"<task-id>: <title> (<repo>)"}]}]}
  ]}
]}
```
Expand the `taskList` to one item per `success_criteria`, and the summary `bulletList` to **all** `task_dag` rows (unique `localId`s).

---

## 6. Files Read

- `config/integrations.json` — Jira config.
- `plans/<plan_id>/plan.md` — re-read when the authoritative lists (`task_dag`, `plan_data`, `plan_endpoints`, `plan_fe_functions`) are not passed explicitly. The Completeness Gate audits against these.

## 7. Files Written

None — returns the Jira key to `/create-plan`.

## 8. State Changes

None.

## 9. Failure Handling

- Jira config missing, or MCP + REST both fail: warn, return `null`. Assembly writes `jira_tickets: []`; plan creation continues.
- REST not 200/201: log status + body, warn, return `null`.
- 400 mentioning ADF: check for `taskList`/`taskItem` in the description (not allowed) → switch to `bulletList`; check `codeBlock` has `attrs.language`. Fix, retry **once**.
- A **failing Completeness Gate is not a Jira failure** — it is a content-assembly bug. Fix the markdown and re-run the gate; never ship a story that failed the gate, and never fall back to a shorter version to get past it.
- Never retry the API more than once after a fix.

## 10. Output

The Jira issue key (e.g. `"JAR-42"`), or `null` if Jira is unavailable.

## 11. Rules and Constraints

- Never invoked directly — always via `/create-plan` Step 2f.
- **Assembly order is fixed: ledger → markdown → gate → ADF → create.** Never author ADF straight from units.
- **The Completeness Gate is a hard stop.** If the plan has N tasks / M models / K endpoints / F FE functions, the Story has exactly those — a representative subset is a defect.
- **A serializer block is mandatory when a serializer unit exists** — it is not a conditional-to-taste section.
- **Section 5 (Impact) is mandatory** whenever the plan modifies existing code, shared components, or shared infrastructure.
- Model blocks include **every** column from the plan's Data tables — including fields whose only visible effect is downstream UX (e.g. a `sync_error` that produces status badges).
- **NEVER `taskList`/`taskItem` in the description** (allowed in comments only).
- `codeBlock` always carries `attrs.language`; `localId`s unique; no nested paragraphs.
- Section 9 subsections are conditional on repo kind; one `9a` per backend repo, one `9b` per frontend repo, `9c` only when both sides are in scope. Lambda/Layer repos document execution flow instead of REST endpoints.
- Do not write plan files, do not transition issue status. MCP first, REST fallback. Jira failure never blocks plan creation.
