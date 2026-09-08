---
name: planning-frontend
description: Orient in a frontend repo, surface mandatory design questions (page placement, routing type, UX pattern, permission registration), resolve design details, and return an ordered list of implementation units with files_touched and backend dependencies. Invoked by /create-plan Step 2e for each frontend/full-stack repo — never directly.
---

# Skill: Planning — Frontend

## 1. Purpose

Given a signed-off product plan, a repo name, and the backend implementation units (if any), orient in the repo, ask all mandatory design questions, resolve implementation specifics, and return an **ordered list of implementation units**. Each unit names the files it touches, the API contracts it depends on, and any backend unit dependencies. The assembly step (Step 2f) turns these units into tasks.

## 2. When Invoked

Invoked by `/create-plan` Step 2e, once per repo with `kind: frontend` or `kind: full-stack`. Never invoked directly by the user. Always runs after `planning-backend` when backend repos are in scope — it needs the backend implementation units (specifically their `Exposes contract` fields) to verify API alignment.

## 3. Inputs

- `repo_name` — the name the user provided in Step 2c (e.g. `hawkeye`)
- The signed-off product plan from `planning/SKILL.md`
- Backend implementation units from `planning-backend` (if any backend repos are in scope) — used to verify API contract alignment
- Jira issue key, if any

## 4. Workflow

### Step 1 — Orient in the Repo

**Resolve the repo ID and paths first.** Read `config/repositories.json` and find the entry whose `id` or `path` matches `repo_name`. The `id` indexes the context directory; the `path` gives the workspace location. Example: `id: "hawkeye"` → context at `repo-context/hawkeye/`, source at `workspace/hawkeye/`.

Read context files if available — skip gracefully if absent:
- `repo-context/<id>/context.md` — stack, directory map, routing, entry points
- `repo-context/<id>/structure.json` — file tree with component/page/service roles
- `repo-context/<id>/patterns.json` — representative file paths per pattern
- `repo-context/<id>/conventions.md` — component patterns, state management, data fetching, design system
- `repo-context/<id>/testing.md` — test setup, how components are tested

If no context files exist, read key files directly from `workspace/<id>/` (root listing + `package.json`, `src/App.tsx` or `src/main.ts`, router config). Suggest running `/repo-context <id>` afterwards.

Read 2–3 representative source files to ground your understanding before writing any questions or units — e.g. an existing screen most similar to what this plan adds, plus the router/permission registration file. If the product plan or any prior conversation references a Figma file, screenshot, or mockup, note its URL/path so you can reference it when asking Category B questions.

After reading, state what you found:
```
Repo: <name>  (id: <id>, path: workspace/<id>)
Framework: <e.g. React 18 / Next.js 14 / Vue 3>
Router: <e.g. React Router v6, Next.js App Router, Vue Router>
State management: <e.g. Zustand, Redux, React Query, none>
Design system: <e.g. Tailwind + shadcn/ui, Material UI, custom>
Context files: <present | absent — suggest /repo-context <id>>
Similar feature: <nearest existing screen/component and where it lives, including file path>
Permission system: <how pages are registered and become visible in the menu — one sentence>
```

---

### Step 1b — Propose Build Scope

**Run this immediately after Step 1, before asking any questions.**

Read the product plan in full. Derive what this frontend repo needs to build. Present a structured scope proposal — the user must be able to read this and say "you missed X" before any detailed questions are asked.

```
## What I propose to build in <repo-name>

**New pages / screens / routes:**
  - <PageName> — one line on what it shows and what user action it enables
  - ...
  (write "none" if no new pages)

**New tab or section components (within an existing page):**
  - <ComponentName> — which existing page it lives in, what it does
  - ...
  (write "none" if no new tabs/sections)

**New shared components:**
  - <ComponentName> — what it does, which screens use it
  (write "none" if none)

**Modified existing pages / components:**
  - <page or component name> — what changes
  (write "none" if nothing modified)

**API calls this frontend will make:**
  - <action> → <backend endpoint or service> — when it's called
  - ...

**Permission / route registration required:**
  - <yes — describe what needs to be registered and where | no>

Does this cover everything, or is anything missing from this repo's scope?
```

**Wait for the user's answer before proceeding to Step 2.** If they flag missing items, add them and re-present. If they confirm it's complete, proceed.

This proposal becomes the boundary for Step 2 questions — ask only about the items listed here.

**Intra-phase checkpoint — run immediately after scope is confirmed:** Silently write both `partial.json` and `partial.md`:
- `partial.json`: read existing file, set `frontend_units` to `[]` (empty array — signals "2e started, units not yet collected"), set `notes` to `"frontend design in progress — scope confirmed for <repo>"`, update `saved_at`. Write atomically.
- `partial.md`: write with `| 5 · Frontend Design | → In progress |` and all prior completed sections filled in. Frontend Design section body: `"Scope proposal confirmed — design questions pending."`. Write atomically.
Do not print anything to the user.

---

### Step 2 — Surface Mandatory Design Questions

**This step is MANDATORY. Run it before drafting any implementation units.**

The product plan states what flows and screens are needed. This step answers the repo-specific "how" and "where" questions that can only be resolved through code inspection and user input. The product plan mentioning a UI concept is NOT the same as confirming the page placement, routing type, or design system specifics.

**Scan the confirmed scope from Step 1b and identify all open questions across the following categories. Ask ALL applicable questions grouped by category in one or two messages.**

Do NOT skip a category because the product plan mentioned the topic at a high level. Do NOT assume an answer because it seems "obvious" from the plan. If a category genuinely does not apply, skip it.

---

**Category A — Page Placement and Routing**
*(Always ask for any new screen, page, or significant section of the UI)*

- Which dashboard should this feature live under? (Provide the dashboard `uri` — not just the display name.) Which user role(s) should see it?
- Which sidebar group should it appear in, and what is the `parent_uri` for that group?
- Should this be implemented as:
  (a) a new separate route (new entry in the permissions/routing system, appears in the sidebar),
  (b) a tab on an existing page (no new route, lives inside an existing screen),
  (c) a drawer or modal on an existing screen (no route, no sidebar entry), or
  (d) a combination?
- If a new route: what should the URL path, the `uri` value, the display name, and the `calendar_type` be for the permissions record?
- How does the new page get registered so it appears in the sidebar? Is there a management command, DB seed, or admin UI step required? Who runs it and when?

---

**Category B — UX / Design Reference**
*(Always ask — never start designing a screen without a reference; no design from scratch)*

First, determine which design input mode applies. Ask the user:

> Do you have a Figma/wireframe, a screenshot, or a reference to an existing screen/component in the repo? Share whichever you have now.

Then, based on what they provide, ask the mode-specific questions below. Only ask questions from the matching mode.

---

**Mode 1 — Figma or Wireframe provided**
*(User shares a Figma link or a wireframe file)*

- Does the Figma cover all the flows listed in the product plan? If any flow is missing (e.g. empty state, error state, mobile view), call it out now.
- Are there any interactions or transitions shown in the Figma that are not standard in this repo's design system? (e.g. custom animations, non-standard modals)
- Which design system tokens, color constants, or component library items in the Figma map to what this repo uses? (e.g. Figma "Primary Button" → `Button` from `antd`; Figma `#1890FF` → `COLORS.primary` from `utility/colors.js`)
- Are there any elements in the Figma that should NOT be implemented in this phase (deferred, out of scope)?
- Is pixel-level fidelity required, or is structural/behavioral fidelity sufficient?

---

**Mode 2 — Screenshot provided**
*(User shares a static image of an existing screen — from this app or another)*

- Which specific parts of this screenshot should be replicated exactly (layout, component structure, visual style) vs. adapted for the new feature?
- Which interactions and states are NOT visible in the screenshot and need to be decided now? (e.g. how filters behave, what happens on row click, loading/empty/error states)
- If the screenshot is from a different app or repo: which design system elements in this repo are the closest match to what's shown? (e.g. "the filter bar shown → use `FilterBar` from `src/components/common/FilterBar.js`")
- Are there any visual elements in the screenshot that should NOT be replicated (e.g. a column, a button, a panel that doesn't apply here)?

---

**Mode 3 — Repo file or component reference**
*(User names an existing screen, section, or component in this repo — e.g. "the admin panel utility tabs in hawkeye")*

- What is the exact file path of the reference screen or component? (e.g. `src/components/app/admin/utility/index.js`)
- Which parts of that reference should be reused as-is, cloned and adapted, or are off-limits for this feature?
- What is structurally different about the new feature compared to the reference? (e.g. different data source, extra tab, different action buttons, additional filter)
- Should the new screen live alongside the reference (sibling route/tab) or replace/extend it?
- Are there any conventions in the reference file that are specific to that screen and should NOT be carried over (e.g. a one-off workaround, a deprecated pattern)?

---

*(If the user provides none of the above — no Figma, no screenshot, no repo reference — do not proceed. Ask them to either share one of the above or open the app and identify the closest existing screen by its menu path or URL. Do not design from scratch.)*

---

**Category C — Tab, Drawer, and Navigation Structure**
*(Ask if the feature involves tabs, multi-section pages, or detail views)*

- If tabs are used: should they use the application's standard tab component (e.g. Ant Design Tabs) or a custom tab bar pattern as used by existing screens? Provide the reference file.
- When a user navigates away from a tab and returns, should the tab state (filters, selected rows, form data) be preserved or reset?
- Should any user action in one tab (e.g. creating a record) automatically refresh content in another tab?
- Is the detail view a drawer, a modal, or a separate route? If a drawer, what is its width and how is it triggered?

---

**Category D — State Management and Data Fetching**
*(Ask if the feature involves shared state, complex data fetching, or optimistic updates)*

- Is there any state that needs to be shared between tabs, between a list and a drawer, or between parent and child components? If so, where should it live (page-level component, context, Redux store)?
- Should data be refetched automatically after a create/edit/delete action, or is there a manual refresh button?
- For paginated tables: which pagination hook or component is the standard in this repo? Does it support both offset and cursor-based pagination?

---

**Category E — Permission Gating and Action-Level Controls**
*(Ask if the feature has any action-level permissions beyond page visibility)*

- Which actions (create, edit, delete, trigger, approve) require permission gating beyond just the page being visible to the user role?
- Should any tab, section, or button be hidden or disabled based on user role or specific permission flag?
- What is the `can_edit` or action permission URI for this page, and how is it checked in this codebase?

---

**Category F — API Contract Specifics**
*(Ask for each backend unit whose contract this frontend consumes)*

For each backend endpoint this screen will call:
- What is the exact URL path, method, and base server (JARVIS, FLEET, etc.)?
- What query parameters are accepted for filtering/pagination, and what are their exact names?
- What is the response envelope shape — e.g. `{data: {records: [...], metadata: {...}}}` vs `{data: [...], pagination: {...}}`?
- What HTTP status codes indicate an actionable error (e.g. 400 for blocked delete) vs. a generic failure?

---

**Wait for user answers before proceeding to Step 2.5.**

Group questions into at most two messages. Do not ask more than 12 questions total across all categories — prioritize those whose answer most changes the component structure, routing approach, or visual design. Category B must always be asked before Categories C–F.

---

### Step 2.5 — Design Synthesis and Approval

**This step is MANDATORY.** Run it after receiving answers to Category B questions, before proceeding to Steps 3–6 or drafting any implementation units. The design direction must be locked before the technical breakdown begins.

**1. Read the reference material.**

- **Mode 1 (Figma):** Confirm you can access the Figma link. Note any flows or states from the product plan that the Figma does not cover — these become open items in the synthesis.
- **Mode 2 (Screenshot):** Identify which existing repo files most closely implement what the screenshot shows. Read 1–2 of those files to ground the mapping.
- **Mode 3 (Repo reference):** Read the exact file(s) the user named. Note the component structure, state management approach, data fetching pattern, and any conventions used.

State what you read:
```
Design reference: <Figma URL | "screenshot provided" | file path(s) read>
Key patterns observed: <e.g. "uses AntD Tabs with lazy-loaded tab content, filter bar above the tab container, row click opens a right drawer at 600px">
```

**2. Draft a design proposal.**

Produce a concrete description of what the new feature will look like and how it will behave, grounded in the reference:

```
Design Proposal: <feature name>

Layout:        <page structure — header, filter bar, tab container, table/cards, drawer, etc.>
Placement:     <route or tab location, based on Category A answers>
Follows:       <which reference file / Figma frame / screenshot section this mirrors>
Deviations:    <intentional differences from the reference, and why>

Components:
  Reuse as-is: <component name — file path>
  Clone & adapt: <component name — file path — what changes>
  New:         <component name — what it does, which reference it mirrors>

UX decisions:
  - <e.g. "Tab state resets on navigate away — matches existing utility tab pattern">
  - <e.g. "Detail opens in right drawer (600px), not a separate route">
  - <e.g. "Empty state: icon + message + CTA button, same as <file>">

Design system:
  - <token / constant / class names that must be used — exact names and import paths>

Open items:    <flows or states not covered by the reference that still need a decision>
```

**3. Generate an HTML mockup.**

After drafting the design proposal, produce a static HTML file that visually represents the proposed UI. Write it to `plans/<plan-id>/design-mockup.html`.

The mockup must:
- Use inline CSS only (no external dependencies — it must open in any browser without a server)
- Render the full page layout: nav/sidebar placeholder, page header, filter bar, tabs or section structure, table or card area, any drawers or modals (shown open in a second section if needed)
- Use realistic placeholder data — not "Lorem ipsum", but data that matches the domain (e.g. driver names, trip IDs, status badges)
- Show the key states inline: normal loaded state, one empty state, one error/blocked state (can be separate `<section>` blocks with a heading label)
- Match the visual style of the reference as closely as possible using the design system tokens and color constants identified in the proposal (hardcode the actual hex/spacing values you found)
- Include a comment block at the top: `<!-- Design Proposal: <feature name> | Reference: <file or Figma> | Generated by planning-frontend skill -->`

Tell the user:
```
Design mockup written: $AI_ORCH_PLAN_DIR/design-mockup.html
Open it in a browser to review the proposed layout.
```

**4. Gate — explicit approval required.**

Present the text proposal and point to the mockup file, then ask:
> Open `$AI_ORCH_PLAN_DIR/design-mockup.html` in a browser. Does this layout and design direction match your vision? Approve to proceed, or tell me what to change.

If the user requests changes: update the proposal text, regenerate the mockup, and re-present. Do not proceed to Step 3 until the design is explicitly approved.

**Intra-phase checkpoint — run immediately after design is approved:** Silently write both `partial.json` and `partial.md`:
- `partial.json`: read existing file, update `notes` to `"frontend design in progress — design approved for <repo>"`. All other fields unchanged. Write atomically.
- `partial.md`: same structure — `| 5 · Frontend Design | → In progress |`. Frontend Design section body: `"Scope confirmed, design approved — implementation units pending."`. Write atomically.
Do not print anything to the user.

---

### Step 3 — Resolve Screens and Components

Based on user answers and the product plan's flows:
- Which screens, pages, or routes are new or modified
- The exact component hierarchy for each screen (page component → section components → shared components)
- Which existing components, hooks, or layout wrappers are reused vs. created new
- Any drawers, modals, or overlays: their trigger, width, content, and close behavior
- State management: which state lives at which component level, what goes to context or store

### Step 4 — Resolve State and Data Fetching

Determine:
- What state each component owns (local, lifted, context, store)
- Which API endpoints are called, when (on mount, on user action, on tab switch, polling)
- Which existing hook or data-fetch utility is used (e.g. `useTableList`, React Query, `onFetch` directly)
- Cache invalidation / refetch strategy after mutations

If the backend units are available: verify the API contracts align. If a field name, response shape, or URL differs from what was assumed, flag it now and record it in the unit as a `Backend dep` contract note.

### Step 5 — Resolve Validation, Loading, Error, and Empty States

For every flow in the product plan:

| State | What the user sees |
|-------|--------------------|
| Loading | Spinner, skeleton, or disabled state — where exactly? |
| Empty | What is shown when there is no data yet? |
| Validation error | Inline field error, toast, or modal? Which fields? |
| Network / server error | Toast, inline message, or retry button? Any error boundaries? |
| Blocked action (e.g. delete blocked by rule) | Where is the block reason shown — toast, inline message under button? |
| Success | Toast, redirect, in-place update, or drawer close? |

Match existing patterns from the reference screen identified in Step 2. Do not over-specify states the product plan already answered clearly — "matches existing pattern in `<file>`" is a complete answer.

### Step 6 — Resolve API Contract Alignment (if backend is in scope)

Read each backend unit's `Exposes contract` field. For each contract this frontend will consume:
- Confirm field names, types, and structure match what the frontend expects
- Confirm the base server constant (`SERVER.JARVIS`, `SERVER.FLEET`, etc.)
- Confirm auth headers (inherited from the API client, or must be set explicitly?)
- Confirm error status codes the frontend must handle (400 for validation, 403 for permission, etc.)

If a mismatch is found: record it as a note in the relevant FE unit — `Backend dep: <BE-ID> — contract mismatch: <description>`. The assembly step treats this as a dependency AND a flag for the developer to resolve with the backend author before implementation.

If no backend is in scope: name the existing endpoints consumed and confirm their contract has not changed since the last release.

### Step 7 — Output Implementation Units

Produce an ordered list of self-contained implementation units. Order by natural dependency (API client before the component that calls it; route registration last).

Format each unit as:

```
Unit FE-01: <short title>
  What: <specific description — what screen, component, or module is written; what pattern it follows; which existing file it mirrors>
  Files: <repo-relative paths — be specific, never leave this empty>
  Depends on: <unit IDs, or "—" if none>
  Backend dep: <backend unit ID whose contract this consumes, or "—">
  States: <loading / empty / error / blocked / success — note only non-obvious handling and the component that shows it>
  Notes: <convention to carry into the task: exact class names, color tokens, hook names, import paths>
```

Unit types to recognize:
- Route / page — one per screen; includes permission registration note if needed
- Tab container — the parent component managing tab state and layout
- Tab component — one per tab if each tab has independent data fetching and state
- Drawer / modal — separate unit when the drawer has its own API calls
- API client module — the fetch/mutation functions; separate from the component that calls them
- Shared component — extracted only if used by more than one unit
- Route registration — `routerUtils.js` / `router.js` changes to add the new page

**Backend unit dependencies must be listed.** If this frontend unit consumes a contract defined by a backend unit, name the backend unit ID in `Backend dep`. The assembly step uses this to encode the `depends_on` edge in the task DAG.

**Include the DB/permission registration step** as a unit or a note. In repos with runtime permission systems (e.g. hawkeye), the page registration is a required post-deploy step — call it out explicitly in the unit that registers the route, or as its own unit if it requires a management command.

## 5. Files Read

- `config/repositories.json` — to resolve repo `id`, `path`, and `base_branch`
- `repo-context/<id>/context.md` (if present)
- `repo-context/<id>/structure.json` (if present)
- `repo-context/<id>/patterns.json` (if present)
- `repo-context/<id>/conventions.md` (if present)
- `repo-context/<id>/testing.md` (if present)
- 2–3 representative source files from `workspace/<id>/`: an existing screen most similar to the new feature + the router/permission registration file

## 6. Files Written

- `$AI_ORCH_PLAN_DIR/design-mockup.html` — static HTML mockup generated in Step 2.5 for design approval.
- `$AI_ORCH_PLAN_DIR/log.md` — updated after every user answer during Steps 2–6 (see Log Maintenance below).
- `$AI_ORCH_PLAN_DIR/partial.json` — written once, silently, after Step 7 units are produced.

## 6a. Log Maintenance

**Before sending the design question cluster in Step 2** — list every question being asked in **Still to answer**, write `log.md` atomically, then send the questions:
```
- **<Category label>**: <the question, in one plain sentence>
```

**Before presenting the design proposal in Step 2.5** — add the design approval question to **Still to answer**, write `log.md`, then display the design proposal and mockup path:
```
- **Design approval**: Does this layout and design direction match your vision?
```

**After every user answer during Steps 2, 2.5, and 3–6** (routing questions, design approval, state decisions), update `log.md` atomically:

1. Append a new Q&A block at the bottom of the **Conversation so far** section:
   ```
   **Q<N> · <short label — e.g. "Page placement", "Design reference", "Tab state">**
   You were asked: <the question, one plain sentence>
   You said: <the user's answer — 1–3 sentences capturing the substance>
   ```
   Only log real decisions. Do not log repo orientation output.

2. Rewrite the **Where we are** section:
   - Under **What we agreed to build**: update with UI structure confirmed (screens, placement, routing approach).
   - Under **How we'll approach it**: add specific frontend decisions (e.g. "right drawer at 600px, AntD Tabs, matches hawkeye utility tab pattern at `src/…`").
   - Under **Key constraints**: add any frontend-specific constraints (design system, routing constraints, permission model).
   - Update **Still to answer** — remove answered questions, add any new open items.

**After the design mockup is approved (Step 2.5 Step 4)**: add a log entry:
```
**Q<N> · Design approval**
You were asked: Does this layout and design direction match your vision?
You said: <their feedback or approval — paraphrase faithfully>
```

**After Step 7**, silently write both `partial.json` and `partial.md`:
- Read the existing `partial.json`, update `resumed_phase` to `6`, set `frontend_units` to the list of units, update `saved_at` and `notes: "auto-saved after frontend design"`. Write all other fields unchanged.
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
| 5 · Frontend Design | ✓ Done |
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

<bullet per repo>

---

## Backend design

### BE-01 · <unit title>

<description, files, contract>

---

## Frontend design

<For each unit: heading + 2–3 sentences on what it does, files it touches, backend unit it depends on.>

### FE-01 · <unit title>

<description, files, backend dep>

### FE-02 · <unit title>

<description, files, backend dep>

---

> ⚠ Draft — `plan.json` not yet written. Resume: `/create-plan <plan_id>`
MD
mv "$PLAN_DIR/partial.md.tmp" "$PLAN_DIR/partial.md"
```
Do not print anything to the user when writing these files.

## 7. State Changes

`partial.json` updated with frontend units after Step 7. Design mockup HTML written to plan directory.

## 8. Failure Handling

- If `conventions.md` is missing: note this in the units' Notes field. Do not guess at design system usage or component patterns — ask the user which existing screen to match.
- If no design reference is provided (no Figma, no screenshot, no repo file): do not proceed to Step 2.5. Block and ask the user to provide one. If they cannot, ask them to open the app and name the closest screen by URL or menu path.
- If the backend API contract is unknown (no backend units, and no existing endpoint to read): mark those units with `Backend dep: TBD — contract must be agreed before implementation` and flag this as a blocker in the plan notes.
- If the repo has no context files: orient by reading `workspace/<id>/` directly. State what you found, suggest `/repo-context <id>`, and continue.
- If the user answers "it's in the product plan" to a mandatory question: acknowledge, but confirm you have the specific repo-level detail (exact dashboard uri, exact sidebar parent_uri, exact reference file path). Do not accept "there's a list view" as a complete answer to "which existing screen should this match."

## 9. Output

An ordered list of frontend implementation units (FE-01, FE-02, …), each with: title, specific description of what code it writes, files_touched, intra-repo and backend dependencies, state handling notes, and conventions. Returned to `/create-plan` for Step 2f assembly.

## 10. Rules and Constraints

- **Step 2 is mandatory** — never skip it, never shortcut it with assumptions. The product plan answers "what screens exist"; this step answers "exactly where in the app they live and what pattern they follow."
- **Step 2.5 is mandatory** — never skip the design synthesis and approval gate. Do not draft implementation units until the design direction is explicitly approved. If no design reference was provided (no Figma, no screenshot, no repo file), block and ask before continuing.
- **Category B has three modes** — detect which applies (Figma, screenshot, repo reference) and ask only the mode-specific questions. Never ask all three sets.
- Never ask a question whose exact answer can be read directly from the product plan AND confirmed in the repo code. But a product plan mention of a UI concept is NOT confirmation of the page placement, dashboard, role, or routing approach — always ask for these specifics.
- Never invoked directly — always through `/create-plan` Step 2e.
- Do not write any plan files or feature code.
- Group questions into 1–2 messages; ask at most 10 questions total, prioritizing those whose answer most changes the component structure or routing approach.
- `files_touched` must never be empty — use the most specific glob available (`src/pages/<feature>/**`).
- Backend contract alignment must be checked explicitly when backend units are in scope — a mismatch here is cheaper to catch than after implementation.
- DB/permission registration steps must appear as a unit or explicit note — they are required for the feature to be visible to users and are frequently forgotten.
