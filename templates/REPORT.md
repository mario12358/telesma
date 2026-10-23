# telesma/state/REPORT.md - Project execution report

<!-- This file goes IN FULL into the startup prompt of every session. Two kinds of sections:  -->
<!--   • current state (Summary) — OVERWRITE it, it is meant to be one up-to-date description; -->
<!--   • chronicle (Test status, Task history, Change history, Problem log,                    -->
<!--     Visual artifacts) — APPEND one entry; older ones rotate to telesma/state/REPORT_ARCHIVE.md   -->
<!--     at startup (Test status: the 3 latest runs).                                          -->
<!-- Do not create your own `## ` sections for session summaries — EVERY `## ` section outside -->
<!-- this template is ad-hoc and only the 3 newest of them are kept.                           -->
<!-- Rotation moves WHOLE entries, multi-line ones too. An entry must have a recognisable      -->
<!-- start (a table row, `### …`, `- [date] …`, `- **Name …**`), and a paragraph glued        -->
<!-- under an entry counts as its continuation and goes to the archive together with it.      -->

## Summary

- **Start**: [start date]
- **Status**: In progress | Completed | Blocked
- **Progress**: 0/0 tasks completed

## Test status

<!--
The table is the current state — REPLACE the numbers, do not add a second table.
Above the table, one paragraph per full-suite run, opened with bold text carrying the date:

**Regression after Phase 12 (2026-08-20) — GREEN:** backend `pytest -q` 340/0, frontend 210/0.
Compared with 328/205 after Phase 11: +12 backend tests. Tag `telesma/phase-12`.

The date in the first line is MANDATORY — rotation uses it to tell which runs to keep
(the 3 latest) and which to move to telesma/state/REPORT_ARCHIVE.md. A paragraph without a date
is treated as a continuation of the run above it. A block without a date stays in the file
forever and grows in the prompt of every session.
-->

| Metric | Value |
|--------|-------|
| Total tests | 0 |
| Pass | 0 |
| Fail | 0 |
| Skip | 0 |
| Last run | - |

## Task history

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|
| | | | | | |

## Change history

<!--
Entries added by Telesma after processing a file from telesma/changes/.
Entry format (one ### per change):

### YYYY-MM-DD <file-name>.md
- **Kind**: bug | correction | feature
- **Bug source**: [bugs only: task X.Y that built it | unknown]
- **Detected by**: [bugs only: test | scenario | review | telesma | owner | production]
- **Priority**: critical | normal
- **Affects**: [the affects field from the frontmatter, or "general"]
- **Summary**: [1-2 sentences on what changes and why]
- **Modified pending tasks**: [list of numbers, e.g. 4.2, 5.1] or "none"
- **New rework phase**: [e.g. Phase 6.Z1 with 3 tasks] or "none"
- **New tasks**: [list of numbers, e.g. 7.4, 7.5] or "none"

The change's source file lives in telesma/changes/processed/<file-name>.md (audit trail in git).
-->

## Visual artifacts

<!--
Section filled in ONLY when the `## Visual artifacts` section in telesma/config.md has
`Screenshots: yes` or `Recordings: yes`. Full procedure: section 0.5 of the instructions.

Row format:
| Phase | Type | ID | Artifact file | Spec source |
|-------|------|----|--------------:|-------------|
| 1     | screen | B1_ProjectOverview | telesma/artifacts/screens/B1_ProjectOverview.png | telesma/spec/ux_ui/screens-b1-b2.jsx:52-200 |
| 1     | flow   | step-1             | telesma/artifacts/flows/step-1-sign-up.webm      | telesma/spec/APP_FLOW.md:11-30 |

Info warnings (no APP_FLOW.md despite Recordings: yes, no flow_files, etc.) go
below the table with the prefix `> ⚠ Info:` so the user can see what happened "silently".
-->

| Phase | Type | ID | Artifact file | Spec source |
|-------|------|----|---------------|-------------|
| | | | | |

## Problem log

<!-- Format: [date] Task X.X: problem description - fix/status -->
<!-- We do NOT keep a list of changed files — git knows it better: git log --stat -->
