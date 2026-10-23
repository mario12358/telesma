## 10. Interactive mode — log to `telesma/state/DECISIONS.md`

After `TELESMA COMPLETE` (or when the autonomous loop stops for another reason — `TELESMA BLOCKED`, the end of the active phases, a manual pause by the user) the Claude CLI session stays open and the user moves into **manual interaction**: asks questions, requests changes, agrees on the direction of further work. Append **every such exchange** to `telesma/state/DECISIONS.md` as one entry — it is a changelog for the human showing "what we agreed on during the project, and why".

**When to log:**
- Every answer to a user message in interactive mode (after TELESMA COMPLETE/BLOCKED, or when the `Active phases` have run out and Telesma has no tasks left to take)
- You **do not log** exchanges from the autonomous phase (the iteration cycle of section 1) — those are in `telesma/state/REPORT.md`
- You log **everything** in interactive mode: educational questions, requests for explanation, design agreements, debugging, small changes. You do no filtering — the file is a changelog for the user, and they decide what is valuable to them.

**On entering interactive mode — once:** if there are commits since the last version (the `VERSIONS:` line
in the prompt or `git log $(git describe --tags --abbrev=0 --match 'v*')..HEAD --oneline`), and the last
full suite in REPORT.md was green — a full release proposal in the format of 15.1, before you start
answering the user's questions. One proposal per session; another one only after new work.

**Procedure per exchange:**

1. Answer the user normally (a full answer — code, explanations, everything as usual in a chat)
2. **Append an entry to `telesma/state/DECISIONS.md`** with the Edit tool (append at the end of the file):
   ```markdown
   ## YYYY-MM-DD HH:MM — [short topic, 3-7 words]
   **Kind**: [exactly one word: bug | correction | feature | question | operations]
   **Bug source**: [only when Kind = bug: task X.Y, which built it | unknown]
   **Detected by**: [only when Kind = bug: test | scenario | review | telesma | owner | production]
   **Question/context**: [1-2 sentences — what the user asked or brought up, a paraphrase, not a quote]
   **Outcome**: [2-4 sentences — the essence of your answer: a decision, a recommendation, an explanation. NO code, NO full file lists, NO long technical explanations. If a design decision was made — state it outright ("we agreed that X").]
   **Impact** (optional): [task X.Y / file / phase, if the exchange concerns something specific]
   ```
   **Kind** — one word, always: `bug` — something already built does not work, or works differently from what the task/agreement said (test: had it worked, this exchange would not have happened) · `correction` — it works as agreed, but the user now wants it differently · `feature` — new scope · `question` — an explanation or analysis without
   a change to the project · `operations` — deployment, server, release, environment. An exchange that
   started as a question and ended with a fix is a `bug`. Label honestly: `bug` is not a judgement
   of anyone's work, it is the only signal from which the framework can later be improved —
   an entry about something broken described as `feature` erases that signal.
   `Bug source` — only with `Kind: bug`: the number of the task that built what does not work
   (`git log -S'<distinctive fragment>' --oneline` or `git blame` points at the commit, and its subject —
   at the task). Cannot be established in two minutes → `unknown`. Without this field the bug is charged
   to the framework version under which it was REPORTED, not the one under which it was INTRODUCED — and
   every new version looks bad because of defects inherited from earlier ones.
   `Detected by` — only with `Kind: bug`, one word: `test` (a later automated test or the
   full suite) · `scenario` (a manual test before a release) · `review` · `telesma` (you found it yourself during other
   work) · `owner` (noticed while working with the application, before a release) · `production` (after a release:
   a user, monitoring, a log). Two frameworks with the same number of bugs differ fundamentally if one
   catches them with tests and the other at the customer's — this field makes that countable.
3. **Dual-write for decisions with architectural consequences:** if the outcome changes the architecture,
   a convention or the direction of further work (e.g. "we are moving to X", "/api/v2 endpoints instead of /api",
   "we are dropping module Y") — add it ALSO to the `Key decisions` table in
   `telesma/state/PROJECT_CONTEXT.md`. DECISIONS.md is write-only and the next autonomous session will NOT
   read it — without the dual-write an agreement from the conversation is invisible to mode 1. Educational questions
   and small explanations stay only in DECISIONS.
   The `Key decisions` table rotates into `telesma/state/CONTEXT_ARCHIVE.md` (the last 40
   rows stay), so mark a decision that is **still binding** — one whose violation would break the project —
   with `📌` in the Decision column: a row with 📌 stays in the file forever. One-off
   resolutions (a choice between two equivalent options in a specific task) stay unmarked.
   The same applies to the `Known problems and solutions` table (the last 30 rows stay):
   a pitfall that **came back despite being written down** gets a guard in code (a test, a linter rule, a `grep`
   in the smoke suite) and the note `→ guard: <name>` — a pinned note does not stop an error
   made by reflex (section 7). `📌` only for pitfalls that cannot be checked
   mechanically. Leave a one-off slip unmarked; it should rotate out once it is no longer fresh.
4. Beyond that — no committing, no report in REPORT.md, no other actions. The file grows chronologically.

**What does NOT go into an entry:**
- Code (snippets, diffs, file contents)
- Full tool output (Bash output, file lists from ls)
- Quotes of the user's message longer than 1 sentence — always paraphrase
- Your full answers — only the essence (2-4 sentences)

**Date format:** use the current system date/time (Bash: `date '+%Y-%m-%d %H:%M'`).

**The file is not loaded by Telesma in any other process** — it is a write-only changelog for the user. Do not use it as a source of decisions in the autonomous loop, do not read it at start, do not reference it in PLAN.md.

**Example entry:**
```markdown
## 2026-04-23 16:42 — Changing the API caching strategy
**Kind**: question
**Question/context**: The user asked whether it is worth moving the cache from Redis to in-memory for the /api/products endpoints.
**Outcome**: We stay with Redis. In-memory would improve latency by ~5ms, but we would lose cache consistency between instances (we run 3 pods). If we ever scale down to a single pod or accept stale data — we revisit the topic.
**Impact**: Task 4.3 (cache layer) — left as it was.
```

## 13. BACKLOG — the channel for "topics for later"

`telesma/state/BACKLOG.md` is a list of TODOs/ideas/debt picked up during interactive sessions. **Read-write** (the difference from DECISIONS/BUGFIXES/REVIEWS — write-only changelogs). Active in the interactive modes: section 10 (after TELESMA COMPLETE/BLOCKED), 11 (bugfix), 12 (review).

In autonomous mode (1) BACKLOG is not modified — the read exception is described below.

### Entry format

```markdown
- [ ] **Title** — `P2` `chat`
  - **Context**: 2026-05-19, test session B2. The user noticed that the AI ignores meta-questions about the conversation history.
  - **Suggested solution**: add a "META-QUESTIONS ABOUT THE CONVERSATION" section to the chat orchestrator's system prompt.
  - **Dependencies**: [item X] (optional)
```

Priorities: `P0` (critical, for the next session) → `P1` (important, for the current phase) → `P2` (nice to have) → `P3` (an idea for the future).

### 13.1 When to add (heuristics + confirmation protocol)

Catch the signals in the conversation:
- The user says: "that's for later", "we'll fix that some day", "that's a topic for a separate session", "let's leave that"
- In a bugfix diagnosis (section 11) or a review (section 12) you caught something **outside the scope** of the current problem that is worth remembering
- The user points out a weakness/limitation but does not ask for a fix now
- Claude proposes 2-3 improvements, the user picks one → the rest → a signal for BACKLOG

**Confirmation protocol (MANDATORY — do not add without the user's OK):**

1. Once you catch a signal, propose briefly to the user:
   ```
   This sounds like a BACKLOG topic. I propose adding:
   - Title: [short title, 3-7 words]
   - Priority: P2 (nice to have)
   - Area: [chat | b1 | nav | tests | infra | ...]
   Add it? (yes / other priority / other area / skip)
   ```
2. **yes** → add the entry (Edit, append; if a `## <area>` section exists, add it there; if not — under `## Unclassified (to triage)`)
3. **other priority/area** → use the user's value, add it
4. **skip** → do not add, remember the decision for the current conversation (do not ask again about the same topic)

Date format from `date '+%Y-%m-%d'`.

### 13.2 Promoting BACKLOG → telesma/changes/

When an item becomes a formal change of requirements/functionality (with an effect on PLAN.md):

1. The user says: "promote X from BACKLOG to telesma/changes/" (X = the title or a fragment of it)
2. Read the full text of the item from BACKLOG.md
3. Generate a slug from the title (lower-case, dashes, max 40 characters)
4. Create `telesma/changes/<slug>.md`:
   ```markdown
   ---
   date: YYYY-MM-DD
   priority: <normal | critical>   # P0 → critical, P1-P3 → normal
   affects: <context from the BACKLOG item, or "general">
   ---

   # <item title>

   <suggested solution + context from BACKLOG, expanded into a formal description of the change>
   ```
5. Mark the item in BACKLOG.md (keep `[ ]`, add a suffix):
   ```markdown
   - [ ] **Title** [→ telesma/changes/<slug>.md] — `P2` `chat`
   ```
6. Commit together: `git add telesma/state/BACKLOG.md telesma/changes/<slug>.md && git commit -m "Telesma: promote BACKLOG → telesma/changes/<slug>"`
7. Tell the user: "Promoted. The next run in mode 1 will process the change through section 0.3."

### 13.3 Ad-hoc execution (from interactive mode)

The user may say "do item X from BACKLOG" in mode 10 or 11:

1. Read the full text of the item
2. Implement following the guidelines (general.md + the tech tags implied by the area)
3. Test (command from `telesma/config.md`)
4. Commit as `Telesma: <item title>` (if `Auto-commit: yes`)
5. Mark the item `[x]` + the commit hash:
   ```markdown
   - [x] **Title** (abc1234) — `P2` `chat`
   ```
6. If this happened in bugfix mode (11) → also add an entry to BUGFIXES.md (if applicable — a bug fix)

### 13.4 Archiving (lazy cleanup)

At Telesma's start (section 0):

1. Check `telesma/state/BACKLOG.md` — count the `[x]` items whose commit date is older than 30 days (read the hash in parentheses → `git show <hash> --format=%cs`)
2. If there are >10 such items → **IN INTERACTIVE MODE** (10/11/12) propose to the user:
   ```
   BACKLOG.md has N completed items older than 30 days. Move them to BACKLOG_DONE.md? (yes / no)
   ```
3. **yes** → create/append to `telesma/state/BACKLOG_DONE.md` (append + a `## Archived YYYY-MM-DD` header per batch), remove the moved items from BACKLOG.md, commit together
4. **no** or **autonomous mode (1)** → skip, check again at the next run

In mode 1 do NOT suggest archiving — do not clutter the autonomous loop.

### 13.5 Exception for autonomous mode (1)

Mode 1 generally **does NOT read or modify BACKLOG**. The only exception: when the autonomous loop exhausts all active phases (before the TELESMA COMPLETE message of section 9), Claude checks BACKLOG:

- Read BACKLOG.md (once, at the very end of the loop)
- If there are `P0` or `P1` items not marked `[→ telesma/changes/...]` → **before** TELESMA COMPLETE insert this information:
  ```
  BACKLOG has N P0/P1 items that were not promoted:
  - [title 1] (P0)
  - [title 2] (P1)
  Suggestion: consider promoting them to telesma/changes/ in interactive mode before you close the phase.
  ```
- After the message go on as usual to TELESMA COMPLETE (section 9), then section 10 (interactive mode), where the user can decide on promotion

### What NOT to do in this channel

- Do not add without the user's confirmation (the heuristics are a PROPOSAL, not an auto-write)
- Do not BACKLOG things that belong to other channels:
  - **A design decision** (e.g. "we agreed that X") → DECISIONS.md (section 10)
  - **A fix of a current bug** → BUGFIXES.md (section 11)
  - **A finding from a review** → REVIEWS.md (section 12) with the "TODO" action
  - **A concrete spec change** the user wants to make → telesma/changes/<file>.md (section 0.3) directly, without BACKLOG
- Do not modify BACKLOG in autonomous mode (1) — exception 13.5 covers only **reading** + a suggestion
- Do not delete `[x]` items right away — they stay ~30 days for audit (then archiving to BACKLOG_DONE.md)
- Do not log BACKLOG entries into DECISIONS.md (it blurs the purpose of both channels)

## 15. Releasing a version (tag `vX.Y.Z`)

A version (`vX.Y.Z`) marks **a state released to production**, not a completed phase. The `telesma/phase-*` tags
from section 2 are something else — internal progress markers for rollback and `git bisect`. Do not mix them:
a phase tag is created automatically after a green suite, a release version tag is **never** created without the user's
decision.

**Vocabulary when talking to the user: say "version".** The word "tag" on its own makes the user think of `(tech:)`
on tasks and of `telesma/phase-*`, so when writing about a release say "release version vX.Y.Z" or "version vX.Y.Z" —
never a bare "tag". The user does not need to know that a version is technically a git tag.

### 15.1 When you propose — and how

You propose a release **at each of these moments**, not only after a phase:

| Moment | Form |
|--------|-------|
| green full suite after a phase (section 2) | full proposal (block below) |
| `TELESMA COMPLETE` (section 9), when there are commits since the last version | full proposal, **before** the final message |
| entering interactive mode for another reason (section 10) — tasks finished, `TELESMA WAITING`, `TELESMA BLOCKED` — when there are commits since the last version and the last full suite in REPORT.md was green | full proposal, once per session |
| after a fix commit in bugfix mode (section 11) | short: one sentence with the patch number |
| the user asks for a version | no proposal — you create it right away (after 15.5) |

**Full proposal** — always the same block, so the user recognises it at a glance:

```
📦 RELEASE PROPOSAL — version vX.Y.Z
Previous version: vA.B.C (<date>), <N> commits since then, phases: <list>.
What landed: <2–3 sentences in product language — what the user can see or do, not task numbers>
Number: minor, because features were added  |  patch, because only fixes
Attack surface: <from the VERSIONS: line: new routes, public ones among them, role changes> — this line only when there is one
Answer "yes" (or give another number) → I create the release version vX.Y.Z, write
docs/test-scenarios/vX.Y.Z.md for the testers and give you the push command.
"no" or no answer → I go back to the loop and will ask after the next phase.
```

**Short proposal** (bugfix): "The fix is in the repo. Release it as version vX.Y.(Z+1)? "yes" →
I create the release version per section 15; "no" → it waits for the next release."

Rules:

- No answer = no version. Do not tag "just in case", do not ask the same thing twice
  in the same situation — ask again only once something new has landed (another phase, another fix).
- A user who once answered "do not ask about releases" — you do not ask until the end of the session; an entry in DECISIONS.md.
- You get the data for the block from `git describe --tags --abbrev=0 --match 'v*'` (15.2) and
  `git log <previous>..HEAD --oneline`; the startup script also gives them in the `VERSIONS:` line of the prompt.
- The proposal is **visible**: a separate paragraph, not a sentence folded into the phase report.

### 15.2 The number

```bash
git describe --tags --abbrev=0 --match 'v*'   # the last version = the starting point
```

`--match 'v*'` is required — without it `describe` returns the nearest `telesma/phase-*` tag.

- **minor** (`v1.4.0` → `v1.5.0`) — features were added
- **patch** (`v1.4.0` → `v1.4.1`) — only a fix
- **major** — only on the user's explicit instruction

No `v*` tag at all → propose `v0.1.0`.

### 15.3 What you do — exactly this and nothing more

**Step 1 — the manual test scenarios file** `docs/test-scenarios/vX.Y.Z.md`
(file name = tag name). It is created **before** the tag and becomes part of the tagged state —
otherwise it describes a version it is not part of. Template and rules: **section 15.7**.

**Step 2 — commit** the scenarios file (the tree has to be clean before the tag, condition 15.5).

**Step 3 — the release version tag:**

```bash
git tag -a vX.Y.Z -m "<2-4 sentences: what was added, who it matters to>"
```

Build the message from what **actually landed** since the previous tag:

```bash
git log <previous-tag>..HEAD --oneline
```

In product language, not task numbers — "Added CSV export of reports and filtering by date",
not "Tasks 4.1–4.6". No file list, no commit list. PLAN.md says what was *planned*,
git says what *landed* — for a release the latter is what counts.

### 15.4 What you do NOT do

- **You do not push the release tag — ever.** Not with `Auto-push: no`, not with `Auto-push: yes`, not
  with the GitHub integration (which lets you push task branches, not tags). `git push origin vX.Y.Z`,
  `git push --tags` and `--follow-tags` are the user's commands; the permission hook refuses them. After
  the tag give the user the command:

  ```bash
  git push origin vX.Y.Z
  ```

  and say **explicitly**: tags do not travel with a plain `git push`. Without this step the tag exists only
  locally — this is the moment that gets lost.
- You do not merge into `main`, you do not deploy.
- You do not touch files with a version number (`package.json`, `pyproject.toml`, `VERSION`) — the version is
  derived from git when the image is built, there is nothing to bump in the repo.

### 15.5 Blocking conditions — do not create the version, say why

1. **The full suite is not green.**
2. **`git status --porcelain` is not empty** — a tag on a dirty tree points at a state nobody can later
   reproduce; with `git describe --dirty` in production it would also look clean, because the tree
   there already is clean.
3. **A tag with that name already exists** (`git tag -l vX.Y.Z`) — propose the next number.

`-f` on version tags is **forbidden** (unlike `telesma/phase-*`) — a release is immutable.

### 15.6 After creating the version (tag)

Both steps apply in every mode, including the autonomous loop (mode 1) — a release made without
the user watching still gets its entry and its message.

1. An entry in `telesma/state/DECISIONS.md` (format from section 10, `Kind: operations`): the version
   number + a one-sentence scope. Write it in the same step as the tag, before anything else.
2. The message to the user — one block, in this order:

   ```
   ✅ VERSION vX.Y.Z created (git tag, commit <sha7>).
   Scenarios for testers: docs/test-scenarios/vX.Y.Z.md — a click-through list before deployment.
   The version is local only for now. Send it: git push origin vX.Y.Z
   (tags do not travel with a plain `git push`).
   ```

Nothing beyond that.

### 15.7 The manual test scenarios file

**Why:** automated tests are green by definition (without that there is no tag). This file collects
**only what the automation could not check**: the look, behaviour on real data,
paths through external services, things that need production. Without it the release goes out on
"it probably works".

**Where:** `docs/test-scenarios/vX.Y.Z.md`. The directory may already contain older files — **do not
change them** and do not try to merge them.

**Skeleton:** `telesma/state/TEST_SCENARIOS_TEMPLATE.md` — the only source of the file's structure.
Read it and fill it in; do not reproduce the layout from memory and **do not modify the template itself**
(the user may have adapted it to their stack). Sections that have no content in this release
(e.g. barriers, when nothing new was added) simply delete from the copy.

**Where the content comes from:** from `git log <previous-tag>..HEAD` and from the `<!-- -->` comments on
tasks closed in that range in `telesma/state/PLAN.md` — that is where the findings and deliberate
deviations sit, i.e. the best candidates for a scenario. **Do not rewrite the automated tests.**

**`telesma/spec/APP_FLOW.md` — how to use it (if it exists).** The Steps are already written in the user's
language and in clicks, i.e. in the format the template requires — do not invent paths, point at the Step.
You have the line ranges in the `## Flows` section of `telesma/state/SPEC_INDEX.md`, so you do not read the whole file.

- **A Step with a green e2e test → does NOT go into the functional sections.** The automation has just walked
  that path; rewriting it breaks the rule "only what the automation could not check", and that is
  the most common source of checklists nobody reads to the end.
- **A Step without an e2e test, touched by the change → a prime candidate for section 1.**
- **The regression section = a list of the Steps that go through the changed code**, by name and as a pointer
  (`Step 3 — Creating a project (telesma/spec/APP_FLOW.md)`), without rewriting the steps themselves.
- **When `Recordings: yes` and `telesma/artifacts/flows/step-N-<slug>.<ext>` exists for a touched Step** —
  add the path to the recording next to the scenario. The tester gets a "this is how it should look" reference instead of
  reconstructing the expected state from a description.

**Marking convention (one, at the top of the file, taken from the template):**
`[x]` = checked and works · `[-]` = checked and does NOT work · `[ ]` = not checked.
**One scenario = one checkbox** — the line `- [ ] **Result N.M**` at its end. "Expected"
and "Failure signal" are plain text, not separate fields to tick (otherwise nobody knows what
a ticked failure means). For `[-]` ask for one sentence: what the user saw instead of the expected outcome.

**Content rules:**

- **"Failure signal" is mandatory** on every functional scenario. Without it it is easy
  to accept as correct something that only looks familiar.
- **A barriers section** (things that must be rejected) — if the release adds any
  limit, validation or permission. A test that something does **not** work is just as important.
- **Mark what cannot be checked on dev** and why (a different provider, no traffic, no
  historical data). Silence in such a scenario is no proof that it works.
- **Zero description of the implementation.** File and class names only when the user really has to look there
  or add something by hand.
- **Order: first what used to be a defect**, then new features, regression at the end.
- Leave room for a measurement (`**Measured result:** ____`) wherever an acceptance criterion
  speaks of a number that could not be measured in tests.
- **Take the commands from the project's stack**, not from examples: migrations and starting the environment from
  `docs/RUNBOOK.md`, test counts from the suite defined in the `## Tests` section of `telesma/config.md`.

---

