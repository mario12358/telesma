#!/usr/bin/env python3
"""Tests of the configuration wizard: templates/setup/configure.py (the deterministic engine) and
the launcher's first start (templates/setup/wizard.sh), driven without a terminal and through a
pseudo-terminal. Fixtures in temporary directories; the repository is never touched.

    python3 tools/test-setup.py
"""

import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGURE = ROOT / "templates" / "setup" / "configure.py"
TEMPLATE = ROOT / "templates" / "config.md"
LAUNCHER = ROOT / "telesma.sh"

FAILURES = []


def ok(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILURES.append(msg)


def cfg(*args):
    r = subprocess.run([sys.executable, "-I", str(CONFIGURE), *map(str, args)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    configure {' '.join(map(str, args))}: rc={r.returncode} {r.stderr.strip()}")
    return r.stdout


def kv(text):
    return dict(l.split("=", 1) for l in text.splitlines() if "=" in l)


def blocks(config):
    text = Path(config).read_text(encoding="utf-8")
    sec = re.search(r"^## Checks\n(.*?)(?=^## |\Z)", text, re.M | re.S).group(1)
    return re.findall(r"^### (\S+)", sec, re.M)


# ---------------------------------------------------------------------------------------------
# configure.py
# ---------------------------------------------------------------------------------------------

def test_profiles():
    print("configure.py — profiles and check tiers")
    with tempfile.TemporaryDirectory() as d:
        c = Path(d) / "config.md"
        shutil.copy(TEMPLATE, c)
        out = cfg("profile", c, "recommended", "--template", TEMPLATE)
        s = kv(cfg("status", c))
        ok(s["judge"] == "rules" and s["checks"] == "basic", f"recommended: judge rules, checks basic ({s['judge']}, {s['checks']})")
        ok(blocks(c) == ["secrets", "weakenings", "tests", "hygiene"], f"basic keeps four blocks in template order: {blocks(c)}")
        before = c.read_text()
        ok(cfg("profile", c, "recommended", "--template", TEMPLATE) == "" and c.read_text() == before,
           "second run: no output, file unchanged")
        cfg("checks", c, "security", "--template", TEMPLATE)
        ok(len(blocks(c)) == 11 and blocks(c)[-1] == "red-team", f"security: all 11 blocks ({len(blocks(c))})")
        # a user edit inside a kept block survives a tier change
        text = c.read_text().replace("### secrets\n- **When**: commit, ci", "### secrets\n- **When**: commit")
        c.write_text(text)
        cfg("checks", c, "standard", "--template", TEMPLATE)
        ok("### secrets\n- **When**: commit\n" in c.read_text() and "intent" not in blocks(c),
           "standard after security: intent/red-team removed, the edited secrets block kept")
        cfg("checks", c, "none", "--template", TEMPLATE)
        s = kv(cfg("status", c))
        ok(blocks(c) == [] and s["checks"] == "none" and "- **Enabled**: no" in c.read_text(), "none: no blocks, Enabled: no")
        cfg("checks", c, "basic", "--template", TEMPLATE)
        ok(blocks(c) == ["secrets", "weakenings", "tests", "hygiene"], "basic again: blocks come back from the template")
        ok("<!-- Check fields" in c.read_text(), "the section's trailing comment survives every rebuild")
        cfg("profile", c, "minimal", "--template", TEMPLATE)
        s = kv(cfg("status", c))
        ok(s["judge"] == "off" and s["checks"] == "none", "minimal: judge off, checks none")
        # the merge at startup must accept the result: no stray fields outside blocks
        sec = re.search(r"^## Checks\n(.*?)(?=^## |\Z)", c.read_text(), re.M | re.S).group(1)
        ok(sec.count("- **Enabled**") == 1 and sec.count("- **PR status**") == 1, "section fields intact")


def test_tests_and_stacks():
    print("configure.py — stack detection and ## Tests")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        c = root / "config.md"
        shutil.copy(TEMPLATE, c)
        p = root / "py"
        p.mkdir()
        (p / "pyproject.toml").write_text("[project]\nname='x'\n[tool.ruff]\nline-length=100\n[tool.mypy]\nstrict=true\n")
        det = kv(cfg("detect", p))
        ok(det["stack"] == "python" and det["git"] == "no", f"python project detected ({det['stack']}, git={det['git']})")
        cfg("tests", c, "--stack", "auto", "--project", p)
        s = kv(cfg("status", c))
        ok(s["test_command"] == "pytest -q" and s["lint_command"] == "ruff check ." and s["typecheck_command"] == "mypy .",
           f"python commands from pyproject: {s['test_command']} / {s['lint_command']} / {s['typecheck_command']}")
        text = c.read_text()
        ok("  - Bash(pytest:*)" in text and "  - Bash(npm test:*)" not in text and "  - WebFetch(domain:claude.ai)" in text,
           "allowed commands: stack rules replaced, user/base entries kept")

        n = root / "node"
        n.mkdir()
        (n / "package.json").write_text('{"name":"x","scripts":{"test":"vitest run","lint":"eslint .","typecheck":"tsc --noEmit"}}')
        (n / "pnpm-lock.yaml").write_text("")
        cfg("tests", c, "--stack", "auto", "--project", n)
        s = kv(cfg("status", c))
        ok(s["test_command"] == "pnpm test" and s["lint_command"] == "pnpm lint" and s["typecheck_command"] == "pnpm typecheck",
           f"node with pnpm lockfile and scripts: {s['test_command']} / {s['lint_command']} / {s['typecheck_command']}")

        m = root / "mono"
        (m / "backend").mkdir(parents=True)
        (m / "frontend").mkdir()
        (m / "backend" / "pyproject.toml").write_text("[project]\nname='b'\n")
        (m / "frontend" / "package.json").write_text('{"scripts":{"test":"jest","lint":"eslint ."}}')
        det = kv(cfg("detect", m))
        ok(det["parts"] == "python:backend node:frontend", f"monorepo parts one level down: {det['parts']}")
        cfg("tests", c, "--stack", "auto", "--project", m)
        s = kv(cfg("status", c))
        ok(s["test_command"] == "(cd backend && pytest -q) && (cd frontend && npm test)",
           f"monorepo tests in subshells: {s['test_command']}")
        ok(s["lint_command"].startswith("cd backend && ruff check .") and " · " in s["lint_command"],
           f"monorepo linters separated by ' · ' for lint-types: {s['lint_command']}")

        cfg("tests", c, "--stack", "rust")
        s = kv(cfg("status", c))
        ok(s["test_command"] == "cargo test" and "  - Bash(cargo:*)" in c.read_text() and "  - Bash(pytest:*)" not in c.read_text(),
           "explicit stack (greenfield rust): commands and rules swapped")
        r = subprocess.run([sys.executable, "-I", str(CONFIGURE), "tests", str(c), "--stack", "cobol"], capture_output=True, text=True)
        ok(r.returncode == 2, "unknown stack → exit 2")
        cfg("set", c, "Project", "Language", "pl")
        ok(kv(cfg("status", c))["language"] == "pl", "set: a plain field")
        summary = cfg("summary", c)
        ok("cargo test" in summary and "[## Tests]" in summary, "summary names the section of every row")


# ---------------------------------------------------------------------------------------------
# the launcher
# ---------------------------------------------------------------------------------------------

# Fake Claude CLI. Records the prompt it was started with (positional argument in interactive
# mode, stdin in pipe mode) in $FAKE_LOG, and — with FAKE_WRITE set — plays an interview session
# that writes what INTERVIEW.md asks for: the spec files, the technical template without its
# marker, ## Tests in config.md. The launcher cds into the project before starting it.
FAKE_CLAUDE = r'''#!/bin/sh
[ "$1" = auth ] && exit 0
# A hook runs python3 through `sh -c`: what reaches it from the launcher's environment must work there
[ -n "$FAKE_SH_LOG" ] && /bin/sh -c 'python3 -c "print(4242)"' > "$FAKE_SH_LOG"
# What stdin is: the real Claude Code dies on a terminal opened as /dev/tty on macOS
[ -n "$FAKE_TTY_LOG" ] && env python3 -c 'import os; print(os.ttyname(0) if os.isatty(0) else "-")' >> "$FAKE_TTY_LOG"
# The Windows route (run_claude): the prompt comes as --append-system-prompt-file <file>.
pf=""; prev=""
for a in "$@"; do [ "$prev" = "--append-system-prompt-file" ] && pf="$a"; prev="$a"; done
if [ -n "$pf" ]; then cat "$pf" > "${FAKE_LOG:-/dev/null}"
elif [ "$#" -gt 0 ]; then printf '%s' "$*" > "${FAKE_LOG:-/dev/null}"; else cat > "${FAKE_LOG:-/dev/null}"; fi
case "$(cat "${FAKE_LOG:-/dev/null}")" in
  *"Interview phase"*)
    [ -n "$FAKE_WRITE" ] || exit 0
    printf '# Sorter\n\n## What it does\nSorts photos.\n' > telesma/spec/IDEA.md
    printf '# Requirements\n\n## R1: List photos\n- When the user picks a folder, then the photos appear.\n' > telesma/spec/REQUIREMENTS.md
    printf '# APP_FLOW.md — Sorter\n\n## Step 1 — Pick a folder\n\n**User**: clicks Open.\n' > telesma/spec/APP_FLOW.md
    tail -n +2 telesma/spec/TECHNICAL_GUIDELINES.md > tg.tmp && mv tg.tmp telesma/spec/TECHNICAL_GUIDELINES.md
    for f in "Test command" "Full suite command" "Smoke suite"; do
      python3 "$CONFIGURE_PY" set telesma/config.md Tests "$f" "pytest -q" > /dev/null
    done
    ;;
  *"Perform ONLY steps 1 and 2"*)
    [ -n "$FAKE_QUESTIONS" ] || exit 0
    printf '# Questions\n\n## Questions\n\n### Q1: How big is the board?\n- **Proposed answer**: 10x10\n- **Answer**:\n- **Status**: \342\235\223\n' > telesma/state/QUESTIONS.md
    ;;
  *"Perform ONLY step 4"*)
    [ -n "$FAKE_PLAN" ] || exit 0
    printf '# Plan\n\n### Phase 1: Start\n\n- [ ] Task 1.1: First screen\n- [ ] Task 1.2: Second screen\n' > telesma/state/PLAN.md
    python3 "$CONFIGURE_PY" set telesma/config.md Project Clarified yes > /dev/null
    # A model that writes QUESTIONS.md from memory instead of editing it: the answers are gone
    sed 's/^- \*\*Answer\*\*:.*/- **Answer**:/' telesma/state/QUESTIONS.md > q.tmp && mv q.tmp telesma/state/QUESTIONS.md
    ;;
esac
exit 0
'''


def fake_bin(tmp):
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    claude = b / "claude"
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(0o755)
    # The interview's stack tests with `pytest -q`; the launcher checks that the project's tools exist
    pytest = b / "pytest"
    pytest.write_text("#!/bin/sh\nexit 0\n")
    pytest.chmod(0o755)
    return b


def env_for(tmp, **extra):
    # The telemetry opt-in lives in ~/.config/telesma/hub and registers with the shared hub: a test
    # that answers "yes" must touch neither this machine's opt-in nor the real hub.
    env = dict(os.environ, PATH=f"{fake_bin(tmp)}{os.pathsep}{os.environ.get('PATH', '')}", TELESMA_NO_UPDATE_CHECK="1",
               FAKE_LOG=str(tmp / "claude.log"), CONFIGURE_PY=str(CONFIGURE),
               XDG_CONFIG_HOME=str(tmp / "xdg"), TELESMA_SHARED_HUB="http://127.0.0.1:9")
    # LC_ALL and LC_MESSAGES win over LANG (POSIX): the macOS CI runner sets LC_ALL=en_US.UTF-8, and
    # every test that gives LANG=pl_PL to see the Polish lines got English
    env.pop("LC_ALL", None)
    env.pop("LC_MESSAGES", None)
    env.update(extra)
    return env


def run_launcher(tmp, project, *args, **extra):
    return subprocess.run(["bash", str(LAUNCHER), str(project), *args], env=env_for(tmp, **extra), capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, start_new_session=True, timeout=120)


def strip(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def test_first_start_no_tty():
    print("launcher — first start without a terminal")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        project.mkdir()
        r = run_launcher(tmp, project)
        out = strip(r.stdout)
        spec = project / "telesma" / "spec"
        ok(r.returncode == 0 and (spec / "TECHNICAL_GUIDELINES.md").is_file(), "empty project: spec/ with the technical template")
        ok(not (spec / "APP_FLOW.md").exists() and not (spec / "ux_ui" / "LINKS.md").exists(),
           "no APP_FLOW.md / LINKS.md on the first start (visual-artifacts inputs are opt-in)")
        ok("1. Put the project description" in out and "3. Run again" in out, "three next steps printed")
        ok(not (project / "telesma" / "config.md").exists(), "config.md not yet created (spec first)")

        (spec / "TECHNICAL_GUIDELINES.md").write_text("# Project technical guidelines\n\n- **Language / runtime**: Go\n")
        (spec / "shop.md").write_text("# Shop\n\nOrders.\n")
        (project / "go.mod").write_text("module x\n")
        r = run_launcher(tmp, project)
        out = strip(r.stdout)
        c = project / "telesma" / "config.md"
        ok(r.returncode == 0 and c.is_file(), f"second start: config.md created, exit {r.returncode}")
        ok("No terminal" in out and "recommended" in out and "--setup" in out, "no terminal: the recommended profile, pointer to --setup")
        s = kv(cfg("status", c))
        ok(s["judge"] == "rules" and s["checks"] == "basic" and s["test_command"] == "go test ./...",
           f"recommended + detected Go: judge={s['judge']} checks={s['checks']} tests={s['test_command']}")
        ok("Auto-approve**: yes" in c.read_text() and blocks(c) == ["secrets", "weakenings", "tests", "hygiene"],
           "config file reflects the profile")
        ok(not (project / "telesma" / "checks").exists(), "the wizard run ends before anything else is delivered")

        r = run_launcher(tmp, project, "--setup")
        ok(r.returncode == 0 and "needs a terminal" in strip(r.stdout), "--setup without a terminal: summary only")


def drive(cmd, answers, env, timeout=120):
    """Runs `cmd` on a pty; sends the next answer after every prompt (a line ending in ': ')."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(cmd[0], cmd, env)       # env as given: a variable env_for removed stays removed
    out, buf, i = b"", b"", 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            buf += chunk
        elif re.search(rb": $|\]: $", buf):
            os.write(fd, ((answers[i] if i < len(answers) else "") + "\n").encode())
            i += 1
            buf = b""
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    return strip(out.decode("utf-8", "replace").replace("\r", ""))


def test_not_a_project_folder():
    print("launcher — home, Desktop, the projects folder are never a new project")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        home = tmp / "home"
        for sub in ("Desktop", "Telesma", "Desktop/prog"):
            (home / sub).mkdir(parents=True)
        for where in (home, home / "Desktop", home / "Telesma"):
            r = run_launcher(tmp, where, HOME=str(home), LANG="en_US.UTF-8")
            out = strip(r.stdout)
            ok(r.returncode == 1 and "Not here" in out and "--new" in out, f"{where.name}: refused with the way on")
            ok(not (where / "telesma" / "state").exists() and not (where / ".claude").exists(), f"{where.name}: nothing created")
        # no path given: the current folder (a stale desktop shortcut started in Desktop)
        r = subprocess.run(["bash", str(LAUNCHER)], env=env_for(tmp, HOME=str(home)), cwd=home / "Desktop",
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True, timeout=120)
        ok(r.returncode == 1 and not (home / "Desktop" / "telesma").exists(), "no path, started in Desktop: refused")
        r = run_launcher(tmp, home / "Desktop", HOME=str(home), LANG="pl_PL.UTF-8")
        ok("Nie tutaj" in strip(r.stdout), "the refusal in the system language")
        r = run_launcher(tmp, home / "Desktop" / "prog", HOME=str(home))
        ok(r.returncode == 0 and (home / "Desktop" / "prog" / "telesma").is_dir(), "a folder of its own inside Desktop: fine")
        (home / "Desktop" / "telesma" / "state").mkdir(parents=True)
        (home / "Desktop" / "telesma" / "state" / ".telesma-version").write_text("18\n")
        r = run_launcher(tmp, home / "Desktop", HOME=str(home))
        ok("Not here" not in strip(r.stdout), "an existing project there (.telesma-version) goes on")


def test_first_start_tty():
    print("launcher — first start and --setup through a pseudo-terminal")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        (project / "telesma" / "spec").mkdir(parents=True)
        (project / "telesma" / "spec" / "shop.md").write_text("# Shop\n")
        (project / "package.json").write_text('{"scripts":{"test":"vitest run"}}')
        env = env_for(tmp)
        # language pl (asked first), experience developer, profile minimal, git init yes, detected
        # stack yes, four commands + smoke kept, judge off, tier none, telemetry no
        out = drive(["bash", str(LAUNCHER), str(project)],
                    ["pl", "", "minimal", "", "", "", "", "", "", "", "off", "none", "", "n"], dict(env, LANG="de_DE.UTF-8"))
        c = project / "telesma" / "config.md"
        ok(c.is_file() and "=== Następne kroki ===" in out and "-m 1" not in out and "Idziemy dalej?" in out
           and "Gdy zechcesz iść dalej, wpisz:" in out,
           "first start: next steps are one command, then 'go on?' — n prints the command (in Polish once the language is pl)")
        ok("Language [de]:" in out or "Język [de]:" in out, "the language question comes first and proposes the system's language")
        ok("── Repozytorium git" in out and "Profil [recommended]:" in out and "── Pytania o uprawnienia" in out
           and "Testy " in out.split("=== Konfiguracja")[1] and "[T/n]:" in out,
           "after the answer the whole wizard, the yes/no letters and the summary are in Polish")
        s = kv(cfg("status", c))
        ok(s["judge"] == "off" and s["checks"] == "none" and s["language"] == "pl" and s["test_command"] == "npm test",
           f"answers applied: judge={s['judge']} checks={s['checks']} language={s['language']} tests={s['test_command']}")
        ok((project / ".git").is_dir(), "git init offered and done")
        ok("── Integracje" not in out, "minimal profile does not ask about integrations")
        ok("TECHNICAL_GUIDELINES.md" in out and "domyślne" in out.split("TECHNICAL_GUIDELINES.md")[1][:120],
           "next steps say the technical guidelines may stay as they are")

        out = drive(["bash", str(LAUNCHER), str(project), "--setup"], ["3", "security", "5", "n", "y", "q"], env)
        s = kv(cfg("status", c))
        ok(s["checks"] == "security" and s["recordings"] == "yes" and s["screenshots"] == "no",
           f"--setup menu: checks={s['checks']} recordings={s['recordings']} screenshots={s['screenshots']}")
        ok((project / "telesma" / "spec" / "APP_FLOW.md").is_file(), "recordings on → APP_FLOW.md template created")
        ok("Gotowe" in out and "=== Konfiguracja (telesma/config.md) ===" in out, "menu ends with the summary")
        ok(s["experience"] == "developer" and "Język, poziom" in out, "experience: developer by default, shown in the menu")
        ok("Kept local values" not in out and "Config merge" not in out, "a start that changes nothing in config.md reports nothing")


def test_new_project():
    print("launcher — --new: the interview, the beginner wizard, resume and refusal")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        project.mkdir()
        r = run_launcher(tmp, project, "--new")
        ok(r.returncode == 1 and "needs a terminal" in strip(r.stdout) and not (project / "telesma").exists(),
           "--new without a terminal: refused before anything is created")

        # 1. the interview is interrupted (the fake Claude writes nothing)
        env = env_for(tmp, PYTHONIOENCODING="cp1250")  # a Windows console: Python writes cp1250, which has no →
        out = drive(["bash", str(LAUNCHER), "--new", str(project)], ["pl"], env)
        c = project / "telesma" / "config.md"
        spec = project / "telesma" / "spec"
        ok("Rozmowa się nie skończyła" in out and "--new" in out and c.is_file(), "interrupted interview: told how to continue, in Polish")
        s = kv(cfg("status", c))
        ok(s["experience"] == "beginner" and s["language"] == "pl", f"config.md created before the session: experience={s['experience']} language={s['language']}")
        prompt = (tmp / "claude.log").read_text()
        ok("--permission-mode acceptEdits" in prompt and "Interview phase" in prompt and "-2.4 Choosing the technology" in prompt,
           "the session gets INTERVIEW.md and acceptEdits")
        ok("LANGUAGE: pl" in prompt and "EXPERIENCE: beginner" in prompt, "LANGUAGE and the EXPERIENCE block are in the prompt")
        ok("- telesma/spec/TECHNICAL_GUIDELINES.md" in prompt and (spec / "TECHNICAL_GUIDELINES.md").is_file(),
           "the technical template is there and listed for the resume")
        ok("Profile" not in out and "=== Next steps ===" not in out, "no wizard before the interview is complete")

        # 2. the second --new resumes and finishes; the beginner wizard asks only about telemetry,
        #    in the person's language, and asks whether to go on instead of listing commands
        #    Run with a python3 that ends lines with \r\n, as Python does on Windows.
        crlf = tmp / "crlf"
        crlf.mkdir()
        (crlf / "python3").write_text(f'#!/bin/bash\n"{sys.executable}" "$@" | sed $\'s/$/\\r/\'\nexit ${{PIPESTATUS[0]}}\n')
        (crlf / "python3").chmod(0o755)
        env = env_for(tmp, FAKE_WRITE="1", TELESMA_STRIP_CR="1", FAKE_SH_LOG=str(tmp / "sh.log"))
        env["PATH"] = f"{crlf}{os.pathsep}{env['PATH']}"
        out = drive(["bash", str(LAUNCHER), "--new", str(project)], ["", "n"], env)
        ok((tmp / "sh.log").read_text().strip() == "4242" and not list(project.glob(">(*")),
           "the \\r filter reaches `sh -c` in the session (hooks) and works there: output kept, no stray file")
        ok("Language Telesma should talk in" not in out, "resume: the language is not asked again")
        ok((spec / "IDEA.md").is_file() and (spec / "REQUIREMENTS.md").is_file()
           and "TELESMA_SPEC_TEMPLATE" not in (spec / "TECHNICAL_GUIDELINES.md").read_text().split("\n", 1)[0],
           "the interview wrote the specification")
        ok("Opis Twojego pomysłu jest zapisany" in out and "=== Telesma — ustawienia ===" in out,
           "the first-start wizard ran after the interview, in Polish")
        ok("Profil [" not in out and "── Pytania o uprawnienia" not in out and "── Kontrole jakości" not in out
           and "── Stos i testy" not in out and "── Język" not in out and "Wysyłać te notatki? [t/N]" in out,
           "beginner wizard: no profile/judge/checks/tests questions, the telemetry opt-in is asked in plain words")
        ok("Merge telesma/config.md" not in out and "Kept local values" not in out, "beginner: no config-merge report")
        ok("=== Next steps ===" not in out and "=== Następne kroki ===" not in out and "=== Konfiguracja" not in out,
           "beginner: no summary table and no list of commands")
        ok("Idziemy dalej?" in out and "Gdy zechcesz iść dalej, wpisz:" in out,
           "beginner: asked whether to go on; no → the one command that continues")
        s = kv(cfg("status", c))
        ok(s["judge"] == "rules" and s["checks"] == "basic" and s["tests"] == "set" and s["test_command"] == "pytest -q",
           f"recommended profile + tests from the interview: judge={s['judge']} checks={s['checks']} tests={s['test_command']}")
        ok(s["telemetry"] in ("no", "off"), f"telemetry declined by default: {s['telemetry']}")
        ok((project / ".git").is_dir() and "historia każdej zmiany" in out, "git started without a question")

        # 2b. a plain start goes on with the clarification, in plain Polish words
        out = drive(["bash", str(LAUNCHER), str(project)], [], env)
        prompt = (tmp / "claude.log").read_text()
        ok("Perform ONLY steps 1 and 2" in prompt and "EXPERIENCE: beginner" in prompt,
           "plain start after the settings: clarification phase A with the EXPERIENCE block")
        ok("Telesma czyta opis i przygotowuje pytania" in out and "wpisz /exit" in out
           and "Phase: generating" not in out, "clarification hints in plain Polish")

        # 2b'. the same on Windows: the prompt in a file appended to the system prompt, stdin left
        #      to the terminal (Claude Code there cannot read the keyboard from a pipe)
        out = drive(["bash", str(LAUNCHER), str(project)], [], dict(env, TELESMA_PROMPT_VIA_FILE="1"))
        prompt = (tmp / "claude.log").read_text()
        ok("Perform ONLY steps 1 and 2" in prompt and "EXPERIENCE: beginner" in prompt,
           "Windows route: the clarification prompt reaches Claude through --append-system-prompt-file")

        # 2b''. a relative project path (`./telesma.sh ./p`): the clarification cd's into the project
        #      and must still find the questions it wrote
        out = drive(["bash", "-c", f'cd "{tmp}" && exec bash "{LAUNCHER}" ./p'], ["", "q"], dict(env, FAKE_QUESTIONS="1"))
        ok("Pytania od Telesmy: 1" in out and "nie zapisała pytań" not in out,
           "relative project path: the questions written in phase A are found and asked")

        # 2c. one run from the idea to the clarification: ENTER at "go on?" starts it right away
        p2 = tmp / "p2"
        (tmp / "claude.log").unlink()
        out = drive(["bash", str(LAUNCHER), "--new", str(p2)], ["pl", "", ""], env)
        prompt = (tmp / "claude.log").read_text()
        ok("Idziemy dalej?" in out and "Perform ONLY steps 1 and 2" in prompt,
           "ENTER at 'go on?': the clarification starts in the same run")

        # 2c'. the installer's "start now" hands the launcher `< /dev/tty`: on macOS Claude Code must get
        #      the terminal's own device — on /dev/tty it dies with "EINVAL … kqueue"
        if sys.platform == "darwin":
            tty_log = tmp / "tty.log"
            drive(["bash", "-c", f'exec bash "{LAUNCHER}" --new "{tmp / "p3"}" < /dev/tty'], ["pl"], dict(env, FAKE_TTY_LOG=str(tty_log)))
            seen = tty_log.read_text().split("\n")[0] if tty_log.is_file() else "(claude not started)"   # the interview
            ok(seen.startswith("/dev/tty") and seen != "/dev/tty", f"stdin /dev/tty → Claude gets the terminal device ({seen})")

        # 2d. after clarification: the "what now?" menu, and closing the build session returns to it
        cfg("set", c, "Project", "Clarified", "yes")
        plan = project / "telesma" / "state" / "PLAN.md"
        plan.write_text("# Plan\n\n### Phase 1: Start\n\n- [ ] Task 1.1: First screen\n", encoding="utf-8")
        out = drive(["bash", str(LAUNCHER), str(project)], ["1", "q"], env)
        ok(out.count("Telesma — co teraz?") == 2 and "zostały do zrobienia: 1" in out,
           "beginner: the build session ends → back to the 'what now?' menu, with the open steps")

        # 2e. a tool the project's commands need is missing: named, and a beginner's build does not start
        cfg("set", c, "Tests", "Test command", "nosuchtool-xyz run")
        out = drive(["bash", str(LAUNCHER), str(project)], ["1"], env)
        ok("nosuchtool-xyz nie jest zainstalowany" in out and "Telesma zatrzymuje się tutaj" in out
           and out.count("Telesma — co teraz?") == 1, "beginner: a missing build tool stops before the session, in Polish")
        r = subprocess.run(["bash", str(LAUNCHER), "--doctor", str(project)], capture_output=True, text=True,
                           env=dict(env, LANG="en_US.UTF-8"), stdin=subprocess.DEVNULL, timeout=60)
        ok(r.returncode == 1 and "✗ nosuchtool-xyz is not installed" in strip(r.stdout) and "✓ pytest" in strip(r.stdout),
           "--doctor <project>: also the tools of the project's commands")
        cfg("set", c, "Tests", "Test command", "pytest -q")

        # 3. --new on a clarified project is refused
        out = drive(["bash", str(LAUNCHER), "--new", str(project)], [], env)
        ok("already has a specification" in out and "telesma/changes/" in out, "--new on a clarified project: refused, points at changes/")


def test_experience_in_prompt():
    print("launcher — the EXPERIENCE block reaches the clarification prompt only for a beginner")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        spec = project / "telesma" / "spec"
        spec.mkdir(parents=True)
        (spec / "shop.md").write_text("# Shop\n\nOrders.\n")
        (spec / "TECHNICAL_GUIDELINES.md").write_text("# Project technical guidelines\n\n- **Language / runtime**: Python\n")
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        r = run_launcher(tmp, project)                       # first start → config.md + silent wizard
        c = project / "telesma" / "config.md"
        ok(r.returncode == 0 and c.is_file(), "config.md created")
        cfg("set", c, "Project", "Experience", "beginner")
        r = run_launcher(tmp, project)                       # clarification phase A: prompt piped to claude
        prompt = (tmp / "claude.log").read_text()
        ok("Perform ONLY steps 1 and 2" in prompt, f"clarification phase A reached (exit {r.returncode})")
        ok("type /exit — it closes only this conversation, and Telesma then shows the questions" in prompt,
           "phase A ends by telling the person how to go on (the launcher's hint scrolled away)")
        ok("LANGUAGE: en" in prompt and "EXPERIENCE: beginner" in prompt and "plain words" in prompt,
           "beginner: the EXPERIENCE block follows the LANGUAGE line")
        cfg("set", c, "Project", "Experience", "developer")
        run_launcher(tmp, project)
        prompt = (tmp / "claude.log").read_text()
        ok("LANGUAGE: en" in prompt and "EXPERIENCE: beginner — the person" not in prompt, "developer: no EXPERIENCE block, no tokens spent")


def test_clarification_end():
    print("launcher — the technical template never blocks; unanswered ✅ items are asked; answers survive the plan session; 'start building?'")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        spec = project / "telesma" / "spec"
        spec.mkdir(parents=True)
        shutil.copy(ROOT / "templates" / "SPEC_TEMPLATE.md", spec / "TECHNICAL_GUIDELINES.md")   # the marker stays
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        env = env_for(tmp)
        r = run_launcher(tmp, project)                       # first start → config.md + silent wizard
        c = project / "telesma" / "config.md"
        ok(c.is_file(), "config.md created with the unfilled template as the only spec file")
        r = run_launcher(tmp, project)
        out = strip(r.stdout)
        ok("telesma/spec/ is empty" in out and "unfilled template" not in out and "TELESMA_SPEC_TEMPLATE" not in out,
           "an unfilled template alone is 'no specification', not a demand to edit the template")

        (spec / "shop.md").write_text("# Shop\n\nOrders.\n")
        r = run_launcher(tmp, project)
        prompt = (tmp / "claude.log").read_text()
        ok("Perform ONLY steps 1 and 2" in prompt and "TELESMA_SPEC_TEMPLATE" not in strip(r.stdout),
           "with a spec next to it the unfilled template does not block the clarification")

        # Q1 answered by the person (not the proposal), Q2 marked ✅ by a model with nothing in Answer
        q = project / "telesma" / "state" / "QUESTIONS.md"
        q.write_text("# Questions\n\n- **State**: in progress\n- **Total questions**: 2\n- **Answered**: 2\n\n## Questions\n\n"
                     "### Q1: Board size?\n- **Proposed answer**: 10x10\n- **Answer**: 8x8\n- **Status**: ✅\n\n"
                     "### Q2: Colors?\n- **Proposed answer**: black and white\n- **Answer**: \n- **Status**: ✅\n", encoding="utf-8")
        out = drive(["bash", str(LAUNCHER), str(project)], ["", "n"], dict(env, FAKE_PLAN="1"))
        text = q.read_text(encoding="utf-8")
        ok("1 items in QUESTIONS.md were marked resolved without an answer" in out and "Question 1/2" not in out
           and "- **Answer**: black and white" in text, "Q2 (✅, no answer) went back to the queue and was asked; Q1 was not")
        ok("- **Answer**: 8x8" in text and "dropped your answers" in out and "answers to: Q1" in out,
           "the plan session rewrote QUESTIONS.md: the answers are restored, Q1 (not the proposal) is named")
        ok("=== Clarification finished ===" in out and "Start building now?" in out and "(2 tasks)" in out
           and "When you want to go on, type:" in out and "Kept local values" not in out,
           "a developer is asked whether to start building; 'n' prints the command that continues")

        # ## Tests left for the plan ("later"): the next start reads the plan's Stack line, proposes the
        # stack's commands and permission rules once, before the mode menu
        plan = project / "telesma" / "state" / "PLAN.md"
        plan.write_text("# Plan\n\n- **Stack**: Flutter (Dart) + Riverpod; proxy: Hono/TypeScript\n\n### Phase 1: Start\n\n- [ ] Task 1.1: First screen\n",
                        encoding="utf-8")
        out = drive(["bash", str(LAUNCHER), str(project)], ["", "q"], env)
        s = kv(cfg("status", c))
        ok("The plan names the stack: Flutter" in out and "for flutter from it?" in out and s["test_command"] == "flutter test"
           and "Bash(flutter:*)" in c.read_text() and "still the template placeholder" not in out,
           f"the stack comes from the plan: tests={s['test_command']}, permission rules added, no validator error")


def test_preflight():
    print("launcher — what the machine needs is checked before anything is created")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # Only the shell tools the launcher needs: no git, no python3, a Claude that is signed out.
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for t in ("bash", "uname", "grep", "tr", "cut", "dirname", "sed", "awk", "cat", "head"):
            if shutil.which(t):
                (bin_dir / t).symlink_to(shutil.which(t))
        claude = bin_dir / "claude"
        claude.write_text('#!/bin/sh\n[ "$1" = auth ] && echo \'{"loggedIn": false}\'\nexit 0\n')
        claude.chmod(0o755)
        project = tmp / "p"
        r = subprocess.run([shutil.which("bash"), str(LAUNCHER), str(project)], capture_output=True, text=True,
                           env=dict(os.environ, PATH=str(bin_dir), LANG="pl_PL.UTF-8", LC_ALL="", LC_MESSAGES="",
                                    TELESMA_NO_UPDATE_CHECK="1"),
                           stdin=subprocess.DEVNULL, timeout=60)
        out = strip(r.stdout + r.stderr)
        ok(r.returncode == 1 and not project.exists(), f"missing pieces: exit 1, nothing created (exit {r.returncode})")
        ok("git nie jest zainstalowany" in out and "Python 3 (python3) nie jest zainstalowany" in out
           and "niezalogowany" in out and "claude auth login" in out, "each missing piece named, with what to do, in the system language")
        r = subprocess.run(["bash", str(LAUNCHER), "--doctor"], capture_output=True, text=True,
                           env=env_for(tmp, LANG="en_US.UTF-8"), stdin=subprocess.DEVNULL, timeout=60)
        out = strip(r.stdout)
        ok(r.returncode == 0 and "✓ git" in out and "Everything Telesma needs is in place" in out, "--doctor: a ✓ per piece, exit 0")


def test_smart_app_control():
    print("preflight — Smart App Control on Windows stops a stack that compiles its own exe, before the build")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        b = tmp / "bin"
        b.mkdir()
        (b / "uname").write_text("#!/bin/sh\necho MINGW64_NT-10.0-26300\n")
        (b / "dotnet").write_text("#!/bin/sh\nexit 0\n")
        (b / "uv").write_text("#!/bin/sh\nexit 0\n")
        for f in ("uname", "dotnet", "uv"):
            (b / f).chmod(0o755)

        def run(state, tests, verbose=""):
            reg = b / "reg"
            reg.write_text("#!/bin/sh\n" + ("" if state is None else
                           "printf 'HKEY_LOCAL_MACHINE\\\\SYSTEM\\\\CurrentControlSet\\\\Control\\\\CI\\\\Policy\\r\\n"
                           f"    VerifiedAndReputablePolicyState    REG_DWORD    {state}\\r\\n\\r\\n'\n"))
            reg.chmod(0o755)
            config = tmp / "config.md"
            config.write_text(f"# c\n\n## Tests\n\n- **Test command**: {tests}\n\n## Git\n")
            env = dict(os.environ, PATH=f"{b}{os.pathsep}{os.environ.get('PATH', '')}", LANG="pl_PL.UTF-8", LC_ALL="", LC_MESSAGES="")
            r = subprocess.run(["bash", "-c", f'SCRIPT_DIR="{ROOT}"; source "$SCRIPT_DIR/templates/messages/msg.sh"; '
                                'msg_set_language pl; source "$SCRIPT_DIR/templates/setup/preflight.sh"; '
                                f'preflight_stack "{config}" {verbose}; echo "rc=$?"'],
                               capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
            return strip(r.stdout)
        out = run("0x1", "dotnet test")
        ok("rc=1" in out and "Smart App Control" in out and "Wyłączone" in out and "ponownej instalacji" in out,
           "on + dotnet: named before the build, how to turn it off, that it may not come back, rc 1")
        ok("rc=0" in run("0x1", "uv run pytest -q"), "on + Python (a signed interpreter): no stop")
        ok("rc=0" in run("0x2", "dotnet test"), "evaluation mode blocks nothing: no stop")
        ok("rc=0" in run("0x0", "dotnet test"), "off: no stop")
        ok("rc=0" in run(None, "dotnet test"), "no such setting (Windows 10): no stop")
        ok("Inteligentna kontrola aplikacji: wyłączona" in run("0x0", "dotnet test", "verbose"), "--doctor shows the state")
        ok("nie dotyczy" in run("0x1", "uv run pytest -q", "verbose"), "--doctor: on, but this Python project is not affected")


def test_update_offer():
    print("launcher — a newer release upstream is offered at the start and pulled on yes")
    branch = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
    if not branch or branch == "HEAD":
        print("  (skipped: detached HEAD)")
        return
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        up, c = tmp / "upstream", tmp / "clone"
        genv = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "clone", "-q", str(ROOT), str(up)], check=True)
        # a clone carries commits only: the launcher and the catalog as they are in the working tree
        for rel in ("telesma.sh", "templates/messages/pl.txt", "templates/setup/preflight.sh"):
            shutil.copy(ROOT / rel, up / rel)
        subprocess.run(["git", "-C", str(up), "commit", "-q", "-am", "working tree"], env=genv)
        subprocess.run(["git", "clone", "-q", str(up), str(c)], check=True)
        (up / "CHANGELOG.md").write_text((up / "CHANGELOG.md").read_text() + "\n## 99.0.0\n")
        subprocess.run(["git", "-C", str(up), "commit", "-q", "-am", "99.0.0"], check=True, env=genv)
        subprocess.run(["git", "-C", str(up), "tag", "-a", "v99.0.0", "-m", "99"], check=True, env=genv)
        launcher = c / "telesma.sh"

        def tag_of(repo):
            return subprocess.run(["git", "-C", str(repo), "describe", "--tags", "--abbrev=0", "--match", "v*"], capture_output=True, text=True).stdout.strip()
        # no terminal: the news and the command, nothing pulled
        p1 = tmp / "p1"
        r = subprocess.run(["bash", str(launcher), str(p1)], env=env_for(tmp, TELESMA_NO_UPDATE_CHECK="", LANG="pl_PL.UTF-8"),
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        out = strip(r.stdout)
        ok("Jest nowa wersja Telesmy: 99.0.0" in out and "Zaktualizuj poleceniem" in out and "pull --ff-only" in out,
           "no terminal: the new version named, the command given")
        ok(tag_of(c) != "v99.0.0", "no terminal: nothing pulled")
        # a terminal, "n": nothing pulled, asks again next time
        out = drive(["bash", str(launcher), str(tmp / "p2")], ["n"], env_for(tmp, TELESMA_NO_UPDATE_CHECK="", LANG="pl_PL.UTF-8"))
        ok("Zaktualizować teraz?" in out and "Nie teraz" in out and tag_of(c) != "v99.0.0", "answer n: not pulled, told it asks again")
        # a terminal, ENTER: pulled, the launcher starts again and goes on with the project
        p3 = tmp / "p3"
        out = drive(["bash", str(launcher), str(p3)], [""], env_for(tmp, TELESMA_NO_UPDATE_CHECK="", LANG="pl_PL.UTF-8"))
        ok("zaktualizowana do 99.0.0" in out and tag_of(c) == "v99.0.0", f"ENTER: pulled to the new release ({tag_of(c)})")
        ok(out.count("Autonomous Development Loop") == 2 and (p3 / "telesma" / "spec").is_dir(),
           "started again after the update and went on with the project")
        # up to date: silence
        r = subprocess.run(["bash", str(launcher), str(p3)], env=env_for(tmp, TELESMA_NO_UPDATE_CHECK=""),
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        ok("new Telesma version" not in strip(r.stdout) and "behind" not in strip(r.stdout), "up to date: no update line")


def test_home_menu():
    print("launcher — --home: the desktop shortcut's start menu")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = tmp / "Documents" / "Telesma"
        # an interrupted interview, then a project with two open steps (worked on last)
        p1 = root / "p1"
        (p1 / "telesma" / "spec").mkdir(parents=True)
        (p1 / "telesma" / "config.md").write_text("## Project\n\n- **Language**: pl\n- **Experience**: beginner\n- **Clarified**: no\n")
        time.sleep(1.1)
        p2 = root / "mines"
        (p2 / "telesma" / "spec").mkdir(parents=True)
        (p2 / "telesma" / "state").mkdir()
        (p2 / "telesma" / "spec" / "IDEA.md").write_text("# Morskie Miny\n")
        (p2 / "telesma" / "spec" / "REQUIREMENTS.md").write_text("# Requirements\n")
        (p2 / "telesma" / "spec" / "TECHNICAL_GUIDELINES.md").write_text("# Project technical guidelines\n")
        (p2 / "telesma" / "config.md").write_text("## Project\n\n- **Experience**: beginner\n- **Clarified**: yes\n")
        (p2 / "telesma" / "state" / "PLAN.md").write_text("- [x] Task 1.1: a\n- [ ] Task 1.2: b\n- [ ] Task 1.3: c\n")
        env = env_for(tmp, LANG="pl_PL.UTF-8")
        out = drive(["bash", str(LAUNCHER), "--home", str(root)], ["q"], env)
        ok(f"Twoje projekty są w folderze: {root}" in out and "1) Nowy pomysł" in out, "the menu: the folder and a new idea, in the system language")
        ok("2) Morskie Miny — kroków do zrobienia: 2" in out and "3) p1 — opis pomysłu jeszcze niedokończony" in out
           and "Wybór [2]" in out, "projects by last work, named from the interview, with where they stand; the latest is the default")
        out = drive(["bash", str(LAUNCHER), "--home", str(root)], ["3", "pl"], env)
        ok("nowy projekt z pomysłu" in out, "an interrupted interview continues with --new")
        out = drive(["bash", str(LAUNCHER), "--home", str(root)], ["1", "Zdjęcia z łódki", ""], env)
        ok((root / "zdjecia-z-lodki" / "telesma" / "config.md").is_file() and "nowy projekt z pomysłu" in out,
           "a new idea: a folder named from the working name, then the interview")
        ok("Język, w którym Telesma ma rozmawiać" in out and "[pl]:" in out and "- **Language**: pl" in (root / "zdjecia-z-lodki" / "telesma" / "config.md").read_text()
           and "Autonomous Development Loop" not in out and "does not exist - creating" not in out,
           "from the menu: no banner, no English lines; the language question in the system language, which is the default")
        out = drive(["bash", str(LAUNCHER), "--home", str(root)], ["1", 'gra na Mac "Mario", tylko w tej edycji bohaterem jest Yoshi'], env)
        ok((root / "gra-na-mac-mario-tylko-w-tej-edycji").is_dir(), "a long name: the folder ends on a whole word")


def test_installer():
    print("install.sh — dependencies, Telesma, the desktop shortcut (from this clone, signed-in fake claude)")
    branch = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
    if not branch or branch == "HEAD":
        print("  (skipped: detached HEAD, nothing to clone a branch from)")
        return
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        home, dest, desktop, projects = tmp / "home", tmp / "home" / ".telesma", tmp / "Desktop", tmp / "Documents" / "Telesma"
        home.mkdir()
        env = env_for(tmp, LANG="pl_PL.UTF-8", HOME=str(home), TELESMA_REPO=str(ROOT), TELESMA_BRANCH=branch,
                      TELESMA_INSTALL_DIR=str(dest), TELESMA_PROJECTS=str(projects), TELESMA_DESKTOP=str(desktop))
        out = drive(["bash", "-c", f'bash < "{ROOT / "install.sh"}"'], ["n"], env)
        ok("=== Telesma — instalacja ===" in out and "Telesma pobrana" in out and (dest / "telesma.sh").is_file(),
           "piped like curl | bash: Telesma cloned, lines in the system language")
        ok(projects.is_dir() and "Uruchomić Telesmę teraz?" in out, "projects folder made, asked whether to start")
        cmd = home / ".local" / "bin" / "telesma"
        ok(cmd.is_symlink() and cmd.resolve() == (dest / "telesma.sh").resolve() and "Polecenie telesma jest w" in out,
           "the `telesma` command in ~/.local/bin is a symlink to the clone")
        if sys.platform == "darwin":
            sc = desktop / "Telesma.command"
            ok(sc.is_file() and os.access(sc, os.X_OK) and f'--home "{projects}"' in sc.read_text(),
               "macOS: an executable Telesma.command on the desktop opens the start menu")
            app = home / "Applications" / "Telesma.app" / "Contents"
            ok(os.access(app / "MacOS" / "Telesma", os.X_OK) and "<string>Telesma</string>" in (app / "Info.plist").read_text()
               and f'--home "{projects}"' in (app / "Resources" / "Telesma.command").read_text(),
               "macOS: also Telesma.app in ~/Applications (Spotlight, hidden desktop icons)")
        out = drive(["bash", "-c", f'bash < "{ROOT / "install.sh"}"'], ["n"], env)
        ok("Telesma zaktualizowana" in out, "a second run updates instead of cloning")
        # a clone left on another branch (an earlier run without TELESMA_BRANCH) moves to the one asked for
        subprocess.run(["git", "-C", str(dest), "checkout", "-q", "-b", "old"], check=True)
        subprocess.run(["git", "-C", str(dest), "remote", "set-url", "origin", str(tmp / "elsewhere")], check=True)
        out = drive(["bash", "-c", f'bash < "{ROOT / "install.sh"}"'], ["n"], env)
        head = subprocess.run(["git", "-C", str(dest), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        ok("Telesma zaktualizowana" in out and head == branch, f"another TELESMA_REPO/BRANCH: the clone switches to them ({head})")
        # a clone that cannot get there — another history (the public 1.0.0 vs this one), the branch
        # already made by a failed run — is kept aside and Telesma is downloaded again
        subprocess.run(["git", "-C", str(dest), "checkout", "-q", "--orphan", "other"], check=True)
        subprocess.run(["git", "-C", str(dest), "commit", "-q", "-m", "unrelated", "--author", "t <t@example.com>"],
                       check=True, env=dict(os.environ, GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com"))
        subprocess.run(["git", "-C", str(dest), "branch", "-q", "-D", branch], check=True)
        subprocess.run(["git", "-C", str(dest), "branch", "-q", branch], check=True)     # same name, unrelated history
        (dest / "mine.txt").write_text("kept\n")
        out = drive(["bash", "-c", f'bash < "{ROOT / "install.sh"}"'], ["n"], env)
        aside = [p for p in home.iterdir() if p.name.startswith(".telesma.old-")]
        head = subprocess.run(["git", "-C", str(dest), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        ok("zachowana jako" in out and "Telesma pobrana" in out and head == branch and (dest / "telesma.sh").is_file(),
           "unrelated history on the branch asked for: the old clone aside, a fresh one downloaded")
        ok(len(aside) == 1 and (aside[0] / "mine.txt").read_text() == "kept\n", "the old clone kept whole")


def test_message_catalogs():
    print("messages — every key used in the launcher and the wizard is in every catalog, same placeholders")
    code = "".join((ROOT / f).read_text() for f in ("telesma.sh", "templates/setup/wizard.sh", "templates/setup/preflight.sh",
                                                     "templates/setup/home.sh", "templates/integrations/lib.sh",
                                                     "install.sh", "install.ps1"))
    used = {}
    for m in re.finditer(r"""msg ([a-z0-9_.]+) (?:'([^']*)'|"([^"]*)")""", code):
        used.setdefault(m.group(1), m.group(2) if m.group(2) is not None else m.group(3))
    # configure.py reads the same catalog for the summary table: L('key', 'English')
    for m in re.finditer(r"""\bL\('([a-z0-9_.]+)', '([^']*)'\)""", (ROOT / "templates/setup/configure.py").read_text()):
        used.setdefault(m.group(1), m.group(2))
    ok(len(used) > 50, f"{len(used)} message keys found in the code")
    for cat in sorted((ROOT / "templates/messages").glob("*.txt")):
        entries, malformed = {}, []
        for line in cat.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                k, sep, v = line.partition(" = ")
                if not sep or k in entries:
                    malformed.append(line)
                entries[k] = v
        ok(not malformed, f"{cat.name}: every line is a unique `KEY = text` {malformed}")
        missing = sorted(set(used) - set(entries))
        unused = sorted(set(entries) - set(used))
        ok(not missing, f"{cat.name}: no key missing {missing}")
        ok(not unused, f"{cat.name}: no key the code does not use {unused}")
        bad = [k for k in used if k in entries and entries[k].replace("%%", "").count("%s") != used[k].replace("%%", "").count("%s")]
        ok(not bad, f"{cat.name}: same number of %s placeholders {bad}")
    def lang(v):
        r = subprocess.run(["bash", "-c", f'SCRIPT_DIR="{ROOT}"; source "$SCRIPT_DIR/templates/messages/msg.sh"; '
                            f'msg_set_language "{v}"; echo "$MSG_LANG"; msg q.item "--- Question %s/%s ---" 2 5'],
                           capture_output=True, text=True)
        return r.stdout.split("\n", 1)
    ok(lang("pl")[0] == "pl" and lang("PL-pl")[0] == "pl" and lang("Polski")[0] == "pl", "pl, PL-pl, Polski → the Polish catalog")
    ok(lang("de")[0] == "en" and lang("")[0] == "en", "a language without a catalog → English")
    ok(lang("pl")[1] == "--- Pytanie 2/5 ---" and lang("de")[1] == "--- Question 2/5 ---", "translation with arguments; English fallback")
    # The system language with no LANG at all (Git Bash on Windows): the Windows locale from the
    # registry — a fake uname and a fake reg.exe with reg's real output (CRLF, indented)
    with tempfile.TemporaryDirectory() as d:
        b = Path(d) / "bin"
        b.mkdir()
        (b / "uname").write_text("#!/bin/sh\necho MINGW64_NT-10.0-26300\n")
        (b / "reg").write_text("#!/bin/sh\n"
                               "printf 'HKEY_CURRENT_USER\\\\Control Panel\\\\International\\r\\n"
                               "    LocaleName    REG_SZ    pl-PL\\r\\n\\r\\n'\n")
        for f in ("uname", "reg"):
            (b / f).chmod(0o755)

        def system_lang(**extra):
            env = dict(os.environ, PATH=f"{b}{os.pathsep}{os.environ.get('PATH', '')}", LANG="", LC_ALL="", LC_MESSAGES="")
            env.update(extra)
            r = subprocess.run(["bash", "-c", f'SCRIPT_DIR="{ROOT}"; source "$SCRIPT_DIR/templates/messages/msg.sh"; '
                                'msg_system_language'], capture_output=True, text=True, env=env)
            return r.stdout.strip()
        ok(system_lang() == "pl", "no LANG on Windows (Git Bash): the Windows locale from the registry → pl")
        ok(system_lang(LANG="de_DE.UTF-8") == "de", "LANG set: it wins over the registry")


FAKE_GH = r"""#!/bin/sh
# Fake GitHub CLI: an empty private repository (no default branch, no auto-merge, no protection).
case "$*" in
  --version) echo "gh version 2.0.0 (2026-01-01)" ;;
  "auth status") exit 0 ;;
  *"--json nameWithOwner"*) echo '{"nameWithOwner":"acme/shop"}' ;;
  *"--json visibility"*) echo PRIVATE ;;
  *"--json defaultBranchRef"*) echo "" ;;
  *allow_auto_merge*) echo false ;;
  *"/protection"*) exit 1 ;;
  *"/rules/branches/"*) echo 0 ;;
  *) exit 0 ;;
esac
"""


def test_integrations_wizard_tty():
    print("launcher — --integrations through a pseudo-terminal (fake gh, both integrations)")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        (project / "telesma" / "spec").mkdir(parents=True)
        (project / "telesma" / "spec" / "shop.md").write_text("# Shop\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "remote", "add", "origin", "https://github.com/acme/shop.git"], check=True)
        env = env_for(tmp)
        gh = fake_bin(tmp) / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        r = run_launcher(tmp, project)          # no tty → recommended profile, config.md exists
        c = project / "telesma" / "config.md"
        ok(r.returncode == 0 and c.is_file(), "config.md created before --integrations")
        # both; repo from origin; merge agent; checks empty (→ test); PR limit; Specky project; MCP default
        out = drive(["bash", str(LAUNCHER), "--integrations", str(project)],
                    ["3", "", "agent", "", "", "01ARZ3NDEKTSV4RRFFQ69G5FAV", ""], env)
        text = c.read_text()
        ok("No such file" not in out and "── Integration: requirement tracker" in out,
           "setup.sh subprocesses see SCRIPT_DIR / PROJECT_DIR / CONFIG_FILE")
        ok("Repository**: github" in text and "Repo**: acme/shop" in text and "Merge**: agent" in text,
           "GitHub section written from the origin remote")
        ok("Tracker**: specky" in text and "Tracker project**: 01ARZ3NDEKTSV4RRFFQ69G5FAV" in text,
           "Specky section written")
        ok("Required checks**: Specky contract check, test, Telesma: checks (local)" in text
           and (project / ".github" / "workflows" / "specky-ci.yml").is_file(),
           "both integrations: CI template copied, contract status added to the required checks")
        ok("do not cover main)" in out, "empty repository: the default branch falls back to main")
        ok("Bash(gh pr create:*)" in text and "mcp__plugin_specky_specky-record" in text,
           "permissions of both integrations added to Allowed commands")
        ok((project / "telesma" / "state" / "SPECKY.md").is_file(), "SPECKY.md cursor file created")


if __name__ == "__main__":
    test_profiles()
    test_tests_and_stacks()
    test_first_start_no_tty()
    test_not_a_project_folder()
    test_first_start_tty()
    test_new_project()
    test_experience_in_prompt()
    test_clarification_end()
    test_preflight()
    test_smart_app_control()
    test_update_offer()
    test_home_menu()
    test_installer()
    test_message_catalogs()
    test_integrations_wizard_tty()
    print()
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("OK — all checks passed")
