---
name: planning-backend
description: Orient in a backend repo, surface mandatory design questions (credentials, signatures, IAM, async, error strategy), resolve design details, and return an ordered list of implementation units with files_touched and exposed contract details. Invoked by /create-plan Step 2d for each backend/full-stack repo — never directly.
---

# Skill: Planning — Backend

## 1. Purpose

Given a signed-off product plan and a repo name, orient in the repo, ask all mandatory design questions, resolve implementation specifics, and return an **ordered list of implementation units**. Each unit names the files it touches and any contract it exposes for a frontend to consume. The orchestrator assembly step (Step 2f) turns these units into tasks.

## 2. When Invoked

Invoked by `/create-plan` Step 2d, once per repo with `kind: backend` or `kind: full-stack`. Never invoked directly by the user or by the `planning` skill.

## 3. Inputs

- `repo_name` — the name the user provided in Step 2c (e.g. `everest_jarvis`)
- The signed-off product plan from `planning/SKILL.md` (overview, flows, data, NFRs, open questions)
- Jira issue key, if any

## 4. Workflow

### Step 1 — Orient in the Repo

**Resolve the repo ID and paths first.** Read `config/repositories.json` and find the entry whose `id` or `path` matches `repo_name`. The `id` field indexes the context directory; the `path` field gives the workspace location. Example: `id: "everest_jarvis"` → context at `repo-context/everest_jarvis/`, source at `workspace/everest_jarvis/`.

Read context files if available — skip gracefully if absent:
- `repo-context/<id>/context.md` — stack, directory map, entry points, key conventions
- `repo-context/<id>/structure.json` — file tree with roles (models, views, services, etc.)
- `repo-context/<id>/patterns.json` — representative file paths per pattern
- `repo-context/<id>/conventions.md` — request/response shape, validation, auth, pagination
- `repo-context/<id>/testing.md` — test framework, fixtures, how tests are run

If no context files exist, read the repo root at `workspace/<id>/` (a few targeted reads: root listing + key entry points such as `settings.py`, `manage.py`, `app.py`, `src/main.py`). Suggest running `/repo-context <id>` afterwards to generate context for future plans.

After reading, state what you found:
```
Repo: <name>  (id: <id>, path: workspace/<id>)
Framework: <e.g. Django 4.2 / FastAPI / Express>
Context files: <present | absent — suggest /repo-context <id>>
Similar feature: <nearest existing feature and where it lives>
Conventions: <auth pattern, response shape, validation approach — one line each>
```

Read 1–3 representative source files to ground your understanding before writing any questions or units — e.g. an existing model, view, and serializer for the app most similar to what this plan adds.

---

### Step 1b — Propose Build Scope

**Run this immediately after Step 1, before asking any questions.**

Read the product plan in full. Derive what this repo needs to build. Present a structured scope proposal — be specific, not vague. The user must be able to read this and say "you missed X" before any detailed questions are asked.

```
## What I propose to build in <repo-name>

**New models / tables:**
  - <ModelName> — one line on what it stores
  - <ModelName> — ...
  (write "none" if no new models)

**Modified models / tables:**
  - <ModelName>.<field> — what changes and why
  (write "none" if no modifications)

**New API endpoints / handlers / event classes:**
  - <METHOD /path or action name> — one line on what it does
  - ...
  (write "none" if no new endpoints)

**Modified endpoints / handlers:**
  - <what changes> — one line
  (write "none" if nothing modified)

**Async jobs / scheduled tasks / queue consumers:**
  - <name> — trigger, what it does
  (write "none" if no async work)

**External integrations:**
  - <service> — what operations are called
  (write "none" if no external calls)

**Management commands / one-time scripts:**
  - <name> — purpose
  (write "none" if none)

Does this cover everything, or is anything missing from this repo's scope?
```

**Wait for the user's answer before proceeding to Step 2.** If they flag missing items, add them to the proposal and re-present. If they confirm it's complete, proceed.

This proposal becomes the boundary for Step 2 questions — ask only about the items listed here. Do not ask about items the user did not confirm.

**Intra-phase checkpoint — run immediately after scope is confirmed:** Silently write both `partial.json` and `partial.md`:
- `partial.json`: read existing file, set `backend_units` to `[]` (empty array — signals "2d started, units not yet collected"), set `notes` to `"backend design in progress — scope confirmed for <repo>"`, update `saved_at`. Write atomically.
- `partial.md`: write with `| 4 · Backend Design | → In progress |` and all prior completed sections (brainstorming, product plan, repos) filled in. Backend Design section body: `"Scope proposal confirmed — design questions pending."`. Write atomically.
Do not print anything to the user.

---

### Step 2 — Surface Mandatory Design Questions

**This step is MANDATORY. Run it before drafting any implementation units.**

The product plan and brainstorming summary answer high-level "what" and "why" questions. This step answers repo-specific "how" questions that require the user's explicit confirmation. The product plan mentioning a topic is NOT the same as confirming the implementation decision.

**Scan the confirmed scope from Step 1b and identify all open questions across the following categories. Ask ALL applicable questions grouped by category in one or two messages.**

Do NOT skip a category because the product plan mentioned the topic at a high level. Do NOT assume an answer because it seems "obvious" from the plan. If a category does not apply at all (e.g. no external integrations in the feature), skip it.

---

**Category A — External Integrations: Auth & Credentials**
*(Ask if the feature calls any external API, SDK, cloud service, or third-party system)*

- What is the exact credential mechanism for `<service>`? (env var name, AWS Parameter Store path, IAM role chain, secrets manager key — provide the exact identifier, not just "env vars")
- Are all required IAM permissions / API scopes already provisioned in all target environments (dev/staging/prod), or is infra work needed? If already provisioned, confirm which role/policy grants them.
- Is this integration synchronous (blocks the request) or async (queued)? If async, what is the retry policy and DLQ strategy?
- What should happen when the external call fails? (retry, log-and-continue, surface to user, rollback prior step)

---

**Category B — Modifications to Existing Code**
*(Ask if any existing function, method, class, or Lambda handler is modified)*

- For each function/method being changed: what is the new exact signature? List added, renamed, and removed parameters with their types and defaults.
- Is this change backwards-compatible with all existing callers? If not, which callers need updating and are they in scope for this plan?
- For Lambda functions: are there other Lambda functions or consumers that call the same handler or share the same code path that would also need updating?

---

**Category C — Data Model, Migration, and Data Migration**
*(Always ask the data migration question. Ask schema questions if new tables, columns, indexes, or constraints are added.)*

- **Data migration (always ask):** Does this plan require any data migration — backfilling existing rows, transforming existing data, seeding lookup/reference tables, or importing records from an external system (e.g. AWS, CSV, another DB, legacy table)? If yes: (a) what is the exact strategy — management command, one-time script, or Django `RunPython` in the migration file? (b) can it run while the app is live (online) or does it require a maintenance window? (c) is it idempotent / safe to re-run if it fails halfway? (d) is it in scope for this plan or tracked separately as a follow-up?
- For any field where the type or constraint is non-obvious: confirm the exact choice. (e.g. IntegerField vs CharField for IDs, NULL vs blank default for optional fields, unique_together vs application-level dedup)
- Is the schema migration reversible? Are there any zero-downtime concerns (large table row-locks, column backfills)?
- If the repo connects to more than one DB: which DB does this model belong to?
- Are there any ORM-unsupported constructs needed (partitions, raw indexes, triggers) that must be added via raw SQL after the schema migration?

---

**Category D — Async, Queues, and Idempotency**
*(Ask if background jobs, SQS queues, scheduled tasks, or async processing are involved)*

- What is the exact idempotency key? Where and how is it enforced — DB unique constraint, cache key, event dedup field?
- What is the retry policy for transient failures (network, rate limit)? What happens after max retries — DLQ, dead letter alert, silent log?
- How do failures surface to operators — log-only, or visible somewhere in the UI?
- Is the task triggered once (on user action) or periodically (cron)? If periodic, what prevents overlapping runs?

---

**Category E — Multi-System CRUD Rollback**
*(Ask if the feature writes to more than one system — e.g. DB + external API + queue — in a single operation)*

- What is the rollback or compensation strategy if step N succeeds but step N+1 fails? Specify the exact inverse operation for each system.
- Are there cases where partial success is acceptable (write DB, fail external call, but don't roll back)?
- Which system is written first, and why? (First write defines the atomicity boundary.)

---

**Category F — Security and Input Validation**
*(Ask for any endpoint that accepts user-supplied data or operates on other users' resources)*

- Are there any ownership or tenancy checks required (e.g. "user can only view their own records")?
- Which fields are sanitized or validated at the serializer vs. DB level vs. both?
- Is any user-supplied field passed to an external API or shell command that could be an injection vector?

---

**Wait for user answers before proceeding to Steps 3–8.**

**Intra-phase checkpoint — run immediately after receiving answers to the design question cluster:** Silently write both `partial.json` and `partial.md`:
- `partial.json`: read existing file, update `notes` to `"backend design in progress — design questions answered for <repo>"`. All other fields unchanged. Write atomically.
- `partial.md`: same structure as the scope checkpoint above — `| 4 · Backend Design | → In progress |`. Backend Design section body: `"Scope confirmed, design questions answered — implementation units pending."`. Write atomically.
Do not print anything to the user.

Group your questions into at most two messages (e.g. Category A+B in one, C+D+E+F in the next if there are many). Do not ask more than 8 questions total — if you have more, prioritize those whose answer most changes the implementation.

---

### Step 3 — Resolve Endpoints / Handlers / Tasks

Based on user answers and the product plan's flows, determine:
- Which new API endpoints or handlers are needed (method, path, purpose)
- Which existing endpoints are modified and how
- The complete request and response shape for each endpoint:
  - All request fields: name, type, required/optional, validation rule
  - All response fields: name, type, whether always present or conditional
  - All error codes and their response bodies
- Input validation rules and where enforced (serializer, middleware, model)

For each endpoint, write it out in full. Do not summarize — the implementation unit description must include the complete contract.

### Step 4 — Resolve Data Model Changes

Determine for each model:
- Complete field list: name, field type, null/blank, default, max_length/choices where applicable
- Indexes, unique constraints, and `db_table` Meta
- Whether a migration is needed and whether it is reversible
- Any raw SQL constructs needed post-migration (partitions, full-text indexes)
- Base class choice (if Django: which BaseModel variant — do not add fields already on the base)

If the product plan's data section already answered this fully and you confirmed specifics in Step 2, move on without re-asking.

### Step 5 — Resolve Async Work

If the product plan implies async processing (background jobs, queues, scheduled tasks):
- Which task queue handles it (Celery, SQS, APScheduler, etc.)
- What triggers the task, what it does, what it returns or writes
- Retry policy: max retries, backoff, DLQ handling
- How failures surface (DLQ, error logging, alert, UI error state)
- Idempotency: exactly how duplicate processing is prevented

If no async work is implied by the plan, skip this step.

### Step 6 — Resolve External Integrations

If the product plan touches external systems (confirmed via Step 2 Category A answers):
- Which SDK or client library is used and how it is instantiated (singleton, per-request, etc.)
- Which operations are called (create, read, update, list, delete)
- Error handling: retry count, backoff, fallback if service is down
- Whether the integration is synchronous or async

If none, skip.

### Step 7 — Resolve Error Handling and Logging

State the expected error handling approach, aligned with `conventions.md` and Step 2 Category E answers:
- Which errors are user-visible (with a message in the response) vs. internal-only (logged and 500)
- Log level and which fields are logged on error (user id, request id, endpoint, error message)
- Any metrics or alerts that should fire on failure

If `conventions.md` documents a standard approach that fully applies, confirm it applies — do not repeat it verbatim.

### Step 8 — Output Implementation Units

Produce an ordered list of self-contained implementation units. Order by natural dependency (things that must exist before others come first).

Format each unit as:

```
Unit BE-01: <short title>
  What: <specific description — what code is written, which pattern it follows, what the contract is>
  Files: <repo-relative paths — be specific, never leave this empty>
  Depends on: <unit IDs within this repo, or "—" if none>
  Exposes contract: <yes — method, path, key request fields, key response fields | "—" if no FE consumes this>
  Notes: <convention to carry into the task description — e.g. "follows OrderSerializer pattern at apps/orders/serializers.py:42">
```

Unit types to recognize:
- Schema migration — standalone; can often run before the endpoint code exists
- Data migration — separate unit when existing rows must be backfilled, transformed, or imported; always separate from the schema migration unit. Include: strategy (management command / RunPython / one-time script), idempotency guarantee, online vs offline, and whether it is in scope for this plan or a follow-up
- Endpoint / handler — one per logical operation (create, update, delete, list are usually separate)
- Async task — separate from the endpoint that enqueues it
- Integration module — wrapper around an external service
- Management command — DB seeding, data import, one-time operations
- Shared helper / middleware — extracted only if used by more than one unit

**If the user confirmed a data migration is in scope (Category C answer), it must appear as its own unit** — never merged into the schema migration unit or the endpoint unit. If out of scope, record it as a delivery note in the plan.

**Flag exposed contracts explicitly.** If a frontend repo is in scope and will consume a contract this unit defines, set `Exposes contract: yes` and provide the complete shape: method, path, all key request fields and their types, all key response fields. The frontend skill (step 2e) reads these to check alignment. Do not write FE unit IDs here — those don't exist until step 2e runs.

## 5. Files Read

- `config/repositories.json` — to resolve repo `id`, `path`, and `base_branch`
- `repo-context/<id>/context.md` (if present)
- `repo-context/<id>/structure.json` (if present)
- `repo-context/<id>/patterns.json` (if present)
- `repo-context/<id>/conventions.md` (if present)
- `repo-context/<id>/testing.md` (if present)
- 1–3 representative source files from `workspace/<id>/` for grounding (existing model, view, serializer similar to the feature)

## 6. Files Written

- `$AI_ORCH_PLAN_DIR/log.md` — updated after every user answer during Steps 2–7 (see Log Maintenance below).
- `$AI_ORCH_PLAN_DIR/partial.json` — written once, silently, after Step 8 units are collected and shown to the user (no separate approval gate is required — returning the units to `/create-plan` is the handoff signal).

## 6a. Log Maintenance

**Before sending the design question cluster in Step 2** — list every question being asked in **Still to answer**, write `log.md` atomically, then send the questions. Format each entry as:
```
- **<Category label>**: <the question, in one plain sentence>
```
Write `log.md` before waiting for the user's response so the log always records what is pending.

**After every user answer during Steps 2–7** (design questions, data model confirmations, integration decisions), update `log.md` atomically (`log.md.tmp` → `mv log.md.tmp log.md`):

1. Append a new Q&A block at the bottom of the **Conversation so far** section:
   ```
   **Q<N> · <short label — e.g. "Credentials for EventBridge">**
   You were asked: <the question, one plain sentence>
   You said: <the user's answer — 1–3 sentences capturing the substance, not just "env var">
   ```
   Only log real decisions. Do not log orientation output (repo summary, what was read).

2. Rewrite the **Where we are** section:
   - Under **How we'll approach it**: expand with specific backend decisions confirmed so far (e.g. "Celery task, idempotency via unique constraint on (case, programme)", "EventBridge SDK wrapper, boto3 singleton client").
   - Under **Key constraints**: add any backend-specific constraints confirmed in this step.
   - Under **Open risks**: add any risks surfaced in the design questions.
   - Under **Still to answer**: remove answered questions; add any new ones raised by the user's answers.

**After Step 8**, silently write both `partial.json` and `partial.md`:
- Read the existing `partial.json`, update `resumed_phase` to `5`, set `backend_units` to the list of units, update `saved_at` and `notes: "auto-saved after backend design"`. Write all other fields unchanged.
- Then write `partial.md`:

```bash
PLAN_DIR="${AI_ORCH_PLAN_DIR:-plans/<slug>}"

cat > "$PLAN_DIR/partial.md.tmp" <<'MD'
# <title> — Draft Plan

**Plan ID:** <slug>
**Jira:** <key or "none">
**Saved:** <ISO 8601>

## Progress

| Phase | Status |
|-------|--------|
| 1 · Brainstorming   | ✓ Done |
| 2 · Product Plan    | ✓ Done |
| 3 · Repo Intake     | ✓ Done |
| 4 · Backend Design  | ✓ Done |
| 5 · Frontend Design | – Pending |
| 6 · Assembly        | – Pending |

---

## What we're building

<problem — prose>

### Who this is for

<users paragraph>

### What success looks like

1. <criterion>

### Scope

<scope paragraph>

### How we'll build it

<direction paragraph>

### Risks to watch

1. <risk and impact>

---

## Product plan

<full approved product plan prose>

---

## Repos involved

<bullet per repo: name, kind, one sentence on what changes there>

---

## Backend design

<For each unit: heading + 2–3 sentences on what it does, files it touches, contract it exposes.>

### BE-01 · <unit title>

<description, files, contract>

### BE-02 · <unit title>

<description, files, contract>

---

> ⚠ Draft — `plan.json` not yet written. Resume: `/create-plan <plan_id>`
MD
mv "$PLAN_DIR/partial.md.tmp" "$PLAN_DIR/partial.md"
```
Do not print anything to the user when writing these files.

## 7. State Changes

`partial.json` updated with backend units after Step 8.

## 8. Failure Handling

- If `conventions.md` is missing: note this in the units' Notes field so the developer knows to check conventions manually. Do not guess.
- If a design question cannot be answered from the product plan or repo context: ask. **Do not assume.** Assumptions that prove wrong after implementation are expensive.
- If the repo has no context files at all: orient by reading `workspace/<id>/` directly (root listing + key entry points). Say what you found, suggest `/repo-context <id>`, and continue.
- If the user answers "already covered in brainstorming" to a mandatory question: acknowledge, confirm you now have the specific implementation detail, and proceed. Do not accept "it's in the plan" as a full answer to a question about exact credential names, exact function signatures, or exact IAM policy scope.

## 9. Output

An ordered list of backend implementation units (BE-01, BE-02, …), each with: title, specific description of what code it writes, files touched, intra-repo dependencies, complete exposed contract description (when a frontend consumes it), and conventions. Returned to `/create-plan` for Step 2f assembly.

## 10. Rules and Constraints

- **Step 2 is mandatory** — never skip it, never shortcut it with assumptions. The product plan answers "what" and "why"; this step answers "exactly how" at the code level.
- Never ask a question whose exact answer can be read directly from the product plan AND confirmed in the repo code. But a product plan mention of a topic is NOT confirmation of the implementation decision — always ask for the exact credential name, exact function signature, exact IAM policy, etc.
- Never invoked directly — always through `/create-plan` Step 2d.
- Do not write any plan files or feature code.
- Group questions into 1–2 messages; ask at most 8 questions total, prioritizing those whose answer most changes the implementation.
- `files_touched` must never be empty — the orchestrator uses it to gate concurrent dispatch. If uncertain, use the most specific glob available (`apps/<app>/**`).
- Exposed contract descriptions must include ALL key fields, not just an example — the FE skill and Jira story both depend on these.
