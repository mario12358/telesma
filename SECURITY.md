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

- The judge only ever **removes** prompts; anything it is unsure about is asked of the human.
  An `ALLOW` from the model is the only decision with an effect, and the evaluation gate
  (`tools/telesma-judge-eval.py`) requires zero false allows on the dangerous set.
- Quality checks never print secret values, only a rule, a file, a line and a fingerprint.
- Telemetry is off by default. When enabled it sends counters and Telesma's own notes, never
  `telesma/spec/`, source code, `telesma/changes/` or commands from the judge log.
