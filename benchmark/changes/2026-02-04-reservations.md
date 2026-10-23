---
date: 2026-02-04
priority: normal
affects: telesma/spec/library.md (section "6. Loans")
---

# Reservations of items that are temporarily unavailable

When all copies are on loan, a reader can join a queue.

## Creating

`POST /reservations` with `{"reader_id", "item_id"}` → `201` and the reservation: `id`,
`reader_id`, `item_id`, `state`, `date` (the day it was created), `valid_until` (`null` while
the reservation is waiting). A non-existent reader or item → `404`. Rules, in this order:

1. the item is an audiobook or has an available copy → `409 {"error": "available"}` (there is
   nothing to wait for);
2. the reader already has a reservation of this item in state `waiting` or `ready_for_pickup`
   → `409 {"error": "already_reserved"}`.

A new reservation has the state `waiting`. The queue of one item is served in the order of
creation (ascending `id`).

## A copy coming back

When a copy comes back (`POST /loans/{id}/return`) and the item has reservations in state
`waiting`, the first one in the queue moves to state `ready_for_pickup` with `valid_until` = today + 2 days.
That copy is set aside: **it does not count towards `available`** and nobody but that reader
can borrow it — another reader gets `409 {"error": "reserved"}` (in place of the
`no_copies` rule, when the only free copies are the ones set aside).

When the reader with a `ready_for_pickup` reservation borrows that item, the reservation moves to
state `fulfilled`. All the other loan rules apply to them.

## Expiry

On a day change, a `ready_for_pickup` reservation for which the new today is later than
`valid_until` moves to state `expired`, and the copy set aside passes to the next `waiting`
reservation of this item (new `valid_until` = new today + 2 days). When the queue is
empty, the copy goes back to `available`.

## Reading and cancelling

- `GET /items/{id}/reservations` → `200 {"reservations": [...]}` — all reservations of the
  item, in ascending `id` order, in all states.
- `DELETE /reservations/{id}` → `200` and the reservation in state `cancelled`. Cancelling a
  `ready_for_pickup` reservation passes the copy on in the same way as expiry does. A reservation in a
  state other than `waiting` and `ready_for_pickup` → `409 {"error": "inactive"}`.
