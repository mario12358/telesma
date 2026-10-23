## 14. Artifact regeneration mode (mode 4, autonomous)

A backfill of visual artifacts (screenshots + video recordings) **without touching PLAN.md**. The mode for the situation "the project is done, I have APP_FLOW.md, I have no recordings" — or when you want to regenerate after UI/flow changes. Complementary to section 0.5 (which works per task inside the regular loop).

### Rules on entering artifacts mode

- ALWAYS `Clarified: yes` in `telesma/config.md` (the clarification phase makes no sense in this mode)
- The `## Visual artifacts` section of `telesma/config.md` must have **at least one** flag set to `yes` (`Screenshots: yes` or `Recordings: yes`). Both `no` → the message *"TELESMA ARTIFACTS: nothing to do"* and the session ends.
- Does NOT work on new tasks — only generates missing artifacts
- Does NOT modify PLAN.md (checkboxes unchanged, content unchanged)
- Does NOT process `telesma/changes/` (if there are pending changes — info to REPORT.md and ignore them; mode 1 will do the full processing)
- Does NOT log to `DECISIONS.md` (autonomous, not a chat) — logs to REPORT.md like mode 1

### Step 1: Validation and building the list of targets

1. **Check the flags** in `config.md` → extract `Screenshots`, `Recordings`, `Flow files`, `Commit artifacts`
2. **Scan PLAN.md for tags** (✅ tasks AND pending ones — in this mode the checkbox status does not matter):
   - Every occurrence of `(screen: <id>)` → a screen candidate
   - Every occurrence of `(flow: <file>#step-<N>)` → a flow candidate
3. **Scan the flow files** (when `Recordings: yes`):
   - For every file in `Flow files` (typically `telesma/spec/APP_FLOW.md`) → find all `## Step N — Title` headings
   - Every Step N → a flow candidate (even if no task in PLAN.md has a matching tag — that is the typical backfill case)
   - Skip files with the `TELESMA_APP_FLOW_TEMPLATE` marker in the first line (unfilled templates)
4. **Deduplication** — if the same Step appears in PLAN.md as a tag AND in APP_FLOW.md as a heading, treat it as one target
5. **Filter by the flags**: when `Screenshots: no` → drop all screen candidates; when `Recordings: no` → drop all flow candidates

### Step 2: Checking existing artifacts (idempotency)

For each candidate check whether the artifact already exists:
- Screen `<id>` → `telesma/artifacts/screens/<id>.png` (Glob)
- Flow `step-<N>` → `telesma/artifacts/flows/step-<N>-*.{webm,mp4,mov}` (Glob — the slug after `step-N-` varies)

If the file exists → **SKIP**, add it to the "skipped (idempotent)" count. Do not regenerate — this is a backfill mode, not a force-regen. (A user who wants to force it must delete `telesma/artifacts/` by hand.)

### Step 3: Generating the missing artifacts

For each missing candidate:

#### Screen `<id>`

1. **Find the test that shows this screen**:
   - Convention: `tests/screenshots/<id>.spec.ts` (Playwright) or `e2e/screenshots/<id>.e2e.ts` (Detox)
   - If it does not exist: `Grep` for the identifier in `tests/` and `e2e/` — it may be in another file
2. **If the test does not exist** → write a short spec following the procedure of section 0.5 + the Recording section of the `playwright.md`/`detox.md` guidelines. Use `telesma/spec/ux_ui/` through SPEC_INDEX as the reference for the look.
3. **Run the test**, verify that the file `telesma/artifacts/screens/<id>.png` appeared
4. **Entry in REPORT.md** `## Visual artifacts`:
   ```
   | <phase-from-PLAN> | screen | <id> | telesma/artifacts/screens/<id>.png | telesma/spec/ux_ui/<file>:<lines> |
   ```
   If the candidate did not come from PLAN.md (only from the ux_ui scan) → `<phase> = -` or `backfill`

#### Flow `step-<N>`

1. **Load the Step fragment** from the flow file through `## Flows` in SPEC_INDEX (line range → `Read(offset, limit)`)
   - If SPEC_INDEX does not have `## Flows` yet → do a mini-update now (section -1, Step 1)
2. **Find the e2e test for this Step**:
   - Convention: `e2e/specs/flows/step-<N>-*.spec.ts` (Playwright) or `e2e/flows/step-<N>-*.e2e.ts` (Detox) — the slug after `-` varies
   - If it does not exist: write it following the procedure of section 0.5 (mirror the Step's prose as actions + assertions)
3. **Turn recording on** in the test config (`video: 'on'` Playwright, `--record-videos all` Detox) — see the Recording section of `playwright.md`/`detox.md`
4. **Run the test**, move the video from the default location to `telesma/artifacts/flows/step-<N>-<slug>.<ext>` (slug = the step title in kebab-case)
5. **Entry in REPORT.md** `## Visual artifacts`:
   ```
   | <phase> | flow | step-<N> | telesma/artifacts/flows/step-<N>-<slug>.<ext> | <file>:<lines> |
   ```

### Step 4: Error handling per target

Generating a single artifact **does not block** the others. Per target:

| Situation | Behaviour |
|----------|-----------|
| Test written, run green, artifact file created | ✅ entry in REPORT.md |
| Test written, run red (the e2e fails) | ❌ entry in REPORT.md "Problem log" + info `> ⚠ Test fails — step-N skipped`. Continue with the rest. |
| Test written, run green, but the artifact file was not created (recording misconfigured) | ❌ entry in the problems + the suggestion *"check playwright.config.ts / .detoxrc.js"*. Continue. |
| The screen does not exist in `src/components/` (it cannot be shown) | ❌ entry in the problems *"Screen `<id>` does not exist in the code — skipping"*. Continue. |
| Step N in APP_FLOW.md talks about an action that is not implemented | ❌ the test fails normally → falls into the second row of the table |

### Step 5: Finalisation

1. **Commit** everything that was created (new tests + telesma/artifacts/ if `Commit artifacts: yes` + REPORT.md) **in one commit**:
   ```bash
   git add tests/screenshots/ e2e/specs/flows/ telesma/state/REPORT.md
   # when Commit artifacts: yes → git add telesma/artifacts/
   git commit -m "Telesma: regenerate visual artifacts ([N flows], [M screens])"
   ```
   Section 4 (Git safety) applies — no `git add -A`, no `--no-verify`.

2. **Final report** — the signal that the mode has finished:
   ```
   TELESMA ARTIFACTS REGENERATED

   Recordings:   X generated / Y skipped (already exist) / Z failed
   Screenshots:  A generated / B skipped (already exist) / C failed

   New tests:  [list of test files, if any were created]
   Artifacts:  telesma/artifacts/flows/ (X files), telesma/artifacts/screens/ (A files)
   Commit:     <hash> ([N flows], [M screens])

   Details in telesma/state/REPORT.md → ## Visual artifacts.
   ```

3. After the report the session moves into **interactive mode** (section 10) — the user can ask questions, request a forced regeneration of a specific artifact (by deleting the file and running again), etc. From this moment everything is logged to `telesma/state/DECISIONS.md`.

### Boundary vs other modes

| Mode | What it does | Modifies PLAN.md? | Records? |
|------|---------|--------------------|---------:|
| 1 (autonomous) | Works on new tasks in the loop; capture as a side effect (step 11 of the cycle) | ✅ (marks ✅) | Only for the tasks currently being worked on that carry tags |
| 4 (artifacts) | Backfills artifacts for the existing state; does not choose new tasks | ❌ (read-only) | YES — that is the point of the mode |

**When to use mode 4 instead of 1:**
- PLAN.md is already done but there are no recordings (the classic backfill)
- You added `telesma/spec/APP_FLOW.md` after the fact (after filling in the template)
- You changed the config from `Recordings: no` to `Recordings: yes` and want to catch up
- You refactored the UI/flow and want to refresh all recordings (first `rm -rf telesma/artifacts/`, then `-m 4`)

**What NOT to do in artifacts mode:**

- Do not choose tasks from PLAN.md and do not uncheck/check checkboxes
- Do not generate artifacts for Steps/screens that are only drafts (the `TELESMA_APP_FLOW_TEMPLATE` marker, unfilled mockups in `telesma/spec/ux_ui/`)
- Do not write tests that go beyond the scope of the Step/screen (if the test needs an implementation that is missing → an entry in the problems, do not patch the code together)
- Do not commit if **everything** failed (zero artifacts generated) — a report without a commit
- Do not delete existing artifacts or tests (idempotency = skip, do not overwrite)

---

