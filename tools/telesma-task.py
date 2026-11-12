#!/usr/bin/env python3
"""The task loop's mechanical steps, done by a script instead of by the model.

    telesma-task.py next [--full]          the next task and its context; reserves it
    telesma-task.py done [<id>] [-m TEXT] [--trailer "Key: value"]… [--only PATH]…
                                           finish the reserved task: tests, checks, tick, report row, commit
    telesma-task.py commit --kind K -m TEXT [--trailer …]… [--only PATH]…
                                           a commit that is not a task (K: changes, regression, survey,
                                           bugfix, review, artifacts, backlog): the same tests and checks
    telesma-task.py suite                  the full suite when one is due (end of a phase, after a
                                           change request): Test status paragraph, metrics, phase tag
    telesma-task.py changes                the next change request with its context and earlier decisions
    telesma-task.py release vX.Y.Z -m TEXT  the release version tag, after the person's yes (the guard asks):
                                           clean tree, green full suite on this state, scenarios committed,
                                           release checks; annotated, never -f, never pushed
    telesma-task.py session-start [--continue]
                                           the launcher, before a session: limits snapshot, session counters;
                                           exit 3 when the previous session ran out of its budget
    telesma-task.py changes-done FILE --kind bug|correction|feature -m SUMMARY
                         [--source X.Y|unknown] [--detected-by WHO] [--withdrawn]
                                           check the plan edit, write Change history, move, commit

The model decides WHEN a task is finished; WHAT happens then is this script: it chooses the files
(everything `git status` shows, minus `Ignore on commit`), runs the project's tests and the quality
checks on exactly those files, ticks the plan, writes the `Task history` row and commits with the
footer. `--only PATH` narrows the files to those under PATH (the survey commits telesma/ only;
anything else in the tree stays as it is). The model never assembles a `git add` / `git commit` itself, so nothing has to be guessed
from the shape of a command (docs/ARCHITECTURE.md §23).

The script runs from the Telesma clone (it is not copied into the project, so the agent does not
rewrite it without a question); the project is the git work tree of the current directory, or
`--project DIR`. The reservation and the counters live in `.git/telesma-task/session.json` — this
machine's data, nothing to commit.

Exit codes: 0 = done / committed / issued (or a terminal state was reported), 1 = refused,
2 = usage error.
Stdlib only, Python 3.9+.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TELESMA = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import telesma_state as ts  # noqa: E402
import telesma_github as ghf  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

KINDS = ("changes", "regression", "survey", "bugfix", "review", "artifacts", "backlog", "release")
# This machine's files: never part of a commit, whatever the config says
ALWAYS_EXCLUDED = ("telesma/state/PERMISSIONS.jsonl", "telesma/state/CHECKS.jsonl",
                   "telesma/state/.telesma-lock/", "telesma/state/.questions-before-plan", "telesma/state/WAITING.md",
                   ".claude/settings.local.json", ".claude/settings.local.json.bak")
TEST_TIMEOUT = int(os.environ.get("TELESMA_TEST_TIMEOUT", "1500"))
OUTPUT_TAIL = 60
SPEC_PRINT_LIMIT = 400        # lines of one spec / UI fragment printed by `next`
SMALL_FILE = 200              # a spec file this short is printed whole
BASH = shutil.which("bash")


class Refused(Exception):
    pass


# --- small helpers --------------------------------------------------------------------------

def self_command():
    path = os.path.abspath(sys.argv[0])
    return f"python3 {path}" if " " not in path else f'python3 "{path}"'


def now():
    return datetime.datetime.now()


def git(root, *args, check=True, input_bytes=None, env=None):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, input=input_bytes, env=env)
    if check and r.returncode != 0:
        raise Refused(f"git {' '.join(args[:2])} failed: {r.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return r


def project_root(argv_project):
    start = argv_project or os.getcwd()
    r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    root = r.stdout.strip() if r.returncode == 0 else ""
    if not root or not os.path.isfile(os.path.join(root, ts.CONFIG)):
        raise Refused(f"no Telesma project here ({start}): a git work tree with {ts.CONFIG} is needed")
    return root


def session_path(root):
    r = git(root, "rev-parse", "--git-path", "telesma-task")
    d = r.stdout.decode().strip()
    d = d if os.path.isabs(d) else os.path.join(root, d)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "session.json")


def load_session(root):
    try:
        with open(session_path(root), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_session(root, data):
    ts.atomic_write(session_path(root), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def tail(text, n=OUTPUT_TAIL):
    lines = (text or "").rstrip().split("\n")
    return "\n".join(lines[-n:])


# --- the files of a commit ------------------------------------------------------------------

def changed_files(root):
    """Everything `git status` reports (modified, deleted, renamed, untracked one by one)."""
    raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    parts = raw.decode("utf-8", "surrogateescape").split("\0")
    out, i = [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        out.append(path)
        if "R" in xy or "C" in xy:
            if i < len(parts) and parts[i]:
                out.append(parts[i])        # the source of a rename leaves the tree
            i += 1
    return sorted(set(out))


def commit_set(root, cfg, only=None):
    patterns = ts.ignore_patterns(cfg)
    files, excluded = [], []
    for p in changed_files(root):
        if only and not any(p == o.rstrip("/") or p.startswith(o.rstrip("/") + "/") for o in only):
            continue                        # outside --only: neither committed nor reported as excluded
        if any(p == x or (x.endswith("/") and p.startswith(x)) for x in ALWAYS_EXCLUDED) \
                or ts.ignored(p, patterns):
            excluded.append(p)
        else:
            files.append(p)
    return files, excluded


def staged(root):
    raw = git(root, "diff", "--cached", "--name-only", "-z").stdout.decode("utf-8", "surrogateescape")
    return [p for p in raw.split("\0") if p]


# --- tests ----------------------------------------------------------------------------------

ZERO = [re.compile(p, re.I | re.M) for p in (
    r"collected 0 items", r"\bno tests ran\b", r"No tests found", r"No test files found",
    r"^\s*0 passing\b", r"\bRan 0 tests?\b", r"\bTests:\s+0 total\b", r"\bno test files\b",
    r"\b0 tests? (?:run|executed|passed)\b", r"\bexecuted 0 tests?\b")]
POSITIVE = [re.compile(p, re.I | re.M) for p in (
    r"\b([1-9][0-9]*) (?:passed|passing)\b", r"\bRan ([1-9][0-9]*) tests?\b",
    r"\bTests:\s+([1-9][0-9]*) passed\b", r"^ok\s+\S+", r"test result: ok\. ([1-9][0-9]*) passed",
    r"\b([1-9][0-9]*) tests? (?:completed|succeeded|passed)\b", r"\b([1-9][0-9]*) examples?, 0 failures\b")]


def zero_tests(output):
    """The "0 tests" guard: a run that reports no executed test counts as a failure, even with
    exit code 0 — it is almost always a wrong pattern or an empty test directory."""
    if any(p.search(output) for p in POSITIVE):
        return False
    running = re.findall(r"^running (\d+) tests?$", output, re.M)       # cargo
    if running and all(n == "0" for n in running):
        return True
    return any(p.search(output) for p in ZERO)


def summary_of(output):
    for p in (r"(\d+ passed(?:, \d+ \w+)*)", r"Tests:\s+([^\n]+)", r"(\d+ passing)", r"(Ran \d+ tests?)",
              r"test result: ok\. (\d+ passed)"):
        m = re.findall(p, output)
        if m:
            return m[-1].strip()[:60]
    return "green"


def run_command(root, label, cmd):
    print(f"  {label}: {cmd}", flush=True)
    start = now()
    # bash, as when the model ran the command through its Bash tool (Git Bash on Windows); a plain
    # shell only where there is no bash at all
    argv = [BASH, "-c", cmd] if BASH else cmd
    try:
        r = subprocess.run(argv, shell=not BASH, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        raise Refused(f"{label} did not finish within {TEST_TIMEOUT} s: `{cmd}`\n{tail(out)}")
    out = r.stdout.decode("utf-8", "replace")
    secs = int((now() - start).total_seconds())
    if r.returncode != 0:
        raise Refused(f"{label} failed (exit {r.returncode}, {secs} s): `{cmd}`\n{tail(out)}")
    return out, secs


def tests_trusted(root):
    """`## Tests` names commands that run on this machine; they run only once the person has
    confirmed the section here (templates/setup/trust.py — the launcher is the only writer)."""
    sys.path.insert(0, os.path.join(TELESMA, "templates", "setup"))
    try:
        import trust
    except ImportError:
        return False
    return "Tests" not in trust.untrusted(root)


def run_tests(root, cfg, files):
    """Lint (when `Lint before commit: yes`), the test command, the smoke suite. A commit that
    touches only telesma/ (state files, the survey, processed changes) runs no project tests.
    Returns the text for the Tests cell."""
    if not any(not p.startswith("telesma/") for p in files):
        return "state files only"
    test_cmd = cfg.field("Tests", "Test command")
    smoke = cfg.field("Tests", "Smoke suite")
    lint = cfg.field("Tests", "Linter/formatter")
    wanted = [x for x in (test_cmd, smoke, lint) if not ts.unset(x)]
    if test_cmd.strip().startswith("["):
        raise Refused("## Tests → Test command is still the template placeholder — set the project's test "
                      "command in telesma/config.md (or `none` when the project has no tests)")
    if wanted and not tests_trusted(root):
        raise Refused("the ## Tests section of telesma/config.md is not confirmed on this machine (it changed "
                      "since the last start) — its commands are not run. This is not a test failure: report "
                      "TELESMA BLOCKED; the person confirms the section at the next start of the launcher")
    if ts.is_yes(cfg.field("Tests", "Lint before commit")) and not ts.unset(lint):
        run_command(root, "lint", lint)
    if ts.unset(test_cmd):
        return "no tests (Test command: none)"
    out, secs = run_command(root, "tests", test_cmd)
    if zero_tests(out):
        raise Refused(f"the test command reported 0 executed tests: `{test_cmd}` — a configuration error "
                      f"(wrong pattern, empty test directory), not a pass\n{tail(out, 20)}")
    result = f"{summary_of(out)} ({secs} s)"
    if not ts.unset(smoke) and smoke.strip() != test_cmd.strip():
        sout, ssecs = run_command(root, "smoke suite", smoke)
        if zero_tests(sout):
            raise Refused(f"the smoke suite reported 0 executed tests: `{smoke}`\n{tail(sout, 20)}")
        result += f"; smoke {summary_of(sout)}"
    return result


# --- checks ---------------------------------------------------------------------------------

def run_checks(root, files):
    """The commit-point quality checks on exactly `files` (telesma/checks/telesma-checks.py
    --files-commit). Returns the warnings text; raises Refused on a blocking finding."""
    runner = os.path.join(root, "telesma", "checks", "telesma-checks.py")
    if not os.path.isfile(runner):
        return ""
    r = subprocess.run([sys.executable, runner, "--files-commit"], cwd=root, capture_output=True,
                       input="\0".join(files).encode("utf-8", "surrogateescape"), timeout=900)
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    if r.returncode == 2:
        raise Refused("telesma/checks/telesma-checks.py does not know --files-commit (an older or edited copy) "
                      "— report TELESMA BLOCKED; the launcher updates the delivered copy at its next start")
    if r.returncode != 0:
        raise Refused("quality checks refused the commit:\n" + out +
                      "\nFix what they name and run done again. If a finding is wrong, do NOT get around it: "
                      "TELESMA BLOCKED with the fingerprint — the person writes the exception.")
    return "" if out.startswith(("Checks disabled", "Checks (commit): clean")) else out


def record_evidence(root):
    runner = os.path.join(root, "telesma", "checks", "telesma-checks.py")
    if os.path.isfile(runner):
        subprocess.run([sys.executable, runner, "--record-commit"], cwd=root, capture_output=True, timeout=120)


# --- commit ---------------------------------------------------------------------------------

def make_commit(root, files, excluded, subject, body, trailers):
    """Stage exactly `files` (deletions included), drop from the index what is excluded, commit."""
    env = dict(os.environ, GIT_LITERAL_PATHSPECS="1")
    if files:
        git(root, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
            input_bytes="\0".join(files).encode("utf-8", "surrogateescape"), env=env)
    leftovers = [p for p in staged(root) if p not in files]
    if leftovers:
        git(root, "reset", "-q", "--pathspec-from-file=-", "--pathspec-file-nul",
            input_bytes="\0".join(leftovers).encode("utf-8", "surrogateescape"), env=env)
    if not staged(root):
        raise Refused("nothing to commit")
    message = subject.strip()
    if body and body.strip():
        message += "\n\n" + body.strip()
    if trailers:
        message += "\n\n" + "\n".join(t.strip() for t in trailers if t.strip())
    message += "\n\n" + ts.FOOTER + "\n"
    r = git(root, "commit", "-q", "-F", "-", input_bytes=message.encode("utf-8"), check=False)
    if r.returncode != 0:
        raise Refused("git commit failed (a pre-commit hook of the project?):\n"
                      + tail((r.stdout + r.stderr).decode("utf-8", "replace")))
    return git(root, "rev-parse", "HEAD").stdout.decode().strip()


def check_trailers(trailers):
    for t in trailers:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*: \S.*", t.strip()) or "\n" in t:
            raise Refused(f"--trailer must be one line `Key: value`: {t!r}")
        if t.lower().startswith(("co-authored-by", "claude-session", "generated")):
            raise Refused(f"--trailer {t.split(':')[0]}: the footer is only `{ts.FOOTER}`")


def short_subject(text, limit=72):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def commits_resolved(root, report):
    """REPORT.md with `this commit` rows pointing at their commit: a row cannot name the SHA of the
    commit it is part of, so the next write of the report does (found by the subject `done` gave it)."""
    if "this commit" not in (report or ""):
        return report
    r = git(root, "log", "-500", "--format=%h%x09%s", check=False)
    newest = {}
    for line in r.stdout.decode("utf-8", "replace").split("\n"):
        sha, _, subject = line.partition("\t")
        if sha and subject:
            newest.setdefault(subject, sha)
    return ts.resolve_history_commits(report, lambda name: newest.get(short_subject(f"Telesma: {name}")))


# --- the GitHub flow (section 17, change plan Z5) ------------------------------------------

WAITING_FILE = "telesma/state/WAITING.md"
MAX_WAIT = 480                # seconds `next` may wait for checks: the Bash tool stops at 600


def merge_mode(cfg):
    m = cfg.field("Integrations", "Merge", "agent").strip().lower()
    return m if m in ("auto", "agent", "manual") else "agent"


def wait_limit(cfg):
    m = re.match(r"(\d+)\s*(s|sec|m|min)?", cfg.field("Integrations", "Wait for merge", "10 min").strip().lower())
    if not m:
        return MAX_WAIT
    secs = int(m.group(1)) * (1 if (m.group(2) or "m").startswith("s") else 60)
    return min(secs, MAX_WAIT)


def apply_derived(root, prs, session):
    """What GitHub says, written into the state files of the current tree: a task whose PR is merged
    is ticked and gets its history row (once), and the full-suite paragraphs run on main and not yet
    committed are put back. Idempotent — a checkout or a pull may throw the uncommitted state files
    away, and this writes them again from the same facts. Returns the phases a merge completed."""
    plan_path, report_path = os.path.join(root, ts.PLAN), os.path.join(root, ts.REPORT)
    text = ts.read_text(plan_path) or ""
    report = ts.read_text(report_path) or ""
    plan = ts.Plan(text)
    # (pr: #n) is committed on the task's branch; main learns it from GitHub, by the PR's title
    by_name = ghf.task_prs(prs)
    lines = text.split("\n")
    for o in plan.order:
        if o["done"] or o["pr"] is not None:
            continue
        pr = ghf.pr_for(ts.name_of(plan, o), by_name)
        if pr:          # CLOSED too: a task whose PR was closed by hand stops the flow, it never gets a second PR
            lines[o["idx"]] = lines[o["idx"]].rstrip() + f" (pr: #{pr['number']})"
    text = "\n".join(lines)
    plan = ts.Plan(text)
    phases = []
    for o in plan.order:
        if o["done"] or o["pr"] is None:
            continue
        pr = prs.get(o["pr"])
        if not pr or pr.get("state") != "MERGED":
            continue
        name = ts.name_of(plan, o)
        text = ts.tick(text, o["idx"])
        if f"| {ts.cell(name)} |" not in report:
            sha = ((pr.get("mergeCommit") or {}).get("oid") or "")[:9]
            fixes = int((session.get("pr_fixes") or {}).get(str(o["pr"]), 0))
            report = ts.add_history_row(report, [name, "✅", "merged (checks green)", fixes + 1,
                                                 f"{sha} (#{o['pr']})".strip(), now().strftime("%Y-%m-%d %H:%M")])
        if o["phase"] and o["phase"] not in phases:
            phases.append(o["phase"])
    for run in session.get("carry") or []:
        if run["paragraph"] not in report:
            report = ts.add_test_run(report, run["paragraph"], run.get("counts"), run.get("date", ""))
    if text != (ts.read_text(plan_path) or ""):
        ts.atomic_write(plan_path, text)
        done_n, total = ts.Plan(text).counts()
        report = ts.set_progress(report, done_n, total)
    if report != (ts.read_text(report_path) or ""):
        ts.atomic_write(report_path, report)
    complete = ts.Plan(text)
    return [p for p in phases if complete.phase_complete(p)]


def restore_state_files(root):
    """The derived, uncommitted state edits are dropped before a checkout (apply_derived writes them
    again); anything else uncommitted outside a task is the person's and stops the flow."""
    for rel in (ts.PLAN, ts.REPORT):
        if git(root, "ls-files", "--error-unmatch", rel, check=False).returncode == 0:
            git(root, "checkout", "-q", "--", rel)


def print_fix(fix):
    print(f"TELESMA PR FIX: PR #{fix['n']} ({fix.get('name') or fix.get('kind')}) — required check red: "
          f"{', '.join(fix.get('red') or ['?'])}. Fix {fix.get('count')} of {fix.get('max')}.\n\n"
          f"You are on its branch `{fix['branch']}`. Diagnose with `gh pr checks {fix['n']}` and "
          "`gh run view --log-failed` (read-only), fix it on this branch, write the Problem log entry "
          f"`[date] [check] PR #{fix['n']} — <check>: <cause>`, then `{self_command()} done` — it commits and "
          "pushes the fix to the same PR (section 17.4). Never a new PR for the same task.")


def reconcile(root, cfg, session):
    """Section 17.1 by the script: back to main as GitHub has it, merge what is green (Merge: agent),
    re-point and rebase chained successors, tick what was merged, stop on a closed PR, hand out a red
    check as a fix, and say WAITING at the open-PR limit. Returns (exit code to stop with, or None to
    go on and choose a task; the PRs; the base branch)."""
    main = ghf.base_branch(root)
    waiting = os.path.join(root, WAITING_FILE)
    rb = session.get("rebase")
    if rb:
        left = ghf.continue_rebase(root) if ghf.rebase_in_progress(root) else []
        if left:
            print("TELESMA REBASE CONFLICT on `" + rb["branch"] + "`: " + ", ".join(left) + "\nResolve the conflict "
                  "markers in these files (edit only — no git commands), then run next again; it stages them and "
                  "continues the rebase.")
            return 0, None, main
        ghf.push(root, rb["branch"], force=True)
        session.pop("rebase", None)
        save_session(root, session)
    if session.get("pr_fix"):
        print_fix(session["pr_fix"])
        return 0, None, main
    files, _ = commit_set(root, cfg)
    stray = [p for p in files if p not in (ts.PLAN, ts.REPORT)]
    if stray:
        text = ("TELESMA BLOCKED\n\nProblem: uncommitted changes outside a task: " + ", ".join(stray[:8]) +
                "\nNeed help with: are they yours? Commit or stash them; work of Telesma goes through done.")
        write_blocked(root, text)
        print(text)
        return 0, None, main
    git(root, "fetch", "-q", "origin")
    prs = ghf.list_prs(root)
    restore_state_files(root)
    ghf.sync_main(root, main)
    apply_derived(root, prs, session)
    plan = ts.load_plan(root)
    required = ghf.required_checks(cfg)
    mode = merge_mode(cfg)
    side = session.get("side_prs") or []
    ours = sorted({o["pr"] for o in plan.order if not o["done"] and o["pr"] is not None} | {x["n"] for x in side})
    if mode == "agent":
        merged = False
        for n in ours:
            pr = prs.get(n)
            if not pr or pr.get("state") != "OPEN" or ghf.checks_state(pr, required)[0] != "green":
                continue
            successors = [q for q in prs.values() if q.get("state") == "OPEN" and q.get("baseRefName") == pr["headRefName"]]
            for q in successors:
                ghf.repoint(root, q["number"], main)            # 1. the successor's new base FIRST
            ghf.merge(root, n, delete_branch=not successors)     # 2. squash, no --delete-branch under a chain
            todo = session.setdefault("rebase_todo", [])
            todo += [{"branch": q["headRefName"], "old": pr["headRefName"], "n": q["number"]} for q in successors]
            merged = True
        if merged:
            save_session(root, session)
            git(root, "fetch", "-q", "origin")
            prs = ghf.list_prs(root)
            restore_state_files(root)
            ghf.sync_main(root, main)
            apply_derived(root, prs, session)
    while session.get("rebase_todo"):
        t = session["rebase_todo"][0]
        left = ghf.rebase_onto(root, main, t["old"], t["branch"])
        session["rebase_todo"] = session["rebase_todo"][1:]
        if left:
            session["rebase"] = t
            save_session(root, session)
            print(f"TELESMA REBASE CONFLICT on `{t['branch']}` (PR #{t['n']}, re-pointed onto {main}): " + ", ".join(left) +
                  "\nResolve the conflict markers in these files (edit only — no git commands), then run next again.")
            return 0, None, main
        ghf.push(root, t["branch"], force=True)
        restore_state_files(root)
        ghf.sync_main(root, main)
        apply_derived(root, prs, session)
        save_session(root, session)
    for o in plan.order:
        if not o["done"] and o["pr"] is not None and (prs.get(o["pr"]) or {}).get("state") == "CLOSED":
            text = (f"TELESMA BLOCKED\n\nTask: {ts.name_of(plan, o)}\nProblem: PR #{o['pr']} was closed without a merge.\n"
                    "Need help with: why was it closed? Telesma does not open a second PR for the same task.")
            write_blocked(root, text)
            print(text)
            return 0, None, main
    session["side_prs"] = [x for x in side if (prs.get(x["n"]) or {}).get("state") == "OPEN"]
    head_report = git(root, "show", f"HEAD:{ts.REPORT}", check=False).stdout.decode("utf-8", "replace")
    session["carry"] = [r for r in session.get("carry") or [] if r["paragraph"] not in head_report]
    apply_derived(root, prs, session)
    # a phase whose tasks are all merged and that has no phase tag yet owes its regression on main;
    # the tag, placed by a green suite, is what says it ran
    done_plan = ts.load_plan(root)
    phases = [pid for pid, ph in done_plan.phases.items()
              if not ph["archived"] and done_plan.phase_complete(pid)
              and any(o["pr"] is not None for o in done_plan.order if o["phase"] == pid)
              and git(root, "rev-parse", "-q", "--verify", f"refs/tags/telesma/phase-{pid}", check=False).returncode != 0]
    if os.path.isfile(waiting):
        os.remove(waiting)
    if phases and suite_after_phase(cfg):
        session["suite_due"] = {"reason": f"Phase {phases[0]}", "phase": phases[0]}
        save_session(root, session)
        print(f"Merged: Phase {phases[0]} is complete on {main}. TELESMA SUITE DUE: run `{self_command()} suite` "
              "(the phase regression runs on main, section 17.3).")
        return 0, None, main
    plan = ts.load_plan(root)
    fixes_max = limit_value(cfg.field("Integrations", "Max fixes per PR"), 3)
    for n in sorted({o["pr"] for o in plan.order if not o["done"] and o["pr"] is not None} | {x["n"] for x in session["side_prs"]}):
        pr = prs.get(n)
        if not pr or pr.get("state") != "OPEN":
            continue
        state, red = ghf.checks_state(pr, required)
        if state != "red":
            continue
        count = int((session.get("pr_fixes") or {}).get(str(n), 0)) + 1
        task_item = next((o for o in plan.order if o["pr"] == n), None)
        name = ts.name_of(plan, task_item) if task_item else None
        if fixes_max and count > fixes_max:
            text = (f"TELESMA BLOCKED\n\nTask: {name or 'PR #' + str(n)}\nProblem: PR #{n} is red ({', '.join(red)}) after "
                    f"{count - 1} fixes (Max fixes per PR: {fixes_max}). {pr.get('url', '')}\n"
                    "Need help with: look at the PR and the last diagnosis in the Problem log.")
            write_blocked(root, text)
            print(text)
            return 0, None, main
        session.setdefault("pr_fixes", {})[str(n)] = count
        restore_state_files(root)
        git(root, "checkout", "-q", pr["headRefName"]) if git(root, "rev-parse", "-q", "--verify",
                                                               f"refs/heads/{pr['headRefName']}", check=False).returncode == 0 \
            else git(root, "checkout", "-q", "-b", pr["headRefName"], f"origin/{pr['headRefName']}")
        session["pr_fix"] = {"n": n, "branch": pr["headRefName"], "name": name, "red": red, "count": count,
                             "max": fixes_max, "calls": 0}
        save_session(root, session)
        print_fix(session["pr_fix"])
        return 0, None, main
    save_session(root, session)
    open_task = [o for o in plan.order if not o["done"] and o["pr"] is not None
                 and (prs.get(o["pr"]) or {}).get("state") == "OPEN"]
    limit = ts.pr_limit(cfg)
    if len(open_task) >= limit:
        listing = ", ".join(f"#{o['pr']} ({o['tid'] or plan.label(o)})" for o in open_task)
        text = (f"TELESMA WAITING\n\nOpen PRs: {listing} — waiting for merge / checks.\n"
                f"Merge: {mode}. Nothing is broken. Run again after a merge.")
        ts.atomic_write(waiting, text + "\n")
        print(text)
        return 0, None, main
    return None, prs, main


def wait_for_checks(root, cfg, prs, plan):
    """Nothing to start while PRs wait: watch the first pending one for up to `Wait for merge`."""
    pending = [o["pr"] for o in plan.order if not o["done"] and o["pr"] is not None
               and (prs.get(o["pr"]) or {}).get("state") == "OPEN"]
    if not pending:
        return False
    limit = wait_limit(cfg)
    print(f"Waiting up to {limit} s for the checks of PR #{pending[0]}…", flush=True)
    try:
        subprocess.run([ghf.gh_binary(), "pr", "checks", str(pending[0]), "--watch", "--interval", "20"], cwd=root,
                       capture_output=True, timeout=limit)
    except (OSError, subprocess.TimeoutExpired):
        pass
    print(f"Run `{self_command()} next` again: it merges what turned green and goes on.")
    return True


def side_commit(root, cfg, session, files, excluded, kind, subject, body, trailers):
    """With the integration nothing lands on main directly: a commit that is not a task goes through
    its own branch and PR (merged like a task's by the next reconciliation)."""
    main = ghf.base_branch(root)
    branch = ghf.branch_name(cfg, kind, subject.split(":", 2)[-1]) + "-" + now().strftime("%H%M%S")
    git(root, "checkout", "-q", "-b", branch)
    try:
        sha = make_commit(root, files, excluded, subject, body, trailers)
    except Refused:
        git(root, "checkout", "-q", main, check=False)
        git(root, "branch", "-q", "-D", branch, check=False)
        raise
    record_evidence(root)
    ghf.push(root, branch)
    n = ghf.open_pr(root, branch, main, subject, pr_body(body, trailers))
    if merge_mode(cfg) == "auto":
        ghf.enable_auto_merge(root, n)
    session.setdefault("side_prs", []).append({"n": n, "branch": branch, "kind": kind})
    save_session(root, session)
    git(root, "checkout", "-q", main)
    return sha, n


def pr_body(body, trailers):
    parts = [b for b in ((body or "").strip(), "\n".join(t.strip() for t in trailers or [] if t.strip())) if b]
    return "\n\n".join(parts + [ts.FOOTER])


def done_github(root, cfg, session, item, name, files, excluded, args):
    """done with the integration: a fix pushed to its PR, or the task's commit, push, PR and (pr: #n)."""
    fix = session.get("pr_fix")
    branch = ghf.current_branch(root)
    if fix:
        if branch != fix["branch"]:
            raise Refused(f"the PR fix belongs on `{fix['branch']}`, you are on `{branch}`")
        run_tests(root, cfg, files)
        warnings = run_checks(root, files)
        sha = make_commit(root, files, excluded, short_subject(f"Telesma: fix PR #{fix['n']} — {fix.get('name') or fix.get('kind')}"),
                          args.message, args.trailer)
        record_evidence(root)
        ghf.push(root, branch)
        session.pop("pr_fix", None)
        save_session(root, session)
        print(f"committed {sha[:9]} and pushed to PR #{fix['n']}")
        if warnings:
            print(warnings)
        print(f"Next: `{self_command()} next` — it reads the checks again.")
        return 0
    if session.get("branch") and branch != session["branch"]:
        raise Refused(f"{name} is worked on `{session['branch']}`, you are on `{branch}` — `git checkout {session['branch']}`")
    run_tests(root, cfg, files)
    warnings = run_checks(root, files)
    subject = short_subject(f"Telesma: {name}")
    sha = make_commit(root, files, excluded, subject, args.message, args.trailer)
    record_evidence(root)
    ghf.push(root, branch)
    n = ghf.open_pr(root, branch, session.get("base") or ghf.base_branch(root), subject, pr_body(args.message, args.trailer))
    # (pr: #n) is not committed on the branch: main learns it from the PR's title (apply_derived)
    if merge_mode(cfg) == "auto":
        ghf.enable_auto_merge(root, n)
    session.update({"task": None, "status": None, "branch": None, "base": None, "last": name, "refusals": 0,
                    "tasks_this_session": int(session.get("tasks_this_session", 0)) + 1})
    save_session(root, session)
    print(f"committed {sha[:9]} {name} — PR #{n} opened ({merge_mode(cfg)} merge); the task is ticked when it is merged")
    if warnings:
        print(warnings)
    print(f"Next: `{self_command()} next`")
    return 0


# --- done -----------------------------------------------------------------------------------

def cmd_done(root, args):
    cfg = ts.load_config(root)
    session = load_session(root)
    reserved = session.get("task")
    if session.get("pr_fix") and ts.git_integration(cfg):
        files, excluded = commit_set(root, cfg, args.only)
        if not files:
            raise Refused("nothing changed — the fix changes something on the PR's branch")
        try:
            return done_github(root, cfg, session, None, session["pr_fix"].get("name") or "", files, excluded, args)
        except ghf.GitHubError as e:
            raise Refused(str(e))
    if not reserved:
        raise Refused(f"no task is issued — run `{self_command()} next` first; done finishes the task next issued")
    plan_path = os.path.join(root, ts.PLAN)
    plan = ts.load_plan(root)
    item = plan.find(reserved)
    name = session.get("name", "?")
    if args.id and args.id != (reserved.get("tid") or ""):
        raise Refused(f"the issued task is {name}, not {args.id} — finish it first (or run next to see it)")
    if item is None:
        raise Refused(f"the issued task {name} is no longer in {ts.PLAN} (renumbered or removed?) — run next")
    if item["done"]:
        raise Refused(f"{name} is already ticked in {ts.PLAN} — only done ticks a task; restore `- [ ]` and run done")
    if session.get("status") == "committed":
        raise Refused(f"{name} was already committed ({session.get('commit', '')[:9]}) and waits for its PR "
                      "(section 17.2) — run next")
    if ts.git_integration(cfg) and not session.get("pr_fix"):
        files, excluded = commit_set(root, cfg, args.only)
        if not [p for p in files if p not in (session.get("next_wrote") or [])]:
            raise Refused("nothing changed in the work tree — a finished task changes something")
        print(f"Telesma done: {name} (branch {ghf.current_branch(root)})", flush=True)
        try:
            return done_github(root, cfg, session, item, name, files, excluded, args)
        except Refused:
            session["refusals"] = int(session.get("refusals", 0)) + 1
            save_session(root, session)
            raise
        except ghf.GitHubError as e:
            raise Refused(str(e))

    files, excluded = commit_set(root, cfg, args.only)
    if not [p for p in files if p not in (session.get("next_wrote") or [])]:
        raise Refused("nothing changed in the work tree (besides what next itself corrected) — a finished "
                      "task changes something")
    print(f"Telesma done: {name}", flush=True)
    print(f"  files: {len(files)}" + (f" (excluded by Ignore on commit: {len(excluded)})" if excluded else ""))

    git_mode = ts.git_integration(cfg)
    auto_commit = cfg.field("Git", "Auto-commit", "yes").lower() not in ("no", "false")
    refusals = int(session.get("refusals", 0))
    original_plan = ts.read_text(plan_path)
    report_path = os.path.join(root, ts.REPORT)
    original_report = ts.read_text(report_path)
    wrote = False
    try:
        tests = run_tests(root, cfg, files)
        if not git_mode:
            # With a repository integration the tick and the row come with the merge (17.1).
            text = ts.tick(original_plan, item["idx"])
            ts.atomic_write(plan_path, text)
            if original_report is not None:
                issued = session.get("issued")
                minutes = ""
                if issued:
                    try:
                        minutes = f" ({int((now() - datetime.datetime.fromisoformat(issued)).total_seconds() // 60)} min)"
                    except ValueError:
                        pass
                done_n, total = ts.Plan(text).counts()
                report = ts.fill_summary(commits_resolved(root, original_report), now().strftime("%Y-%m-%d"))
                report = ts.add_history_row(report, [
                    name, "✅", tests, refusals + 1, "this commit" if auto_commit else "not committed",
                    now().strftime("%Y-%m-%d %H:%M") + minutes])
                ts.atomic_write(report_path, ts.set_progress(report, done_n, total))
            wrote = True
            for p in (ts.PLAN, ts.REPORT):
                if p not in files and os.path.exists(os.path.join(root, p)):
                    files.append(p)
        warnings = run_checks(root, sorted(set(files)))
        if not auto_commit:
            session.update({"task": None, "last": name, "refusals": 0})
            save_session(root, session)
            print(f"done {name} — Auto-commit: no, nothing committed")
            return 0
        sha = make_commit(root, sorted(set(files)), excluded, short_subject(f"Telesma: {name}"),
                          args.message, args.trailer)
    except Refused:
        if wrote:
            ts.atomic_write(plan_path, original_plan)
            if original_report is not None:
                ts.atomic_write(report_path, original_report)
        session["refusals"] = refusals + 1
        save_session(root, session)
        hard = limits(root, session).get("Max refusals per task")
        if hard and session["refusals"] >= hard:
            exhaust(root, session, "Max refusals per task",
                    f"done was refused {session['refusals']} times for {name}; the last reason is below")
        raise
    record_evidence(root)
    if git_mode:
        session.update({"status": "committed", "commit": sha})
    else:
        session.update({"task": None, "status": None, "last": name, "refusals": 0,
                        "tasks_this_session": int(session.get("tasks_this_session", 0)) + 1})
        pid = item["phase"]
        if pid and ts.load_plan(root).phase_complete(pid) and suite_after_phase(cfg):
            session["suite_due"] = {"reason": f"Phase {pid}", "phase": pid}
    save_session(root, session)
    print(f"committed {sha[:9]} {name}")
    if warnings:
        print(warnings)
    if git_mode:
        print("Repository integration: push this branch and open the PR (section 17.2), add (pr: #n) to the task; "
              "the task is ticked after the merge (17.1).")
    if session.get("suite_due"):
        print(f"Phase {session['suite_due']['phase']} is complete. Next: `{self_command()} suite` (Bash tool timeout "
              "600000; when the full suite takes longer than about 8 minutes, run it in the background and wait).")
    else:
        print(f"Next: `{self_command()} next`")
    return 0


def cmd_commit(root, args):
    if args.kind not in KINDS:
        raise Refused(f"--kind is one of: {', '.join(KINDS)}")
    if not (args.message or "").strip():
        raise Refused("-m: one sentence saying what this commit is")
    cfg = ts.load_config(root)
    files, excluded = commit_set(root, cfg, args.only)
    if not files:
        raise Refused("nothing changed in the work tree")
    print(f"Telesma commit ({args.kind}): {len(files)} files", flush=True)
    run_tests(root, cfg, files)
    warnings = run_checks(root, files)
    first, _, rest = args.message.strip().partition("\n")
    if ts.git_integration(cfg):
        try:
            sha, n = side_commit(root, cfg, load_session(root), files, excluded, args.kind,
                                 short_subject(f"Telesma: {args.kind}: {first}"), rest, args.trailer)
        except ghf.GitHubError as e:
            raise Refused(str(e))
        print(f"committed {sha[:9]} — PR #{n} opened; merged by the next reconciliation (`next`)")
        if warnings:
            print(warnings)
        return 0
    sha = make_commit(root, files, excluded, short_subject(f"Telesma: {args.kind}: {first}"), rest, args.trailer)
    record_evidence(root)
    print(f"committed {sha[:9]}")
    if warnings:
        print(warnings)
    session = load_session(root)
    if session.get("regression") and args.kind == "regression":
        print(f"Next: `{self_command()} suite` — the full suite decides whether the regression is fixed.")
    return 0


# --- the session budget (K2) ---------------------------------------------------------------

LIMITS = (("Max refusals per task", 5), ("Max attempts per task", 3), ("Max tasks per session", None),
          ("Max hours per session", None))
BUDGET_MARK = "Budget:"


def limit_value(raw, default):
    v = (raw or "").strip().lower()
    if not v:
        return default
    if v in ("none", "no", "-", "unlimited"):
        return None
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return default


def limits(root, session):
    """The limits as read at the start of the session (the launcher's session-start); the config
    itself only when there is no snapshot (a session not started by the launcher)."""
    snap = session.get("limits")
    if isinstance(snap, dict):
        return snap
    cfg = ts.load_config(root)
    return {k: limit_value(cfg.field("Telesma loop", k), d) for k, d in LIMITS}


def exhaust(root, session, reason, detail):
    """The budget is used up: BLOCKED.md written by the script, the session marked — `next` hands
    out nothing and the guard refuses everything but reads until a person decides at the next start."""
    session["exhausted"] = {"reason": reason, "at": now().isoformat(timespec="seconds")}
    save_session(root, session)
    text = (f"TELESMA BLOCKED\n\n{BUDGET_MARK} {reason}\nProblem: {detail}\n"
            "Need help with: the session stopped on its limit. Look at the task and the Problem log; the next "
            "start of the launcher asks whether to go on (the counters start again).")
    write_blocked(root, text)
    print(text)
    return 0


def cmd_session_start(root, args):
    session = load_session(root)
    if session.get("exhausted") and not args.cont:
        print(f"exhausted: {session['exhausted'].get('reason')} ({session['exhausted'].get('at')})")
        return 3
    if args.cont:
        session.pop("exhausted", None)
        session["issues"], session["refusals"] = (1 if session.get("task") else 0), 0
        blocked = os.path.join(root, ts.BLOCKED)
        if BUDGET_MARK in (ts.read_text(blocked) or ""):
            os.remove(blocked)
    cfg = ts.load_config(root)
    session.update({"started": now().isoformat(timespec="seconds"), "tasks_this_session": 0, "calls_since_next": 0,
                    "limits": {k: limit_value(cfg.field("Telesma loop", k), d) for k, d in LIMITS}})
    save_session(root, session)
    print("session started")
    return 0


def budget_check(root, session, again):
    """None when the next task may be issued, else the exhaust() result."""
    lim = limits(root, session)
    started = session.get("started")
    hours = lim.get("Max hours per session")
    if hours and started:
        try:
            spent = (now() - datetime.datetime.fromisoformat(started)).total_seconds() / 3600
        except ValueError:
            spent = 0
        if spent >= hours:
            return exhaust(root, session, "Max hours per session",
                           f"the session has run {spent:.1f} h; the limit is {hours} h")
    tasks = lim.get("Max tasks per session")
    if tasks and int(session.get("tasks_this_session", 0)) >= tasks:
        return exhaust(root, session, "Max tasks per session", f"{tasks} tasks were finished in this session")
    attempts = lim.get("Max attempts per task")
    if again and attempts and int(session.get("issues", 0)) + 1 > attempts:
        return exhaust(root, session, "Max attempts per task",
                       f"{session.get('name')} was handed out {session.get('issues')} times without a finished done")
    return None


# --- the full suite: end of a phase, after a change request (Z3) ----------------------------

def suite_after_phase(cfg):
    v = cfg.field("Tests", "Full suite after", "every phase").strip().lower()
    return v not in ("none", "never", "no", "manual")


def baseline_failures(report):
    """Failures the adoption baseline already had (`**Baseline at adoption (…) — RED…:** … N failed`):
    a run that fails no more than that inherited, it did not regress (section 2)."""
    m = re.search(r"^\*\*Baseline at adoption \([^)]*\) — (\w+)[^\n]*", report or "", re.M)
    if not m or m.group(1) == "GREEN":
        return None
    f = re.search(r"(\d+) failed", m.group(0))
    return int(f.group(1)) if f else None


def current_branch(root):
    r = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    return r.stdout.decode().strip()


def cmd_suite(root, args):
    cfg = ts.load_config(root)
    session = load_session(root)
    due = session.get("suite_due") or ({"reason": "a regression fix", "phase": None} if session.get("regression") else None)
    if not due and not args.full:
        raise Refused("no full suite is due — it runs at the end of a phase and after a change request "
                      "(use `suite --full` to run it anyway)")
    due = due or {"reason": "a run on request", "phase": None}
    full = cfg.field("Tests", "Full suite command")
    if ts.unset(full) or full.strip().startswith("["):
        full = cfg.field("Tests", "Test command")
    if ts.unset(full) or full.strip().startswith("["):
        raise Refused("## Tests has no Full suite command and no Test command")
    if not tests_trusted(root):
        raise Refused("the ## Tests section of telesma/config.md is not confirmed on this machine — report "
                      "TELESMA BLOCKED; the person confirms it at the next start of the launcher")
    print(f"Telesma suite ({due['reason']}): {full}", flush=True)
    argv = [BASH, "-c", full] if BASH else full
    start = now()
    try:
        r = subprocess.run(argv, shell=not BASH, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=TEST_TIMEOUT)
        out, rc = r.stdout.decode("utf-8", "replace"), r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (e.stdout or b"").decode("utf-8", "replace") + f"\n(time limit {TEST_TIMEOUT} s)", -1
    secs = int((now() - start).total_seconds())
    counts = ts.parse_counts(out)
    green = rc == 0 and not zero_tests(out)
    report_path = os.path.join(root, ts.REPORT)
    report = ts.read_text(report_path) or ""
    inherited = baseline_failures(report)
    only_inherited = (not green and inherited is not None and counts is not None and rc != -1
                      and counts["fail"] <= inherited)
    git_mode = ts.git_integration(cfg)
    branch = current_branch(root)
    on_branch = git_mode and branch not in ("main", "master", cfg.field("Integrations", "Base branch") or "main")
    phase = due.get("phase")
    title = ("Preliminary run" if on_branch else f"Regression after Phase {phase}" if phase
             else f"Full suite after {due['reason']}")
    verdict = "GREEN" if green else "RED (inherited failures only)" if only_inherited else "RED"
    numbers = (f"{counts['pass']} passed, {counts['fail']} failed, {counts['skip']} skipped" if counts
               else summary_of(out) if green else f"exit {rc}")
    date = now().strftime("%Y-%m-%d")
    tag = f"telesma/phase-{phase}" if green and phase and not on_branch else None
    paragraph = f"**{title} ({date}) — {verdict}:** `{full}` — {numbers} ({secs} s)."
    if tag:
        paragraph += f" Tag `{tag}`."
    report = commits_resolved(root, report)
    ts.atomic_write(report_path, ts.add_test_run(report, paragraph, counts, now().strftime("%Y-%m-%d %H:%M")))
    print(paragraph)
    if not green and not only_inherited:
        session["regression"] = {"since": now().isoformat(timespec="seconds"), "reason": due["reason"],
                                 "command": full, "tail": tail(out, 40)}
        session["suite_due"] = due
        save_session(root, session)
        print("\n" + tail(out, 40))
        print(f"\nTELESMA REGRESSION — no new task until the full suite is green. Fix the cause (section 2), record it "
              f"in the Problem log, `{self_command()} commit --kind regression -m \"<what broke and why>\"`, then "
              f"`{self_command()} suite` again.")
        return 0
    # green (or no worse than the adoption baseline): the run is the phase's record
    auto_commit = cfg.field("Git", "Auto-commit", "yes").lower() not in ("no", "false")
    if git_mode:
        # nothing is committed on main directly: the paragraph is kept (apply_derived puts it back
        # after a pull) and, at the end of a phase, goes with the ticks and rows into a state PR
        session.setdefault("carry", []).append({"paragraph": paragraph, "counts": counts,
                                                "date": now().strftime("%Y-%m-%d %H:%M")})
        save_session(root, session)
    elif auto_commit:
        files, excluded = commit_set(root, cfg)
        if files:
            run_checks(root, files)
            sha = make_commit(root, files, excluded, short_subject(f"Telesma: {title} — {verdict}"), "", [])
            record_evidence(root)
            print(f"committed {sha[:9]}")
    if tag and (auto_commit or git_mode):
        runner = os.path.join(root, "telesma", "checks", "telesma-checks.py")
        if os.path.isfile(runner):
            pr = subprocess.run([sys.executable, runner, "--point", "phase"], cwd=root, capture_output=True,
                                timeout=900)
            pout = (pr.stdout + pr.stderr).decode("utf-8", "replace").strip()
            if pr.returncode != 0:
                session["suite_due"] = due
                session["regression"] = {"since": now().isoformat(timespec="seconds"), "reason": f"phase checks of {phase}",
                                         "command": "telesma/checks/telesma-checks.py --point phase", "tail": pout}
                save_session(root, session)
                print(pout + f"\n\nTELESMA REGRESSION — the phase checks block the tag {tag}. Fix what they name, "
                      f"`commit --kind regression`, then `suite` again (section 19.1).")
                return 0
            if pout and not pout.startswith(("Checks disabled", "Checks (phase): clean")):
                print(pout)
        git(root, "tag", "-f", tag)
        print(f"tag {tag}")
        if git_mode:
            files, excluded = commit_set(root, cfg)
            if files:
                try:
                    _, n = side_commit(root, cfg, session, files, excluded, "state",
                                       short_subject(f"Telesma: state after Phase {phase}"),
                                       "Ticks, Task history rows and the phase regression, as GitHub and the suite "
                                       "recorded them.", [])
                    print(f"state PR #{n} opened (ticks, history rows, the run) — merged by the next reconciliation")
                    session = load_session(root)
                except ghf.GitHubError as e:
                    print(f"the state PR could not be opened ({e}); the state stays in the tree and is retried")
    session.pop("regression", None)
    session.pop("suite_due", None)
    session["green"] = {"head": git(root, "rev-parse", "HEAD").stdout.decode().strip(),
                        "at": now().isoformat(timespec="seconds"), "command": full}
    save_session(root, session)
    if phase:
        print("End of the phase: review PROJECT_CONTEXT.md (section 7 — known pitfalls) and propose a release in a "
              "📦 RELEASE PROPOSAL block (section 15.1) if there is anything to release.")
    print(f"Next: `{self_command()} next`")
    return 0


# --- release versions (Z6) ------------------------------------------------------------------

RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
# what may land between the green suite and the tag: the scenarios file and state-file notes
AFTER_GREEN = ("docs/test-scenarios/", "telesma/state/")


def cmd_release(root, args):
    tag = (args.id or "").strip()
    if not RELEASE_TAG.match(tag):
        raise Refused("release takes a version vX.Y.Z (section 15.2)")
    if not (args.message or "").strip():
        raise Refused("-m: 2-4 sentences on what landed, in product language (section 15.3)")
    if git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        raise Refused(f"{tag} exists already — a release is immutable; propose the next number (15.5)")
    cfg = ts.load_config(root)
    files, _ = commit_set(root, cfg)
    if ts.git_integration(cfg):
        files = [p for p in files if not p.startswith("telesma/state/")]     # derived, travels with the next PR
    if files:
        raise Refused("the tree is not clean (" + ", ".join(files[:5]) + ("…" if len(files) > 5 else "") +
                      f") — commit first: `{self_command()} commit --kind release -m \"…\"` (15.5)")
    scenarios = f"docs/test-scenarios/{tag}.md"
    if git(root, "cat-file", "-e", f"HEAD:{scenarios}", check=False).returncode != 0:
        raise Refused(f"{scenarios} is not committed — write it (section 15.7) and commit it before the tag")
    head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    green = (load_session(root).get("green") or {}).get("head")
    if not green:
        raise Refused(f"no green full suite recorded on this machine — run `{self_command()} suite --full` first (15.5)")
    if green != head:
        if git(root, "merge-base", "--is-ancestor", green, head, check=False).returncode != 0:
            raise Refused(f"the last green full suite was on another line of history — run `{self_command()} suite --full`")
        since = [p for p in git(root, "diff", "--name-only", f"{green}..{head}").stdout.decode().split("\n") if p]
        code = [p for p in since if not p.startswith(AFTER_GREEN)]
        if code:
            raise Refused("code changed since the last green full suite (" + ", ".join(code[:5]) +
                          f") — run `{self_command()} suite --full` first")
    runner = os.path.join(root, "telesma", "checks", "telesma-checks.py")
    if os.path.isfile(runner):
        r = subprocess.run([sys.executable, runner, "--point", "release"], cwd=root, capture_output=True, timeout=900)
        out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
        if r.returncode != 0:
            raise Refused("the release checks block the version:\n" + out)
    git(root, "tag", "-a", tag, "-m", args.message.strip())
    print(f"created {tag} on {head[:7]} (annotated; not pushed)")
    print("Now, in this order (section 15.6): the DECISIONS.md entry (Kind: operations), then the message to the "
          f"person with `git push origin {tag}` — tags do not travel with a plain `git push`.")
    return 0


# --- change requests (Z4) -------------------------------------------------------------------

DECISION_SOURCES = ("telesma/state/PROJECT_CONTEXT.md", "telesma/state/DECISIONS.md", "telesma/state/QUESTIONS.md",
                    "telesma/state/CONTEXT_ARCHIVE.md", "telesma/state/BUGFIXES.md")
STOP_WORDS = {"change", "changes", "should", "would", "could", "there", "their", "which", "these", "those",
              "about", "after", "before", "where", "every", "other", "being", "added", "field", "first"}


def earlier_decisions(root, text, name, limit=12):
    """Lines of the decision sources that share a distinctive word with the change (0.6) — quoted
    verbatim with file and line, so a conflict is read, not remembered."""
    body = re.sub(r"^---.*?---", "", text or "", flags=re.S)
    words = {w.lower() for w in re.findall(r"[A-Za-zÀ-ž]{6,}", name.replace("-", " ") + " " + body[:1500])}
    words -= STOP_WORDS
    if not words:
        return []
    pat = re.compile(r"\b(" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)[:40]) + r")", re.I)
    hits = []
    for rel in DECISION_SOURCES:
        for i, line in enumerate((ts.read_text(os.path.join(root, rel)) or "").split("\n"), 1):
            if line.strip() and not line.lstrip().startswith(("<!--", "|---", "| ---")) and len(set(
                    m.lower() for m in pat.findall(line))) >= 2:
                hits.append(f"{rel}:{i}: {line.strip()[:300]}")
                if len(hits) >= limit:
                    return hits
    return hits


def affects_fragment(root, affects):
    """`telesma/spec/x.md:120-145` → the lines; `x.md (section "Name")` → that section's range from the index."""
    m = re.match(r"^\s*(\S+?):(\d+)-(\d+)", affects or "")
    if m:
        rel, full = spec_file(root, m.group(1))
        if full:
            return f"#### {rel}:{m.group(2)}-{m.group(3)}\n" + fragment(full, int(m.group(2)), int(m.group(3)))
        return ""
    m = re.match(r"^\s*(\S+)\s*\(section\s*[\"“]?([^\"”)]+)", affects or "")
    if m:
        rel, full = spec_file(root, m.group(1))
        key, entry = find_entry(spec_index_entries(ts.read_text(os.path.join(root, ts.SPEC_INDEX)) or ""), m.group(1))
        if full and entry:
            row = next((r for r in entry["rows"] if "start" in r and len(r["cells"]) > 1
                        and m.group(2).strip().lower() in r["cells"][1].lower()), None)
            if row:
                return f"#### {rel} — {row['cells'][1]} (lines {row['start']}-{row['end']})\n" + \
                    fragment(full, row["start"], row["end"])
    return ""


def cmd_changes(root, args):
    pending = ts.change_order(root, ts.pending_changes(root))
    if not pending:
        print(f"No change request is waiting in telesma/changes/. Next: `{self_command()} next`")
        return 0
    name = pending[0]
    text = ts.read_text(os.path.join(root, ts.CHANGES, name)) or ""
    fm = ts.frontmatter(text)
    print(f"TELESMA CHANGE: telesma/changes/{name}" + (f"   ({len(pending) - 1} more after it)" if len(pending) > 1 else ""))
    print(f"Priority: {fm.get('priority', 'normal')} · Affects: {fm.get('affects', 'general')}"
          + (f" · Kind: {fm['kind']}" if fm.get("kind") else ""))
    print("\n## The request\n\n" + text.strip())
    frag = affects_fragment(root, fm.get("affects", ""))
    if frag:
        print("\n## The spec it affects (before)\n\n" + frag)
    hits = earlier_decisions(root, text, name)
    print("\n## Earlier decisions that may concern it (verbatim; section 0.6)\n")
    print("\n".join(hits) if hits else "none found by the words of the request — still recall by topic (0.6)")
    session = load_session(root)
    session["change"] = name
    save_session(root, session)
    print(f"\n## Then\n\nAnalyse the impact and edit PLAN.md (section 0.3). Finish with `{self_command()} changes-done {name} "
          "--kind bug|correction|feature -m \"<1-2 sentences>\"` (+ `--source X.Y|unknown --detected-by …` for a bug; "
          "`--withdrawn` when it contradicts a decision the person kept). It checks the plan, writes the Change history "
          "entry, moves the file to processed/ and commits.")
    return 0


DETECTED_BY = ("test", "scenario", "review", "telesma", "owner", "production")


def head_plan(root):
    r = git(root, "show", f"HEAD:{ts.PLAN}", check=False)
    return ts.Plan(r.stdout.decode("utf-8", "replace") if r.returncode == 0 else "")


def cmd_changes_done(root, args):
    name = os.path.basename(args.id or "")
    src = os.path.join(root, ts.CHANGES, name)
    if not name or not os.path.isfile(src):
        raise Refused(f"no telesma/changes/{name or '<file>'} — give the file name `changes` issued")
    kind = (args.kind or "").strip()
    if kind not in ("bug", "correction", "feature"):
        raise Refused("--kind is exactly one of: bug, correction, feature (section 0.3)")
    if not (args.message or "").strip():
        raise Refused("-m: the Summary, 1-2 sentences on what changes and why")
    if kind == "bug":
        if not args.source or (args.source != "unknown" and not re.fullmatch(ts.TASK_ID, args.source)):
            raise Refused("a bug needs --source <task id that built it> or --source unknown")
        if args.detected_by not in DETECTED_BY:
            raise Refused("a bug needs --detected-by " + "|".join(DETECTED_BY))
    elif args.source or args.detected_by:
        raise Refused("--source and --detected-by belong to a bug only")

    old, new = head_plan(root), ts.load_plan(root)
    flipped = [t for t, o in old.tasks.items() if t in new.tasks and not o.get("archived")
               and not new.tasks[t].get("archived") and o["done"] != new.tasks[t]["done"]]
    if flipped or sum(1 for o in new.order if o["done"]) != sum(1 for o in old.order if o["done"]):
        raise Refused("a checkbox changed state in PLAN.md" + (f" ({', '.join(flipped)})" if flipped else "") +
                      " — a change never unticks or ticks a task: rework goes into a new `.Z` phase (section 0.3)")
    tag = f"(change: {name})"
    added = [t for t in new.tasks if t not in old.tasks and not new.tasks[t].get("archived")]
    modified = [t for t in new.tasks if t in old.tasks and not new.tasks[t]["done"] and not new.tasks[t].get("archived")
                and new.lines[new.tasks[t]["idx"]] != old.lines[old.tasks[t]["idx"]]]
    if args.withdrawn:
        if added or modified or new.text.strip() != old.text.strip():
            raise Refused("--withdrawn: the plan must stay as it was")
    else:
        untagged = [t for t in added + modified if tag not in new.lines[new.tasks[t]["idx"]]]
        if untagged:
            raise Refused(f"new or changed tasks without `{tag}`: {', '.join(untagged)}")
        errs = ts.dependency_errors(new) + new.errors
        if errs:
            raise Refused("the plan does not hold together:\n" + "\n".join(f"- {e}" for e in errs[:10]))
    new_z = [p for p in new.phases if p not in old.phases and ".Z" in p]
    z_text = ", ".join(f"Phase {p} with {len(new.phases[p]['tasks'])} tasks" for p in new_z) or "none"
    fm = ts.frontmatter(ts.read_text(src) or "")
    summary = re.sub(r"\s+", " ", args.message).strip()
    if args.withdrawn and "withdrawn" not in summary.lower():
        summary = "withdrawn — " + summary
    lines = [f"### {now().strftime('%Y-%m-%d')} {name}", f"- **Kind**: {kind}"]
    if kind == "bug":
        lines += [f"- **Bug source**: {args.source}", f"- **Detected by**: {args.detected_by}"]
    lines += [f"- **Priority**: {fm.get('priority', 'normal') or 'normal'}",
              f"- **Affects**: {fm.get('affects', 'general') or 'general'}",
              f"- **Summary**: {summary}",
              f"- **Modified pending tasks**: {', '.join(modified) or 'none'}",
              f"- **New rework phase**: {z_text}",
              f"- **New tasks**: {', '.join(t for t in added if new.tasks[t]['phase'] not in new_z) or 'none'}"]
    report_path = os.path.join(root, ts.REPORT)
    original_report = ts.read_text(report_path)
    cfg = ts.load_config(root)
    ts.atomic_write(report_path, ts.add_change_entry(original_report or "", "\n".join(lines)))
    dest_dir = os.path.join(root, ts.CHANGES, "processed")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest):
        ts.atomic_write(report_path, original_report or "")
        raise Refused(f"telesma/changes/processed/{name} exists already — rename the request")
    os.replace(src, dest)
    try:
        files, excluded = commit_set(root, cfg)
        run_tests(root, cfg, files)
        warnings = run_checks(root, files)
        if ts.git_integration(cfg):
            sha, _ = side_commit(root, cfg, load_session(root), files, excluded, "changes",
                                 short_subject(f"Telesma: changes: process {name}"), summary, args.trailer)
        else:
            sha = make_commit(root, files, excluded, short_subject(f"Telesma: changes: process {name}"), summary,
                              args.trailer)
    except (Refused, ghf.GitHubError) as e:
        os.replace(dest, src)
        ts.atomic_write(report_path, original_report or "")
        if isinstance(e, ghf.GitHubError):
            raise Refused(str(e))
        raise
    record_evidence(root)
    session = load_session(root)
    session.pop("change", None)
    if not args.withdrawn and suite_after_phase(cfg):
        session["suite_due"] = {"reason": name, "phase": None}
    save_session(root, session)
    print(f"committed {sha[:9]} — {name} processed")
    if warnings:
        print(warnings)
    if ts.pending_changes(root):
        print(f"Next: `{self_command()} changes`")
    elif session.get("suite_due"):
        print(f"Next: `{self_command()} suite` — the plan changed, the full suite checks its assumptions.")
    else:
        print(f"Next: `{self_command()} next`")
    return 0


# --- next -----------------------------------------------------------------------------------

def spec_index_entries(text):
    """{file path as written in the index: [section rows]} from the `## Documents` part:
    `### <file> (N lines)` followed by a `| Lines | Section | Anchor | Description |` table."""
    out, cur, ui = {}, None, False
    for i, line in enumerate((text or "").split("\n")):
        if line.startswith("## "):
            ui = line.strip() in ("## UX/UI guidelines", "## Flows")
            cur = None
            continue
        m = re.match(r"^### (\S+)", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, {"rows": [], "ui": ui})
            continue
        if cur and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rng = re.fullmatch(r"(\d+)\s*-\s*(\d+)", cells[0]) if cells else None
            if rng:
                out[cur]["rows"].append({"line": i, "start": int(rng.group(1)), "end": int(rng.group(2)),
                                         "cells": cells})
            elif cur and len(cells) >= 3 and not set(cells[0]) <= set("-: "):
                out[cur]["rows"].append({"line": i, "cells": cells})
    return out


def find_entry(entries, path):
    """An index entry for `path` (written with or without the telesma/spec/ prefix)."""
    want = path[len("telesma/spec/"):] if path.startswith("telesma/spec/") else path
    for k, v in entries.items():
        kk = k[len("telesma/spec/"):] if k.startswith("telesma/spec/") else k
        if kk == want:
            return k, v
    return None, None


def spec_file(root, path):
    p = path if path.startswith("telesma/") else os.path.join(ts.SPEC, path)
    full = os.path.join(root, p)
    return (p, full) if os.path.exists(full) else ((path, os.path.join(root, path))
                                                   if os.path.exists(os.path.join(root, path)) else (p, None))


def verify_anchors(root, index_lines, key, entry):
    """Procedure 0.1 step 4, by the script: the line at the start of every range must be the
    section's anchor; a shifted range is found again by the exact anchor text and the index row is
    corrected. Returns (fixed, unresolved) lists of section names."""
    rel, full = spec_file(root, key)
    if not full:
        return [], []
    flines = (ts.read_text(full) or "").split("\n")
    fixed, unresolved = [], []
    for row in entry["rows"]:
        cells = row["cells"]
        if "start" not in row or len(cells) < 3:
            continue
        anchor = cells[2].strip().strip("`").strip()
        if not anchor or anchor.lower() in ("-", "none"):
            continue
        start, end = row["start"], row["end"]
        if 0 < start <= len(flines) and flines[start - 1].strip() == anchor:
            continue
        hits = [j + 1 for j, l in enumerate(flines) if l.strip() == anchor]
        if not hits:
            unresolved.append(cells[1])
            continue
        new = min(hits, key=lambda h: abs(h - start))
        delta = new - start
        row["start"], row["end"] = new, end + delta
        old = index_lines[row["line"]]
        index_lines[row["line"]] = re.sub(r"(\|\s*)\d+\s*-\s*\d+", lambda m: f"{m.group(1)}{new}-{end + delta}",
                                          old, count=1)
        fixed.append(cells[1])
    return fixed, unresolved


def fragment(full, start, end, limit=SPEC_PRINT_LIMIT):
    flines = (ts.read_text(full) or "").split("\n")
    end = min(end, len(flines), start + limit - 1)
    body = "\n".join(f"{n:>5}  {flines[n - 1]}" for n in range(max(start, 1), end + 1))
    return body


def spec_part(root, plan_line, out, blockers, wrote):
    specs = ts.tags(plan_line, "spec")
    if not specs:
        out.append("## Specification\n\nThe task has no (spec:) tag — find the sections in SPEC_INDEX.md by "
                   "name and keywords (section 0.1) and Read them with offset/limit.")
        return
    index_path = os.path.join(root, ts.SPEC_INDEX)
    index_text = ts.read_text(index_path) or ""
    index_lines = index_text.split("\n")
    entries = spec_index_entries(index_text)
    changed = False
    out.append("## Specification")
    for tag in specs:
        fname, _, note = tag.partition(" ")
        rel, full = spec_file(root, fname)
        if not full:
            blockers.append(f"(spec: {tag}) — no file {fname} in telesma/spec/ or the project root")
            continue
        key, entry = find_entry(entries, fname)
        flen = len((ts.read_text(full) or "").split("\n"))
        if entry is None:
            if flen <= SMALL_FILE:
                out.append(f"### {rel} ({flen} lines, not in SPEC_INDEX.md — whole file)\n\n"
                           + fragment(full, 1, flen))
            else:
                out.append(f"### {rel} ({flen} lines) — no entry in SPEC_INDEX.md: Grep it for the task's terms "
                           "and Read only the matching part.")
            continue
        fixed, unresolved = verify_anchors(root, index_lines, key, entry)
        changed = changed or bool(fixed)
        rows = [r for r in entry["rows"] if "start" in r]
        head = f"### {rel} ({flen} lines)"
        if fixed:
            head += f"\nAnchors moved — SPEC_INDEX.md corrected for: {', '.join(fixed)}."
        if unresolved:
            head += (f"\nAnchor not found in the file for: {', '.join(unresolved)} — the range is not reliable; "
                     "Grep for the section heading.")
        table = "\n".join(f"- lines {r['start']}-{r['end']}: {r['cells'][1]}"
                          + (f" — {r['cells'][3]}" if len(r['cells']) > 3 and r['cells'][3] else "") for r in rows)
        words = [w.lower() for w in re.findall(r"\w{3,}", note)]
        picked = [r for r in rows if words and any(w in (r["cells"][1] + " " + r["cells"][2]).lower() for w in words)]
        if flen <= SMALL_FILE:
            out.append(head + "\n\n" + fragment(full, 1, flen))
        elif picked:
            out.append(head + "\n\nSections:\n" + table + "\n\n" + "\n\n".join(
                f"#### {r['cells'][1]} (lines {r['start']}-{r['end']})\n" + fragment(full, r["start"], r["end"])
                for r in picked))
        else:
            out.append(head + "\n\nSections (ranges verified against their anchors — Read only the ones this task "
                       "needs, with offset/limit):\n" + table)
    if changed:
        ts.atomic_write(index_path, "\n".join(index_lines))
        wrote.append(ts.SPEC_INDEX)


def guideline_part(root, plan_line, session, full, out, blockers):
    tech = ts.tags(plan_line, "tech")
    gdir = os.path.join(root, ts.GUIDELINES)
    names = ["general"] + [t for t in tech if t != "general"]
    missing = [t for t in tech if not os.path.isfile(os.path.join(gdir, f"{t}.md"))]
    if missing:
        try:
            available = sorted(n[:-3] for n in os.listdir(gdir) if n.endswith(".md"))
        except OSError:
            available = []
        for t in missing:
            blockers.append(f"the task has (tech: {t}), but telesma/guidelines/{t}.md does not exist. "
                            f"Available tags: {', '.join(available) or 'none'}. Need help with: should I (a) add a "
                            f"guideline for \"{t}\", (b) change the tag in PLAN.md, or (c) do the task with general.md alone?")
        return
    shown = sorted(session.get("guidelines_shown") or [])
    want = sorted(names)
    paths = [f"{ts.GUIDELINES}/{n}.md" for n in names if os.path.isfile(os.path.join(gdir, f"{n}.md"))]
    if full or shown != want:
        out.append("## Guidelines (binding; the more specific one wins over general.md)")
        for p in paths:
            out.append(f"### {p}\n\n" + (ts.read_text(os.path.join(root, p)) or "").strip())
        session["guidelines_shown"] = want
    else:
        out.append("## Guidelines\n\nThe same set as for the previous task, already given in full: "
                   + ", ".join(paths) + f". After a compaction run `{self_command()} next --full`.")


def ui_part(root, plan_line, out, blockers):
    index_text = ts.read_text(os.path.join(root, ts.SPEC_INDEX)) or ""
    entries = spec_index_entries(index_text)
    parts = []
    for name in ("ui-tokens", "ui-component", "ui-screen", "flow"):
        for ref in ts.tag_values(plan_line, name):
            path, _, ids = ref.partition("#")
            path = path.strip()
            rel, full = spec_file(root, path)
            if not full:
                blockers.append(f"({name}: {ref}) — no file {path}")
                continue
            if name == "ui-tokens":
                parts.append(f"- ({name}) {rel}: copy the file 1:1 into the project and wire it into the global style.")
                continue
            key, entry = find_entry(entries, path)
            for ident in [x.strip() for x in ids.split(",") if x.strip()] or [""]:
                if entry is None or not ident:
                    blockers.append(f"({name}: {ref}) — no entry for it in SPEC_INDEX.md")
                    continue
                if os.path.basename(path) == "LINKS.md":
                    row = next((r for r in entry["rows"] if r["cells"] and r["cells"][0] == ident), None)
                    if not row or len(row["cells"]) < 3 or not row["cells"][2].startswith("http"):
                        blockers.append(f"({name}: {ref}) — no link for {ident} in the SPEC_INDEX.md link table; "
                                        "ask the person to share or fix the link")
                        continue
                    parts.append(f"- ({name}) {ident}: fetch {row['cells'][2]} with WebFetch ONCE for this task; "
                                 "its content is the mockup (section 0.4).")
                    continue
                col = 1
                row = next((r for r in entry["rows"] if "start" in r and len(r["cells"]) > col
                            and r["cells"][col] == ident), None)
                if not row:
                    blockers.append(f"({name}: {ref}) — no row {ident} in SPEC_INDEX.md for {path}")
                    continue
                parts.append(f"#### ({name}) {rel}#{ident} (lines {row['start']}-{row['end']})\n"
                             + fragment(full, row["start"], row["end"]))
    if parts:
        out.append("## UI and flows (a reference, not production code — rewrite into the stack, tokens instead of "
                   "hardcoded values; section 0.4 / 0.5)\n\n" + "\n\n".join(parts))


def change_part(root, plan_line, out):
    for name in ts.tags(plan_line, "change"):
        for d in (os.path.join(ts.CHANGES, "processed"), ts.CHANGES):
            p = os.path.join(root, d, name)
            if os.path.isfile(p):
                out.append(f"## Change request {d}/{name}\n\n" + (ts.read_text(p) or "").strip())
                break


def write_blocked(root, text):
    ts.atomic_write(os.path.join(root, ts.BLOCKED), text.strip() + "\n")


def cmd_next(root, args):
    cfg = ts.load_config(root)
    session = load_session(root)
    if session.get("exhausted"):
        ex = session["exhausted"]
        print(f"TELESMA BLOCKED — the session budget is used up ({ex.get('reason')}, {ex.get('at')}). Report it and "
              "stop; the next start of the launcher asks the person whether to go on.")
        return 0
    blocked_file = os.path.join(root, ts.BLOCKED)
    if os.path.isfile(blocked_file):
        print("TELESMA BLOCKED (from telesma/state/BLOCKED.md)\n\n" + (ts.read_text(blocked_file) or "").strip())
        print("\nResolve this first: check whether the answer is already in the state files (config, PLAN, "
              "telesma/changes/); if not, ask the person. When it is resolved, delete telesma/state/BLOCKED.md "
              "and run next again.")
        return 0
    prs, main = None, None
    git_mode = ts.git_integration(cfg)
    if git_mode:
        reserved = session.get("task")
        found = ts.load_plan(root).find(reserved) if reserved else None
        if not (found and not found["done"]) or session.get("pr_fix") or session.get("rebase"):
            try:
                stop, prs, main = reconcile(root, cfg, session)
            except ghf.GitHubError as e:
                print(f"TELESMA BLOCKED — the GitHub reconciliation failed: {e}\nCheck `gh auth status` and the "
                      "network; nothing was merged by this run.")
                return 0
            if stop is not None:
                return stop
            session = load_session(root)
            blocking = [x for x in session.get("side_prs") or [] if x.get("kind") in ("changes", "regression")]
            if blocking:
                x = blocking[0]
                print(f"TELESMA WAITING for PR #{x['n']} ({x['kind']}) to be merged: main does not hold it yet, and "
                      "the plan / the suite depend on it.")
                if not wait_for_checks(root, cfg, {x["n"]: {"state": "OPEN"}},
                                       ts.Plan(f"- [ ] Task 0.0: x (pr: #{x['n']})")):
                    print(f"Run `{self_command()} next` after the merge.")
                return 0
    if session.get("regression"):
        reg = session["regression"]
        print(f"TELESMA REGRESSION ({reg.get('reason')}, since {reg.get('since')}): `{reg.get('command')}` is red.\n\n"
              + (reg.get("tail") or "") +
              f"\n\nNo new task until it is green: fix the cause (section 2), record it in the Problem log, "
              f"`{self_command()} commit --kind regression -m \"<what broke and why>\"`, then `{self_command()} suite`.")
        return 0
    if session.get("suite_due"):
        print(f"TELESMA SUITE DUE ({session['suite_due'].get('reason')}): run `{self_command()} suite` before the next task.")
        return 0
    pending = ts.pending_changes(root)
    if pending:
        print("TELESMA CHANGES PENDING: " + ", ".join(ts.change_order(root, pending)))
        print(f"\nProcess them before the next task (section 0.3): `{self_command()} changes` gives the first one.")
        return 0

    plan = ts.load_plan(root)
    reserved = session.get("task")
    item, again = None, False
    if reserved:
        found = plan.find(reserved)
        if found and not found["done"] and session.get("status") != "committed":
            item, again = found, True
        elif session.get("status") == "committed" and found and not found["done"] and found["pr"] is None:
            plan.pr_lines[found["idx"]] = 0      # committed, its PR not tagged yet: not issued twice
    sel = None
    if item is None:
        sel = ts.select(plan, cfg)
        if sel["why"] == "chain" or sel["why"] == "task":
            item = sel["item"]
        elif sel["why"] == "human":
            humans = [plan.label(o) for o in sel["open"] if ts.WAITING_ON_HUMAN in plan.lines[o["idx"]]]
            text = ("TELESMA BLOCKED\n\nTask: " + ", ".join(humans) + "\nProblem: only items waiting on a person "
                    "(⛔) are left in the active phases.\nNeed help with: do them, or tell me what replaces them.")
            write_blocked(root, text)
            print(text)
            return 0
        else:
            if sel["git"] and sel["open_prs"]:
                print("No task to start: " + ts.launcher_hint(plan, sel))
                if not (prs and wait_for_checks(root, cfg, prs, plan)):
                    print(f"Run `{self_command()} next` after a merge.")
                return 0
            if not sel["open"]:
                session.update({"task": None, "status": None})
                save_session(root, session)
                print("TELESMA COMPLETE — no unchecked item is left in the active phases. Finish per section 9 "
                      "(final full suite, report, docs/RUNBOOK.md, release proposal).")
                return 0
            lines = []
            for o, unmet in sel["blocked"][:10]:
                lines.append(f"- {plan.label(o)} waits for: {', '.join(unmet) or '?'}")
            reason = "every remaining task waits for an unfinished dependency"
            if sel["inactive"]:
                reason = ("a dependency is in a phase that is not active (`Active phases` in config.md): "
                          + "; ".join(f"{t} → {d} (phase {p})" for t, d, p in sel["inactive"][:5]))
            text = ("TELESMA BLOCKED\n\nProblem: " + reason + "\n" + "\n".join(lines) +
                    "\nNeed help with: activate the phase, reorder the plan, or finish the dependency by hand?")
            write_blocked(root, text)
            print(text)
            return 0

    stop = budget_check(root, session, again)
    if stop is not None:
        return stop
    line = plan.lines[item["idx"]]
    name = ts.name_of(plan, item)
    out, blockers, wrote = [], [], []
    spec_part(root, line, out, blockers, wrote)
    guideline_part(root, line, session, args.full, out, blockers)
    ui_part(root, line, out, blockers)
    change_part(root, line, out)
    if blockers:
        text = f"TELESMA BLOCKED\n\nTask: {name}\nProblem: " + "\n".join(blockers)
        write_blocked(root, text)
        print(text)
        return 0

    issues = int(session.get("issues", 0)) + 1 if again else 1
    if not again:
        session["next_wrote"] = []
    session["next_wrote"] = sorted(set(session.get("next_wrote") or []) | set(wrote))
    session["calls_since_next"] = 0
    if git_mode and not again:
        base = main or ghf.base_branch(root)
        if sel and sel["why"] == "chain":
            dep = next((d for d in item["deps"] if plan.pr_open(d)), None)
            pred = (prs or {}).get(plan.tasks[dep]["pr"]) if dep else None
            base = pred["headRefName"] if pred else base
        branch = ghf.branch_name(cfg, item["tid"], ts.title_of(plan.lines[item["idx"]]))
        try:
            # the branch carries the task's work only: what GitHub says (ticks, (pr:), history rows)
            # is written on main and committed by the state PR at the end of a phase — parallel task
            # PRs editing neighbouring plan lines would conflict at every merge
            restore_state_files(root)
            ghf.start_branch(root, branch, base)
        except ghf.GitHubError as e:
            print(f"TELESMA BLOCKED — the task branch could not be created: {e}")
            return 0
        session.update({"branch": branch, "base": base})
    session.update({"task": plan.key(item), "name": name, "status": None,
                    "issued": session.get("issued") if again and session.get("issued") else now().isoformat(timespec="seconds"),
                    "issues": issues, "refusals": int(session.get("refusals", 0)) if again else 0})
    save_session(root, session)

    phase = plan.phases.get(item["phase"] or "", {})
    head = f"TELESMA NEXT: {name}"
    if item["phase"]:
        head += f"   (Phase {item['phase']}: {phase.get('title', '')})"
    lines_out = [head]
    if again:
        lines_out.append(f"Issued again (issue {issues}; done refused {session['refusals']} times) — on a later try "
                         "widen the context (section 5).")
    if sel and sel["why"] == "chain":
        lines_out.append("Chain: it depends on unmerged " + ", ".join(sel["chain_waiting"]) +
                         " — branch off the branch of that PR (section 17.2).")
    if sel and sel["git"]:
        lines_out.append(ts.launcher_hint(plan, sel) + f" | branch `{session.get('branch')}` off `{session.get('base')}`")
    lines_out.append("\n## Task\n\n" + "\n".join(plan.block(item)))
    print("\n".join(lines_out))
    print("\n" + "\n\n".join(out))
    print(f"\n## When it is finished\n\nRun `{self_command()} done` (Bash tool timeout 600000): it runs the tests "
          "and the checks, ticks the task, writes the report row and commits. Do not tick PLAN.md, do not write the "
          "Task history row and do not run git add / git commit yourself.")
    return 0


# --- main -----------------------------------------------------------------------------------

class Args:
    def __init__(self):
        self.command, self.id, self.full, self.message, self.kind = None, None, False, "", None
        self.trailer, self.project, self.only = [], None, []
        self.source, self.detected_by, self.withdrawn, self.cont = None, None, False, False


def parse(argv):
    a = Args()
    it = iter(argv)
    for x in it:
        if x in ("-h", "--help"):
            return None
        if x == "--full":
            a.full = True
        elif x in ("-m", "--message"):
            a.message = next(it, "")
        elif x == "--trailer":
            a.trailer.append(next(it, ""))
        elif x == "--kind":
            a.kind = next(it, "")
        elif x == "--only":
            v = next(it, "")
            if not v or v.startswith(("/", "-")) or ".." in v.split("/"):
                raise Refused("--only takes a path inside the project, e.g. telesma/")
            a.only.append(v)
        elif x == "--project":
            a.project = next(it, None)
        elif x == "--source":
            a.source = next(it, "")
        elif x == "--detected-by":
            a.detected_by = next(it, "")
        elif x == "--withdrawn":
            a.withdrawn = True
        elif x == "--continue":
            a.cont = True
        elif x.startswith("-"):
            raise Refused(f"unknown option {x}")
        elif a.command is None:
            a.command = x
        elif a.command in ("done", "changes-done", "release") and a.id is None:
            a.id = x
        else:
            raise Refused(f"unexpected argument {x}")
    return a


def main(argv):
    try:
        a = parse(argv)
        commands = {"next": cmd_next, "done": cmd_done, "commit": cmd_commit, "suite": cmd_suite,
                    "changes": cmd_changes, "changes-done": cmd_changes_done, "session-start": cmd_session_start,
                    "release": cmd_release}
        if a is None or a.command not in commands:
            sys.stdout.write(__doc__)
            return 2
        root = project_root(a.project)
        check_trailers(a.trailer)
        return commands[a.command](root, a)
    except Refused as e:
        print(f"refused: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
