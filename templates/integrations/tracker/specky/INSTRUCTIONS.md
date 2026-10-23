## 18. Integration: requirement tracker (Specky)

Active because `telesma/config.md` → `## Integrations` has `Tracker: specky`. Specky is the source of truth
for requirements and criteria; `telesma/spec/` in the repo stays frozen, and requirement changes come in through
`telesma/changes/` (section 0.3) — this section only says **where** those files come from and **what** you add to
commits, tests and the plan. `project_id` = the `Tracker project` field. Sync state:
`telesma/state/SPECKY.md` (committed).

Two MCP servers, one token (as a plugin: `plugin:specky:specky` and `plugin:specky:specky-record`):

| Server | Tools you use |
|--------|---------------|
| **core** (`/mcp`) | `whoami`, `list_projects`, `get_spec_markdown`, `get_requirement`, `what_changed`, `get_work_queue`, `check_anchors`, `propose_requirements`, `propose_requirement_edit`, `raise_spec_issue`, `set_requirement_in_progress`, `set_requirement_code_ready`, `mark_criteria_tested`, `list_snapshots`, `create_snapshot` (the last one only at a release, 18.7) |
| **record** (`/mcp/record`) | `get_requirement_history` (before → after of a requirement), `diff_snapshots`; `record_decision` and `create_project` only at the human's explicit request |

Specky's rule applies in full: you **propose** (`propose_*`), a human decides. A loop without a human gets
`decision_requires_interactive_client` for every decision — do not work around it. The claude.ai connector
is a client with `can_decide: false`; decisions need the plugin and a human in the conversation.

### 18.1 Session start — synchronization (once per session, BEFORE section 0.3)

1. `whoami(project_id)` → one sentence into REPORT.md → Summary: "Specky: working as {display_name}
   ({email}), organization {organization_name}, client {client_class}". The project missing from the list →
   TELESMA BLOCKED (a token for another account/organization — do not guess). `can_propose: false` →
   TELESMA BLOCKED at once: this client cannot even propose, the loop has nothing to work with.
2. `what_changed(project_id, since_seq)` with the cursor from `telesma/state/SPECKY.md`; the first session
   passes `since_seq=0` explicitly (without the argument the server uses a cursor it remembers per MCP
   client, and a client without one gets "since_seq is required"). The answer has `items` (each with
   `kind` and `informational`), `next_seq` and `more_after_next_seq` (a page holds at most 50). With
   `more_after_next_seq: true` call again from `next_seq` **before** you move the cursor in the file.
   Items with `informational: true` (`snapshot_created`, `requirement_superseded`) get no file — one line in
   REPORT.md at most. Then `get_work_queue(project_id)`.
3. Every item that needs work → **one file** `telesma/changes/<YYYY-MM-DD>-specky-<7 characters of the id>.md`:

   ```markdown
   ---
   date: 2026-09-25
   kind: bug | correction | feature
   affects: <spec section / task X.Y from telesma/state/SPECKY.md, if known>
   specky_req: <requirement_id>
   specky_hash: <content_hash, 7 characters>
   specky_reason: <the queue key or the what_changed kind this came from>
   pr: <#n, when the item concerns a PR>
   ---
   # <requirement / queue item title>
   <content: what changed (before → after from get_requirement_history — record server), which criteria,
    the note from the queue (to_fix_note, open_matters), what to adjust>
   ```

   What becomes a file, and with which `kind`:

   | From `get_work_queue` | Meaning | File |
   |---|---|---|
   | `work_queue` (`to_fix`, with `to_fix_note`, `needs_reimplementation`, `open_matters`, `external_ref`) | the human sent the requirement back | `bug` (+ `**Bug source**` from the requirement → task map) |
   | `failing_pull_requests` | a PR whose contract does not match; the fix goes **onto that branch**, never a new PR | `bug` with `pr:` |
   | `drift_after_code_ready` | the text changed after you set code_ready | `correction` |
   | `stale_evidence` | a criterion changed after its test passed — test it again | `correction` |
   | `superseding_built` | a successor of a requirement you built — adapt the code, do not rebuild | `correction` |
   | `stale_decisions` | a technical decision no longer current | `correction` |
   | `my_decided_proposals` with a rejection | your proposal was rejected | `correction` |
   | `to_build` + `counts` (`in_progress` with `started_by`, `open`) | the remaining work | no file — the numbers go into REPORT.md |
   | `inactive_requirements` | accepted, no movement for N days — a question for the human | no file — one line in REPORT.md |
   | `pending_proposals`, accepted `my_decided_proposals` | your proposals awaiting / accepted; an accepted one maps `external_ref` → `requirement_id` | no file — update the map in `telesma/state/SPECKY.md` |
   | From `what_changed` | a new accepted requirement | `feature` |
   | | an edit of an existing requirement | `correction` |

   The kind test as in section 0.3: "had it worked, would this entry exist?".
4. You move the `since_seq` cursor and the date in `telesma/state/SPECKY.md` **only after the files are written**
   (an interrupted session = nothing is lost, at worst a file is created twice — section 0.3 handles that).
5. Zero items → one line in REPORT.md, carry on as normal. Files exist → section 0.3 as always.

Queue items concerning a PR (`failing_pull_requests`, `to_fix`) have **precedence** over new tasks from
the plan — section 0.3 turns them into a task/rework phase, and with the GitHub integration (section 17.4)
the fix goes onto that PR's branch.

### 18.2 Before a task — anchors (after step 3 of section 1)

A task has lines `- Specky: (req: <id> v<n>.<r> @<hash7>)` (one per requirement; `n` = text version, `r` =
criteria revision) and optionally `- Specky criteria: (crit: <id>) …`. Before coding:

1. `check_anchors(project_id, items=[{requirement_id, version_number: <n>, criterion_ids, content_hash: "<hash7>"}])`
   for all of the task's anchors. The answer per item: `current` / `stale` / `missing`, with `current_label`,
   `current_hash`, `lifecycle_status`, `missing_criteria`. With a hash given, freshness is decided by the
   **hash**, not the number (an added criterion creates no text version); `stale` also covers a changed
   lifecycle (deprecated, superseded).
2. `stale` → `get_requirement` (full, current content + `content_hash`) — you read it **before**
   implementing, update the anchor line in PLAN.md to `current_label` / `current_hash` and note in
   REPORT.md what changed. A change that invalidates part of the plan → a file in `telesma/changes/`
   (18.1 point 3), not a silent fix. `missing` → the requirement is gone: a file in `telesma/changes/`
   (`correction`) and the task waits for the human.
3. A task without anchors although it implements a requirement (visible from `spec:` or its content) →
   find the requirement in `get_spec_markdown(project_id)`, take its id, version and hash from
   `get_requirement`, add the anchor and a row to the map in `telesma/state/SPECKY.md`.
4. `set_requirement_in_progress(requirement_id)` — records the hash you start from. A refusal
   `requirement_not_accepted` means a draft: do not retry, take the next task or `raise_spec_issue`
   (18.8). A `to_fix` requirement may go back to `in_progress` — that is the normal path of a fix.

### 18.3 Commit — trailer and code ready (supplement to section 4)

Every commit implementing a requirement ends with a trailer (after an empty line, above the footer
`🤖 Generated with Telesma`):

```
Specky-Req: <requirement_id>@<first 7 characters of content_hash>
```

One trailer per requirement; the hash from `get_requirement` **from this session**, not from the anchor in the plan
(the anchor may have been `stale`). A commit with no requirement behind it (tooling, docs, a scenarios file)
carries `Specky-Req: none` — a repository connected to Specky **requires** a trailer (`require_trailer`): a PR
without one gets the status `failure`, `none` gives `neutral`. With the GitHub integration the trailer also
goes into the PR body (17.3 step 4); the PR is merged only with the Specky status `success`.

After the PR merge / after the commit that completes the requirement:

```
set_requirement_code_ready(requirement_id, requirement_hash=<content_hash from get_requirement in THIS session —
                           the same one the trailer's 7 characters come from>)
```

- `missing_requirement_hash` — you called it without the hash; call again with it.
- `stale_requirement_hash` — the text changed since you started. `get_requirement`, compare with what you
  built; adjust the code and fix the trailer (`git commit --amend` on the task branch, before the merge) or,
  when the change is more than you can absorb in this task, `raise_spec_issue` (18.8) and a file in
  `telesma/changes/`. **Never skip silently**: without `code_ready` the release snapshot's "Ready since version X"
  stays empty.

### 18.4 Criterion tests

A test checking a criterion has, **on the line directly above the test**, the comment:

| Language | Where |
|----------|-------|
| Python | `# specky: crit <criterion_id>` above `def test_*` (above the decorators, if any) |
| JS/TS (vitest, jest) | `// specky: crit <criterion_id>` above `it(...)` / `test(...)` |
| Deno | `// specky: crit <criterion_id>` above `Deno.test(...)` |
| Playwright / Detox | `// specky: crit <criterion_id>` above `test(...)` / `it(...)` |

One test can carry several comments (one criterion per line). The proof of a criterion is the result
from CI — the JUnit report from the workflow (`.github/workflows/specky-ci.yml`, an artifact with "junit" in its
name); Specky reads it on the PR and, after the merge, from the run on the default branch.

`mark_criteria_tested(project_id, items=[{criterion_id, criterion_hash, test_ref, commit_sha}])` is the
**fallback**, not the rule: only for a criterion CI cannot prove (a stack whose test markers Specky does not
read, a manual check). `criterion_hash` = the criterion's `content_hash` from `get_requirement`, `test_ref` =
file and test name, `commit_sha` = the commit with the test. An item without the full set lands as
`needs_manual_check` — a question for the human, not evidence. `stale_evidence` in the queue (18.1) = the
criterion changed after the test — run the test against the new text and mark again.

`- AC:` on a task and Specky criteria are the same thing seen from two sides — every criterion from an anchor has a test
with the comment, and a test that does not touch the criterion does not finish the task (section 1 step 10).

### 18.5 Task 1.1 (skeleton) with the GitHub integration

The wizard copied `.github/workflows/specky-ci.yml`. In 1.1 adapt the steps to the stack (runtime
setup, install, the test command with a JUnit report into `reports/*.xml`), **keeping the contract points
from the file's header**: an artifact with "junit" in its name, test steps with `continue-on-error: true` (the
report must exist for a red test too), no path filter in `on:`, `push: branches: [main]` kept (Specky also
collects evidence from the run on the default branch after the merge), a criterion demo as the artifact
`specky-demo-<criterion_id>`. Job name = an entry in `Required checks`.

Verifying the setup on the first PR: Specky's comment shows, next to a criterion with `specky: crit`,
the state ✅/❌ — not ⏳ or "CI did not run it". Any other state → Problem log (`[check]`) and fix the workflow
before taking the next task; without it no PR will pass the contract.

### 18.6 What you do NOT do

- You do not decide in Specky — `accept_proposals`, `reject_proposals`, `decide_realization`,
  `decide_collisions`, `answer_questions`, `endorse_proposal` — even when the server would allow it; in chat
  you call them only at the human's explicit request in this conversation (`whoami` → `can_decide`), and
  `decision_not_confirmed` means nothing was saved: do not retry, ask.
- You do not set `done` or `to_fix` yourself (`agent_can_only_set_code_ready`); `code_ready` is as far as you go.
- You do not call `record_decision` or `create_project` (record server) on your own — a technical decision
  goes into PROJECT_CONTEXT.md; the human records it in Specky if they want it there.
- You do not copy requirements into `telesma/spec/` — `telesma/spec/` is frozen; Specky lives in the anchors and `telesma/changes/`.
- You do not guess `content_hash`, `criterion_id` or `criterion_hash` — always from `get_requirement`.
- You do not move the cursor before the files in `telesma/changes/` are written.
- You do not create snapshots (`create_snapshot`) outside a `vX.Y.Z` release (18.7) — neither on
  `telesma/phase-*` tags nor "as a test": every extra snapshot spoils the next release's "What's new".
- You do not keep notes about Specky in session memory or in files outside `telesma/` — everything the
  next session needs to know is in `telesma/state/SPECKY.md`, PLAN.md (anchors) and REPORT.md.

### 18.7 Release — snapshot in Specky (supplement to section 15.6)

After a successful `git tag -a vX.Y.Z` (15.3 step 3), as **the first point of 15.6**, you freeze the state
of the specification as a version. The tester reads the scenarios in Specky ("Versions and export" → "What's new" →
"How to test"), not in the repo:

```
create_snapshot(
  project_id        = <Tracker project>,
  git_tag           = "vX.Y.Z",
  git_commit_sha    = <git rev-parse vX.Y.Z^{}>,
  test_scenarios_md = <full content of docs/test-scenarios/vX.Y.Z.md, read from disk AFTER the commit>,
  notes             = <the tag message — the same 2–4 sentences>,
  idempotency_key   = "telesma-release-vX.Y.Z-<sha7>"
)
```

**After the tag, not before**: the snapshot carries the SHA of the tagged commit, and the scenarios file sits in that
commit — the copy in Specky and the state under the tag are identical by definition. Before the tag there is no SHA.

**In the scenarios file** (15.3 step 1, i.e. *before* it goes into the commit) add one sentence under the marking
convention: "The scenarios are also visible in Specky (Versions and export → What's new), but
**you record the result here**, in `docs/test-scenarios/vX.Y.Z.md`." The checkboxes in Specky are inactive;
acceptance in Specky is a separate product feature, not this screen.

**What you get for free:** "Ready since version X" counts requirements with the `code_ready`/`done` status
frozen in the snapshot — those are your `set_requirement_code_ready` calls from 18.3. If the phase's last
requirement does not have `code_ready` yet, set it (with its `requirement_hash`) **before** the snapshot,
otherwise it only lands in the next release.

Rules:

- **Specky does not block a release.** The tag and the file are in git; the snapshot is a copy for the tester. Server
  unavailable or a refusal → a `[specky]` entry in the Problem log with the call's parameters and a command
  for the human: `python3 tools/telesma-specky-snapshots.py <project> vX.Y.Z` (a script from the Telesma
  repository, REST with e-mail + password login). The tag stays — you do not revert it or repeat it.
- **`snapshot_tag_exists`** → a snapshot of this version already exists (made by hand on the web, or a repeat).
  Take its id from `list_snapshots(project_id)`, put it in REPORT.md, do not create a second one and **do not
  rename the tag** to "push it through". The frozen state is readable with `get_spec_markdown(project_id, snapshot_id)`.
- **One snapshot per release and only at this point** — see 18.6.
- The content limit is 200,000 characters; Telesma's file is usually 3–15 KB. A bigger one you shorten in the
  regression section (pointers to Steps instead of descriptions), not in the scenarios.

### 18.8 Proposals, spec issues and deprecation

- **A blocker that comes from the specification** (a contradiction, a missing decision, a criterion that cannot
  be tested) → besides `telesma/state/BLOCKED.md`, `raise_spec_issue(project_id, issue_type, description,
  related_requirement_ids)` — the human sees it in the tracker, where they decide, not only in a file.
- **A gap you can fill** (a requirement the spec implies but Specky lacks) → `propose_requirements(project_id,
  items=[…])` with `type`, `scope` and `external_ref: "telesma:<task id>"`. The `external_ref` comes back in
  `get_work_queue` (`my_decided_proposals`), in the PR comment and in `work_queue`, so the requirement → task
  map in `telesma/state/SPECKY.md` fills itself after the human accepts. A proposal is not a requirement:
  no anchor, no trailer, no `in_progress` until it is accepted (`created` in the decision result gives the id).
- **A change to an existing requirement** → `propose_requirement_edit(requirement_id, ops=[…])` with
  `text | add_criterion | edit_criterion | remove_criterion | move_to_section | deprecate | set_source_url`.
  Change a criterion **in place** (`edit_criterion`), never remove-and-add — it carries the history of its evidence.
- **A task that removes or replaces a feature** → `propose_requirement_edit` with
  `{op: 'deprecate', reason, replacement_id?}` on the requirement it implemented; the successor carries
  `supersedes`. A `superseding_built` item in the queue (18.1) is the same thing seen from the other side.
