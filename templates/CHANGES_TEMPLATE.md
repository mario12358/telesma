---
date: YYYY-MM-DD
priority: normal
kind: feature
affects: telesma/spec/<file>.md (section "<section name>") | telesma/spec/<file>.md:<line-from>-<line-to> | general
---

<!--
Change file — introduces a modification of the specification after the clarification phase.

How to use it:
1. Copy this file under any name into the project's telesma/changes/ directory
   (e.g. telesma/changes/2026-04-23-email-validation.md). Any name works.
2. Fill in the frontmatter (optional, but recommended):
   - date: date the change was requested
   - priority: critical | normal (critical ones are applied first)
   - kind: feature (new scope) | correction (works as agreed, should work differently)
     | bug (something already built does not work). No field → Telesma judges from the content.
   - affects: a pointer to the telesma/spec/ section the change concerns
     (Telesma reads that section to compare "before vs after")
3. Describe in the body WHAT changes and WHY — without it Telesma will block applying it.
4. Save the file. Telesma processes it at the next start:
   - Modifies telesma/state/PLAN.md (pending tasks, or creates a rework phase "N.Z1" for ✅ ones)
   - Adds an entry to telesma/state/REPORT.md → ## Change history
   - Moves this file to telesma/changes/processed/ (audit trail in git)

What Telesma does with different kinds of changes:
- Pending task → edits the description in place + annotation (change: <file-name>)
- New functionality → appends new tasks to the right phase
- The change touches a ✅ completed task → creates a new rework phase (e.g. Phase 6.Z1)
  with tasks `(requires: <original-number>)`. The ✅ checkbox is NOT unchecked.

Delete this comment section once filled in.
-->

# What changes

[Describe concretely which functionality/behaviour/requirement we are changing.
Be unambiguous — if the content is unclear, Telesma returns TELESMA BLOCKED instead of guessing.]

# Why

[Reason for the change: a client request, a product decision, a compliance requirement, a bug found
in the specification, a change of priorities, etc. This helps a future reader of the change history
understand the context.]

# Impact (optional)

[If you know which tasks in telesma/state/PLAN.md are affected — list them here.
Telesma analyses the plan anyway, but your hint speeds it up and lowers the risk of a mistake.

Example:
- Phase 3 task 3.2 (LoginForm) — needs rework, add an MX check
- Phase 5 task 5.1 (RegisterForm) — pending, update the description
- New task: backend MX validator, into Phase 2]
