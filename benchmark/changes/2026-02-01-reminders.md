---
date: 2026-02-01
priority: normal
affects: telesma/spec/library.md (section "6. Loans")
---

# Reminders for readers

Readers forget their due dates. The system should create notifications on its own, which a
staff member will read and pass on.

## What should happen

On every day change (`POST /system/day` to a date later than the current one) the system goes
through unreturned loans and creates notifications:

- `due_tomorrow` — when the new today is exactly one day earlier than `due_date`;
- `past_due` — when the new today is later than `due_date`.

For a single loan each of these two kinds is created **at most once**, regardless of how many
times and by how many days the day changes. Jumping several days at once is normal
(weekends, holidays): if the day jumps from a date before the due date straight to a date after
it, only `past_due` is created — `due_tomorrow` would no longer be true. Setting the same date
as the current one creates nothing.

## Reading

`GET /readers/{id}/notifications` → `200 {"notifications": [...]}` in ascending `id` order.
Entry: `id`, `kind` (`due_tomorrow` | `past_due`), `loan_id`, `title` (the item's
title), `date` (the day the notification was created). A non-existent reader →
`404 not_found`. A loan returned before the day change gets no more notifications;
notifications created earlier stay on the list.
