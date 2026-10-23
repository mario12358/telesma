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

def fake_bin(tmp):
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    claude = b / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    return b


def env_for(tmp):
    return dict(os.environ, PATH=f"{fake_bin(tmp)}{os.pathsep}{os.environ.get('PATH', '')}", TELESMA_NO_UPDATE_CHECK="1")


def run_launcher(tmp, project, *args):
    return subprocess.run(["bash", str(LAUNCHER), str(project), *args], env=env_for(tmp), capture_output=True,
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
        os.environ.update(env)
        os.execvp(cmd[0], cmd)
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


def test_first_start_tty():
    print("launcher — first start and --setup through a pseudo-terminal")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "p"
        (project / "telesma" / "spec").mkdir(parents=True)
        (project / "telesma" / "spec" / "shop.md").write_text("# Shop\n")
        (project / "package.json").write_text('{"scripts":{"test":"vitest run"}}')
        env = env_for(tmp)
        # profile minimal, git init yes, detected stack yes, four commands + smoke kept, judge off,
        # tier none, language pl
        out = drive(["bash", str(LAUNCHER), str(project)],
                    ["minimal", "", "", "", "", "", "", "", "off", "none", "pl"], env)
        c = project / "telesma" / "config.md"
        ok(c.is_file() and "=== Next steps ===" in out and "-i" in out, "first start: wizard ran to the next steps")
        s = kv(cfg("status", c))
        ok(s["judge"] == "off" and s["checks"] == "none" and s["language"] == "pl" and s["test_command"] == "npm test",
           f"answers applied: judge={s['judge']} checks={s['checks']} language={s['language']} tests={s['test_command']}")
        ok((project / ".git").is_dir(), "git init offered and done")
        ok("Integrations" not in out.split("=== Configuration")[0].split("Quality checks")[-1],
           "minimal profile does not ask about integrations")

        out = drive(["bash", str(LAUNCHER), str(project), "--setup"], ["3", "security", "5", "n", "y", "q"], env)
        s = kv(cfg("status", c))
        ok(s["checks"] == "security" and s["recordings"] == "yes" and s["screenshots"] == "no",
           f"--setup menu: checks={s['checks']} recordings={s['recordings']} screenshots={s['screenshots']}")
        ok((project / "telesma" / "spec" / "APP_FLOW.md").is_file(), "recordings on → APP_FLOW.md template created")
        ok("Done" in out and "=== Configuration" in out, "menu ends with the summary")


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
    test_first_start_tty()
    test_integrations_wizard_tty()
    print()
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("OK — all checks passed")
