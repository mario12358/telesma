#!/usr/bin/env python3
"""Tests of the integrations (section ## Integrations) in telesma.sh — without starting Claude.

Extracts Python blocks (heredocs PYPLAN, PYCFG, PYMERGE) from telesma.sh and runs them on
fixture files: the plan validator with the (pr: #n) tag and the hint with the PR limit, the config
validator with the integration rules, and the config merge that brings an old config up to the
template. It also runs the launcher itself against a project with an old internal state version,
which must be refused before anything is touched. Above all it guards one thing: a project
WITHOUT integrations gets exactly what it got before them (a hint with no additions, zero warnings).

Run: python3 tools/test-integrations.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TELESMA = Path(__file__).resolve().parent.parent
SCRIPT = (TELESMA / "telesma.sh").read_text(encoding="utf-8")
TEMPLATE = (TELESMA / "templates" / "config.md").read_text(encoding="utf-8")
FAILURES = []


def ok(cond, desc):
    print(("  ✓ " if cond else "  ✗ ") + desc)
    if not cond:
        FAILURES.append(desc)


def heredoc(marker):
    m = re.search(r"<<'" + marker + r"'[^\n]*\n(.*?)\n" + marker + r"\n", SCRIPT, re.S)
    assert m, f"no heredoc {marker} in telesma.sh"
    return m.group(1)


def run(marker, *args, cwd=None):
    r = subprocess.run([sys.executable, "-", *map(str, args)], input=heredoc(marker),
                       capture_output=True, text=True, cwd=cwd)
    return r.stdout, r.stderr, r.returncode


def config(**fields):
    """The config template with field values replaced (label → value)."""
    t = TEMPLATE
    t = t.replace("[e.g. pytest -v, npm test, cargo test]", "pytest")
    t = t.replace("[e.g. pytest -v --tb=short, npm run test:all]", "pytest -q")
    t = t.replace("[e.g. ruff check, eslint, cargo fmt -- none if you don't use one]", "none")
    for label, value in fields.items():
        t, n = re.subn(r"^- \*\*" + re.escape(label) + r"\*\*:.*$", f"- **{label}**: {value}", t, count=1, flags=re.M)
        assert n == 1, f"field {label} does not exist in the template"
    return t


PLAN_BASE = """# Plan

## Tasks

### Phase 1: Start

- [x] Task 1.1: Skeleton (pr: #5)
- [ ] Task 1.2: Model (pr: #6)
- [ ] Task 1.3: API (pr: #7) (requires: 1.2)
- [ ] Task 1.4: Screen (requires: 1.2)
- [ ] Task 1.5: Docs
"""

GITHUB = {"Repository": "github", "Repo": "o/r", "Auto-push": "yes", "Required checks": "test"}


def prepare(tmp, plan, cfg):
    (tmp / "PLAN.md").write_text(plan, encoding="utf-8")
    (tmp / "config.md").write_text(cfg, encoding="utf-8")
    (tmp / "g").mkdir(exist_ok=True)
    (tmp / "g" / "general.md").write_text("# g\n", encoding="utf-8")
    (tmp / "spec").mkdir(exist_ok=True)


def plan_hint(tmp):
    out, err, rc = run("PYPLAN", tmp / "PLAN.md", tmp / "config.md", tmp / "g", tmp / "spec")
    assert rc == 0, err
    return out.split("\n", 1)[0].removeprefix("HINT:"), err


def test_plan():
    print("PYPLAN — hint and (pr: #n)")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # No integration, no tags: exactly what it used to be
        prepare(tmp, PLAN_BASE.replace(" (pr: #5)", "").replace(" (pr: #6)", "").replace(" (pr: #7)", ""), config())
        hint, err = plan_hint(tmp)
        ok(hint == "1.2", f"without integration the hint = the first [ ] (got: {hint!r})")
        ok("WARNING" not in err and "ERROR" not in err, "without integration: zero warnings")

        # No integration, but (pr:) tags in the plan → warning, the hint skips PRs in progress
        prepare(tmp, PLAN_BASE, config())
        hint, err = plan_hint(tmp)
        ok("Repository: none" in err, "(pr:) tags without integration → WARNING")
        ok(hint == "1.5", f"PRs in progress skipped, tasks depending on them too (got: {hint!r})")

        # github integration, limit 3: 1.5 independent + PR counter
        prepare(tmp, PLAN_BASE, config(**GITHUB, **{"Open PR limit": "3"}))
        hint, err = plan_hint(tmp)
        ok(hint.startswith("1.5 | open PRs: 2/3 (#6→1.2, #7→1.3)"), f"hint with the PR counter (got: {hint!r})")
        ok("WARNING" not in err, "with integration: (pr:) tags without a warning")

        # Limit reached (2/2)
        prepare(tmp, PLAN_BASE, config(**GITHUB, **{"Open PR limit": "2"}))
        hint, _ = plan_hint(tmp)
        ok(hint.startswith("PR LIMIT REACHED (2/2"), f"limit → TELESMA WAITING in the hint (got: {hint!r})")
        ok("queued: 1.5" in hint, "limit: the queue is still shown")

        # Nothing independent → a chain off an unmerged PR
        prepare(tmp, PLAN_BASE.replace("- [ ] Task 1.5: Docs\n", ""),
                config(**GITHUB, **{"Open PR limit": "3"}))
        hint, _ = plan_hint(tmp)
        ok(hint.startswith("1.4 (chain — depends on unmerged: 1.2 (PR #6)"), f"chain as the last option (got: {hint!r})")

        # A phase with [ ] + (pr:) does not collapse in the prompt (the checkbox decides)
        out, _, _ = run("PYPLAN", tmp / "PLAN.md", tmp / "config.md", tmp / "g", tmp / "spec")
        ok("- [ ] Task 1.2: Model (pr: #6)" in out, "a task with a PR in progress stays in the prompt")


def test_config():
    print("PYCFG — integration rules")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        prepare(tmp, PLAN_BASE, config())
        out, _, _ = run("PYCFG", tmp / "config.md", tmp / "PLAN.md")
        ok("Integrations" not in out, "default config (none/none): no remarks about integrations")

        prepare(tmp, PLAN_BASE, config(**{"Repository": "github", "Merge": "agent"}))
        out, _, _ = run("PYCFG", tmp / "config.md", tmp / "PLAN.md")
        ok("E:**Repo**" in out, "github without Repo → error")
        ok("E:**Auto-push**" in out, "github with Auto-push: no → error")
        ok("E:**Required checks**" in out, "agent without checks → error")
        ok("W:permission judge disabled" in out, "Auto-approve: no → warning")

        prepare(tmp, PLAN_BASE, config(**{"Repository": "github", "Repo": "o/r", "Auto-push": "yes",
                                          "Merge": "manual", "Auto-approve": "yes"}))
        out, _, _ = run("PYCFG", tmp / "config.md", tmp / "PLAN.md")
        ok(not [l for l in out.split("\n") if l.startswith("E:")], f"valid github/manual config: zero errors ({out.strip()!r})")

        prepare(tmp, PLAN_BASE, config(**{"Repository": "gitlab", "Tracker": "specky"}))
        out, _, _ = run("PYCFG", tmp / "config.md", tmp / "PLAN.md")
        ok("E:**Repository**" in out, "unknown Repository value → error")
        ok("E:**Tracker project**" in out, "specky without project_id → error")

        prepare(tmp, PLAN_BASE, config(**{"Tracker": "specky", "Tracker project": "01M3A4YYQKVWPRBEGHA699B6KK"}))
        out, _, _ = run("PYCFG", tmp / "config.md", tmp / "PLAN.md")
        ok("Tracker" not in out, "specky with a ULID: no remarks")


def test_merge():
    print("PYMERGE — an old config gets the missing section and fields")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        old = re.sub(r"^## Integrations\n.*?(?=^## )", "", TEMPLATE, flags=re.M | re.S)
        old = re.sub(r"^- \*\*Language\*\*:.*\n(?:  <!--.*\n)*", "", old, flags=re.M)
        old = old.replace("- **Repository**: none", "")
        assert "## Integrations" not in old and "**Language**" not in old
        target = tmp / "config.md"
        target.write_text(old.replace("- **Clarified**: no", "- **Clarified**: yes"), encoding="utf-8")
        out, err, rc = run("PYMERGE", TELESMA / "templates" / "config.md", target)
        ok(rc == 0, f"merge passed ({err.strip()!r})")
        t = target.read_text(encoding="utf-8")
        ok(t.count("## Integrations") == 1 and "- **Repository**: none" in t,
           "the ## Integrations section added once, values 'none'")
        project = re.search(r"^## Project\n(.*?)(?=^## )", t, re.M | re.S).group(1)
        ok("- **Language**: en" in project, "Language added under ## Project with the default 'en'")
        ok("- **Clarified**: yes" in t, "local value kept")


def run_launcher(tmp, project):
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "claude"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
               TELESMA_NO_UPDATE_CHECK="1")
    return subprocess.run(["bash", str(TELESMA / "telesma.sh"), str(project)], env=env,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          start_new_session=True, timeout=60)


def test_version_gate():
    print("Format gate — a pre-release project is refused before anything is touched")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "project"
        (project / "spec").mkdir(parents=True)
        (project / "spec" / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (project / "ralph").mkdir()
        (project / "ralph" / ".ralph-version").write_text("18\n", encoding="utf-8")
        r = run_launcher(tmp, project)
        ok(r.returncode == 1, f"ralph/.ralph-version without telesma/ → exit 1 (got: {r.returncode})")
        ok("pre-release version" in r.stdout and "migration tool" in r.stdout,
           "the message points at the migration tool")
        ok(sorted(p.name for p in project.iterdir()) == ["ralph", "spec"]
           and sorted(p.name for p in (project / "ralph").iterdir()) == [".ralph-version"],
           "nothing was created, moved or changed (no telesma/)")

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "project"
        (project / "ralph").mkdir(parents=True)
        (project / "ralph" / "notes.md").write_text("the user's own directory\n", encoding="utf-8")
        r = run_launcher(tmp, project)
        ok((project / "ralph" / "notes.md").is_file() and (project / "telesma" / "spec").is_dir(),
           "a ralph/ directory without .ralph-version is the user's own — left alone")

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        project = tmp / "project"
        (project / "telesma" / "state").mkdir(parents=True)
        (project / "telesma" / "state" / ".telesma-version").write_text("17\n", encoding="utf-8")
        r = run_launcher(tmp, project)
        ok(r.returncode == 1 and not (project / "telesma" / "spec").exists(),
           "telesma/ at a format below 18 → exit 1, nothing created")


def test_specky_template():
    print("Specky template — tool names match Specky v0.45 (core + record)")
    d = TELESMA / "templates" / "integrations" / "tracker" / "specky"
    instr = (d / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    for gone in ("get_requirements", "mark_criterion_tested", "set_realization_status", "resolve_",
                 "stale_hash |", "failing_criterion"):
        ok(gone not in instr, f"INSTRUCTIONS.md does not use the removed name {gone!r}")
    for needed in ("requirement_hash", "mark_criteria_tested", "more_after_next_seq", "Specky-Req: none",
                   "v<n>.<r>", "failing_pull_requests", "raise_spec_issue", "get_requirement_history",
                   "can_propose", "### 18.8"):
        ok(needed in instr, f"INSTRUCTIONS.md covers {needed!r}")
    perms = [l.strip() for l in (d / "permissions.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    ok(perms == ["mcp__plugin_specky_specky", "mcp__plugin_specky_specky-record", "mcp__claude_ai_Specky"],
       f"permissions: plugin core, plugin record, claude.ai connector ({perms})")
    ci = (d / "specky-ci.yml").read_text(encoding="utf-8")
    on_block = "\n".join(l for l in ci.split("\njobs:")[0].split("\non:")[-1].splitlines() if not l.lstrip().startswith("#"))
    ok("continue-on-error: true" in ci and "v0.45.0" in ci and "paths" not in on_block,
       "specky-ci.yml: v0.45 header, continue-on-error on the test step, no path filter in on:")
    gh = (TELESMA / "templates" / "integrations" / "git" / "github" / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    ok("Specky-Req: none" in gh, "GitHub 17.3 mentions Specky-Req: none")


if __name__ == "__main__":
    test_plan()
    test_config()
    test_merge()
    test_version_gate()
    test_specky_template()
    print()
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("OK — all checks passed")
