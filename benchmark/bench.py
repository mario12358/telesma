#!/usr/bin/env python3
"""Telesma's frozen benchmark — the same small project, from scratch, on a given framework version.

    python3 benchmark/bench.py run [--telesma <git ref|path>] [--label v8] [-n 3]
    python3 benchmark/bench.py judge <workspace> A|B                # judge only, no Telesma
    python3 benchmark/bench.py compare                              # table from benchmark/results/

Why: the reference project keeps growing and the models keep changing, so its data cannot tell
the effect of a framework change apart from everything else. Here ONLY the Telesma version changes.

The course of one run:
  stage A  frozen spec + frozen PLAN.md → `telesma.sh -m 1` until the plan is checked off
           → hidden stage A tests
  stage B  four frozen change requests into `telesma/changes/` → Telesma once more → hidden A+B tests
           (`telesma/changes/` is the main channel through which a project grows, and the rules of section 0.3 act there)
The judge is a set of tests Telesma DOES NOT SEE (`benchmark/hidden/`): they go through HTTP only,
so they measure what a user would see — including a mechanism that was built and wired to nothing.
The workspace lives outside the repository (~/.cache/telesma-bench), and the harness copies into it
only `project/` and `telesma/changes/`.

One run is an anecdote: the model is not deterministic. Compare series (`-n 3` and more)
and look at the spread, not at a single number. Changing anything in `project/`, `telesma/changes/` or
`hidden/` changes the benchmark fingerprint — results with different fingerprints are not comparable.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CACHE = Path.home() / ".cache" / "telesma-bench"
TEST_COMMAND = "python3 -m unittest discover -s tests"
PERMISSIONS = ("Bash(python3:*)", "Bash(python:*)", "Bash(mv:*)", "Bash(git mv:*)", "Bash(grep:*)",
               "Bash(curl:*)", "Bash(cat:*)", "Bash(kill:*)", "Bash(lsof:*)", "Bash(sleep:*)")
OPEN_TASK = re.compile(r"^- \[ \]\s*\W*(?:Task|Test)\b", re.M)
# The first real run (2026-09-19) exhausted the subscription's session limit halfway through stage B:
# Telesma exited with code 1 after 4 seconds, and the result looked like "did not finish the plan".
LIMIT = re.compile(r"hit your (session|usage|weekly)?\s*limit|usage limit reached|limit .{0,20}resets", re.I)


def benchmark_fingerprint():
    h = hashlib.sha256()
    for directory in ("project", "start_b", "changes", "hidden"):
        for p in sorted((HERE / directory).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and "reference" not in p.parts:
                h.update(str(p.relative_to(HERE)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:12]


def git(directory, *a):
    return subprocess.run(["git", "-C", str(directory), *a], capture_output=True, text=True).stdout.strip()


def telesma_dir(spec):
    """Path to the framework at the requested version. A git ref → a separate working tree (worktree),
    so the current repo stays untouched and two versions can run side by side."""
    if not spec or spec == "current":
        return REPO
    if Path(spec).is_dir():
        return Path(spec).resolve()
    commit = git(REPO, "rev-parse", "--verify", f"{spec}^{{commit}}")
    if not commit:
        sys.exit(f"No such directory or git ref: {spec}")
    target = CACHE / "telesma" / commit[:12]
    if not (target / "telesma.sh").is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(target), commit],
                       check=True, capture_output=True)
    return target


def set_field(text, field, value):
    new, n = re.subn(rf"^(- \*\*{re.escape(field)}\*\*:).*$", rf"\1 {value}", text, count=1, flags=re.M)
    return new if n else text


def prepare(telesma, ws, from_b):
    """`from_b`: start from the frozen state AFTER stage A (`start_b/` — code, tests and state files
    from a run that passed the stage A judge at 100%). Stage A costs half a run, and the rules
    about `telesma/changes/` act in stage B; a shared starting codebase also reduces the spread."""
    shutil.copytree(HERE / ("start_b" if from_b else "project"), ws)
    cfg = (telesma / "templates/config.md").read_text(encoding="utf-8")
    for field, value in (("Clarified", "yes"), ("Test command", TEST_COMMAND + " -v"),
                         ("Full suite command", TEST_COMMAND + " -v"),
                         ("Smoke suite", TEST_COMMAND), ("Linter/formatter", "none"),
                         # The benchmark does not clutter the team's hub — the harness collects events itself.
                         ("Send", "no")):
        cfg = set_field(cfg, field, value)
    cfg = cfg.replace("- **Allowed commands**:\n",
                      "- **Allowed commands**:\n" + "".join(f"  - {p}\n" for p in PERMISSIONS), 1)
    (ws / "telesma/config.md").write_text(cfg, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    git(ws, "add", "-A")
    subprocess.run(["git", "-C", str(ws), "-c", "user.name=bench", "-c", "user.email=bench@localhost",
                    "commit", "-q", "-m", "benchmark: initial state"], check=True)


def open_tasks(ws):
    plan = ws / "telesma/state/PLAN.md"
    return len(OPEN_TASK.findall(plan.read_text(encoding="utf-8"))) if plan.is_file() else -1


def pending_changes(ws):
    return [p.name for p in (ws / "telesma/changes").glob("*.md") if p.name != "EXAMPLE.md"] \
        if (ws / "telesma/changes").is_dir() else []


def start_telesma(telesma, ws, log, limit_s, model):
    env = dict(os.environ)
    if model:
        env["ANTHROPIC_MODEL"] = model
    t0 = time.time()
    offset = log.stat().st_size if log.is_file() else 0
    with log.open("ab") as f:
        f.write(f"\n===== start {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n".encode())
        f.flush()
        p = subprocess.Popen(["bash", str(telesma / "telesma.sh"), str(ws), "-m", "1"],
                             stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                             env=env, start_new_session=True)
        try:
            code = p.wait(timeout=limit_s)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            code = "time limit"
    with log.open("rb") as f:
        f.seek(offset)
        limit = bool(LIMIT.search(f.read().decode("utf-8", "ignore")))
    return dict(code=code, seconds=int(time.time() - t0), subscription_limit=limit)


def stage(name, telesma, ws, log, a):
    """Starts Telesma until the plan is checked off (and telesma/changes/ is empty) — the way a human
    resuming the session would. A blocker or no progress ends the stage."""
    starts = []
    for _ in range(a.max_starts):
        before = (open_tasks(ws), len(pending_changes(ws)), git(ws, "rev-parse", "HEAD"))
        starts.append(start_telesma(telesma, ws, log, a.limit_min * 60, a.model))
        after = (open_tasks(ws), len(pending_changes(ws)), git(ws, "rev-parse", "HEAD"))
        if starts[-1]["subscription_limit"] or (ws / "telesma/state/BLOCKED.md").is_file() \
                or (after[0] == 0 and after[1] == 0) or after == before:
            break
    blocked = ws / "telesma/state/BLOCKED.md"
    return dict(stage=name, starts=starts, interrupted_by_limit=starts[-1]["subscription_limit"],
                open_tasks=open_tasks(ws),
                unprocessed_changes=pending_changes(ws),
                blocker=blocked.read_text(encoding="utf-8")[:1500] if blocked.is_file() else None,
                judge=judge(ws, name), own_tests=own_tests(ws),
                commit=git(ws, "rev-parse", "--short", "HEAD"))


def judge(ws, name):
    r = subprocess.run([sys.executable, str(HERE / "hidden/judge.py"), str(ws), name],
                       capture_output=True, text=True, timeout=1800)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return dict(stage=name, total=0, passed=0, error=(r.stderr or r.stdout)[-800:])


def own_tests(ws):
    """Tests written by Telesma — for comparison with the judge: "green at my end" versus the result
    seen from outside is exactly the gap the benchmark is meant to measure."""
    try:
        r = subprocess.run(TEST_COMMAND.split(), cwd=ws, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(error=str(e)[:200])
    m = re.search(r"Ran (\d+) tests?", r.stderr)
    return dict(count=int(m.group(1)) if m else 0, green=r.returncode == 0 and bool(m))


def telemetry(ws):
    r = subprocess.run([sys.executable, str(REPO / "tools/telesma-telemetry.py"), str(ws), "--json"],
                       capture_output=True, text=True, timeout=300)
    ev = [json.loads(l) for l in r.stdout.split("\n") if l.strip()]
    sessions = [e["metrics"] for e in ev if e["type"] == "session"]
    tries = [e["metrics"]["tries"] for e in ev if e["type"] == "task" and e["metrics"].get("tries")]
    tools = sum(s["tool_calls"] for s in sessions)
    return dict(
        tasks=sum(e["type"] == "task" for e in ev), mean_tries=round(statistics.mean(tries), 2) if tries else None,
        problems=sum(e["type"] == "problem" for e in ev), pitfalls=sum(e["type"] == "pitfall" for e in ev),
        red_runs=sum(e["type"] == "test_run" and e["metrics"]["red_on_the_way"] for e in ev),
        ac_entry=len(re.findall(r"^\s+- AC: entry", (ws / "telesma/state/PLAN.md").read_text(encoding="utf-8"), re.M)),
        sessions=len(sessions), models=sorted({s["model"] for s in sessions}),
        output_tokens=sum(s["tokens"]["output"] for s in sessions), turns=sum(s["turns"] for s in sessions),
        compactions=sum(s["compactions"] for s in sessions),
        tool_error_percent=round(100 * sum(s["tool_errors"] for s in sessions) / tools, 1) if tools else None,
        commits=int(git(ws, "rev-list", "--count", "HEAD") or 0))


def run(a):
    telesma = telesma_dir(a.telesma)
    version = re.search(r"^TELESMA_FORMAT=(\d+)", (telesma / "telesma.sh").read_text(encoding="utf-8"), re.M)
    label = a.label or f"v{version.group(1) if version else '?'}"
    (HERE / "results").mkdir(exist_ok=True)
    for nr in range(1, a.n + 1):
        stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{label}-{nr}"
        ws = CACHE / "runs" / stamp / "project"
        ws.parent.mkdir(parents=True, exist_ok=True)
        log = ws.parent / "telesma.log"
        print(f"[{stamp}] workspace: {ws}", flush=True)
        prepare(telesma, ws, not a.full)
        t0 = time.time()
        result = dict(stamp=stamp, label=label, benchmark=benchmark_fingerprint(),
                      telesma_commit=git(telesma, "rev-parse", "--short", "HEAD"),
                      format_version=int(version.group(1)) if version else None, requested_model=a.model,
                      workspace=str(ws), stages=[])
        if a.full:
            result["stages"].append(stage("A", telesma, ws, log, a))
            print(f"[{stamp}] stage A: judge {result['stages'][0]['judge'].get('passed')}/"
                  f"{result['stages'][0]['judge'].get('total')}", flush=True)
            git(ws, "tag", "-f", "bench/stage-A")
        if not a.only_a and not any(s["interrupted_by_limit"] for s in result["stages"]):
            (ws / "telesma/changes").mkdir(exist_ok=True)
            for c in sorted((HERE / "changes").glob("*.md")):
                shutil.copy(c, ws / "telesma/changes" / c.name)
            result["stages"].append(stage("B", telesma, ws, log, a))
            print(f"[{stamp}] stage B: judge {result['stages'][-1]['judge'].get('passed')}/"
                  f"{result['stages'][-1]['judge'].get('total')}", flush=True)
        result["minutes"] = round((time.time() - t0) / 60, 1)
        result["telemetry"] = telemetry(ws)
        result["mode"] = "full" if a.full else "from_b"
        (HERE / "results" / f"{stamp}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        if any(s["interrupted_by_limit"] for s in result["stages"]):
            print(f"[{stamp}] INTERRUPTED: Claude subscription limit. The result is saved with a flag "
                  f"and left out of the comparison; series stopped — resume once the limit renews.", flush=True)
            break


def compare(_):
    groups = {}
    for p in sorted((HERE / "results").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        groups.setdefault((r["benchmark"], r["label"], r.get("mode", "full")), []).append(r)
    if not groups:
        sys.exit("No results in benchmark/results/.")

    def spread(values, fmt="{:.0f}"):
        values = [v for v in values if v is not None]
        if not values:
            return "—"
        return fmt.format(statistics.mean(values)) + (f" ({fmt.format(min(values))}–{fmt.format(max(values))})"
                                                      if len(values) > 1 else "")

    def percent(r, name):
        s = next((s for s in r["stages"] if s["stage"] == name and not s.get("interrupted_by_limit")), None)
        return 100 * s["judge"]["passed"] / s["judge"]["total"] if s and s["judge"].get("total") else None

    now = benchmark_fingerprint()
    print(f"benchmark (current fingerprint: {now}) — mean (min–max)\n")
    print(f"{'version':10} {'n':>2}  {'judge A %':>14}  {'judge B %':>14}  {'own tests':>13}  "
          f"{'minutes':>13}  {'out tokens (k)':>15}  {'AC entry':>10}  models")
    for (fingerprint, label, mode), rs in groups.items():
        last = [r["stages"][-1] for r in rs]
        interrupted = sum(any(s.get("interrupted_by_limit") for s in r["stages"]) for r in rs)
        print(f"{label + '/' + mode:10} {len(rs):>2}  {spread([percent(r, "A") for r in rs]):>14}  "
              f"{spread([percent(r, "B") for r in rs]):>14}  "
              f"{spread([s['own_tests'].get('count') for s in last]):>13}  "
              f"{spread([r['minutes'] for r in rs]):>13}  "
              f"{spread([r['telemetry']['output_tokens'] / 1000 for r in rs]):>15}  "
              f"{spread([r['telemetry']['ac_entry'] for r in rs]):>10}  "
              f"{','.join(sorted({m for r in rs for m in r['telemetry']['models']}))}"
              + (f"   ⚠ {interrupted} interrupted by the limit (stage left out)" if interrupted else "")
              + ("" if fingerprint == now else f"   ⚠ different benchmark fingerprint ({fingerprint})"))
    print("\nFailed judge tests (in how many runs):")
    for (fingerprint, label, mode), rs in groups.items():
        counter = {}
        for r in rs:
            for n in r["stages"][-1]["judge"].get("failed", []):
                counter[n] = counter.get(n, 0) + 1
        for n, count in sorted(counter.items(), key=lambda x: -x[1])[:12]:
            print(f"  {label:8} {count}/{len(rs)}  {n}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("run")
    u.add_argument("--telesma", default="current", help="git ref, path or `current`")
    u.add_argument("--label", help="series name in the comparison (default v<TELESMA_FORMAT>)")
    u.add_argument("-n", type=int, default=1, help="number of runs in the series")
    u.add_argument("--model", help="model for claude (ANTHROPIC_MODEL); default: the user's settings")
    u.add_argument("--limit-min", type=int, default=120, help="time limit of one Telesma start, in minutes")
    u.add_argument("--max-starts", type=int, default=4, help="how many times to resume Telesma within a stage")
    u.add_argument("--full", action="store_true",
                   help="start from an empty project (stage A + B); default: start from the state after stage A")
    u.add_argument("--only-a", action="store_true", help="with --full: skip stage B (the change requests)")
    u.set_defaults(f=run)
    o = sub.add_parser("judge")
    o.add_argument("ws")
    o.add_argument("stage", choices=["A", "B"])
    o.set_defaults(f=lambda a: print(json.dumps(judge(Path(a.ws), a.stage), ensure_ascii=False, indent=1)))
    sub.add_parser("compare").set_defaults(f=compare)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
