#!/usr/bin/env python3
"""Test of telesma-repair.py — builds damaged repositories and checks two invariants.

    python3 tools/test-repair.py

INVARIANT 1 — nothing gets lost. The repair rewrites files based on git history, so there
must be proof that it does not delete content. A line-by-line comparison will not work,
because the tool DELIBERATELY reformats (breaks long tasks, turns `- [x] note` into
`> note`), so we count WORDS: every word of length ≥4 must occur after the repair at least as
many times as before it. The only exemption is the rotation's own bookkeeping (the
`— ✅ completed` stub and `<!-- telesma-archived: -->`), because restoring a phase puts the
real content in their place.

INVARIANT 2 — the repair is idempotent: a second run does not change a single byte.

It is also checked that files outside the repair's scope (DECISIONS.md, BACKLOG.md,
PROJECT_CONTEXT.md) stay byte-identical.
"""
import collections
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "telesma-repair.py"
WORD = re.compile(r"[\w./_-]{4,}", re.UNICODE)
BOOKKEEPING = re.compile(r"^(### Phase .*— ✅ completed \(.*\)|<!--\s*telesma-archived:.*-->)\s*$")
OUT_OF_SCOPE = ("DECISIONS.md", "BACKLOG.md", "PROJECT_CONTEXT.md", "CONTEXT_ARCHIVE.md")

SIDE_FILES = {
    "DECISIONS.md": "# DECISIONS\n\n## 2026-01-01 — outcome\n\n"
                    "We agreed that low-severity collisions do not block acceptance.\n",
    "BACKLOG.md": "# BACKLOG\n\n- [ ] think about indexes on llm_usage\n",
    "PROJECT_CONTEXT.md": "# Context\n\n## Key decisions\n\n| Date | Decision | Reason |\n"
                          "|---|---|---|\n| 2026-01-01 | 📌 Postgres as the queue | fewer "
                          "moving parts |\n",
}

# --- scenario A: rotation cut entries in half ---------------------------------
A_REPORT = """# telesma/state/REPORT.md

## Task history

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|

### Phase 7 (Something) — COMPLETE (2026-02-01)

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|
| 7.1 first | ✅ | 3/3 | 1 | (7) | 2026-02-01 |
| 7.2 second | ✅ | 5/5 | 2 | (7) | 2026-02-01 |

> ⚠ A remark about the phase.

## Problem log

- [2026-02-02] Task 7.2: **symptom** — first line of the entry.
  Second line of the description, which belongs to the same entry.
  ⚠ Third line with the general lesson.

- [2026-02-01] Task 7.1: short one-line entry without a body.

<!-- Format: [date] Task X.X: problem description - solution/status -->
"""

A_PLAN = """# telesma/state/PLAN.md

## Tasks

### Phase 7: Something

- [x] Task 7.1: short (tech: python)
- [x] Task 7.2: a description long enough to exceed the four-hundred-character limit and force \
a break at a sentence boundary. The first sentence says what there is to do. The second adds context \
that cannot be skipped without losing the meaning, and it goes on, and on, until the line becomes \
unreadable for a human and expensive in the prompt. ⚠ The third part is a pitfall during implementation. \
(requires: 7.1) (tech: python)
"""

# --- scenario B: phase archived despite an unfinished ⛔ task ------------------
B_PLAN = """# telesma/state/PLAN.md

## Tasks

### Phase 9: Something finished

- [x] Task 9.1: done (tech: python)
- [x] ⚠ Implementation note: the guard survived mutation on the first attempt

### Phase 10: Phase with a blocker

- [x] Task 10.1: done (tech: python)
- [ ] ⛔ Task 10.2 (BLOCKED — with the owner): verify in production
- [ ] consider whether this should be split into two steps
"""

B_REPORT = """# telesma/state/REPORT.md

## Task history

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|

### Phase 9 (Something finished) — COMPLETE (2026-03-01)

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|
| 9.1 done | ✅ | 2/2 | 1 | (9) | 2026-03-01 |

## Problem log

<!-- Format: [date] Task X.X: problem description - solution/status -->
"""


def git(t, *a):
    subprocess.run(["git", "-C", str(t), *a], check=True, capture_output=True)


def repo(t):
    (t / "telesma" / "state").mkdir(parents=True)
    git(t, "init", "-q")
    git(t, "config", "user.email", "t@example.com")
    git(t, "config", "user.name", "T")


def write(t, **files):
    for n, text in files.items():
        (t / "telesma" / "state" / n).write_text(text, encoding="utf-8")


def scenario_a(t):
    repo(t)
    write(t, **{"REPORT.md": A_REPORT, "PLAN.md": A_PLAN}, **SIDE_FILES)
    git(t, "add", "-A"); git(t, "commit", "-qm", "full state")
    r = t / "telesma" / "state"
    lines = r.joinpath("REPORT.md").read_text(encoding="utf-8").split("\n")
    lines = [l for l in lines if not l.startswith(("| 7.1", "| 7.2"))
             and not l.startswith("- [2026-02-02] Task 7.2:")]
    r.joinpath("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    r.joinpath("REPORT_ARCHIVE.md").write_text(
        "# telesma/state/REPORT_ARCHIVE.md\n\n## Rotation 2026-02-10\n\n### Task history\n\n"
        "| Task | Status | Tests | Tries | Commit | Time |\n"
        "|------|--------|-------|-------|--------|------|\n"
        "| 7.1 first | ✅ | 3/3 | 1 | (7) | 2026-02-01 |\n"
        "| 7.2 second | ✅ | 5/5 | 2 | (7) | 2026-02-01 |\n\n### Problem log\n\n"
        "- [2026-02-02] Task 7.2: **symptom** — first line of the entry.\n\n"
        "- [2026-02-01] Task 7.1: short one-line entry without a body.\n", encoding="utf-8")
    git(t, "add", "-A"); git(t, "commit", "-qm", "after the old rotation")


def scenario_b(t):
    repo(t)
    write(t, **{"PLAN.md": B_PLAN, "REPORT.md": B_REPORT}, **SIDE_FILES)
    git(t, "add", "-A"); git(t, "commit", "-qm", "state before archiving")
    r = t / "telesma" / "state"
    lines = r.joinpath("PLAN.md").read_text(encoding="utf-8").split("\n")
    i = lines.index("### Phase 10: Phase with a blocker")
    block = lines[i:]
    while block and not block[-1].strip():
        block.pop()
    r.joinpath("PLAN.md").write_text("\n".join(lines[:i] + [
        "### Phase 10: Phase with a blocker — ✅ completed (1/1 tasks; content in telesma/state/PLAN_ARCHIVE.md)",
        "<!-- telesma-archived: 10.1 -->", ""]), encoding="utf-8")
    r.joinpath("PLAN_ARCHIVE.md").write_text(
        "# telesma/state/PLAN_ARCHIVE.md\n\n## Rotation 2026-03-05\n\n" + "\n".join(block) + "\n",
        encoding="utf-8")
    git(t, "add", "-A"); git(t, "commit", "-qm", "after the wrong archiving")


def words(directory):
    c = collections.Counter()
    for f in sorted(directory.glob("*.md")):
        for l in f.read_text(encoding="utf-8").split("\n"):
            if not BOOKKEEPING.match(l):
                c.update(WORD.findall(l))
    return c


def check(name, build):
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "project"
        build(t)
        r = t / "telesma" / "state"
        bytes_before = {f.name: f.read_bytes() for f in r.glob("*.md")}
        before = words(r)
        repair = subprocess.run([sys.executable, str(TOOL), str(t), "--fix"],
                                capture_output=True, text=True)
        bytes_after = {f.name: f.read_bytes() for f in r.glob("*.md")}
        after = words(r)
        ok = True

        lost = {w: (n, after[w]) for w, n in before.items() if after[w] < n}
        if lost:
            ok = False
            print(f"  ✗ {name}: lost words: {list(lost)[:8]}")
        if not repair.stdout.strip():
            ok = False
            print(f"  ✗ {name}: the repair did nothing — the scenario does not reproduce the damage")
        if "Nothing needed changing" in repair.stdout:
            ok = False
            print(f"  ✗ {name}: the repair found nothing to fix — the scenario does not reproduce "
                  f"the damage")

        for n in OUT_OF_SCOPE:
            if n in bytes_before and bytes_before[n] != bytes_after.get(n):
                ok = False
                print(f"  ✗ {name}: {n} changed, yet it is outside the repair's scope")

        subprocess.run([sys.executable, str(TOOL), str(t), "--fix"], capture_output=True)
        if {f.name: f.read_bytes() for f in r.glob("*.md")} != bytes_after:
            ok = False
            print(f"  ✗ {name}: the second run changed files (not idempotent)")

        if ok:
            print(f"  ✓ {name}: nothing lost ({sum(before.values())} → {sum(after.values())} "
                  f"words), out-of-scope files untouched, second run without changes")
        return ok


if __name__ == "__main__":
    print("Test tools/telesma-repair.py")
    results = [check("entries cut in half", scenario_a),
               check("phase archived with pending work", scenario_b)]
    sys.exit(0 if all(results) else 1)
