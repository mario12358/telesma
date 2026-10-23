# BACKLOG — topics for later

A list of ideas, small improvements and technical debt picked up during
interactive sessions. **Read-write** — Claude may check items off and archive them
(with the user's confirmation), the user edits freely (priorities, ordering,
adding items by hand).

## How it differs from the other channels

- `telesma/changes/<file>.md` = a concrete change of telesma/spec/functionality → Telesma
  applies it sequentially to `PLAN.md` in the next autonomous loop
  (section 0.3 of the instructions).
- `DECISIONS.md` = changelog of project decisions (write-only, section 10).
- `BUGFIXES.md` = changelog of bug fixes (write-only, section 11).
- `REVIEWS.md` = changelog of code reviews (write-only, section 12).
- **BACKLOG.md** (this file) = open topics, ideas, "nice to have",
  observations from discussions — with no guarantee Telesma will take them. The user decides
  when to promote an item from the backlog to `telesma/changes/` or do it ad hoc.

## Entry format

```markdown
- [ ] **Title** — `priority` `area`
  - **Context**: where it came from (date, thread, observation)
  - **Suggested solution**: one or two sentences
  - **Dependencies**: which other items block it / depend on it (optional)
```

## Priorities

- `P0` — critical (to do in the next session)
- `P1` — important (to do in the current phase)
- `P2` — nice to have (when there is slack)
- `P3` — an idea for the future (we may never do it)

## Workflow

- **Adding** (proactive + confirmation): Claude picks up signals in the conversation
  ("for later", an out-of-scope observation) → proposes an entry with a priority and
  area → the user says OK / change the priority / skip. Without an OK nothing is added.
- **Promotion BACKLOG → telesma/changes/**: when an item becomes a formal change,
  the user says "promote X" → Claude creates `telesma/changes/<slug>.md` with frontmatter
  + marks the item `[→ telesma/changes/<slug>.md]`. The next mode 1 start picks up
  the change through section 0.3.
- **Ad-hoc execution**: the user says "do X" → Claude implements, tests,
  commits, marks it `[x] (abc1234)`.
- **Archiving**: after >30 days completed items are moved to
  `BACKLOG_DONE.md` (lazily, at Telesma's start when there are >10 items).

Full procedure: section 13 in `templates/instructions/INTERACTIVE.md`.

---

<!-- Add items below, grouped into ## sections per area when there are >10 entries -->

## Unclassified (to triage)
