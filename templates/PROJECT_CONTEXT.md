# PROJECT_CONTEXT.md

This file keeps the project context that survives `/compact`.

## Tech stack

- Language: [e.g. Python 3.11]
- Framework: [e.g. FastAPI]
- Database: [e.g. PostgreSQL]
- Tests: [e.g. pytest]

## Architecture

[A short description of the project structure]

## Key decisions

<!-- The table grows with every session, and the file goes into the startup prompt in full, so    -->
<!-- telesma.sh keeps its 40 latest rows in it — older ones go to telesma/state/CONTEXT_ARCHIVE.md     -->
<!-- (write-only). A decision that is still BINDING — one whose violation would break the project — -->
<!-- mark with 📌 in the Decision column: a row with 📌 is never rotated.                           -->

| Date | Decision | Reason |
|------|----------|--------|
| | | |

## Known problems and solutions

<!-- Known pitfalls: distilled from the Problem log at the end-of-phase checkpoint (section 7  -->
<!-- of the instructions). Only RECURRING patterns — a one-off error stays in the Problem log  -->
<!-- in REPORT.md. One row = one pitfall, on ONE line and concise: the file goes               -->
<!-- in full into the prompt of every session.                                                 -->
<!-- telesma.sh keeps the 30 latest rows here, older ones → telesma/state/CONTEXT_ARCHIVE.md.      -->
<!-- A pitfall that COMES BACK despite being written down (happened ≥2 times): mark it with 📌 -->
<!-- — such a row never rotates. Leave a one-off slip unmarked.                                -->

| Problem | Solution |
|---------|----------|
| | |

## Component dependencies

[A description of how the components work together]

## Current state

<!-- CURRENT STATE — OVERWRITE. It should answer "where are we TODAY", not be a chronicle    -->
<!-- of turns: task history has its own place in REPORT.md and rotates there, while nothing  -->
<!-- rotates here. Appending more "turn of 08-19 closed" paragraphs turns this               -->
<!-- section into a second, unbounded report in the prompt of every session.                 -->

- Last completed task: [number/name]
- Next task: [number/name]
- Blockers: [if any]
