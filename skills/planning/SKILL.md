---
name: planning
description: Turn an approved brainstorming summary into a full product plan — solution overview, user-facing flows, data schema tables, execution lifecycle (state machines + flow steps for async plans), system architecture diagram (for multi-service plans), NFR table, and assumptions. Requires explicit sign-off before the command continues to repo intake. Does not ask repo-specific questions and does not write any files.
---

# Skill: Planning

## 1. Purpose

Turn the five context fields from `brainstorming` into a full **prose product plan**: solution overview, user-facing flows, data involved, non-functional requirements, and open questions or assumptions. Present it and gate on explicit sign-off before the command advances to repo intake.

This skill produces words, not tasks. It pins down *what* is being built and *why*. Repo-specific design (endpoints, components, migrations) happens later in `planning-backend` and `planning-frontend`. Assembly into tasks and file writing happens in `/create-plan` Step 2f.

**CRITICAL — no new questions:** The entire product plan (Steps 1–5, including Execution Lifecycle and System Architecture) is written by the agent from the approved brainstorming summary. Do NOT ask the user additional questions to fill any section — the brainstorming summary already contains the problem, scope, constraints, direction, and architecture signals needed. Write the full plan, present it once, gate on one approval. Extra questions here defeat the purpose of the brainstorming step.

## 2. When Invoked

Invoked by `/create-plan` Step 2b, after the brainstorming summary is approved. Never invoked directly by the user.

## 3. Inputs

- Approved brainstorming summary: problem, user, success criteria, scope, constraints, direction, open risks.
- Jira issue key (if `--jira` was given) — carry it forward as reference.

## 4. Workflow

### Step 1 — Solution Overview

Write 2–4 sentences: what is being built, which problem it solves, and how this approach addresses it. Derive from the `Direction` in the brainstorming summary. Do not invent scope — if the brainstorming summary left something ambiguous, flag it as an assumption in Step 5.

**Direction drift:** If your product plan's implementation deviates from the approved brainstorming Direction in any material way (different library, different trigger mechanism, different architectural pattern), state the deviation explicitly and give a one-line reason in the Overview. Example: "Brainstorming proposed DOCX+LibreOffice for PDF generation; this plan uses xhtml2pdf+HTML templates because LibreOffice is unavailable in the Lambda runtime." Never silently adopt a different approach — the brainstorming Direction is what the user approved.

### Step 2 — User-Facing Flows

Describe what the user experiences, not how the system implements it.

**Single-trigger features** (one primary flow, e.g. a scheduled Lambda, a batch job): document one **Happy path** from trigger to successful outcome, then **Key edge cases** — the 2–4 most important failure or exceptional paths. Skip edge cases obvious from context.

**Multi-operation features** (multiple distinct user actions, e.g. Create / Edit / Delete / Pause / Trigger / Sync): document each operation as its own **named flow**, not a single happy path. Each named flow shows:
1. What triggers it (user action, schedule, event)
2. The success path (numbered steps, trigger → outcome)
3. The inline failure path — **if the failure produces a different data state or UX than success** (e.g. "DB write succeeded but external API failed → set `sync_error`, show Retry button"). Do not repeat obvious failures ("returns 400 on bad input") — only states that an engineer needs to explicitly handle.

After the named flows, add a **Key edge cases** section for cross-cutting scenarios that apply to multiple flows (concurrency, dedup, partial failure).

Write in plain language. A numbered list or short prose paragraphs both work — match the complexity of the feature.

### Step 3 — Data Involved

Name the data this plan touches: entities/models created or modified, key fields, relationships, and any persistence requirements (e.g. "uploaded files go to S3; metadata record in DB"). If the plan is UI-only, name the API data shapes instead.

**Format:** When field-level detail is known from brainstorming, write each entity as a markdown table with columns `Column | Type | Notes`. Use plain-English types (varchar, int, JSON, FK → OtherModel, ENUM(a,b,c), datetime). One table per entity. Add a short prose note below each table for non-obvious invariants (e.g. denormalization rationale, partition strategy, dedup logic). If field detail is genuinely unknown, prose is acceptable — but prefer tables when you have the information.

Do not specify migration SQL or schema DDL — that is repo-specific and belongs in `planning-backend`.

### Step 3a — Execution Lifecycle (conditional)

**Write this section when the plan involves async or event-driven execution** — scheduled jobs, queue consumers, webhook handlers, background workers, state machines. Skip it for purely synchronous CRUD features.

**This section is agent-generated from the brainstorming summary and scope. Do not ask the user any questions to fill it — derive everything from what was already captured in brainstorming.** If a detail is genuinely unknown, state it as an assumption.

Cover:
- **State machines** — draw the states and transitions for each stateful entity (e.g. Schedule: active → running → active; Job: pending → running → success/failure). Use a compact arrow format:
  ```
  active ──► running ──► active   (job completes)
  active ──► paused              (operator pauses)
  ```
- **Execution flow** — step-by-step what happens at each lifecycle event. Use labelled blocks (ON START, ON SUCCESS, ON FAILURE, ON TIMEOUT). Number the steps within each block. Be precise about which DB writes happen and in what order.
- **Write ordering** — for plans that span a DB and an external API (EventBridge, S3, SQS, Jira, WhatsApp queue), state explicitly per operation type which is written first and what happens when either side fails:
- *DB-first*: DB record written → external API called. If external API fails: set `sync_error` / error field on the DB record; do not roll back the DB write. Operator retries via a sync endpoint.
- *API-first*: external API called → DB written on success. If external API fails: return error, DB unchanged. If API succeeds but DB fails: call inverse API op to undo.
If different operations within the same plan use different strategies (e.g. create is DB-first, edit is API-first), document each strategy separately.

**Key invariants** — dedup logic, retry behaviour, partial-send rules, anything that must be true across all execution paths.

This section feeds directly into task descriptions in `planning-backend` — make it specific enough that an engineer can implement the state transitions without re-reading the entire product plan.

### Step 3b — System Architecture (conditional)

**Write this section when the plan touches more than one service or infrastructure boundary** — multiple repos, Lambda + DB, queue-based fanout, third-party integrations. Skip it for single-service plans.

**This section is agent-generated from the repos list and scope. Do not ask the user any questions — draw what you know from the brainstorming summary.**

Produce an ASCII box diagram showing:
- Each service / component as a labelled box
- Data flow arrows between boxes, labelled with the mechanism (REST API, SQS, boto3, direct DB write, etc.)
- The user or trigger at the top, persistence at the bottom

Keep it compact — one screen. Use box-drawing characters (`┌─┐`, `└─┘`, `│`, `▼`, `▲`, `──►`) for readability.

### Step 4 — Non-Functional Requirements

Always write this section as a markdown table, even if only one or two rows apply. Do not write prose for NFRs.

| Area | Requirement |
|------|-------------|
| Scale | Volume, throughput, latency targets if stated; pagination strategy; index/partition plan |
| Auth | Who can perform this action; any role or scope checks |
| Idempotency | Whether the operation must be safe to retry; dedup mechanism |
| Observability | Logging, metrics, alerting expectations |
| Backwards compatibility | Whether the change must be invisible to existing clients; rollout notes |

Omit rows that genuinely do not apply. Do not invent requirements to fill the table. If none apply, write a single-row table: `| None | No special NFRs for this scope. |`.

### Step 5 — Open Questions and Assumptions

List anything that could affect the design but was not answered during brainstorming. Use this format:

```
Assumption: <X is true — note if wrong this would change Y>
Open question: <unresolved — needs an answer before or during backend/frontend design>
```

If the brainstorming summary listed open risks, fold them in here.

### Step 6 — Present and Gate

**Before presenting to the user**, do these three things in order, all silently:
1. Update `log.md` **Still to answer** to add the approval question: `- **Product plan approval**: Does this product plan look right? (yes / revise <section>)` — then write `log.md`.
2. Write `partial.json` with the generated plan content.
3. Write `partial.md`.

This ensures the content is saved and the pending question is recorded even if the terminal dies before the user approves.

Present the product plan:

```
## Product Plan

### Overview
<Step 1 output>

### User-Facing Flows
<Step 2 output>

### Data
<Step 3 output — entity tables>

### Execution Lifecycle
<Step 3a output — state machines + flow steps; omit section entirely if not async/event-driven>

### System Architecture
<Step 3b output — ASCII diagram; omit section entirely if single-service>

### Non-Functional Requirements
<Step 4 output — markdown table>

### Assumptions
<Step 5 output>

---
Does this product plan look right? (yes / revise <section>)
```

**Do not hand off to the next step until the user confirms.** If they ask to revise a section, update it, rewrite the files again with the revised plan, and re-present the full plan — never re-present only the changed section, as changes in one section often affect others.

### Step 7 — Hand Off

Once signed off, update `partial.json` to set `resumed_phase: 3` and `notes: "product plan approved"` — everything else stays as written in Step 6. Pass the full prose product plan back to `/create-plan`. The command advances to Step 2c (repo intake). Do not ask repo questions here.

## 5. Files Read

None.

## 6. Files Written

- `$AI_ORCH_PLAN_DIR/log.md` — updated after any user input during Steps 1–6 (see Log Maintenance below).
- `$AI_ORCH_PLAN_DIR/partial.json` — written once, silently, immediately after the user signs off in Step 6.

## 6a. Log Maintenance

The product plan is largely generated by the agent rather than through Q&A, but revisions and sign-off are user actions that should be logged.

**When the user provides revision feedback (Step 6 revise loop)**: append one Q&A block to the **Conversation so far** section of `log.md`:
```
**Q<N> · Product plan revision**
You were asked: Does this product plan look right?
You said: <their feedback — paraphrase faithfully>
```

**After sign-off (Step 6 confirmed)**: rewrite the **Where we are** section to add:
- Under **What we agreed to build**: add one sentence summarising what the product plan confirmed (the primary solution approach and key flows).
- Under **How we'll approach it**: note any specific architectural direction confirmed in the product plan (e.g. "async batch engine, no new frontend").

Write "All questions answered ✓" in **Still to answer** if no brainstorming questions remain open.

**After Step 6 sign-off**, silently write both files. Read the existing `partial.json` first, update `resumed_phase` to `3`, `product_plan` to the full approved prose, `saved_at`, and `notes: "auto-saved after product plan sign-off"`. Then write `partial.md`:

```bash
PLAN_DIR="${AI_ORCH_PLAN_DIR:-plans/<slug>}"

# partial.json — update resumed_phase and product_plan, keep rest intact
# (read existing file, update fields, write atomically)

# partial.md
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
| 3 · Repo Intake     | – Pending |
| 4 · Backend Design  | – Pending |
| 5 · Frontend Design | – Pending |
| 6 · Assembly        | – Pending |

---

## What we're building

<problem statement — 2–4 sentences, plain prose>

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

<Full approved product plan prose: overview, user-facing flows, data involved, NFRs, open questions and assumptions.>

---

> ⚠ Draft — `plan.json` not yet written. Resume: `/create-plan <plan_id>`
MD
mv "$PLAN_DIR/partial.md.tmp" "$PLAN_DIR/partial.md"
```
Do not print anything to the user when writing these files.

## 7. State Changes

`partial.json` updated with product plan after Step 6 sign-off.

## 8. Failure Handling

- If the brainstorming summary is too vague to write a coherent overview: ask one focused clarifying question before writing anything. Do not write a vague plan hoping review will catch it.
- If the user's sign-off reveals a scope change that contradicts the brainstorming summary: flag the contradiction explicitly before revising. The brainstorming summary is the source of truth; a revision here may mean the brainstorming step should have been run again.

## 9. Output

A signed-off prose product plan (overview, flows, data, NFRs, open questions), returned to `/create-plan` for Step 2c.

## 10. Rules and Constraints

- Produce the full structured product plan — prose, markdown tables, ASCII diagrams, and NFR tables are all expected. Do NOT reduce sections to bullet summaries.
- Do not produce task lists or feature code.
- Schema definitions are NOT allowed (no SQL DDL, no Django field definitions) — those belong in `planning-backend`. Data section uses conceptual markdown tables (column name + plain-English type + note) only.
- Do not ask repo-specific questions (exact endpoints, component file paths, migrations) — those belong in `planning-backend` / `planning-frontend`.
- Do not write any plan files.
- Never invoked before the brainstorming summary is explicitly approved.
- Gate on explicit confirmation — silence or subject change is not approval.
- Never skip Execution Lifecycle for async/event-driven plans. Never skip System Architecture for multi-service plans. These are not optional extras — they are required sections that feed `planning-backend` task descriptions.
