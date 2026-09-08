---
name: brainstorming
description: You MUST use this before /create-plan asks any repo-specific question. Turns a raw requirement, Jira ticket, or rough idea into a clear, agreed-upon direction — classifies the request, asks clarifying questions one at a time, proposes approaches, and gates on explicit user approval before the command advances to the product plan step.
---

# Skill: Brainstorming

## 1. Purpose

Turn a raw requirement — free text, a Jira issue, or a rough idea — into five agreed-upon context fields: **problem, user, success criteria, scope, constraints**. These become `plan.json.context` and anchor everything that follows. This skill pins down the PROBLEM, not the solution — direction comes here, repo-specific design comes later.

<HARD-GATE>
Do not let the conversation advance past this skill until you have presented a synthesized summary and the user has explicitly approved it. "Sounds good" or "yes, that's right" is enough — silence, or the conversation simply moving to the next topic, is not approval. The command advances to the product plan step only after explicit confirmation.
</HARD-GATE>

## 2. When Invoked

Invoked by `/create-plan` (Step 2a) before any repo-specific work. Never invoked directly by the user, and never used for bug fixes — those go through `bug-management`'s own autonomous flow.

## 3. Inputs

- Requirement text as typed by the user.
- Jira issue key, if `--jira` was passed.

## 4. Workflow

### Step 0 — Context Intake (always run first)

Before classifying or asking any question, check the requirement text. If it is a short title or phrase (roughly fewer than 15 words, no clear problem statement), ask **one** question:

> Do you have a Jira ticket key (e.g. `JAR-1234`) or a detailed description to paste in? Sharing either now lets me skip questions the context already answers. Say **proceed** to continue with what you've provided.

- If the user gives a Jira key → treat it as `--jira <KEY>`, then go to Step 1.
- If the user pastes a description → treat it as enriched requirement text, skip Step 1, go to Step 2.
- If the user says "proceed" or equivalent → continue to Step 2 with the original text.

If the requirement text already contains a clear problem description (a full sentence or more), skip this step and go directly to Step 1.

---

### Step 1 — Load Jira Context (if provided)

If a Jira issue key was passed (via `--jira` argument or offered in Step 0), fetch it via the Atlassian MCP server (`atlassian` / `jira_get_issue`) — see `.claude/MCP.md`. Extract title, description, and any acceptance criteria already written. If the MCP server is unavailable, warn and continue with the requirement text alone — never block on it.

### Step 2 — Classify the Request

State the classification out loud before asking anything else, so the user can correct it if it's wrong:

| Classification | Signs |
|---|---|
| **Feature** | Net-new capability; no existing flow to modify |
| **Change** | Modifies the behavior of something that already exists (in a known codebase or service) |
| **Initiative** | Bundles multiple related features/changes — likely needs decomposing into more than one plan |
| **Unclear** | Not enough information yet — ask before classifying |

If **Initiative**: say so immediately, and help the user decompose it into independently-plannable pieces before going further. Brainstorm only the first piece through the rest of this flow; the remaining pieces become future `/create-plan` runs.

### Step 3 — Ask Clarifying Questions, One at a Time

**Scope of questions — strictly the five context fields (problem, user, success criteria, scope, constraints).** The following are always off-limits in brainstorming — they belong in later steps:

| Off-limits topic | Where it is resolved |
|---|---|
| Which repos or services are involved | Step 2c — Repo Intake |
| Tech stack, frameworks, languages, databases | Steps 2d / 2e — planning-backend / planning-frontend |
| API design, data models, schema, migrations | Step 2d — planning-backend |
| UI patterns, components, routing, state | Step 2e — planning-frontend |
| Deployment, infrastructure, environment | Step 2d or 2e |

If a question feels technical or repo-specific, skip it here — it will be asked in the right step.

Ask only what's needed to understand the problem — never more than one question per message. Prefer whichever question would most change the direction if answered differently. Typical ground to cover — skip anything the requirement text or Jira ticket already answers:

- What problem is this solving, and why now?
- Who is affected, and what happens if this isn't done?
- As a [role], I want [capability], so that [outcome] — pin down the user story.
- What is explicitly out of scope?
- What's the appetite — hours, a day, a few days, longer?
- What could make this bigger or harder than it looks?
- What assumptions are being made that could be wrong?
- What existing queues, tables, APIs, or external systems does this integrate with or depend on? (Captures pre-existing infrastructure so planning doesn't have to assume it.)
- Are there any configuration values, external files (templates, fixtures), data seeds, or inputs from other teams this feature needs before it can go live? (Captures operational dependencies early — otherwise they surface as late assumptions.)

If an answer raises a new question, ask that follow-up before moving to the next topic — don't queue multiple questions in one message.

**Know when to stop asking.** Aim to reach Step 4 within about six questions. If the direction is still unclear after that, say so plainly and propose narrowing the scope — an endlessly-clarified request is a sign the request is too big, not that one more question will settle it.

### Step 4 — Propose Directions

Once the shape of the request is clear, propose 1–3 concrete directions with trade-offs. Lead with the one you'd recommend and say why. Keep this conversational — a paragraph per option, not a spec.

If there is really only one sane direction, say so plainly instead of manufacturing alternatives.

**Direction must stay at the architectural level.** Describe which components exist, how data flows between them, and what the trigger mechanism is (e.g., "two-phase Lambda driven by EventBridge + SQS", "DB-first write with external API sync", "shared Lambda Layer for cross-service status writes"). Do NOT name specific libraries, ORMs, or schema patterns — those belong in planning-backend and planning-frontend. A direction that specifies a library (e.g., "docxtpl + LibreOffice for PDF") is too low-level and may be wrong by the time planning runs.

### Step 5 — Present the Synthesized Direction and Gate

Summarize in a short brief. The five `context` fields map directly into `plan.json` after approval — fill them precisely:

```
## Brainstorming Summary

Classification    : <Feature | Change | Initiative>

Problem           : <one or two sentences — what is broken or missing, and why it matters now>
User              : <who is affected and how>
Success criteria  :
  - <measurable outcome 1>
  - <measurable outcome 2>
  [For automated/event-driven features: each independently verifiable behaviour gets its own
   criterion — selection logic, per-recipient routing, failure isolation, re-trigger behaviour]
Scope             : <what is explicitly in scope, including pre-existing systems this integrates with>
Constraints       : <technical or business constraints — things this plan must not break or must reuse;
                    include pre-existing queues/tables/APIs this depends on;
                    include any operational dependencies (configs, templates, seeds) needed before go-live>

Direction         : <architectural approach — components, data flow, trigger mechanism.
                    NOT specific libraries or schema patterns — those belong in planning-backend/frontend.>
Open risks        : <anything uncertain or that could make this harder than it looks>

Does this look right before we move to the product plan?
```

**Do not proceed until the user confirms.** If they push back, revise and re-present — never reinterpret silence, or a change of subject, as agreement.

### Step 6 — Hand Off

Once approved, hand the brainstorming summary — including all five context fields and the Jira key if one was given — back to `/create-plan`. The command advances to Step 2b (planning skill). Do not branch into repo-specific questions here; that comes later in Steps 2d and 2e.

## 5. Files Read

- External Jira issue, if `--jira` provided.

## 6. Files Written

- `$AI_ORCH_PLAN_DIR/log.md` — updated after every user answer (see Log Maintenance below).
- `$AI_ORCH_PLAN_DIR/partial.json` — written once, silently, immediately after the user approves the summary in Step 5.

## 6a. Log Maintenance

**Before asking each question in Steps 3 and 4** — immediately before sending the question to the user, add it to **Still to answer** and write `log.md`:
```
- **Q<N> · <label>**: <the question, written so the user can answer without re-reading the terminal>
```
Write `log.md` atomically, then send the question. This ensures the log always shows what is pending even if the session crashes mid-question.

**After every user answer during Steps 3 and 4**, update `log.md` atomically (`log.md.tmp` → `mv log.md.tmp log.md`):

1. Append a new Q&A block at the bottom of the **Conversation so far** section:
   ```
   **Q<N> · <short label>**
   You were asked: <the question, one plain sentence>
   You said: <the user's answer — quote or paraphrase faithfully in 1–3 sentences>
   ```
   Only log real decisions made by the user. Do not log "yes/approved" responses, navigational prompts, or internal steps.

2. Rewrite the **Where we are** section in full — four short prose paragraphs:
   - **The problem** — what is broken or missing, who is affected, why it matters. "Not yet confirmed." until answered.
   - **Who this is for** — users and how they interact. "Not yet confirmed." until answered.
   - **What we agreed to build** — scope in and out. "Not yet confirmed." until answered.
   - **How we'll approach it** — chosen direction. "Not yet confirmed." until answered.
   - **Key constraints** — most important constraints confirmed so far.
   - **Open risks** — one sentence per risk. "None surfaced yet." if none.

3. Rewrite the **Still to answer** section — list only questions the user has not yet answered. Remove each entry as it is answered. Write "All questions answered ✓" when the list is empty.

**Before presenting the summary in Step 5** — update `log.md` **Still to answer** to add the approval question, then write `log.md`, then display the summary:
```
- **Brainstorming approval**: Does this brainstorming summary look right before we move to the product plan?
```

**After Step 5 approval**, silently write both `partial.json` and `partial.md`:

```bash
PLAN_DIR="${AI_ORCH_PLAN_DIR:-plans/<slug>}"

# 1. partial.json
cat > "$PLAN_DIR/partial.json.tmp" <<'JSON'
{
  "plan_id": "<slug>",
  "title": "<title>",
  "resumed_phase": 2,
  "saved_at": "<ISO 8601>",
  "jira_key": "<key or null>",
  "brainstorming_summary": {
    "classification": "<feature|change|initiative>",
    "problem": "<one or two sentences>",
    "user": "<who is affected and how>",
    "success_criteria": ["<criterion 1>", "..."],
    "scope": "<what is in scope>",
    "constraints": ["<constraint 1>", "..."],
    "direction": "<chosen approach>",
    "open_risks": ["<risk 1>", "..."]
  },
  "product_plan": null,
  "repos": null,
  "backend_units": null,
  "frontend_units": null,
  "notes": "auto-saved after brainstorming approval"
}
JSON
mv "$PLAN_DIR/partial.json.tmp" "$PLAN_DIR/partial.json"

# 2. partial.md — human-readable draft shown in UI
cat > "$PLAN_DIR/partial.md.tmp" <<'MD'
# <title> — Draft Plan

**Plan ID:** <slug>
**Jira:** <key or "none">
**Saved:** <ISO 8601>

## Progress

| Phase | Status |
|-------|--------|
| 1 · Brainstorming   | ✓ Done |
| 2 · Product Plan    | – Pending |
| 3 · Repo Intake     | – Pending |
| 4 · Backend Design  | – Pending |
| 5 · Frontend Design | – Pending |
| 6 · Assembly        | – Pending |

---

## What we're building

<2–4 sentences — what is broken or missing today, who is affected, why it matters now. Plain language, no bullet points.>

### Who this is for

<One paragraph — the users, their role, and how this change affects their workflow.>

### What success looks like

<Each success criterion as a complete sentence, numbered.>

1. <criterion>
2. <criterion>

### Scope

<One paragraph — what is in scope and what is explicitly out of scope.>

### How we'll build it

<One paragraph — the chosen technical direction in plain language.>

### Risks to watch

<One sentence per risk stating what it is and what the impact is if it materialises.>

1. <risk and impact>

---

> ⚠ Draft — `plan.json` not yet written. Resume: `/create-plan <plan_id>`
MD
mv "$PLAN_DIR/partial.md.tmp" "$PLAN_DIR/partial.md"
```
Do not print anything to the user when writing these files.

## 7. State Changes

`partial.json` written (or overwritten) with brainstorming summary after Step 5 approval.

## 8. Failure Handling

- If Jira is unavailable, continue with whatever requirement text is available — never block on it.
- If the request turns out to be an Initiative spanning unrelated repos or teams, stop and help decompose rather than brainstorming all of it at once.

## 9. Output

An approved brainstorming summary with five context fields populated (problem, user, success criteria, scope, constraints), handed back to `/create-plan` for Step 2b.

## 10. Rules and Constraints

- Never skip the approval gate — not for a request that looks "obvious", not for a small one.
- One question per message.
- Do not invoke `planning`, write any plan file, or touch any repository until the summary is approved.
- Do not re-ask a question the requirement text or Jira ticket already answered.
- Never used for bug fixes — `/fix-bug` and `bug-management` own that flow entirely.
- **Step 0 is always the first action** — never classify or ask questions before first checking whether the user has Jira or richer context to provide (when requirement text is short).
- **Never ask about repos, services, tech stack, frameworks, data models, API design, migrations, infrastructure, or any implementation detail.** Those belong in Steps 2c (repo intake), 2d (planning-backend), and 2e (planning-frontend). If a question touches any of those areas, skip it here.
