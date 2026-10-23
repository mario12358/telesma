---
kind: rule
run: python3 run.py
check: python3 run.py --check
when: phase, release, ci
scope: changed
on_failure: block
---

# Check: red-team

In a medical project a real authorization hole ("doctor A1 admitted a patient from A2's queue")
was found by a red team with mutation — not by the implementation's tests, which were green.
Telesma invented a per-role red team at the end of every phase there on its own; this check turns
that into a rule for every project with an attack surface map (`telesma/state/SECURITY_MAP.md`, the
`intent` check).

**What it checks.** Routes from the map with a role other than `anonymous` whose definition or
body changed since the previous phase tag (at `release` — since the previous version, in CI —
since `TELESMA_SINCE`). Each one must have a marker in some test file:

```
# telesma: red-team PATCH /projects/{project_id} — no-session, foreign-role, foreign-owner, csrf
```

A path parameter in any form (`{id}`, `:id`, `<id>`), but as a parameter — `/projects/5` does
not match `/projects/{id}`; the mount prefix (`/api`) may or may not be in the marker. Several
markers for one route add up their cases. The required cases follow from the map:

| Case | When required | What the test does |
|---|---|---|
| `no-session` | always | request without authentication → 401/403/redirect, state unchanged |
| `foreign-role` | the map has at least two roles besides `anonymous`, and the route does not admit all of them | an account of a role outside the route's list → 403 |
| `foreign-owner` | Ownership column ≠ `—` (also `?`) | an account with the right role, but someone else's resource (another organization, another patient) → 403/404 |
| `csrf` | a write method and `Session` ≠ `header` | a write without an Origin header and with a foreign one → 403, state unchanged |

Aliases in the marker: `other-organization`, `foreign-organization` = `foreign-owner`.

A test that iterates over a module's route list ("CSRF on every write route of the registrar")
is marked with one wildcard marker: `telesma: red-team * /registrar/* — csrf` (method `*` or
`ALL`, a path ending in `/*` = every route under the prefix). A wildcard declares more than a
single line — all the more reason the test must actually go through every route on the list.

| Rule | Severity | What |
|---|---|---|
| `red-team-missing` | **block** | a protected route changed in the phase lacks one of the required cases. The message is ready task text: the route, the missing cases, the marker line to write |
| `red-team-undecided` | warn | routes changed in the phase with the role `?` in the map — not covered until the role is decided |

**The first phase after the map is created only warns** (the map is absent at the reference
point): nobody has reviewed the skeleton's roles yet, and blocking the tag on the first start
would stall the loop on debt from before the check. From the next phase on it blocks.

**What it does not check.** That the test actually attacks and would fail if the guard were
removed — the marker is a declaration. That is checked by the mutation test from
`telesma/guidelines/general.md` (remove the guard, the test must turn red) and by the phase
auditor (stage E4). This check makes sure a test was written at all for every changed route and
every case that follows from the map.

**Skipped:** public routes, routes without a map row (reported by `intent`), test files as a
source of routes.
