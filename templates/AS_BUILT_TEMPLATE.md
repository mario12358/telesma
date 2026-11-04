<!-- TELESMA_AS_BUILT_TEMPLATE: written by the survey session of `telesma.sh --adopt`; the session deletes this line in Task 0.1 -->
# As built — [project name]

The system as it stood at commit [sha] ([date]), when Telesma took it over (`Adopted at` in
`telesma/config.md`). Written by the survey session from the code and its tests, corrected by the
owner. Part of `telesma/spec/`: frozen after clarification like the rest of it; what changes later
goes through `telesma/changes/`.

How to read it: one section per module; one `- When …, then …` line per behaviour, with the place
in the code (`path:lines`) and a confidence tag — `[verified by test: <name>]` when a test the
survey read exercises it, `[inferred]` when it was read from the code alone. `## Open questions`
lists what the code does not explain; the clarification turns each into an assumption or a
question for the owner. Correct any line that is wrong — a wrong "as built" becomes a wrong plan.

## Overview

- **Purpose**: [what the system is for, two sentences]
- **Runs as**: [CLI / HTTP service on port … / desktop window / library / scheduled job]
- **Entry points**: [main module, routes file, command names]
- **Test baseline**: see `telesma/state/REPORT.md` → Test status (run by the launcher at adoption)

| Module | Path | Role | Tests |
|--------|------|------|-------|
| [name] | [directory or files] | [one phrase] | [n files / none] |

## [Module]

[What it is for and what calls it, one to three sentences.]

- When [trigger or input], then [observable result]. (`path:lines`) [verified by test: `test_name`]
- When [...], then [...]. (`path:lines`) [inferred]

### Notes
- External services, data stores and configuration keys this module touches
- Known limits visible in the code (`path:line`)

## Open questions

- OQ1: [what the code does not explain] — [where] ([what the survey would assume])
