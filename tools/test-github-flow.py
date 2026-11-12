#!/usr/bin/env python3
"""Self-test of the scripted GitHub flow (tools/telesma_github.py through telesma-task.py next /
done / commit / suite): a fake `gh` keeps the PRs in a JSON file and really squash-merges into a
local bare repository that plays `origin`. Temp directories only, no network."""
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
sys.path.insert(0, str(TELESMA / "templates" / "setup"))
import trust  # noqa: E402

FAILURES = []
TMP = Path(tempfile.mkdtemp(prefix="telesma-gh-"))
XDG = TMP / "xdg"
ENV = dict(os.environ, XDG_CONFIG_HOME=str(XDG), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", TELESMA_TEST_TIMEOUT="60")

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile
state_path, origin = os.environ["FAKE_GH_STATE"], os.environ["FAKE_GH_ORIGIN"]
st = json.load(open(state_path))
a = sys.argv[1:]
st.setdefault("log", []).append(" ".join(a[:4]))
def save():
    json.dump(st, open(state_path, "w"), indent=1)
def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default
def g(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write("git " + " ".join(args) + ": " + r.stdout + r.stderr)
        sys.exit(1)
    return r.stdout.strip()
if a[:2] == ["pr", "list"]:
    print(json.dumps(st["prs"])); save(); sys.exit(0)
if a[:2] == ["pr", "create"]:
    n = len(st["prs"]) + 1
    st["prs"].append({"number": n, "state": "OPEN", "headRefName": opt("--head"), "baseRefName": opt("--base"),
                      "title": opt("--title"), "body": opt("--body"), "url": f"https://github.com/o/r/pull/{n}",
                      "statusCheckRollup": st.get("default_checks", []), "mergeCommit": None})
    save(); print(f"https://github.com/o/r/pull/{n}"); sys.exit(0)
if a[:2] == ["pr", "edit"]:
    pr = st["prs"][int(a[2]) - 1]; pr["baseRefName"] = opt("--base"); save(); sys.exit(0)
if a[:2] == ["pr", "merge"]:
    pr = st["prs"][int(a[2]) - 1]
    if "--auto" in a:
        pr["auto"] = True; save(); sys.exit(0)
    w = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "-q", "--no-local", origin, w], check=True)
    g(w, "checkout", "-q", pr["baseRefName"])
    g(w, "merge", "--squash", "-q", "origin/" + pr["headRefName"])
    g(w, "commit", "-q", "-m", pr["title"] + "\n\n" + (pr.get("body") or ""))
    g(w, "push", "-q", "origin", pr["baseRefName"])
    pr["state"], pr["mergeCommit"] = "MERGED", {"oid": g(w, "rev-parse", "HEAD")}
    if "--delete-branch" in a:
        g(w, "push", "-q", "origin", "--delete", pr["headRefName"])
    save(); sys.exit(0)
if a[:2] == ["pr", "checks"]:
    save(); sys.exit(0)
save(); sys.exit(0)
'''

CHECK = {"__typename": "CheckRun", "name": "test", "status": "COMPLETED"}


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


def sh(d, *cmd, check=True):
    r = subprocess.run(list(cmd), cwd=d, env=ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd}: {r.stdout}{r.stderr}")
    return r.stdout.strip()


def config(**fields):
    t = TEMPLATE
    for label, value in fields.items():
        t, n = re.subn(r"^- \*\*" + re.escape(label) + r"\*\*:.*$", f"- **{label}**: {value}", t, count=1, flags=re.M)
        assert n == 1, label
    return t


def world(name, plan, **extra):
    base = TMP / name
    origin, d = base / "origin.git", base / "proj"
    base.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    d.mkdir()
    (d / "telesma" / "state").mkdir(parents=True)
    (d / "telesma" / "guidelines").mkdir()
    (d / "telesma" / "guidelines" / "general.md").write_text("# general\n", encoding="utf-8")
    (d / "telesma" / "state" / "PLAN.md").write_text(plan, encoding="utf-8")
    (d / "telesma" / "state" / "REPORT.md").write_text(REPORT, encoding="utf-8")
    (d / "telesma" / "state" / ".telesma-version").write_text("21\n", encoding="utf-8")
    fields = {"Test command": "python3 -m unittest discover -s tests -q", "Full suite command":
              "python3 -m unittest discover -s tests", "Linter/formatter": "none", "Repository": "github",
              "Repo": "o/r", "Merge": "agent", "Required checks": "test", "Open PR limit": "2"}
    fields.update(extra)
    (d / "telesma" / "config.md").write_text(config(**fields), encoding="utf-8")
    (d / "tests").mkdir()
    (d / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (d / "tests" / "test_ok.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n"
                                            "    def test_ok(self):\n        self.assertTrue(True)\n", encoding="utf-8")
    (d / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    sh(d, "git", "init", "-q", "-b", "main")
    sh(d, "git", "add", "-A")
    sh(d, "git", "commit", "-q", "-m", "init")
    sh(d, "git", "remote", "add", "origin", str(origin))
    sh(d, "git", "push", "-q", "-u", "origin", "main")
    sh(d, "git", "remote", "set-head", "origin", "main")
    old = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(XDG)
    trust.stamp(str(d), None)
    os.environ.pop("XDG_CONFIG_HOME") if old is None else os.environ.__setitem__("XDG_CONFIG_HOME", old)
    fake = base / "gh"
    fake.write_text(FAKE_GH, encoding="utf-8")
    fake.chmod(0o755)
    state = base / "gh.json"
    state.write_text(json.dumps({"prs": [], "default_checks": [dict(CHECK, status="IN_PROGRESS")]}), encoding="utf-8")
    env = dict(ENV, TELESMA_GH=str(fake), FAKE_GH_STATE=str(state), FAKE_GH_ORIGIN=str(origin))
    return d, origin, state, env


def task(d, env, *args):
    r = subprocess.run([sys.executable, str(TOOL), *args], cwd=d, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def gh_state(state):
    return json.loads(state.read_text(encoding="utf-8"))


def set_checks(state, n, conclusion):
    st = gh_state(state)
    st["prs"][n - 1]["statusCheckRollup"] = [dict(CHECK, conclusion=conclusion)] if conclusion else \
        [dict(CHECK, status="IN_PROGRESS")]
    state.write_text(json.dumps(st), encoding="utf-8")


def work(d, name):
    (d / f"{name}.py").write_text(f"{name.upper()} = 1\n", encoding="utf-8")


PLAN = ("# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [ ] Task 1.1: Alpha part\n- [ ] Task 1.2: Beta part (requires: 1.1)\n"
        "- [ ] Task 1.3: Gamma part\n")

print("next / done — branch per task, PR, (pr: #n), the tick at the merge")
d, origin, state, env = world("flow", PLAN)
rc, out = task(d, env, "next")
ok(out.startswith("TELESMA NEXT: Task 1.1: Alpha part") and sh(d, "git", "rev-parse", "--abbrev-ref", "HEAD")
   == "task-1-1-alpha-part", "next creates the task branch off origin/main")
work(d, "alpha")
rc, out = task(d, env, "done")
st = gh_state(state)
ok(rc == 0 and "PR #1 opened" in out and st["prs"][0]["headRefName"] == "task-1-1-alpha-part"
   and st["prs"][0]["baseRefName"] == "main", "done pushes the branch and opens the PR against main")
ok(st["prs"][0]["body"].rstrip().endswith("🤖 Generated with Telesma"), "the PR body ends with the footer")
ok(sh(d, "git", "diff", "--name-only", "origin/main", "origin/task-1-1-alpha-part").split() == ["alpha.py"],
   "the PR holds the task's work only — no state files that would collide with other PRs")
ok("main" == sh(d, "git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/main").split("/")[-1]
   and "alpha.py" not in sh(d, "git", "ls-tree", "--name-only", "origin/main"), "nothing reached main")

rc, out = task(d, env, "next")
ok(out.startswith("TELESMA NEXT: Task 1.3: Gamma part"), "with #1 pending, the independent task comes first (17.2)")
work(d, "gamma")
rc, out = task(d, env, "done")
ok("PR #2 opened" in out, "its PR #2")
rc, out = task(d, env, "next")
ok(out.startswith("TELESMA WAITING") and (d / "telesma/state/WAITING.md").is_file(),
   "two open PRs at Open PR limit 2, none red → TELESMA WAITING")

print("merge on green required checks, history row, the next task off the new main")
set_checks(state, 1, "SUCCESS")
rc, out = task(d, env, "next")
st = gh_state(state)
ok(st["prs"][0]["state"] == "MERGED" and "pr merge 1 --squash" in " | ".join(st["log"]), "#1 merged by squash")
ok("alpha.py" in sh(d, "git", "ls-tree", "--name-only", "origin/main"), "its work is on main")
ok(out.startswith("TELESMA NEXT: Task 1.2: Beta part") and not (d / "telesma/state/WAITING.md").exists(),
   "WAITING.md removed; the dependent task is issued now")
ok(sh(d, "git", "merge-base", "--is-ancestor", "origin/main", "HEAD", check=False) == "", "its branch starts from the new main")

print("a red required check — a fix on the same branch, counted")
work(d, "beta")
rc, out = task(d, env, "done")
ok("PR #3 opened" in out and "telesma/state/PLAN.md" not in sh(d, "git", "diff", "--name-only", "origin/main", "HEAD"),
   "the tick of 1.1 does not ride in a task PR")
set_checks(state, 2, "FAILURE")
rc, out = task(d, env, "next")
ok(out.startswith("TELESMA PR FIX: PR #2") and sh(d, "git", "rev-parse", "--abbrev-ref", "HEAD") == "task-1-3-gamma-part",
   "a red PR is handed out before anything new, on its own branch")
rc, out = task(d, env, "next")
ok(out.startswith("TELESMA PR FIX: PR #2"), "and handed out again until fixed")
(d / "gamma.py").write_text("GAMMA = 2\n", encoding="utf-8")
rc, out = task(d, env, "done")
ok(rc == 0 and "pushed to PR #2" in out and "GAMMA = 2" in sh(d, "git", "show", "origin/task-1-3-gamma-part:gamma.py"),
   "done commits and pushes the fix to the same PR")
ok(len(gh_state(state)["prs"]) == 3, "no new PR for the fix")

print("the end of the phase on main")
set_checks(state, 2, "SUCCESS")
set_checks(state, 3, "SUCCESS")
rc, out = task(d, env, "next")
ok("TELESMA SUITE DUE" in out and sh(d, "git", "rev-parse", "--abbrev-ref", "HEAD") == "main",
   "both merged; Phase 1 complete → the suite is due, on main")
rc, out = task(d, env, "suite")
ok(rc == 0 and "Regression after Phase 1" in out and sh(d, "git", "tag", "-l", "telesma/phase-1") == "telesma/phase-1",
   "the phase regression on main, tagged")
ok(sh(d, "git", "rev-parse", "origin/main") == sh(d, "git", "rev-parse", "main") and "state PR #4 opened" in out,
   "nothing committed on main by the suite: ticks, rows and the run go into a state PR")
st = gh_state(state)
state_files = sh(d, "git", "diff", "--name-only", "origin/main", "origin/" + st["prs"][3]["headRefName"]).split()
ok(state_files == ["telesma/state/PLAN.md", "telesma/state/REPORT.md"], "the state PR holds PLAN.md and REPORT.md only")
state_report = sh(d, "git", "show", "origin/" + st["prs"][3]["headRefName"] + ":telesma/state/REPORT.md")
ok(re.search(r"^\| Task 1\.1: Alpha part \| ✅ \| merged \(checks green\) \| 1 \| [0-9a-f]{9} \(#1\) \|",
             state_report, re.M) is not None, "its history row names the squash commit and the PR")
set_checks(state, 4, "SUCCESS")
rc, out = task(d, env, "next")
ok(out.startswith("TELESMA COMPLETE") and gh_state(state)["prs"][3]["state"] == "MERGED",
   "the state PR merged; every task merged → TELESMA COMPLETE")
main_plan = sh(d, "git", "show", "origin/main:telesma/state/PLAN.md")
ok("- [x] Task 1.1: Alpha part (pr: #1)" in main_plan and "- [x] Task 1.3: Gamma part (pr: #2)" in main_plan,
   "main's plan holds the ticks and the PR numbers")
rep = (d / "telesma/state/REPORT.md").read_text(encoding="utf-8")
ok("**Regression after Phase 1" in rep and "| Task 1.3: Gamma part | ✅ | merged (checks green) | 2 |" in rep,
   "the suite paragraph and the rows are kept in the tree (tries = fixes + 1)")

print("a chain — the successor re-pointed before the predecessor's merge, then rebased")
CHAIN = "# Plan\n\n## Tasks\n\n### Phase 2: B\n\n- [ ] Task 2.1: Base part\n- [ ] Task 2.2: Next part (requires: 2.1)\n"
c, corigin, cstate, cenv = world("chain", CHAIN, **{"Open PR limit": "3"})
task(c, cenv, "next")
work(c, "base")
task(c, cenv, "done")
rc, out = task(c, cenv, "next")
ok(out.startswith("TELESMA NEXT: Task 2.2") and "Chain" in out, "only a dependent task left → a chain")
ok(sh(c, "git", "merge-base", "--is-ancestor", "origin/task-2-1-base-part", "HEAD", check=False) == "",
   "branched off the predecessor's branch")
work(c, "next")
task(c, cenv, "done")
st = gh_state(cstate)
ok(st["prs"][1]["baseRefName"] == "task-2-1-base-part", "the successor's PR is based on the predecessor's branch")
set_checks(cstate, 1, "SUCCESS")
rc, out = task(c, cenv, "next")
st = gh_state(cstate)
log = st["log"]
edit_at = next(i for i, x in enumerate(log) if x.startswith("pr edit 2"))
merge_at = next(i for i, x in enumerate(log) if x.startswith("pr merge 1"))
ok(edit_at < merge_at and st["prs"][1]["baseRefName"] == "main", "re-pointed to main BEFORE the merge")
ok("--delete-branch" not in [x for x in log if x.startswith("pr merge 1")][0] and
   "task-2-1-base-part" in sh(c, "git", "ls-remote", "--heads", str(corigin)), "the predecessor merged without --delete-branch")
ok(sh(c, "git", "merge-base", "--is-ancestor", "origin/main", "origin/task-2-2-next-part", check=False) == "",
   "the successor rebased onto the new main and pushed (--force-with-lease)")

print("a commit that is not a task goes through its own PR")
(d / "fix.py").write_text("FIX = 1\n", encoding="utf-8")
rc, out = task(d, env, "commit", "--kind", "bugfix", "-m", "fix the thing")
st = gh_state(state)
ok(rc == 0 and "PR #5 opened" in out and st["prs"][4]["headRefName"].startswith("task-bugfix-")
   and sh(d, "git", "rev-parse", "--abbrev-ref", "HEAD") == "main", "commit --kind bugfix → a PR, back on main")
ok("fix.py" not in sh(d, "git", "ls-tree", "--name-only", "origin/main"), "main untouched until it is merged")

print("closed without a merge")
e, eorigin, estate, eenv = world("closed", PLAN)
task(e, eenv, "next")
work(e, "alpha")
task(e, eenv, "done")
st = gh_state(estate)
st["prs"][0]["state"] = "CLOSED"
estate.write_text(json.dumps(st), encoding="utf-8")
rc, out = task(e, eenv, "next")
ok(out.startswith("TELESMA BLOCKED") and "closed without a merge" in out, "a PR closed by hand → TELESMA BLOCKED")

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)}")
    sys.exit(1)
print("OK — all checks passed")
