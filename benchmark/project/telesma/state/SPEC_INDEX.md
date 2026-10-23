# SPEC_INDEX.md - Project documentation index

> Index frozen together with the benchmark — not generated during clarification.

## Statistics

- **Files**: 1
- **Total size**: 98 lines
- **Indexed on**: 2026-09-19

## Documentation quality

- **Completeness**: 95% — HTTP contract, rules, errors and formats described explicitly
- **Unambiguity**: high
- **Consistency**: high
- **Project size**: small

### Topic gaps

- none

### Recommendation

The documentation is sufficient to implement the plan without questions.

## Documents

### library.md (98 lines)
Full specification of the library HTTP service: start-up, system time, error format, items, readers, loans with rules and fines, reports.

#### Sections:
| Lines | Section | Anchor | Description |
|-------|---------|--------|-------------|
| 1-6 | Introduction | # Library — specification | Purpose of the service, one process, SQLite, no login |
| 7-20 | Technical requirements | ## 1. Technical requirements | Standard library only, start command, tests, amount and date formats |
| 21-30 | System time | ## 2. System time | Day stored in the database, GET/POST /system/day, date in the past, /health |
| 31-42 | Errors | ## 3. Errors | Error response shape, statuses 400/404/409, rule order |
| 43-53 | Items | ## 4. Items | Item fields, creation, read, list with type filter, available |
| 54-64 | Readers | ## 5. Readers | Reader fields, unique e-mail, fine balance, payment and overpayment |
| 65-87 | Loans | ## 6. Loans | Due dates, four rules in order, return, fines, reader's list |
| 88-98 | Reports | ## 7. Reports | Overdue report and CSV export with header and quoting |

#### Keywords: loan, due_date, fine, fine_balance, overdue, limit, copies, available, CSV, system/day

## Flows

No user-flow files (a service without a user interface).
