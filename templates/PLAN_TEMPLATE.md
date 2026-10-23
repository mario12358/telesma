# telesma/state/PLAN.md - Project task list

## Project information

- **Name**: [project name]
- **Stack**: [technologies]

## Tasks

<!-- A task line is ≤ 400 characters (the telesma.sh validator warns above that). The plan says  -->
<!-- WHAT is to be done; rationale, findings from the work and the "why this way" go to             -->
<!-- telesma/state/REPORT.md (Problem log) or telesma/state/PROJECT_CONTEXT.md (Key decisions).                      -->
<!-- Reason: the plan is read and edited on EVERY task and goes into the prompt in full,            -->
<!-- while those files rotate into the archive. Write acceptance criteria as `- AC:` under          -->
<!-- the task, do not glue them onto its line.                                                       -->
<!--                                                                                                 -->
<!-- Every `- [ ]` item MUST start with the word `Task` or `Test` (a state marker before it         -->
<!-- is OK: `- [ ] ⛔ Task 4.2: …`). An item without that word is invisible to the loop —           -->
<!-- it cannot be selected and does not count toward the phase's progress, yet it looks like        -->
<!-- finished work; the validator warns. Write a note into telesma/state/REPORT.md instead.                  -->
<!-- `⛔` means "waiting for a human" (manual test in production, the owner's decision):            -->
<!-- the task counts toward phase completeness, but the startup hint skips it, so the loop          -->
<!-- does not point every session at the one thing it cannot do itself.                              -->
<!--                                                                                                 -->
<!-- A `### Phase N: … — ✅ completed` header with a `telesma-archived` comment under it is the stub  -->
<!-- of a phase moved to telesma/state/PLAN_ARCHIVE.md by state file rotation. Do not edit it               -->
<!-- by hand — dependencies (requires: X.Y) on the tasks listed there still resolve.                 -->

### Phase 1: Setup

- [ ] Task 1.1: Architecture skeleton and conventions — module map, API error format, naming conventions; result goes to PROJECT_CONTEXT.md
- [ ] Task 1.2: [description]
- [ ] Test: [test for the tasks above]

### Phase 2: [Feature name]

- [ ] Task 2.1: [description] (requires: 1.1, 1.2) (tech: [tag]) (spec: [file.md])
  - AC: [acceptance criterion taken from the spec, verifiable]
  - AC: [second criterion]
- [ ] Test: [test of task 2.1 — covers the AC criteria, not the implementation]
- [ ] Task 2.2: [UI description] (requires: 2.1) (tech: react, typescript)
- [ ] Test: [test of task 2.2]
- [ ] Task 2.3: E2E test — [a concrete user scenario] (requires: 2.1, 2.2) (spec: [file with the flow]) (tech: playwright, typescript)

### Phase 3: [Another feature without UI]

- [ ] Task 3.1: [description] (requires: 2.1) (tech: [tag])
- [ ] Test: [test of task 3.1]

## Spec coverage

<!-- Generated in clarification step 6: every section from SPEC_INDEX → the tasks that implement it, -->
<!-- or "out of scope — reason". A section with no tasks and no reason = a hole in the plan.          -->

| File | Section | Tasks |
|------|---------|-------|
| [file.md] | [section] | [2.1, 2.2 or "out of scope — reason"] |

## Variant: multi-client (BFF + dedicated controllers per platform)

If the project has **≥2 clients** (e.g. web + mobile) and a backend in the BFF model (shared core + separate controllers per client), use phase numbering with a platform suffix. Phases without a suffix = core + the main client (usually web); phases with an `M`/`I`/`A` suffix = an extra track per client.

Example (Auth module, two clients):

```
### Phase 1: Auth module — Core + Web
- [ ] Task 1.1: users migration (tech: sql)
- [ ] Task 1.2: User entity + repo (requires: 1.1) (spec: domain.md) (tech: python)
- [ ] Task 1.3: AuthService: hash, JWT (requires: 1.2) (spec: domain.md) (tech: python)
- [ ] Task 1.4: Controller /api/web/auth/* (requires: 1.3) (spec: api-web.md) (tech: python)
- [ ] Task 1.5: LoginForm + RegisterForm (requires: 1.4) (spec: ui-spec.md) (tech: react, typescript)
- [ ] Task 1.6: E2E test — sign-up, login, logout (web) (requires: 1.1, 1.2, 1.3, 1.4, 1.5) (spec: ui-spec.md, user-flows.md) (tech: playwright, typescript)

### Phase 1M: Auth module — Mobile
- [ ] Task 1M.1: Controller /api/mobile/auth/* (requires: 1.3) (spec: api-mobile.md) (tech: python)
- [ ] Task 1M.2: LoginScreen + RegisterScreen (requires: 1M.1) (spec: mobile-spec.md) (tech: react-native, typescript)
- [ ] Task 1M.3: E2E test — sign-up, login, logout (mobile iOS + Android) (requires: 1M.1, 1M.2) (spec: mobile-spec.md, user-flows.md) (tech: detox, typescript)
```

Configuration in `telesma/config.md`:
- Branch `web`: `Active phases: 1, 2, 3, ...`
- Branch `mobile`: `Active phases: 1M, 2M, 3M, ...`

Cross-branch dependencies (`1M.1 requires: 1.3`) are resolved by merging into `develop` + rebase. Telesma reports `TELESMA BLOCKED` when a service from a core phase does not exist in the code yet — a natural signal to rebase.

## Variant: with `telesma/spec/ux_ui/` (mockups / design tokens / reference components)

If the project has a `telesma/spec/ux_ui/` directory with design (CSS, JSX, HTML), UI tasks use three additional tags (procedure in section 0.4 of the instructions):

- `(ui-tokens: telesma/spec/ux_ui/tokens.css)` — Claude copies the file 1:1 to `src/styles/`
- `(ui-component: telesma/spec/ux_ui/components-primitives.jsx#Icon,Avatar,Badge)` — Claude rewrites the listed components (after `#`, comma-separated) into `src/components/<Name>.tsx`
- `(ui-screen: telesma/spec/ux_ui/screens-b1-b2.jsx#B1_ProjectOverview)` — Claude implements ONE screen (after `#`) using components that already exist in `src/components/`

**Every screen task MUST list the components it uses in its description** ("Uses: TopBar, Avatar, Badge, ProjectCard") — this lets Claude load the API from `src/components/<Name>.tsx` instead of going back to the UX/UI prototype.

Example of a Setup phase + screens:

```
### Phase 0: Design system / UI shell
- [ ] Task 0.1: Copy the design tokens (ui-tokens: telesma/spec/ux_ui/tokens.css) (tech: react, typescript)
- [ ] Task 0.2: Implement primitives — Icon, Avatar, Badge, Sparkle (requires: 0.1) (ui-component: telesma/spec/ux_ui/components-primitives.jsx#Icon,Avatar,Badge,Sparkle) (tech: react, typescript)
- [ ] Test: 0.2 — render of every primitive + snapshot
- [ ] Task 0.3: Implement domain components — ProjectCard, KeyMetrics, ChatBubble (requires: 0.2) (ui-component: telesma/spec/ux_ui/components-domain.jsx#ProjectCard,KeyMetrics,ChatBubble) (tech: react, typescript)
- [ ] Test: 0.3 — render + interactions

### Phase 1: Project Overview
- [ ] Task 1.1: Screen B1 Project Overview. Uses: TopBar, Avatar, Badge, ProjectCard, KeyMetrics (requires: 0.2, 0.3) (ui-screen: telesma/spec/ux_ui/screens-b1-b2.jsx#B1_ProjectOverview) (spec: requirements.md) (tech: react, typescript)
- [ ] Test: 1.1 — the screen renders with fixture data
- [ ] Task 1.2: E2E test — navigation Project Overview → Project Detail (requires: 1.1) (spec: user-flows.md) (tech: playwright, typescript)
```

## Variant: with visual artifacts (screenshots / video recordings)

If the `## Visual artifacts` section in `telesma/config.md` has `Screenshots: yes` or `Recordings: yes`, tasks can use two additional tags (procedure in section 0.5 of the instructions):

- `(screen: <id>)` — after the task's test passes, Telesma takes a screenshot of the screen with that ID and saves it to `telesma/artifacts/screens/<id>.png`. Most often `<id>` is the same as in `ui-screen:` (e.g. `B1_ProjectOverview`).
- `(flow: <file>#step-<N>)` — a tag on the **end-of-phase e2e** task. The e2e test mirrors the flow from `telesma/spec/APP_FLOW.md` Step N and saves the video to `telesma/artifacts/flows/step-N-<slug>.webm`. The tag is mapped to a fragment through `## Flows` in `telesma/state/SPEC_INDEX.md`.

Example of a phase with UI + recordings:

```
### Phase 1: Project Overview (with visual artifacts)
- [ ] Task 1.1: Screen B1 Project Overview. Uses: TopBar, Avatar, Badge, ProjectCard (requires: 0.2, 0.3) (ui-screen: telesma/spec/ux_ui/screens-b1-b2.jsx#B1_ProjectOverview) (screen: B1_ProjectOverview) (spec: requirements.md) (tech: react, typescript)
- [ ] Test: 1.1 — the screen renders with fixture data
- [ ] Task 1.2: E2E test — Step 1 (sign-up → create a project) (requires: 1.1) (flow: telesma/spec/APP_FLOW.md#step-1) (tech: playwright, typescript)
- [ ] Task 1.3: E2E test — Step 2 (upload a specification) (requires: 1.1) (flow: telesma/spec/APP_FLOW.md#step-2) (tech: playwright, typescript)
```

Every Step = a separate e2e task = one recording. Precise granularity (1:1).

## Notes

- Dependencies: `(requires: X.X, Y.Y)` - Telesma skips the task if its dependencies are not completed
- Phase numbering: digit or digit+letter (e.g. `Phase 2`, `Phase 2M`, `Phase 6.Z1`). Suffix `M`/`I`/`A` = a track per client (mobile/iOS/Android, multi-client). Suffix `.Z<n>` = a rework phase resulting from a change in `telesma/changes/`.
- Documentation: `(spec: file.md, other-file.md)` - Telesma loads ONLY the related fragments of these files (through telesma/state/SPEC_INDEX.md + Read with offset/limit)
- Technology: `(tech: tag1, tag2)` - Telesma loads style/convention guidelines from `telesma/guidelines/<tag>.md` + always `general.md`. Tags must exist in `telesma/guidelines/` (missing = TELESMA BLOCKED).
- UX/UI (when `telesma/spec/ux_ui/` exists): `(ui-tokens: ...)` | `(ui-component: <file>#<list>)` | `(ui-screen: <file>#<id>)` — section 0.4 of the instructions. Identifiers after `#` must exist in `## UX/UI guidelines` in SPEC_INDEX.md.
- Visual artifacts (when config has `Screenshots: yes` or `Recordings: yes`): `(screen: <id>)` | `(flow: <file>#step-<N>)` — section 0.5 of the instructions. No APP_FLOW.md despite `Recordings: yes` = info in REPORT.md (not a blocker).
- Change: `(change: <file-name>.md)` — annotation on tasks modified or created by a file from `telesma/changes/`. When working on the task Telesma reads `telesma/changes/processed/<file-name>.md` to learn the context (what changed and why).
- Every implementation task has a `- [ ] Test: ...` item (unit/integration) right after it.
- **E2E at the end of a phase as a full task**: if the phase contains UI (`tech: react`, `react-native`, `vue`, `angular`), the last task of the phase must be `Task N.X: E2E test — [scenarios]` with `(requires: ...)` covering every task of the phase and `(tech: playwright, typescript)` (web) or `(tech: detox, typescript)` (mobile). Phases without UI do not need it.
- **Rework phases `.Z<n>`**: created automatically by Telesma when a change from `telesma/changes/` touches a ✅ task. Numbering: `Phase <N>.Z1`, `.Z2`, ..., where `N` is the phase whose task is being reworked. Every task in a Z phase has `(requires: <original-number>)` on the task being reworked and `(change: ...)`. The original task's checkbox is NOT unchecked — the completion history stays.
- [additional information for Claude]
