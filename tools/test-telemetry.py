#!/usr/bin/env python3
"""Test of telesma-telemetry.py — builds a project from scratch and checks four invariants.

    python3 tools/test-telemetry.py

INVARIANT 1 — nothing confidential leaves. Canaries sit in `telesma/spec/`, code, `telesma/changes/` and in a
command from PERMISSIONS.jsonl; none of them may appear in the events. A secret written into
the problem log (Telesma's text, so it does go out) must be cut out.

INVARIANT 2 — the id survives rotation. An entry moved from REPORT.md to the archive is still
the same event: the set of ids before and after must be identical.

INVARIANT 3 — sending is idempotent and loses nothing. A second run sends nothing; with a dead
server nothing is marked as sent, and the next run delivers everything.

INVARIANT 4 — the collector only reads: the project after a run is byte-for-byte the same
(`.git` included — the second source reads commit history).

INVARIANT 5 — the shared hub needs a per-machine opt-in. `Send: yes` + `Endpoint: shared` without
~/.config/telesma/hub makes zero HTTP requests; with it, the batch carries no sender name and no
directory name; `Scope: metrics` carries no title, text or entry opener — and no free text
anywhere else in an event; `--forget` deletes on the hub and removes the opt-in.

INVARIANT 6 — a committed config cannot act on a machine whose user never saw it. `Send: yes` +
a custom endpoint + a literal, `env:` or `cmd:` key without the trust record of this machine
(~/.config/telesma/trust/, written by telesma.sh) makes zero requests and runs no command; an
edit after the confirmation withdraws it; `auto` is never a key for a server other than the
shared hub; endpoints are https (http only to this machine).

INVARIANT 7 — what a server answers is data: a status line with escape sequences, a malformed
`rejected_ids`, a non-numeric counter neither reach the terminal nor break the bookkeeping.

The scrub is pinned with secret-shaped canaries in every text source (problem log, REVIEWS.md,
BLOCKED.md, a tester's scenario note): a URL with credentials, an AWS key id, a JWT, GitHub and
Google tokens, an Authorization header, an e-mail address, an absolute path outside home. The
name of a change file and free text in config values, plan tags, the status cell and the judge
log never leave in any scope.

Plus the sources beyond state files: git (the commit subject and the session transcript carry
canaries too — only numbers come out of them), the `Kind` field and the framework version.
"""
import hashlib
import http.server
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import tokenize
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "telesma-telemetry.py"
CANARIES = ("CANARY_SPEC", "CANARY_CODE", "CANARY_CHANGES", "CANARY_COMMAND",
            "CANARY_COMMIT", "CANARY_TRANSCRIPT",
            # a change file's name; free text in config values, a plan tag, the status cell,
            # the judge log — none of them is an entry Telesma wrote about its work
            "CANARY_CHANGENAME", "CANARY_CONFIG", "canary_tag", "CANARY_STATUS", "CANARY_PERM")
SECRET = "sk-abcdefghijklmnopqrstuvwxyz123456"
# Secret-shaped strings inside entry text (which does go out with scope `full`): each must be
# cut by the scrub, wherever the entry lives.
SECRET_CANARIES = (
    "Q0FOQVJZX0JBU0lDOnB3ZA",                                   # Authorization: Basic … (problem log)
    "reviewer.canary@example.org", "CANARY_DBPASS", "db.canary.internal",   # REVIEWS.md
    "/srv/clients/acme-canary",                                 # REVIEWS.md: absolute path outside home
    "eyJzdWIiOiJDQU5BUllfSldUIn0", "AKIACANARYAWSKEY0001",      # BLOCKED.md: JWT, AWS key id
    "github_pat_11CANARYG0abcdefghijklmnop", "AIzaSyCANARY7890abcdefghijklmnopqrstuv",  # scenario note
    "ghs_CANARYabcdefghijklmnopqrstuvwxyz01",
)

LOG_ENTRY = f"""- [2026-02-02] Task 7.2: **mock returned 200, production 401** — first line.
  Second line: the token in the test was {SECRET}, it had to be moved out.
  The request carried `Authorization: Basic Q0FOQVJZX0JBU0lDOnB3ZA==` and ghs_CANARYabcdefghijklmnopqrstuvwxyz01.
  **General lesson: a test on a mock does not prove authorization.**
"""

REPORT = """# telesma/state/REPORT.md

## Test status

| Metric | Value | Date |
|---|---|---|
| backend | **99 passed** | 2026-02-02 |

**Regression after Phase 7 (2026-02-02) — GREEN, but only on the second attempt:** backend
**41 passed / 2 skipped / 0 failed** (08:10); first attempt **39 passed / 2 failed** (949 s).

A paragraph without a date continues the same run.

**Previous run 2026-02-01 (after task 7.1):** backend **30 passed / 0 failed**.

**Regression after Phase 8 (2026-02-03) — GREEN (locally, branch of task 8.4):** api+shared 276/0,
web 185/1, e2e 45/45. Test 3.11 fixed (3/8 failures on repeats) — expect.poll, 45/45
over 5 repeats.

## Task history

### Phase 7 (Something) — COMPLETE (2026-02-01)

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|
| 7.1 first | ✅ | 3/3 | 1 | abc1234 | 2026-02-01 |
| 7.2 endpoint `accept|reject` | ✅ | 5/5 | 3 | def5678 | 2026-02-02 |
| 7.3 test on production | CANARY_STATUS_LONGWORD waiting for the owner | 0/1 | 1 | — | 2026-02-03 |

## Change history

### 2026-02-03 2026-02-03-CANARY_CHANGENAME-limit.md
- **Kind**: bug
- **Bug source**: task 7.1
- **Detected by**: production

Modified 7.3, created Phase 7.Z1 (rework 7.1).

## Problem log

<!-- format: [date] Task X.Y: description -->

%s
- [2026-02-01] Task 7.1: one-line entry.
- [2026-02-02] [check] PR #8 — Specky contract check red: requirement hash out of date.
"""

FILES = {
    "telesma/state/.telesma-version": "7\n",
    "telesma/config.md": "## Project\n\n- **Adopted**: yes\n\n## Tests\n\n- **Smoke suite**: none\n\n## Integrations\n\n"
                       "- **Repository**: github\n- **Merge**: agent\n- **Tracker**: none\n\n"
                       "## Telesma loop\n\n- **Max tries per task**: CANARY_CONFIG tries\n\n"
                       "## Auto-approval\n\n- **Auto-approve**: yes\n"
                       "- **Judge**: CANARY_CONFIG my own judge\n\n"
                       "## Telemetry\n\n"
                       "- **Send**: yes\n- **Endpoint**: ENDPOINT\n"
                       "- **API key**: env:TELESMA_TEST_HUB_KEY\n- **Project label**:\n",
    "telesma/state/PLAN.md": "### Phase 7: Something\n\n- [x] Task 7.1: first (tech: python) (pr: #7)\n"
                     "- [x] Task 7.2: endpoint (requires: 7.1) (tech: python, sql)\n"
                     "- [ ] ⛔ Task 7.3: test on production (tech: python, canary_tag with words) (pr: #8)\n",
    "telesma/state/REPORT.md": REPORT % LOG_ENTRY,
    "telesma/state/BUGFIXES.md": "# BUGFIXES\n\n<!--\n## YYYY-MM-DD HH:MM — [template]\n-->\n\n"
                         "## 2026-02-05 10:00 — 500 on an empty cart\n**Symptom**: 500.\n"
                         "**Cause**: missing guard.\n**Fix**: guard.\n"
                         "**Test**: no test — verified manually\n**Commit**: aaa1111 fix\n",
    "telesma/state/DECISIONS.md": "# DECISIONS\n\n## 2026-02-06 — limit counted per organization\n"
                          "**Kind**: correction\n"
                          "**Question/context**: how to count.\n**Outcome**: per organization.\n\n"
                          "## 2026-02-07 — entry from before the Kind field\n"
                          "**Question/context**: x.\n**Outcome**: y.\n",
    "telesma/state/PROJECT_CONTEXT.md": "## Known problems and solutions\n\n| Problem | Solution |\n"
                                "|---|---|\n| 📌 session expires after commit | read before committing |\n"
                                "| `pytest` loses a fixture in `conftest.py` | scope=session |\n",
    "telesma/state/PERMISSIONS.jsonl": json.dumps({"tool": "Bash", "input": "echo CANARY_COMMAND",
                                           "mode": "command", "layer": 3, "decision": "allow",
                                           "ts": "2026-02-02T10:00:00"}) + "\n"
                                       + json.dumps({"tool": "Bash", "input": "x", "layer": 3,
                                                     "mode": "CANARY_PERM mode", "decision": "ask",
                                                     "ts": "2026-02-03T10:00:00"}) + "\n",
    "telesma/state/REVIEWS.md": "# REVIEWS\n\n## 2026-02-09 11:00 — Review of task 7.2\n"
                        "**Files**: src/app.py\n**Findings**: 🔴 1 | 🟡 0 | 🟢 0\n\n### Findings\n"
                        "- 🔴 src/app.py:42 — reported by reviewer.canary@example.org; reproduced "
                        "against postgres://admin:CANARY_DBPASS@db.canary.internal:5432/app, log in "
                        "`/srv/clients/acme-canary/logs/app.log` → fixed\n",
    "docs/test-scenarios/v0.1.0.md": "# v0.1.0\n\n- **Date:** 2026-02-07\n\n### 1.1 Login\n\n"
                                     "- [x] **Result 1.1**\n\n### 1.2 Export\n\n"
                                     "- [-] **Result 1.2**\n  Empty file instead of CSV; the tester's "
                                     "github_pat_11CANARYG0abcdefghijklmnop and "
                                     "AIzaSyCANARY7890abcdefghijklmnopqrstuv were in the request.\n\n"
                                     "### 1.3 Limit\n\n- [ ] **Result 1.3**\n",
    "telesma/spec/requirements.md": "CANARY_SPEC secret business model\n",
    "src/app.py": "# CANARY_CODE\n",
    "telesma/changes/processed/2026-02-03-CANARY_CHANGENAME-limit.md": "CANARY_CHANGES client X pays too little\n",
}


class Hub(http.server.BaseHTTPRequestHandler):
    received, alive, header, sender, requests = [], True, "", None, 0

    def do_POST(self):
        Hub.requests += 1
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Hub.header = self.headers.get("Authorization", "")
        if not Hub.alive or self.headers.get("Authorization") != "Bearer secret":
            self.send_response(503 if not Hub.alive else 401)
            self.end_headers()
            return
        Hub.received += json.loads(body)["events"]
        Hub.sender = json.loads(body).get("sender")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


class SharedHub(http.server.BaseHTTPRequestHandler):
    """The shared hub's three endpoints the client uses: /register, /ingest, DELETE /mine."""
    requests, received, sender, token = [], [], None, "th_" + "c" * 48

    def reply(self, code, body=b"{}"):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        SharedHub.requests.append(("POST", self.path, self.headers.get("Authorization", "")))
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/register":
            return self.reply(200, json.dumps({"token": SharedHub.token}).encode())
        if self.headers.get("Authorization") != f"Bearer {SharedHub.token}":
            return self.reply(401)
        SharedHub.received += json.loads(body)["events"]
        SharedHub.sender = json.loads(body).get("sender")
        self.reply(200)

    def do_DELETE(self):
        SharedHub.requests.append(("DELETE", self.path, self.headers.get("Authorization", "")))
        self.reply(200, b'{"deleted_events": 7}')

    def log_message(self, *a):
        pass


TRANSCRIPT = [
    {"type": "user", "timestamp": "2026-02-02T10:00:00Z",
     "message": {"role": "user", "content": "CANARY_TRANSCRIPT start\n\nMODE: autonomous"}},
    {"type": "assistant", "timestamp": "2026-02-02T10:05:00Z",
     "message": {"model": "claude-opus-5", "content": [
         {"type": "text", "text": "CANARY_TRANSCRIPT"},
         {"type": "tool_use", "name": "Read", "input": {"file_path": "CANARY_TRANSCRIPT"}},
         {"type": "tool_use", "name": "Bash", "input": {"command": "echo CANARY_TRANSCRIPT"}}],
                 "usage": {"input_tokens": 10, "output_tokens": 200,
                           "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 40}}},
    {"type": "user", "timestamp": "2026-02-02T10:06:00Z",
     "message": {"role": "user", "content": [
         {"type": "tool_result", "is_error": True, "content": "CANARY_TRANSCRIPT"},
         {"type": "tool_result", "content": "ok"}]}},
    {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-02-02T10:30:00Z"},
]


def gitc(project, date, *args):
    env = dict(os.environ, GIT_AUTHOR_DATE=f"{date}T12:00:00", GIT_COMMITTER_DATE=f"{date}T12:00:00")
    subprocess.run(["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    *args], check=True, env=env)


def commit(project, date, subject, *files):
    gitc(project, date, "add", "--", *files)
    gitc(project, date, "commit", "-q", "-m", subject)


class Hostile(http.server.BaseHTTPRequestHandler):
    """A server that answers with what a terminal or a parser should never be handed."""
    requests, mode = [], "status"

    def reply(self, code, body=b"{}", reason=None):
        self.send_response(code, reason)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        Hostile.requests.append(("POST", self.path, self.headers.get("Authorization", "")))
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/register":
            return self.reply(200, b'{"token": ["th_' + b"c" * 48 + b'"]}')
        if Hostile.mode == "status":
            return self.reply(503, reason="down \x1b]0;OWNED\x07 \\033[31mRED")
        self.reply(200, b'{"rejected_ids": [["x"], 7, {"a": 1}]}' if Hostile.mode == "ids" else b"[1, 2]")

    def do_DELETE(self):
        Hostile.requests.append(("DELETE", self.path, self.headers.get("Authorization", "")))
        self.reply(200, b'{"deleted_events": "7 \\u001b[31mRED"}')

    def log_message(self, *a):
        pass


SHARED = {}


def section_hash(project, name):
    """The trust contract, written out independently of the tool: the `- ` lines of the first
    `## <name>` section, right-stripped, joined with a newline, sha256."""
    lines = (Path(project) / "telesma/config.md").read_text(encoding="utf-8").split("\n")
    start = next((k for k, l in enumerate(lines) if l.rstrip() == f"## {name}"), None)
    section = []
    if start is not None:
        for l in lines[start + 1:]:
            if l.startswith("## "):
                break
            section.append(l)
    kept = [l.rstrip() for l in section if l.lstrip().startswith("- ")]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def trust(project, home):
    """What telesma.sh does once a person has seen the section in a terminal."""
    real = os.path.realpath(str(project))
    d = Path(home) / ".config/telesma/trust"
    d.mkdir(parents=True, exist_ok=True)
    (d / (hashlib.sha256(real.encode()).hexdigest()[:32] + ".json")).write_text(json.dumps(
        {"project": real, "sections": {"Telemetry": section_hash(project, "Telemetry")}}),
        encoding="utf-8")


def run(project, home, *flags, **extra):
    env = dict(os.environ, HOME=str(home), TELESMA_TEST_HUB_KEY="secret", **SHARED)
    env.update(extra)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("XDG_CONFIG_HOME", None)
    args = [str(project), *flags] if project else list(flags)
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, env=env)


def events(project, home):
    return [json.loads(l) for l in run(project, home, "--json").stdout.split("\n") if l]


def file_bytes(project):
    return {str(f.relative_to(project)): f.read_bytes() for f in project.rglob("*") if f.is_file()}


def small_project(tmp, name, key, endpoint, extra=""):
    p = Path(tmp) / name
    (p / "telesma/state").mkdir(parents=True)
    (p / "telesma/config.md").write_text(
        f"## Telemetry\n\n- **Send**: yes\n- **Endpoint**: {endpoint}\n- **API key**: {key}\n"
        f"- **Project label**:\n{extra}", encoding="utf-8")
    (p / "telesma/state/REPORT.md").write_text(
        "## Problem log\n\n- [2026-01-01] Task 1.1: an entry with text.\n", encoding="utf-8")
    return p


def trust_and_hostile_servers(check, port):
    own = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        marker = Path(tmp) / "COMMAND_RAN"

        print("6. a committed config cannot act on a machine whose user never saw it")
        Hub.requests, Hub.header = 0, ""
        for name, key in (("literal", "secret"), ("env", "env:VICTIM_TOKEN"),
                          ("cmd", f"cmd:touch {marker}; echo secret")):
            p = small_project(tmp, name, key, own)
            r = run(p, home, "--send", VICTIM_TOKEN="secret")
            check(r.returncode == 1 and Hub.requests == 0 and not marker.exists(),
                  f"`Send: yes` + custom endpoint + {name} key, no trust record → zero requests"
                  + (", no command run" if name == "cmd" else ""))
            check(not run(p, home, "--last-error").stdout.strip(),
                  f"{name}: not sending for lack of a confirmation is not reported as a failed send")
        trust(p, home)
        r = run(p, home, "--send")
        check(r.returncode == 0 and Hub.requests == 1 and marker.exists() and Hub.header == "Bearer secret",
              "the same `cmd:` project after the confirmation: the command runs, the batch goes out")
        cfg = p / "telesma/config.md"
        cfg.write_text(cfg.read_text().replace("echo secret", "echo secret # edited after the confirmation"))
        (p / "telesma/state/REPORT.md").write_text(
            "## Problem log\n\n- [2026-01-02] Task 1.2: a new entry.\n", encoding="utf-8")
        marker.unlink()
        r = run(p, home, "--send")
        check(r.returncode == 1 and Hub.requests == 1 and not marker.exists(),
              "a section edited after the confirmation is unconfirmed again: nothing sent, nothing run")

        p = small_project(tmp, "two-sections", "secret", "shared",
                          f"\n## Telemetry\n\n- **Send**: yes\n- **Endpoint**: {own}\n- **API key**: secret\n")
        trust(p, home)
        r = run(p, home, "--send")
        check(r.returncode != 0 and Hub.requests == 1,
              "a second `## Telemetry` section does not ride on the confirmation of the first")

        (home / ".config/telesma").mkdir(parents=True, exist_ok=True)
        (home / ".config/telesma/hub").write_text("token: th_" + "a" * 48 + "\nscope: metrics\n")
        p = small_project(tmp, "auto", "auto", own)
        trust(p, home)
        r = run(p, home, "--send")
        check(r.returncode == 2 and Hub.requests == 1 and "th_" not in Hub.header,
              "`API key: auto` with a custom endpoint: the shared hub's token goes nowhere else")
        Hub.received.clear()
        p = small_project(tmp, "narrow", "secret", own)
        trust(p, home)
        r = run(p, home, "--send")
        check(r.returncode == 0 and Hub.received
              and not any(e["title"] or e["text"] or "key" in e for e in Hub.received),
              "`scope: metrics` chosen at the opt-in holds for an own server too")
        (home / ".config/telesma/hub").unlink()

        print("https only (http to this machine)")
        # example.invalid never resolves (RFC 6761) — and no request may be attempted at all
        p = small_project(tmp, "clear-text", "secret", "http://example.invalid:8443")
        trust(p, home)
        r = run(p, home, "--send")
        check(r.returncode == 2 and "not https" in r.stdout,
              "a confirmed `http://` endpoint that is not this machine is refused before any request")
        r = run(None, home, "--register", TELESMA_SHARED_HUB="http://example.invalid:8443")
        check(r.returncode == 2 and "not https" in r.stdout and not (home / ".config/telesma/hub").exists(),
              "--register: a shared-hub address that is not https turns nothing on")
        (home / ".config/telesma/hub").write_text(
            "token: th_" + "a" * 48 + "\nscope: full\nendpoint: http://example.invalid:8443\n")
        p = small_project(tmp, "consent-endpoint", "", "shared")
        r = run(p, home, "--send")
        check(r.returncode == 2 and "not https" in r.stdout,
              "an `endpoint:` in the opt-in file that is not https gets no token")
        r = run(None, home, "--forget")
        check(r.returncode == 2 and (home / ".config/telesma/hub").exists(),
              "--forget does not send the token to a clear-text address either")
        (home / ".config/telesma/hub").unlink()

        print("7. what a server answers is data")
        bad = http.server.HTTPServer(("127.0.0.1", 0), Hostile)
        threading.Thread(target=bad.serve_forever, daemon=True).start()
        hostile = f"http://127.0.0.1:{bad.server_port}"
        p = small_project(tmp, "hostile", "secret", hostile)
        trust(p, home)
        r = run(p, home, "--send")
        err = run(p, home, "--last-error").stdout
        check(r.returncode == 2 and "503" in err and "OWNED" in err
              and not re.search(r"[\x00-\x09\x0b-\x1f\x7f\\\\]", err + r.stdout),
              f"a status line with escape sequences: the error is kept, without control characters "
              f"or backslashes ({err.strip()[-40:]!r})")
        for mode in ("ids", "list"):
            Hostile.mode = mode
            n = len(Hostile.requests)
            r = run(p, home, "--send")
            check(r.returncode == 0 and not r.stderr.strip() and len(Hostile.requests) == n + 1,
                  f"a malformed reply ({mode}) is not a crash: the batch counts as delivered")
            r = run(p, home, "--send")
            check(len(Hostile.requests) == n + 1, f"({mode}) and it is not sent again at every start")
            for cache in (home / ".cache/telesma").glob("telemetry-*.json"):
                cache.unlink()
        r = run(None, home, "--register", TELESMA_SHARED_HUB=hostile)
        check(r.returncode == 2 and not (home / ".config/telesma/hub").exists(),
              "--register: a token that is not a string of the expected shape turns nothing on")
        (home / ".config/telesma/hub").write_text(
            "token: th_" + "a" * 48 + f"\nscope: full\nendpoint: {hostile}\n")
        r = run(None, home, "--forget")
        check(r.returncode == 0 and "RED" not in r.stdout and "\x1b" not in r.stdout,
              "--forget prints a counter from the hub only when it is a number")
        bad.shutdown()

        print("identifiers")
        spec = importlib.util.spec_from_file_location("telemetry", TOOL)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        keys = {tool.remote_key(u) for u in (
            "git@github.com:Org/Repo.git", "https://github.com/Org/Repo.git", "https://github.com/org/repo/",
            "ssh://git@github.com/Org/Repo", "https://user:token@github.com/Org/Repo.git")}
        check(keys == {"github.com/org/repo"},
              f"one repository, one project id — scp form, https, ssh, with credentials ({sorted(keys)})")
        check(tool.remote_key("ssh://git@git.example.com:2332/team/app.git") == "git.example.com:2332/team/app",
              "a `scheme://user@host:port/…` remote keeps the key it always had (ids already reported stay)")
        p = small_project(tmp, "client-name", "", "none")
        pid = json.loads(run(p, home, "--json").stdout.split("\n")[0])["project"]
        other = Path(tmp) / "home2"
        other.mkdir()
        check(pid != hashlib.sha256(b"client-name").hexdigest()[:16]
              and pid == json.loads(run(p, home, "--json").stdout.split("\n")[0])["project"]
              and pid != json.loads(run(p, other, "--json").stdout.split("\n")[0])["project"],
              "a project without a remote: the id is not a bare hash of the directory name, is "
              "stable on this machine and differs on another")


def reused_quotes(path):
    """Lines where a replacement field of an f-string reuses the quote of the f-string itself
    (`f"{x["a"]}"`) — legal from Python 3.12, a SyntaxError on the 3.9 Telesma supports. An older
    interpreter simply compiles the file; a newer one walks the f-string tokens."""
    if sys.version_info < (3, 12):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True)
            return []
        except SyntaxError as e:
            return [e.lineno]
    out, stack = [], []
    with path.open("rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.FSTRING_START:
                stack.append(tok.string.lstrip("rRbBfFuU"))
            elif tok.type == tokenize.FSTRING_END:
                stack.pop()
            elif stack and tok.type == tokenize.STRING \
                    and any(q[0] in tok.string.lstrip("rRbBfFuU")[:1] for q in stack):
                out.append(tok.start[0])
    return out


def python39_grammar(check):
    print("the harness that reads this tool's --json, and the tools, parse on Python 3.9")
    root = TOOL.parent.parent
    for rel in ("benchmark/bench.py", "tools/telesma-telemetry.py", "tools/telesma-repair.py",
                "tools/telesma-survey.py", "tools/telesma-specky-snapshots.py"):
        lines = reused_quotes(root / rel)
        check(not lines, f"{rel}: no f-string reuses its own quote inside a replacement field {lines[:3]}")


def main():
    failures = []

    def check(condition, description):
        print(f"  {'✓' if condition else '✗'} {description}")
        if not condition:
            failures.append(description)

    srv = http.server.HTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    shared = http.server.HTTPServer(("127.0.0.1", 0), SharedHub)
    threading.Thread(target=shared.serve_forever, daemon=True).start()
    SHARED["TELESMA_SHARED_HUB"] = f"http://127.0.0.1:{shared.server_port}"

    with tempfile.TemporaryDirectory() as tmp:
        project, home = Path(tmp) / "project", Path(tmp) / "home"
        home.mkdir()
        for n, content in FILES.items():
            p = project / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content.replace("ENDPOINT", f"http://127.0.0.1:{srv.server_port}"),
                         encoding="utf-8")

        # History: task 7.1 is created BEFORE the project has telesma/state/.telesma-version.
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        # `(#7)` at the end of the subject = squash merge of PR #7 (that is how GitHub signs a squash).
        commit(project, "2026-01-15", "Telesma: 7.1 first CANARY_COMMIT (#7)", "telesma/state/PLAN.md")
        commit(project, "2026-02-02", "Telesma: 7.2 endpoint", "telesma/state/.telesma-version", "src")
        commit(project, "2026-02-04", "fix: 7.2 correction before v0.27.0", "telesma/spec")
        # A blocker that is NO LONGER in the directory — Telesma deletes the file once resolved.
        blk = project / "telesma/state/BLOCKED.md"
        blk.write_text("TELESMA BLOCKED\n\nTask: 7.3 test on production\nProblem: no access\n"
                       "  to the server.\nDetails: the session eyJhbGciOiJIUzI1NiJ9."
                       "eyJzdWIiOiJDQU5BUllfSldUIn0.c2lnbmF0dXJlLWNhbmFyeQ expired, key id "
                       "AKIACANARYAWSKEY0001.\n", encoding="utf-8")
        commit(project, "2026-02-05", "Telesma: blocker", "telesma/state/BLOCKED.md")
        blk.unlink()
        commit(project, "2026-02-06", "Telesma: blocker resolved", "telesma/state/BLOCKED.md")
        # PR #9 closed by a merge commit: the branch lives in history, so time to merge is computable.
        gitc(project, "2026-02-06", "checkout", "-q", "-b", "task-7.2-x")
        (project / "docs/note.md").write_text("CANARY_COMMIT on the branch\n", encoding="utf-8")
        commit(project, "2026-02-07", "Telesma: work on the branch CANARY_COMMIT", "docs/note.md")
        gitc(project, "2026-02-08", "checkout", "-q", "-")
        gitc(project, "2026-02-08", "merge", "--no-ff", "-q", "-m",
             "Merge pull request #9 from o/task-7.2-x CANARY_COMMIT", "task-7.2-x")
        sessions = home / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))
        sessions.mkdir(parents=True)
        (sessions / "11111111-2222-3333-4444-555555555555.jsonl").write_text(
            "\n".join(json.dumps(r) for r in TRANSCRIPT), encoding="utf-8")

        before = file_bytes(project)
        ev = events(project, home)
        everything = json.dumps(ev, ensure_ascii=False)
        types = {e["type"] for e in ev}

        print("1. nothing confidential leaves")
        for k in CANARIES:
            check(k not in everything, f"{k} did not leak")
        check(SECRET not in everything and "[removed]" in everything, "secret from the log cut out")
        check("t@example.com" not in everything, "committer e-mail did not leak")
        for k in SECRET_CANARIES:
            check(k not in everything, f"scrub: {k[:28]} cut out of the entry text")
        rv = next((e for e in ev if e["type"] == "review"), {"text": ""})
        check("src/app.py:42" in rv["text"] and "[e-mail]" in rv["text"]
              and "postgres://[removed]" in rv["text"] and "[path]/app.log" in rv["text"],
              "scrub: the review entry keeps its prose and the file it is about; the address, the "
              "URL with credentials and the directories of an absolute path are replaced")
        check(not any(c in e["text"] + e["title"] + e["key"] for e in ev for c in ("\x1b", "\x07")),
              "no control character in any event")

        print("event content")
        check(types == {"problem", "task", "bugfix", "decision", "change", "pitfall",
                        "scenario", "permissions", "state", "session", "test_run", "blocker",
                        "pr", "review"},
              f"all types present ({sorted(types)})")
        by = {(e["type"], e["key"]): e for e in ev}
        t72 = by[("task", "7.2")]
        check(t72["metrics"]["tries"] == 3, "`|` inside backticks does not shift the Tries column")
        check(t72["tech"] == ["python", "sql"] and t72["phase"] == "7", "task carries tech and phase")
        pr = [e for e in ev if e["type"] == "problem"]
        check(len(pr) == 3 and any("General lesson" in e["text"] for e in pr),
              "log entry is a block, not a line")
        ch = [e for e in pr if e["metrics"].get("red_check")]
        check(len(ch) == 1 and ch[0]["metrics"]["pr"] == 8
              and not any(e["metrics"].get("red_check") for e in pr if e not in ch),
              "`[check]` log entry → red_check + PR number; other entries without the flag")
        check(not any(e["type"] == "bugfix" and "template" in e["title"] for e in ev),
              "template entry inside a comment skipped")
        check(by[("bugfix", "## 2026-02-05 10:00 — 500 on an empty cart")]["metrics"]
              ["no_test"], "bugfix without a test flagged")
        sc = by[("scenario", "v0.1.0")]
        check(sc["metrics"] == {"works": 1, "broken": 1, "unchecked": 1}
              and "Empty file" in sc["text"], "scenarios: counters + note at [-]")
        st = next(e for e in ev if e["type"] == "state")["metrics"]
        check(st["plan"] == {"done": 2, "waiting_for_human": 1} and st["smoke"] is False,
              "state: ⛔ counted separately, missing smoke suite visible")
        check(st["adopted"] is True, "state: an adopted project is flagged (Adopted: yes)")
        changes = [e for e in ev if e["type"] == "change"]
        chg = changes[0] if changes else {"metrics": {}, "key": "", "title": "", "format_version": None}
        check(len(changes) == 1 and chg["metrics"]["rework"], "change → rework")
        check(re.fullmatch(r"change:[0-9a-f]{16}", chg["key"]) is not None
              and chg["title"] == "change request",
              "the name of a change file does not leave: the event carries a hash of it")
        check(by[("task", "7.3")]["metrics"]["status"] == "other" and by[("task", "7.3")]["tech"] == ["python"]
              and t72["metrics"]["status"] == "✅",
              "status cell: a mark stays, a sentence becomes `other`; a tag that is not one word is dropped")
        check(st["judge"] == "other" and st["max_tries"] == "other" and st["auto_approve"] == "yes",
              "state: a config value goes out only as one short word, anything else as `other`")

        print("repository integration (counters only)")
        check(st["integrations"] == {"repository": "github", "merge": "agent", "tracker": "none"}
              and st["pr_open"] == 1 and st["pr_merged"] == 1,
              "state: integration shape + open/merged PRs from plan tags")
        t71 = by[("task", "7.1")]
        check(t71["metrics"]["pr"] == 7 and t72["metrics"]["pr"] is None,
              "task carries the PR number from the `(pr: #n)` tag; without the tag None")
        prs = {e["metrics"]["number"]: e for e in ev if e["type"] == "pr"}
        check(set(prs) == {7, 9} and prs[7]["task"] == "7.1" and prs[7]["date"] == "2026-01-15"
              and prs[7]["metrics"]["hours_to_merge"] is None and prs[7]["metrics"]["fixes"] == 0
              and prs[7]["metrics"]["files"] == 1 and prs[7]["phase"] == "7",
              "squash `(#7)` at the end of the subject → pr event with the task from the subject, "
              "no time to merge")
        check(prs[9]["task"] == "7.2" and prs[9]["metrics"]["hours_to_merge"] == 24.0
              and prs[9]["metrics"]["fixes"] == 1 and prs[9]["metrics"]["files"] == 1
              and prs[9]["date"] == "2026-02-08",
              "merge commit `Merge pull request #9` → time to merge from the branch, fixes from 14 days")
        pr_text = json.dumps(list(prs.values()), ensure_ascii=False)
        check("CANARY_COMMIT" not in pr_text and "Merge pull request" not in pr_text
              and "first" not in pr_text and "branch" not in pr_text,
              "only the number and the task id come out of a commit/PR subject")

        print("sources beyond state files")
        g = t72["metrics"].get("git") or {}
        check(g.get("commits") == 2 and g.get("fixes") == 1 and t72["metrics"]["tries"] == 3,
              "git attaches numbers to a task from the report, does not overwrite tries")
        check(("task", "0.27") not in by, "`v0.27.0` in a commit subject is not task 0.27")
        t71 = by[("task", "7.1")]
        check(t71["format_version"] is None and t72["format_version"] == 7,
              "an event older than the first .telesma-version has an unknown version, not the first known")
        se = next(e for e in ev if e["type"] == "session")["metrics"]
        check(se["mode"] == "autonomous" and se["model"] == "claude-opus-5"
              and (se["tool_calls"], se["tool_errors"], se["compactions"]) == (2, 1, 1)
              and se["tokens"]["output"] == 200 and se["wall_minutes"] == 30
              and se["tools_by_name"] == {"Read": 1, "Bash": 1}
              and se["startup_prompt_chars"] == len("CANARY_TRANSCRIPT start\n\nMODE: autonomous"),
              "session: mode, model, tokens, tool errors, compactions, tools by name, prompt size")
        st_d = next(e for e in ev if e["type"] == "state")["metrics"]["diagnosis"]
        check(isinstance(st_d, dict) and set(st_d) == {"damage", "notice"},
              f"state carries the state-file diagnosis as numbers only ({st_d})")
        check(chg["metrics"]["kind"] == "bug"
              and by[("decision", "## 2026-02-06 — limit counted per organization")]["metrics"]
              ["kind"] == "correction"
              and by[("decision", "## 2026-02-07 — entry from before the Kind field")]["metrics"]
              ["kind"] is None, "Kind field: read, and without the field None (we do not guess)")
        ch = chg
        check(ch["format_version"] == 7 and ch["metrics"]["source_task"] == "7.1"
              and "source_version" in ch["metrics"] and ch["metrics"]["source_version"] is None
              and ch["metrics"]["source_date"] == "2026-02-01",
              "a bug reported under v7 is charged to the version it was INTRODUCED under "
              "(here: before versioning)")
        check(ch["metrics"]["detected_by"] == "production", "a bug carries the line of defence that caught it")
        check(t72["metrics"]["git"]["plus_tests"] == 0 and "plus" in t72["metrics"]["git"],
              "git counts lines added in test files separately (from the path only: test or not)")

        tr = sorted((e for e in ev if e["type"] == "test_run"), key=lambda e: e["date"])
        check(len(tr) == 3 and tr[2]["metrics"]["passed"] == 506 and tr[2]["metrics"]["failed"] == 1
              and tr[2]["metrics"]["red_on_the_way"] and tr[2]["metrics"]["phases"] == ["8"],
              "run in the \"suite passed/failed\" format: summed per suite, e2e 45/45 is zero "
              "failed, \"(3/8 failures…)\" and \"45/45 over 5\" skipped")
        check(len(tr) == 3 and tr[1]["metrics"] == dict(
            verdict="green", phases=["7"], passed=41, failed=2, skipped=2,
            red_on_the_way=True, attempt=2, duration_s=949)
            and "continues the same run" in tr[1]["text"]
            and "99 passed" not in tr[1]["text"],
            "run: block with a dateless paragraph, red on the way, metrics table skipped")
        bl = [e for e in ev if e["type"] == "blocker"]
        check(len(bl) == 1 and bl[0]["metrics"] == dict(hours=24.0, open=False, no_task=False)
              and bl[0]["task"] == "7.3" and bl[0]["title"] == "no access to the server.",
              "blocker reconstructed from git, although the file is gone")
        check(all(e["label"] == "project" for e in ev), "empty label = project directory name")
        no_date = [e for e in ev if not e["date"] and e["type"] == "pitfall"]
        check(no_date and all(e["format_version"] is None for e in no_date),
              "an event without a date in a project with version history has an unknown version, "
              "not the current one")
        pt = [e for e in ev if e["type"] == "pitfall" and "pytest" in e["text"]]
        check(len(pt) == 1 and pt[0]["tech"] == ["python"] and pt[0]["metrics"]["tech_from_text"],
              "a pitfall without a task gets its technology from the text — and it is flagged")
        pm = by[("permissions", "2026-02-02")]
        check(pm["metrics"] == {"command/l3/allow": 1}, f"judge log → counters per day ({pm['metrics']})")
        check(by[("permissions", "2026-02-03")]["metrics"] == {"other/l3/ask": 1},
              "judge log: a field that is not one word is counted as `other`")

        print("2. the id survives rotation")
        (project / "telesma/state/REPORT.md").write_text(REPORT % "", encoding="utf-8")
        (project / "telesma/state/REPORT_ARCHIVE.md").write_text(
            "# archive\n\n## Rotation 2026-03-01\n\n### Problem log\n\n" + LOG_ENTRY,
            encoding="utf-8")
        ev2 = events(project, home)
        check({e["id"] for e in ev} == {e["id"] for e in ev2}, "same ids after moving the entry")
        check(any("General lesson" in e["text"] for e in ev2), "entry text from the archive complete")

        print("6. a custom endpoint from a committed file needs this machine's confirmation")
        r = run(project, home, "--send")
        check(r.returncode == 1 and Hub.requests == 0 and "not confirmed on this machine" in r.stdout,
              "`Send: yes` + a custom endpoint + a readable key, no trust record → zero requests")
        trust(project, home)

        print("3. sending is idempotent and loses nothing")
        Hub.alive = False
        r = run(project, home, "--send")
        check(r.returncode == 2 and not Hub.received, "dead server → code 2, nothing received")
        check(bool(run(project, home, "--last-error").stdout.strip()), "error remembered")
        Hub.alive = True
        r = run(project, home, "--send")
        check(r.returncode == 0 and len(Hub.received) == len(ev2),
              f"after the server came back everything arrived ({len(Hub.received)}/{len(ev2)})")
        check(not run(project, home, "--last-error").stdout.strip(), "error cleared")
        n = Hub.sender or {}
        check(re.fullmatch(r"[0-9a-f]{12}", n.get("id", "")) is not None and n.get("name")
              and "@" not in json.dumps(n), "batch signed by the sender (hash, no e-mail)")
        salt = home / ".config/telesma/salt"
        mail = subprocess.run(["git", "-C", str(project), "config", "user.email"],
                              capture_output=True, text=True).stdout.strip() or "?"
        check(salt.is_file() and (salt.stat().st_mode & 0o777) == 0o600
              and n.get("id") != hashlib.sha256(mail.lower().encode()).hexdigest()[:12],
              "sender id is salted per machine (salt 0600 next to the opt-in), not a bare hash of the e-mail")
        run(project, home, "--send")
        check(len(Hub.received) == len(ev2), "second run sends nothing")
        cfg = project / "telesma/config.md"
        cfg.write_text(cfg.read_text().replace("Send**: yes", "Send**: no"))
        with (project / "telesma/state/BUGFIXES.md").open("a") as f:
            f.write("\n## 2026-02-08 — new bug\n**Symptom**: x\n")
        run(project, home, "--send")
        check(len(Hub.received) == len(ev2), "`Send: no` → nothing goes out")

        print("5. the shared hub needs a per-machine opt-in")
        consent = home / ".config/telesma/hub"
        cfg.write_text(cfg.read_text().replace("Send**: no", "Send**: yes")
                       .replace(f"Endpoint**: http://127.0.0.1:{srv.server_port}", "Endpoint**: shared"))
        r = run(project, home, "--send")
        check(r.returncode == 1 and not SharedHub.requests,
              "`Send: yes` + `Endpoint: shared` without the opt-in file → zero HTTP requests")
        r = run(None, home, "--register", "--scope", "full")
        check(r.returncode == 0 and consent.is_file() and SharedHub.token in consent.read_text()
              and (consent.stat().st_mode & 0o777) == 0o600, "--register → opt-in file 0600 with the token")
        r = run(project, home, "--send")
        sh = SharedHub.received
        check(r.returncode == 0 and len(sh) == len(ev2) + 1, f"opted in → events arrive ({len(sh)})")
        payload = json.dumps(sh, ensure_ascii=False) + json.dumps(SharedHub.sender)
        check(SharedHub.sender and "name" not in SharedHub.sender, "shared hub: no sender name in the batch")
        check(all(e["label"] == e["project"] for e in sh) and '"project"' not in
              json.dumps([e["label"] for e in sh]), "shared hub: empty label = project hash, not the directory")
        check(all(k not in payload for k in CANARIES) and SECRET not in payload,
              "shared hub: canaries did not leak")
        check(any(e["text"] for e in sh), "scope full: entry text goes out")
        SharedHub.received = []
        (home / ".cache/telesma").joinpath(
            next(f.name for f in (home / ".cache/telesma").glob("telemetry-*-shared.json"))).unlink()
        cfg.write_text(cfg.read_text().replace("- **Project label**:", "- **Scope**: metrics\n- **Project label**:"))
        run(project, home, "--send")
        check(SharedHub.received and not any(e["title"] or e["text"] or "key" in e
                                             for e in SharedHub.received),
              f"`Scope: metrics` → no title, text or key ({len(SharedHub.received)} events)")

        def strings(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    yield k
                    yield from strings(v)
            elif isinstance(x, list):
                for v in x:
                    yield from strings(v)
            elif isinstance(x, str):
                yield x
        loose = sorted({t for e in SharedHub.received for t in strings(e)
                        if len(t) > 64 or re.search(r"\s", t)})
        dump = json.dumps(SharedHub.received, ensure_ascii=False)
        check(not loose and not any(k in dump for k in CANARIES + SECRET_CANARIES),
              f"`Scope: metrics` → no free text anywhere in an event: every string is one word {loose[:3]}")
        own = list((home / ".cache/telesma").glob("telemetry-*.json"))
        r = run(None, home, "--forget")
        check(r.returncode == 0 and ("DELETE", "/mine", f"Bearer {SharedHub.token}") in SharedHub.requests
              and not consent.exists(), "--forget → DELETE /mine with the token, opt-in file removed")
        left = {f.name for f in (home / ".cache/telesma").glob("telemetry-*.json")}
        check(not any(n.endswith("-shared.json") for n in left) and len(left) == len(own) - 1,
              "--forget clears the shared-hub send record, keeps the own-server one")
        n = len(SharedHub.requests)
        run(project, home, "--send")
        check(len(SharedHub.requests) == n, "after --forget nothing goes out")

        print("4. the collector only reads")
        for n in ("telesma/state/REPORT.md", "telesma/state/REPORT_ARCHIVE.md", "telesma/config.md",
                  "telesma/state/BUGFIXES.md"):
            before.pop(n, None)
        now = file_bytes(project)
        check(all(now.get(n) == b for n, b in before.items()), "project files unchanged")
        check(set(now) - set(before) <= {"telesma/state/REPORT.md", "telesma/state/REPORT_ARCHIVE.md",
                                         "telesma/config.md", "telesma/state/BUGFIXES.md"},
              "no new files in the project")

    trust_and_hostile_servers(check, srv.server_port)
    python39_grammar(check)
    srv.shutdown()
    shared.shutdown()
    print("OK" if not failures else f"FAILURES: {len(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    print("Test tools/telesma-telemetry.py")
    main()
