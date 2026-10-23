#!/usr/bin/env python3
"""Tests of tools/telesma-specky-snapshots.py against a fake Specky (http.server in a thread) and a repo with tags.

Pins: form login + session cookie + CSRF double-submit on POST; the snapshot payload (tag,
SHA of the tagged commit, tag message, full file text); oldest tag first regardless of the
order of the arguments; a tag without a file skipped; 409 `snapshot_tag_exists` = skip, not an
error (a second run is idempotent); the password never in the output; `--dry-run` sends
nothing; exit code 1 when the server answers with an error.

Run: python3 tools/test-specky-snapshots.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TELESMA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TELESMA / "tools"))
import importlib

snapshots = importlib.import_module("telesma-specky-snapshots")

PASSWORD = "Secret-Password-Canary-77"
EMAIL = "tester@example.com"
PROJECT_ID = "01J9XYZ0123456789ABCDEFGHJ"
FAILURES = []


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


# --- fake Specky ------------------------------------------------------------------------------

class State:
    def __init__(self):
        self.snapshots: list[dict] = []   # creation order
        self.requests: list[tuple[str, str]] = []
        self.refuse = False               # 500 on every POST snapshots


STATE = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _cookies(self):
        c = SimpleCookie()
        c.load(self.headers.get("Cookie", ""))
        return {k: v.value for k, v in c.items()}

    def _json(self, status, data, headers=()):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        STATE.requests.append(("GET", self.path))
        if self.path == "/api/auth/csrf":
            if self._cookies().get("specky_session") != "session-123":
                return self._json(401, {"detail": "Unauthorized"})
            return self._json(200, {"csrf_token": "csrf-abc"},
                              [("Set-Cookie", "specky_csrf=csrf-abc; Path=/")])
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        STATE.requests.append(("POST", self.path))
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path == "/api/auth/login":
            if self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                return self._json(415, {"detail": "form only"})
            fields = dict(urllib.parse.parse_qsl(body.decode()))
            if fields.get("username") == EMAIL and fields.get("password") == PASSWORD:
                self.send_response(204)
                self.send_header("Set-Cookie", "specky_session=session-123; Path=/; HttpOnly")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._json(400, {"detail": "LOGIN_BAD_CREDENTIALS"})
        if self.path == f"/api/projects/{PROJECT_ID}/snapshots":
            ck = self._cookies()
            if ck.get("specky_session") != "session-123":
                return self._json(401, {"detail": "Unauthorized"})
            if ck.get("specky_csrf") != self.headers.get("X-CSRF-Token"):
                return self._json(403, {"detail": "CSRF"})
            if STATE.refuse:
                return self._json(500, {"detail": "outage"})
            data = json.loads(body)
            for m in STATE.snapshots:
                if m["git_tag"] == data.get("git_tag"):
                    return self._json(409, {"detail": {"code": "snapshot_tag_exists",
                                                      "snapshot_id": m["id"]}})
            data["id"] = f"snap-{len(STATE.snapshots) + 1}"
            STATE.snapshots.append(data)
            return self._json(201, {"id": data["id"], "name": data["name"]})
        self._json(404, {"detail": "not found"})


def server():
    s = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


# --- repo with tags ---------------------------------------------------------------------------

def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True,
                          text=True, env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}).stdout


def repo_with_tags(directory: Path, mcp_base: str) -> Path:
    repo = directory / "proj"
    (repo / "telesma" / "state").mkdir(parents=True)
    (repo / "docs" / "test-scenarios").mkdir(parents=True)
    (repo / "telesma" / "config.md").write_text(
        "## Tests\n- **Test command**: true\n\n## Integrations\n\n<!-- comment -->\n"
        "- **Repository**: none\n- **Tracker**: specky\n"
        f"- **Tracker project**: {PROJECT_ID}\n  <!-- project_id -->\n"
        f"- **Tracker MCP**: {mcp_base}/mcp\n\n## Permissions\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("1")
    git(repo, "add", "."); git(repo, "commit", "-qm", "start")
    # v0.1.0 — scenarios file, annotated tag with a message
    (repo / "docs/test-scenarios/v0.1.0.md").write_text("# v0.1.0 — scenarios\n\n- [ ] **Result 1.1**\n")
    git(repo, "add", "."); git(repo, "commit", "-qm", "release 0.1.0")
    git(repo, "tag", "-a", "v0.1.0", "-m", "First release.\n\nLogin and list.")
    # v0.2.0 — WITHOUT a scenarios file (must be skipped with --all)
    (repo / "a.txt").write_text("2")
    git(repo, "add", "."); git(repo, "commit", "-qm", "release 0.2.0")
    git(repo, "tag", "-a", "v0.2.0", "-m", "No scenarios.")
    # v0.10.0 — file + lightweight tag (no message); the number checks version sort, not lexical
    (repo / "docs/test-scenarios/v0.10.0.md").write_text("# v0.10.0\n\n- [ ] **Result 1.1**\n")
    git(repo, "add", "."); git(repo, "commit", "-qm", "release 0.10.0")
    git(repo, "tag", "v0.10.0")
    # phase tag — never a release
    git(repo, "tag", "telesma/phase-3")
    return repo


def run(*args, password=PASSWORD):
    out, err = io.StringIO(), io.StringIO()
    env_prev = os.environ.get("SPECKY_PASSWORD")
    os.environ["SPECKY_PASSWORD"] = password
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = snapshots.main(list(args))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
    finally:
        if env_prev is None:
            os.environ.pop("SPECKY_PASSWORD", None)
        else:
            os.environ["SPECKY_PASSWORD"] = env_prev
    return code, out.getvalue(), err.getvalue()


def main():
    s, base = server()
    with tempfile.TemporaryDirectory() as tmp:
        repo = repo_with_tags(Path(tmp), base)
        sha_010 = git(repo, "rev-parse", "v0.1.0^{}").strip()
        sha_0100 = git(repo, "rev-parse", "v0.10.0^{}").strip()

        print("--dry-run")
        code, out, err = run(str(repo), "--all", "--dry-run", "--email", EMAIL)
        ok(code == 0, "exit code 0")
        ok("v0.1.0" in out and "v0.10.0" in out and "v0.2.0" not in out,
           "list: tags with a file, without v0.2.0 (no file) and without telesma/phase-*")
        ok(out.index("v0.1.0") < out.index("v0.10.0"), "order by version number, not lexical")
        ok(not STATE.requests, "--dry-run sent no request")

        print("first run --all")
        code, out, err = run(str(repo), "--all", "--email", EMAIL)
        ok(code == 0, f"exit code 0 (stderr: {err.strip()[:120]!r})")
        ok(len(STATE.snapshots) == 2, f"two snapshots created ({len(STATE.snapshots)})")
        ok([m["git_tag"] for m in STATE.snapshots] == ["v0.1.0", "v0.10.0"], "oldest first")
        m1 = STATE.snapshots[0]
        ok(m1["git_commit_sha"] == sha_010 and STATE.snapshots[1]["git_commit_sha"] == sha_0100,
           "SHA = the commit the tag points at (not the SHA of the tag object)")
        ok(m1["name"] == "v0.1.0" and m1["description"] == "First release.\n\nLogin and list.",
           "name = tag, description = message of the annotated tag")
        ok(STATE.snapshots[1]["description"] is None, "lightweight tag → description None")
        ok(m1["test_scenarios_md"] == (repo / "docs/test-scenarios/v0.1.0.md").read_text(),
           "full text of the scenarios file in the payload")
        paths = [p for _, p in STATE.requests]
        ok(paths[:2] == ["/api/auth/login", "/api/auth/csrf"], "login, then CSRF, then the POSTs")
        ok(PASSWORD not in out and PASSWORD not in err, "the password does not appear in the output")
        ok("✓ v0.1.0" in out and "snap-1" in out, "the output gives the snapshot id")

        print("second run — idempotence (409)")
        code, out, err = run(str(repo), "v0.10.0", "v0.1.0", "--email", EMAIL)
        ok(code == 0, "409 snapshot_tag_exists is not an error")
        ok(len(STATE.snapshots) == 2, "nothing new was created")
        ok(out.count("already exists") == 2 and "snap-2" in out, "both tags reported as existing, with id")
        ok(out.index("v0.1.0") < out.index("v0.10.0"),
           "oldest first also with arguments given in reverse")

        print("errors")
        code, out, err = run(str(repo), "v9.9.9", "--email", EMAIL)
        ok(code == 1 and "no such v* tags" in err, "unknown tag → exit code 1, nothing sent")
        code, out, err = run(str(repo), "v0.1.0", "--email", EMAIL, password="wrong")
        ok(code == 1 and "login: HTTP 400" in err, "wrong password → exit code 1, login message")
        ok("wrong" not in out, "a wrong password does not reach the output either")
        STATE.refuse = True
        code, out, err = run(str(repo), "v0.1.0", "--email", EMAIL)
        ok(code == 1 and "HTTP 500" in err, "server error on snapshot → exit code 1")
        STATE.refuse = False

        print("configuration")
        cfg = repo / "telesma" / "config.md"
        cfg.write_text(cfg.read_text().replace("- **Tracker**: specky", "- **Tracker**: none"))
        code, out, err = run(str(repo), "--all", "--dry-run")
        ok(code == 1 and "Tracker: specky" in err, "without Tracker: specky and without --project-id → exit code 1")
        code, out, err = run(str(repo), "--all", "--dry-run", "--project-id", PROJECT_ID)
        ok(code == 0 and "2 snapshots" in out, "--project-id is enough without Tracker: specky")
        ok(snapshots.base_from_mcp("https://app.specky.app/mcp") == "https://app.specky.app",
           "REST address = Tracker MCP without the path")

    s.shutdown()
    print()
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
