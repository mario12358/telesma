# Contributing to Telesma

Thanks for considering a contribution. Telesma is a small codebase with strong conventions, so a few
minutes with this page saves a review round.

## Layout in one paragraph

`telesma.sh` is the launcher: it prepares a project, rotates and validates state files,
assembles the startup prompt from `templates/instructions/*.md` and starts Claude Code.
`templates/` holds everything copied into a user's project (config, state-file templates,
technology guidelines, the permission-judge hook, quality checks, integrations).
`tools/` holds standalone utilities (repair, telemetry, judge evaluation, migration) and the
self-tests. `benchmark/` is a frozen project used to compare Telesma versions. Start with
`CLAUDE.md` for the architecture and `docs/` for user-facing behaviour.

## Ground rules

- **Python is stdlib-only, Bash is plain Bash 3.2+** (macOS default). No new runtime dependency
  without discussion: Telesma is cloned, not installed.
- **Everything in English** — identifiers, comments, messages, docs.
- **State files are a contract.** Section names, task keywords and field labels in
  `templates/*.md` are parsed by the launcher, the tools and the checks, and written by the model
  following `templates/instructions/`. Changing one means changing all of them and adding a
  migration (see below).
- **The judge only removes prompts.** A change to `telesma-permission-judge.py` may never turn an
  "ask the human" into an allow without passing the evaluation gate
  (`python3 tools/telesma-judge-eval.py`), and may never add a hard deny where asking would do.
- **Checks never print secrets** and never block on network failures.
- Commit and PR footers produced by Telesma are exactly `🤖 Generated with Telesma`.

## Tests

```bash
tools/test-all.sh            # every self-test
tools/test-all.sh checks     # only files whose name contains "checks"
bash -n telesma.sh
```

Each test builds its fixtures in a temporary directory. A change to a parser comes with a fixture
that would have failed before it.

## Versions and migrations

Two independent numbers:

- **Release version** (`vX.Y.Z` git tag, `CHANGELOG.md`) — what users install.
- **`TELESMA_FORMAT`** in `telesma.sh` — the internal state-format counter stored in each
  project's `telesma/state/.telesma-version`. Bump it when a project's files must be migrated, or when a
  change in the instructions should be measurable in telemetry, and add the migration step to
  the launcher's version gate.

## Pull requests

One topic per PR, a description of the behaviour change (not just the diff), tests green,
and an entry in `CHANGELOG.md` under "Unreleased".
