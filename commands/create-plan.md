---
description: Convert a requirement into a structured, orchestrator-ready plan file. Planning only — writes no feature code and never executes.
argument-hint: "<requirement text> [--jira <ISSUE-KEY>]"
---

# Command: create-plan

Interactive planning session that ends in a structured plan under `plans/<slug>/`. Produces three files: `plan.json` (machine-readable task DAG the orchestrator parses), `plan.md` (human-readable summary), and `state.json` (initial execution state). At plan approval, also creates a Jira Story (or updates an existing ticket if `--jira` is given). Does not execute — a separate orchestrator reads the plan later.

**Arguments:** $ARGUMENTS

## Usage

```
/create-plan <requirement text>
/create-plan <requirement text> --jira <ISSUE-KEY>
```

- `<requirement text>` — free-text description of what needs to be built or changed (required)
- `--jira <ISSUE-KEY>` — optional; pass an existing Jira ticket key. Brainstorming pre-fills from it (skips questions it already answers). At assembly, the ticket is updated with the plan summary instead of a new Story being created.

## What to expect — step by step

`/create-plan` is a guided conversation. It never jumps ahead. At each step the agent either asks you questions or generates content for your approval. Here is exactly what happens and what you need to bring:

| Step | Agent does | You provide |
|------|-----------|-------------|
| **2a · Brainstorming** | Asks one question at a time to pin down the problem | Answers: what is broken, who is affected, what success looks like, what is in/out of scope, which existing queues/tables/APIs this touches, any configs or templates ops must supply before go-live |
| **2b · Product Plan** | Generates the full prose plan — overview, flows, data schema tables, execution lifecycle, system architecture, NFR table, assumptions | Just **approve or ask for a revision** — no new information required |
| **2c · Repo Intake** | Asks which repos are involved | Repo names (matching `config/repositories.json`), their kind (backend / frontend / full-stack), base branch |
| **2d · Backend Design** | Reads the repo code, proposes what it will build (models, endpoints, jobs), then asks design questions | Confirm the scope proposal, fill gaps the agent cannot read from code (DB name, existing table conventions, payload format, external service contracts) |
| **2e · Frontend Design** | Reads the repo code, proposes screens/components/API calls, then asks design questions | Confirm the scope proposal, fill gaps (existing page patterns, permission keys, sidebar placement, UX conventions) |
| **2f · Assembly** | Converts all units into a task DAG, adds per-repo test + review gates, encodes dependencies, creates the Jira story | Just **approve the DAG or request changes** — no new information required |

**Heaviest input:** 2a (brainstorming) and 2d/2e (design questions) — this is where your domain knowledge goes in.
**Lightest input:** 2b (product plan) and 2f (assembly) — mostly just say yes.

At the end of every step the agent silently checkpoints progress. If the session crashes or you need to pause, run `/create-plan <plan_id>` to resume from where you left off.

---

## Flow at a glance

```
You type:  /create-plan "requirement text" [--jira KEY]
                │
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2a · BRAINSTORMING                                                   │
│  Agent asks: problem · user · success criteria · scope               │
│              existing systems · operational dependencies              │
│  You answer one question at a time                                   │
│  ── GATE: approve summary ────────────────────────────────────────── │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼  (approved)
┌──────────────────────────────────────────────────────────────────────┐
│  2b · PRODUCT PLAN  [agent-generated, no questions]                   │
│  Agent writes: overview · user flows · data schema tables            │
│                execution lifecycle · system architecture              │
│                NFR table · assumptions                                │
│  ── GATE: approve or ask for revisions ───────────────────────────── │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼  (signed off)
┌──────────────────────────────────────────────────────────────────────┐
│  2c · REPO INTAKE                                                     │
│  You provide: repo names · kind · base branch                        │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2d · BACKEND DESIGN  (one pass per backend repo)                    │
│  Agent reads code → proposes scope → asks design questions           │
│  You confirm scope, answer gaps                                      │
│  Output: implementation units (BE-01, BE-02 …)                      │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼  (must finish before 2e)
┌──────────────────────────────────────────────────────────────────────┐
│  2e · FRONTEND DESIGN  (one pass per frontend repo)                  │
│  Agent reads code → proposes scope → asks design questions           │
│  You confirm scope, answer gaps                                      │
│  Output: implementation units (FE-01, FE-02 …)                      │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2f · ASSEMBLY  [agent-generated, no questions]                       │
│  Agent builds task DAG · adds test + review gates per repo           │
│  ── GATE: approve DAG ────────────────────────────────────────────── │
│  Writes: plan.json · plan.md · state.json                            │
│  Agent creates Jira story (or updates existing ticket)               │
└──────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
          Run /execute-plan <plan_id> to begin execution
```

---

## Plan Schema

Every plan writes three files. `plan.json` is the contract the orchestrator reads. `plan.md` is for humans. `state.json` seeds the execution engine's initial state.

**`plans/<slug>/plan.json`**

```json
{
  "id": "<YYYYMMDD-slugified-title>",
  "title": "<title>",
  "created": "<ISO 8601>",
  "context": {
    "problem": "one or two sentences — what is broken or missing, and why it matters now",
    "user": "who is affected and how",
    "success_criteria": ["measurable outcome 1", "measurable outcome 2"],
    "scope": "what is explicitly in scope for this plan",
    "constraints": ["must not break X", "must reuse Y", "no OAuth in this phase"]
  },
  "repos": [
    {
      "name": "<repo-name>",
      "path_or_url": "workspace/<repo-name>",
      "kind": "backend | frontend | full-stack",
      "base_branch": "<base_branch from repositories.json>"
    }
  ],
  "tasks": [
    {
      "id": "task-001",
      "title": "<short imperative title>",
      "repo": "<repo-name>",
      "type": "architecture | development | test | review | debug",
      "description": "<specific instructions; embed acceptance criteria here>",
      "depends_on": [],
      "parallelizable": true,
      "files_touched": ["apps/auth/views.py", "apps/auth/serializers.py"]
    }
  ],
  "delivery": {
    "jira_tickets": []
  }
}
```

Key invariants:
- `depends_on: []` — task can start immediately; no upstream dependency.
- `parallelizable: true` only when the task shares no files and has no unmet `depends_on` with any concurrently running task.
- Tasks form a DAG — the orchestrator reads `depends_on` to schedule work.
- Every field must be present, even if empty (`[]`, `null`, `""`). The orchestrator does not handle missing fields.
- `delivery.jira_tickets` starts as `[]` when `plan.json` is first written (Step 7). The `create-jira-story` skill (2f Step 8) runs after plan files are written and updates `delivery.jira_tickets` in-place with the real key. Jira is optional — if not configured, it stays `[]`.

**`plans/<slug>/plan.md`** — format defined in Step 2f below.

---

## Environment integration (when invoked by the UI)

If the orchestrator UI launched this run, two env vars are pre-populated:

- `AI_ORCH_PLAN_SLUG` — the plan slug the server reserved. **Use this verbatim in Step 2f Step 6** — do not re-derive it. The server already checked for collisions and created `plans/$AI_ORCH_PLAN_SLUG/` on disk with a seed `status.json`.
- `AI_ORCH_PLAN_DIR` — absolute path to that same folder. **In Step 2f Step 8, write `plan.json`, `plan.md`, `state.json` into this existing directory** — do not `mkdir` a new folder.

You do not need to write any status/heartbeat file. The UI infers progress by watching the filesystem (existence of `plan.json` marks completion). If both env vars are unset, this is a bare CLI run — derive slug and create the folder as originally specified.

---

## Step 0 — Mode detection: resume vs. fresh

**Before running Step 2a**, inspect `$ARGUMENTS`. If it looks like a plan_id (matches `^[0-9]{8}-[a-z0-9-]+$`) AND `plans/$ARGUMENTS/partial.json` exists, this is a **resume** — not a fresh plan.

**Resume flow:**

1. Read `plans/$ARGUMENTS/partial.json` — it holds the saved conversation state:
   ```json
   {
     "plan_id": "<slug>",
     "title": "<user-facing title>",
     "resumed_phase": <1..6>,       // the next phase to run
     "saved_at": "<ISO 8601>",
     "jira_key": "<key or null>",
     "brainstorming_summary": <fields from 2a — problem, user, success_criteria, scope, constraints> | null,
     "product_plan": "<full prose from 2b>" | null,
     "repos": [ ... 2c output ... ] | null,
     "backend_units": [ ... 2d output ... ] | null,
     "frontend_units": [ ... 2e output ... ] | null,
     "notes": "<optional free-text from user at save time>"
   }
   ```

2. Restore local state from those fields. Skip phases whose output is already saved — jump to `resumed_phase`. Print a resume banner:
   ```
   Resuming plan <plan_id>
   Title: <title>
   Saved: <saved_at>  ·  Notes: <notes or "(none)">
   Progress restored:
     2a Brainstorming     : <✓ saved | – not yet>
     2b Product Plan      : <✓ saved | – not yet>
     2c Repo Intake       : <✓ saved | – not yet>
     2d Backend Design    : <✓ saved | → in progress (restarting) | – not yet>
     2e Frontend Design   : <✓ saved | → in progress (restarting) | – not yet>
   Continuing at Phase <resumed_phase> — <label>. Say "save plan" any time to pause again.
   ```

   **In-progress detection — check `backend_units` and `frontend_units` values carefully:**
   - `null` → phase not started yet. Run fresh from Step 1.
   - `[]` (empty array) → phase was started (scope proposal was confirmed) but the session ended before units were produced. Show `→ in progress (restarting)` in the banner and immediately print:
     ```
     ⚠ [Backend | Frontend] design was in progress when the session ended.
       Scope was confirmed but implementation units were not collected.
       Notes at interruption: <notes field>
       Restarting from the scope proposal — design questions will need to be answered again.
     ```
     Then re-run the relevant sub-skill starting from Step 1b (scope proposal) — skip Step 1 repo orientation re-read, but re-derive and re-present the scope proposal immediately so the user can confirm or adjust before answering design questions again.
   - `[...]` (non-empty array) → phase complete. Show `✓ saved`. Present the saved units and ask "continue with these, or revise?" before advancing.

3. Continue from `resumed_phase`. For any restored field with saved content (non-null, non-empty), do NOT re-run its sub-skill — just show the user the saved content and ask "continue with this, or revise?" before advancing.

If `$ARGUMENTS` does not look like a plan_id, this is a fresh plan — run Step 2a as normal.

---

## Save-partial trigger (available throughout 2a–2f)

At any point after Step 0, if the user's message expresses intent to pause and continue later — examples: "save plan", "save partial", "pause here", "let's continue tomorrow", "save and exit", "hold this" — **stop the current step and save**:

1. Determine the plan folder:
   - If `$AI_ORCH_PLAN_DIR` is set, use it (this is a UI-driven run).
   - Else, if the slug has already been derived in Step 2f Step 6, use `plans/<slug>/`.
   - Else, derive the slug from `$ARGUMENTS` right now (same rule as Step 2f Step 6) and `mkdir -p plans/<slug>/`.

2. Build `partial.json` with everything captured so far (any field not yet reached stays `null`). Include a `resumed_phase` = the current phase number (the one you were about to run when the user asked to save). Optionally ask the user for a one-line note explaining why they're pausing, and store it in `notes`.

3. Write both files atomically:
   ```bash
   PLAN_DIR="${AI_ORCH_PLAN_DIR:-plans/<slug>}"
   cat > "$PLAN_DIR/partial.json.tmp" <<'JSON'
   { ... the object above ... }
   JSON
   mv "$PLAN_DIR/partial.json.tmp" "$PLAN_DIR/partial.json"

   cat > "$PLAN_DIR/partial.md.tmp" <<'MD'
   # <title> — Draft Plan
   ... (per partial.md format in the Auto-save section) ...
   MD
   mv "$PLAN_DIR/partial.md.tmp" "$PLAN_DIR/partial.md"
   ```

4. Tell the user, then stop:
   ```
   ✓ Partial plan saved.
     ID     : <plan_id>
     Folder : plans/<plan_id>/
     Saved  : <phases with content>
     Next   : Phase <resumed_phase> — <label>

   To resume:
     • CLI:  /create-plan <plan_id>
     • UI :  click "Resume Plan" on the Plans page.
   ```

Do **not** write `plan.json`, `plan.md`, or `state.json` on a save-partial — those only appear at Step 2f Step 8 when the full DAG has been approved. A partial plan is distinguished by having `partial.json` but no `plan.json` in the folder.

---

## Auto-save at phase gates

**In addition to the user-triggered save above**, automatically write `partial.json` immediately after the user approves or signs off each phase gate — without asking, without pausing, without printing a save banner. This is a silent background checkpoint. It runs synchronously before moving to the next phase.

| Trigger | `resumed_phase` to write | Fields populated |
|---------|--------------------------|-----------------|
| User approves brainstorming summary (end of 2a) | `2` | `brainstorming_summary` |
| User signs off product plan (end of 2b) | `3` | + `product_plan` |
| User confirms repo list (end of 2c) | `4` | + `repos` |
| Backend design complete, all units collected (end of 2d) | `5` | + `backend_units` |
| Frontend design complete, all units collected (end of 2e) | `6` | + `frontend_units` |

**Rules:**
- Use the same atomic write as the manual save: `partial.json.tmp` → `mv partial.json.tmp partial.json`.
- Always include all fields captured so far; fields not yet reached stay `null`.
- Set `notes: "auto-saved at phase <N>"` so it is distinguishable from a manual save.
- Do not print anything to the user — just write the file and immediately continue to the next phase.
- If `$AI_ORCH_PLAN_DIR` is set, write there. Otherwise use `plans/<slug>/` (slug is always known by the time 2a completes because the folder was created for `log.md`).
- **Always write `partial.md` alongside `partial.json`** — see format below.

### `partial.md` format

Write this file atomically (`partial.md.tmp` → `mv partial.md.tmp partial.md`) every time `partial.json` is written — at every auto-save gate and every manual save. It is the human-readable draft plan shown in the UI. **Only write sections whose phase is complete** — never show pending or half-answered sections. Each section must be fully written from the approved output of that phase, not from an in-progress state.

```markdown
# <title> — Draft Plan

**Plan ID:** <slug>
**Jira:** <key or "none">
**Saved:** <ISO 8601>

## Progress

| Phase | Status |
|-------|--------|
| 1 · Brainstorming | ✓ Done / → In progress / – Pending |
| 2 · Product Plan  | ✓ Done / → In progress / – Pending |
| 3 · Repo Intake   | ✓ Done / → In progress / – Pending |
| 4 · Backend Design | ✓ Done / → In progress / – Pending |
| 5 · Frontend Design | ✓ Done / → In progress / – Pending |
| 6 · Assembly | – Pending |

---

## What we're building

<!-- Include this section only if brainstorming is complete (resumed_phase >= 2) -->

<Write 2–4 sentences describing the problem in plain language — what is broken or missing today, who is affected, and why it matters now. Do not use bullet points here. Write it as you would explain it to a new team member.>

### Who this is for

<One paragraph describing the users — roles, what they do today, and how this change affects their workflow.>

### What success looks like

<Write each success criterion as a complete sentence, not a fragment. Example: "A driver who qualifies under both Bad Debt and Car Recovery on the same day receives exactly one notice, with Car Recovery taking priority." Number them 1, 2, 3… One per line, no sub-bullets.>

1. <criterion>
2. <criterion>

### Scope

<One paragraph describing what is in scope and what is explicitly out of scope. Prose, not bullets.>

### How we'll build it

<One paragraph describing the chosen technical direction in plain language — which services, what pattern, any key architectural decisions already confirmed.>

### Risks to watch

<For each open risk: one sentence stating what it is and one sentence stating the impact if it materialises. Number them.>

1. <risk and impact>

---

## Product plan

<!-- Include this section only if product plan is complete (resumed_phase >= 3) -->

<Paste the full prose product plan approved in step 2b — solution overview, user-facing flows, data involved, non-functional requirements, open assumptions.>

---

## Repos involved

<!-- Include this section only if repo intake is complete (resumed_phase >= 4) -->

<For each repo: name, kind (backend/frontend/full-stack), and one sentence on what work lands there.>

- **<repo-name>** (<kind>) — <what changes here>

---

## Backend design

<!-- Include this section only if backend design is complete (resumed_phase >= 5) -->

<For each implementation unit: its title as a heading, followed by 2–3 sentences on what it does, what files it touches, and any contract it exposes to the frontend.>

### BE-01 · <unit title>

<description>

### BE-02 · <unit title>

<description>

---

## Frontend design

<!-- Include this section only if frontend design is complete (resumed_phase >= 6) -->

<For each implementation unit: its title as a heading, followed by 2–3 sentences on what it does, what files it touches, and which backend unit it depends on.>

### FE-01 · <unit title>

<description>

---

> ⚠ Draft — `plan.json` not yet written. Resume: `/create-plan <plan_id>`
```

---

## Living Log File

**Purpose:** Users running `/create-plan` inside tmux or any terminal without scroll-back cannot see earlier questions and answers. The log file is a real-time readable record of the entire planning conversation — every question asked, every answer given, and the running confirmed context. It is updated after **every user response**, not just on save.

### When to create

- **Fresh plan:** Create `log.md` immediately after Step 0 confirms this is a fresh run (before asking the first brainstorming question). If `$AI_ORCH_PLAN_DIR` is set, write there. Otherwise derive the slug right now and `mkdir -p plans/<slug>/` so the file has a home.
- **Resumed plan:** Recreate `log.md` from `partial.json` on resume (after printing the resume banner), replaying all previously confirmed Q&A before continuing.

### When to update

`log.md` is updated at **two** moments, not one:

1. **Before showing anything** — whenever you are about to ask a question, present a summary, display a plan, or show a task DAG: first add every pending question to **Still to answer** and write `log.md`. This way the log always reflects what is being asked, even if the session crashes before the user replies.

2. **After every user response** — append a Q&A block to **Conversation so far**, remove the answered question(s) from **Still to answer**, and rewrite **Where we are** in full. Do this before asking the next question.

Never batch updates. A user should be able to open `log.md` mid-session and see both what was asked and the latest confirmed answer.

### Format

```markdown
# Plan Log — <title or "Untitled">

**Plan ID:** <slug or "pending"> · **Jira:** <key or "none"> · **Updated:** <ISO 8601>

---

## Conversation so far

<!-- One block per question–answer exchange. Only include real questions asked to the user.
     Do NOT log internal steps, confirmations like "yes/approved", or meta-discussion. -->

**Q1 · <short label>**
You were asked: <restate the question in one plain sentence>
You said: <the user's answer — quote directly or paraphrase faithfully in 1–3 sentences. Capture the substance, not just "yes".>

---

**Q2 · <short label>**
You were asked: <question>
You said: <answer>

---

<!-- add new blocks at the bottom, never edit previous ones -->

---

## Where we are

<!-- Rewrite this entire section after every answer. Write in prose — no bullet lists.
     This is what the user reads to understand the current confirmed state. -->

### The problem

<2–3 sentences. What is broken or missing today, who is affected, what the business impact is.
If not yet confirmed, write: "Not yet confirmed.">

### Who this is for

<1–2 sentences describing the users and how they interact with the system.
If not yet confirmed, write: "Not yet confirmed.">

### What we agreed to build

<2–3 sentences on scope — what is in, what is explicitly out. Plain language.
If not yet confirmed, write: "Not yet confirmed.">

### How we'll approach it

<1–2 sentences on the chosen technical direction. No jargon — explain like a summary.
If not yet confirmed, write: "Not yet confirmed.">

### Key constraints

<2–3 sentences on the most important constraints agreed so far — things the build must respect.
If not yet confirmed, write: "Not yet confirmed.">

### Open risks

<One sentence per risk. If none confirmed yet: "None surfaced yet.">

---

## Still to answer

<!-- List only genuine open questions the user still needs to answer.
     Remove each one as soon as the user answers it.
     If all questions are answered: write "All questions answered ✓" and omit the list. -->

- **Q<N>** · <label>: <the full question, written so the user can answer it without re-reading the terminal>
```

### Rules

- Write `log.md` atomically: `log.md.tmp` → `mv log.md.tmp log.md`.
- Never edit or remove previous Q&A blocks — only append new ones at the bottom of the Conversation section.
- Rewrite **Where we are** and **Still to answer** in full after every user response.
- Only log questions that required a real decision from the user. Do not log approvals ("yes/approved"), navigational prompts, or internal skill steps.
- Write **Where we are** in prose, not bullet points. A reader should be able to understand the full picture by reading four short paragraphs, not scanning a list.
- If the plan has no slug yet, buffer the log in memory and flush it as soon as the folder is created.
- The log is for human reading only — it is never parsed by the orchestrator.

---

## Steps

Run in strict order. Confirm each step with the user before advancing to the next. Never skip a gate.

**CRITICAL — no exploration before brainstorming:** Do NOT read any files, search the codebase, explore repos, or spawn any agents before completing Step 0 and Step 2a. The very first action after reading this skill is Step 0 (mode detection), then immediately Step 2a (brainstorming). Repo orientation happens in Steps 2d and 2e only — not here.

### 2a. DISCOVERY — Brainstorming Skill

Invoke `skills/brainstorming/SKILL.md` inline.

Pass: the requirement text, the `--jira` key if given.

The skill pins down the five context fields — problem, user, success criteria, scope, constraints — asking one cluster of questions at a time. If `--jira` was given, it loads the ticket first and only asks about gaps. It ends with a synthesized summary and a confirmation gate.

**Do not advance to 2b until the brainstorming summary is explicitly approved by the user.**

**AUTO-SAVE gate:** immediately after approval, silently write `partial.json` with `resumed_phase: 2` and `brainstorming_summary` populated, then continue.

---

### 2b. PRODUCT PLAN — Planning Skill

Invoke `skills/planning/SKILL.md` inline, passing the approved brainstorming summary.

The skill writes a prose product plan: solution overview, user-facing flows (happy path + key edge cases), data involved, non-functional needs (scale, auth, idempotency, observability), and open questions or assumptions. It presents the plan and requires explicit sign-off.

**Do not advance to 2c until the product plan is explicitly signed off.**

**AUTO-SAVE gate:** immediately after sign-off, silently write `partial.json` with `resumed_phase: 3` and `product_plan` populated, then continue.

---

### 2c. REPO INTAKE

Ask the user:

```
Which repos does this plan touch?

For each repo, provide:
  - Name (the id field from config/repositories.json, e.g. "hawkeye" or "everest_jarvis")
  - Kind: backend, frontend, or full-stack
  - Base branch (default: taken from repositories.json; override if needed)

You can list multiple. Reply "none yet" if this is greenfield work with no existing repo.
```

**Resolve each repo name via `config/repositories.json`:**
- Look up the entry by `id` field.
- Copy `base_branch` from the entry (unless the user overrides it).
- Set `path_or_url` to the repo's `path` field (e.g. `workspace/hawkeye`).
- If no matching `id` is found: tell the user and ask whether to (a) correct the name, or (b) enter the `path` and `base_branch` manually for a new/unregistered repo. In case (b), note that `/repo-context <id>` should be run once the repo is cloned, and that the sub-skills will fall back to reading `workspace/<id>/` directly.

If `none yet`: record `repos: []` and note in `plan.md` that this plan cannot be executed until a repository is named. Skip Steps 2d and 2e — go directly to 2f.

**AUTO-SAVE gate:** immediately after the user confirms the repo list (or "none yet"), silently write `partial.json` with `resumed_phase: 4` and `repos` populated, then continue.

**Log maintenance for Step 2c:**

*Before asking* — add to `log.md` **Still to answer** and write the file immediately:
```
- **Repos in scope**: Which repos does this plan touch? (name, kind, base branch for each)
```

*After the user confirms repos* — append a Q&A block to **Conversation so far**:
```
**Q<N> · Repos in scope**
You were asked: Which repos does this plan touch?
You said: <list the repos the user named, with kind>
```
Rewrite **Where we are** to record the confirmed repo list under **How we'll approach it**. Remove the repo question from **Still to answer**.

**`full-stack` repos:** a repo with `kind: full-stack` runs BOTH Step 2d (backend pass) AND Step 2e (frontend pass) for that same repo. Treat it as two separate design passes over the same codebase. The resulting tasks are tagged with that repo name but may have `type: development` for both backend and frontend work — distinguish them in the task title (e.g. "Add auth endpoint [backend]" vs "Add login page [frontend]").

---

### 2d. BACKEND DESIGN — Planning-Backend Skill (one pass per backend repo)

For each repo with `kind: backend` or `kind: full-stack`, invoke `skills/planning-backend/SKILL.md` inline, passing:
- The repo name (as entered in 2c — the skill resolves its path and context via `config/repositories.json`)
- The approved product plan from 2b

The skill reads `repo-context/<id>/` for context (context.md, structure.json, patterns.json, conventions.md, testing.md), orients in the repo, resolves design questions, and returns an **ordered list of implementation units** — each unit names the files it touches, any contract it exposes for a frontend to consume, and conventions to carry forward.

Collect all backend implementation units before advancing to 2e.

**AUTO-SAVE gate:** immediately after all backend units are collected, silently write `partial.json` with `resumed_phase: 5` and `backend_units` populated, then continue.

---

### 2e. FRONTEND DESIGN — Planning-Frontend Skill (one pass per frontend repo)

Run AFTER 2d — frontend design requires backend implementation units to verify API contracts.

For each repo with `kind: frontend` or `kind: full-stack`, invoke `skills/planning-frontend/SKILL.md` inline, passing:
- The repo name (the skill resolves path and context via `config/repositories.json`)
- The approved product plan from 2b
- All backend implementation units from 2d (so API contracts are visible)

The skill reads `repo-context/<id>/`, orients in the repo, resolves design questions (screens, state, API calls, loading/error/empty states), and returns an **ordered list of implementation units** — each unit names the files it touches and the backend unit IDs it depends on (via the `Backend dep` field).

Collect all frontend implementation units before advancing.

**AUTO-SAVE gate:** immediately after all frontend units are collected, silently write `partial.json` with `resumed_phase: 6` and `frontend_units` populated, then continue.

---

### 2f. ASSEMBLY

Turn the backend and frontend implementation units into the task DAG, present it for approval, then write the plan files.

**Step 1 — Derive the plan title.**
Compress the brainstorming summary's `Problem` field into a 3–5 word imperative noun phrase (e.g. "Add Driver Location Tracking", "Fix Fare Calculation Bug"). This becomes `plan.json.title` and the basis for the slug.

**Step 2 — Handle the greenfield case (`repos: []`).**
If steps 2d and 2e were skipped (no repos), there are no implementation units. Ask the user to describe 2–5 high-level tasks that capture intent. Set `repo: "<pending>"` on each. These are placeholders — the orchestrator cannot execute them until a repository is registered in `config/repositories.json` and bound at execution time.

**Step 3 — Convert implementation units to tasks.**

One implementation unit → one or more tasks. Split only along seams where each piece can be reviewed independently:
- Backend seams: migration, endpoint, async task, integration, management command
- Frontend seams: route/page, shared component, API client module, **tab or section component** (one task per tab/section when files share no code and can be developed independently — do NOT bundle multiple independent tab components into one task)

**Grouping rule:** Merge only when files are tightly coupled (e.g. a list view and the inline form on the same screen). Never merge components that live in separate files, fetch their own data independently, and have no shared state between them — these must be separate tasks even if they share a parent component.

Every task must have all fields populated:

| Field | Guidance |
|-------|----------|
| `id` | `task-001`, `task-002`, … sequential |
| `title` | Short imperative phrase: "Add auth endpoint", "Create login page" |
| `repo` | Matches a `repos[].name` in this plan (or `"<pending>"` for greenfield) |
| `type` | `architecture` (design/contract), `development` (code), `test` (test suite), `review` (human gate), `debug` (investigation) |
| `description` | Specific instructions + acceptance criteria embedded inline. Reference the exact models/endpoints/components named in 2d/2e — do not restate the whole requirement. |
| `depends_on` | List of task IDs that must finish first; `[]` if none |
| `parallelizable` | `true` only when no unmet `depends_on` AND no overlap in `files_touched` with any concurrently running task |
| `files_touched` | Repo-relative paths or globs. Never empty — the orchestrator uses this to gate concurrent dispatch |

**Step 3a — Quality gate tasks (mandatory, per repo)**

After all implementation units are converted to tasks, add quality-gate tasks for **every repo** in the plan. These are not optional — they ensure implementation is verified and reviewed before delivery. Run this step for each repo independently; the chains across repos are parallel.

For each repo, in order:

**A. Test task (conditional on repo runtime config)**

Look up the repo's entry in `config/repositories.json` (where `id == <repo-name>`). Read `runtime.test` and `runtime.test_cmd`.

- `runtime.test == true` AND `runtime.test_cmd` non-null → create **one** `test` task:
  - `id`: next sequential id
  - `title`: `"Run <repo-name> test suite"`
  - `type`: `"test"`
  - `repo`: `<repo-name>`
  - `description`: `"Run the full test suite. Activate env: <runtime.activate>. Command: <runtime.test_cmd>. Report all failures with output. Do not write any code."`
  - `depends_on`: IDs of every `architecture` and `development` task in this repo
  - `parallelizable`: false
  - `files_touched`: `[]` — tester reads but writes no source files

- `runtime.test == false` OR `runtime.test_cmd` null → **skip the test task**. Do not create a placeholder — the orchestrator would dispatch a tester against a repo with nothing to run. Instead, note the absence in the review task description (below).

**B. Review task (always — no exceptions)**

Create **one** `review` task per repo regardless of whether a test task exists:

- `id`: next sequential id
- `title`: `"Review <repo-name> implementation"`
- `type`: `"review"`
- `repo`: `<repo-name>`
- `description`: `"Review all implementation tasks for <repo-name> in this plan against the plan spec, repo conventions (repo-context/<repo>/conventions.md), security, error handling, and edge cases. Files in scope: <union of files_touched from all dev/arch tasks for this repo>.<if no test task was created for this repo, append: " No automated test suite exists for this repo — apply extra scrutiny to logic correctness and edge-case coverage.">"`
- `depends_on`: IDs of every `architecture` and `development` task in this repo **plus** the test task ID (if one was created for this repo)
- `parallelizable`: false
- `files_touched`: union of all `files_touched` from the implementation tasks in this repo

**Mandatory chain per repo:**
```
arch/dev tasks → [test task, if runtime.test==true] → review task (always)
```

No implementation task should land without a downstream review. If the plan touches multiple repos, each repo gets its own independent quality chain.

---

**Step 4 — Encode dependencies.**

- Frontend tasks that consume a backend contract must list the defining backend task in `depends_on`. Use the `Exposes contract` / `Backend dep` fields from 2d/2e to identify these edges.
- Within the same repo, tasks that write overlapping files must be ordered via `depends_on`.
- Cross-repo tasks never share files by definition, but still need `depends_on` if one side depends on a contract the other defines.
- The test and review tasks added in Step 3a already carry their within-repo dependency edges. Check that cross-repo frontend implementation tasks also `depends_on` their backend counterparts — not just the API service module task, but any backend task whose contract the frontend consumes directly.

**Step 5 — Present the draft for approval before writing any files.**

```
Plan title: <title>

## Draft Task DAG

| ID | Title | Repo | Type | Depends On | Parallel |
|----|-------|------|------|------------|---------|
| task-001 | ... | ... | development | — | ✓ |
| task-002 | ... | ... | development | task-001 | — |

<n> tasks total · <n> parallelizable

Approve? (yes / revise title / revise task-NNN / add a task / remove task-NNN)
```

Do not write any files until the user confirms. If they request revisions, update and re-present.

**Log maintenance for Step 2f — before presenting the DAG:** Update `log.md` **Still to answer** to add the approval question, then write the file, then display the DAG table:
```
- **Assembly approval**: Does the task DAG look right? (yes / revise title / revise task-NNN / add a task / remove task-NNN)
```

**After the user responds:** Append a Q&A block to **Conversation so far**:
```
**Q<N> · Assembly approval**
You were asked: Does the task DAG look right? (<n> tasks)
You said: <"approved" | description of what to change>
```
- **If approved:** rewrite **Where we are** — add "Task DAG approved — <n> tasks across <repos>" under **What we agreed to build**. Remove the approval question from **Still to answer**. Silently write a final `partial.json` checkpoint (`notes: "assembly approved — writing plan files"`).
- **If revision requested:** log the revision, update the DAG, add the approval question back to **Still to answer** for the next round. Silently write `partial.json` (`notes: "assembly revision <N>"`) before re-presenting.

**Step 6 — Derive the plan slug and check for collisions.**

**If `$AI_ORCH_PLAN_SLUG` is set, use it verbatim.** The orchestrator server reserved this slug up front, already handled collisions, and created `$AI_ORCH_PLAN_DIR` (= `plans/$AI_ORCH_PLAN_SLUG/`) with a seed `status.json`. Skip derivation and skip the `plans/<slug>/` collision check — this directory is yours. Still perform the branch collision check below.

Otherwise (CLI run, env unset): slug = `YYYYMMDD-<slugified-title>`: lowercase, spaces and special characters replaced by `-`. Prefix with today's date. Example: `20260826-add-driver-location-tracking`. If `plans/<slug>/` already exists, append a counter: `20260826-add-driver-location-tracking-2`.

**Predict the branch name and check for protected-branch collisions.** The plan slug is the input to `/execute-plan`'s branch resolver — surface what will happen now so the user can rename the plan title if there'd be a collision. Read templates from `config/repositories.json.branch_naming`, never hardcode:

- If `--jira <KEY>` was passed OR Step 8 will later return a Jira key → template `branch_naming.feature_with_jira` with `{jira_key}` and `{description} = <title-slug>` (2–5 kebab-case words from the plan title, no date prefix).
- Else (Jira skipped or not configured) → template `branch_naming.feature_no_jira` with `{plan_id} = <slug>` (the slug already carries date + description).

Applied to the default config, that predicts `feature-JAR-1234-add-driver-tracking` or `feature-20260826-add-driver-location-tracking`.

For every repo in the plan, cross-check the predicted branch against `config/repositories.json.repositories[<repo.name>].protected_branches`. If it matches any of them, halt this step and ask the user to shorten or rephrase the plan title so the slug produces a non-colliding branch — do not silently proceed and let `/execute-plan` fail on collision at pre-flight. Re-derive the slug from the new title and re-check.

Store the predicted branch to reference in Step 8; do not write it into `plan.json` — the branch is derived from `plan_id` + jira key + config at execute time, so persisting it would make the plan sensitive to config drift.

**Step 7 — Write plan files into the plan directory.**

**If `$AI_ORCH_PLAN_DIR` is set, write into that existing directory** — the server already created it and put a seed `status.json` in it. Do NOT `mkdir` a new folder. Write `plan.json`, `plan.md`, `state.json` alongside the existing `status.json`.

Otherwise (CLI run, env unset): create `plans/<slug>/` first, then write all three files.

**Write `plan.json`** per the schema above. For `delivery`:
- `jira_tickets`: `[]` — the Jira ticket is created in Step 8; this field is updated in-place after creation.

**Write `plans/<slug>/plan.md`**:

```markdown
# <title>

**Plan ID:** <id>
**Created:** <ISO 8601>
**Repos:** <name (kind)>, <name (kind)>

---

## Context

**Problem:** <problem>
**User:** <user>

**Success criteria:**
- <criterion>

**Scope:** <scope>

**Constraints:**
- <constraint>

---

## Product Plan

<!-- Paste the full approved product plan from step 2b VERBATIM — do not summarise, do not shorten.
     Every subsection the planning skill produced must appear here in full:
     Overview · User-Facing Flows · Data (with schema tables) · Execution Lifecycle (if async)
     · System Architecture (if multi-service) · Non-Functional Requirements (table) · Assumptions -->

### Overview
<from step 2b>

### User-Facing Flows
<from step 2b — happy path + key edge cases>

### Data
<from step 2b — one markdown table per entity>

### Execution Lifecycle
<from step 2b — state machines + per-lifecycle-event flow steps; omit section if not async/event-driven>

### System Architecture
<from step 2b — ASCII box diagram; omit section if single-service>

### Non-Functional Requirements
<from step 2b — markdown table>

### Assumptions
<from step 2b>

---

## Task DAG

| ID | Title | Repo | Type | Depends On | Parallel |
|----|-------|------|------|------------|---------|
| task-001 | ... | ... | development | — | ✓ |
| task-002 | ... | ... | development | task-001 | — |

<n> tasks total · <n> parallelizable

### Parallelism notes

Describe execution in waves — which tasks start immediately, which unblock after each wave, and why. Note any file-overlap constraints that prevent tasks running in parallel even when `depends_on` is clear. Example:

**Wave 1 (immediate):** task-001, task-006 — no dependencies, different repos.
**Wave 2 (after task-001):** task-002, task-003 — both unblock from task-001, no overlapping files.
**Wave 3 (after task-002 + task-003):** task-004 — gate task, depends on both.

One sentence per wave is enough. Name the tasks by ID, not just by title.

---

## Task Details

<!-- One subsection per task. Copy description verbatim from plan.json — do not summarise or shorten.
     This is the authoritative implementation spec the developer reads before writing any code. -->

### task-001 · <title>

**Repo:** <repo> · **Type:** <type> · **Depends on:** <depends_on joined by ", " or "—"> · **Files:** <files_touched joined by ", ">

<task description verbatim from plan.json>

### task-002 · <title>

**Repo:** <repo> · **Type:** <type> · **Depends on:** <depends_on joined by ", " or "—"> · **Files:** <files_touched joined by ", ">

<task description verbatim from plan.json>

<!-- repeat for every task -->

---

## Delivery

- **Jira:** <ticket key and URL, or "none">
- **Branch (predicted):** `<predicted branch name from Step 6>` — resolved from `config/repositories.json.branch_naming` at `/execute-plan` pre-flight

> ⚠ Greenfield plan — no repository bound yet. Run `/execute-plan <id> --repos <name>` once the repo exists under `workspace/` and is registered in `config/repositories.json`.

> ⚠ **Delivery note:** <any post-deploy operational step that is required after execution completes — e.g. running a management command, attaching a Lambda Layer, seeding a permission, coordinating with another team. Write one ⚠ block per distinct post-deploy action. Omit this section entirely if there are no post-deploy steps.>
```
(Omit the greenfield ⚠ line for plans that have repos. Omit the delivery note ⚠ lines if there are no post-deploy steps. Omit the branch line only if the plan is greenfield.)

**Write `plans/<slug>/state.json`** — initial execution state for the orchestrator:

```json
{
  "plan_id": "<slug>",
  "status": "approved",
  "created_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",
  "started_at": null,
  "finished_at": null,
  "branch": null,
  "worktrees": {},
  "provisioning": {},
  "provisioning_notes": {},
  "task_states": {},
  "task_results": {},
  "attempts": {},
  "fix_cycles": {},
  "adhoc_tasks": {},
  "current_tasks": [],
  "blocked_by": {},
  "prs": {},
  "jira_updated": [],
  "stop_reason": null,
  "stop_task_id": null
}
```

Every field is seeded with its correct empty type — `{}` for dicts, `[]` for lists, `null` for scalars. The orchestrator iterates `adhoc_tasks` and other dicts on every loop tick; a missing field causes a crash. The execute-plan skill extends `worktrees`, `provisioning`, and `branch` during pre-flight; the orchestrator extends everything else during the DAG loop.

After writing all three files, proceed to Step 8.

**Step 8 — Create or update the Jira ticket.**

Invoke `skills/create-jira-story/SKILL.md` inline, passing:
- `plan_title` — the title derived in Step 1
- `plan_id` — the slug derived in Step 6
- `context` — the five fields from the approved brainstorming summary
- `open_risks` — the "Open risks" field from the brainstorming summary
- `repos` — the list from 2c (used to resolve the Jira project key via `jira.projects` in `config/integrations.json`)
- `backend_units` — the implementation units collected from 2d (empty list if no BE repos)
- `frontend_units` — the implementation units collected from 2e (empty list if no FE repos)
- `jira_key` — the `--jira` value if provided, otherwise `null`

The skill creates a new Story (or updates the existing ticket) and returns the Jira key. If a key is returned, update `delivery.jira_tickets` in `plan.json` to `["<key>"]` (atomic overwrite of the same file written in Step 7). If the skill returns `null`, leave `delivery.jira_tickets: []`.

The skill handles MCP → REST fallback and never blocks plan creation on Jira failure.

**STOP after completing Step 8.** Print:

```
Plan saved: plans/<id>/
  plan.json   — machine-readable task DAG (<n> tasks, <n> parallelizable)
  plan.md     — human-readable summary
  state.json  — initial status: approved

Repos  : <names and kinds>  [or "none — bind a repo via /execute-plan <id> --repos <name>"]
Jira   : <ticket key> — <jira.base_url>/browse/<key>  [or "not configured — Jira skipped"]
Branch : <predicted branch name from Step 6>  [omit line entirely if greenfield]

Run /execute-plan <id> to begin execution.
```

The `Branch` line is a preview — the branch is not created here. `/execute-plan` re-resolves it at pre-flight using the same config templates. If Jira was skipped at Step 8 but the user later provides a key at `/execute-plan`'s Jira gate (see `skills/execute-plan/SKILL.md` Step 1), the branch shifts from the no-jira fallback to `feature_with_jira` — this preview reflects the state at plan creation only.

---

## Constraints

- Never skip a gate — not for a request that looks "obvious", not for a small one.
- Do not write plan files before the user approves the task DAG in step 2f.
- Do not execute any implementation work.
- Do not write feature code.
- Do not assign tasks to agents or invoke developer/tester/reviewer agents.
- For greenfield work (`repos: []`): state explicitly in `plan.md` that `/execute-plan` halts until a repo exists under `workspace/` and is registered in `config/repositories.json`.
- **Do not read files, search the codebase, or explore repos before Step 2a.** The first action is always Step 0 then Step 2a (brainstorming). Any codebase/repo exploration belongs in Steps 2d and 2e only.

## Workflow Diagram

```
/create-plan "requirement" [--jira KEY]
        │
        ▼
┌─────────────────────────────────────────────────┐
│ 2a. brainstorming skill                          │  problem · user · success criteria · scope · constraints
│                                                   │  HARD GATE: explicit approval required
└──────────────────────┬──────────────────────────┘
                       ▼  (approved)
┌─────────────────────────────────────────────────┐
│ 2b. planning skill                               │  prose product plan: overview · flows · data · NFRs · open questions
│                                                   │  HARD GATE: explicit sign-off required
└──────────────────────┬──────────────────────────┘
                       ▼  (signed off)
┌─────────────────────────────────────────────────┐
│ 2c. repo intake                                  │  ask for repos; resolve id + path + base_branch from repositories.json
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ 2d. planning-backend                             │  once per backend/full-stack repo
│     reads repo-context/<id>/  +  workspace/<id>/│  → outputs BE-01, BE-02, … implementation units
└──────────────────────┬──────────────────────────┘
                       ▼  (must complete before 2e — frontend needs backend units)
┌─────────────────────────────────────────────────┐
│ 2e. planning-frontend                            │  once per frontend/full-stack repo
│     reads repo-context/<id>/  +  workspace/<id>/│  → outputs FE-01, FE-02, … implementation units
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ 2f. assembly                                     │  build task DAG:
│                                                   │    Step 3  — convert impl units to arch/dev tasks
│                                                   │    Step 3a — per-repo quality gates (MANDATORY):
│                                                   │              test task (if runtime.test==true)
│                                                   │              review task (always, no exceptions)
│                                                   │    Step 4  — encode all dependencies
│                                                   │  → PRESENT DRAFT → approval gate
│                                                   │  → write plan.json + plan.md + state.json (jira_tickets: [])
│                                                   │  → create-jira-story skill (create or update ticket, update plan.json) → STOP
└─────────────────────────────────────────────────┘
```

`brainstorming` never touches repo code. `planning` produces prose only. `planning-backend` / `planning-frontend` read repo code but write nothing. `create-jira-story` runs after user approval — Jira failure never blocks plan creation. 2e always runs after 2d — it needs backend units to check API contracts.
