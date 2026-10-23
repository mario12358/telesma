## 19. Quality checks (active: `## Checks` → `Enabled: yes`)

Before `git commit`, `git tag telesma/phase-*` and `git tag … vX.Y.Z` a hook runs the checks
from `telesma/checks/` (secrets, weakenings and the others listed in the config). You do not run
them yourself — they happen at the git operation you perform anyway.

A check reads files **before** the command runs. That is why a commit and a tag always go as a
separate command: in the same command, only `git add`/`rm`/`mv`, `cd` and reading commands without
redirection (`grep`, `ls`, `cat`, `head`, `find` without `-exec`/`-delete`) may stand before
`git commit`, and a tag goes after the commit, in the next command. A file write and a commit in one
command, `bash -c "git commit …"` or a git alias that is a script are rejected by the hook before it
checks anything.

The `lint-types` check takes its commands from `## Tests` (`Linter/formatter`, `Typecheck command`) —
an empty field = no such tool, so fill them in during task 1.1 together with the linter configuration.
The `dead-entry` check warns about a symbol new in the phase that nothing leads to — it is the
mechanical guard of `AC: entry`; the answer is wiring up the entry or removing the code, not an exception.

The `intent` and `red-team` checks compare the code with the attack-surface map `telesma/state/SECURITY_MAP.md`
(format: `telesma/checks/intent/MAP_TEMPLATE.md`). You add a new route together with its row
in `## Routes`, in the same commit: who has access (a role from `## Roles`, `anonymous` = public)
and whether it touches someone else's resource (Ownership). A new role gets the name of its guard
from the code in `## Roles`. Role `?` from the skeleton → settle it when you touch the route. At the
end of a phase, every protected route changed in the phase needs a test that attacks it and expects
a refusal, with the marker `telesma: red-team <METHOD> <path> — <cases>` — the phase-tag block says
which cases are missing; add them as a task of this phase. You do not change the map to make a check
pass: a role wider than in the spec, or `anonymous` without a reason, is a workaround (19.1).

`telesma/checks/` belongs to the repository (CI runs the same runner). Files from this directory that
are new or were updated at startup go into the session's first commit — like the archives from
section 4. The same goes for `telesma/state/SECURITY_MAP.md` when the startup created its skeleton.

### 19.1 Operation stopped (blocking findings)

1. Read the list: check, file:line, message, fingerprint.
2. **Fix the cause** and retry the same operation. A secret → remove it from the file and move it to
   an environment variable (name in `docs/RUNBOOK.md`, the value never in the repo); if it already
   reached a commit, tell the human it has to be revoked — removing it from history is not enough.
3. A wrong finding (false positive) → **TELESMA BLOCKED**: fingerprint, check, file, why it is not
   a problem. The human writes the exception into `telesma/state/CHECK_EXCEPTIONS.md`.

You never get around a check: no changing the command so the hook does not recognise it, no
committing with another tool, no editing `telesma/checks/`, `telesma/state/CHECK_EXCEPTIONS.md` or the
`## Checks` section (those writes ask the human anyway), no splitting a file so a pattern stops matching.

### 19.2 Warnings

They arrive as context after an operation that went through. Severity is per rule and set by the
module (table in `telesma/checks/<check>/CHECK.md`) — e.g. an AWS key blocks, while `password = "…"`
only warns, although both rules belong to the `secrets` check with `On failure: block`. The config
field can only soften a severity. A warning under "block" is therefore intended behaviour. If they
concern your change → fix it in the same task or note in `REPORT.md` → `## Problem log` why it stays.
A warning about a check that did not run (tool missing, time limit) → tell the human at the next
report: the operation went through **without** that check.

### 19.3 Weakenings

When you deliberately disable a safeguard or add a workaround (because the human asks for it,
because a manual test needs it), mark the place on the same line or the line above:

```
telesma: weakening <id> — <reason and removal condition>
```

An open weakening blocks the release tag (section 15). You remove it together with its marker once
the condition is gone. A weakening without a marker detected by a pattern is a warning — mark it or remove it.

### 19.4 Check evidence and PR status (with a repository integration)

After `git commit` the hook saves evidence that the `commit`-point checks passed for that SHA, and
after `git push` to a task branch it posts the status **"Telesma: checks (local)"** on the PR (`PR status`
in `## Checks`): which checks, how many commits, when, the date of the last dependency audit. You do
none of this yourself — and you **never post statuses by hand** (`gh api … statuses`): a green
status must mean "the hook saw it", not "Telesma says so".

- A red status saying "no check evidence for … commits" = some commit of the branch was made outside
  the hook (by hand, with `--no-verify`, with another tool) or before the checks were enabled.
  Fix: `git commit --amend --no-edit` as a plain Bash command (the hook runs the checks and assigns
  the evidence), then `git push --force-with-lease` to your own branch. Never remove the status or ask
  the human for an exception — this is not a finding in the code.
- A red status "check did not run" = at some commit a check reported an error (tool missing, time
  limit). Tell the human — the operation went through without it.
- After a push the hook tells you what it posted (or that it failed — e.g. no `gh`). A failed post
  **does not block** work; note it in REPORT.md under the task.
- Rebase and squash change the SHA; the evidence is found by the content of the change (`git patch-id`),
  so after `rebase --onto origin/main` (17.5) the status stays green without your involvement.
