# Changelog

All notable changes to Telesma are documented here. Release versions follow
[Semantic Versioning](https://semver.org). The internal state-format version (`TELESMA_FORMAT`,
stored per project in `telesma/state/.telesma-version`) is independent and listed per release.

## Unreleased

State format: 20 (unchanged).

- The baseline at adoption checks only the tools its own command calls. The wizard's default
  linter and typechecker for Python (`ruff check .`, `mypy .`) are often not installed on the
  machine that adopts a project; the baseline does not run them, yet their absence left it
  `NOT RUN` — on such machines, and on the CI runners, where `test-setup.py` failed since 1.3.0.
  `preflight_stack` takes the command as a third argument; the pre-build check is unchanged.

## 1.3.0 — 2026-11-04

State format: 20 (a new instruction module, two new `## Project` fields that the config merge adds
on the next start — a format-19 project is stamped 20 without any other change).

- **Adopting an existing project**: `telesma.sh --adopt` takes over code Telesma did not build.
  The launcher checks the preconditions (code, a git commit, a clean tree — `git init` and a first
  commit are offered, secrets go into `.gitignore` first), runs the setup wizard and sets
  `Adopted: yes` / `Adopted at`. The next start records the test baseline in `REPORT.md`, runs the
  quality checks once over the whole repository when they are on, mines the git history into a
  `SURVEY:` block (`tools/telesma-survey.py` — counts and paths, never an author or a subject) and
  writes `### Phase 0: Existing system` into the plan, one task per part of the code; a survey
  session (`templates/instructions/SURVEY.md`, section -3) then works through Phase 0 and writes
  `telesma/spec/AS_BUILT.md` — the system as found, one `When …, then …` line per behaviour with
  `path:lines` and a `[verified by test]` / `[inferred]` tag — plus `PROJECT_CONTEXT.md` and the
  conventions found, writing only inside `telesma/` (permission mode `default`, an `Edit(telesma/**)` allow rule — a write anywhere
  else is refused). The clarification has one branch for adopted projects (open questions become
  assumptions or questions, Phase 0 stays, the plan starts at Phase 1, a red baseline proposes
  characterisation tests first); a test red at adoption is an inherited failure, not a regression;
  modes 2 and 3 work before the clarification. The telemetry `state` event carries an `adopted`
  flag. The baseline's numbers (JUnit XML of the run, or the summary line of pytest, jest, cargo,
  dotnet) fill the metrics table of `REPORT.md`; a deep single-root layout (`app/src/main/java/…`)
  is split into one survey task per child directory; every line of the adoption the person reads
  is in the project's language (Polish catalog). `docs/ADOPTION.md` (the proposal) is replaced by
  `ARCHITECTURE.md` §21 and `WORKFLOW.md` §19.
- Startup-prompt diet for the guidelines index: in the implementation modes the full `tag —
  keywords` line stays only for the tags the project uses (the plan's `(tech:)` tags and Stack
  line, the detected manifests) and for `general.md`; the other guidelines are named in one line.
  Every file is still delivered to `telesma/guidelines/`, and the clarification sees the full index.
  Measured: 8 KB → under 2 KB per session on a project with three tags.
- CI hardened the way `guidelines/github-actions.md` tells user projects to: read-only token,
  `persist-credentials: false`, a 30-minute job timeout, actions pinned to a commit SHA with
  Dependabot bumping them, stale runs cancelled. The Specky CI template delivered to projects
  gets the same read-only token, a timeout, `persist-credentials: false` and PR-only cancellation.

## 1.2.1 — 2026-11-04

State format: 19 (unchanged).

- The installers put a `telesma` command in `~/.local/bin` (a symlink on macOS and Linux; on
  Windows a Git Bash script plus a `telesma.cmd` for PowerShell and cmd, the folder added to the
  user's PATH), so the quick start no longer repeats `~/tools/telesma/telesma.sh`.
- README reworked around one install path and one command: a comparison table under "Why
  Telesma", a "which start does what" table in the quick start, three showcase thumbnails, an FAQ,
  the 48 guidelines folded away, the wizard, session, integrations, safety and language sections
  cut to a few lines each with links into `docs/`.

## 1.2.0 — 2026-11-03

State format: 19 (instruction change only — a format-18 project is stamped 19 at the next start,
no file is migrated).

- Earlier decisions are recalled instead of re-made. The logs that are never in a prompt
  (`DECISIONS.md`, `BUGFIXES.md`, `REVIEWS.md`, `QUESTIONS.md`, the archives) were also never read:
  a design question that came back months later was answered from scratch and logged as a second,
  different decision; a change request could silently reverse an answer given in clarification; a
  bug fixed in bugfix mode never became a known pitfall; an overturned decision stood next to the
  old one, pinned forever. Now, before any answer, fix proposal, change plan or question to the
  user, one Grep of the topic across those files (section 0.6) — a hit opens the reply with what was
  agreed, when and why — the outcome quoted verbatim, not paraphrased (a paraphrase written while
  weighing a new idea drifts towards what the idea needs) — and asks whether it still holds; a
  proposal that contradicts the hit gets the question "change the decision, or the proposal?"
  before any recommendation, and no tool that writes runs until the user answers. A logged
  recommendation nobody answered is not a decision: its entry starts with `No decision —
  awaits: …`, and recall treats it as the question returning, not as consent. `Key decisions` and `Known problems` rows
  end with a pointer to their full entry (`→ DECISIONS.md 2026-04-23 16:42`, `→ QUESTIONS.md A7`,
  `→ BUGFIXES.md …`); clarification answers become `Key decisions` rows; a change that contradicts a
  decision blocks with the decision quoted instead of being planned; bugfix mode adds recurring
  causes to `Known problems`; an overturned decision is edited in place (`~~old~~ → new`,
  `superseded: …`), never added beside the old row. No structural token changed.

## 1.1.1 — 2026-11-03

State format: 18 (unchanged).

- Smart App Control on Windows 11: before a session that builds, a project whose tools compile
  their own programs (`dotnet`, `cargo`, `go`, `flutter` …) is told that Smart App Control is on,
  that it refuses what Telesma builds there — the tests included — with no "run anyway", how to
  turn it off and that on many Windows versions it cannot be turned back on without reinstalling.
  A beginner's build does not start; a developer is warned. Python and Node projects pass (a
  signed interpreter). `--doctor <project>` shows the state. The `wpf` and `pyside6` guidelines
  tell the model to stop with `TELESMA BLOCKED` on that error instead of retrying — the first
  Windows beginner project hit it three times half-way through.
- `SHOWCASE.md`: the first six programs built with Telesma, with screenshots.
- A newer Telesma release is offered at the start: "A new Telesma version is out: 1.2.0 (this one
  is 1.1.0). Update now?" in the system language; yes is `git pull --ff-only` (nothing local is
  overwritten — a clone with edits gets the command instead) and the launcher starts itself again.
  Without a terminal, the news and the command. Commits behind without a new release: the line
  for developers as before.

## 1.1.0 — 2026-11-02

State format: 18 (unchanged).

- The first-start wizard asks for the language and the experience first and proposes the
  system's language; from there every line of the wizard, the `[Y/n]` letters (`[T/n]`, `t` = yes)
  and the configuration summary are in that language (`templates/messages/<lang>.txt`, read by
  `configure.py summary --lang` too), as are the mode menu, the clarification hints and its end.
  `beginner` chosen there leads straight to the short setup. The merge report of `config.md`
  prints only when a section or field was added or the file carries a field the template does
  not know — the list of kept values is gone. A project with no code yet answers the stack
  question with `later` (the default): the clarification picks the stack, and the first start
  after the plan reads its `Stack` line, proposes the test commands and permission rules for it
  (`configure.py tests`) and asks once — a guess before the spec was even read is gone.
- `telesma/spec/TECHNICAL_GUIDELINES.md` is optional: left as it is (marker in line 1) it means
  "the defaults apply" and never blocks the start — the wizard's next steps say so, and the
  clarification does not ask about it. Alone in `telesma/spec/` it still counts as no spec.
- The wizard ends by asking "go on?" (ENTER starts the clarification) and the clarification by
  asking "Start building now?" (ENTER starts the loop; `n` prints the one command that continues)
  instead of commands to type — for a developer too; `-m 1` is no longer listed before a plan
  exists. A session is closed
  with `/exit` wherever the launcher or the model says how to go on — not Ctrl+C twice.
- A rejected assumption whose comment is not a decision ("I do not understand") is the one
  question the plan session may ask: it explains, waits for the answer, writes it into
  `QUESTIONS.md` and only then plans — before, it planned on its own proposal and said so after.
- Two safety nets around `QUESTIONS.md`: a contradiction or question with ✅ and an empty
  Resolution/Answer was never shown to the user and goes back to the queue on every start, not
  only right after generation; and the plan session is told to edit the State line, never to
  rewrite the file — if it does anyway, the answers are put back from a copy taken before the
  session, and the questions whose answer differed from the proposal are named, because the plan
  was made without them.
- Starting from an idea: `telesma.sh --new <project>` interviews you (six plain questions, one at
  a time — `templates/instructions/INTERVIEW.md`), writes `telesma/spec/` itself (`IDEA.md`,
  `REQUIREMENTS.md` with "when …, then …" checks, `APP_FLOW.md`, the filled technical template),
  picks the technology from who will use the program and where (a fixed table), fills `## Tests`
  for it, reads everything back and then runs the setup. Interrupted → `--new` again continues.
- `Experience: developer | beginner` in `## Project`. `beginner` appends the `EXPERIENCE` block
  (`BEGINNER.md`) after the `LANGUAGE` line: plain words, one question at a time with a default,
  the effect of an action instead of its command, progress in one sentence; the clarification
  accepts Telesma's assumptions and names the first three; the first-start wizard applies the
  recommended profile without the questions a beginner cannot answer and asks only about
  telemetry. Mechanics, permission prompts and state files are unchanged. The wizard asks for it
  next to the language.
- A beginner is led, not handed commands: after the settings Telesma asks "go on?" and starts the
  clarification; after the plan, whether to start building. No → one command continues with the
  right next step. The telemetry question is one plain yes/no; a hub that does not answer is one
  sentence. A plain start offers "build on" or "something does not work".
  Closing a build or bugfix session brings a beginner back to that menu (with the steps still
  open). Telesma builds the program itself and opens the folder with it on screen instead of
  handing over a build command, asks to try it before proposing a version, and gives any command
  it needs as one that works from every folder.
- Desktop programs: new guidelines `wpf` (MVVM with CommunityToolkit.Mvvm, ViewModels in a plain
  library testable on any OS, FlaUI for the few end-to-end flows, one self-contained exe,
  SmartScreen) and `pyside6` (Qt-free core, pytest-qt headless, PyInstaller per system, Gatekeeper
  and SmartScreen). The interview's technology table moves to .NET 10 (.NET 8 support ends
  November 2026) and Python 3.13 with uv, and says that a program for a system is built and tried
  on that system.
- Every start checks what the machine needs — git, Python 3.9+ as `python3`, Claude Code and its
  sign-in — before anything is created, and names what to install for this system (macOS, Linux,
  Windows/Git Bash), in the system language. On Windows, where python.org installs `python` and
  `python3` is the Store placeholder, it offers to create `python3.exe`. `telesma.sh --doctor`
  runs the check on its own. `.gitattributes` keeps LF line endings on a Windows checkout.
- Before a session that builds, the programs the project's `## Tests` commands call (`dotnet`,
  `uv`, `npm` …) must be on the machine: a missing one is named with what to install, and with
  winget (Windows) or Homebrew (macOS) Telesma offers to install it — only after "yes". A beginner's
  build does not start without it; a developer is warned. `telesma.sh --doctor <project>` checks
  them too.
- A beginner's plan ends with a packaging task: the program as one file to double-click, started
  from where it was placed, with a short "how to use" text next to it in the person's language.
- A hook that fails (a crash, not a check refusing with a reason) stops the session with
  `TELESMA BLOCKED` and its error; the model never gets the same write through another tool or
  edits the hook setup.
- One-line installers for people who do not program: `install.ps1` (Windows: Git for Windows,
  Python with a `python3.exe`, Claude Code via `winget` / the official installer) and `install.sh`
  (macOS: Apple's command line tools, Claude Code), each asking before every installation, then
  Telesma itself, the Claude sign-in and a «Telesma» desktop shortcut. Run again = update.
- `telesma.sh --home [folder]`: the shortcut's start menu — a new idea (a folder named from a
  working name, then the interview) or one of the projects, newest first, with where each stands;
  an interrupted interview continues. Projects live in `~/Telesma`, outside the folders iCloud or
  OneDrive sync.
- Launcher messages in your `Language`: `templates/messages/` (Polish now) covers the interview,
  the settings, telemetry, the clarification questions and the next steps; a language without a
  catalog falls back to English. The system language comes from `LANG`, else from the system
  itself: `AppleLocale` on macOS, the Windows locale in the registry under Git Bash (which sets no
  `LANG`).
- Every release says how to start it: the "version created" message has a `Run it:` line (the
  built file with its full path to double-click, a command that works from any folder, or the
  address), the scenarios file opens with "Start the version", `docs/RUNBOOK.md` starts with it and
  `TELESMA COMPLETE` repeats it — after the first Windows game shipped as v0.1.0 with the tests and
  scenarios described but no word on how to play it.
- Home, Desktop, Documents, Downloads and the projects folder `~/Telesma` are never made into a
  project: started there (or with no path from there — a desktop shortcut of an older version),
  the launcher creates nothing and names the command that starts a project in a folder of its own.
- A rerun of an installer whose `~/.telesma` cannot be brought to the branch asked for (another
  history, files git does not know) keeps the old clone whole as `~/.telesma.old-<date>` and
  downloads Telesma again, instead of stopping.

- Shared, opt-in Telesma hub: the setup wizard (every profile, default no) asks once, listing
  everything that is sent; a yes registers a token of this machine's own (`~/.config/telesma/hub`)
  and sets `Endpoint: shared`. A committed `Send: yes` no longer switches anyone on: a person who
  clones such a project is asked once on their machine. `Scope: metrics` sends numbers only.
  To the shared hub the sender's name is not sent and an empty `Project label` is the project hash.
- `telesma.sh --telemetry-forget`: deletes everything this machine sent to the shared hub and
  withdraws the opt-in. Privacy page: `<hub>/privacy`.
- Own self-hosted server works as before (`Endpoint: https://…`, `API key`); `API key: auto`
  reads the opt-in token.

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
