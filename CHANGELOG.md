# Changelog

All notable changes to Telesma are documented here. Release versions follow
[Semantic Versioning](https://semver.org). The internal state-format version (`TELESMA_FORMAT`,
stored per project in `telesma/state/.telesma-version`) is independent and listed per release.

## 1.0.0 — first public release

State format: 18.

First public version.

- Continuous-session autonomous loop for Claude Code: clarification (contradictions, assumptions,
  adaptive questions) → plan with dependencies, spec/tech/UI tags and acceptance criteria →
  implement → test → commit → report, with `/compact`-safe state files.
- Modes: autonomous, bugfix, code review, visual-artifact backfill; interactive decision log and
  backlog after completion; release proposals with manual test scenarios.
- Selective spec retrieval through an anchored index; per-task technology guidelines.
- Spec change channel (`telesma/changes/`) with rework phases.
- State-file rotation, startup prompt diet, state-file diagnosis and repair (`--repair`).
- Permission judge hook (hard patterns, read layer, disguised-write rules, optional model judge
  with fallback and shadow mode) and its evaluation set.
- Quality checks triggered by git operations: secrets, weakenings, dependencies, dependency audit
  (OSV), weakened tests, repository hygiene, dead entry points, SAST, lint/types, attack-surface
  map (`intent`) and red-team markers; result posted to PRs as a commit status.
- Optional integrations: GitHub (branch per task → PR → checks → squash merge) and
  [Specky](https://app.specky.app) (requirement anchors, criteria evidence from CI, release
  snapshots with test scenarios).
- Optional self-hosted quality telemetry (off by default).
- Frozen benchmark with a hidden HTTP judge for comparing Telesma versions.
- Setup wizard: the first start asks one question per module (profile minimal / recommended /
  full, stack detection → test commands, permission judge, quality-check tier, integrations,
  visual artifacts, language) and ends with the next command; `telesma.sh --setup` reopens it as a
  menu on an existing project. The recommended profile turns the permission judge on in `rules`
  mode (no model) and the `basic` check tier.
- Quality checks in three tiers (`basic`, `standard`, `security`) instead of all-or-nothing.
- 46 technology guidelines (languages, frameworks, data stores, infrastructure, testing,
  accessibility, LLM-powered features), refreshed to current practice.
- One directory in your project: everything Telesma reads and writes lives in `telesma/` (config,
  spec, changes, state, guidelines, checks, artifacts); outside it only `.claude/` and the project's
  own `docs/RUNBOOK.md` and `docs/test-scenarios/`.
- New `Language` setting: Telesma talks to you and writes prose in your language while state-file
  structure stays English.

Hardened after the first live end-to-end trial of this version (reading-list app, GitHub + Specky,
18 tasks, release v0.1.0):

- Permission judge: a **contract layer** in the `PreToolUse` hook refuses a PR merge while a
  required check is red, pending or missing (or with `--admin`) and any push of a release tag
  (`vX.Y.Z`, `--tags`). These rules now hold in Claude Code's `auto` permission mode, where the
  `PermissionRequest` hook is never called; the trial ran in that mode and both happened. The judge
  notes an `auto` session in `telesma/state/PERMISSIONS.jsonl`, the launcher warns at the next start and
  starts Claude with an explicit `--permission-mode`. Nothing else is ever denied.
- Command fixes: `gh pr checks … | tail && gh pr merge` (the pipe hides the checks' exit code) and a
  `gh pr create` without a `Specky-Req:` trailer with the Specky tracker are sent back for correction.
- Instructions: the release tag is never pushed by Telesma, also with `Auto-push: yes` (15.4);
  the `DECISIONS.md` entry after a tag applies in the autonomous mode too (15.6); `gh pr checks` runs
  alone, never piped, before an agent merge (17.3).
- Setup wizard: the integration setup scripts received no `SCRIPT_DIR`/`PROJECT_DIR`/`CONFIG_FILE`
  and configured nothing; an empty repository has a default branch of `main` for the messages.
- Checks: dead-entry recognises a route called from a server-side template path
  (`/books/{{ book.id }}`, `<%= id %>`).
