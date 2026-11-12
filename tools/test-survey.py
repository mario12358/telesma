#!/usr/bin/env python3
"""Tests of tools/telesma-survey.py — the git digest behind `telesma.sh --adopt`.

A fixture repository is built in a temporary directory: two source packages, tests kept apart,
fix commits, a revert, two release tags, a CHANGELOG and a TODO. The checks: the block names the
numbers a survey session needs, never an author (a canary name and e-mail must not appear), the
parts come out as survey units, a directory without git gets a block instead of an error, and a
second run prints the same thing.

    python3 tools/test-survey.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "telesma-survey.py"
FAILURES = []
AUTHOR = ["-c", "user.name=CANARY_AUTHOR", "-c", "user.email=canary.person@example.com"]


def ok(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILURES.append(msg)


def run(*args):
    r = subprocess.run([sys.executable, "-I", str(TOOL), *map(str, args)], capture_output=True, text=True)
    if r.returncode != 0:
        print("    stderr:", r.stderr.strip())
    return r.stdout


def git(repo, *args, date="2026-03-01T10:00:00"):
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(repo), *AUTHOR, *args], check=True, capture_output=True, env=env)


def commit(repo, msg, files, date):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", msg, date=date)


def test_repo():
    print("survey — a repository with history")
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "shop"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        commit(repo, "initial", {
            "README.md": "# Shop\n", "CHANGELOG.md": "# Changes\n",
            "pyproject.toml": "[project]\nname='shop'\n",
            "src/api/auth.py": "def login():\n    pass\n",
            "src/api/orders.py": "def place():\n    pass  # TODO: validate\n",
            "src/web/cart.tsx": "export const Cart = () => null;\n",
            "tests/api/test_auth.py": "def test_login():\n    assert True\n",
            ".github/workflows/ci.yml": "on: push\n",
        }, "2025-01-10T10:00:00")
        git(repo, "tag", "v0.1.0", date="2025-01-10T10:00:00")
        commit(repo, "fix: login crash on empty password", {"src/api/auth.py": "def login(p=''):\n    return bool(p)\n"},
               "2025-02-01T10:00:00")
        commit(repo, "fix login redirect", {"src/api/auth.py": "def login(p=''):\n    return bool(p) and 1\n"},
               "2025-02-03T10:00:00")
        commit(repo, "feat: cart totals", {"src/web/cart.tsx": "export const Cart = () => 1;\n"}, "2025-03-01T10:00:00")
        commit(repo, "chore: bump deps", {"pyproject.toml": "[project]\nname='shop'\nversion='2'\n"}, "2025-04-01T10:00:00")
        git(repo, "tag", "v0.2.0", date="2025-04-01T10:00:00")
        commit(repo, "feat: wishlist", {"src/web/wishlist.tsx": "export const W = () => 0;\n"}, "2025-05-01T10:00:00")
        git(repo, "revert", "--no-edit", "HEAD", date="2025-05-02T10:00:00")
        commit(repo, "docs: adr", {"docs/adr/0001-postgres.md": "# Postgres\n"}, "2025-06-01T10:00:00")

        block = run(repo)
        ok(block.startswith("SURVEY:"), "the block starts with SURVEY:")
        ok("8 commits by 1 author(s), 2025-01-10 → 2025-06-01 (5 months)" in block, f"history line: {block.splitlines()[1]}")
        ok("Releases: 2 tags, scheme vX.Y.Z, last v0.2.0 (2025-04-01); 3 commits since" in block, "releases line")
        ok("Reverts: 1 (last 2025-05-02); fix/bug commits: 2" in block, "reverts and fix commits counted")
        ok("src/api/auth.py 2" in block and "orders.py" not in block.split("Fix density")[1].split("\n")[0],
           "fix density names the file touched by two fix commits only")
        ok("Churn (commits touching, top): src " in block and "tests 1" in block, "churn per top-level directory")
        ok("Dependency changes: 2 commits" in block and "last 2025-04-01" in block and "pyproject.toml" in block,
           "dependency commits (initial + bump) with the last date and the manifest")
        ok("README, CHANGELOG; ADRs in docs/adr" in block, "documentation present, ADR directory found")
        ok("CI: .github/workflows (1 files)" in block, "CI detected")
        ok("Code: 4 files" in block and "test files: 1 (ratio 0.25)" in block,
           "code and test counts (the reverted file is gone, tests kept apart)")
        ok("TODO/FIXME/HACK: 1 in 1+ files (top: src/api/orders.py 1)" in block, "TODO count with the file")
        ok("Parts (one Phase 0 task each): src/api (2 files, 1 tests), src/web (1 files, 0 tests)" in block,
           f"parts under src/, the tests directory folded into the api unit: {block.splitlines()[-1]}")
        ok("CANARY_AUTHOR" not in block and "canary.person" not in block and "example.com" not in block,
           "no author name or e-mail in the block")
        ok("login crash" not in block and "wishlist" not in block, "no commit subject in the block")
        again = run(repo)
        ok(again == block, "a second run prints the same block" + ("" if again == block else
           " — differs: " + next((f"{x!r} vs {y!r}" for x, y in zip(block.splitlines(), again.splitlines()) if x != y), "length")))

        parts = run(repo, "--parts").splitlines()
        ok(len(parts) == 2 and all(len(l.split("\t")) == 4 for l in parts), f"--parts: one tab-separated line per unit ({len(parts)})")
        api = next(l for l in parts if l.startswith("src/api"))
        ok(api.split("\t")[1:] == ["2", "1", "auth.py, orders.py"], f"api unit: {api}")
        j = json.loads(run(repo, "--json"))
        ok(j["authors"] == 1 and j["tag_scheme"] == "vX.Y.Z" and j["head"] and "CANARY" not in json.dumps(j),
           "--json carries the numbers and no author")


def test_other_schemes_and_no_git():
    print("survey — X.Y.Z tags, a root-level project, no git, an empty repository")
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "tool"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "master")
        commit(repo, "start", {"main.py": "print(1)\n", "util.py": "x = 1\n", "test_util.py": "def test_x(): pass\n",
                               "requirements.txt": "requests\n"}, "2024-11-01T10:00:00")
        git(repo, "tag", "1.0.0", date="2024-11-01T10:00:00")
        block = run(repo)
        ok("scheme X.Y.Z, last 1.0.0" in block and "counts only v* tags" in block, "a non-v scheme is named and explained")
        ok("Parts (one Phase 0 task each): (root) (2 files, 1 tests)" in block, f"root files form one unit: {block.splitlines()[-1]}")
        ok("branch master" in block, "branch named")

        plain = Path(d) / "plain"
        (plain / "lib").mkdir(parents=True)
        (plain / "lib" / "a.go").write_text("package a\n")
        (plain / "lib" / "a_test.go").write_text("package a\n")
        block = run(plain)
        ok("No git history" in block and "Parts (one Phase 0 task each): lib (1 files, 1 tests)" in block,
           "no git: a block that says so, units from the working tree")
        ok(run(plain, "--parts").strip() == "lib\t1\t1\ta.go", "--parts without git")

        empty = Path(d) / "empty"
        empty.mkdir()
        git(empty, "init", "-q")
        (empty / "x.rb").write_text("puts 1\n")
        block = run(empty)
        ok("no commit yet" in block and "(root) (1 files" in block, "an empty repository: no history, units from the tree")

        r = subprocess.run([sys.executable, "-I", str(TOOL)], capture_output=True, text=True)
        ok(r.returncode == 0 and "SURVEY" in r.stdout, "no argument: usage")


def test_special_files():
    print("survey — a tracked symlink to a pipe, a pipe among the test results: skipped, never opened")
    if not hasattr(os, "mkfifo"):
        print("  - no FIFOs on this platform: skipped")
        return
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "trap"
        repo.mkdir()
        os.mkfifo(Path(d) / "pipe")
        git(repo, "init", "-q", "-b", "main")
        commit(repo, "start", {"a.py": "x = 1  # TODO: one\n"}, "2025-01-10T10:00:00")
        os.symlink(Path(d) / "pipe", repo / "evil.py")
        os.symlink(Path(d) / "pipe", repo / "TEST-evil.xml")
        git(repo, "add", "evil.py", "TEST-evil.xml")
        git(repo, "commit", "-q", "-m", "a link to a pipe", date="2025-01-11T10:00:00")
        os.mkfifo(repo / "junit-pipe.xml")
        for args, what in (((repo,), "the block"), ((repo, "--test-results", "--since", "0"), "--test-results")):
            try:
                r = subprocess.run([sys.executable, "-I", str(TOOL), *map(str, args)],
                                   capture_output=True, text=True, timeout=30)
                ok(r.returncode == 0 and (what != "the block" or "TODO/FIXME/HACK: 1 in 1+ files" in r.stdout),
                   f"{what}: finishes, the pipe behind the link is not read")
            except subprocess.TimeoutExpired:
                ok(False, f"{what}: hung on a pipe")


def test_deep_layout_and_results():
    print("survey — a deep single-root layout is split by its children; the numbers of a test run")
    with tempfile.TemporaryDirectory() as d:
        app = Path(d) / "android"
        base = app / "app" / "src" / "main" / "java" / "com" / "x" / "reader"
        for name in ("MainActivity.kt", "ReaderViewModel.kt", "App.kt"):
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            (base / name).write_text("class A\n")
        for sub, n in (("pdf", 3), ("ui", 4)):
            for i in range(n):
                (base / sub / f"F{i}.kt").parent.mkdir(parents=True, exist_ok=True)
                (base / sub / f"F{i}.kt").write_text("class B\n")
        (app / "app" / "src" / "test" / "java" / "com" / "x" / "reader" / "pdf").mkdir(parents=True)
        (app / "app" / "src" / "test" / "java" / "com" / "x" / "reader" / "pdf" / "PdfTest.kt").write_text("class T\n")
        parts = run(app, "--parts").splitlines()
        names = [l.split("\t")[0] for l in parts]
        ok(names == ["app/src/main/java/com/x/reader/ui", "app/src/main/java/com/x/reader",
                     "app/src/main/java/com/x/reader/pdf"],
           f"ten files under one deep directory → one unit per child, the root files keep the directory's name: {names}")
        pdf = next(l for l in parts if l.endswith("F0.kt, F1.kt, F2.kt"))
        ok(pdf.split("\t")[2] == "1", "the test kept apart under src/test counts for the pdf unit")
        small = Path(d) / "small"
        (small / "app" / "src" / "main" / "java" / "a").mkdir(parents=True)
        for i in range(3):
            (small / "app" / "src" / "main" / "java" / "a" / f"F{i}.kt").write_text("x\n")
        (small / "app" / "src" / "main" / "java" / "Main.kt").write_text("x\n")
        ok(run(small, "--parts").split("\t")[0] == "app/src", "four files stay one unit — no split below the threshold")

        # the numbers of a run: JUnit XML newer than the start wins over the log
        import time
        start = time.time() - 1
        res = app / "app" / "build" / "test-results" / "testDebugUnitTest"
        res.mkdir(parents=True)
        (res / "TEST-a.xml").write_text('<?xml version="1.0"?>\n<testsuite name="a" tests="3" skipped="1" failures="0" errors="0">\n</testsuite>\n')
        (res / "TEST-b.xml").write_text('<testsuites><testsuite name="b" tests="2" skipped="0" failures="1" errors="0"/></testsuites>\n')
        old = app / "app" / "build" / "test-results" / "old"
        old.mkdir()
        (old / "TEST-old.xml").write_text('<testsuite tests="99" failures="99"/>\n')
        os.utime(old / "TEST-old.xml", (start - 100, start - 100))
        log = Path(d) / "run.log"
        log.write_text("BUILD SUCCESSFUL\n")
        ok(run(app, "--test-results", "--since", str(start), "--log", log).strip()
           == "total=5 pass=3 fail=1 skip=1 source=junit-xml", "JUnit XML written since the start: summed, the old file ignored")
        log.write_text("....F\n== 1 failed, 4 passed, 2 skipped, 1 error in 0.31s ==\n")
        ok(run(small, "--test-results", "--since", str(start), "--log", log).strip()
           == "total=8 pass=4 fail=2 skip=2 source=log:pytest", "no XML: the pytest summary line of the log")
        log.write_text("Tests:       1 failed, 3 passed, 4 total\n")
        ok(run(small, "--test-results", "--since", str(start), "--log", log).strip()
           == "total=4 pass=3 fail=1 skip=0 source=log:jest", "the jest summary line")
        log.write_text("test result: ok. 5 passed; 0 failed; 2 ignored; 0 measured\n")
        ok(run(small, "--test-results", "--since", str(start), "--log", log).strip()
           == "total=7 pass=5 fail=0 skip=2 source=log:cargo", "the cargo summary line")
        log.write_text("nothing here\n")
        ok(run(small, "--test-results", "--since", str(start), "--log", log).strip() == "", "no numbers anywhere: empty output")


if __name__ == "__main__":
    test_repo()
    test_other_schemes_and_no_git()
    test_special_files()
    test_deep_layout_and_results()
    print()
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("OK — all checks passed")
