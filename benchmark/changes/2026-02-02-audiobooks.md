---
date: 2026-02-02
priority: normal
affects: telesma/spec/library.md (section "4. Items")
---

# New item type: audiobook

The library has bought audiobook licences. These are files, so there are no physical copies.

## Rules

- A new value of the `type` field: `audiobook`. On creation the `copies` field is
  **optional and ignored** for an audiobook; the item returns `copies: null` and `available: null`.
- An audiobook is always available — the `no_copies` rule does not apply to it, the same title
  can be borrowed by any number of readers at once. One reader, however, may not have
  two unreturned loans of the same audiobook → `409 {"error": "already_borrowed"}`
  (checked after `loan_limit`).
- An audiobook **counts** towards the limit of 3 unreturned loans and is subject to the other rules.
- `due_date` = today + 7 days. Late fine: 0.5 per day.

An audiobook must work everywhere a book and a film do: the `GET /items?type=audiobook` filter,
the overdue report, the CSV export, notifications.
