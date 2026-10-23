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

Plus the sources beyond state files: git (the commit subject and the session transcript carry
canaries too — only numbers come out of them), the `Kind` field and the framework version.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "telesma-telemetry.py"
CANARIES = ("CANARY_SPEC", "CANARY_CODE", "CANARY_CHANGES", "CANARY_COMMAND",
            "CANARY_COMMIT", "CANARY_TRANSCRIPT")
SECRET = "sk-abcdefghijklmnopqrstuvwxyz123456"

LOG_ENTRY = f"""- [2026-02-02] Task 7.2: **mock returned 200, production 401** — first line.
  Second line: the token in the test was {SECRET}, it had to be moved out.
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

## Change history

### 2026-02-03 2026-02-03-new-limit.md
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
    "telesma/config.md": "## Tests\n\n- **Smoke suite**: none\n\n## Integrations\n\n"
                       "- **Repository**: github\n- **Merge**: agent\n- **Tracker**: none\n\n"
                       "## Telemetry\n\n"
                       "- **Send**: yes\n- **Endpoint**: ENDPOINT\n"
                       "- **API key**: env:TELESMA_TEST_HUB_KEY\n- **Project label**:\n",
    "telesma/state/PLAN.md": "### Phase 7: Something\n\n- [x] Task 7.1: first (tech: python) (pr: #7)\n"
                     "- [x] Task 7.2: endpoint (requires: 7.1) (tech: python, sql)\n"
                     "- [ ] ⛔ Task 7.3: test on production (tech: python) (pr: #8)\n",
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
                                           "ts": "2026-02-02T10:00:00"}) + "\n",
    "docs/test-scenarios/v0.1.0.md": "# v0.1.0\n\n- **Date:** 2026-02-07\n\n### 1.1 Login\n\n"
                                     "- [x] **Result 1.1**\n\n### 1.2 Export\n\n"
                                     "- [-] **Result 1.2**\n  Empty file instead of CSV.\n\n"
                                     "### 1.3 Limit\n\n- [ ] **Result 1.3**\n",
    "telesma/spec/requirements.md": "CANARY_SPEC secret business model\n",
    "src/app.py": "# CANARY_CODE\n",
    "telesma/changes/processed/2026-02-03-new-limit.md": "CANARY_CHANGES client X pays too little\n",
}


class Hub(http.server.BaseHTTPRequestHandler):
    received, alive, header, sender = [], True, "", None

    def do_POST(self):
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


def run(project, home, *flags):
    env = dict(os.environ, HOME=str(home), TELESMA_TEST_HUB_KEY="secret")
    env.pop("CLAUDE_CONFIG_DIR", None)
    return subprocess.run([sys.executable, str(TOOL), str(project), *flags],
                          capture_output=True, text=True, env=env)


def events(project, home):
    return [json.loads(l) for l in run(project, home, "--json").stdout.split("\n") if l]


def file_bytes(project):
    return {str(f.relative_to(project)): f.read_bytes() for f in project.rglob("*") if f.is_file()}


def main():
    failures = []

    def check(condition, description):
        print(f"  {'✓' if condition else '✗'} {description}")
        if not condition:
            failures.append(description)

    srv = http.server.HTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

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
                       "  to the server.\n", encoding="utf-8")
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

        print("event content")
        check(types == {"problem", "task", "bugfix", "decision", "change", "pitfall",
                        "scenario", "permissions", "state", "session", "test_run", "blocker",
                        "pr"},
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
        check(by[("change", "2026-02-03-new-limit.md")]["metrics"]["rework"], "change → rework")

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
        check(by[("change", "2026-02-03-new-limit.md")]["metrics"]["kind"] == "bug"
              and by[("decision", "## 2026-02-06 — limit counted per organization")]["metrics"]
              ["kind"] == "correction"
              and by[("decision", "## 2026-02-07 — entry from before the Kind field")]["metrics"]
              ["kind"] is None, "Kind field: read, and without the field None (we do not guess)")
        ch = by[("change", "2026-02-03-new-limit.md")]
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

        print("2. the id survives rotation")
        (project / "telesma/state/REPORT.md").write_text(REPORT % "", encoding="utf-8")
        (project / "telesma/state/REPORT_ARCHIVE.md").write_text(
            "# archive\n\n## Rotation 2026-03-01\n\n### Problem log\n\n" + LOG_ENTRY,
            encoding="utf-8")
        ev2 = events(project, home)
        check({e["id"] for e in ev} == {e["id"] for e in ev2}, "same ids after moving the entry")
        check(any("General lesson" in e["text"] for e in ev2), "entry text from the archive complete")

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
        run(project, home, "--send")
        check(len(Hub.received) == len(ev2), "second run sends nothing")
        cfg = project / "telesma/config.md"
        cfg.write_text(cfg.read_text().replace("Send**: yes", "Send**: no"))
        with (project / "telesma/state/BUGFIXES.md").open("a") as f:
            f.write("\n## 2026-02-08 — new bug\n**Symptom**: x\n")
        run(project, home, "--send")
        check(len(Hub.received) == len(ev2), "`Send: no` → nothing goes out")

        print("4. the collector only reads")
        for n in ("telesma/state/REPORT.md", "telesma/state/REPORT_ARCHIVE.md", "telesma/config.md",
                  "telesma/state/BUGFIXES.md"):
            before.pop(n, None)
        now = file_bytes(project)
        check(all(now.get(n) == b for n, b in before.items()), "project files unchanged")
        check(set(now) - set(before) <= {"telesma/state/REPORT.md", "telesma/state/REPORT_ARCHIVE.md",
                                         "telesma/config.md", "telesma/state/BUGFIXES.md"},
              "no new files in the project")

    srv.shutdown()
    print("OK" if not failures else f"FAILURES: {len(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    print("Test tools/telesma-telemetry.py")
    main()
