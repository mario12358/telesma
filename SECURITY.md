# Security policy

Telesma runs an AI agent with access to your shell and installs Claude Code hooks that approve or
block commands on your behalf (the permission judge, `templates/hooks/telesma-permission-judge.py`)
and gate git operations (quality checks, `templates/checks/`). A flaw in either can let a command
through that should have reached a human. Please report such problems privately.

## Reporting a vulnerability

Email **mariusz.iskra@gmail.com** with:

- what the problem is and which component it affects (judge layer, read layer, a check, the launcher),
- a minimal command or project state that reproduces it,
- the Telesma version (`git describe --tags`) and your OS.

Please do not open a public issue for anything that lets a command bypass the judge or a blocking
check. You will get an answer within a week. Fixes are released as a patch version and credited in
`CHANGELOG.md` unless you prefer otherwise.

## Scope

In scope: the permission judge (hard patterns, `Always ask`, read layer, disguised-write rules,
model layer, git integration gate), the quality checks runner and modules, the launcher's handling
of `.claude/settings.local.json`, and anything that could leak secrets into telemetry.

Out of scope: behaviour of Claude Code itself, of the model you configure as a judge, and of
third-party tools Telesma calls (`gh`, `gitleaks`, `semgrep`).

## Design guarantees you can rely on

- The judge only ever **removes** prompts; anything it is unsure about, or cannot parse, is asked
  of the human. An `ALLOW` from the model is the only decision with an effect, and the evaluation
  gate (`tools/telesma-judge-eval.py`) requires zero false allows on the dangerous cases of a
  working set and of a held-out set. That is a statement about those sets, not a proof: the judge
  reads command lines, it does not sandbox them, and it cannot see what a script, a Makefile
  target or a package script does once allowed.
- A committed `telesma/config.md` cannot run a command, choose a permission mode or name a server
  on your machine before you have seen the value: the launcher shows new or changed executable
  fields and asks once per machine (`~/.config/telesma/trust/`).
- Quality checks never print secret values, only a rule, a file, a line and a fingerprint.
- From state format 21 the agent does not commit, push or merge: a hook refuses `git add` /
  `git commit` and the other history-writing git commands, GitHub writes (`gh pr create/merge`,
  `gh api` with a method or fields), ticking tasks and editing the report's history, and the task tool commits exactly the files it ran the tests and
  the checks on. The hook reads command text like the judge; a script the agent writes and then runs
  is outside what it can see — the commit evidence and CI are the layers that verify the result.
- Telemetry is off by default. The shared hub needs a per-machine opt-in that a committed config
  cannot give; your own server needs https, a key, and the `## Telemetry` section confirmed on
  that machine. When enabled it sends counters and Telesma's own notes (numbers only with
  `Scope: metrics`). It never sends the files in `telesma/spec/` or `telesma/changes/`, source
  files, or commands from the judge log; with `Scope: full` the text of Telesma's own entries
  goes out after scrubbing, and such an entry can quote a path, a line of code or your words —
  [docs/TELEMETRY.md](docs/TELEMETRY.md) lists exactly what leaves.

## What Telesma does not protect against

- The agent runs with your user's permissions. With `## Sandbox → Enabled: yes` (the default for
  new projects) Claude Code's sandbox limits what Bash commands may write, read and reach; file
  edits through Claude Code's own tools, `Excluded commands`, MCP servers and a project without the
  sandbox (native Windows, `Enabled: no`) are outside it. Run untrusted projects in a container or
  a separate account.
- Text the model reads (a spec, a change request, a fetched mockup page, the code of an adopted
  project) can try to instruct it. The instructions tell the model to treat such text as material
  and to stop on it; that is a mitigation, not a boundary.

## Supported versions

Security fixes are released for the latest minor version only.
