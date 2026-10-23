# telesma/config.md - Project configuration

## Project

- **Clarified**: no
  <!-- "no"  = needs the clarification phase (Telesma reads telesma/spec/, generates questions, then telesma/state/PLAN.md) -->
  <!-- "yes" = project ready for implementation (telesma/state/PLAN.md is complete) -->
- **Language**: en
  <!-- Language Telesma uses to talk to you and to write prose into state files (REPORT.md, -->
  <!-- DECISIONS.md, scenarios, …), e.g. en, pl, de. Structural labels (section headers,   -->
  <!-- field names, task keywords) stay English — scripts parse them.                      -->

## Tests

- **Test command**: [e.g. pytest -v, npm test, cargo test]
- **Full suite command**: [e.g. pytest -v --tb=short, npm run test:all]
- **Smoke suite**: none
  <!-- A fast subset of tests run after EVERY task (regression caught immediately,       -->
  <!-- not at the end of the phase). E.g. tests of completed modules. Small projects: full suite. -->
  <!-- "none" = skip (task tests only + full suite after the phase).                      -->
- **Full suite after**: every phase
- **Linter/formatter**: [e.g. ruff check, eslint, cargo fmt -- none if you don't use one]
- **Typecheck command**: none
  <!-- Typechecker, e.g. `mypy src`, `pyright`, `npx tsc --noEmit`. The lint-types check (## Checks) -->
  <!-- runs the linter on changed files at commit, and the typechecker at phase end.               -->
  <!-- "none" = no typechecker.                                                                   -->
- **Lint before commit**: no

## Git

- **Auto-commit**: yes
- **Auto-push**: no
- **Branch strategy**: none (commit to the current branch)
- **Ignore on commit**: `.env`, `.env.*`, `*.log`, `*.tmp`, `node_modules/`, `__pycache__/`, `.DS_Store`, `*.sqlite`, `telesma/artifacts/`, `telesma/state/PERMISSIONS.jsonl`, `telesma/state/CHECKS.jsonl`
  <!-- Patterns in backticks ON PURPOSE — markdown linters turn bare *.log / __pycache__ -->
  <!-- into emphasis, silently breaking the ignore list.                                 -->

## Integrations

<!-- By default Telesma has NO integration: it commits to the current branch, never pushes, -->
<!-- knows no requirement tracker — exactly as in a project without this section. Each    -->
<!-- integration adds its own instruction section                                          -->
<!-- (templates/integrations/<type>/<name>/INSTRUCTIONS.md) and changes the definition of  -->
<!-- "task done". Wizard: ./telesma.sh --integrations <project>                        -->
<!-- (it also starts on its own the first time config.md is created).                      -->

- **Repository**: none
  <!-- none | github. Repository integration = a branch per task + PR + merge;              -->
  <!-- a task is closed on MERGE, not when the PR is opened. Requires: gh (GitHub CLI)      -->
  <!-- logged in, `Auto-push: yes` in ## Git. Telesma never pushes to main.                   -->
- **Repo**:
  <!-- owner/name on GitHub — the wizard detects it from `git remote get-url origin` -->
- **Merge**: agent
  <!-- auto   = GitHub auto-merge (`gh pr merge --auto --squash`); needs a public repo        -->
  <!--          or a Pro/Team plan (branch protection with required checks).                  -->
  <!-- agent  = Telesma waits for the checks and merges itself once green (`gh pr merge --squash`); -->
  <!--          works on Free with a private repo. GitHub enforces nothing — the rule          -->
  <!--          "merge only on green required checks" is enforced by the permission judge      -->
  <!--          (its own `gh pr checks` before every merge), not by an instruction.            -->
  <!-- manual = the PR waits for a human; it counts toward the open PR limit.                  -->
- **Required checks**: none
  <!-- Check names, comma-separated, e.g. "Specky contract check, test". In agent mode     -->
  <!-- the list must NOT be empty — an agent without a list has nothing to wait for.          -->
- **Open PR limit**: 3
  <!-- Limit reached (no PR red) = TELESMA WAITING, end of session. Nothing is broken —       -->
  <!-- start again after a merge.                                                           -->
- **Wait for merge**: 10 min
  <!-- How long Telesma waits for checks/merge after opening a PR before taking the next task. -->
  <!-- Short = more branch chains; long = slower session, simpler history.                   -->
- **Max fixes per PR**: 3
  <!-- Red check → fix on THE SAME branch (never a new PR). After this many fixes            -->
  <!-- TELESMA BLOCKED with a link to the PR. A separate counter from "Max tries per task".     -->
- **Branch prefix**: task-
  <!-- Task branch: <prefix><id>-<slug>. The judge removes the push prompt ONLY for         -->
  <!-- branches with this prefix.                                                           -->
- **Tracker**: none
  <!-- none | specky. Requirement tracker over MCP: requirement anchors on tasks, a           -->
  <!-- `Specky-Req: <id>@<hash7>` trailer in commits, `specky: crit <id>` above criterion tests, -->
  <!-- synchronization (`what_changed`, `get_work_queue`) → files in telesma/changes/.                -->
- **Tracker project**:
  <!-- project_id of the project in the tracker (Specky: the ULID from the project URL) -->
- **Tracker MCP**: https://app.specky.app/mcp
  <!-- Address of the tracker's MCP server — for documentation and the wizard; the MCP tools  -->
  <!-- are configured in Claude Code (claude.ai connector or `claude mcp add`).               -->

## Checks

<!-- Quality checks: verifications that fire ON THEIR OWN on git operations —              -->
<!-- Telesma does not have to remember to run them. Points: commit (before git commit),       -->
<!-- phase (before a telesma/phase-* tag), release (before a vX.Y.Z tag), ci (in the pipeline: -->
<!-- python3 telesma/checks/telesma-checks.py --point ci --since origin/main).                  -->
<!-- A "block" finding stops the operation, a "warn" one goes to Claude and to              -->
<!-- telesma/state/CHECKS.jsonl. Modules: telesma/checks/<name>/ (described in CHECK.md).             -->
<!-- False alarm → an exception by fingerprint in telesma/state/CHECK_EXCEPTIONS.md — written by a  -->
<!-- human; a write to that file, to the modules or to this section always asks the human.  -->
<!-- Tiers (the setup wizard, `telesma.sh --setup`, keeps only the blocks of the chosen tier):  -->
<!--   basic     secrets, weakenings, tests, hygiene — no network, no tools, no map           -->
<!--   standard  + dependencies, dependency-audit, sast, lint-types, dead-entry               -->
<!--   security  + intent, red-team (applications with HTTP routes; attack-surface map)       -->
<!-- A check without a `### <name>` block below does not run and costs nothing.              -->

- **Enabled**: no
  <!-- yes = PreToolUse hook + modules copied to telesma/checks/ at startup -->
- **PR status**: yes
  <!-- With the repository integration (section Integrations → Repository: github): after every push -->
  <!-- to a task branch the hook posts the commit status "Telesma: checks (local)" — which checks     -->
  <!-- passed on the commits of that branch, when, with what result, the date of the last           -->
  <!-- dependency audit. A commit with no local evidence (made outside the hook) = red status.      -->
  <!-- It is an attestation from this machine, not verification: hence "local" in the name. The     -->
  <!-- wizard adds this name to "Required checks", so the judge will not merge a PR without evidence. -->
  <!-- no = nothing is posted.                                                                      -->

### secrets
- **When**: commit, ci
- **Scope**: changed
- **On failure**: block
  <!-- keys in known formats, .env/*.pem files; gitleaks when it is in PATH -->

### weakenings
- **When**: commit, phase, release, ci
- **Scope**: changed
- **On failure**: block
  <!-- marker "telesma: weakening <id> — <reason>"; an open weakening blocks the release;        -->
  <!-- MUTANT in code always blocks; TLS off / debug / csrf_exempt without a marker warns       -->

### dependencies
- **When**: commit, ci
- **Scope**: changed
- **On failure**: block
  <!-- new package in package.json / requirements / pyproject / deno.json vs the registry:      -->
  <!-- does not exist (name invented by the model), < 7 days old, typo of a popular one → block -->

### dependency-audit
- **When**: phase, release, ci
- **Scope**: all
- **On failure**: block
  <!-- vulnerabilities from the OSV database for lockfile versions; blocks critical/high with a fix -->
  <!-- in production dependencies — the rest warns                                                -->

### tests
- **When**: commit, ci
- **Scope**: changed
- **On failure**: block
  <!-- .only / fit / skip without a reason / deleted test file block; code without a test in the commit, -->
  <!-- a test changed together with the code it checks, a test without assertions — warn               -->

### hygiene
- **When**: commit, ci
- **Scope**: changed
- **On failure**: block
  <!-- build directories (dist/, node_modules/, __pycache__/…), file > 5 MB, manifest            -->
  <!-- changed without the lockfile → block; floating versions, binaries in code, IDE files → warn -->

### dead-entry
- **When**: phase, release, ci
- **Scope**: all
- **On failure**: warn
  <!-- a symbol (function / class / route / component) added since the last phase tag that       -->
  <!-- nothing outside its own test references — the mechanical guard of the "AC: entry" rule.   -->
  <!-- Tools: vulture / knip / ts-prune when present; without them grep over definitions. Warns only. -->

### sast
- **When**: commit, phase, ci
- **Scope**: changed
- **On failure**: block
  <!-- semgrep (p/owasp-top-ten, p/security-audit) on changed files; without semgrep, built-in  -->
  <!-- patterns. Injections (SQL, command, code), deserialization, path traversal block;         -->
  <!-- the rest warns. Test files are skipped.                                                   -->

### lint-types
- **When**: commit, phase, ci
- **Scope**: changed
- **On failure**: block
  <!-- Linter from the "Linter/formatter" field and typechecker from "Typecheck command" (## Tests) -->
  <!-- on changed files; errors block, warnings warn. Full run (tsc, mypy) at phase end.           -->
  <!-- Additionally a typographic quote used as a string delimiter — always.                       -->

### intent
- **When**: commit, phase, ci
- **Scope**: changed
- **On failure**: block
  <!-- Code vs the attack surface map telesma/state/SECURITY_MAP.md (telesma.sh writes a skeleton): -->
  <!-- a new route without a row in the map and a route without its role's guard block; a new    -->
  <!-- public route, new outbound host, secret from the environment, GRANT / SECURITY DEFINER,   -->
  <!-- long base64 blob — warn. Project without HTTP routes: silence.                            -->

### red-team
- **When**: phase, release, ci
- **Scope**: changed
- **On failure**: block
  <!-- A protected route changed in the phase must have a test with the marker                  -->
  <!-- "telesma: red-team <METHOD> <path> — no-session, foreign-role, foreign-owner, csrf"         -->
  <!-- (cases follow from the map). Missing marker blocks the phase tag; the first phase with a map only warns. -->

<!-- Check fields: When (commit, phase, release, ci), Scope (changed | all),                  -->
<!-- On failure (block | warn — config can soften a module, never harden it),                 -->
<!-- Time limit (optional; units s, sec, min — e.g. 30 s, 5 min). A check without an entry here does not run and costs nothing. -->

## Visual artifacts

<!-- Opt-in: screenshots per screen from telesma/spec/ux_ui/ + recordings per Step from telesma/spec/APP_FLOW.md. -->
<!-- Full procedure: section 0.5 of the instructions (templates/instructions/CORE.md).            -->
<!-- No APP_FLOW.md despite Recordings: yes → info in REPORT.md (not a blocker).                 -->

- **Screenshots**: no
  <!-- yes = after implementing a task tagged (screen: <id>) Telesma takes a screenshot       -->
  <!--       and saves it to telesma/artifacts/screens/<id>.png (Playwright/Detox)                  -->
  <!-- no  = skip — screenshots only when Playwright takes them natively (on failure)       -->

- **Recordings**: no
  <!-- yes = on end-of-phase e2e tasks tagged (flow: APP_FLOW.md#step-N) Telesma             -->
  <!--       generates a video to telesma/artifacts/flows/step-N-<slug>.webm (Playwright) or .mp4    -->
  <!--       (Detox). No flow_files or no APP_FLOW.md → info in REPORT.md                    -->
  <!-- no  = skip — no recordings regardless of tags                                        -->

- **Flow files**: telesma/spec/APP_FLOW.md
  <!-- List of files with user→system flows (one or many, comma-separated).                 -->
  <!-- Each file has "## Step N — Title" sections, each mapped to a separate recording.      -->
  <!-- The files are part of telesma/spec/ — frozen after clarification, changed through telesma/changes/.   -->

- **Artifacts dir**: telesma/artifacts/
  <!-- Directory for saved screenshots and videos. Structure: telesma/artifacts/screens/ + flows/.   -->
  <!-- Created with the first artifact. In .gitignore by default.                            -->

- **Commit artifacts**: no
  <!-- yes = telesma/artifacts/ goes into git (note: videos can be large, consider Git LFS)          -->
  <!-- no  = telesma/artifacts/ in .gitignore; REPORT.md keeps the list of file names for audit      -->

## Telesma loop

- **Max tries per task**: 3
  <!-- Context compression (auto-compact) happens automatically when the window fills up —  -->
  <!-- Claude cannot call /compact by itself. The protection is the state files updated     -->
  <!-- after every task (section 6 of the instructions).                                     -->
- **Report progress**: yes
- **Rotate state files**: yes
  <!-- REPORT.md, PROJECT_CONTEXT.md and PLAN.md go IN FULL into the startup prompt         -->
  <!-- and grow linearly with the project. Rotation moves older entries to telesma/state/*_ARCHIVE.md -->
  <!-- (write-only, never loaded into any prompt) at every start: deterministic,            -->
  <!-- zero tokens. What stays: 10 Task history entries, 10 log entries, 10 Change history   -->
  <!-- entries, the 3 latest runs in Test status, 3 dated Summary bullets,                   -->
  <!-- 3 "## " sections outside the template, 40 Key decisions rows                          -->
  <!-- and 30 Known problems rows.                                                           -->
  <!-- An entry is a WHOLE block (a multi-line description, a "### Phase …" subsection with  -->
  <!-- its prose), not a single line — rotation never cuts an entry in half.                 -->
  <!-- A decision or pitfall that is still binding: mark the row with 📌 — it does not rotate. -->
  <!-- In PLAN.md the INTROS of non-canonical "## " sections (request notes) rotate too;     -->
  <!-- the phases under them stay, and a section with even one `- [ ]` task is not touched.  -->
  <!-- "no" turns all of it off (including the phase archiving below).                       -->
- **Plan phases in file**: 5
  <!-- How many of the latest 100%-completed phases stay in telesma/state/PLAN.md in full.           -->
  <!-- Older ones go to telesma/state/PLAN_ARCHIVE.md, and the plan keeps a one-line stub with the   -->
  <!-- list of ids — (requires: X.Y) on an archived task still resolves.                     -->
  <!-- Only kicks in above 100 KB of plan (small project = zero churn in git).               -->
  <!-- "none" = do not touch PLAN.md; 0 = archive every completed phase.                     -->
- **Active phases**: all
  <!-- "all" = work through the whole telesma/state/PLAN.md -->
  <!-- List of phase ids, e.g. "1, 2, 3" or "1M, 2M, 3M" -->
  <!-- Multi-client (BFF): web branch → "1, 2, 3", mobile branch → "1M, 2M, 3M" -->
  <!-- Id = digit or digit+letter (case-sensitive, matched against the PLAN.md header) -->
  <!-- Telesma skips tasks from phases not on the list -->

## Working directories

<!-- Directories OUTSIDE the repository that Claude may access without asking.           -->
<!-- Telesma syncs this list with permissions.additionalDirectories in                     -->
<!-- .claude/settings.local.json (file access — without loading CLAUDE.md, hooks         -->
<!-- or skills from those directories, unlike the --add-dir flag).                       -->
<!-- The same list goes to the permission judge: file operations in these directories    -->
<!-- stop being treated as "outside the project".                                        -->
<!-- NO NEED to list here: the project directory or the Claude Code session scratchpad   -->
<!-- (/private/tmp/claude-<uid>) — the judge trusts them by default. The scratchpad is   -->
<!-- the agent's workspace, not user files; the backup → mutate → restore pattern works  -->
<!-- with no entry at all. List it here only if you want Claude Code to read files       -->
<!-- from there without asking as well.                                                  -->

- **Extra directories**:
  <!-- Absolute paths, `~` and `$VARIABLES` are expanded; relative ones resolve against the project. -->
  <!-- Roots like `/`, `~`, `/Users`, `/Volumes` are rejected — that is not                  -->
  <!-- configuration, it is switching protection off.                                         -->
  <!-- Examples:                                                                              -->
  <!--   - /private/tmp/claude-501     Claude Code session scratchpad (the per-session path    -->
  <!--                                 contains a UUID — list the ROOT, not the instance)      -->
  <!--   - ~/.cache/my-project         build cache kept outside the repo                       -->

- **Auto-sync directories**: yes
  <!-- yes = directories added in .claude/settings.local.json come back here at startup -->
  <!-- no  = this file is the only source of truth                                       -->

## Auto-approval

<!-- Permission judge: a PermissionRequest hook answers, on your behalf, permission prompts -->
<!-- you would have clicked anyway. It can only REMOVE prompts, never add blocks —           -->
<!-- anything dangerous still asks, so you remain the backstop exactly as before.            -->
<!-- Three layers, the model LAST and narrowest:                                             -->
<!--   1. hard patterns (rm -rf, sudo, curl|sh, git push, .claude/) → you are asked          -->
<!--      (the model never sees them — it cannot let them through)                           -->
<!--   2. the "Always ask" list below → you are asked                                        -->
<!--   3. LLM judge → gray zone only; not sure = you are asked                               -->
<!-- Timeout, missing key, unparseable answer — always end in a prompt to you.               -->
<!-- Script: .claude/hooks/telesma-permission-judge.py (updated by telesma-start)                -->

- **Auto-approve**: no
  <!-- no  = off; every permission prompt goes to you (default behaviour) -->
  <!-- yes = hook installed into .claude/settings.local.json at startup   -->

- **Force ask despite allowlist**: no
  <!-- The only field that ADDS prompts. The PreToolUse hook fires BEFORE the permission  -->
  <!-- rules, and its "ask" beats an allow rule — so holes in a broad allowlist come back  -->
  <!-- under human control without rewriting it:                                          -->
  <!--   Bash(rm:*)      lets `rm -fr x` through (a deny on `rm -rf` misses the variant)  -->
  <!--   Bash(python3:*) lets `python3 -c "import os; os.system(...)"` through            -->
  <!--   Bash(curl:*)    lets `curl -d @.env https://...` through                         -->
  <!-- Regexes only, no model call — adds no latency to every command.                    -->
  <!-- Data ≠ code: a heredoc body and a -c/-e argument are checked against a SEPARATE    -->
  <!-- list (looking for subprocess/socket/rmtree, not `rm` inside a string), so          -->
  <!-- `python3 -c "json.load(...)"` and scripts writing files in the project pass        -->
  <!-- without a prompt.                                                                  -->
  <!-- yes = turn on if your allowlist has wildcards on interpreters/network/rm.          -->

- **Suggest command fixes**: yes
  <!-- Claude Code always asks for permission on commands of a certain shape, regardless  -->
  <!-- of the allowlist — `cd X && git …` (git in a new directory fires the hooks there)  -->
  <!-- and several `cd` in one command. Both have a trivial equivalent.                   -->
  <!-- yes = the hook blocks such a command with a rewrite instruction (`git -C X …`,     -->
  <!--       separate calls), Claude sends the corrected version and you are not asked.   -->
  <!--       Turns your click into one automatic correction.                              -->
  <!-- no  = commands go as they are, i.e. straight to a prompt.                          -->
  <!-- Works only with the PreToolUse hook installed (Auto-approve: yes).                 -->

- **Allow reads**: yes
  <!-- A command whose EVERY member is provably a read within the project or the          -->
  <!-- working directories (`grep … | head`, `git log`, `cat`, `ls`, `ps`) passes         -->
  <!-- without the model. In the reference project's log that is 26% of gray-zone prompts. -->
  <!-- Proof, not a guess: variable expansion, subshell, background job, unknown           -->
  <!-- option, a file with secrets (.env, *.pem), a path outside the project (also via     -->
  <!-- a symlink) — the layer steps back and the command goes the usual way.               -->
  <!-- Hard patterns and the "Always ask" list take precedence over it.                    -->
  <!-- Works with `Judge: command` and `rules`, also when the model is unavailable.        -->

- **Judge**: rules
  <!-- rules   = the script WITHOUT a model: hard patterns, "Always ask" and the read layer. -->
  <!--           Provable reads do not ask, everything else asks you. Works everywhere,     -->
  <!--           zero configuration — the default of the setup wizard.                       -->
  <!-- command = the same script + a model over an OpenAI-compatible API (Ollama, vLLM,     -->
  <!--           LiteLLM, …) for the gray zone. Set Endpoint/Model (command) below and run   -->
  <!--           the evaluation set before trusting it.                                      -->
  <!-- none    = no LLM judge; only the PreToolUse hook remains (field above)               -->
  <!--           The only variant with a full deterministic layer BEFORE the model:        -->
  <!--           a hit in "Always ask" = a prompt to you, not a refusal.                   -->
  <!-- prompt  = Claude Code's built-in judge (field Model (prompt/agent)). Zero            -->
  <!--           configuration, but layer 2 can then only block, not ask.                 -->
  <!-- agent   = like prompt, but the judge has Read/Grep and can inspect the repo state.   -->
  <!--           Slower and more expensive; marked experimental in Claude Code.             -->

- **Risk level**: conservative
  <!-- conservative = ALLOW only for reversible operations contained in the project:     -->
  <!--                tests, linters, build, reads, git add/commit/diff/log.             -->
  <!--                Command substitutions $( ) and backticks → you are asked.          -->
  <!-- balanced     = additionally writing files in the project, installing dependencies -->
  <!--                from official registries, docker compose on localhost, migrations. -->
  <!-- A write disguised as a read (`echo x > file`, `sed -i`, `sort -o`, `find -delete`, rm -->
  <!-- and mv in the project) at conservative ASKS by rule, before the command reaches    -->
  <!-- the model — the model let 19 of these through out of 26 errors in the evaluation set. -->
  <!-- At both levels these ask by rule: git discarding work (checkout --, restore, stash,  -->
  <!-- commit --amend, rebase, tag), files with secrets, a symlink leaving the project,     -->
  <!-- a program under a project path posing as a system command, PATH= before a command.   -->

- **Gated tools**: Bash
  <!-- Tool name pattern (regex/pipe), e.g. "Bash" or "Bash|Edit|Write".                 -->
  <!-- With Mode: acceptEdits, Edit/Write do not ask anyway — Bash alone is usually enough. -->

- **Model (command)**: llama3.1:8b
- **Endpoint (command)**: http://localhost:11434/v1/chat/completions
- **API key (command)**: none
  <!-- Used only with `Judge: command`. Example: a local Ollama server (change the model to  -->
  <!-- one the server has). Before trusting ANY model as the judge, run it                   -->
  <!-- through the evaluation set — ALLOW is the judge's only decision with an effect:     -->
  <!--   python3 <telesma>/tools/telesma-judge-eval.py --endpoint … --model …                 -->
  <!-- Required result: FALSE ALLOWS: 0. Small models fail this gate more easily.         -->
  <!-- This file goes into git, so do NOT paste a key here. Five ways to write it:        -->
  <!--   env:NAME         environment variable; needs `export NAME=sk-...`                -->
  <!--   file:~/.config/telesma/judge.key    first line of a file outside the repo — no      -->
  <!--                    export, works even when you run `claude` without telesma.sh -->
  <!--   cmd:security find-generic-password -s telesma-judge -w    the command's stdout;     -->
  <!--                    macOS Keychain / pass / vault — the key is never stored in clear -->
  <!--   sk-...           literal; the script warns at every start, use only when          -->
  <!--                    config.md is NOT under version control                           -->
  <!--   none             no Authorization header — for a local server                     -->
  <!-- Anything that cannot be resolved = the judge stays silent, the prompt goes to you.  -->

- **Fallback endpoint (command)**: none
- **Fallback model (command)**:
- **Fallback API key (command)**: none
- **Fallback mode**: shadow
  <!-- A second model, asked when the primary DOES NOT ANSWER (network, timeout, 401, 5xx). -->
  <!-- Typically local: Ollama `http://localhost:11434/v1/chat/completions`, LM Studio      -->
  <!-- `http://localhost:1234/v1/chat/completions` — both speak an OpenAI-compatible API.   -->
  <!-- shadow = the fallback decides nothing. Its verdict goes to the log (in the background, -->
  <!--          no delay), also when the primary works — so the two models can be           -->
  <!--          compared on your own commands before you give it the right to allow.        -->
  <!--          Result: `python3 tools/telesma-judge-eval.py --labels <project>`             -->
  <!-- allow  = when the primary does not answer, the fallback's ALLOW removes the prompt.  -->
  <!-- BEFORE you set `allow`, run the model through the evaluation set — a small model     -->
  <!-- lets dangerous things through more easily, and ALLOW is the judge's only decision    -->
  <!-- with an effect:                                                                      -->
  <!--   python3 <telesma>/tools/telesma-judge-eval.py --endpoint … --model …                   -->
  <!-- Required result: FALSE ALLOWS: 0.                                                    -->
  <!-- After the primary fails, the hook does not retry it for 2 minutes, so a dead         -->
  <!-- server does not add a timeout to every command.                                      -->

- **Model (prompt/agent)**: claude-haiku-5-5

- **Decision log**: yes
  <!-- yes = every decision (layer, reason, command) → telesma/state/PERMISSIONS.jsonl.          -->
  <!-- The only way to check whether the judge lets too much through. Keep "yes"         -->
  <!-- at least for the first few sessions.                                              -->
  <!-- The log contains FULL commands and stays on this machine — telemetry sends only   -->
  <!-- counters from it. New projects have it in "Ignore on commit" (section Git);       -->
  <!-- in a project created earlier add `telesma/state/PERMISSIONS.jsonl` there yourself.        -->

- **Log human decision**: yes
  <!-- A PostToolUse hook appends to the log that a command you were asked about actually -->
  <!-- ran — i.e. that you approved it. It judges nothing and affects nothing.            -->
  <!-- These are the only labels a model can be evaluated on against your commands, or    -->
  <!-- one day fine-tuned on. Requires `Decision log: yes`.                               -->

- **Always ask**:
  <!-- Extra patterns (regex, case-insensitive) checked BEFORE the model.               -->
  <!-- The model cannot override them. Examples: `docker\s+system\s+prune`, `alembic\s+downgrade` -->

## Telemetry

<!-- Optional: events about the QUALITY OF TELESMA'S WORK sent to a telemetry server YOU run -->
<!-- (the Telesma hub, not published yet; payload in docs/TELEMETRY.md). Off by default — nothing leaves this -->
<!-- machine. Sending runs in the background at startup, zero tokens, never blocks work.   -->
<!-- NOT sent: telesma/spec/, code, telesma/changes/ or commands from PERMISSIONS.jsonl (counters only).   -->
<!-- Preview of what would be sent: python3 <telesma>/tools/telesma-telemetry.py <project> --json -->

- **Send**: no
  <!-- yes = send to the Endpoint below -->

- **Endpoint**: none
  <!-- Address of your telemetry server, e.g. https://telemetry.example.com -->

- **API key**: env:TELESMA_HUB_TOKEN
  <!-- env:NAME · file:<path outside the repo> · cmd:<command> — never literal, this file goes into git -->

- **Project label**:
  <!-- Readable project name on the server; empty = name of the project directory -->

## Permissions

<!-- Telesma syncs this section with .claude/settings.local.json at every start:          -->
<!-- 1. At startup: telesma/config.md ∪ settings.local.json → written to both files       -->
<!-- 2. During the session: the Claude CLI itself appends "allow always" to settings.local.json -->
<!-- 3. At the next start: new entries are merged back here                             -->

- **Mode**: acceptEdits
  <!-- default            = asks about every tool                          -->
  <!-- acceptEdits        = auto-accepts Edit/Write, asks about Bash        -->
  <!-- bypassPermissions  = no prompts at all (risky, e.g. rm -rf)          -->
  <!-- plan               = planning mode without modifying files          -->

- **Auto-sync new permissions**: yes
  <!-- yes = permissions granted during a session ("allow always") are added to this list -->
  <!-- at the next start, so you are not asked again                                      -->
  <!-- no  = only this file is the source of truth, new entries from the session are ignored -->

- **Generalize permissions**: yes
  <!-- yes = exact commands approved during a session are promoted to Bash(family:*) patterns -->
  <!-- for a curated list of safe families (tests, linters, git add/commit, docker          -->
  <!-- compose, ...). Example: approving "npm test -- --coverage" gives Bash(npm test:*).   -->
  <!-- Destructive/network ones (rm, sudo, curl, git push) never — those always ask.        -->
  <!-- no  = entries stay exactly as approved                                              -->

- **Allowed commands**:
  - Bash(npm test:*)
  - Bash(npm run:*)
  - Bash(npm install:*)
  - Bash(npx:*)
  - Bash(pytest:*)
  - Bash(mkdir:*)
  - Bash(ls:*)
  - Bash(git add:*)
  - Bash(git commit:*)
  - Bash(git status)
  - Bash(git diff:*)
  - Bash(git log:*)
  - Bash(git tag:*)
  - Bash(git describe:*)
  - WebFetch(domain:claude.ai)

- **Denied commands**:
  - Bash(rm -rf:*)
  - Bash(sudo:*)
  - Bash(git push --force:*)
  - Bash(git reset --hard:*)
