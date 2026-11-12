#!/usr/bin/env python3
"""Self-test of tools/telesma-task.py (`next`, `done`, `commit`) and tools/telesma_state.py.

Every case builds a git project in a temp directory; the trust record goes to a temp
XDG_CONFIG_HOME. Nothing here touches this repository.
"""
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

FAILURES = []
XDG = tempfile.mkdtemp(prefix="telesma-task-xdg-")
ENV = dict(os.environ, XDG_CONFIG_HOME=XDG, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", TELESMA_TEST_TIMEOUT="60")
ENV.pop("GIT_DIR", None)


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
task(k2, "next"); task(k2, "next")
rc, out = task(k2, "next")
ok("Budget: Max attempts per task" in out, "the same task handed out a third time with a limit of 2 → stop")

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

for x in (d, d2, d3, d4, d5, d6, d7, d8, d9, e, e2, e3, c, k, k2, k3, k4, r):
    shutil.rmtree(x, ignore_errors=True)
shutil.rmtree(XDG, ignore_errors=True)
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)}")
    sys.exit(1)
print("OK — all checks passed")
