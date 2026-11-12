## 17. Integration: git repository (GitHub)

Active because `telesma/config.md` → `## Integrations` has `Repository: github`. Fields of the section:
`Repo`, `Merge` (auto | agent | manual), `Required checks`, `Open PR limit`, `Wait for merge`,
`Max fixes per PR`, `Branch prefix`.

The definition of "task done" changes to: **PR merged into main**. Opening a PR is not the end of
the task. The whole GitHub side is done by the task tool (`TASK_TOOL`) — you never run `git push`,
`git checkout`/`pull` on main, `gh pr create`, `gh pr merge`, `gh pr edit` or `gh api` yourself (a
hook refuses them). Reading is yours: `gh pr view`, `gh pr checks`, `gh run view --log-failed`.

### 17.1 What `next` does first — reconciling PR state

Before it hands out anything, `next` fetches, reads `gh pr list` and goes back to main as GitHub has
it. Then, for every task with a PR (it finds them by the PR title `Telesma: Task N.M: …`):

| PR state | What the script does |
|----------|----------------------|
| `MERGED` | ticks the task, writes its `Task history` row (commit = the squash on main, `(#n)`), adds `(pr: #n)` to the task line — in the tree on main; they are committed by the state PR at the end of the phase (17.3) |
| `OPEN`, required checks green, `Merge: agent` | merges it by squash — a chained successor is re-pointed to main **first** and the predecessor merged without `--delete-branch`, then the successor is rebased onto the new main and pushed with `--force-with-lease` (17.5) |
| `OPEN`, a required check red | hands it out as `TELESMA PR FIX` before anything new (17.4) |
| `OPEN`, pending / `Merge: manual` / `auto` | counts toward the limit; at `Open PR limit` → `TELESMA WAITING` (17.6) |
| `CLOSED` without a merge | `TELESMA BLOCKED` — someone closed the PR by hand; no second PR for that task |

A required check that is missing counts as pending, never as green. Without `Required checks`
any red check is red and anything running is pending.

### 17.2 Choosing a task — what `next` hands out

- An independent task first: a task whose `(requires: X.Y)` has an open PR is unfinished. Only when
  nothing independent is left, a **chain**: `next` says `Chain` and the branch starts from X.Y's
  branch; its PR is based on that branch until X.Y is merged.
- The task's branch `<Branch prefix><id>-<slug>` is created by `next`, off main or off the
  predecessor's branch. One branch = one task. Stay on it until `done`.
- Nothing to start while PRs wait: `next` watches the checks for up to `Wait for merge` (at most
  8 minutes) and tells you to run it again.

### 17.3 Finishing a task — `done` on the task branch

`done` runs the tests and the checks, commits the task's work on its branch, pushes it and opens the
PR — title = the commit subject (with the task id), body = the commit body with the trailers and the
footer. A trailer the project needs goes in `--trailer` (with the Specky integration every PR body
carries one: `Specky-Req: <id>@<hash7>`, or `Specky-Req: none` for a PR with no requirement behind
it — a connected repository marks a PR without any trailer red). With `Merge: auto` it enables
GitHub's auto-merge (squash). It does **not** tick the task and does not touch the state files of
the branch: the tick, the `(pr: #n)` and the history row come from GitHub at the merge — parallel
PRs editing neighbouring plan lines would collide at every merge.

The phase regression runs **on main**, after all of the phase's tasks are merged: `next` says
`TELESMA SUITE DUE`, `suite` runs the full suite on main, writes `**Regression after Phase N (date)
— …**`, tags the phase on green and opens one **state PR** (`Telesma: state after Phase N`) with the
ticks, the rows and the run; the next reconciliation merges it like any other. A red result on main
is a regression with priority (section 2), also when the branch was green — squash and the merge
order can assemble the code differently from how it sat on the branch. A full-suite run on a task
branch is a `Preliminary run`, never tagged. Section 15 (releases) happens on main, after the state
PR is merged.

Every other commit (`commit --kind …`, `changes-done`) goes through its own branch and PR too —
nothing lands on main directly. `next` waits for a `changes` or `regression` PR before it goes on:
main does not hold it until it is merged.

### 17.4 Red required check — `TELESMA PR FIX`

A fix **on the same branch**, never a new PR for the same task. `next` checks the branch out and says
which check is red:

1. `gh pr checks <n>` + the job log (`gh run view --log-failed`) → diagnosis.
   The "Specky contract check" red → Specky's comment on the PR says exactly what: an outdated
   requirement hash (read the requirement again — section 18), a red criterion test, an open
   issue in Specky (that is the human's — TELESMA BLOCKED with a link).
2. Fix it, an entry in REPORT.md → Problem log, opener: `[date] [check] PR #<n> — <check>: <cause>`.
   The `[check]` prefix is fixed — telemetry counts regressions caught by CI by it.
3. `done` — it commits and pushes the fix to the same PR. `next` reads the checks again.
4. `Max fixes per PR` fixes for one PR → the script stops with TELESMA BLOCKED and the PR's link.

### 17.5 Branch chain

Merge is always by squash (one commit = one task on main). Squash changes the SHA, so a chained
branch has to be re-pointed and rebased; a PR whose base branch disappears is **closed** by GitHub.
The script keeps the order — successor re-pointed to main, predecessor merged without
`--delete-branch`, successor rebased onto the new main and pushed with `--force-with-lease` — one
PR at a time from the bottom. What stays yours is a **rebase conflict**: `next` says
`TELESMA REBASE CONFLICT` with the files; resolve the conflict markers in those files (edit only, no
git commands) and run `next` again — it stages them, continues the rebase and pushes.

### 17.6 TELESMA WAITING — PR limit reached

Not an error and not a blocker: the loop did everything it could without a merge. `next` writes
`telesma/state/WAITING.md` (the launcher shows it at the next start; the next reconciliation removes
it). Report it and end the session:

```
TELESMA WAITING

Open PRs: #12 (3.2), #13 (3.3), #14 (3.4) — waiting for merge / checks.
Merge: <auto|agent|manual>. Nothing is broken. Run again after a merge.
```

### 17.7 What you do NOT do

- No git or gh writes yourself: no push, no merge, no `gh pr create/edit/close`, no `gh api` with
  a method or fields — the hook refuses them and names the task-tool command.
- You do not check `[x]` — the merge does, through the script.
- You do not open a second PR for a task, and you do not record a run from a branch as "Regression
  after Phase".
- Section 9 (TELESMA COMPLETE) comes from `next`, only when **all** tasks are merged.
