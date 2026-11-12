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
- To the shared hub the sender's **name is not sent** (only a salted hash of the e-mail, see
  "Identity"), and an empty `Project label` is the **project hash**, not the directory name —
  directory names often name a client.
- The scope chosen at the opt-in (`metrics`) holds for every destination, a server of your own
  included.

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

`telesma/config.md` is committed, so these four lines reach everyone who clones the repository —
and one of them may name a command (`cmd:`) or a variable of yours (`env:`). They therefore act
only on a machine where a person has **seen and confirmed the `## Telemetry` section**: `telesma.sh`
asks in the terminal and records the confirmation per project in `~/.config/telesma/trust/`
(outside every repository; a hash of the section's `- ` lines). Without that record the collector
makes **no request, reads no key and runs no command**; it says so with exit code 1 and the
launcher does not report it as a failed send. Editing the section afterwards withdraws the
confirmation until the next start in a terminal. If the file holds two `## Telemetry` sections
(or a field inside a comment) that read differently from the confirmed lines, nothing is sent.

The endpoint must be `https://`; `http://` is accepted only for this machine (`localhost`,
`127.0.0.1`, `::1`). The same holds for the shared hub's address and for the `endpoint:` line of
the opt-in file — a token never travels in clear text. The wizard's `own server` answer sets
`Send` and `Endpoint`.

| Field | Default | Meaning |
|-------|---------|---------|
| `Send` | `no` | `yes` = this project may be reported |
| `Endpoint` | `none` | `shared` = the shared hub; `https://…` = your server (needs the confirmation above); `none` or empty = sending stays silent |
| `API key` | `env:TELESMA_HUB_TOKEN` | own server only: `env:NAME`, `file:<path outside the repo>` or `cmd:<command>` (stdout) — read, and for `cmd:` run, only after the confirmation above. Never write the key itself here — `config.md` is committed. `auto` (the shared hub's token) is not accepted for another server |
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
a file path in the history only "is this a test file" is kept. (An *entry* in a state file may of
course name a file or quote a commit title — see "What leaves, exactly".)

**From Claude Code transcripts on this machine:** counters only — Telesma mode, model, tokens, number of
tool calls by tool *name* and how many errored, compactions, wall-clock minutes, size of the startup
prompt. Never arguments, never message text. The model matters most: without it a framework change
cannot be told apart from a model change.

**From the permission judge log:** per-day counters of decisions by layer — never the commands.

**A daily state snapshot:** sizes of the state files and of the instruction templates, the result of
the state-file diagnosis, which integrations are on, and a few config values (judge variant, smoke suite
on/off, max tries). A config value, a `(tech: …)` tag, the status cell of a task row, a model or tool
name and the fields of the judge log go out only when they are **one short word**; anything longer is
sent as `other` (tags: dropped).

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

## What leaves, exactly

**Never sent** (in any scope):

- the files in `telesma/spec/` and in `telesma/changes/` (written by a human about the product) —
  they are not opened at all, and not even the *name* of a change file leaves: a `change` event
  carries a hash of it;
- source files and any other file content outside the state files listed above (not opened);
- commands from `telesma/state/PERMISSIONS.jsonl` — only counters;
- commit subjects and PR titles from git, transcript text, tool arguments;
- your e-mail address, the origin URL, your home directory path.

**Sent with scope `full`: the text of the entries** — problem-log entries, `BUGFIXES.md`,
`REVIEWS.md` and `DECISIONS.md` entries, `## Change history` blocks, the pitfalls table, test-run
paragraphs, the text of `BLOCKED.md`, the title cell of a task-history row, and from the manual
scenario files the heading and up to three lines of the tester's note under each broken or partial
result. Most of it Telesma wrote about its own work; some of it is a person's words (a tester's
note, an owner's comment quoted in a review, a decision). **This is prose, and prose can quote
anything**: a relative file path and line number, a line of code, a commit title, a host name, a
sentence the owner said. Telemetry does not open your code or your spec, but it cannot know what
an entry repeats from them. If that matters for a project, choose scope `metrics`.

Before any text leaves, a scrub replaces what is recognisably sensitive:

| Shape | Becomes |
|-------|---------|
| private key blocks; `sk-…`, `pk-…`, `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_…`, `github_pat_…`, `glpat-…`, `xox?-…`; AWS key ids (`AKIA…`, `ASIA…`); Google keys (`AIza…`); JWTs; `Bearer …`; `Authorization: …`; `password=…`, `secret:`, `token=`, `api_key=` | `[removed]` |
| a URL with credentials, `scheme://user:password@host…` | `scheme://[removed]` (host included) |
| e-mail addresses | `[e-mail]` |
| your home directory | `~` |
| the directories of an absolute path outside home (`/srv/…`, `/var/…`, `/Users/<other>/…`, `C:\…`) | `[path]/` + the file name |

The scrub recognises shapes; it is not a guarantee that no secret in an unusual form gets through,
and it leaves host names, relative paths and ordinary words alone.

**Sent with scope `metrics`: no text at all** — no `title`, no `text`, no `key`; numbers, dates,
types, task ids, and the one-word values described above. The test suite pins this: with canaries
in every source, every string in a `metrics` event is a single word.

The test suite (`tools/test-telemetry.py`) pins these statements with canary values in the spec,
the code, a change file and its name, a judge-log command, a commit subject, a transcript, config
values, and secret-shaped strings inside the problem log, `REVIEWS.md`, `BLOCKED.md` and a scenario
note.

## Identity and the payload (schema 2)

```json
{"schema": 2, "sender": {"id": "<hash>", "name": "<git user.name>"}, "events": [ … ]}
```

sent as `POST <Endpoint>/ingest` with `Authorization: Bearer <API key>`, at most a few hundred events
per request. Every event has the same shape:

| Field | Meaning |
|-------|---------|
| `id` | 32 hex chars, hash of project + type + `key` (see below) — the server upserts by it |
| `key` | the entry opener the id is derived from (first line of the entry, scrubbed); for a `change` event `change:<hash of the file name>`; absent with scope `metrics` |
| `schema` | `2` |
| `type` | one of the event types listed above |
| `date` | `YYYY-MM-DD` or `null` |
| `project`, `label` | project id (hash) and readable label |
| `format_version` | Telesma state-format version at the time of the event, or `null` |
| `task`, `phase` | task id (`3.2`) and its phase, or `null` |
| `tech` | technology tags of the task, a list of strings |
| `title`, `text` | the entry's first line and body, after the scrub; empty with scope `metrics` |
| `metrics` | a small object of numbers and flags specific to the type |

The server answers `2xx` with a JSON object; an optional `rejected_ids` list of strings names events
it did not store (an unknown `type`, for example). Any other status or a network error marks nothing as
sent. The reply is treated as data: at most 1 MB is read, anything that is not a list of strings is
ignored, and what is kept of an error (the status line) is stored and shown without control characters.

- **Project id** = a hash of the `origin` remote reduced to `host[:port]/path` (no scheme, no
  credentials, no `.git`), so two people on the same repository produce the same ids whether they
  cloned over https, `ssh://` or `git@host:path`. It is a plain hash on purpose — it has to be the
  same on every machine — which means someone who holds the data and guesses the repository URL can
  confirm the guess. A project **without a remote** shares nothing between machines: its id is the
  directory name hashed under a per-machine salt. `Project label` adds a readable name.
- **Sender** = an HMAC of `git config user.email` (as seen from the project) under a random
  per-machine salt, `~/.config/telesma/salt` (mode 0600, created on first use) — not a plain hash,
  which could be confirmed for any known address. The id is therefore the same for all your projects
  on one machine and different on another machine; the address itself never leaves. `user.name` goes
  only to your own server, never to the shared hub. Without git it falls back to OS user + hostname
  (salted the same way). It is attribution, not authentication — only the key is verified.
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
- A server named in `config.md` gets nothing — no request, no key read, no `cmd:` run — until the
  `## Telemetry` section was confirmed on this machine, and nothing over clear-text http.
- No file of `telesma/spec/`, `telesma/changes/` or your source is read. Entry text (scope `full`)
  is scrubbed but is prose that may quote from them; scope `metrics` sends no text.
- The collector is read-only towards the project, `.git` included.
- `--json` shows byte for byte what would be sent (before the `metrics` cut and name removal for
  the shared hub).
- Turning it off for a project is one word: `Send: no`. Withdrawing and deleting everything:
  `telesma.sh --telemetry-forget`.
