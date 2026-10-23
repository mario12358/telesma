# telesma/state/REPORT.md - Project execution report

<!-- This file goes IN FULL into the startup prompt of every session. Two kinds of sections:    -->
<!--   • current state (Summary) — OVERWRITE, it is meant to be one up-to-date description;    -->
<!--   • chronicle (Test status, Task history, Change history, Problem log,                   -->
<!--     Visual artifacts) — APPEND one entry; older ones rotate into telesma/state/REPORT_ARCHIVE.md   -->
<!--     at startup (Test status: the 3 latest runs).                                          -->
<!-- Do not create your own `## ` sections for session summaries — EVERY `## ` section outside -->
<!-- this template is ad hoc and only the 3 newest of them are kept.                           -->
<!-- Rotation moves WHOLE entries, multi-line ones too. An entry must have a recognisable      -->
<!-- opener (a table row, `### …`, `- [date] …`, `- **Name …**`), and a paragraph glued        -->
<!-- under an entry counts as its continuation and goes to the archive together with it.      -->

## Summary

- **Start**: 2026-09-19
- **Status**: Completed
- **Progress**: 10/10 tasks completed (each with its "Test" line); full suite 117/117, runbook in `docs/RUNBOOK.md`

## Test status

<!--
The table is current state — REPLACE the numbers, do not add a second table.
Above the table one paragraph per full-suite run, opened with bold text carrying a date:

**Regression after Phase 12 (2026-08-20) — GREEN:** backend `pytest -q` 340/0, frontend 210/0.
Compared with 328/205 after Phase 11: +12 backend tests. Tag `telesma/phase-12`.

The date in the first line is MANDATORY — rotation uses it to tell which runs to keep
(the 3 latest) and which to move to telesma/state/REPORT_ARCHIVE.md. A paragraph without a date
is treated as a continuation of the run above it. Without a date the block stays in the file
forever and grows in the prompt of every session.
-->

**Regression after Phase 1 (2026-09-19) — GREEN:** `python3 -m unittest discover -s tests -v` 23/0 (skeleton 14, system day 9). Tag `telesma/phase-1`.

**Regression after Phase 2 (2026-09-19) — GREEN:** `python3 -m unittest discover -s tests -v` 48/0. Compared with 23 after Phase 1: +12 items, +13 readers. Tag `telesma/phase-2`.

**Regression after Phase 3 (2026-09-19) — GREEN:** `python3 -m unittest discover -s tests -v` 105/0. Compared with 48 after Phase 2: +9 loan, +18 rules, +23 returns/fines/payments, +7 reader's list. Tag `telesma/phase-3`.

**Regression after Phase 4 — final (2026-09-19) — GREEN:** `python3 -m unittest discover -s tests -v` 117/0. Compared with 105 after Phase 3: +6 overdue report, +6 CSV export. Commands from `docs/RUNBOOK.md` checked with `curl` against a live process. Tag `telesma/phase-4`.

| Metric | Value |
|--------|-------|
| Total tests | 117 |
| Pass | 117 |
| Fail | 0 |
| Skip | 0 |
| Last run | 2026-09-19 (full suite after Phase 4, final) |

## Task history

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|
| 1.1 Architecture skeleton + Test | ✅ | 14/14, `json_object` mutant killed | 1 | 6978488 | 2026-09-19 |
| 1.2 System time + Test | ✅ | 23/23, `date_in_past` mutant killed | 1 | d0d9651 | 2026-09-19 |
| 2.1 Items + Test | ✅ | 35/35, `?type=` filter mutant killed | 1 | 0b83739 | 2026-09-19 |
| 2.2 Readers + Test | ✅ | 48/48, e-mail normalization mutant killed | 1 | 130e442 | 2026-09-19 |
| 3.1 Loan + Test | ✅ | 57/57, film due-date mutant killed | 1 | ea6a3d2 | 2026-09-19 |
| 3.2 Loan rules + Test | ✅ | 75/75, 4 mutants (10.0 threshold, due-date boundary, limit 3, no copies) killed | 1 | 647e90a | 2026-09-19 |
| 3.3 Return, fines, payment + Test | ✅ | 98/98, 3 mutants (film rate, `already_returned`, overpayment boundary) killed | 1 | 2d8350b | 2026-09-19 |
| 3.4 Reader's loan list + Test | ✅ | 105/105, `?state=` validation mutant killed | 1 | 0da0c82 | 2026-09-19 |
| 4.1 Overdue report + Test | ✅ | 111/111, unreturned-filter mutant killed | 2 | 8d795fd | 2026-09-19 |
| 4.2 CSV export + Test | ✅ | 117/117, `fine` format mutant killed | 1 | `Telesma: 4.2` | 2026-09-19 |

## Change history

<!--
Entries added by Telesma after processing a file from telesma/changes/.
Entry format (one ### per change):

### YYYY-MM-DD <file-name>.md
- **Kind**: bug | correction | feature
- **Priority**: critical | normal
- **Affects**: [the affects field from the frontmatter, or "general"]
- **Summary**: [1-2 sentences on what changes and why]
- **Modified pending tasks**: [list of numbers, e.g. 4.2, 5.1] or "none"
- **New rework phase**: [e.g. Phase 6.Z1 with 3 tasks] or "none"
- **New tasks**: [list of numbers, e.g. 7.4, 7.5] or "none"

The source file of the change lives in telesma/changes/processed/<file-name>.md (audit trail in git).
-->

## Visual artifacts

<!--
Section filled in ONLY when the `## Visual artifacts` section of telesma/config.md has
`Screenshots: yes` or `Recordings: yes`. Full procedure: section 0.5 of the instructions.

Row format:
| Phase | Type | ID | Artifact file | Spec source |
|-------|------|----|--------------:|-------------|
| 1     | screen | B1_ProjectOverview | telesma/artifacts/screens/B1_ProjectOverview.png | telesma/spec/ux_ui/screens-b1-b2.jsx:52-200 |
| 1     | flow   | step-1             | telesma/artifacts/flows/step-1-registration.webm | telesma/spec/APP_FLOW.md:11-30 |

Info warnings (no APP_FLOW.md despite Recordings: yes, no flow_files, etc.) go
below the table with the prefix `> ⚠ Info:` so the user sees what happened "silently".
-->

| Phase | Type | ID | Artifact file | Spec source |
|-------|------|----|---------------|-------------|
| | | | | |

## Problem log

<!-- Format: [date] Task X.X: problem description - solution/status -->
<!-- We do NOT keep a list of changed files — git knows it better: git log --stat -->

- [2026-09-19] Task 1.1: `python.md` (pytest, `src/`, pyproject, venv) and `sql.md` (`created_at` from the clock, soft delete) conflict with spec §1–2 (standard library only, package in the root directory, the system does not read the clock) - no block, because the user settled it in config.md (the `unittest` command) and in AC 1.1; I follow the spec, decisions in PROJECT_CONTEXT.
- [2026-09-19] Task 4.1: changed the test `test_report_many_overdue_in_ascending_id_order_with_own_days` before the first commit - the scenario had John borrow a book while his film was overdue, which rightly gives 409 `has_overdue` (spec library.md §6 Loans, rule 2); the third loan is now made by a new reader, the report assertions (order by id, `days_overdue`) not weakened. Code unchanged.
- [2026-09-19] Task 1.1: the AC «invalid JSON → 400» has no POST route in the product yet - the test goes through real HTTP on an `/echo` route injected into `Application(routes=...)`; a test on `POST /system/day` comes in 1.2.
