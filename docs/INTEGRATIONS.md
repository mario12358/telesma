# Integrations: git repository and requirement tracker

By default Telesma **has no integration at all**: it commits to the current branch, never pushes and
knows no requirement tracker. A project without the `## Integrations` section (or with `none` values)
behaves exactly as before. An integration is an optional module that changes the definition of
"task done".

That default is guaranteed structurally, not by promise: the instruction sections of the integrations
(`templates/integrations/<type>/<name>/INSTRUCTIONS.md`) are appended to the startup prompt only when
the config names them, so a project without integrations does not pay a single token for them.

Two integrations exist today, independent of each other:

| Integration | Config field | Instruction section | What it changes |
|-------------|--------------|---------------------|-----------------|
| Git repository (GitHub) | `Repository: github` | 17 | a branch per task → PR → checks → squash merge; a task is done after the merge; open-PR limit; `TELESMA WAITING` |
| Requirement tracker (Specky) | `Tracker: specky` | 18 | requirement anchors in the plan, `Specky-Req:` trailer in commits, `specky: crit` above criterion tests, sync → `telesma/changes/`, release snapshots |

Both at once give the full contract: every PR gets the "Specky contract check" status, and the wizard
copies a CI template that feeds Specky the test results.

## Turning it on

```bash
./telesma.sh --integrations /path/to/project   # wizard on an existing project
./telesma.sh --setup /path/to/project          # the setup menu → 4) Integrations
./telesma.sh /path/to/project                  # the first start asks about integrations in the "full" profile
```

The wizard asks what to connect the project to (`1` GitHub, `2` Specky, `3` both, `N` none), checks the
tools (`gh` installed and logged in, an `origin` remote, what the repository supports: auto-merge,
branch protection), writes the `## Integrations` section into `telesma/config.md`, adds the permissions
the integration needs and prints "how this will work" in about ten lines. Apart from `config.md`
(and `.github/workflows/specky-ci.yml` when both integrations are chosen) it changes nothing. Without
a terminal (CI) it stays silent instead of hanging.

The section in `telesma/config.md`:

| Field | Default | Meaning |
|-------|---------|---------|
| `Repository` | `none` | `github` = a branch per task + PR + merge. Requires `gh` and `Auto-push: yes` in `## Git` (the wizard sets it) |
| `Repo` | — | `owner/name` (the wizard reads it from `git remote get-url origin`) |
| `Merge` | `agent` | `auto` = GitHub auto-merge (a public repo, or a Pro/Team plan with branch protection); `agent` = Telesma waits for the checks and merges itself (works on Free with a private repo); `manual` = the PR waits for a human |
| `Required checks` | `none` | check names, comma-separated; in `agent` mode it must not be empty |
| `Open PR limit` | `3` | limit reached = `TELESMA WAITING`, end of the session |
| `Wait for merge` | `10 min` | how long Telesma waits after opening a PR before taking the next task |
| `Max fixes per PR` | `3` | red check → a fix on the same branch; after this many → `TELESMA BLOCKED` |
| `Branch prefix` | `task-` | task branch `<prefix><id>-<slug>`; push permissions cover this prefix only |
| `Tracker` | `none` | `specky` = requirement anchors, commit trailer, criterion tests, sync → `telesma/changes/` |
| `Tracker project` | — | `project_id` in Specky (a ULID, visible in the project's URL) |
| `Tracker MCP` | `https://app.specky.app/mcp` | address of the MCP server (for documentation and the wizard) |

The validator at startup checks the field values, whether `gh` is installed and logged in, the `gh`
version (≥ 2.41 — the permission judge reads checks with `gh pr checks --json`), and with `Merge: auto`
whether the repository has auto-merge and branch protection. Errors gate the start just like errors in
the `## Tests` section.

## Git repository (GitHub) — how Telesma works

Why this exists: on an early test project the loop finished its whole plan and left **77 open PRs**.
It treated a task as done the moment its PR was opened, knew nothing about required checks or merges,
and chained every new PR on the previous unmerged one. The integration makes the PR flow an explicit
contract instead of something the session improvises.

1. Every task = its own branch `task-<id>-<slug>` off main + exactly one PR (title = the commit
   subject, body = the commit body with its trailers). Telesma never pushes to main.
2. A task is **done after the merge**, not when the PR is opened. In the plan a task with a PR carries
   the tag `(pr: #n)` and the checkbox `[ ]` until the merge; after the merge it becomes `[x]` and the
   tag stays (audit + telemetry). Because the checkbox is what phase completeness reads, a phase is
   not complete until its code is on main.
3. Merge follows the `Merge` field. In `agent` mode GitHub enforces nothing, so the rule "merge only on
   green required checks" is enforced by the **permission judge** (`## Auto-approval`, see
   [PERMISSION_JUDGE.md](PERMISSION_JUDGE.md)), not promised by an instruction: before every
   `gh pr merge` it runs `gh pr checks` itself and lets the merge through only when every required
   check is **present** and green — a missing check is not a green one. Otherwise you are asked. With
   the judge off, every merge asks you.
4. A red required check = a fix on **the same branch**, never a second PR. The entry in the
   `## Problem log` starts with `[check]` (telemetry counts regressions caught by CI by that prefix).
5. Every iteration starts by reconciling PRs (`gh pr list`): MERGED → checked off; red → priority;
   green/pending → counts toward the limit; closed by hand → `TELESMA BLOCKED` (Telesma does not guess why
   and does not reopen).
6. A task that depends on an unmerged PR: an independent task goes first. Only when none is left does
   Telesma chain — a branch off that PR's branch (see "Branch chains" below). Merge is always a squash
   (one commit = one task on main; release notes and telemetry rely on it).
7. Open-PR limit reached and none of them red → `TELESMA WAITING`: Telesma writes `telesma/state/WAITING.md` and
   ends the session. Nothing is broken — the loop did everything it could without a merge. Run it
   again after a merge; the file is shown at the next start and deleted once the PRs are reconciled.
8. Phase tags (`telesma/phase-*`), the full suite after a phase and release versions `vX.Y.Z` happen on
   **main**, after all of the phase's tasks are merged. A full-suite run on a task branch is recorded
   only as a `Preliminary run`; `Regression after Phase N` is written from main — squash and the merge
   order can assemble the code differently from how it sat on the branch.

### Merge modes

| Mode | What happens | When to use it |
|------|--------------|----------------|
| `agent` (default) | Telesma waits on `gh pr checks --watch`, then runs `gh pr merge --squash`; the judge verifies the required checks once more before letting the merge through | a private repository on GitHub Free, which has neither auto-merge nor branch protection |
| `auto` | `gh pr merge --auto --squash`; GitHub merges once the protected branch's required checks pass | a public repository, or a paid plan with branch protection and required status checks |
| `manual` | nothing — the PR waits for a human; it still counts toward the open-PR limit | you want to review every PR yourself |

The wizard detects what the repository supports and recommends `agent` when auto-merge or branch
protection is missing. When you pick `auto` on a repository without auto-merge it offers to enable it
(which fails on plans that do not include it); `auto` without branch protection would merge a PR
without waiting for checks, so the wizard refuses that combination.

### Branch chains and the rebase order

Chains are avoided first: after opening a PR Telesma waits up to `Wait for merge`, then takes an
independent task. When a chain is unavoidable, squash changes the predecessor's SHA, so the successor
**must** be re-pointed and rebased — otherwise its PR shows the predecessor's diff and Specky sees
foreign trailers.

The order matters. A PR whose base branch is deleted is **closed** by GitHub, not re-pointed — that is
how a successor PR got closed in the reference project after `gh pr merge <predecessor> --delete-branch`.
So Telesma goes from the bottom of the chain, one PR at a time:

```bash
gh pr edit <successor> --base main                              # 1. first the successor's new base
gh pr merge <predecessor> --squash                              # 2. merge the predecessor WITHOUT --delete-branch
git fetch origin
git rebase --onto origin/main <predecessor-branch> <my-branch>  # 3. rebase the successor
git push --force-with-lease origin <my-branch>
```

`--force-with-lease` only ever goes to Telesma's own task branch; bare `--force` never. The judge lets
`gh pr edit` through in exactly one form, `--base main`. Branches are deleted at the end, when the whole
chain is on main.

### Permissions

The wizard adds to `Allowed commands`: `gh pr create/list/view/checks/diff/status`,
`git fetch/pull/checkout -b/switch/rebase` and push **only** to `task-*` branches. `gh pr merge` and
pushes anywhere else are **deliberately** absent from the allowlist — they go through the judge or ask
you. Without the integration, `git push` remains a hard pattern in the judge and always asks.

### PR status "Telesma: checks (local)"

With quality checks enabled (`## Checks` → `Enabled: yes`, field `PR status: yes` — the default; see
[CHECKS.md](CHECKS.md)) the hook does two things Telesma does not have to remember:

1. After every `git commit` it saves **evidence**: which `commit`-point checks passed for that SHA, when,
   with how many warnings (`.git/telesma-checks/<sha>.json` — this machine's data, nothing to commit).
2. After every `git push` to a task branch it collects the evidence for the `origin/main..HEAD` commits
   and posts one **commit status** on the branch tip via `gh api` (the statuses API works with the
   ordinary `gh auth login` token; the Checks API would need a GitHub App). The status shows up in the
   PR's check list next to "Specky contract check":

   ```
   Telesma: checks (local)  ✓  clean: dependencies, secrets, weakenings · 3 commits · 2026-10-07 14:03 · OSV audit 2026-10-05 clean
   ```

   It is red when some commit **has no evidence** (made outside the hook: by hand, with `--no-verify`,
   before the checks were enabled) or when a check **did not run** at some commit (tool missing, time
   limit). Missing evidence is not green — the same rule the judge applies to a missing check.

The wizard adds this name to `Required checks`, so the judge will not merge a PR without evidence.
Rebase and squash change the SHA; the evidence is found again by `git patch-id` (the content of the
change is the same), so chains stay green after the rebase above.

**What it is, and what it is not.** It is an **attestation from the developer's machine**, not
verification: anyone with push rights can post an identical status with one `gh api` call. Hence
"local" in the name, and the date and commit count in the description. `gh api` is deliberately not on
the allowlist, so an attempt by the model to post a status by hand goes to the judge, i.e. to you. The
verifiable variant is the same runner in the pipeline
(`python3 telesma/checks/telesma-checks.py --point ci --since origin/main` — seconds, no secrets needed).
The hook calls `gh` itself (no permission prompts); `gh` unavailable or an API error = an entry in
`telesma/state/CHECKS.jsonl` and a note for Telesma — the push is never blocked.

## Requirement tracker (Specky) — how Telesma works

[Specky](https://app.specky.app) is a requirements tool built by Telesma's author. It keeps the
specification as a contract between people and the coding agent: every requirement has acceptance
criteria, a content hash and an explicit human approval, and Specky remembers what changed since the
agent last looked. It talks to Claude Code over MCP, reads test results from CI and shows, per
criterion, whether a PR actually proves it. Telesma works fine without it — this integration is
optional — but if you want requirements that stay in sync with the code instead of a frozen `telesma/spec/`
directory, this is what it is for. Questions and access: hello@specky.app.

1. Specky is the source of truth for requirements and criteria. `telesma/spec/` in the repo stays frozen;
   requirement changes arrive through `telesma/changes/` like any other change.
2. Tasks in the plan carry anchors `- Specky: (req: <id> v<n>.<r> @<hash7>)` — `n` the text version,
   `r` the criteria revision — plus `- Specky criteria: (crit: <id>) …`. Before a task Telesma runs
   `check_anchors`; `stale` = the requirement changed (text, criteria or lifecycle — the hash decides) →
   Telesma reads it again before writing code and updates the anchor.
3. Every commit implementing a requirement ends with the trailer `Specky-Req: <id>@<hash7>` (the hash
   from `get_requirement` in this session, never guessed); a commit with no requirement behind it carries
   `Specky-Req: none`. A repository connected to Specky requires the trailer: a PR without one is red,
   `none` is neutral, and a PR is merged only with the Specky status green. With GitHub the trailer also
   goes into the PR body, so it survives the squash onto main. When the requirement is built, Telesma
   sets `code_ready` with the requirement's hash — a stale hash means the text moved under its feet, and
   it re-reads instead of skipping.
4. A criterion test has the line `specky: crit <criterion_id>` directly above it (Python above
   `def test_*`, JS/TS above `it(...)`/`test(...)`, Deno above `Deno.test(...)`). The proof is not
   Telesma's word but the JUnit report from CI — see "Criteria evidence via CI" below. Specky shows ✅/❌
   per criterion on the PR and the "Specky contract check" status. `mark_criteria_tested` exists as the
   fallback for criteria CI cannot prove; an incomplete item lands as "needs manual check", not as evidence.
5. Synchronization: at session start and by hand with `./telesma.sh --sync-specky <project>` (a
   short Claude session that does only the sync). Telesma fetches `what_changed` from the cursor in
   `telesma/state/SPECKY.md` (pages of 50; the first session from `since_seq=0`), plus `get_work_queue`;
   every item that needs work becomes a file `telesma/changes/<date>-specky-<id>.md` with
   `kind: bug | correction | feature` in its frontmatter — `to_fix` and failing PRs as bugs, drift after
   code ready, stale evidence, superseded requirements and stale decisions as corrections, new accepted
   requirements as features; counts and inactive requirements only as lines in `REPORT.md`. From there
   the ordinary change channel takes over (plan mutation, rework phases, `REPORT.md`,
   `telesma/changes/processed/`). The cursor moves only after the files are written, so an interrupted
   session loses nothing.
6. Telesma only **proposes** (`propose_requirements`, `propose_requirement_edit`, `raise_spec_issue`);
   decisions in Specky (`accept_proposals`, `reject_proposals`, `decide_realization`,
   `decide_collisions`, `answer_questions`) are made by a human. A loop with no human present gets
   `decision_requires_interactive_client` for any decision, and does not work around it. A proposal
   carries `external_ref: telesma:<task>`, so the requirement → task map fills itself once the human
   accepts; a task that removes a feature proposes `deprecate` on its requirement.
7. Everything Telesma learns from Specky stays in `telesma/` (`SPECKY.md`, anchors in `PLAN.md`,
   `REPORT.md`) and `telesma/changes/` — a new session rediscovers nothing.

### Criteria evidence via CI (`specky-ci.yml`)

With both integrations the wizard copies `.github/workflows/specky-ci.yml`. In task 1.1 (the
architecture skeleton) Telesma adapts its steps to the stack — runtime setup, install, the test command
writing a JUnit report — while **keeping the two contract points** from the file's header:

- the artifact with the JUnit XML reports has "junit" in its name;
- the test steps run with `continue-on-error: true`, so the report exists for a red test too; no `paths:`
  filter in `on:`; `push: branches: [main]` stays, because Specky also collects evidence after the merge;
- a criterion demo (recording or screenshot) is uploaded as the artifact `specky-demo-<criterion_id>`.

The Specky plugin is the recommended client (`/plugin marketplace add SpeckyContractCheck/specky-plugin`,
`/plugin install specky@specky`): two MCP servers, core and "record" (requirement history, snapshot
diffs), one token; the wizard allows both. The claude.ai connector works for the loop but cannot decide.

Everything else (language, commands, steps) is per project. The job name (`test` by default) is one of
the `Required checks`. On the first PR Telesma verifies the setup: Specky's comment must show ✅/❌ next to
each criterion marked with `specky: crit`, not ⏳ or "CI did not run it" — otherwise it fixes the
workflow before taking the next task, since no PR would pass the contract.

### Release snapshots (section 18.7)

Right after `git tag vX.Y.Z` (section 15) Telesma calls `create_snapshot` with the tag, the SHA of the
tagged commit, the tag message and the full content of `docs/test-scenarios/vX.Y.Z.md`. In Specky
("Versions and export" → "What's new") the tester sees which requirements became ready since the
previous release — this comes for free, it is the `code_ready` statuses Telesma set while working,
frozen — and reads the manual scenarios under "How to test".

- **After the tag, never before:** the snapshot carries the SHA, and the scenarios file is inside that
  commit, so both copies are identical by construction.
- **Results are recorded in the file in the repo** — the checkboxes in Specky are inactive, and the
  file says so in its header.
- **Specky never blocks a release.** The tag and the file are in git; if Specky is unavailable, the
  `## Problem log` gets a `[specky]` entry with the command to backfill the snapshot later.
  `snapshot_tag_exists` = the snapshot is already there; nothing is renamed or repeated.
- **Never a snapshot on `telesma/phase-*`:** "previous version" in Specky is the adjacent snapshot on the
  list, so every extra snapshot would spoil the next release's "What's new".

**Backfill for tags made before the integration:**

```bash
python3 tools/telesma-specky-snapshots.py <project> --all              # every v* tag that has a scenarios file
python3 tools/telesma-specky-snapshots.py <project> v0.3.0 v0.3.1      # the given tags
python3 tools/telesma-specky-snapshots.py <project> --all --dry-run    # list only, send nothing
```

It uses Specky's REST API with e-mail + password login (REST has no bearer auth). The password comes
from `SPECKY_PASSWORD` or a terminal prompt, never from an argument (it would land in shell history);
the e-mail from `--email` or `SPECKY_EMAIL`. The address and `project_id` come from `## Integrations`
(`Tracker MCP` without `/mcp`, `Tracker project`); `--url` and `--project-id` override them. Tags are
processed **oldest first**, so the snapshot order matches the release order; an HTTP 409 means the
snapshot already exists and the tag is skipped.

## Files

| File | Role |
|------|------|
| `telesma/config.md` → `## Integrations` | configuration (the only place the wizard edits, besides `Auto-push` and the permissions) |
| `telesma/state/WAITING.md` | `TELESMA WAITING` state (PR limit reached); shown at startup, deleted after reconciliation |
| `telesma/state/SPECKY.md` | sync cursor + requirement → task map; committed |
| `.github/workflows/specky-ci.yml` | CI template with the Specky contract (artifact "junit", `specky-demo-<id>`) |
| `docs/test-scenarios/vX.Y.Z.md` | manual test scenarios of a release (section 15.7); with `Tracker: specky` also copied into the Specky snapshot (18.7) — results are recorded in the file |
| `tools/telesma-specky-snapshots.py` (in the Telesma repo) | snapshots backwards over REST for `v*` tags with a scenarios file; 409 = skipped |
| `templates/integrations/` (in the Telesma repo) | one directory = one integration: `INSTRUCTIONS.md`, `setup.sh`, `permissions.txt`, `DESCRIPTION.txt` |

## Adding another integration

See `templates/integrations/README.md` — e.g. a new `git/gitlab/` directory with the same files, an
entry in the wizard, the value in the startup validator, and recognition of the new CLI's merge/push
commands in the permission judge (without it everything asks the human: safe, but the loop stops on
every merge).
