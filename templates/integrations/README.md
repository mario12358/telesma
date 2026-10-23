# Integrations

By default Telesma **has no integration at all**: it commits to the current branch, never pushes, knows no
requirement tracker. An integration is an optional module that changes the definition of "task done" —
switched on by the fields of the `## Integrations` section in `telesma/config.md`, configured with the wizard
(`./telesma.sh --integrations <project>`; it also starts on its own the first time `config.md` is created).

Two types, independent of each other:

| Type | Config field | Today | What it changes |
|------|--------------|-------|-----------------|
| git repository | `Repository: github` | `git/github/` | a branch per task → PR → checks → merge; task ✅ after merge; open PR limit; `TELESMA WAITING` |
| requirement tracker | `Tracker: specky` | `tracker/specky/` | requirement anchors in the plan, `Specky-Req` trailer in commits, `specky: crit` above tests, sync → `telesma/changes/` |

Both at once = the full contract (the PR gets the "Specky contract check" status; the wizard copies
`specky-ci.yml`).

## One directory = one integration

```
<type>/<name>/
├── INSTRUCTIONS.md   # instruction section appended to the prompt when the config field = <name>
├── setup.sh          # wizard: checks tools, asks questions, writes fields to telesma/config.md
├── permissions.txt   # rules for "Allowed commands" (one per line, # = comment)
├── DESCRIPTION.txt   # "how this will work" — printed by the wizard, copied into the docs
└── (own files)       # e.g. specky-ci.yml
```

`telesma.sh` reads `Repository:` and `Tracker:` and appends `integrations/git/<value>/INSTRUCTIONS.md`
and `integrations/tracker/<value>/INSTRUCTIONS.md` after the mode sections, before `INTERACTIVE.md`.
A value without a directory = a red error and a stop. `none` = nothing. The fields of the `## Integrations`
section live in `templates/config.md` (the single source of their comments).

## How to add an integration (e.g. `git/gitlab`)

1. A `git/gitlab/` directory with the five files above. `INSTRUCTIONS.md` gets section number 17
   (repository) or 18 (tracker) — the section **overrides CORE steps by reference** ("instead of
   step 12 of section 1…"), it does not copy them.
2. `setup.sh`: `source "$SCRIPT_DIR/templates/integrations/lib.sh"` (`config_field`, `set_field`,
   `add_permissions`, `ask_value`, `ask_yes_no`, `show_description`). It checks the hosting CLI (`glab`),
   the login, the remote; writes `Repository: gitlab` + the fields. Exit code 1 = aborted, the section
   stays at `none`.
3. The permission judge (`templates/hooks/telesma-permission-judge.py`, its git integration rules) knows `gh`;
   for another CLI you have to add recognition of its merge/push commands — otherwise everything asks
   the human (safe, but the loop stops on every merge).
4. The config validator in `telesma.sh` (section `Integrations`) — add the name to the
   list of allowed values and the CLI check.
5. The wizard (`wizard.sh`) — a menu entry.
