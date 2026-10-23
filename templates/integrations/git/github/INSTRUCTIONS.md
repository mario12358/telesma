## 17. Integration: git repository (GitHub)

Active because `telesma/config.md` → `## Integrations` has `Repository: github`. This section **overrides**
the indicated steps of sections 1, 3, 4 and 9 — the rest of CORE applies unchanged. Fields of the `## Integrations` section:
`Repo`, `Merge` (auto | agent | manual), `Required checks`, `Open PR limit`, `Wait for merge`,
`Max fixes per PR`, `Branch prefix`.

The definition of "task done" changes to: **PR merged into main**. Opening a PR is not the end of
the task. In the plan you record the state "PR open, waiting" with the tag `(pr: #<n>)` on the task line, next to
the `[ ]` checkbox; after the merge the checkbox becomes `[x]`, the tag stays (audit + telemetry).

### 17.1 Start of an iteration — reconciling PR state (BEFORE step 2 of section 1)

Once per iteration, with one call:

```bash
git fetch origin
gh pr list --state all --limit 100 --json number,state,headRefName,baseRefName,mergedAt,statusCheckRollup
```

For every task with `(pr: #n)` in PLAN.md:

| PR state | What you do |
|----------|-------------|
| `MERGED` | `[ ]` → `[x]` in PLAN.md, a row in REPORT.md (Task history: commit = the squash on main). When other open PRs had `base` = this PR's branch → **17.5 rebase**. When it was the phase's last `[ ]` → **phase regression on main** (17.3, the paragraph on tags). |
| `OPEN`, required check red | **Takes precedence** over any new task → 17.4. |
| `OPEN`, checks green/pending | Counts toward the limit. `Merge: agent` and all required ones green → merge now (17.3 step 5). `Merge: manual` → waits for a human. |
| `CLOSED` without merge | **TELESMA BLOCKED** — someone closed the PR by hand; do not guess why, do not open a new one. |

After reconciling: `git checkout main && git pull --ff-only origin main`. Every new branch starts
from the current main.

### 17.2 Choosing a task — limit and dependencies (steps 2-3 of section 1)

- Count `[ ]` with `(pr:)` = Telesma's open PRs. When ≥ `Open PR limit` and none of them is red
  → **TELESMA WAITING** (17.6). Do not open another PR.
- A task with `(requires: X.Y)`, where X.Y has `(pr:)` and `[ ]` (unmerged): treat it as an **unfinished**
  dependency — take an independent task first. Only when no independent one is left:
  a chain — a branch off X.Y's branch, `gh pr create --base <X.Y's branch>`. Note in REPORT.md that the PR is
  chained (after X.Y is merged it has to be re-pointed — 17.5).

### 17.3 Finishing a task (INSTEAD OF step 12 of section 1)

1. Branch: `git checkout -b <Branch prefix><id>-<slug>` (off main, or off the predecessor's branch — 17.2).
   Slug: 2-4 ASCII words, hyphens. One branch = one task; never commit a task to main.
2. Commit per section 4 (specific files; PLAN.md gets the `(pr:)` tag only after step 4 — so you commit PLAN.md
   and REPORT.md in a **second** commit on the same branch, or with `--amend` before the push;
   the simplest: `gh pr create` first, then add the tag, `git commit --amend --no-edit`, push).
   Practical order: commit the code → push → PR → tag in the plan → amend → `git push --force-with-lease`.
3. `git push -u origin <branch>`.
4. `gh pr create --title "<commit subject>" --body "<commit body, with trailers>"` — title = the commit
   subject (with the task id), body = the full commit body. The squash onto main takes the PR's title and body, so
   trailers (e.g. `Specky-Req:`) must be in the body, otherwise they will not reach main. With the Specky
   integration every PR body carries a trailer — `Specky-Req: <id>@<hash7>` or `Specky-Req: none` for a PR
   with no requirement behind it (a connected repository marks a PR without any trailer red). PR number →
   the tag `(pr: #n)` on the task line in PLAN.md.
5. Merge per the `Merge` field:
   - `auto`: `gh pr merge <n> --auto --squash --delete-branch`, then `gh pr checks <n> --watch`
     with the `Wait for merge` time limit (one Bash call with a timeout; not a loop).
   - `agent`: `gh pr checks <n> --watch --fail-fast` (limit `Wait for merge`) **as its own Bash call,
     without a pipe** — `gh pr checks … | tail && gh pr merge …` hides the exit code of the checks and
     merges on red. Read the result, and only when every one of the `Required checks` is green →
     `gh pr merge <n> --squash --delete-branch` in a separate command. The permission hook checks
     the checks once more itself and refuses a merge with a red, pending or missing required check —
     a refusal despite "green" means some required check is **absent** (did not run); do not ask the
     human for permission, check the workflow instead.
   - `manual`: nothing — the PR waits for a human.
6. Outcome: merged → `[x]` in the plan, REPORT.md, `git checkout main && git pull --ff-only`.
   Not merged once `Wait for merge` has passed → the task stays `[ ]` with `(pr:)`, you move on to
   the next one (17.2). A red check while waiting → 17.4.

   `--delete-branch` in both modes **only when no open PR is based on this branch**
   (`gh pr list --base <branch>` empty) — otherwise 17.5.

Phase tags (`telesma/phase-<ID>`), the full suite after a phase and section 15 (releases) are done on **main**
after all of the phase's tasks are merged — not on a task branch. A full-suite run on a branch is
**not** a phase regression: you record it in REPORT.md as
`**Preliminary run after Phase N (date) — GREEN (branch <name>)**` and do not tag. The phase regression
happens in 17.1, in the first iteration in which all of the phase's tasks are `[x]`: the full suite on
main → the entry `**Regression after Phase N (date) — …**` → tag. A red result on main is a regression
with priority (section 2), also when the preliminary run was green — squash and the merge order
can assemble the code differently from how it sat on the branch.

### 17.4 Red required check

A fix **on the same branch**, never a new PR for the same task:

1. `gh pr checks <n>` + the job log (`gh run view --log-failed` when needed) → diagnosis.
   The "Specky contract check" red → Specky's comment on the PR says exactly what: an outdated
   requirement hash (read the requirement again — section 18), a red criterion test, an open
   issue in Specky (that is the human's — TELESMA BLOCKED with a link).
2. Fix it, tests locally, commit on the branch, `git push origin <branch>`. Back to 17.3 step 5.
3. Counter: `Max fixes per PR` (separate from `Max tries per task`). Exhausted → TELESMA BLOCKED
   with a link to the PR and the last diagnosis.
4. An entry in REPORT.md → Problem log, opener: `[date] [check] PR #<n> — <check>: <cause>`.
   The `[check]` prefix is fixed — telemetry counts regressions caught by CI by it.

### 17.5 Branch chain — merging from the bottom, the successor re-pointed BEFORE the predecessor's merge

Merge always by squash (one commit = one task on main; release notes and
telemetry stand on that). Squash changes the SHA, so a chained branch **must** be re-pointed, otherwise the PR
shows the predecessor's diff and Specky sees foreign trailers. A PR whose base branch disappeared
is **closed** by GitHub — it does not re-point it by itself (that is how PR #84 got closed in the reference project after
`gh pr merge #83 --delete-branch`). So the order is fixed, one PR at a time from the bottom of the chain:

```bash
gh pr edit <successor> --base main                              # 1. FIRST the successor's new base
gh pr merge <predecessor> --squash                              # 2. merge the predecessor WITHOUT --delete-branch
git fetch origin
git rebase --onto origin/main <predecessor-branch> <my-branch>  # 3. rebase the successor
git push --force-with-lease origin <my-branch>
```

You delete the branches at the end, when the whole chain is on main (`git push origin --delete` asks
the human — leave it to them, or use `gh pr merge --delete-branch` on the last PR of the chain).
Do not delete the predecessor's local branch before the rebase (it is needed as the cut point); afterwards
`git branch -d`. After every step `gh pr view <successor> --json state,baseRefName` — the state must be
`OPEN`, the base `main`. `--force-with-lease` **only** on your own task branch; bare `--force` never.
`gh pr edit` may be used only in the form `--base main` — the permission judge lets only that one through.

### 17.6 TELESMA WAITING — PR limit reached

This is not an error and not a blocker: the loop did everything it could without a merge. Write `telesma/state/WAITING.md`
(the script shows it at the next start; delete the file in 17.1 once the PRs are reconciled) and end the session:

```
TELESMA WAITING

Open PRs: #12 (3.2), #13 (3.3), #14 (3.4) — waiting for merge / checks.
Merge: <auto|agent|manual>. Nothing is broken. Run again after a merge.
```

### 17.7 What you do NOT do

- You do not push to main or to someone else's branch; you do not use a refspec with `:` (`branch:main`).
- No `gh pr merge` without `--squash`; no `--admin`; in `auto` mode you do not merge by hand.
- You do not close PRs (`gh pr close`) and do not open a second PR for a task that has `(pr:)`.
- You do not delete branches with `-D`; no `git reset --hard` on a branch with unmerged work.
- No `--delete-branch` on a PR that another open PR is based on — GitHub will close the successor.
- You do not record a run from a branch as "Regression after Phase" and do not tag a phase before the full
  suite on main.
- You do not check `[x]` before the merge — "tests green on my side" is not "merged".
- Section 9 (TELESMA COMPLETE) only when **all** tasks are `[x]`, i.e. merged.
