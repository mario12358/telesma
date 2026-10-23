# Telesma Instructions — Clarification Phase

You are working in the clarification phase of a Telesma project (generating the spec index, the questions and the plan).
References to sections 0+ describe the later implementation phase — its instructions are loaded separately.

## -1. Clarification phase (if `Clarified: no` in telesma/config.md)

This phase runs ONLY when telesma/config.md says `Clarified: no`. If it says `Clarified: yes` — skip this section and go to section 0.

### Step 1: Analysing the documentation and indexing

1. Read ALL files in the `telesma/spec/` directory (use the Read tool for each file on the list given in the startup prompt)
2. Understand: the project's goal, functional and non-functional requirements, architecture, constraints, acceptance criteria
3. Note: ambiguities, missing information, contradictions, assumptions that need confirmation
4. **Generate `telesma/state/SPEC_INDEX.md`** — a two-level documentation index:

For EACH file in telesma/spec/ record:
- The file name and its line count
- 1-2 sentences describing its content
- **A sections table** with exact line numbers (from-to), the section name and a short description (5-15 words)
- A list of keywords (5-10 terms)

In addition, give a **documentation quality assessment** (section `## Documentation quality` in telesma/state/SPEC_INDEX.md):
- **Completeness** (0-100%) — assess coverage: functional requirements, non-functional ones (performance, security, SLA), external integrations, data model, acceptance criteria, error handling, deployment, tests
- **Unambiguity** (high/medium/low) — how many places leave room for interpretation
- **Consistency** (high/medium/low) — whether the documents contradict each other
- **Project size** (small/medium/large) — number of modules, integrations, domain complexity
- **Topic gaps** — a concrete list of areas described poorly or not at all
- **Recommendation** — one sentence: is the spec enough, or is it worth completing it first

This assessment DRIVES the number of questions in step 2 (see the adaptive criteria).

Rules for building the index:
- Determine sections by markdown headings (##, ###) or by logical breaks in the text
- If a document has no headings — split it into blocks of ~100 lines with a description of their content
- Line numbers MUST be exact (verify them while generating)
- **The `Anchor` column** = the exact text of the heading/first line opening the section (copied
  1:1 from the file). It is a safeguard against line ranges silently drifting: procedure 0.1 compares
  the start of the fetched fragment with the anchor and, on a mismatch, fixes the index itself with Grep
- A section description must be concrete: "user CRUD, roles, profile" — not "information about users"
- At the end: update the statistics (number of files, total size)

Example entry in telesma/state/SPEC_INDEX.md:
```
### api-spec.md (2450 lines)
Full REST API specification of an e-commerce system describing endpoints, data models and error codes.

#### Sections:
| Lines | Section | Anchor | Description |
|-------|--------|---------|------|
| 1-45 | Introduction | # API Specification v2 | API conventions, versioning, response format |
| 46-180 | Auth module | ## Authorization and authentication | Registration, login, JWT, refresh token, roles |
| 181-340 | Users module | ## User management | User CRUD, profile, password change |
| 341-520 | Orders module | ## Orders | Creating orders, statuses, history, cancellation |

#### Keywords: REST, endpoint, auth, JWT, user, order, CRUD, validation
```

**UX/UI guidelines (`telesma/spec/ux_ui/`)**

If the `telesma/spec/ux_ui/` directory exists with files (`.css`, `.html`, `.jsx`, `.tsx`, `.png`, `.svg` etc.) — create a SEPARATE section `## UX/UI guidelines` in telesma/state/SPEC_INDEX.md. These are **design prototypes/reference**, not a text spec — Claude reads them on tasks tagged `(ui-*: ...)` (section 0.4).

For each file in `telesma/spec/ux_ui/` record:
- The relative path (e.g. `telesma/spec/ux_ui/screens-b1-b2.jsx`) and the line count
- **Type** — one of: `tokens` (CSS variables, design system), `design-system` (a static DS presentation, e.g. HTML), `primitives` (atoms: Button, Avatar, Badge), `domain` (domain components), `polish` (finishing components), `screens` (complete screens), `artboards` (sets of artboards / iterations)
- 1-2 sentences describing its content
- **An elements table** with exact line numbers — ONE row = ONE screen or ONE component. This is key: UI tasks will reference elements by `#ElementName` and Claude must know the line range to load ONLY its own fragment (section 0.4).

Example UX/UI entry:
```
### telesma/spec/ux_ui/components-primitives.jsx (220 lines)
**Type**: primitives
UI atoms used by the screens: SVG icons, avatars, badges, sparkle.

#### Elements:
| Lines | Element | Description |
|-------|---------|------|
| 4-9 | Sparkle | Animated SVG spark (12px), AI mode |
| 11-51 | Icon | Stroke icon library (30+ paths: chevron, file, search, ...) |
| 54-70 | Avatar | Circle with initials, deterministic colour from a hash, AI variant |
| 73-130 | Badge | Toned chip (neutral/success/warning/danger/info/accent) |

### telesma/spec/ux_ui/screens-b1-b2.jsx (380 lines)
**Type**: screens
Screens B1 (Project Overview) and B2 (Clarification Loop).

#### Elements:
| Lines | Element | Description |
|-------|---------|------|
| 5-50 | TopBar | Shared header (logo, breadcrumb, search) |
| 52-200 | B1_ProjectOverview | The project's main screen — cards, metrics, action list |
| 202-380 | B2_ClarificationLoop | Clarification loop screen — questions, answers, status |

### telesma/spec/ux_ui/tokens.css (94 lines)
**Type**: tokens
Design tokens: colours, fonts, dark (canonical) + light themes. Copied 1:1 into the project (section 0.4).
```

**Rules for the UX/UI section:**
- Line numbers MUST be exact — UI tasks load the fragment with `Read(file, offset=X, limit=Y)`
- The element name = the identifier used in tags `(ui-screen: file.jsx#ElementName)` — prefer names from the code (e.g. the component name `B1_ProjectOverview`) or the section's first heading/comment
- Do not split artificially — ONE screen in a file = ONE row, even if it is 200 lines long
- Binary files (`.png`, `.jpg`, `.pdf` with mockups) → an entry WITHOUT an elements table, only the path + description

**Link registry (`telesma/spec/ux_ui/LINKS.md`)**

If `telesma/spec/ux_ui/LINKS.md` exists WITHOUT the `TELESMA_UX_LINKS_TEMPLATE` marker in line 1 — it is a registry of mockups kept outside the repo (e.g. Claude Design canvases). Index every `## <id> — Title` entry with a `- link:` field in the same `## UX/UI guidelines` section:

1. **Fetch the link's content** (WebFetch) — ONCE per entry. Write the content description (screens, elements, states) from the FETCHED content, not only from the entry's `scope` field — the plan generator tags tasks based on this description
2. **Add a row** to the links table (format in SPEC_INDEX_TEMPLATE): `| Id | Type | Link | Description |` — copy Id and Link EXACTLY from LINKS.md (deterministic change detection by telesma.sh compares these values)
3. **Unreachable link** (fetch error — usually an artifact that was not shared) → an entry with the description "(link unavailable — needs to be shared)" + a question in QUESTIONS.md; do NOT block indexing of the remaining entries

Tasks in PLAN.md tag such mockups with the same grammar as file mockups — the file is the registry: `(ui-screen: telesma/spec/ux_ui/LINKS.md#<id>)`. Resolving the tag: links table row → WebFetch (section 0.4). Link mockups and file mockups are equal sources when generating UI tasks.

**Flows (flow files → mapping onto e2e + recordings)**

If the `## Visual artifacts` section of `telesma/config.md` has `Recordings: yes` AND the listed `Flow files` exist in `telesma/spec/` (typically `telesma/spec/APP_FLOW.md`) — create a SEPARATE section `## Flows` in `telesma/state/SPEC_INDEX.md`. Flow files describe user flows step by step; each `## Step N — Title` is **a separate e2e scenario + one video recording (1:1)** (section 0.5).

For each flow file record:
- The relative path and the line count
- **Type**: `flow`
- 1-2 sentences of description
- **A steps table** — ONE row = ONE `## Step N` in the file (line range + ID + title + actors + 1 sentence of essence)

Example Flows entry:
```
### telesma/spec/APP_FLOW.md (313 lines)
**Type**: flow
Main MVP1 user flows — from registration to exporting the specification.

#### Steps:
| Lines | ID | Title | Actors | Main actions |
|-------|----|-------|---------|--------------|
| 11-30 | step-1 | Registration and project creation | User, System | Creating an account, email verification, creating a project |
| 33-50 | step-2 | Multi-upload of the specification | User, AI pipeline | Drag&drop, conversion, streaming requirement extraction |
| 53-67 | step-3 | First requirements list screen | User | Filtering, sorting, traceability viewer |
```

**Rules for the Flows section:**
- The step ID is always in the form `step-<N>` (lowercase, with a hyphen). It is the identifier after `#` in tags `(flow: <file>#step-<N>)`.
- The line range MUST be exact — e2e tasks load the fragment with `Read(offset, limit)`
- Title = the text after " — " in the Step heading, shortened to max ~80 characters
- Actors = from the Step's prose, comma-separated
- Main actions = ONE sentence, the essence, without UI details

**When NOT to create the `## Flows` section in SPEC_INDEX:**
- `Recordings: no` in the config
- the `Flow files` do not exist / are empty
- The flow file has the `TELESMA_APP_FLOW_TEMPLATE` marker in its first line (= an unfilled template)
- The flow file contains no `## Step N — ...` headings

In each of these situations Telesma will detect the gap in section 0.5 and write an info line to REPORT.md instead of blocking — carry on normally.

### Step 2: Generating questions, assumptions and contradictions

Check whether `telesma/state/QUESTIONS.md` exists:
- **It does not exist** → generate a new file from the analysis of the documentation
- **It exists and its state = in progress** → go to step 3 (resume)
- **It exists and its state = done** → go to step 4

**HARD RULE — statuses at generation time.** Every new item gets a "waiting for the user" status:
contradictions `⚠️`, assumptions `🔵`, questions `❓`. **NEVER generate the `✅` status** — ✅ is set
only by the bash script after the user's actual decision. An item generated with ✅ is treated by the
script as resolved and **the user will never see it** — the plan will be built from your proposals
without their approval. Leave the `Answer`/`Resolution` field empty.

The file `telesma/state/QUESTIONS.md` has **three sections** (the order is deliberate — the user resolves from the top):

1. **Contradictions** — errors in the spec to be fixed **before** we start answering questions
2. **Assumptions** — things decided without asking (a spot check; reduces the number of questions)
3. **Questions** — only what truly cannot reasonably be assumed or inferred from the spec

#### Contradictions

Generate the section `## Contradictions in the documentation` with every contradiction detected:
- Two places in the spec contradict each other (e.g. file A: "REST API", file B: "gRPC")
- A functional requirement clashes with a non-functional one (e.g. "real-time" vs "batch every 15 min")
- Numbers/values differ between documents

Format:
```markdown
### S1: [short description of the contradiction]
- **Source A**: file.md:lines — "[quote or paraphrase]"
- **Source B**: file.md:lines — "[quote or paraphrase]"
- **Proposed resolution**: [which one is right and why, or a proposed compromise]
- **Resolution**:
- **Status**: ⚠️
```

If there are no contradictions → leave the section empty with the comment `<!-- No contradictions detected -->`.

#### Assumptions

Generate the section `## Assumptions` with the things you decide **yourself** (instead of asking):
- Industry standards (e.g. password hashing with bcrypt, not MD5)
- Stack conventions (e.g. snake_case table names in Postgres)
- Reasonable interpretations of the spec (e.g. "the user can log in" → also needs a logout endpoint)
- Default values for non-functional aspects (e.g. a 30s timeout if none is given)

The goal is **to reduce the number of questions** — ask only about what is non-obvious; list the rest as assumptions for a spot check.

Format:
```markdown
### A1: [the assumption in one sentence]
- **Category**: [architecture | technology | ...]
- **Source**: [file.md:lines | industry standard | stack convention]
- **Rationale**: [why it is reasonable]
- **Status**: 🔵
```

Assumption statuses:
- 🔵 — to be verified (default)
- ✅ — accepted by the user
- ❌ — rejected → **move it to the Questions section** as a regular question with the proposed answer "no" and room for an alternative

**Assumptions from `telesma/spec/ux_ui/` (automatic)**

If `telesma/spec/ux_ui/` exists with files, create spot-check assumptions that follow from what you see in the mockups:
- **Theme** — e.g. if `tokens.css` defines `theme-dark` and `theme-light` with the comment "dark canonical" → assumption: "The default theme is dark; light is available as a user preference"
- **Fonts** — if the tokens use specific fonts (IBM Plex, JetBrains Mono etc.) → assumption: "Fonts bundled locally (not Google Fonts) — removes the dependency on an external CDN"
- **Component stack** — if the mockups are JSX with `var(--*)` from tokens.css → assumption: "Styling through CSS variables from `tokens.css` (copied 1:1); production components rewritten into a modular stack, NOT copied 1:1 from the prototype"
- **Pixel-perfect vs adaptive** — if concrete dimensions are visible (e.g. a 44px topbar, a 22px avatar) → assumption: "Keep the dimensions from the mockups (pixel-aware), responsiveness only where the mockup defines no breakpoints"

These assumptions have the 🔵 status — the user spot-checks them, rejected ones move to Questions.

**Multi-client detection (automatic architectural assumption)**

When `telesma/spec/` implies **≥2 clients** (web + mobile, web + CLI, etc.) — detected by keywords: web/frontend/SPA, mobile/iOS/Android/React Native, desktop, CLI — create a MANDATORY assumption:

```markdown
### A[n]: Multi-client architecture — BFF with dedicated controllers + a branch per client
- **Category**: architecture
- **Source**: [spec sections describing the clients, e.g. ui-spec.md:1-20, mobile-spec.md:1-40]
- **Rationale**: Shared core (entities, services, migrations) + separate `/api/<client>/*` controllers per platform. Mono-repo, long-lived branches per client (`web`, `mobile`) integrated through `develop`. Allows genuinely parallel work, minimises merge conflicts, clean responsibilities per track.
- **Status**: 🔵
```

If the user rejects it (❌) — move it to Questions with alternatives: (a) a monolith with one `/api/*` for all clients, (b) separate backends per client, (c) microservices, (d) other.

With **≥3 clients** do NOT create this assumption — instead ask a question in the Questions section about the phase naming convention (the `M`/`I`/`A`/`D` suffixes are readable up to 2 clients, beyond that they need the user's decision).

#### Questions

When generating questions:
1. Create the file `telesma/state/QUESTIONS.md` with the questions grouped into categories:
   - **architecture** — system structure, patterns, component split
   - **requirements** — missing/unclear functional requirements
   - **technology** — technology choices, versions, dependencies
   - **priorities** — what is critical, what is optional, MVP vs full scope
   - **constraints** — limits, budget, time, external integrations
2. Every question MUST contain a proposed answer (your best proposal based on the docs)
3. Questions should be concrete and decision-oriented — not vague
4. The number of questions is **adaptive** — it depends on the project's size and the documentation's quality, not on a fixed limit:
   - Small project + good documentation (consistent, complete, unambiguous) → 3-7 questions
   - Medium project or average documentation → 8-15 questions
   - Large project or poor documentation (gaps, contradictions, ambiguities) → 15-30+ questions
   - Size criteria: number of modules/components, domain complexity, number of integrations
   - Spec quality criteria: requirements coverage, unambiguity, absence of contradictions, presence of acceptance criteria
   - Rule: every question MUST be necessary for building a good plan — do not ask about things clearly described in the spec or about details that can reasonably be assumed

Question format:
```markdown
### Q1: [a concrete question]
- **Category**: [category]
- **Source**: [file.md:lines | file.md (section X) | none — gap in the spec]
- **Proposed answer**: [your proposal based on the docs + rationale]
- **Answer**: 
- **Status**: ❓
```

Rules for the **Source** field:
- It points at the place in the documentation that produced the question — an unclear fragment, a contradiction, or an explicit gap
- Format `file.md:120-135` (lines) or `file.md (Auth module)` (section) — lets the user verify quickly
- If the question arose from **missing** information → write `none — [the specific gap]` (e.g. `none — validation error handling is not described`)
- If the question covers several places → list at most the 2-3 most important ones

5. Update the Status section: total number of questions, assumptions, contradictions, analysed documents

### Step 3: Asking the questions (handled by the bash script)

This step is carried out automatically by `telesma.sh` — the script shows the questions in the terminal and collects the user's answers. Claude does NOT ask the questions directly.

After the Q&A, telesma/state/QUESTIONS.md will contain the user's answers (status ✅ on every question).

### Step 4: Generating telesma/state/PLAN.md

After ALL questions are answered and the contradictions and assumptions are resolved:

1. Check that every contradiction has a filled-in **Resolution** (status ✅). If not → TELESMA BLOCKED.
2. Check the assumptions: treat accepted ones (✅) as agreed; rejected ones (❌) should already have been moved to questions and have an answer.
3. Change the state in telesma/state/QUESTIONS.md to `done`
4. Generate telesma/state/PLAN.md from four sources of knowledge:
   - The documentation in `telesma/spec/` (specification, requirements, diagrams)
   - Contradiction resolutions from `telesma/state/QUESTIONS.md`
   - Accepted assumptions from `telesma/state/QUESTIONS.md`
   - Answers to the questions from `telesma/state/QUESTIONS.md`
   - The `PLAN_TEMPLATE.md` template (structure: phases, dependencies, tests)
5. telesma/state/PLAN.md should contain:
   - Concrete, atomic tasks (not "build the backend", but "create the User model with fields X, Y, Z")
   - Logical phases (setup → core → features → polish)
   - **Task 1.1 = "Architecture skeleton and conventions"** (always the first implementation task):
     it sets the module map (directory → responsibility), the API response/error format, naming
     conventions and the layering pattern — the result recorded in PROJECT_CONTEXT.md (sections Architecture +
     Key decisions). Without it, cross-cutting things are decided implicitly by the first task that
     touches them, and later ones may decide differently (especially after auto-compact)
   - Dependencies between tasks `(requires: X.X)`
   - **References to the documentation `(spec: file.md)`** — which documents are the source of requirements for the task
   - **Technology tags `(tech: tag1, tag2)`** — match them to each task based on `GUIDELINES_INDEX` (in the prompt) and the task's context (backend/frontend/db/etc.). Use only tags from the index. Purely configuration/design tasks may have no `(tech: ...)` — then only `general.md` gets loaded.
   - **Acceptance criteria for non-trivial tasks** (heuristic: a task tagged `(spec: ...)`
     or `(ui-screen: ...)`): 2-4 points indented under the task, EXTRACTED FROM THE SPEC (not invented),
     format `  - AC: <verifiable criterion>`. They are an objective reference point for the loop — the test
     is to cover the criteria, not the implementation. Simple tasks (setup, migration) without criteria,
     so the plan does not bloat.
     A task that adds a MECHANISM (a service, endpoint, worker, screen, rule) has among its criteria
     `  - AC: entry — <what triggers it>` (a user step, an event, a schedule) — also
     when the spec only says WHAT is to happen. If you cannot name the entry → the plan is missing
     the task that builds it
   - A test after every implementation (unit/integration as an annotation `- [ ] Test: ...`)
   - **An e2e task at the end of every phase with UI** (see below)
   - **Tracker anchors** — when `telesma/config.md` → `## Integrations` has `Tracker: specky`: before
     laying out tasks, fetch the project's requirements (`get_requirements` on `Tracker project`, when in
     doubt `get_plan_prompt`) and under EVERY task that implements a requirement add the line
     `  - Specky: (req: <requirement_id> v<n> @<7 characters of content_hash>)` (one per requirement) and,
     when the requirement has criteria, `  - Specky criteria: (crit: <criterion_id>) …`. Specky criteria
     are ready-made `- AC:` — do not invent your own next to them. Every requirement → a row in the map
     `telesma/state/SPECKY.md` (requirement → tasks). A requirement without a task = a hole in the plan, like a spec
     section without coverage. With `Repository: github`, task 1.1 also covers adapting
     `.github/workflows/specky-ci.yml` to the stack (section 18.5 of the instructions)
   - **Attack surface map** — when `telesma/config.md` → `## Checks` has `Enabled: yes`
     and an `### intent` subsection: create `telesma/state/SECURITY_MAP.md` following
     `telesma/checks/intent/MAP_TEMPLATE.md` with the sections `## Roles` (actors from the spec; the column
     "Guard in code" is filled in by the task that builds authentication) and `## Ownership boundaries`
     (who sees and changes whose resource — another organisation, another patient, someone else's project — and what a
     violation returns). Routes are added during implementation; the checks verify them against this map
   - A realistic order
6. **Spec coverage (a mandatory step after laying out the tasks):** go through the section tables in telesma/state/SPEC_INDEX.md
   and for EACH section list the tasks that implement it — as a `## Spec coverage` section at the end of
   telesma/state/PLAN.md:
   ```
   ## Spec coverage
   | File | Section | Tasks |
   |------|--------|---------|
   | api-spec.md | Auth module | 2.1, 2.2, 2.5 |
   | api-spec.md | Orders module | out of scope — MVP without orders (answer Q4) |
   ```
   A section with no tasks and no "out of scope — reason" justification = a hole in the plan: go back and add
   tasks. In an autonomous loop this type of error only surfaces at the end of the project.
7. **Plan self-review (the last step before finishing):** read the generated plan with fresh
   eyes against the checklist: task atomicity / a feasible order / dependencies exist and have no cycles /
   a test with every implementation / e2e at the end of every phase with UI / coverage of the gaps from the spec quality
   assessment (the `Topic gaps` section in SPEC_INDEX — a significant gap → a task or a deliberate omission
   in Spec coverage) / **no task line exceeds 400 characters** (rationale and context
   belong in telesma/state/PROJECT_CONTEXT.md, criteria on separate `- AC:` lines — the whole plan goes
   into the prompt of every session). Fix any gaps found right away.

**Generating tasks from `telesma/spec/ux_ui/` (mockups → production components/screens)**

If `telesma/spec/ux_ui/` contains files, the UX/UI section of telesma/state/SPEC_INDEX.md is the source for **three types of tasks** (usually laid out as one "Design system / UI shell" phase before the feature phases):

1. **Design tokens setup** (if a `tokens` file exists in UX/UI):
   - One task: copies `telesma/spec/ux_ui/tokens.css` 1:1 to `src/styles/tokens.css` (or equivalent), wires it into the global style
   - Tag: `(ui-tokens: telesma/spec/ux_ui/tokens.css)` + `(tech: react, typescript)` (or `react-native`)
   - No `(requires: ...)` — it is the foundation

2. **Components setup (primitives + domain)** — one task = one logical group of components (3-7 components), so the context per task is coherent:
   - Tag: `(ui-component: telesma/spec/ux_ui/components-primitives.jsx#Icon,Avatar,Badge,Sparkle)` — a list of identifiers after `#`, comma-separated
   - `(requires: <tokens-task>)` — components depend on the tokens
   - The task description names the concrete components: "Implement Icon, Avatar, Badge, Sparkle (primitives) — in `src/components/`. Each in its own TSX file, use `var(--*)` from tokens.css."

3. **Per screen — ONE task = ONE screen**:
   - Tag: `(ui-screen: telesma/spec/ux_ui/screens-b1-b2.jsx#B1_ProjectOverview)` — ONE identifier after `#`
   - `(requires: ...)` — all component setup tasks whose components the screen uses (Claude sees that from the mockup)
   - **The task description MUST list the components the screen uses**: "Screen B1 Project Overview. Uses: TopBar, Avatar, Badge, ProjectCard, KeyMetrics" — this lets Claude load only `src/components/<Name>.tsx` during implementation, WITHOUT going back to the UX/UI prototype for the component API (they already exist in production code)
   - `(spec: ...)` — additionally the spec documents describing the screen's data/flow (if any)

**Optimal context per screen task** (important — so Claude does not have to redo things):
- The mockup loads ONLY its own fragment: `Read(file, offset=X, limit=Y)` with the line range from SPEC_INDEX (1 screen ≠ a whole file with 5 screens)
- Claude learns the primitives' API by reading `src/components/<Name>.tsx` (already implemented in the setup) — it does not go back to the prototype in `telesma/spec/ux_ui/`
- The text spec (if the task has `(spec: ...)`) — through SPEC_INDEX + offset/limit as usual

**Multi-client and UI**: if the multi-client assumption A is active, each screen lands in the phase of its platform:
- Web screen (`(ui-screen: ...)` + `(tech: react, typescript)`) → phase `N` (web)
- Mobile screen (`(ui-screen: ...)` + `(tech: react-native, typescript)`) → phase `NM` (mobile)
- Tokens and primitives may be shared (a shared Setup phase) or per platform — Claude decides based on whether the `telesma/spec/ux_ui/` mockups address both platforms or only one.

Example Setup phase with UX/UI:
```
### Phase 0: Design system / UI shell
- [ ] Task 0.1: Copy the design tokens (ui-tokens: telesma/spec/ux_ui/tokens.css) (tech: react, typescript)
- [ ] Task 0.2: Implement the primitives — Icon, Avatar, Badge, Sparkle (requires: 0.1) (ui-component: telesma/spec/ux_ui/components-primitives.jsx#Icon,Avatar,Badge,Sparkle) (tech: react, typescript)
- [ ] Test: 0.2 — render of each primitive + snapshot
- [ ] Task 0.3: Implement the domain components — ProjectCard, KeyMetrics, ChatBubble (requires: 0.2) (ui-component: telesma/spec/ux_ui/components-domain.jsx#ProjectCard,KeyMetrics,ChatBubble) (tech: react, typescript)
- [ ] Test: 0.3 — render + interactions

### Phase 1: Project Overview
- [ ] Task 1.1: Screen B1 Project Overview. Uses: TopBar, Avatar, Badge, ProjectCard, KeyMetrics (requires: 0.2, 0.3) (ui-screen: telesma/spec/ux_ui/screens-b1-b2.jsx#B1_ProjectOverview) (spec: requirements.md) (tech: react, typescript)
- [ ] Test: 1.1 — the screen renders with data from a fixture
- [ ] Task 1.2: E2e test — navigation Project Overview → Project Detail (requires: 1.1) (spec: user-flows.md) (tech: playwright, typescript)
```

**E2e tasks at the end of a phase (mandatory for phases with UI)**

If a phase contains at least one task with a UI tag (`react`, `react-native`, `vue`, `angular`, `svelte`), **the last task of the phase must be a full e2e task** (not a `Test:` annotation) covering all UI scenarios of that phase:

- An identifier like any other task (`Task N.X`, where X = the last number in the phase)
- `(requires: N.1, N.2, ...)` — a list of ALL previous tasks of the phase (because e2e needs a working full stack)
- `(spec: ...)` — documents describing the user flow (not just one endpoint)
- `(tech: ...)` chosen per platform:
  - Web → `(tech: playwright, typescript)`
  - Mobile React Native → `(tech: detox, typescript)` or alternatively `maestro` (ask in the clarification phase if it is not known)
- The description names concrete scenarios (e.g. "registration → email verification → login → logout"), not a generic "e2e tests"

Phases without UI (pure backend, migrations, infrastructure) **do not get** an e2e task — a `Test:` annotation after each task plus the full suite after the phase are enough.

Example tasks with tags:
```
- [ ] Task 2.1: POST /api/auth/register endpoint with email validation (requires: 1.1) (spec: api-spec.md, auth-requirements.md) (tech: nodejs, typescript)
- [ ] Task 3.2: LoginForm component with form validation (requires: 2.1) (spec: ui-spec.md) (tech: react, typescript)
- [ ] Task 3.3: E2e test — registration, login, logout (requires: 3.1, 3.2) (spec: ui-spec.md, user-flows.md) (tech: playwright, typescript)
- [ ] Task 4.1: Migration of the users schema (requires: 1.1) (spec: db-schema.md) (tech: sql)
```

**Multi-client — phase split for BFF + branches per client**

If the multi-client assumption A was accepted (✅) or the user explicitly confirmed it in Questions, generate the plan following the pattern below. Otherwise — standard numbering `Phase 1, 2, 3, ...`.

- **One client** (web only or mobile only): standard numbering. Each phase is an end-to-end module (core + controller + UI). No suffixes.

- **Two clients** (web + mobile, the typical case): **two phases** for each module:
  - `Phase N` — **Core + Web**: entities, repo, domain services, the `/api/web/*` controller, the web UI. Core goes here because web usually leads.
  - `Phase NM` — **Mobile**: the `/api/mobile/*` controller + React Native screen(s). Tasks have `(requires: N.X)` pointing at services from phase N — Telesma will block (TELESMA BLOCKED) until the core lands in develop and the mobile branch rebases. Task numbering in a suffixed phase: `NM.1`, `NM.2`.
  - Exception: if the module is mobile-only (barcode scanning, push-only notifications, sensors) — the core goes into phase `N` combined with mobile, and `NW` covers web (the reverse convention).

- **≥3 clients**: ask a question about the naming convention (do not create an assumption) — the suffixes can be `M`/`I`/`A`/`D` or something else, the user's decision.

**Rules per mobile/additional client track:**
- Tasks touch ONLY files specific to their track (`src/controllers/mobile/`, `mobile-app/`, `ios/`, `android/`) — no files shared with another track. This guarantees no merge conflicts between the `web` and `mobile` branches.
- Dependencies on services from the core phase are expressed with `(requires: N.X)` — cross-phase numbering works normally.
- **E2E as a separate task at the end of the phase**: Playwright for web (`tech: playwright, typescript`), Detox/Maestro for mobile (`tech: detox, typescript`). `(requires: ...)` covers ALL previous tasks of the phase.
- `(tech: ...)` tags per platform: `react, typescript` for web; `react-native, typescript` for mobile.

Example (Auth module, two clients):
```
### Phase 1: Auth module — Core + Web
- [ ] Task 1.1: users migration (spec: db-schema.md) (tech: sql)
- [ ] Task 1.2: User entity + repo (requires: 1.1) (spec: domain.md) (tech: python)
- [ ] Task 1.3: AuthService (hash, JWT) (requires: 1.2) (spec: domain.md) (tech: python)
- [ ] Task 1.4: Controller /api/web/auth/* (requires: 1.3) (spec: api-web.md) (tech: python)
- [ ] Task 1.5: LoginForm + RegisterForm (requires: 1.4) (spec: ui-spec.md) (tech: react, typescript)
- [ ] Task 1.6: E2e test — registration, login, logout (web) (requires: 1.1, 1.2, 1.3, 1.4, 1.5) (spec: ui-spec.md, user-flows.md) (tech: playwright, typescript)

### Phase 1M: Auth module — Mobile
- [ ] Task 1M.1: Controller /api/mobile/auth/* (requires: 1.3) (spec: api-mobile.md) (tech: python)
- [ ] Task 1M.2: LoginScreen + RegisterScreen (requires: 1M.1) (spec: mobile-spec.md) (tech: react-native, typescript)
- [ ] Task 1M.3: E2e test — registration, login, logout (mobile iOS + Android) (requires: 1M.1, 1M.2) (spec: mobile-spec.md, user-flows.md) (tech: detox, typescript)
```

**Phase numbering accepts an optional letter suffix** after the number (`Phase 1M`, `Phase 2I`, `Phase 3A`) and an optional rework suffix `.Z<n>` (`Phase 6.Z1`, `Phase 2M.Z1`). Recognition regex: `^### Phase ([0-9]+[A-Z]?(?:\.Z[0-9]+)?):`. Tasks in a suffixed phase use the same numbering (`1M.1`, `1M.2`, `6.Z1.1`, `6.Z1.2`). Phases `N` and `NM` are siblings (not nested) — both are scanned independently when choosing a task. Rework phases `N.Z<n>` belong to the track of the base phase `N` (selected together with it through `Active phases`).

6. Change in `telesma/config.md`: `Clarified: no` → `Clarified: yes`
7. Message:

```
TELESMA: PLAN GENERATED

The plan is saved in telesma/state/PLAN.md, based on:
- Documentation: [list of files from telesma/spec/]
- Answers to [N] clarifying questions

Review telesma/state/PLAN.md and choose:
1. Approve → Telesma starts the implementation
2. Edit → fix the plan by hand, then run Telesma again
```

8. Wait for the user's decision:
   - **Approve/ok/start/yes** → go to section 0 (start of implementation)
   - **Edit/no/stop** → END the session (the user edits by hand)

---

