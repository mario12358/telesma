# Quality telemetry (`## Telemetry`)

Telesma leaves a lot of knowledge in a project about **how its work went** — tries per task, the problem
log, bugfixes, blockers, pitfalls, manual test results — and nobody reads it with an eye on the
framework itself. Telemetry turns those files into events that can be compared across framework
versions, models and projects, so that a change to Telesma can be judged by data rather than by
impression.

**It is optional and off by default.** With `Send: no` (the template default) nothing leaves your
machine. There are two destinations:

- **The shared Telesma hub**, run by the project's author — events from many real projects are what
  framework improvements are made from. Sending to it needs **your explicit opt-in on this machine**;
  a setting in the repository cannot give it for you.
- **A server you run yourself** — the payload is documented below, so a receiver of your own is a
  few dozen lines: accept the POST, store the events by `id`.

## The shared Telesma hub

The setup wizard asks once (every profile, default **no**) and lists exactly what is sent:

```
Telemetry
  Telesma can send events about the quality of ITS OWN work to the shared Telesma hub
  (run by the project's author) so the framework can be improved from real projects.
  Sent: task outcomes and timings, test results, problem/pitfall/decision entries from
  telesma/state (titles and text, secrets removed), check findings, permission counters,
  framework version, technology tags, a hash of the project's origin URL and of your
  git e-mail. Never sent: your spec, code, telesma/changes/, commands, prompts.
  Privacy and deletion: https://<hub>/privacy — delete any time: telesma.sh --telemetry-forget
Send telemetry? [y/N/own server]
```

A `y` asks one more thing — **scope**: `full` (titles and text of Telesma's own entries, after the
secret scrub) or `metrics` (numbers, types and dates only). Then the client registers a token of
this machine's own with the hub (`POST /register`), writes it to `~/.config/telesma/hub` (mode
0600, outside every repository) and sets `Send: yes`, `Endpoint: shared` in `telesma/config.md`.

**The opt-in is per person and machine, not per repository.** `telesma/config.md` is committed: if
one person's `Send: yes` were enough, everyone who clones the repo would start sending without being
asked. So:

- `Send: yes` + `Endpoint: shared` in the repo means only "this project may be reported". Without
  `~/.config/telesma/hub` the client makes **no request at all**.
- Someone who clones such a project is asked once, at the first start on their machine (without a
  terminal: not asked, nothing sent, one line in the startup output). A "no" is remembered.
- `Send: no` switches the project off for everyone; `Scope: metrics` narrows it to numbers for
  everyone. A project can narrow what a person agreed to, never widen it.
- To the shared hub the sender's **name is not sent** (only the e-mail hash), and an empty
  `Project label` is the **project hash**, not the directory name — directory names often name a client.

### Deleting your data

```bash
telesma.sh --telemetry-forget
```

calls `DELETE /mine` on the hub, which immediately deletes every event sent with this machine's token
and the token itself; then it removes `~/.config/telesma/hub` and the local record of what was sent.
Turning telemetry off in one project (`--setup` → Telemetry → no) does not withdraw the opt-in for
your other projects — `--telemetry-forget` does. The hub deletes events older than its retention
period (see `/privacy`) on its own.

## Your own server

```markdown
## Telemetry

- **Send**: yes
- **Endpoint**: https://telemetry.example.com
- **API key**: env:TELESMA_HUB_TOKEN
- **Project label**: my-project
```

Here the key on each machine is that machine's opt-in: without it nothing is sent. The wizard's
`own server` answer sets `Send` and `Endpoint`.

| Field | Default | Meaning |
|-------|---------|---------|
| `Send` | `no` | `yes` = this project may be reported |
| `Endpoint` | `none` | `shared` = the shared hub; `https://…` = your server; `none` or empty = sending stays silent |
| `API key` | `env:TELESMA_HUB_TOKEN` | own server only: `env:NAME`, `file:<path outside the repo>`, `cmd:<command>` (stdout) or `auto` (the token from `~/.config/telesma/hub`). Never write the key itself here — `config.md` is committed |
| `Scope` | `full` | shared hub only: `metrics` = no titles, text or entry openers, for everyone on this project |
| `Project label` | empty | a readable project name on the server; empty = the directory name (own server) or the project hash (shared hub) |

At every start `telesma.sh` runs the collector **in the background** and never waits for it: Telesma's
start must not depend on someone else's server. Collection is pure file reads, zero tokens, a fraction
of a second on a warm cache. What was already sent is remembered in `~/.cache/telesma/telemetry-<id>.json`
(outside the repository — a state file in the project would dirty the tree at every start). A failed send
marks nothing as sent, so the next start retries on its own; the error is shown as one yellow line at the
next start and disappears after the next success. There is no queue file.

## Preview before you enable it

```bash
python3 <telesma>/tools/telesma-telemetry.py <project>              # summary: how many events of each type
python3 <telesma>/tools/telesma-telemetry.py <project> --json       # exactly what would be sent, as JSON lines
python3 <telesma>/tools/telesma-telemetry.py <project> --send       # send now, per ## Telemetry
python3 <telesma>/tools/telesma-telemetry.py <project> --last-error # error of the last send (empty = it got through)
```

`--json` works with `Send: no` — read it before you decide.

## What is collected

**From Telesma's state files** (`telesma/state/`): the problem log, the task history (tries per task), test-suite
runs from `## Test status` (passed/failed/skipped, the verdict, whether it was red along the way),
`BUGFIXES.md`, `REVIEWS.md`, `DECISIONS.md`, `## Change history`, the known-pitfalls table, manual test
scenario results, and every blocker from the git history of `BLOCKED.md` (Telesma deletes the file once a
blocker is resolved, so the directory alone shows at most the last one).

**From git:** only the task id is taken from a commit subject; from it come the date, number of files,
lines changed, number of commits, later fix commits and minutes since the previous commit. With the
GitHub integration also PR counters from squash commits on main. The subject text itself stays home. From
a file path only "is this a test file" is kept.

**From Claude Code transcripts on this machine:** counters only — Telesma mode, model, tokens, number of
tool calls by tool *name* and how many errored, compactions, wall-clock minutes, size of the startup
prompt. Never arguments, never message text. The model matters most: without it a framework change
cannot be told apart from a model change.

**From the permission judge log:** per-day counters of decisions by layer — never the commands.

**A daily state snapshot:** sizes of the state files and of the instruction templates, the result of
the state-file diagnosis, which integrations are on, and a few config values (judge variant, smoke suite
on/off, max tries).

Event types: `task`, `test_run`, `problem`, `bugfix`, `review`, `decision`, `change`, `pitfall`,
`scenario`, `blocker`, `permissions`, `session`, `pr`, `state`.

Three fields Telesma writes into its entries make the data readable as signal:

- **`Kind`** (`bug | correction | feature | question | operations`) on change and decision entries.
  `telesma/changes/` is the normal channel through which a project *grows*, so the number of changes says
  nothing about quality; what does is how many of them exist because something already built did not
  work. A change file may state `kind:` in its frontmatter.
- **`Detected by`** (`test | scenario | review | telesma | owner | production | guard`) on bugs: the same
  number of bugs means something else when tests catch them than when a customer does.
- **`Bug source`** (`task X.Y | unknown`) on bugs: a bug is charged to the framework version under which
  it was *introduced*, not the one under which it was reported — otherwise every new version would look
  worse than its predecessor for months.

Each event carries the framework version **at the time of the event** (read from the git history of
`telesma/state/.telesma-version`; `null` when older than that file), so "before vs after a framework change" stays
measurable even when a year of history is sent for the first time.

## What never leaves the machine

- `telesma/spec/` and `telesma/changes/` — written by a human about the product.
- Source code and file contents.
- Commands from `telesma/state/PERMISSIONS.jsonl` — only counters.
- Commit subjects, PR titles, transcript text, tool arguments.
- Your e-mail address.

What does go out is text **Telesma wrote about its own work** (problem-log entries, bugfix and decision
descriptions, pitfalls), after a scrub that removes secret-shaped strings (API keys, bearer tokens,
`password=…`, private keys) and replaces your home directory with `~`. The test suite pins these
guarantees with canary values that must never appear in the output.

## Identity and the payload (schema 2)

```json
{"schema": 2, "sender": {"id": "<hash>", "name": "<git user.name>"}, "events": [ … ]}
```

sent as `POST <Endpoint>/ingest` with `Authorization: Bearer <API key>`, at most a few hundred events
per request. Every event has the same shape:

| Field | Meaning |
|-------|---------|
| `id` | 32 hex chars, hash of project + type + `key` (see below) — the server upserts by it |
| `key` | the entry opener the id is derived from (first line of the entry, scrubbed) |
| `schema` | `2` |
| `type` | one of the event types listed above |
| `date` | `YYYY-MM-DD` or `null` |
| `project`, `label` | project id (hash) and readable label |
| `format_version` | Telesma state-format version at the time of the event, or `null` |
| `task`, `phase` | task id (`3.2`) and its phase, or `null` |
| `tech` | technology tags of the task, a list of strings |
| `title`, `text` | what Telesma wrote about its own work, after the secret scrub |
| `metrics` | a small object of numbers and flags specific to the type |

The server answers `2xx` with a JSON object; an optional `rejected_ids` list names events it did
not store (an unknown `type`, for example). Any other status or a network error marks nothing as sent.

- **Project id** = a hash of the `origin` URL, so two people on the same repository produce the same
  ids. `Project label` adds a readable name.
- **Sender** = a hash of `git config user.email` as seen from the project (the same on every machine you
  use; the address itself never leaves) plus `user.name` — the name only to your own server, never
  to the shared hub. Without git it falls back to OS user + hostname. It is attribution, not
  authentication — only the key is verified.
- **Event id** is a natural key (project + type + entry opener), not a content hash: when rotation moves
  an entry to the archive, or Claude appends a lesson to it, it is still the same event and the server
  overwrites it. Event ids deliberately do not include the sender, so two people reading the same
  `REPORT.md` produce one event, not two.
- A server older than the client may not know a new event type: it returns `rejected_ids`, and the
  client resends exactly those at later starts until the server catches up.

## Privacy guarantees, in short

- Off by default; no built-in key.
- The shared hub gets nothing without an opt-in file on this machine, which only the wizard (or
  the one-time question at startup) writes — a committed `Send: yes` cannot switch anyone on.
- Your own server gets nothing without a key on this machine.
- The collector is read-only towards the project, `.git` included.
- `--json` shows byte for byte what would be sent (before the `metrics` cut and name removal for
  the shared hub).
- Turning it off for a project is one word: `Send: no`. Withdrawing and deleting everything:
  `telesma.sh --telemetry-forget`.
