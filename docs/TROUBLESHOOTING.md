# Troubleshooting

## Claude stopped

Check whether it printed `TELESMA BLOCKED`. The blocker is also saved in `telesma/state/BLOCKED.md`. Start
again — preferably with `-i`, so you can answer the question directly:

```bash
telesma.sh /path/to/project -m 1 -i
```

The next start shows the blocker in the terminal and passes it to Claude, which resolves it before
choosing a task (and deletes `telesma/state/BLOCKED.md` afterwards). In pipe mode Claude cannot wait for your
answer — stdin is closed — which is why the file exists.

## `TELESMA WAITING`

GitHub integration only: the open-PR limit (`Open PR limit`) was reached and none of the PRs is red.
Nothing is broken. Merge the PRs (or wait for them to be merged) and start again; the content of
`telesma/state/WAITING.md` is shown at the start, and Telesma reconciles the PR states before picking the next task.

## Claude is doing something other than it should

Interrupt it (Ctrl+C) and start again with a more precise `telesma/state/PLAN.md`: smaller tasks, explicit
`(requires:)`, `(spec:)` pointing at the right document, `- AC:` criteria. See
[WORKFLOW.md § 3](WORKFLOW.md#3-writing-a-good-plan).

## The context filled up

Claude Code compacts the context automatically when the window fills; Claude cannot run `/compact`
itself. Telesma is built for this: state files are updated after every task, and after a compaction
Claude rebuilds its state from them and continues with the first unfinished task. If you want to
compact at a moment of your choosing, type `/compact` yourself, with a short summary of the state.

## Tests keep failing

Claude gives up after `Max tries per task` (default 3) and prints `TELESMA BLOCKED`. Each later try
widens the context (neighbouring spec sections, the whole modified file, similar cases in the problem
log). Help it with the concrete question it asked, or simplify the task. Claude is not allowed to make
a test pass by weakening it unless the test contradicts the spec — and then it must cite the spec
and log the change.

A test command that reports **0 tests** counts as a failure even with exit code 0 — check the
command and test paths in `telesma/config.md`.

## A regression after a new phase

Claude should detect it in the full suite (or earlier, in the smoke suite) and fix it before
continuing — a regression takes priority over new tasks. If it cannot, start again with `-i` to help.
Setting a `Smoke suite` makes regressions surface on the task that caused them instead of at the end
of the phase.

## Clarification was interrupted

Start again with `telesma.sh /path/to/project -i`. Telesma reads `telesma/state/QUESTIONS.md` and resumes from
the first unanswered item.

## Startup reports config errors

`Test command` or `Full suite command` is missing or still a `[…]` placeholder. Fill them in
`## Tests` of `telesma/config.md`. Other placeholder values are warnings; fix them when you can. See
[CONFIGURATION.md § Validation](CONFIGURATION.md#validation-at-startup).

## Startup reports plan errors

The plan validator found broken dependencies (a missing id, a cycle, a duplicate), a `(tech:)` tag
without a file in `telesma/guidelines/`, or a `(spec:)` / `(ui-*:)` / `(flow:)` tag pointing at a
missing file. Fix the plan (or add the missing guideline) — continuing anyway means Claude will hit
the same problem mid-task.

## The start shows red state-file diagnosis lines

These are repairable damage (`damage`):

```bash
telesma.sh --repair /path/to/project
```

restores the content from git history and exits. Yellow lines (`notice`) are information only. See
[STATE_FILES.md § Diagnosis](STATE_FILES.md#diagnosis-and---repair).

## The spec changed after clarification

The launcher warns when a spec file's checksum no longer matches the index, and Claude verifies the
anchors of every fragment it reads. But `telesma/spec/` is meant to be frozen: put requirement changes into
`telesma/changes/` instead, so they become plan edits with an audit trail
([WORKFLOW.md § 8](WORKFLOW.md#8-changes-after-clarification)). `telesma/spec/ux_ui/LINKS.md` is the exception
and may be edited at any time.

## A mockup link cannot be fetched

Links in `telesma/spec/ux_ui/LINKS.md` must be shared (public or share links); Telesma cannot fetch a private
artifact. The launcher warns about unreachable links at startup, and a task that needs one blocks.

## A quality check stopped a commit

Read the list: check, `file:line`, message, fingerprint. A real problem is fixed by Claude, which
then retries the commit. A false positive is reported as `TELESMA BLOCKED` — you then add its
fingerprint to `telesma/state/CHECK_EXCEPTIONS.md` (Claude cannot write there without asking you).

A message asking to split the command is not a finding in the code but about the command's shape:
the checks read files before the command runs, so writing files and committing in one command is
refused. Write first, then commit in a separate command. Details: [CHECKS.md](CHECKS.md).

## The `Telesma: checks (local)` status on a PR is red

"No evidence for … commits" means a commit was made outside the hook (by hand, with `--no-verify`, or
before the checks were enabled). Claude fixes it with `git commit --amend --no-edit` as a plain command
and `git push --force-with-lease` to its own task branch. "A check did not run" means a tool was
missing or a time limit was hit on some commit — the operation went through without that check.

## A release version is not offered or not created

Telesma proposes a release only when there are commits since the last `v*` tag and the last full suite
was green. Tagging is refused on a red suite, a dirty working tree (often uncommitted
`telesma/state/*_ARCHIVE.md` files from rotation — commit them), an existing tag of the same name, or, with
checks enabled, an open `telesma: weakening` marker. After tagging, remember that tags are not pushed by
a plain `git push`: run `git push origin vX.Y.Z`.

## A PR was merged on a red check, or a release tag was pushed by Telesma

Almost always the session ran in Claude Code's **`auto` permission mode** (the status bar shows it;
Shift+Tab cycles the modes). In `auto` the built-in classifier answers permission prompts and the
Telesma permission judge is never called, so "merge only on green" and "the user pushes the tag"
were enforced by nobody. The launcher warns at the next start when the previous session left an
`auto` note in `telesma/state/PERMISSIONS.jsonl`.

- Keep the mode at the one the launcher sets (`## Permissions → Mode`, default `acceptEdits`).
- Since the contract layer ([PERMISSION_JUDGE.md](PERMISSION_JUDGE.md)) these two operations are
  refused in every mode; an older hook in `.claude/hooks/` is updated at the next start through
  `.telesma-manifest` unless you edited it.
- A merge that already happened on red: fix forward on `main` (a new PR), do not force-push.
  A pushed tag that should not exist yet: `git push --delete origin vX.Y.Z` is your decision.

## Permission prompts keep interrupting the loop

- Approved commands are merged back into `## Permissions` and generalized to prefix patterns at the
  next start (`Generalize permissions: yes`), so the same family should not ask twice.
- Commands like `cd X && git …` always prompt in Claude Code regardless of the allowlist; with the
  judge's `Suggest command fixes: yes` they are rewritten automatically.
- Directories outside the repository that Telesma legitimately uses belong in `## Working directories`.
- For the rest, consider the permission judge ([PERMISSION_JUDGE.md](PERMISSION_JUDGE.md)).
