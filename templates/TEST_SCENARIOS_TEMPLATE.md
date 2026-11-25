# vX.Y.Z — manual test scenarios

<!--
Template of the file created for EVERY release version tag (section 15.7 of Telesma's instructions).
File name = tag name: docs/test-scenarios/vX.Y.Z.md
It collects ONLY what automated tests could not check.
The template is stack-neutral — take commands and package names from docs/RUNBOOK.md
and from the `Tests` section of telesma/config.md.
Delete this comment and every <...> placeholder when filling it in.
-->

- **Tag:** `vX.Y.Z`
- **Date:** <YYYY-MM-DD>
- **Previous version:** `<vX.Y-1.0>`
- **Scope:** <phases / areas, in plain words — not task numbers>
- **Migrations / deployment steps:** <what has to be run at deployment + a one-sentence effect, or "none">
- **Automated tests:** <result of the suite from the `Tests` section of telesma/config.md — numbers per package>, green. Below, only what automation could not check.

**Marking the result:** `[x]` = checked and works · `[-]` = checked and does NOT work · `[ ]` = not checked.
**One scenario = one checkbox** (the `Result N.M` line at the end of the scenario). With `[-]` add one
sentence under the scenario: what you saw instead of the expected outcome.

---

## What this version changes

<!--
The developer's intent, written BEFORE the scenarios: testers compare it with what they see.
One row per change a user can notice, in the user's words. Every row names its scenarios — the main
path and the other paths through the same place — or says why none is needed.
-->

| # | Intended change — what the user should now see or be able to do | Where (screen / command, named as on screen) | Scenarios |
|---|------|------|------|
| Z1 | <one sentence> | <"Name on screen"> | 1.1, 1.2 |
| Z2 | <one sentence> | <"Name on screen"> | none — <covered by an automated test of the same path / not visible to a user> |

---

## 0. Preparation

- [ ] Start the version: <where the program is and how to start it — the built file with its full path to double-click, one command that works from any folder (see docs/RUNBOOK.md), or the address to open>
- [ ] <migration command from the project's stack — see docs/RUNBOOK.md> ends in state `<expected>`
- [ ] Database backup made (if the release changes data, not only the schema)
- [ ] An account with the required role: <role>
- [ ] Data without which the scenarios show nothing: <e.g. a project from before the change, a conversation > N messages>
- [ ] The environment and how it differs from production: <e.g. a different model provider>

---

## 1. <Area — a name the user recognises, not a module name>

### 1.1 <What we check — as a sentence>

**Kind:** change (Z<n>) — <one sentence: what was broken or what is new>

**Steps:**
1. <a step a person can perform, with names copied from the screen: "Save", not `saveButton`>
2. <a step a person can perform>

**Expected:** <something concrete that tells you it worked>
**Failure signal:** <what exactly means the change did not work>
**Reference:** <path to telesma/artifacts/flows/step-N-<slug>.<ext> when there is a recording of this path — otherwise delete this line>
**Measured value:** ____ <only when an acceptance criterion names a number the tests did not measure — otherwise delete this line>

- [ ] **Result 1.1** — matches "Expected"

### 1.2 <Another path through the same place — cancel, empty or wrong input, back, a second time, no network>

**Kind:** change (Z<n>), other path — <one sentence: what this path could break>

**Steps:**
1. <a step a person can perform>

**Expected:** <something concrete that tells you it worked>
**Failure signal:** <what exactly means the change did not work>

- [ ] **Result 1.2** — matches "Expected"

---

## <N>. Barriers — these scenarios must NOT succeed

<!-- Mandatory section when the release adds a limit, a validation or a permission. -->

### <N>.1 <An attempt that must be rejected>

**Kind:** change (Z<n>) — <one sentence: which limit, validation or permission is new>

**Steps:** <a request / action, preferably bypassing the interface>

**Expected:** <error code, refusal, nothing written to the database>
**Failure signal:** <anything that gets through>

- [ ] **Result <N>.1** — attempt rejected as in "Expected"

---

## <N+1>. Regression of indirectly affected areas

<!--
Paths that were not the target of the change but go through the changed code. Every line says in
one sentence why it is here: which changed place it passes through.
When the project has telesma/spec/APP_FLOW.md — point to Steps by name instead of describing the path again.
-->

- [ ] <Step N — Title (telesma/spec/APP_FLOW.md)> — regression: <passes through …>
- [ ] <a path with no counterpart in APP_FLOW — in one sentence> — regression: <passes through …>

---

## Result

- **Tested by:** _______
- **Date:** _______
- **Environment:** dev / production
- **Failed scenarios (`[-]`):** _______
- **Decision:** version ready for deployment / needs fixes
