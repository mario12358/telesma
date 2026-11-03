<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/telesma-logo-dark.svg">
    <img alt="Telesma" src="docs/assets/telesma-logo-light.svg" width="520">
  </picture>
</h1>

<p align="center">
  <b>Describe it. It builds it.</b><br>
  From a written specification to tested, committed code — in one continuous Claude Code session.
</p>

<p align="center">
  <a href="https://github.com/mario12358/telesma/actions/workflows/test.yml"><img alt="Tests" src="https://github.com/mario12358/telesma/actions/workflows/test.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
</p>

> **Not a programmer?** [Start here](#not-a-programmer-start-here): one line to install, then an icon on
> your desktop. **Developer?** Read on, or jump to the [quick start](#quick-start).

**Telesma is an autonomous development loop for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).**
You put a specification into `telesma/spec/`, answer the questions Telesma asks about it, and Telesma turns it
into a plan and works through that plan task by task — implement, test, commit, report, next —
inside a single, continuous Claude Code session.

Telesma builds on the "Ralph loop" technique — run an agent in a loop over a plan until the plan is
done — and adds what a real project needs around it: clarification, contracts in the plan, state
that survives compaction, quality checks and releases. The name is Greek: _télesma_, "completion,
accomplishment" — the word "talisman" comes from it.

Telesma has been used in production for over a year before its public release, on projects of up to
about two thousand planned tasks; the mechanisms described below come from that experience.

```mermaid
flowchart LR
    spec["telesma/spec/<br/>your specification"] --> clarify["Clarification<br/>contradictions · assumptions · questions"]
    clarify --> plan["PLAN.md<br/>phases · tasks · acceptance criteria"]
    plan --> loop
    subgraph loop["One Claude Code session"]
        direction LR
        next["next task"] --> impl["implement"] --> test["test + quality checks"] --> commit["commit + report"] --> next
    end
    loop --> phase["phase done:<br/>full suite + tag"]
    phase --> release["release proposal<br/>vX.Y.Z — you decide"]
    changes["telesma/changes/<br/>change requests"] --> plan
```

## Why Telesma

Most Claude automation restarts the CLI for every task, or keeps one long chat that slowly forgets
what it was doing. Telesma does neither:

- **One continuous session.** Claude runs the iteration loop itself: pick the next task (respecting
  dependencies), load only the spec fragments and conventions that task needs, implement, run the
  tests, check for regressions, mark the task done, commit, and move on.
- **State lives in files, not in the context window.** `telesma/state/PLAN.md`, `telesma/state/REPORT.md` and
  `telesma/state/PROJECT_CONTEXT.md` are updated after every task, so an auto-compaction or a restart
  resumes exactly where the work stopped.
- **The rules that matter are enforced by scripts, not by the model's memory.** The launcher
  validates the plan and the config, rotates state files and trims the startup prompt before a
  single token is spent; git hooks run quality checks on every commit and tag; a permission hook
  removes prompts you would have approved anyway.

## Is it for you?

**A good fit:** a new product or a substantial feature with a written specification (any format —
Markdown, Word, PDF, mockups), built over days or weeks, where you want the work to stay traceable:
the plan, the report, the decisions and every change request live in files in your repository.

**Not a fit:** a one-off fix or a small script (use Claude Code directly), or a project with no
automated tests — Telesma treats green tests as the definition of done, and the launcher stops
before the loop until test commands are set.

**Cost:** Telesma runs on your own Claude Code plan or API key. Long autonomous runs consume a
noticeable part of a plan's usage limits; the launcher keeps the startup prompt small, but the
implementation itself is the bulk of the cost.

## Key features

- **Clarification phase** — Telesma reads the whole spec, rates its quality, and walks you through
  contradictions, assumptions and an adaptive number of questions before it plans anything.
- **Plan with contracts** — tasks carry dependencies `(requires:)`, spec references `(spec:)`,
  technology guidelines `(tech:)`, UI mockup references `(ui-*:)` and acceptance criteria `- AC:`,
  including `- AC: entry` ("what triggers this in the running product").
- **Selective retrieval** — the spec is never loaded whole; an anchored index points each task at
  the exact line range it needs.
- **Technology guidelines** — general clean-code rules plus 48 convention files — languages (Python, TypeScript, Go, Rust, Java,
  Kotlin, Swift, C#, PHP, Ruby), frameworks (React, Next.js, Vue, Svelte, Angular, React Native,
  Flutter, FastAPI, Django, Spring, NestJS, Node, Deno, Hono, HTMX, Tailwind), data (SQL, PostgreSQL,
  MySQL, SQLite, MongoDB, Redis, GraphQL, REST API design), infrastructure (Docker, Kubernetes,
  Terraform, GitHub Actions, Caddy, observability, k6), testing (Playwright, Detox), accessibility,
  LLM-powered features, robotics — loaded per task; add your own.
- **Four modes** — autonomous loop, bugfix chat, context-aware code review, visual-artifact backfill.
- **Change channel** — after clarification the spec is frozen; changes arrive as files in
  `telesma/changes/` and become plan edits or rework phases.
- **Releases** — Telesma proposes a release version at the right moments, writes manual test
  scenarios for what automated tests could not check, and tags only after you say yes.
- **Integrations** (optional) — GitHub pull-request workflow and the Specky requirements tracker.
- **Quality checks** (optional) — secrets, deliberate weakenings, hallucinated packages, known
  vulnerabilities, weakened tests, repository hygiene, dead entry points, SAST, lint/types, and an
  attack-surface map with red-team markers — all triggered by git operations.
- **Permission judge** (optional) — a hook that answers permission prompts for you, and only ever
  removes prompts, never adds blocks.
- **Cheap to restart** — state-file rotation, a startup-prompt diet and a state-file diagnosis with
  a git-based repair keep the cost of a start flat as the project grows.

## Not a programmer? Start here

Telesma takes you from an idea to a program on your computer. It asks what you want, writes it
down, builds the program, tests it and hands it to you as one file to open with a double-click.
You never type a command.

**1. Install it.** One line, copied and pasted. The installer says what it is about to install and
asks before each step; at the end there is a **Telesma** icon on your desktop.

- **Windows 10 or 11**: press Start, type *PowerShell* and open it (the normal one, not "Run as
  administrator"). Paste this line and press Enter:
  ```powershell
  irm https://raw.githubusercontent.com/mario12358/telesma/main/install.ps1 | iex
  ```
- **Mac**: press ⌘ Space, type *Terminal* and open it. Paste this line and press Enter:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/mario12358/telesma/main/install.sh | bash
  ```

It installs the few programs Telesma needs, then Claude Code, and opens your browser to sign in to
your Claude account. When a new Telesma version is out, Telesma says so at the start and asks
whether to update; the same install line, run again, does it too.

**2. Double-click Telesma.** A menu opens: *a new idea*, or one of your programs. Pick a new idea
and Telesma interviews you: six plain questions, one at a time, about ten minutes. It reads the
answers back, asks about a few details, plans the work and builds. When the program is ready it
opens the folder with it and says what to try. Later, the same icon shows your programs with
*Build on* and *Something does not work right*. Your programs live in a *Telesma* folder in your
home folder. [Six programs built this way](SHOWCASE.md).

**Good to know before you start:**

- You need a Claude account with a paid plan (Pro or Max). There is no free way, and building a
  program uses a good part of a plan's monthly limit.
- Claude asks before some actions (installing something, deleting files). Telesma words those
  questions plainly, but you answer them.
- A program is built on the kind of computer it is for: a Windows program on Windows, a Mac
  program on a Mac. The interview offers a program with a window, a page in your browser on your
  own computer, or a command-line tool. A website for other people or a phone app needs hosting,
  accounts and app stores, so the interview does not offer it yet — Telesma itself builds those
  too, from a written specification (the developer path below; see the [showcase](SHOWCASE.md)).
- A freshly built program has no publisher signature. Windows may warn once ("More info" → "Run
  anyway"); Windows 11 with *Smart App Control* on refuses it altogether — Telesma says so before
  building and what the choice is.
- Something wrong? Double-click Telesma, pick the program, choose *Something does not work right*
  and say what you saw.

## Requirements

| Required                                                                     | Optional                                                                        |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `bash` (3.2+, the macOS default works)                                       | `gh` (GitHub CLI ≥ 2.41) — GitHub integration                                   |
| `python3` (standard library only)                                            | `gitleaks` — wider secret detection in the `secrets` check                      |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude`) | `semgrep` — OWASP rule packs in the `sast` check                                |
| `git`                                                                        | `pandoc` — converts `.docx` / `.pdf` / `.odt` / `.rtf` files in `telesma/spec/` |

Telesma is cloned, not installed. Nothing is added to your project's dependencies. Every start checks
the required column (and that Claude Code is signed in) and says what to install; `telesma.sh --doctor`
runs the same check on its own (`--doctor <project>` also checks the programs its test commands call). On Windows Telesma runs in Git Bash, which Claude Code needs there too.
The one-line installers above put Telesma in `~/.telesma` (`%USERPROFILE%\.telesma` on Windows, opened in Git
Bash) and the desktop icon runs `telesma.sh --home`; a rerun updates it, a clone it cannot update is kept as
`.telesma.old-<date>`. Every start checks for a newer release and offers `git pull --ff-only`
(`TELESMA_NO_UPDATE_CHECK=1` turns the check off).

## Quick start

### 1. Clone Telesma

```bash
git clone https://github.com/mario12358/telesma.git ~/tools/telesma
```

### 2. Initialise your project

```bash
~/tools/telesma/telesma.sh /path/to/project
```

The first run creates `telesma/spec/` with one template and prints what goes where. Everything
Telesma reads and writes in your project lives in that one `telesma/` directory:

```
your-project/
├── telesma/
│   ├── config.md     configuration (tests, git, integrations, checks, judge, telemetry)
│   ├── spec/         your specification — frozen after clarification
│   ├── changes/      change requests after the freeze (+ processed/)
│   ├── state/        written by Telesma: PLAN.md, REPORT.md, PROJECT_CONTEXT.md, SPEC_INDEX.md, logs
│   ├── guidelines/   technology guidelines (copied from Telesma, your edits win)
│   ├── checks/       quality-check modules (only with checks enabled)
│   └── artifacts/    screenshots and recordings (only with visual artifacts enabled)
├── .claude/          Claude Code settings and the permission-judge hook (Claude Code looks for them here)
└── docs/             RUNBOOK.md and test-scenarios/ — documentation of your project, not of Telesma
```

### 3. Write the specification

**No specification, just an idea?** `~/tools/telesma/telesma.sh --new /path/to/project` replaces
steps 3 and 4: the interview from [Not a programmer?](#not-a-programmer-start-here) writes
`telesma/spec/` itself (the idea in your words, numbered requirements with "when …, then …" checks,
the user flows, the technology) and runs the setup. It sets `Experience: beginner` (plain words,
see [Language and experience](#language-and-experience)); `--setup` switches it back.

- `telesma/spec/TECHNICAL_GUIDELINES.md` — fill in **only** the fields where you depart from the defaults
  in `telesma/guidelines/` (a mandated stack, hosting, integrations, compliance or SLA requirements).
  An empty field means the default wins, and the file left as it is means the defaults apply —
  the start does not wait for it. Delete the `TELESMA_SPEC_TEMPLATE` marker from its first line
  once you fill something in.
- Any other files with business and functional requirements: goals, use cases, user stories,
  domain model, business rules, acceptance criteria, diagrams. Any format.
- Optional: mockups, design tokens and reference components in `telesma/spec/ux_ui/`.

### 4. Run the setup wizard

```bash
~/tools/telesma/telesma.sh /path/to/project
```

With a specification in place, the second run creates `telesma/config.md` and walks you through
it, one module per question, ENTER accepting the recommended answer:

| Step | What it decides | Recommended |
|---|---|---|
| Language and experience | Asked first, so the rest of the wizard talks in that language: the language Telesma talks and writes prose in; `developer` or `beginner` (plain words — a beginner then gets the short setup) | the system's language, `developer` |
| Profile | `minimal` (the loop only), `recommended`, `full` | `recommended` |
| Stack and tests | Detects the stack from manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, …, also one level down in a monorepo) and proposes the test, lint and typecheck commands; a project with no code yet leaves it to the plan (`later`): the clarification picks the stack, and the first start after the plan proposes the commands and permission rules for it | detected / `later` |
| Permission prompts | The permission judge: `rules` (no model — provable reads pass, everything else still asks you), `command` (a model decides the gray zone), `off` | `rules` |
| Quality checks | `basic` (secrets, weakenings, weakened tests, hygiene — no network, no tools), `standard` (+ dependencies, vulnerability audit, SAST, lint/types, dead entry points), `security` (+ attack-surface map, red team), `none` | `basic` |
| Integrations, visual artifacts, telemetry | Asked in the `full` profile (or when mockups are already in `spec/ux_ui/`) | off |

It ends with a summary and asks whether to go on to the clarification right away; "no" prints
the one command that continues (a plain start always picks the right next step: clarification,
then the question whether to build). Change anything later with `telesma.sh --setup` (a
menu with the state of every module) or by editing `telesma/config.md` — every key is commented
there and documented in [docs/CONFIGURATION.md](docs/CONFIGURATION.md). Without a terminal (CI) the
wizard applies the recommended profile silently.

### 5. Clarify

```bash
~/tools/telesma/telesma.sh /path/to/project -i
```

Telesma indexes the spec, then guides you through contradictions → assumptions → questions (you can
stop and resume at any point; ENTER accepts the proposed answer). Afterwards it writes
`telesma/state/PLAN.md` and sets `Clarified: yes`.

### 6. Build

```bash
~/tools/telesma/telesma.sh /path/to/project          # mode menu
~/tools/telesma/telesma.sh /path/to/project -m 1     # autonomous loop, no menu
```

## How a session works

1. **Clarification** (`Clarified: no`, always interactive). Claude reads everything in `telesma/spec/`,
   writes `telesma/state/SPEC_INDEX.md` (a two-level index with line ranges, anchors and a quality
   assessment of the documentation) and `telesma/state/QUESTIONS.md` with three sections: contradictions to
   resolve, assumptions to spot-check and questions — few for a small, well-written spec, many for
   a large or thin one.
2. **Planning.** From the spec plus your answers Claude writes `telesma/state/PLAN.md`: phases, tasks with
   dependencies and tags, acceptance criteria, task 1.1 "architecture skeleton", and a
   `## Spec coverage` table mapping every spec section to tasks (or to a stated reason it is out of
   scope).
3. **Startup checks** (every run, no tokens spent). The launcher validates the plan (dependency
   graph, cycles, tags vs files) and the config, rotates state files into archives, diagnoses
   state-file damage, applies framework updates to the project, computes a next-task hint and
   assembles a trimmed startup prompt from the instruction modules your mode needs.
4. **The loop.** For each task: check dependencies → load the spec fragment, guidelines and UI
   fragments → implement → run the task tests and the smoke suite → verify the acceptance criteria
   → capture screenshots/recordings if enabled → mark ✅ → update the report → commit specific
   files (never `git add -A`).
5. **End of phase.** Full test suite for regression detection (a regression takes priority over
   new work); a green suite gets the progress tag `telesma/phase-<ID>` and a release proposal.
   Phases with UI end with an e2e task (Playwright or Detox).
6. **Finish.** When everything is done Claude writes `docs/RUNBOOK.md` (env vars, dev/test/build
   commands, seeding, ports) and prints `TELESMA COMPLETE`. If it gets stuck it prints
   `TELESMA BLOCKED` with a concrete question and saves it to `telesma/state/BLOCKED.md` for the next start.
7. **Afterwards.** The session stays open. Every exchange you have with Claude from here on is
   logged to `telesma/state/DECISIONS.md`; ideas for later go to `telesma/state/BACKLOG.md`.

Details: [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Modes

After clarification the launcher asks for a mode, or you pass `-m`:

| Mode | Name                     | What it does                                                                                                                                     | Interactive     |
| ---- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------- |
| 1    | **autonomous** (default) | The loop over `telesma/state/PLAN.md`                                                                                                            | optional (`-i`) |
| 2    | **bugfix**               | Chat: you report a bug → diagnosis → proposal → your OK → fix → test → commit → entry in `telesma/state/BUGFIXES.md`                             | always          |
| 3    | **review**               | Chat: local code review of a chosen scope against your spec, guidelines and project decisions; findings by severity → `telesma/state/REVIEWS.md` | always          |
| 4    | **artifacts**            | Backfills missing screenshots and flow recordings; idempotent, never edits the plan                                                              | optional (`-i`) |

Other launcher commands:

```bash
telesma.sh --setup /path/to/project         # configuration menu: tests, judge, checks, integrations, artifacts, language
telesma.sh --repair /path/to/project        # repair state files from git history, then exit
telesma.sh --integrations /path/to/project  # run only the integrations wizard on an existing project
telesma.sh --sync-specky /path/to/project   # pull Specky changes into telesma/changes/, no loop
```

## Integrations

Telesma has **no integration by default**: it commits to the current branch and never pushes. Each
integration is a separate instruction module that is added to the prompt only when
`## Integrations` in `telesma/config.md` names it, so a project without integrations pays nothing for
them. The integrations wizard (`--integrations`, also a step of the setup wizard) checks the tools,
writes only `telesma/config.md` and explains in ten lines how the result will behave.

### GitHub

One branch and one pull request per task; a task is done when its PR is merged, not when it is
opened. Three merge modes: `agent` (Telesma waits for the required checks and squash-merges —
works on a private repository on GitHub Free), `auto` (GitHub auto-merge), `manual`. **"Merge only
on green" is enforced, not promised:** the permission hook runs its own `gh pr checks` before
letting a merge through, even in Claude Code's `auto` mode; pushes go only to task branches, and
release tags are never pushed by Telesma.

### Specky

[Specky](https://app.specky.app) keeps the specification as a **contract between a human and an
agent**: requirements with acceptance criteria and content hashes, accepted by a human. With
`Tracker: specky` every task is anchored to a requirement version, every commit names it in a
trailer, a test marked `specky: crit <id>` proves a criterion through the JUnit report your CI
publishes, requirement changes arrive as files in `telesma/changes/`, and a release becomes a
Specky snapshot with the tag, the commit and the manual test scenarios. Specky being unreachable
never blocks anything. Specky is a product by the author of Telesma; Telesma works fully without
it (hello@specky.app).

Full reference: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

## Safety

- **Permission judge** (`## Auto-approval`; the setup wizard's recommended profile turns it on in
  `rules` mode, without a model). A Claude Code hook that answers permission prompts on your behalf.
  Its governing rule: **it only removes prompts, it never adds blocks.** Hard patterns (`rm -rf`, `sudo`, `git push`, writes to `.claude/` or `telesma/config.md`, …)
  and your own "always ask" list always reach you; provable reads pass without a model; only the
  gray zone goes to an optional LLM judge, and anything but a clear ALLOW still asks you. Every
  decision is logged locally. See [docs/PERMISSION_JUDGE.md](docs/PERMISSION_JUDGE.md).
- **Quality checks** (`## Checks`; the recommended profile enables the `basic` tier). Triggered by git operations — before `git commit`,
  before a `telesma/phase-*` tag, before a `vX.Y.Z` tag, and in CI — not by the model remembering to
  run them. A blocking finding stops the operation; a false positive is waived by a human only, in
  `telesma/state/CHECK_EXCEPTIONS.md`. With GitHub, the result is posted to the PR as the commit status
  `Telesma: checks (local)`. See [docs/CHECKS.md](docs/CHECKS.md).
- **Telemetry** (`## Telemetry`, off by default). Optional quality events about Telesma's own work,
  sent to the shared Telesma hub after an explicit opt-in on your machine (the setup wizard asks,
  default no; `--telemetry-forget` deletes your data) or to a server you host. See
  [docs/TELEMETRY.md](docs/TELEMETRY.md).
- **Commit footer.** Every commit, PR and PR comment Telesma writes ends with exactly
  `🤖 Generated with Telesma` — no model name, tool name or session link.

## Language and experience

`Language` in `## Project` (default `en`) sets the language Telesma uses to talk to you and to write
prose into state files — report entries, decisions, problem descriptions, test scenarios. Any
language code works (`en`, `pl`, `de`, …). Structural tokens — section headers, task keywords,
tags, field labels, terminal markers such as `TELESMA BLOCKED` — always stay in English, because the
scripts parse them. The launcher's own lines on the way from the idea to the first build (the
interview, the settings, telemetry, the clarification questions, the next step) come from a
catalog in `templates/messages/` — Polish is there; a language without a catalog gets them in
English while Claude itself still talks in yours.

`Experience` (default `developer`) sets who Telesma is talking to. With `beginner` it uses plain
words — "the list of steps" instead of `PLAN.md`, "a saved point in the history" instead of a
commit — asks one question at a time with the answer it would choose, says what an action does
before doing it instead of showing the command, and reports progress in one sentence. The
clarification accepts Telesma's assumptions for you and names the first three. Nothing else
changes: the same loop, the same permission prompts, the same files. `telesma.sh --new` sets it;
`--setup` changes it.

## Documentation

| Document                                             | Contents                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------- |
| [SHOWCASE.md](SHOWCASE.md)                           | Programs built with Telesma, and how to add yours                         |
| [docs/WORKFLOW.md](docs/WORKFLOW.md)                 | Clarification, plan format and tags, modes, changes, releases, monitoring |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md)       | Every `telesma/config.md` section and key, launcher flags                 |
| [docs/STATE_FILES.md](docs/STATE_FILES.md)           | Files Telesma creates in your project, rotation, prompt diet, `--repair`  |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)   | Common problems and what to do                                            |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)         | GitHub and Specky integrations in detail                                  |
| [docs/PERMISSION_JUDGE.md](docs/PERMISSION_JUDGE.md) | The permission judge: layers, variants, evaluation                        |
| [docs/CHECKS.md](docs/CHECKS.md)                     | Quality checks, attack-surface map, PR status                             |
| [docs/TELEMETRY.md](docs/TELEMETRY.md)               | Optional self-hosted quality telemetry                                    |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)         | How the launcher, instructions, hooks and tools fit together              |
| [benchmark/README.md](benchmark/README.md)           | Frozen benchmark for comparing Telesma versions                           |
| [CONTRIBUTING.md](CONTRIBUTING.md)                   | How to contribute, conventions, self-tests                                |
| [SECURITY.md](SECURITY.md)                           | Reporting vulnerabilities                                                 |
| [CHANGELOG.md](CHANGELOG.md)                         | Release history                                                           |

## License

MIT — see [LICENSE](LICENSE).

## Author

Mariusz Iskra — mariusz.iskra@gmail.com
Commercial inquiries: Sparkit — biuro@sparkit.pl
