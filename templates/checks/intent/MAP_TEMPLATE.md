# Attack surface map

<!-- Declaration of intent: who has access to what. The `intent` check compares code against it   -->
<!-- on every commit, the `red-team` check compares tests against it at phase end. Telesma writes    -->
<!-- this file (new route = new row in the same commit); the human sees the changes in the release -->
<!-- proposal and in the PR diff. It does not go into the startup prompt.                          -->

- **Session**: ?
  <!-- cookie | header — how the browser carries identity. cookie (or ?) = every write route       -->
  <!-- needs the red-team case `csrf`; header (Bearer) = it does not.                              -->

## Roles

<!-- Role = who (from the spec). Guard in code = the text that, in the route's definition window   -->
<!-- (decorators and signature, arguments before the handler, @UseGuards, middleware with a        -->
<!-- prefix), stands for this role. Several guards separated by commas = any one is enough.        -->
<!-- `(global)` = the guard stands outside the route (app-wide middleware, proxy forward_auth) —   -->
<!-- the route's code is then not checked, the red team remains. `anonymous` is built in: a public -->
<!-- route.                                                                                         -->

| Role | Who | Guard in code |
|---|---|---|
| anonymous | no session | — |

## Ownership boundaries

<!-- What no rule can check: whether doctor A sees doctor B's patient, whether a member of project -->
<!-- X changes project Y. Every route with an Ownership column other than — gets the red-team case -->
<!-- `foreign-owner`. Row = resource, who may, where the boundary is and what a violation returns. -->

| Resource | Who may | Boundary |
|---|---|---|

## Routes

<!-- Roles: a role or `a + b` (both required); alternatives separated by commas. `?` = undecided  -->
<!-- (warns until someone decides: public, or is a guard missing). Ownership: a resource from the  -->
<!-- table above, `—` = none, `?` = undecided (the red team treats it as a resource).              -->

| Route | Roles | Ownership | File |
|---|---|---|---|

## Outbound

<!-- host = a domain the code sends requests to; env = an environment variable holding a secret;  -->
<!-- db = a fragment of a statement granting privileges (GRANT, SECURITY DEFINER, BYPASSRLS…).     -->
<!-- A new value in code without a row here = a warning.                                            -->

| Kind | Value | Purpose |
|---|---|---|
