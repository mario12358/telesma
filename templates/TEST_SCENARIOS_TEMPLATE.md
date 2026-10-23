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

## 0. Preparation

- [ ] <migration command from the project's stack — see docs/RUNBOOK.md> ends in state `<expected>`
- [ ] Database backup made (if the release changes data, not only the schema)
- [ ] An account with the required role: <role>
- [ ] Data without which the scenarios show nothing: <e.g. a project from before the change, a conversation > N messages>
- [ ] The environment and how it differs from production: <e.g. a different model provider>

---

## 1. <Area — a name the user recognises, not a module name>

### 1.1 <What we check — as a sentence>

**Why:** <one sentence: what was broken or what is new>

**Steps:**
1. <a clickable step>
2. <a clickable step>

**Expected:** <something concrete that tells you it worked>
**Failure signal:** <what exactly means the change did not work>
**Reference:** <path to telesma/artifacts/flows/step-N-<slug>.<ext> when there is a recording of this path — otherwise delete this line>
**Measured value:** ____ <only when an acceptance criterion names a number the tests did not measure — otherwise delete this line>

- [ ] **Result 1.1** — matches "Expected"

---

## <N>. Barriers — these scenarios must NOT succeed

<!-- Mandatory section when the release adds a limit, a validation or a permission. -->

### <N>.1 <An attempt that must be rejected>

**Steps:** <a request / action, preferably bypassing the interface>

**Expected:** <error code, refusal, nothing written to the database>
**Failure signal:** <anything that gets through>

- [ ] **Result <N>.1** — attempt rejected as in "Expected"

---

## <N+1>. Regression of indirectly affected areas

<!--
Paths that were not the target of the change but go through the changed code.
When the project has telesma/spec/APP_FLOW.md — point to Steps by name instead of describing the path again.
-->

- [ ] <Step N — Title (telesma/spec/APP_FLOW.md)>
- [ ] <a path with no counterpart in APP_FLOW — in one sentence>

---

## Result

- **Tested by:** _______
- **Date:** _______
- **Environment:** dev / production
- **Failed scenarios (`[-]`):** _______
- **Decision:** version ready for deployment / needs fixes
