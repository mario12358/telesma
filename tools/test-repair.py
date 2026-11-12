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

INVARIANT 3 — the repair never deletes what git does not know about, and never what it only
resembles: an archived entry that was amended after its first commit is not a stump; a line is
"already in the archive" only as a whole line, not as a fragment of another sentence.

INVARIANT 4 — a project with nothing to repair is byte-identical after the FIRST run (LF and
CRLF), a repaired CRLF file stays CRLF, a file that is not UTF-8 is diagnosed around and refused
by `--fix` before any write, and `--fix` works with a PROJECT_CONTEXT.md it has no business opening.
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


def fix(t, *flags):
    return subprocess.run([sys.executable, str(TOOL), str(t), *flags], capture_output=True, text=True)


def state_bytes(t):
    return {f.name: f.read_bytes() for f in (t / "telesma" / "state").glob("*")}


def expect(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    return bool(cond)


def amended_archive_entry():
    """An entry is committed, Claude appends a lesson (committed), rotation moves the block to
    the archive, a person adds a line there by hand (never committed). The git version of the
    entry is its FIRST one — shorter than what the archive holds."""
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "project"
        repo(t)
        first = "- [2026-01-01] Task 1.1: the mock passed, production failed.\n"
        write(t, **{"REPORT.md": "# R\n\n## Problem log\n\n" + first})
        git(t, "add", "-A"); git(t, "commit", "-qm", "entry")
        write(t, **{"REPORT.md": "# R\n\n## Problem log\n\n" + first
                                 + "  LESSON_COMMITTED: never trust the mock.\n"})
        git(t, "add", "-A"); git(t, "commit", "-qm", "lesson")
        write(t, **{"REPORT.md": "# R\n\n## Problem log\n\n",
                    "REPORT_ARCHIVE.md": "# A\n\n## Rotation 2026-02-01\n\n### Problem log\n\n" + first
                                         + "  LESSON_COMMITTED: never trust the mock.\n"
                                         + "  NOTE_BY_HAND: written in the archive, git never saw it.\n"})
        git(t, "add", "telesma/state/REPORT.md"); git(t, "commit", "-qm", "rotation")
        before = state_bytes(t)
        r = fix(t, "--fix")
        a = (t / "telesma/state/REPORT_ARCHIVE.md").read_text(encoding="utf-8")
        return expect(r.returncode == 0 and "LESSON_COMMITTED" in a and "NOTE_BY_HAND" in a
                      and state_bytes(t) == before and "stumps" not in r.stdout,
                      "an archived entry amended after its first commit is not a stump: the lesson and "
                      "the uncommitted line stay")


def fragment_is_not_archived():
    """Two lines git never saw, each a FRAGMENT of an unrelated archive sentence."""
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "project"
        repo(t)
        write(t, **{"REPORT.md": "# R\n\n## Problem log\n\n- [2026-01-01] Task 1.1: first.\n",
                    "REPORT_ARCHIVE.md": "# A\n\n### Problem log\n\n- [2025-12-01] Task 0.1: the deploy "
                                         "key rotation is postponed until the second quarter.\n"})
        git(t, "add", "-A"); git(t, "commit", "-qm", "state")
        write(t, **{"REPORT.md": "# R\n\n## Problem log\n\nrotation is postponed\n\n"
                                 "- [2026-01-01] Task 1.1: first.\n  key\n"})
        before = state_bytes(t)
        r = fix(t, "--fix")
        text = (t / "telesma/state/REPORT.md").read_text(encoding="utf-8")
        return expect(r.returncode == 0 and "rotation is postponed\n" in text and "  key\n" in text
                      and state_bytes(t) == before,
                      "a line is `already in the archive` only as a whole line — a fragment of another "
                      "sentence is not removed")


CLEAN_REPORT = ("# R\n\n## Task history\n\n### Phase 1\n\n| Task | Status |\n|---|---|\n| 1.1 a | ok |\n\n"
                "## Problem log\n\n- [2026-01-01] Task 1.1: one.\n- [2026-01-02] Task 1.2: two.\n\n"
                "## Notes\n\n```\na\n\n\n\nb\n```\n")


def clean_project_untouched():
    """Entries without a blank line between them, three blank lines inside a code block of
    another section: nothing to repair, so not a byte may move — on the first run."""
    ok = True
    for name, nl in (("LF", "\n"), ("CRLF", "\r\n")):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "project"
            repo(t)
            r = t / "telesma" / "state"
            (r / "REPORT.md").write_bytes(CLEAN_REPORT.replace("\n", nl).encode())
            (r / "PLAN.md").write_bytes("### Phase 1: x\n\n- [x] Task 1.1: a\n".replace("\n", nl).encode())
            git(t, "add", "-A"); git(t, "commit", "-qm", "state")
            before = state_bytes(t)
            out = fix(t, "--fix")
            status = subprocess.run(["git", "-C", str(t), "status", "--porcelain"],
                                    capture_output=True, text=True).stdout
            ok &= expect("Nothing needed changing" in out.stdout and state_bytes(t) == before and not status,
                         f"a clean project ({name}) is byte-identical after the first run, the tree stays clean")
    return ok


def crlf_repair_stays_crlf():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "project"
        scenario_a(t)
        r = t / "telesma" / "state"
        for n in ("REPORT.md", "REPORT_ARCHIVE.md", "PLAN.md"):
            (r / n).write_bytes((r / n).read_bytes().replace(b"\n", b"\r\n"))
        git(t, "add", "-A"); git(t, "commit", "-qm", "a Windows checkout")
        before = words(r)
        out = fix(t, "--fix")
        after = words(r)
        lone = [n for n in ("REPORT.md", "REPORT_ARCHIVE.md", "PLAN.md")
                if (r / n).read_bytes().count(b"\n") != (r / n).read_bytes().count(b"\r\n")]
        text = (r / "REPORT.md").read_bytes().decode()
        archive = (r / "REPORT_ARCHIVE.md").read_bytes().decode()
        return expect("stumps completed" in out.stdout and "table rows" in out.stdout and not lone
                      and "| 7.2 second |" in text and "Second line of the description" in archive
                      and not {w for w, n in before.items() if after[w] < n},
                      f"a CRLF project is repaired like an LF one and stays CRLF {lone}")


def not_utf8():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "project"
        scenario_a(t)
        r = t / "telesma" / "state"
        (r / "REPORT_ARCHIVE.md").write_bytes((r / "REPORT_ARCHIVE.md").read_bytes()
                                              + "- [2026-01-05] za\u017c\u00f3\u0142\u0107\n".encode("iso-8859-2"))
        before = state_bytes(t)
        diag = fix(t)
        out = fix(t, "--fix")
        ok = expect(diag.returncode == 0 and "not valid UTF-8" in diag.stdout and "Traceback" not in diag.stderr,
                    "diagnosis of a file that is not UTF-8: a notice, not a crash")
        ok &= expect(out.returncode == 2 and "not valid UTF-8" in out.stderr and state_bytes(t) == before,
                     "--fix refuses before the first write: not a byte changed in any file")
        (r / "REPORT_ARCHIVE.md").write_bytes(before["REPORT_ARCHIVE.md"][:-20])
        (r / "PROJECT_CONTEXT.md").write_bytes(b"## Current state\n\n\xb1\xe6\xea\n")
        ctx = (r / "PROJECT_CONTEXT.md").read_bytes()
        out = fix(t, "--fix")
        ok &= expect(out.returncode == 0 and "stumps completed" in out.stdout
                     and (r / "PROJECT_CONTEXT.md").read_bytes() == ctx,
                     "--fix does not open PROJECT_CONTEXT.md: one it could not even read does not stop the repair")
        return ok


def no_state_directory():
    with tempfile.TemporaryDirectory() as d:
        out = fix(Path(d))
        return expect(out.returncode == 2 and "No directory" in out.stderr and "Traceback" not in out.stderr,
                      "a directory without telesma/state: a message and exit code 2, not a traceback")


if __name__ == "__main__":
    print("Test tools/telesma-repair.py")
    results = [check("entries cut in half", scenario_a),
               check("phase archived with pending work", scenario_b),
               amended_archive_entry(), fragment_is_not_archived(), clean_project_untouched(),
               crlf_repair_stays_crlf(), not_utf8(), no_state_directory()]
    sys.exit(0 if all(results) else 1)
