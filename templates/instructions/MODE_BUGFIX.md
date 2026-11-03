## 11. Bugfix mode (chosen in the console at start)

After loading the context, the `telesma.sh` script asks the user for the working mode (a console menu or the `-m 1/2` flag). **Bugfix** mode (mode=2) is an iterative conversation with the user about fixing bugs — no autonomous loop, no choosing tasks from PLAN.md, no processing of `telesma/changes/`.

You recognise the mode by the `MODE: bugfix` directive at the end of the startup prompt (after the `# Pending changes` section). The `MODE: autonomous` directive (or its absence) = the standard cycle of section 1.

### Rules on entering bugfix mode

1. Do NOT run the cycle of section 1 (autonomous task selection)
2. Do NOT process `telesma/changes/` (section 0.3 skipped — it is the channel for functional changes, not fixes)
3. Do NOT modify checkboxes in PLAN.md and do not add tasks
4. Greet the user briefly: `"Bugfix mode active. Give me the bug (error message, stack trace or a description of the behaviour) — I will diagnose and fix it."`
5. Wait for a user message describing the bug

### Per reported bug

1. **Diagnosis**:
   - Read the logs/stack trace/message from the user's message
   - Locate the source file (Grep for the function/class/message name, Read the surrounding lines)
   - If the bug concerns a requirement — read the relevant spec fragment through SPEC_INDEX (section 0.1)
   - **Recall (section 0.6)**: Grep the error message, the function or the module in
     `telesma/state/BUGFIXES.md`, `DECISIONS.md`, `CONTEXT_ARCHIVE.md`, `REPORT_ARCHIVE.md`. The
     same bug fixed before means the earlier fix did not hold — say so, and the diagnosis starts
     from why. A decision that explains the behaviour ("we agreed the import skips rows without a
     date") means it may not be a bug at all: tell the user what was agreed and when, before
     proposing a change.
   - Load the guidelines `general.md` + the tag implied by the modified file (e.g. `python.md` for `.py`, `react.md` for `.tsx`)

2. **Fix proposal** — present it to the user in 2-4 sentences:
   - Where the problem is (file:lines)
   - What you propose to change
   - Whether you see a regression risk elsewhere

3. **Wait for approval**:
   - OK / do it / yes → go to the implementation
   - Change / differently / a comment → update the proposal and go back to step 3
   - Questions → answer and go back to step 3

4. **Implementation** — Edit/Write on specific files (following the loaded guidelines)

5. **Test** — run the tests of the area the fix concerns (command from `telesma/config.md`):
   - Green → OK
   - Red → diagnose iteratively (max tries per config), then TELESMA BLOCKED
   - No test → run the nearest logical suite (module/file) or note `no test — verified manually` in the BUGFIXES.md entry

6. **Commit** (if `Auto-commit: yes` in the config):
   ```bash
   git add <specific files>
   git commit -m "Telesma: fix [short description]"
   ```

7. **Entry in `telesma/state/BUGFIXES.md`** with the Edit tool (append at the end of the file):
   ```markdown
   ## YYYY-MM-DD HH:MM — [short bug description, 3-7 words]
   **Kind**: [exactly one word: bug | correction | feature — `bug`: something built does not work;
   `correction`: it works as agreed, it is to work differently; `feature`: a new function reported in this mode.
   The mode is called bugfix, but it is sometimes used for small development — label honestly what it was.]
   **Bug source**: [only when Kind = bug: task X.Y, which built what does not work — from `git log -S`
   or `git blame` on the fixed fragment; cannot be established in two minutes → unknown. From this field
   telemetry attributes the bug to the framework version under which it was INTRODUCED, not the one under which it was reported.]
   **Detected by**: [only when Kind = bug: test | scenario | review | telesma | owner | production —
   which line of defence caught the bug; `production` = after a release, `owner` = before a release, while working with the application]
   **Symptom**: [what the user reported — paraphrased/shortened to 1-2 sentences]
   **Cause**: [diagnosis: where and why, 1-3 sentences]
   **Fix**: [what was changed — files + the essence, 1-3 sentences; NO full diff]
   **Test**: [command and result, or "no test — verified manually"]
   **Commit**: [short hash + title, or "no commit (Auto-commit = no)"]
   ```
   Date format from `date '+%Y-%m-%d %H:%M'`.

8. **A pitfall for the next session.** When the cause is a pattern that will come back on similar
   code — an API quirk, an ordering rule, a convention nobody wrote down ("the ORM needs a flush
   before the id is readable", "component X swallows `onChange` when `value` is undefined") — add
   ONE row to `## Known problems and solutions` in `telesma/state/PROJECT_CONTEXT.md`: the pitfall,
   the fix in a few words, and the pointer `→ BUGFIXES.md YYYY-MM-DD HH:MM` to the entry you just
   wrote. Apply section 7's rule: the SECOND time the same pitfall is fixed, it gets a guard in
   code (`→ guard: <name>`), not a stronger note. A typo, a one-off slip or a bug in logic that
   exists in one place stays only in BUGFIXES.md — the table is loaded into every session and
   earns its place only with things that recur. Bugfix mode is the only place where the
   distillation of section 7 does not run on its own (there is no end of phase here), so this
   step is the one that keeps production bugs from being fixed from scratch twice.
   An entry whose cause is a `Key decisions` row that turned out wrong → supersede that row
   (section 7), do not leave it standing next to the fix.

9. **Version proposal** — if there was a commit: one sentence in the short form of section 15.1
   ("The fix is in the repo. Release it as version vX.Y.(Z+1)? …"). "yes" → section 15 (scenarios file,
   release version tag, push command); "no" → nothing, the fix goes into the next release. A user who
   said "do not ask about releases" is not asked until the end of the session.
10. After writing the entry — stay in bugfix mode, wait for the next report. The session ends when the user closes the CLI or asks for a restart.

### What NOT to do in bugfix mode

- Do not add new functionality — only fix existing functionality
- Do not refactor beyond the minimum needed for the fix (a bug fix does not need surrounding cleanup)
- Do not modify `telesma/spec/`, `telesma/changes/`, `telesma/state/PLAN.md`
- Do not log to `telesma/state/DECISIONS.md` — that is for design decisions from interactive mode (section 10), fixes go to BUGFIXES.md
- Do not commit code that does not pass its tests (unless the user explicitly asks)

### A fix that requires a change of scope

If the diagnosis shows that the "bug" is really a functional gap or a design error that needs a new task:

1. Explain to the user: "This is not a bug — it needs a new task in PLAN.md"
2. Propose the task content (which phase, which tags, the description)
3. Ask the user to restart in mode 1 (`./telesma.sh -m 1`) — the autonomous loop will take up the new task
4. Do NOT add the task yourself in bugfix mode

---
