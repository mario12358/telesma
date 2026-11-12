#!/usr/bin/env python3
"""Self-test of tools/telesma-guard.py (the "code only" PreToolUse hook) and of its registration
by the launcher (the PYGUARD block of telesma.sh). Temp directories only."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TELESMA = Path(__file__).resolve().parent.parent
GUARD = TELESMA / "tools" / "telesma-guard.py"
SCRIPT = (TELESMA / "telesma.sh").read_text(encoding="utf-8")
TEMPLATE = (TELESMA / "templates" / "config.md").read_text(encoding="utf-8")
FAILURES = []


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


PLAN = "# Plan\n\n## Tasks\n\n### Phase 1: A\n\n- [x] Task 1.1: one\n- [ ] Task 1.2: two\n- [ ] Test: three\n"
REPORT = ("# Report\n\n## Summary\n\n- **Progress**: 1/3\n\n## Test status\n\n| Metric | Value |\n|--|--|\n"
          "| Total tests | 3 |\n\n## Task history\n\n| Task | Status |\n|--|--|\n| Task 1.1: one | ✅ |\n\n"
          "## Change history\n\n## Problem log\n\n- [2026-11-01] x\n")


def project(fmt=21, repository="none"):
    d = Path(tempfile.mkdtemp(prefix="telesma-guard-"))
    (d / "telesma" / "state").mkdir(parents=True)
    cfg = re.sub(r"^- \*\*Repository\*\*:.*$", f"- **Repository**: {repository}", TEMPLATE, count=1, flags=re.M)
    (d / "telesma" / "config.md").write_text(cfg, encoding="utf-8")
    (d / "telesma" / "state" / ".telesma-version").write_text(f"{fmt}\n", encoding="utf-8")
    (d / "telesma" / "state" / "PLAN.md").write_text(PLAN, encoding="utf-8")
    (d / "telesma" / "state" / "REPORT.md").write_text(REPORT, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    return d


def call(d, tool, tool_input, mode="default"):
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"tool_name": tool, "tool_input": tool_input,
                                                                     "cwd": str(d), "permission_mode": mode}),
                       capture_output=True, text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(d)))
    if not r.stdout.strip():
        return None
    return json.loads(r.stdout)["hookSpecificOutput"]


def denied(d, cmd):
    out = call(d, "Bash", {"command": cmd})
    return bool(out) and out.get("permissionDecision") == "deny"


d = project()
print("Bash — git and gh writes are refused, with the command to use")
DENY = ['git commit -m "x"', "git add .", "git add src/a.py", "cd sub && git commit -am x", "env A=1 git commit -m x",
        "timeout 60 git push origin main", "git -C . commit -m x", "git tag telesma/phase-1", "git tag -f telesma/phase-1",
        "git tag -f -a v1.0.0 -m x", "git tag v1.0.0", "git tag -d v1.0.0", 'bash -c "git commit -m x"',
        'echo "$(git commit -m x)"', "git reset --hard HEAD~1", "git reset HEAD~1", "git pull", "git revert HEAD",
        "git cherry-pick abc123", "git rebase main", "git merge feature", "git -c alias.z=commit z -m x",
        "git update-ref refs/heads/main HEAD~1", "git branch -D old", "gh pr create --fill", "gh pr merge 3",
        "gh api -X POST repos/o/r/issues", "gh api repos/o/r/issues -f title=x", "gh release create v1.0.0",
        'python3 -c "import os; os.system(\'git commit -m x\')"', "git am < patch.mbox", "git notes add -m x",
        'sh -ec "git commit -m x"', "eval git commit -m x", 'git tag -a v1.2.0 -m "Release"']
for cmd in DENY:
    ok(denied(d, cmd), f"refused: {cmd}")
out = call(d, "Bash", {"command": "git commit -m x"})
ok("telesma-task.py done" in out["permissionDecisionReason"], "the reason names `done`")
ALLOW = ["git status", "git diff --stat", "git log --oneline -5", "git show HEAD", "git tag", "git tag -l",
         "git tag --list 'v*'", "git reset -- src/a.py", "git restore --staged a.py",
         "git restore a.py", "git stash", "git checkout -b task-1", 'grep -rn "git commit" docs/',
         "gh pr view 3", "gh pr list", "gh api repos/o/r/pulls", "git fetch", "git describe --tags",
         f"python3 {TELESMA}/tools/telesma-task.py done", "npm test", "rg 'git push' -n",
         'python3 /home/u/git/telesma/tools/telesma-task.py commit --kind bugfix -m "fix"',
         "bash scripts/git-commit-helper.sh"]
for cmd in ALLOW:
    ok(not denied(d, cmd), f"let through: {cmd}")

print("release — always the person's question")
rel = f'python3 {TELESMA}/tools/telesma-task.py release v1.2.0 -m "CSV export"'
out = call(d, "Bash", {"command": rel})
ok(out and out["permissionDecision"] == "ask" and "v1.2.0" in out["permissionDecisionReason"],
   "release → ask, even where an allow rule would let it through")
out = call(d, "Bash", {"command": rel}, mode="auto")
ok(out and out["permissionDecision"] == "ask", "in auto mode too (the classifier does not decide it)")
for mode in ("bypassPermissions", "dontAsk"):
    out = call(d, "Bash", {"command": rel}, mode=mode)
    ok(out and out["permissionDecision"] == "deny", f"in {mode} nobody is asked → refused")
out = call(dgh_early := project(repository="github"), "Bash", {"command": rel})
ok(out and out["permissionDecision"] == "ask", "with a repository integration as well")
out = call(d, "Bash", {"command": "git tag -a v1.2.0 -m x"})
ok(out and "release v" in out["permissionDecisionReason"], "a hand-made release tag points at `release`")

print("PLAN.md — ticks belong to done")
plan_path = str(d / "telesma" / "state" / "PLAN.md")
out = call(d, "Edit", {"file_path": plan_path, "old_string": "- [ ] Task 1.2: two", "new_string": "- [x] Task 1.2: two"})
ok(out and out["permissionDecision"] == "deny" and "1.2" in out["permissionDecisionReason"], "ticking a task is refused")
out = call(d, "Edit", {"file_path": plan_path, "old_string": "- [x] Task 1.1: one", "new_string": "- [ ] Task 1.1: one"})
ok(out and out["permissionDecision"] == "deny", "unticking a task is refused")
out = call(d, "Edit", {"file_path": plan_path, "old_string": "- [ ] Test: three", "new_string": "- [x] Test: three"})
ok(out and out["permissionDecision"] == "deny", "ticking an item without an id is refused")
out = call(d, "Edit", {"file_path": "telesma/state/PLAN.md", "old_string": "- [ ] Task 1.2: two",
                       "new_string": "- [ ] Task 1.2: two, renamed (change: x.md)"})
ok(out is None, "editing a task's text is fine (relative path too)")
out = call(d, "Write", {"file_path": plan_path, "content": PLAN + "- [x] Task 1.3: pre-ticked\n"})
ok(out and out["permissionDecision"] == "deny", "a Write that adds a ticked task is refused")
out = call(d, "Write", {"file_path": plan_path, "content": PLAN + "\n### Phase 2: B\n\n- [ ] Task 2.1: new\n"})
ok(out is None, "a Write that adds open tasks is fine")
out = call(d, "MultiEdit", {"file_path": plan_path, "edits": [
    {"old_string": "two", "new_string": "deux"}, {"old_string": "- [ ] Task 1.2", "new_string": "- [x] Task 1.2"}]})
ok(out and out["permissionDecision"] == "deny", "a MultiEdit that ticks among other edits is refused")

print("REPORT.md — the history sections belong to the script")
rep_path = str(d / "telesma" / "state" / "REPORT.md")
for old, new, what in (("| Task 1.1: one | ✅ |", "| Task 1.1: one | ✅ |\n| Task 1.2: two | ✅ |", "Task history"),
                       ("| Total tests | 3 |", "| Total tests | 30 |", "Test status"),
                       ("## Change history\n", "## Change history\n\n### 2026-11-11 x.md\n", "Change history")):
    out = call(d, "Edit", {"file_path": rep_path, "old_string": old, "new_string": new})
    ok(out and out["permissionDecision"] == "deny" and what in out["permissionDecisionReason"], f"an edit of {what} is refused")
out = call(d, "Edit", {"file_path": rep_path, "old_string": "- [2026-11-01] x", "new_string": "- [2026-11-01] x\n- [2026-11-11] y"})
ok(out is None, "the Problem log is the model's")
out = call(d, "Edit", {"file_path": rep_path, "old_string": "- **Progress**: 1/3", "new_string": "- **Status**: In progress\n- **Progress**: 1/3"})
ok(out is None, "the Summary is the model's")
other = d / "notes.md"
other.write_text("## Task history\n", encoding="utf-8")
ok(call(d, "Write", {"file_path": str(other), "content": "x"}) is None, "other files are not looked at")

print("inactive — older format, not a Telesma project; the integration is covered")
d20 = project(fmt=20)
ok(not denied(d20, "git commit -m x"), "format 20: nothing refused")
dgh = project(repository="github")
ok(denied(dgh, "git commit -m x") and denied(dgh, "git push -u origin task-1-2-x") and denied(dgh, "gh pr merge 3 --squash")
   and not denied(dgh, "gh pr checks 3") and not denied(dgh, "gh run view --log-failed"),
   "with a repository integration the GitHub writes are the script's too; reading checks and logs is fine")
plain = Path(tempfile.mkdtemp(prefix="telesma-guard-plain-"))
ok(call(plain, "Bash", {"command": "git commit -m x"}) is None, "outside a Telesma project nothing is refused")
r = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
ok(r.returncode == 0 and not r.stdout.strip(), "unreadable input: no decision, exit 0")

print("session budget — out of budget: reads and BLOCKED.md only; the call counter warns")
b = project(repository="github")        # the budget applies with an integration too
sess = b / ".git" / "telesma-task"
sess.mkdir(parents=True)
(sess / "session.json").write_text(json.dumps({"exhausted": {"reason": "Max tasks per session"}}), encoding="utf-8")
for cmd in ("git status", "git log -3", "cat telesma/state/REPORT.md", "ls src", "grep -rn x src"):
    ok(not denied(b, cmd), f"out of budget, let through: {cmd}")
for cmd in ("npm test", "python3 app.py", "git commit -m x", "cat a > b", "rm -rf build"):
    ok(denied(b, cmd), f"out of budget, refused: {cmd}")
out = call(b, "Write", {"file_path": str(b / "src.py"), "content": "x"})
ok(out and "budget is used up" in out["permissionDecisionReason"], "out of budget: a code edit is refused")
ok(call(b, "Write", {"file_path": str(b / "telesma/state/BLOCKED.md"), "content": "x"}) is None,
   "out of budget: BLOCKED.md can be written")
(sess / "session.json").write_text(json.dumps({"task": {"tid": "1.2"}, "name": "Task 1.2: two",
                                               "calls_since_next": 148}), encoding="utf-8")


def post(dd):
    r = subprocess.run([sys.executable, str(GUARD), "--post"], input=json.dumps({"tool_name": "Read", "cwd": str(dd)}),
                       capture_output=True, text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(dd)))
    return r.stdout.strip()


ok(post(b) == "" and "150 tool calls on Task 1.2" in post(b), "the 150th call on one task gets one warning line")
ok(json.loads((sess / "session.json").read_text())["calls_since_next"] == 150, "the counter is kept in the session file")
ok(post(b) == "", "and the next call is quiet again")

print("launcher — the guard is registered once, other hooks kept")
m = re.search(r"<<'PYGUARD'[^\n]*\n(.*?)\nPYGUARD\n", SCRIPT, re.S)
ok(m is not None, "telesma.sh has the PYGUARD block")
s = Path(tempfile.mkdtemp(prefix="telesma-guard-settings-")) / ".claude" / "settings.local.json"
s.parent.mkdir(parents=True)
s.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"PreToolUse": [
    {"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}), encoding="utf-8")
for _ in range(2):
    subprocess.run([sys.executable, "-", str(s), str(GUARD)], input=m.group(1), text=True, check=True)
data = json.loads(s.read_text(encoding="utf-8"))
cmds = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
ok(cmds.count(f'python3 "{GUARD}"') == 1 and "mine.sh" in cmds and data["permissions"]["allow"] == ["Bash(ls:*)"],
   "registered once after two starts; the person's hook and the permissions untouched")
ok(any(g["matcher"] == "Bash|Edit|Write|MultiEdit" for g in data["hooks"]["PreToolUse"]), "matcher covers Bash and edits")
posts = [h["command"] for g in data["hooks"]["PostToolUse"] for h in g["hooks"]]
ok(posts.count(f'python3 "{GUARD}" --post') == 1, "the call counter is registered once as PostToolUse")

for x in (d, d20, dgh, dgh_early, plain, b, s.parent.parent):
    shutil.rmtree(x, ignore_errors=True)
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)}")
    sys.exit(1)
print("OK — all checks passed")
