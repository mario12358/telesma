# SPEC_INDEX.md - Project documentation index

> Generated automatically by Telesma during the clarification phase.
> Enables selective loading of document fragments instead of whole files.

## Statistics

- **Files**: 0
- **Total size**: 0 lines
- **Indexed on**: [date]

## Documentation quality

- **Completeness**: [0-100]% — how well the requirements are covered (functional, non-functional, integrations, acceptance criteria)
- **Unambiguity**: [high | medium | low] — how many places leave room for interpretation
- **Consistency**: [high | medium | low] — whether the documents contradict each other
- **Project size**: [small | medium | large] — based on the number of modules, integrations, domain complexity

### Topic gaps

<!-- List of areas described poorly or not at all in the spec. Drives the number of questions. -->
<!-- Examples: authorization, data model, error handling, performance, deployment, tests -->

- [area]: [short description of what is missing]

### Recommendation

<!-- One sentence: is the documentation enough to make a plan, or is it worth completing the spec first. -->

## Documents

<!--
Format of every document:

### file-name.md (N lines)
[1-2 sentences: what this document is about, what information it contains]

#### Sections:
| Lines | Section | Anchor | Description |
|-------|---------|--------|-------------|
| 1-45 | Introduction | # System specification | Purpose of the document, context, conventions |
| 46-180 | Auth module | ## Authorization | Sign-up, login, JWT tokens, refresh |
| 181-340 | Users module | ## Users | User CRUD, roles, profile, permissions |
| 341-520 | Orders module | ## Orders | Creating orders, statuses, payments |

#### Keywords: auth, JWT, sign-up, login, user, role, order

---

Rules:
- Mark sections by markdown headings or logical divisions of the text
- If the document has no headings — split it into blocks of ~100 lines with a description of the content
- Anchor = the exact text of the line opening the section (1:1 from the file) — procedure 0.1 compares it
  with the start of the fetched fragment and on mismatch corrects the line range with Grep
- Section description: 5-15 words, concrete (what it contains, not "various information")
- Keywords: the 5-10 most important terms from the document
- Line numbers must be exact (check them while generating)
-->

## Flows

<!--
Section generated ONLY when the `## Visual artifacts` section in telesma/config.md has
`Recordings: yes` AND the listed `flow_files` exist in telesma/spec/. Flow files (typically
telesma/spec/APP_FLOW.md) describe user flows scenario by scenario. Every
`## Step N — Title` heading is a separate e2e scenario + one video recording (1:1).

The section is a map of line ranges: the tag `(flow: APP_FLOW.md#step-4)` in PLAN.md → Telesma
reads this table → Read(offset, limit) on the Step 4 fragment → generates an e2e test
based on that fragment + records a video to `telesma/artifacts/flows/step-4-<slug>.webm`.
Procedure in section 0.5 of the instructions.

Format of every entry:

### telesma/spec/APP_FLOW.md (N lines)
**Type**: flow
[1-2 sentences: what the file is about — e.g. "Main user flows of the MVP1 application, from sign-up to export"]

#### Steps:
| Lines | ID | Title | Actors | Main actions |
|-------|----|-------|--------|--------------|
| 11-30 | step-1 | Sign-up and project creation | User, System | Account creation, email verification, creating the first project |
| 33-50 | step-2 | Multi-upload of the specification | User, AI pipeline | Drag&drop of files, conversion, requirement extraction |
| 53-67 | step-3 | First requirement list screen | User | Filtering, sorting, traceability viewer |

---

Rules:
- ONE `## Step N — ...` in the file = ONE row in the table
- ID = `step-<N>` (lowercase, with a hyphen) — the identifier in `(flow: <file>#step-<N>)` tags
- Title = the text after " — " in the Step heading (shortened if long, max ~80 characters)
- Actors = from the Step's prose ("User" / "System" / "AI" / persona name)
- Main actions = 1 sentence, the essence of what happens
- Line numbers MUST be exact — Claude loads the fragment with Read(offset, limit)
- If there are several kinds of flow files (e.g. user-onboarding.md + admin-flows.md) — EACH one as a separate `### telesma/spec/<file> (N lines)` section
-->

## UX/UI guidelines

<!--
Section generated ONLY when the `telesma/spec/ux_ui/` directory exists with files (mockups, design tokens,
reference components — `.css`, `.html`, `.jsx`, `.tsx`). These files are loaded fragment by
fragment through the `(ui-tokens: ...)`, `(ui-component: ...)`, `(ui-screen: ...)` tags
in telesma/state/PLAN.md (procedure in section 0.4 of the instructions).

Format of every entry:

### telesma/spec/ux_ui/<file> (N lines)
**Type**: tokens | design-system | primitives | domain | polish | screens | artboards
[1-2 sentences: what this file is about]

#### Elements:
| Lines | Element | Description |
|-------|---------|-------------|
| 4-9 | Sparkle | Animated SVG sparkle (12px), AI mode |
| 11-51 | Icon | Stroke icon library (30+ paths: chevron, file, search, ...) |
| 54-70 | Avatar | Circle with initials, deterministic color from a hash, AI variant |

---

Mockups through links — when a filled-in `telesma/spec/ux_ui/LINKS.md` exists (a registry of links to
mockups outside the repo, e.g. Claude Design), add an entry with a link table to this section:

### telesma/spec/ux_ui/LINKS.md (link registry)
Mockups kept outside the repo — the tag `(ui-screen: telesma/spec/ux_ui/LINKS.md#<id>)` resolves
through a row of this table, the content is fetched with WebFetch (section 0.4).

#### Links:
| Id | Type | Link | Description |
|----|------|------|-------------|
| b1-project-overview | screen | https://claude.ai/public/artifacts/… | Project overview: cards, metrics; empty/loaded/error states |

---

Rules:
- ONE screen/component in the file = ONE row in the table (even if it has 200 lines)
- Element name = the identifier used in `(ui-screen: file#ElementName)` tags,
  ideally matching the component name in the code (e.g. `B1_ProjectOverview`)
- Line numbers MUST be exact — UI tasks load with `Read(file, offset=X, limit=Y)`
- Binary files (.png, .jpg, .pdf with mockups) → an entry WITHOUT a table, just the path + a description
- The `tokens.css` entry often has only a description without a table (the whole file is copied 1:1)
- In the link table, Id and Link copied EXACTLY from LINKS.md — telesma.sh compares these
  values to detect unindexed/changed entries (LINKS.md is not frozen)
-->
