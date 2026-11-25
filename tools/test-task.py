#!/usr/bin/env python3
"""Self-test of tools/telesma-task.py (`next`, `done`, `commit`) and tools/telesma_state.py.

Every case builds a git project in a temp directory; the trust record goes to a temp
XDG_CONFIG_HOME. Nothing here touches this repository.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TELESMA = Path(__file__).resolve().parent.parent
TOOL = TELESMA / "tools" / "telesma-task.py"
TEMPLATE = (TELESMA / "templates" / "config.md").read_text(encoding="utf-8")
REPORT = (TELESMA / "templates" / "REPORT.md").read_text(encoding="utf-8")
sys.path.insert(0, str(TELESMA / "tools"))
sys.path.insert(0, str(TELESMA / "templates" / "setup"))
import telesma_state as ts  # noqa: E402
import trust  # noqa: E402
import telesma_usage as tu  # noqa: E402

FAILURES = []
XDG = tempfile.mkdtemp(prefix="telesma-task-xdg-")
ENV = dict(os.environ, XDG_CONFIG_HOME=XDG, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", TELESMA_TEST_TIMEOUT="60")
ENV.pop("GIT_DIR", None)
# Claude Code's transcripts: a directory of this test's own (the usage record reads them, K13)
CLAUDE_DIR = Path(tempfile.mkdtemp(prefix="telesma-task-claude-"))
ENV["CLAUDE_CONFIG_DIR"] = str(CLAUDE_DIR)


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


def config(**fields):
    t = TEMPLATE
    for label, value in fields.items():
        t, n = re.subn(r"^- \*\*" + re.escape(label) + r"\*\*:.*$", f"- **{label}**: {value}", t, count=1, flags=re.M)
        assert n == 1, label
    return t


PLAN = """# Plan

## Tasks

### Phase 1: Start

- [ ] Task 1.1: Greeting module (tech: python) (spec: api.md Greeting)
  - AC: greet() returns hello
- [ ] Test: greeting tests (requires: 1.1)
- [ ] Task 1.2: Farewell (requires: 1.1)

### Phase 2: Later

- [ ] ⛔ Task 2.1: Production check by the owner (requires: 1.2)
"""

SPEC = "# API\n\nintro\n\n## Greeting\n\nThe greet function says hello.\n\n## Farewell\n\nbye\n" + "\n".join(
    f"filler {n}" for n in range(300)) + "\n"

INDEX = """# SPEC_INDEX.md

## Documents

### api.md (310 lines)
The API.

#### Sections:
| Lines | Section | Anchor | Description |
|-------|---------|--------|-------------|
| 1-4 | Intro | # API | intro |
| 3-8 | Greeting | ## Greeting | the greet function |
| 9-310 | Farewell | ## Farewell | bye |
"""


def sh(d, *cmd, check=True):
    r = subprocess.run(list(cmd), cwd=d, env=ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd}: {r.stdout}{r.stderr}")
    return r


def project(test_cmd="python3 -m unittest discover -s tests -q", plan=PLAN, checks=False, trusted=True, **extra):
    d = Path(tempfile.mkdtemp(prefix="telesma-task-"))
    (d / "telesma" / "state").mkdir(parents=True)
    (d / "telesma" / "guidelines").mkdir()
    (d / "telesma" / "spec").mkdir()
    (d / "telesma" / "guidelines" / "general.md").write_text("# general\nKeep it simple.\n", encoding="utf-8")
    (d / "telesma" / "guidelines" / "python.md").write_text("# python\nUse type hints.\n", encoding="utf-8")
    (d / "telesma" / "spec" / "api.md").write_text(SPEC, encoding="utf-8")
    (d / "telesma" / "state" / "SPEC_INDEX.md").write_text(INDEX, encoding="utf-8")
    (d / "telesma" / "state" / "PLAN.md").write_text(plan, encoding="utf-8")
    (d / "telesma" / "state" / "REPORT.md").write_text(REPORT, encoding="utf-8")
    fields = {"Test command": test_cmd, "Full suite command": test_cmd,
              "Linter/formatter": "none", "Enabled": "yes" if checks else "no"}
    fields.update(extra)
    (d / "telesma" / "config.md").write_text(config(**fields), encoding="utf-8")
    (d / "tests").mkdir()
    (d / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (d / "tests" / "test_base.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n"
                                              "    def test_ok(self):\n        self.assertTrue(True)\n",
                                              encoding="utf-8")
    (d / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    if checks:
        shutil.copytree(TELESMA / "templates" / "checks", d / "telesma" / "checks")
    sh(d, "git", "init", "-q", "-b", "main")
    sh(d, "git", "add", "-A")
    sh(d, "git", "commit", "-q", "-m", "init")
    if checks:
        sh(d, sys.executable, str(d / "telesma" / "checks" / "telesma-checks.py"), "--baseline", str(d),
           "--templates", str(TELESMA / "templates" / "checks"), "--config-section")
    if trusted:
        restamp(d)
    return d


def restamp(d):
    """The person confirms the config on this machine (the launcher's trust gate)."""
    old = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = XDG
    trust.stamp(str(d), None)
    if old is None:
        del os.environ["XDG_CONFIG_HOME"]
    else:
        os.environ["XDG_CONFIG_HOME"] = old


def task(d, *args):
    r = subprocess.run([sys.executable, str(TOOL), *args], cwd=d, env=ENV, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def head_message(d):
    return sh(d, "git", "log", "-1", "--format=%B").stdout


def read(d, rel):
    return (d / rel).read_text(encoding="utf-8")


# --- the shared module ----------------------------------------------------------------------

print("telesma_state — selection, ticking, the report row")
plan = ts.Plan(PLAN)
cfg = ts.Config(config())
sel = ts.select(plan, cfg)
ok(sel["why"] == "task" and sel["item"]["tid"] == "1.1", "the first unchecked task with its dependencies done is chosen")
ok(ts.launcher_hint(plan, sel) == "1.1", "the launcher hint names it the same way")
ok(ts.name_of(plan, sel["item"]) == "Task 1.1: Greeting module", "the name drops tags")
done_plan = ts.Plan(ts.tick(PLAN, sel["item"]["idx"]))
sel2 = ts.select(done_plan, cfg)
ok(sel2["item"] and ts.name_of(done_plan, sel2["item"]) == "Test: greeting tests",
   "an item without a dotted id (`- [ ] Test:`) is chosen next")
ok(ts.select(ts.Plan(PLAN.replace(" (requires: 1.2)\n", "\n")), ts.Config(config(**{"Active phases": "2"})))["why"] == "human",
   "an active phase holding only a ⛔ item gives 'waiting on a human'")
row = ts.add_history_row(REPORT, ["Task 1.1: X", "✅", "3 passed", 1, "this commit", "2026-11-11 10:00"])
ok("| Task 1.1: X | ✅ | 3 passed | 1 | this commit | 2026-11-11 10:00 |" in row and "| | | | | | |" not in row,
   "the history row replaces the template's empty row")
pats = ts.ignore_patterns(cfg)
ok(ts.ignored(".env", pats) and ts.ignored("a/b/node_modules/x.js", pats) and ts.ignored("x/debug.log", pats)
   and ts.ignored("telesma/artifacts/s.png", pats) and not ts.ignored("src/app.py", pats),
   "Ignore on commit: a file name, a directory anywhere, a glob, a path prefix")

# --- next -----------------------------------------------------------------------------------

print("next — the task and its context")
d = project()
rc, out = task(d, "next")
ok(rc == 0 and out.startswith("TELESMA NEXT: Task 1.1: Greeting module"), "next issues the first task")
ok("  - AC: greet() returns hello" in out, "with its AC lines")
ok("Keep it simple." in out and "Use type hints." in out, "with general.md and the (tech:) guideline in full")
ok("The greet function says hello." in out and "filler 200" not in out,
   "the spec section named in the tag is printed, not the whole file")
ok("| 5-10 | Greeting |" in read(d, "telesma/state/SPEC_INDEX.md"),
   "a range whose anchor moved is found again and corrected in SPEC_INDEX.md")
session = json.loads((d / ".git" / "telesma-task" / "session.json").read_text(encoding="utf-8"))
ok(session["task"] == {"tid": "1.1"}, "the task is reserved outside git")
rc, out = task(d, "next")
ok("Issued again" in out and "already given in full" in out, "a second next re-issues it and lists the guidelines")
rc, out = task(d, "next", "--full")
ok("Use type hints." in out, "--full prints the guidelines again (after a compaction)")

# --- done -----------------------------------------------------------------------------------

print("done — tests, tick, row, commit")
rc, out = task(d, "done")
ok(rc == 1 and "nothing changed" in out, "done with no change (only what next itself corrected) is refused")
(d / "greet.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
(d / "tests" / "test_greet.py").write_text("import unittest\nfrom greet import greet\n\nclass G(unittest.TestCase):\n"
                                           "    def test_greet(self):\n        self.assertEqual(greet(), 'hello')\n",
                                           encoding="utf-8")
(d / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
(d / "debug.log").write_text("x\n", encoding="utf-8")
rc, out = task(d, "done", "1.2")
ok(rc == 1 and "the issued task is Task 1.1" in out, "done for a task that was not issued is refused")
rc, out = task(d, "done", "--trailer", "Specky-Req: R1@abcdef1")
ok(rc == 0 and "committed" in out, "done commits")
msg = head_message(d)
ok(msg.startswith("Telesma: Task 1.1: Greeting module") and msg.rstrip().endswith(ts.FOOTER)
   and "Specky-Req: R1@abcdef1" in msg, "subject = the task, trailer above the footer, footer last")
committed = sh(d, "git", "show", "--name-only", "--format=", "HEAD").stdout.split()
ok("greet.py" in committed and "tests/test_greet.py" in committed and "telesma/state/PLAN.md" in committed
   and "telesma/state/REPORT.md" in committed, "the commit holds the work and the state files")
ok(".env" not in committed and "debug.log" not in committed, "Ignore on commit keeps .env and *.log out")
ok("- [x] Task 1.1:" in read(d, "telesma/state/PLAN.md"), "the task is ticked by the script")
rep = read(d, "telesma/state/REPORT.md")
ok(re.search(r"^\| Task 1\.1: Greeting module \| ✅ \| Ran \d+ tests? \(\d+ s\) \| 1 \| this commit \|", rep, re.M) is not None,
   "the Task history row is written by the script (tries = 1)")
ok("- **Progress**: 1/4 tasks completed" in rep, "the Summary progress is overwritten")
rc, out = task(d, "done")
ok(rc == 1 and "no task is issued" in out, "done again without next is refused")

print("done — refusals")
rc, out = task(d, "next")
ok(out.startswith("TELESMA NEXT: Test: greeting tests"), "next moves on to the following item")
(d / "tests" / "test_fail.py").write_text("import unittest\n\nclass F(unittest.TestCase):\n"
                                          "    def test_no(self):\n        self.fail('red')\n", encoding="utf-8")
before_plan, before_report = read(d, "telesma/state/PLAN.md"), read(d, "telesma/state/REPORT.md")
rc, out = task(d, "done")
ok(rc == 1 and "tests failed" in out and "red" in out, "a red test refuses done and shows the output")
ok(read(d, "telesma/state/PLAN.md") == before_plan and read(d, "telesma/state/REPORT.md") == before_report,
   "a refusal leaves PLAN.md and REPORT.md as they were")
(d / "tests" / "test_fail.py").unlink()
(d / "tests" / "test_more.py").write_text("import unittest\n\nclass M(unittest.TestCase):\n"
                                          "    def test_yes(self):\n        self.assertTrue(1)\n", encoding="utf-8")
rc, out = task(d, "done")
ok(rc == 0, "after the fix done commits")
ok(re.search(r"^\| Test: greeting tests \| ✅ \| .* \| 2 \| this commit \|", read(d, "telesma/state/REPORT.md"), re.M)
   is not None, "tries = refusals + 1")
rep = read(d, "telesma/state/REPORT.md")
first = sh(d, "git", "log", "--format=%h", "--grep", "^Telesma: Task 1.1:").stdout.split()[0]
ok(re.search(rf"^\| Task 1\.1: Greeting module \| ✅ \| .* \| 1 \| {first} \|", rep, re.M) is not None,
   "the next done replaces the earlier row's `this commit` with that commit's SHA")
ok(ts.resolve_history_commits("## Task history\n\n| T | S | t | 1 | this commit | x |\n", lambda n: None)
   == "## Task history\n\n| T | S | t | 1 | this commit | x |\n", "a row whose commit is not found stays as it was")
summary = ts.fill_summary("- **Start**: [start date]\n- **Status**: In progress | Completed | Blocked\n", "2026-11-12")
ok(summary == "- **Start**: 2026-11-12\n- **Status**: In progress\n"
   and ts.fill_summary("- **Start**: 2026-01-01\n", "2026-11-12") == "- **Start**: 2026-01-01\n",
   "done fills the Summary's Start / Status placeholders once and keeps a written value")

print("done — manual tick, zero tests, untrusted tests")
rc, out = task(d, "next")
(d / "farewell.py").write_text("x = 1\n", encoding="utf-8")
p = read(d, "telesma/state/PLAN.md").replace("- [ ] Task 1.2:", "- [x] Task 1.2:")
(d / "telesma" / "state" / "PLAN.md").write_text(p, encoding="utf-8")
rc, out = task(d, "done")
ok(rc == 1 and "already ticked" in out, "a task ticked by hand is refused — only done ticks")

d2 = project(test_cmd="echo 'collected 0 items'")
task(d2, "next")
(d2 / "greet.py").write_text("x = 1\n", encoding="utf-8")
rc, out = task(d2, "done")
ok(rc == 1 and "0 executed tests" in out, "a run with 0 tests is a failure, not a pass")

d3 = project(trusted=False)
task(d3, "next")
(d3 / "greet.py").write_text("x = 1\n", encoding="utf-8")
rc, out = task(d3, "done")
ok(rc == 1 and "not confirmed on this machine" in out, "## Tests not confirmed here: its commands are not run")


def set_field(d, label, value):
    c = d / "telesma" / "config.md"
    text, n = re.subn(r"(?m)^- \*\*" + re.escape(label) + r"\*\*:.*$", f"- **{label}**: {value}",
                      c.read_text(encoding="utf-8"))
    assert n == 1, label
    c.write_text(text, encoding="utf-8")


def record_file(d):
    old = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = XDG
    path = trust.record_path(str(d))
    if old is None:
        del os.environ["XDG_CONFIG_HOME"]
    else:
        os.environ["XDG_CONFIG_HOME"] = old
    return Path(path)


# Specky, 2026-11-13: a reserved task the model parked with ⛔ was handed out again until the
# attempts limit — the reservation must yield to the marker
d9 = project(plan="# Plan\n\n## Tasks\n\n### Phase 1: Start\n\n- [ ] Task 1.1: Measure on live traffic\n"
                  "- [ ] Task 1.2: Edge proxy\n")
rc, out = task(d9, "next")
ok("Task 1.1" in out, "next reserves 1.1")
pl = d9 / "telesma" / "state" / "PLAN.md"
pl.write_text(pl.read_text(encoding="utf-8").replace("- [ ] Task 1.1:", "- [ ] ⛔ Task 1.1:"), encoding="utf-8")
rc, out = task(d9, "next")
ok(rc == 0 and "Released" in out and "TELESMA NEXT: Task 1.2" in out,
   "a reserved task marked ⛔ is released and the scan hands out the next one")
rc, out = task(d9, "next")
ok("TELESMA NEXT: Task 1.2" in out and "Released" not in out, "the new reservation holds")

# 1.4.1: the first task of a new project sets the linter — the unchanged test command still runs
d5 = project()
task(d5, "next")
(d5 / "greet.py").write_text("x = 1\n", encoding="utf-8")
set_field(d5, "Linter/formatter", "false")
set_field(d5, "Lint before commit", "yes")
rc, out = task(d5, "done")
ok(rc == 0 and "committed" in out and "Linter/formatter `false` not run until the person confirms" in out,
   "## Tests waiting for the person: a new linter is not run, the confirmed test command is — done commits")
ok("not run until confirmed: Linter/formatter" in (d5 / "telesma" / "state" / "REPORT.md").read_text(encoding="utf-8"),
   "the Task history row says which command waits for the person")
rc, out = task(d5, "suite", "--full")
ok("not confirmed" not in out and "is not the one confirmed" not in out,
   "suite runs the full suite command the person confirmed while ## Tests waits")

d6 = project()
task(d6, "next")
(d6 / "greet.py").write_text("x = 1\n", encoding="utf-8")
set_field(d6, "Test command", "true")
rc, out = task(d6, "done")
ok(rc == 1 and "changed from a value confirmed" in out, "a confirmed test command the agent changed refuses")
ok("Test command `" in out and "→ `true`" in out and f"telesma.sh {os.path.realpath(d6)}" in out and "/exit" in out,
   "the refusal names the changed field and the exact start that confirms it")
set_field(d6, "Test command", "none")
rc, out = task(d6, "done")
ok(rc == 1 and "changed from a value confirmed" in out, "a confirmed test command set to none refuses")

d7 = project(**{"Linter/formatter": "true", "Lint before commit": "yes"})
task(d7, "next")
(d7 / "greet.py").write_text("x = 1\n", encoding="utf-8")
set_field(d7, "Lint before commit", "no")
rc, out = task(d7, "done")
ok(rc == 1 and "Lint before commit was switched off" in out, "switching off a confirmed lint-at-commit refuses")

d8 = project()
rec = record_file(d8)
body = json.loads(rec.read_text(encoding="utf-8"))
body.pop("values", None)
rec.write_text(json.dumps(body), encoding="utf-8")
task(d8, "next")
(d8 / "greet.py").write_text("x = 1\n", encoding="utf-8")
set_field(d8, "Linter/formatter", "false")
rc, out = task(d8, "done")
ok(rc == 1 and "not confirmed on this machine" in out,
   "a record from before 1.4.1 (no values) with a changed ## Tests refuses as before")
set_field(d8, "Linter/formatter", "none")
os.environ["XDG_CONFIG_HOME"] = XDG
trust.main(["trust.py", "check", str(d8)])
del os.environ["XDG_CONFIG_HOME"]
ok((json.loads(rec.read_text(encoding="utf-8")).get("values") or {}).get("Tests", {}).get("Test command")
   == "python3 -m unittest discover -s tests -q",
   "the launcher's check records the values of a ## Tests whose hash still matches (old record backfilled)")

d4 = project(**{"Auto-commit": "no"})
task(d4, "next")
(d4 / "greet.py").write_text("x = 1\n", encoding="utf-8")
rc, out = task(d4, "done")
ok(rc == 0 and "nothing committed" in out and sh(d4, "git", "rev-list", "--count", "HEAD").stdout.strip() == "1",
   "Auto-commit: no — ticked, nothing committed")

print("next — terminal states")
d5 = project(plan="# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [x] Task 1.1: done\n")
rc, out = task(d5, "next")
ok(out.startswith("TELESMA COMPLETE"), "no unchecked item → TELESMA COMPLETE")
d6 = project(plan="# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [ ] Task 1.1: x (tech: elixir)\n")
rc, out = task(d6, "next")
ok(out.startswith("TELESMA BLOCKED") and "elixir" in out and (d6 / "telesma/state/BLOCKED.md").is_file(),
   "a missing guideline → TELESMA BLOCKED with the question, written to BLOCKED.md")
rc, out = task(d6, "next")
ok("Resolve this first" in out, "while BLOCKED.md exists next does not issue a task")
d7 = project(plan="# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [ ] Task 1.1: a (requires: 2.1)\n\n"
                  "### Phase 2: B\n\n- [ ] Task 2.1: b\n", **{"Active phases": "1"})
rc, out = task(d7, "next")
ok(out.startswith("TELESMA BLOCKED") and "not active" in out, "a dependency in an inactive phase → BLOCKED with the reason")
d8 = project()
(d8 / "telesma" / "changes").mkdir()
(d8 / "telesma" / "changes" / "new-field.md").write_text("---\npriority: normal\n---\nAdd a field.\n", encoding="utf-8")
rc, out = task(d8, "next")
ok(out.startswith("TELESMA CHANGES PENDING: new-field.md"), "pending change files come before the next task")

print("commit --kind")
rc, out = task(d8, "commit", "--kind", "feature", "-m", "x")
ok(rc == 1 and "--kind is one of" in out, "an unknown kind is refused")
(d8 / "telesma" / "changes" / "processed").mkdir()
os.replace(d8 / "telesma/changes/new-field.md", d8 / "telesma/changes/processed/new-field.md")
rc, out = task(d8, "commit", "--kind", "changes", "-m", "process new-field.md")
ok(rc == 0 and head_message(d8).startswith("Telesma: changes: process new-field.md"),
   "commit --kind changes commits with its own subject")
rc, out = task(d8, "done", "--trailer", "Co-Authored-By: someone")
ok(rc == 1 and "footer is only" in out, "a model attribution trailer is refused")

print("checks — exactly the committed files, evidence")
d9 = project(checks=True)
task(d9, "next")
key = "AKIA" + "ZQ3K7WRT2X9PLM4Q"
(d9 / "greet.py").write_text(f"KEY = '{key}'\n", encoding="utf-8")
rc, out = task(d9, "done")
ok(rc == 1 and "quality checks refused" in out and key not in out, "a secret in the work refuses done, never printed")
ok("- [ ] Task 1.1:" in read(d9, "telesma/state/PLAN.md"), "the tick is undone after the refusal")
(d9 / "greet.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
rc, out = task(d9, "done")
head = sh(d9, "git", "rev-parse", "HEAD").stdout.strip()
ok(rc == 0 and (d9 / ".git" / "telesma-checks" / f"{head}.json").is_file(),
   "the commit gets its check evidence — no after-the-fact re-check")
seen = (d9 / ".git" / "telesma-checks" / "seen-head").read_text(encoding="utf-8").strip()
ok(seen == head, "HEAD is marked as seen")

print("suite — end of a phase (Z3)")
ONE = "# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [ ] Task 1.1: a\n\n### Phase 2: B\n\n- [ ] Task 2.1: b (requires: 1.1)\n"
e = project(plan=ONE)
task(e, "next")
(e / "a.py").write_text("A = 1\n", encoding="utf-8")
rc, out = task(e, "done")
ok(rc == 0 and "Phase 1 is complete" in out and " suite" in out, "done on the last task of a phase asks for the suite")
rc, out = task(e, "next")
ok(out.startswith("TELESMA SUITE DUE"), "next issues no task while the suite is due")
rc, out = task(e, "suite")
rep = read(e, "telesma/state/REPORT.md")
ok(rc == 0 and re.search(r"^\*\*Regression after Phase 1 \(\d{4}-\d\d-\d\d\) — GREEN:\*\* .*Tag `telesma/phase-1`", rep, re.M)
   is not None, "a green suite writes the dated Test status paragraph")
ok("| Total tests | 1 |" in rep and "| Fail | 0 |" in rep, "the metrics table is overwritten with the numbers")
ok(sh(e, "git", "tag", "-l", "telesma/phase-1").stdout.strip() == "telesma/phase-1", "the phase tag is placed")
ok(sh(e, "git", "status", "--porcelain").stdout.strip() == "", "the paragraph is committed — the tree is clean")
rc, out = task(e, "next")
ok(out.startswith("TELESMA NEXT: Task 2.1"), "then next moves on")

e2 = project(plan=ONE)
task(e2, "next")
(e2 / "a.py").write_text("A = 1\n", encoding="utf-8")
task(e2, "done")
(e2 / "tests" / "test_late.py").write_text("import unittest\n\nclass L(unittest.TestCase):\n"
                                          "    def test_no(self):\n        self.fail('broken later')\n", encoding="utf-8")
rc, out = task(e2, "suite")
ok("— RED:**" in read(e2, "telesma/state/REPORT.md") and "TELESMA REGRESSION" in out
   and not sh(e2, "git", "tag", "-l", "telesma/phase-1").stdout.strip(), "a red suite: RED paragraph, no tag")
rc, out = task(e2, "next")
ok(out.startswith("TELESMA REGRESSION") and "broken later" in out, "next issues the regression, not a new task")
(e2 / "tests" / "test_late.py").unlink()
rc, out = task(e2, "commit", "--kind", "regression", "-m", "remove the broken test")
ok(rc == 0 and "suite" in out, "the regression fix is committed and points at the suite")
rc, out = task(e2, "suite")
ok(rc == 0 and sh(e2, "git", "tag", "-l", "telesma/phase-1").stdout.strip() == "telesma/phase-1",
   "green again: the phase is tagged")

e3 = project(plan=ONE)
r3 = read(e3, "telesma/state/REPORT.md").replace("## Test status\n", "## Test status\n\n**Baseline at adoption "
     "(2026-11-01) — RED (exit 1):** `x` — 2 tests: 1 passed, 1 failed, 0 skipped\n", 1)
(e3 / "telesma/state/REPORT.md").write_text(r3, encoding="utf-8")
(e3 / "tests" / "test_old.py").write_text("import unittest\n\nclass O(unittest.TestCase):\n"
                                         "    def test_old(self):\n        self.fail('inherited')\n", encoding="utf-8")
sh(e3, "git", "add", "-A"); sh(e3, "git", "commit", "-q", "-m", "baseline")
os.makedirs(e3 / ".git" / "telesma-task", exist_ok=True)
(e3 / ".git" / "telesma-task" / "session.json").write_text(json.dumps({"suite_due": {"reason": "Phase 1", "phase": "1"}}))
(e3 / "telesma/config.md").write_text(read(e3, "telesma/config.md").replace(
    "- **Full suite command**: python3 -m unittest discover -s tests -q",
    "- **Full suite command**: python3 -m unittest discover -s tests"), encoding="utf-8")
restamp(e3)
rc, out = task(e3, "suite")
ok("RED (inherited failures only)" in out and "TELESMA REGRESSION" not in out,
   "adopted project: no more failures than the baseline is not a regression")

print("changes / changes-done (Z4)")
c = project(plan=ONE)
(c / "telesma/state/PROJECT_CONTEXT.md").write_text("## Key decisions\n\n| Date | Decision | Reason |\n|--|--|--|\n"
    "| 2026-10-01 | Exports stay as plain spreadsheet files, never encrypted | owner 📌 |\n", encoding="utf-8")
(c / "telesma" / "changes").mkdir()
(c / "telesma/changes/b-export.md").write_text("---\npriority: normal\n---\n# Encrypted spreadsheet exports\n"
    "Exports must be encrypted spreadsheet files.\n", encoding="utf-8")
(c / "telesma/changes/a-crit.md").write_text("---\npriority: critical\naffects: api.md:5-7\n---\nFix greeting.\n",
                                            encoding="utf-8")
sh(c, "git", "add", "-A"); sh(c, "git", "commit", "-q", "-m", "requests")
rc, out = task(c, "next")
ok(out.startswith("TELESMA CHANGES PENDING: a-crit.md, b-export.md"), "critical first in the pending list")
rc, out = task(c, "changes")
ok(out.startswith("TELESMA CHANGE: telesma/changes/a-crit.md") and "## Greeting" in out,
   "changes issues the critical one with the spec lines it affects")
plan_c = read(c, "telesma/state/PLAN.md")
(c / "telesma/state/PLAN.md").write_text(plan_c.replace("- [ ] Task 2.1: b (requires: 1.1)",
    "- [ ] Task 2.1: b, greeting fixed (requires: 1.1)"), encoding="utf-8")
rc, out = task(c, "changes-done", "a-crit.md", "--kind", "bug", "-m", "greeting fixed")
ok(rc == 1 and "--source" in out, "a bug needs its source")
rc, out = task(c, "changes-done", "a-crit.md", "--kind", "bug", "--source", "1.1", "--detected-by", "owner", "-m", "x")
ok(rc == 1 and "without `(change: a-crit.md)`: 2.1" in out, "a changed task without the (change:) tag is refused")
(c / "telesma/state/PLAN.md").write_text(plan_c.replace("- [ ] Task 1.1: a", "- [x] Task 1.1: a"), encoding="utf-8")
rc, out = task(c, "changes-done", "a-crit.md", "--kind", "feature", "-m", "x")
ok(rc == 1 and "checkbox changed state" in out, "a change that ticks a task is refused")
(c / "telesma/state/PLAN.md").write_text(plan_c.replace("- [ ] Task 2.1: b (requires: 1.1)",
    "- [ ] Task 2.1: b, greeting fixed (requires: 1.1) (change: a-crit.md)\n- [ ] Task 2.2: new (requires: 9.9) (change: a-crit.md)"),
    encoding="utf-8")
rc, out = task(c, "changes-done", "a-crit.md", "--kind", "bug", "--source", "1.1", "--detected-by", "owner", "-m", "x")
ok(rc == 1 and "9.9" in out, "a dependency that does not exist is refused")
(c / "telesma/state/PLAN.md").write_text(plan_c.replace("- [ ] Task 2.1: b (requires: 1.1)",
    "- [ ] Task 2.1: b, greeting fixed (requires: 1.1) (change: a-crit.md)\n- [ ] Task 2.2: new (requires: 2.1) (change: a-crit.md)"),
    encoding="utf-8")
rc, out = task(c, "changes-done", "a-crit.md", "--kind", "bug", "--source", "1.1", "--detected-by", "owner",
               "-m", "The greeting was wrong.")
rep = read(c, "telesma/state/REPORT.md")
ok(rc == 0 and "- **Kind**: bug\n- **Bug source**: 1.1\n- **Detected by**: owner\n- **Priority**: critical" in rep
   and "- **Modified pending tasks**: 2.1" in rep and "- **New tasks**: 2.2" in rep,
   "the Change history entry is written by the script, task lists computed from the plan")
ok((c / "telesma/changes/processed/a-crit.md").is_file() and not (c / "telesma/changes/a-crit.md").exists()
   and head_message(c).startswith("Telesma: changes: process a-crit.md"), "the file is moved and committed")
ok("Next:" in out and "changes" in out, "the next request is pointed at")
rc, out = task(c, "changes")
ok(out.startswith("TELESMA CHANGE: telesma/changes/b-export.md")
   and "PROJECT_CONTEXT.md:5: | 2026-10-01 | Exports stay as plain spreadsheet files" in out,
   "an earlier decision on the topic is quoted verbatim with its file and line")
rc, out = task(c, "changes-done", "b-export.md", "--kind", "feature", "--withdrawn", "-m", "contradicts 2026-10-01")
ok(rc == 0 and "- **Summary**: withdrawn — contradicts 2026-10-01" in read(c, "telesma/state/REPORT.md"),
   "a withdrawn request: entry says so, plan untouched")
rc, out = task(c, "next")
ok(out.startswith("TELESMA SUITE DUE (a-crit.md)"), "after a processed change the full suite is due")

print("session budget (K2)")
TWO = "# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [ ] Task 1.1: a\n- [ ] Task 1.2: b\n- [ ] Task 1.3: c\n"
k = project(plan=TWO, **{"Max tasks per session": "1"})
rc, out = task(k, "session-start")
ok(rc == 0, "session-start takes the limits")
task(k, "next")
(k / "a.py").write_text("A = 1\n", encoding="utf-8")
task(k, "done")
rc, out = task(k, "next")
ok(out.startswith("TELESMA BLOCKED") and "Budget: Max tasks per session" in read(k, "telesma/state/BLOCKED.md"),
   "the session's task limit: next hands out nothing, BLOCKED.md written by the script")
rc, out = task(k, "next")
ok("budget is used up" in out, "and keeps saying so")
rc, out = task(k, "session-start")
ok(rc == 3 and out.startswith("exhausted: Max tasks per session"), "the next start learns it (exit 3)")
rc, out = task(k, "session-start", "--continue")
ok(rc == 0 and not (k / "telesma/state/BLOCKED.md").exists(), "the person's yes clears the budget block")
rc, out = task(k, "next")
ok(out.startswith("TELESMA NEXT: Task 1.2"), "and the loop goes on, counters from zero")

k2 = project(plan=TWO, **{"Max attempts per task": "2"})
task(k2, "session-start")
task(k2, "next"); task(k2, "next"); task(k2, "next")
rc, out = task(k2, "next")
ok(out.startswith("TELESMA NEXT: Task 1.1") and "Budget:" not in out,
   "next run again only to read the task (no tool calls since) is not a new attempt")


def worked(p, calls=40):
    f = p / ".git/telesma-task/session.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["calls_since_next"] = calls
    f.write_text(json.dumps(d), encoding="utf-8")


worked(k2); task(k2, "next"); worked(k2)
rc, out = task(k2, "next")
ok("Budget: Max attempts per task" in out, "the same task handed out a third time after work, with a limit of 2 → stop")

k3 = project(plan=TWO, **{"Max refusals per task": "2"})
task(k3, "session-start")
task(k3, "next")
(k3 / "tests" / "test_red.py").write_text("import unittest\n\nclass R(unittest.TestCase):\n"
                                         "    def test_r(self):\n        self.fail('no')\n", encoding="utf-8")
task(k3, "done")
rc, out = task(k3, "done")
ok(rc == 1 and "Budget: Max refusals per task" in out
   and json.loads((k3 / ".git/telesma-task/session.json").read_text())["exhausted"]["reason"] == "Max refusals per task",
   "the second refused done with a limit of 2 → the session is stopped")
k4 = project(plan=TWO, **{"Max hours per session": "0.0001"})
task(k4, "session-start")
import time; time.sleep(1)
rc, out = task(k4, "next")
ok("Budget: Max hours per session" in out, "the session's hour limit")

print("usage record (K13)")


def transcript(d, name, rows):
    folder = CLAUDE_DIR / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(d))
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def reply(ts_, mid, model="claude-opus-5-5", out=100, read=1000):
    u = {"input_tokens": 3, "output_tokens": out, "cache_read_input_tokens": read, "cache_creation_input_tokens": 50}
    return [{"type": "assistant", "timestamp": ts_, "requestId": "r" + mid, "version": "2.1.323",
             "message": {"id": mid, "model": model, "content": [{"type": "text", "text": "x"}], "usage": u}},
            {"type": "assistant", "timestamp": ts_, "requestId": "r" + mid, "version": "2.1.323",
             "message": {"id": mid, "model": model, "content": [{"type": "tool_use", "name": "Read"}], "usage": u}}]


def utcnow(shift=0):
    return tu.iso(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=shift))


record = lambda d: d / ".git" / "telesma-usage" / "usage.jsonl"  # noqa: E731
u = project()
session_since = utcnow(-5)
transcript(u, "s1.jsonl", reply(utcnow(-3600), "old"))           # before next: not the task's
task(u, "next")
transcript(u, "s1.jsonl", reply(utcnow(), "m1") + reply(utcnow(), "m2", model="claude-haiku-5-5", out=10, read=0))
transcript(u, "s1/subagents/agent-a.jsonl", reply(utcnow(), "s1", model="claude-haiku-5-5", out=20, read=0))
(u / "greet.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
rc, out = task(u, "done")
rows = [json.loads(x) for x in record(u).read_text(encoding="utf-8").splitlines()] if record(u).exists() else []
row = rows[0] if rows else {}
models = (row.get("usage") or {}).get("models", {})
ok(rc == 0 and len(rows) == 1 and row["type"] == "task" and row["task"] == "1.1" and row["phase"] == "1",
   "done writes one task row into .git/telesma-usage/usage.jsonl")
ok(models.get("claude-opus-5-5", {}).get("output") == 100 and models.get("claude-haiku-5-5", {}).get("output") == 30,
   "the row: one response split over two lines counted once, the subagent added, the earlier response left out, "
   "two models apart")
ok(row.get("commit") and sh(u, "git", "rev-parse", "HEAD").stdout.startswith(row["commit"])
   and row.get("attempts") == 1 and row.get("diff", {}).get("files", 0) >= 1 and row["usage"]["versions"] == ["2.1.323"],
   "with the commit, the attempts, the diff and the Claude Code version")
ok(sh(u, "git", "status", "--porcelain").stdout.strip() == "", "the record is not in the work tree (nothing to commit)")
task(u, "next")
(u / "tests" / "test_red.py").write_text("import unittest\n\nclass R(unittest.TestCase):\n"
                                         "    def test_r(self):\n        self.fail('no')\n", encoding="utf-8")
before = record(u).read_bytes()
rc, out = task(u, "done")
ok(rc == 1 and record(u).read_bytes() == before, "a refused done leaves the record byte for byte as it was")
r = subprocess.run([sys.executable, str(TELESMA / "tools" / "telesma_usage.py"), "session", "--since", session_since,
                    "--mode", "1", "--project", str(u)], env=ENV, capture_output=True, text=True)
rows = [json.loads(x) for x in record(u).read_text(encoding="utf-8").splitlines()]
ok(r.returncode == 0 and r.stdout.split("\t")[0] == "1" and rows[-1]["type"] == "session" and rows[-1]["tasks"] == 1
   and rows[-1]["in_tasks"]["output"] == 130, f"the launcher's session row counts the task in it ({r.stdout.strip()})")
r = subprocess.run([sys.executable, str(TELESMA / "tools" / "telesma_usage.py"), "report", str(u)], env=ENV,
                   capture_output=True, text=True)
ok("Tasks finished: 1" in r.stdout and "By phase" in r.stdout and "Most tokens" in r.stdout
   and "claude-opus-5-5" in r.stdout, "telesma.sh --usage: the summary")
ok("Context per step: 386 tokens read per response, over 3 steps; largest single step 1.1k" in r.stdout
   and "ctx/step" in r.stdout and "Largest context per step" in r.stdout,
   "… with the context per step (K14): the input side of every response over the number of responses")
r = subprocess.run([sys.executable, str(TELESMA / "tools" / "telesma_usage.py"), "report", str(u), "--csv"], env=ENV,
                   capture_output=True, text=True)
ok(r.stdout.startswith("type,from,to,task") and len(r.stdout.strip().splitlines()) == 3, "--csv: a header and every row")
ok(r.stdout.splitlines()[0].endswith("context_per_step,peak_context") and r.stdout.splitlines()[1].endswith(",386,1053"),
   "--csv: the context per step and the largest step of each row")
k5 = project(plan=TWO, **{"Max tokens per session": "1k"})
task(k5, "session-start")
transcript(k5, "s.jsonl", reply(utcnow(), "big", out=900, read=900))
rc, out = task(k5, "next")
ok("Budget: Max tokens per session" in out, "the session's token limit (1k)")
n = project()
task(n, "next")
(n / "greet.py").write_text("x = 1\n", encoding="utf-8")
rc, out = task(n, "done")
rows = [json.loads(x) for x in record(n).read_text(encoding="utf-8").splitlines()] if record(n).exists() else []
ok(rc == 0 and rows and rows[0]["usage"] is None and "no transcripts" in rows[0].get("note", ""),
   "no transcripts on this machine: the task is committed, the row says why it has no numbers")
w = project(plan=TWO)
transcript(w, "s.jsonl", reply(utcnow(), "a"))
task(w, "next")
(w / "a.py").write_text("A = 1\n", encoding="utf-8")
task(w, "done")
time.sleep(1.1)
transcript(w, "s.jsonl", reply(utcnow(), "b"))                  # the work, before next
time.sleep(1.1)
task(w, "next")
transcript(w, "s.jsonl", reply(utcnow(), "c"))                  # the call of done
(w / "b.py").write_text("B = 1\n", encoding="utf-8")
task(w, "done")
rows = [json.loads(x) for x in record(w).read_text(encoding="utf-8").splitlines()]
ok(len(rows) == 2 and rows[1]["from"] == rows[0]["to"] and rows[1]["issued"] > rows[1]["from"]
   and tu.sums(rows[1]["usage"])["output"] == 200,
   "work done before next counts for the task: in one session the window opens where the previous task ended")
old = dict(rows[1], usage={"models": {}, "turns": 0}, task="Test: 1.2 — the test of b")
old["from"] = old.pop("issued")
record(w).write_text(json.dumps(rows[0]) + "\n" + json.dumps(old) + "\n", encoding="utf-8")
r = subprocess.run([sys.executable, str(TELESMA / "tools" / "telesma_usage.py"), "rebuild", str(w)], env=ENV,
                   capture_output=True, text=True)
rows = [json.loads(x) for x in record(w).read_text(encoding="utf-8").splitlines()]
ok(r.returncode == 0 and tu.sums(rows[1]["usage"])["output"] == 200 and rows[1]["task"] == "1.2/test"
   and "wall_minutes" in rows[1], f"rebuild recounts an old row from the transcripts ({r.stdout.strip()})")
t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
ok(tu.active_seconds([t0 + datetime.timedelta(seconds=s) for s in (0, 30, 30 + 7200, 30 + 7200 + 30)]) == 60,
   "working time leaves a two-hour pause out")
ok([tu.task_label(x) for x in ("1.1", "Test: 14.3 — Vitest: x", "Task 2.4: y", "Phase 3 notes")]
   == ["1.1", "14.3/test", "2.4", "Phase 3 notes"], "short task names in the record")
shutil.rmtree(w, ignore_errors=True)

print("release (Z6)")
r = project(plan="# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [x] Task 1.1: a\n")
rc, out = task(r, "release", "v1.0.0", "-m", "First version.")
ok(rc == 1 and "test-scenarios/v1.0.0.md is not committed" in out, "no scenarios file → refused")
(r / "docs" / "test-scenarios").mkdir(parents=True)
(r / "docs/test-scenarios/v1.0.0.md").write_text("# Scenarios v1.0.0\n", encoding="utf-8")
rc, out = task(r, "release", "v1.0.0", "-m", "First version.")
ok(rc == 1 and "not clean" in out, "a dirty tree → refused")
task(r, "commit", "--kind", "release", "-m", "test scenarios for v1.0.0")
rc, out = task(r, "release", "v1.0.0", "-m", "First version.")
ok(rc == 1 and "no green full suite" in out, "no green suite on record → refused")
rc, out = task(r, "suite", "--full")
ok(rc == 0 and "GREEN" in out, "suite --full on request")
(r / "late.py").write_text("x = 1\n", encoding="utf-8")
task(r, "commit", "--kind", "bugfix", "-m", "late fix")
rc, out = task(r, "release", "v1.0.0", "-m", "First version.")
ok(rc == 1 and "code changed since the last green" in out and "late.py" in out, "code after the green suite → refused")
task(r, "suite", "--full")
(r / "telesma/state/DECISIONS.md").write_text("# Decisions\n", encoding="utf-8")
task(r, "commit", "--kind", "release", "-m", "notes")
rc, out = task(r, "release", "v1.0.0", "-m", "First version.")
tagtype = sh(r, "git", "cat-file", "-t", "v1.0.0", check=False).stdout.strip()
ok(rc == 0 and tagtype == "tag" and "git push origin v1.0.0" in out,
   "only state notes since the green suite → the annotated tag, and the push command for the person")
rc, out = task(r, "release", "v1.0.0", "-m", "Again.")
ok(rc == 1 and "exists already" in out, "an existing version → refused, never -f")
rc, out = task(r, "release", "1.0.1", "-m", "x")
ok(rc == 1 and "vX.Y.Z" in out, "a name that is not vX.Y.Z → refused")

print("e2e the session cannot run (K12)")
w2 = project()
task(w2, "next")
(w2 / "greet.py").write_text("x = 1\n", encoding="utf-8")
rc, out = task(w2, "done", "--e2e-not-run", "e2e/flow.spec.ts")
ok(rc == 1 and "no such file" in out, "--e2e-not-run names a written test file, or done refuses")
(w2 / "e2e").mkdir()
(w2 / "e2e" / "flow.spec.ts").write_text("test('flow', () => {})\n", encoding="utf-8")
rc, out = task(w2, "done", "--e2e-not-run", "e2e/flow.spec.ts")
ok(rc == 0 and "committed" in out and "e2e waiting for the person" in out,
   "the task is committed on its other tests; its e2e file waits for the person")
ok("e2e not run in session: e2e/flow.spec.ts" in read(w2, "telesma/state/REPORT.md"),
   "the Task history row says which e2e did not run")
rc, out = task(w2, "suite", "--full")
ok(rc == 0 and "E2E WAITING FOR THE PERSON (1)" in out and "e2e-ran" in out, "suite lists what waits, and how to clear it")
(w2 / "docs" / "test-scenarios").mkdir(parents=True)
(w2 / "docs/test-scenarios/v0.1.0.md").write_text("# Scenarios v0.1.0\n", encoding="utf-8")
task(w2, "commit", "--kind", "release", "-m", "scenarios")
rc, out = task(w2, "release", "v0.1.0", "-m", "First.")
ok(rc == 1 and "never run in a session" in out and "e2e/flow.spec.ts" in out,
   "release refuses while an e2e test waits")
rc, out = task(w2, "e2e-ran")
ok(rc == 1 and "terminal" in out, "e2e-ran without a terminal is refused (the agent cannot clear the list)")
rc, out = task(w2, "next", "--e2e-not-run", "e2e/flow.spec.ts")
ok(rc == 1 and "belongs to done" in out, "--e2e-not-run is an option of done only")
shutil.rmtree(w2, ignore_errors=True)

print("next — a task citing the clarification's answers (QUESTIONS.md)")
q = project(plan=PLAN.replace("(spec: api.md Greeting)", "(spec: QUESTIONS.md Q15, Q19, api.md Greeting)"))
(q / "telesma" / "state" / "QUESTIONS.md").write_text(
    "# Clarification\n\n## Questions\n\n### Q15: Objects in the world?\n- **Answer**: yes, with labels\n"
    "- **Status**: ✅\n\n### Q16: Unrelated\n- **Answer**: canary-other\n\n### Q19: Snapshot?\n"
    "- **Answer**: includes objects\n", encoding="utf-8")
rc, out = task(q, "next")
ok(rc == 0 and out.startswith("TELESMA NEXT: Task 1.1"), "(spec: QUESTIONS.md Q15, Q19) does not block next")
ok("yes, with labels" in out and "includes objects" in out and "canary-other" not in out,
   "the cited entries are printed, the others are not")
ok("The greet function says hello." in out, "a spec file in the same tag is still given")
ok(ts.question_ids("QUESTIONS.md Q15") == ["Q15"] and ts.question_ids("Q19") == ["Q19"]
   and ts.question_ids("api.md Q1") is None and ts.question_ids("Quality.md") is None,
   "only QUESTIONS.md and bare S/A/Q ids are read as clarification entries")
q2 = project(plan=PLAN.replace("(spec: api.md Greeting)", "(spec: Q7)"))
rc, out = task(q2, "next")
ok(rc == 0 and "not in this project" in out, "no QUESTIONS.md → a note, never a refusal")
q3 = project(plan=PLAN.replace("(spec: api.md Greeting)", "(spec: missing.md)"))
rc, out = task(q3, "next")
ok("no file missing.md" in out, "a spec file that does not exist is still refused")
for x in (q, q2, q3):
    shutil.rmtree(x, ignore_errors=True)

print("done — the independent review (## Review)")
import http.server  # noqa: E402
import threading  # noqa: E402

REVIEW = {"status": 200, "answer": "", "seen": [], "prompt_tokens": 1200}


class FakeReviewer(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
        REVIEW["seen"].append({"auth": self.headers.get("Authorization"), "body": body})
        data = json.dumps({"choices": [{"message": {"content": REVIEW["answer"]}}],
                           "usage": {"prompt_tokens": REVIEW["prompt_tokens"], "completion_tokens": 80,
                                     "total_tokens": REVIEW["prompt_tokens"] + 80}}).encode()
        self.send_response(REVIEW["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeReviewer)
threading.Thread(target=server.serve_forever, daemon=True).start()
ENDPOINT = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"


def review_field(d, label, value):
    p = d / "telesma" / "config.md"
    head, sep, rest = p.read_text(encoding="utf-8").partition("\n## Review\n")
    assert sep
    rest, n = re.subn(r"^- \*\*" + re.escape(label) + r"\*\*:.*$", f"- **{label}**: {value}", rest, count=1, flags=re.M)
    assert n == 1, label
    p.write_text(head + sep + rest, encoding="utf-8")


def verdict(*findings, paraphrase="Adds a function and its test.", entry="module function"):
    return json.dumps({"paraphrase": paraphrase, "entry": entry, "findings": [
        {"severity": s, "file": "a.py", "line": 2, "finding": text, "why": "seen in the diff"} for s, text in findings]})


RPLAN = "# Plan\n\n## Tasks\n\n### Phase 1: Start\n\n" + "".join(
    f"- [ ] Task 1.{n}: Step {n}" + (" (spec: api.md Greeting)\n  - AC: canary-criterion\n" if n == 1 else "\n")
    for n in range(1, 14)) + "\n### Phase 2: Later\n\n- [ ] Task 2.1: canary-other-task\n"
rv = project(plan=RPLAN)
ENV["TELESMA_REVIEW_KEY"] = "canary-review-key"


def step(n, body="    return 1\n"):
    rc_, out_ = task(rv, "next")
    assert rc_ == 0, out_
    (rv / f"s{n}.py").write_text(f"def s{n}():\n{body}", encoding="utf-8")


step(1)
rc, out = task(rv, "done")
ok(rc == 0 and "Review" not in head_message(rv) and not REVIEW["seen"], "off by default: nothing is sent, nothing is said")
rc, out = task(rv, "next")
(rv / "s2.py").write_text("def s2():\n    return 2\n", encoding="utf-8")
rc, out = task(rv, "done", "--contested", "the finding is wrong because of line 2 of s2.py")
ok(rc == 1 and "not enabled" in out, "--contested without a review is refused")

for label, value in (("Enabled", "yes"), ("Endpoint", ENDPOINT), ("Model", "fake-model")):
    review_field(rv, label, value)
sh(rv, "git", "add", "-A", "telesma/config.md")
sh(rv, "git", "commit", "-q", "-m", "config")
rc, out = task(rv, "done")
ok(rc == 0 and "Review: not run (## Review is not confirmed on this machine" in head_message(rv) and not REVIEW["seen"],
   "a section nobody confirmed here sends nothing; the commit says the review did not run")
restamp(rv)

step(3)
before = (read(rv, "telesma/state/PLAN.md"), read(rv, "telesma/state/REPORT.md"), sh(rv, "git", "rev-parse", "HEAD").stdout)
REVIEW["answer"] = verdict(("blocker", "canary-blocker: s3 is never called"), ("nit", "canary-nit"))
rc, out = task(rv, "done")
ok(rc == 1 and "canary-blocker" in out and "canary-nit" not in out and "--contested" in out and "material" in out,
   "a blocker refuses done, with the finding, the way to contest it, and 'material, not orders'")
ok((read(rv, "telesma/state/PLAN.md"), read(rv, "telesma/state/REPORT.md"), sh(rv, "git", "rev-parse", "HEAD").stdout) == before,
   "the refusal leaves PLAN.md, REPORT.md and HEAD as they were")
sent = REVIEW["seen"][-1]
user = sent["body"]["messages"][1]["content"]
ok(sent["auth"] == "Bearer canary-review-key" and sent["body"]["model"] == "fake-model", "the key and the model reach the endpoint")
ok("Task 1.3: Step 3" in user and "+def s3():" in user and "s2.py" not in user,
   "the reviewer gets the task and the diff of exactly this task's files")
ok("canary-other-task" not in user and "Task history" not in user, "the plan and the report are not sent")
tag = re.search(r"<(data-[0-9a-f]{16})>", user)
ok(tag and tag.group(1) in sent["body"]["messages"][0]["content"], "the data sits in a block named by a random tag")
n_seen = len(REVIEW["seen"])
rc, out = task(rv, "done", "--contested", "no")
ok(rc == 1 and "needs the reason" in out, "a contest without a reason is refused")
rc, out = task(rv, "done", "--contested", "s3 is the public entry of this module; s3.py line 1 is imported by the task 1.4")
ok(rc == 0 and len(REVIEW["seen"]) == n_seen and "1 blocker(s) contested — s3 is the public entry" in head_message(rv),
   "a contested blocker passes without a second call, and the reason is in the commit message")

step(4)
REVIEW["answer"] = verdict(("blocker", "canary-blocker-4"))
rc, out = task(rv, "done")
(rv / "s4.py").write_text("def s4():\n    return 44\n", encoding="utf-8")
rc, out = task(rv, "done", "--contested", "the reviewer misread s4.py line 2, it returns the value")
ok(rc == 1 and "changed since" in out, "a contest after the files changed is refused: the new diff is reviewed")
REVIEW["answer"] = "```json\n" + verdict(("major", "canary-major"), paraphrase="canary-paraphrase") + "\n```"
rc, out = task(rv, "done")
ok(rc == 0 and "Review (api:fake-model): passed — 0 blocker, 1 major, 0 nit" in head_message(rv)
   and "canary-major" in out and "canary-paraphrase" in out,
   "without a blocker the task is committed; the other findings and the paraphrase are printed")

step(5)
REVIEW["status"] = 500
rc, out = task(rv, "done")
ok(rc == 0 and "Review: not run (the reviewer answered HTTP 500" in head_message(rv) and "Review not run" in out,
   "a reviewer that fails is 'not run' — never a refusal, never a pass")
REVIEW["status"] = 200
step(6)
REVIEW["answer"] = "I think it looks fine."
rc, out = task(rv, "done")
ok(rc == 0 and "not run (the reviewer's answer could not be read)" in head_message(rv), "an answer that is not the JSON is 'not run'")
step(7)
REVIEW["answer"] = verdict()
ENV.pop("TELESMA_REVIEW_KEY")
rc, out = task(rv, "done")
ok(rc == 0 and "TELESMA_REVIEW_KEY is not set" in head_message(rv), "a key that cannot be read is 'not run', with the reason")
rows = [json.loads(x) for x in (rv / ".git" / "telesma-review" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()]
ok([x["outcome"] for x in rows] == ["not_run", "refused", "contested", "refused", "passed", "not_run", "not_run", "not_run"]
   and rows[4]["usage"]["total_tokens"] == 1280 and "canary-review-key" not in json.dumps(rows),
   "every review leaves a row in .git/telesma-review/reviews.jsonl, without the key")

print("done — the independent review by a model run locally")
ENV["TELESMA_REVIEW_KEY"] = "canary-review-key"
review_field(rv, "API key", "none")
review_field(rv, "Max diff", "2k")
sh(rv, "git", "add", "-A", "telesma/config.md")
sh(rv, "git", "commit", "-q", "-m", "config")
restamp(rv)
step(8)
REVIEW["answer"] = "<think>Is { this } fine? A blocker maybe.</think>\n" + verdict(("nit", "canary-local-nit"))
rc, out = task(rv, "done")
ok(rc == 0 and REVIEW["seen"][-1]["auth"] is None and "passed — 0 blocker, 0 major, 1 nit" in head_message(rv),
   "API key: none sends no Authorization header; a closed <think> block before the answer is dropped")
step(9)
REVIEW["answer"] = "<think>" + verdict(("blocker", "canary-thought"))
rc, out = task(rv, "done")
ok(rc == 0 and "could not be read" in head_message(rv), "an unclosed <think> block is no answer")
step(10, body="".join(f"    x{i} = {i}\n" for i in range(400)))
n_seen = len(REVIEW["seen"])
rc, out = task(rv, "done")
ok(rc == 0 and len(REVIEW["seen"]) == n_seen and "more than the 2000 of ## Review → Max diff" in head_message(rv),
   "a diff over Max diff is not sent")
review_field(rv, "Max diff", "240000")
sh(rv, "git", "add", "-A", "telesma/config.md")
sh(rv, "git", "commit", "-q", "-m", "config")
restamp(rv)
step(11, body="".join(f"    x{i} = {i}\n" for i in range(4000)))
REVIEW["answer"], REVIEW["prompt_tokens"] = verdict(), 2048
(rv / "bundle.min.js").write_text("var a=1;\n" + "canary-bundle;" * 400 + "\n", encoding="utf-8")
(rv / "s1.py").write_text("def s1():\n    return 1\n\n\ndef canary_untouched():\n    return 0\n\n\nX = 1\n", encoding="utf-8")
rc, out = task(rv, "done")
sent = json.dumps(REVIEW["seen"][-1]["body"])
ok("## s1.py (changed)" in sent and sent.count("canary_untouched") >= 2 and "## s11.py" not in sent,
   "a changed file goes to the reviewer in full after the diff; a new file is whole in the diff already")
ok("# Tests, as the script ran them before this review" in sent and "The Tests cell: Ran 1 test" in sent,
   "the reviewer is told what the tests said when the script ran them")
ok("canary-bundle" not in sent and "bundle.min.js" in sent and "generated or minified" in sent and "x3999 = 3999" in sent,
   "a built or minified file (a line over 2000 characters) is named in the diff, not sent")
ok(rc == 0 and "the reviewer read 2048 tokens of a prompt of" in head_message(rv) and "passed" not in head_message(rv),
   "a reviewer that read only its context window's worth of a longer prompt did not review")
REVIEW["prompt_tokens"] = 1200

import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("telesma_task_mod", str(TELESMA / "tools" / "telesma-task.py"))
_tt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tt)
import telesma_state as _ts  # noqa: E402
_plan = _ts.Plan("### Phase 1: A\n\n- [x] Task 1.1: Build it `a.py`\n  - AC: works\n- [ ] Test: 1.1 — canary-pair\n"
                 "- [ ] Task 1.2: Alone\n\n### Phase 2: B\n\n- [ ] Test: 2.1 — other phase\n")
SWIFT = ("Test Suite 'All tests' passed at 2026-11-21.\n\t Executed 0 tests, with 0 failures (0 unexpected) in 0.000 seconds\n"
         "\u2714 Test run with 11 tests in 3 suites passed after 0.012 seconds.\n")
ok(not _tt.zero_tests(SWIFT) and _tt.summary_of(SWIFT + SWIFT) == "22 tests passed"
   and _tt.zero_tests("\t Executed 0 tests, with 0 failures (0 unexpected) in 0.000 seconds\n")
   and _tt.zero_tests("Executed 0 tests, with 0 failures\n\u2714 Test run with 0 tests passed after 0.001 seconds.\n")
   and not _tt.zero_tests("\t Executed 4 tests, with 0 failures (0 unexpected) in 0.1 seconds\n"),
   "Swift: a Swift Testing run beside XCTest's empty harness is not 0 tests; an empty run of both still is")
ok("come in the next commit" in _tt.related_item(_plan, _plan.order[0]) and "canary-pair" in _tt.related_item(_plan, _plan.order[0])
   and "The task it covers" in _tt.related_item(_plan, _plan.order[1]) and "Build it" in _tt.related_item(_plan, _plan.order[1])
   and _tt.related_item(_plan, _plan.order[2]) == "" and _tt.related_item(_plan, _plan.order[3]) == "",
   "a Task and the Test: item after it are shown to the reviewer as a pair; an item alone has none")
_idx = _tt.spec_index_entries(
    "## Files\n\n### APP_FLOW.md (40 lines)\n| Lines | Section | Anchor | Description |\n|--|--|--|--|\n"
    "| 9-40 | Steps 1-3 | ## Step 1 | all steps |\n\n## Flows\n\n### telesma/spec/APP_FLOW.md (40 lines)\n"
    "| Lines | ID | Title | Actors | Main actions |\n|--|--|--|--|--|\n| 9-20 | step-1 | Start | User | x |\n")
_first = lambda e: next(r["cells"][1] for r in e[1]["rows"] if "start" in r)      # noqa: E731
ok(_first(_tt.find_entry(_idx, "telesma/spec/APP_FLOW.md", ui=True)) == "step-1"
   and _first(_tt.find_entry(_idx, "telesma/spec/APP_FLOW.md")) == "Steps 1-3"
   and _tt.find_entry({"APP_FLOW.md": _idx["APP_FLOW.md"]}, "telesma/spec/APP_FLOW.md", ui=True)[0] == "APP_FLOW.md",
   "a flow file indexed under Files and under Flows: a (flow:) tag reads the Flows entry, a (spec:) tag the Files one")

fake_bin = Path(tempfile.mkdtemp(prefix="telesma-task-bin-"))
(fake_bin / "claude").write_text(
    "#!/bin/sh\nprintf '%s\\n' \"$PWD\" \"$@\" > \"$FAKE_CLAUDE_LOG\"\ncat > \"$FAKE_CLAUDE_LOG.stdin\"\n"
    "cat \"$FAKE_CLAUDE_ANSWER\"\n", encoding="utf-8")
(fake_bin / "claude").chmod(0o755)
ENV["PATH"] = str(fake_bin) + os.pathsep + ENV["PATH"]
ENV["FAKE_CLAUDE_LOG"] = str(fake_bin / "log")
ENV["FAKE_CLAUDE_ANSWER"] = str(fake_bin / "answer")
(fake_bin / "answer").write_text(json.dumps({"is_error": False, "result": verdict(("blocker", "canary-claude-blocker")),
                                             "usage": {"input_tokens": 10, "output_tokens": 5}}), encoding="utf-8")
review_field(rv, "Reviewer", "claude")
review_field(rv, "Model", "claude-haiku-5-5")
sh(rv, "git", "add", "-A", "telesma/config.md")
sh(rv, "git", "commit", "-q", "-m", "config")
restamp(rv)
step(12)
n_seen = len(REVIEW["seen"])
rc, out = task(rv, "done")
clog = (fake_bin / "log").read_text(encoding="utf-8").split("\n")
ok(rc == 1 and "canary-claude-blocker" in out and "claude:claude-haiku-5-5" in out and len(REVIEW["seen"]) == n_seen,
   "Reviewer: claude asks a separate Claude Code session, not the endpoint")
ok(os.path.realpath(clog[0]) != os.path.realpath(str(rv)) and "--tools" in clog and "claude-haiku-5-5" in clog
   and "+def s12():" in (fake_bin / "log.stdin").read_text(encoding="utf-8"),
   "that session starts outside the project, without tools, on the model named, with the diff on stdin")
(fake_bin / "gemini").write_text(
    "#!/bin/sh\nprintf '%s\\n' \"$PWD\" \"$@\" \"ide=$GEMINI_CLI_IDE_SERVER_PORT\" > \"$FAKE_CLAUDE_LOG.gemini\"\n"
    "cat > \"$FAKE_CLAUDE_LOG.gemini.stdin\"\necho 'Ripgrep is not available.'\ncat \"$FAKE_CLAUDE_ANSWER.gemini\"\n", encoding="utf-8")
(fake_bin / "gemini").chmod(0o755)
(fake_bin / "answer.gemini").write_text(json.dumps({
    "response": verdict(("major", "canary-gemini-major")),
    "stats": {"models": {"gemini-x": {"tokens": {"prompt": 900, "candidates": 40, "total": 1000}}}}}), encoding="utf-8")
ENV["GEMINI_CLI_IDE_SERVER_PORT"] = "4242"
review_field(rv, "Reviewer", "gemini")
review_field(rv, "Model", "gemini-x")
sh(rv, "git", "add", "-A", "telesma/config.md")
sh(rv, "git", "commit", "-q", "-m", "config")
restamp(rv)
rc, out = task(rv, "done")
glog = (fake_bin / "log.gemini").read_text(encoding="utf-8").split("\n")
gin = (fake_bin / "log.gemini.stdin").read_text(encoding="utf-8")
ok(rc == 0 and "Review (gemini:gemini-x): passed — 0 blocker, 1 major, 0 nit" in head_message(rv) and "canary-gemini-major" in out,
   "Reviewer: gemini asks Gemini CLI and reads its JSON past the lines it prints first")
ok(os.path.realpath(glog[0]) != os.path.realpath(str(rv)) and "plan" in glog and "gemini-x" in glog and "ide=" in glog
   and "+def s12():" in gin and "You review one finished task" in gin,
   "… read-only, outside the project, without the IDE variables, instructions and diff on stdin")
server.shutdown()
shutil.rmtree(rv, ignore_errors=True)
shutil.rmtree(fake_bin, ignore_errors=True)

# --- this machine's files and markdown-written commands (found on a project migrated from format 19)
mf = project()
(mf / "telesma" / "state" / "CHECKS.jsonl").write_text('{"n": 1}\n', encoding="utf-8")
sh(mf, "git", "add", "-f", "telesma/state/CHECKS.jsonl")
sh(mf, "git", "commit", "-q", "-m", "old layout: the check log is tracked")
restamp(mf)
task(mf, "next")
(mf / "greet.py").write_text("x = 1\n", encoding="utf-8")
(mf / "telesma" / "state" / "CHECKS.jsonl").write_text('{"n": 1}\n{"n": 2}\n', encoding="utf-8")
(mf / "telesma" / "state" / "BLOCKED.md").write_text("TELESMA BLOCKED\n\nProblem: an earlier one\n", encoding="utf-8")
rc, out = task(mf, "done")
tracked = sh(mf, "git", "ls-files", "telesma/state").stdout
ok(rc == 0 and "CHECKS.jsonl" not in tracked and "BLOCKED.md" not in tracked
   and read(mf, "telesma/state/CHECKS.jsonl") == '{"n": 1}\n{"n": 2}\n',
   "done takes a tracked check log out of git (it stays on disk) and never commits BLOCKED.md")
ok("No longer tracked (this machine's files): telesma/state/CHECKS.jsonl" in head_message(mf)
   and "no longer tracked by git" in out, "… and says so in the commit message and the output")

marks = Path(tempfile.mkdtemp(prefix="telesma-task-lint-"))
ln = project(**{"Linter/formatter": f"`touch {marks}/a` · `touch {marks}/b`", "Lint before commit": "yes",
                "Test command": "`python3 -m unittest discover -s tests -q` · `true`"})
task(ln, "next")
(ln / "greet.py").write_text("x = 1\n", encoding="utf-8")
rc, out = task(ln, "done")
ok(rc == 0 and (marks / "a").is_file() and (marks / "b").is_file(),
   "Linter/formatter listing two commands with ` · ` (as configure.py writes it) runs each, not `·` as a command")
ok("tests: python3 -m unittest discover -s tests -q && true" in out,
   "a test command written in backticks runs unquoted (bash would read a backtick as a substitution)")
shutil.rmtree(marks, ignore_errors=True)

for x in (d, d2, d3, d4, d5, d6, d7, d8, d9, e, e2, e3, c, k, k2, k3, k4, r, mf, ln):
    shutil.rmtree(x, ignore_errors=True)
shutil.rmtree(XDG, ignore_errors=True)
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)}")
    sys.exit(1)
print("OK — all checks passed")
