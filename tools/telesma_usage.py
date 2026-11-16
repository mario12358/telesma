#!/usr/bin/env python3
"""The local usage record (change plan K13): tokens, time and model per task, read from Claude
Code's transcripts by a script — the model reports nothing and has no say in it.

    telesma_usage.py report [PROJECT] [--csv]     the summary (`telesma.sh --usage`), or every row as CSV
    telesma_usage.py session --since ISO [--mode M] [--project DIR]
                                                  the launcher, after a Claude session: one `session` row;
                                                  prints `tasks minutes total cache_share models` for its line
    telesma_usage.py rebuild [PROJECT]            recount the task and session rows from the transcripts
                                                  still on this machine (after a fix of how they are counted)

Where the numbers come from: `~/.claude/projects/<project path>/<session>.jsonl` and the
session's subagents (`<session>/subagents/*.jsonl`). Claude Code writes one response over several
lines (one per content block), each with the same `message.id` and the same `usage`: a response
counts once (checked live: every line of a response carries identical usage). A compaction leaves
no usage line, only `compact_boundary` with `preTokens` — recorded as the context it summarised,
never added to the tokens.

The record lives in `.git/telesma-usage/usage.jsonl`: this machine's data, never committed (a shared
file would conflict), never in a prompt. One JSON object per line, counters only — no content, no
command, no path, no person:

    task     written by `telesma-task.py done`: the window from `next` to `done` — or from the end of
             the previous task, when both lie in one Claude session (a model that works first and
             calls `next` just before `done` would otherwise leave the work outside every task)
    session  written by the launcher after each Claude session: the whole session (tasks included;
             what is not in a task row is the overhead — start, compactions, clarification, modes 2/3/4)
    release  written by `telesma-task.py release`: a marker the report groups by

Time is counted twice: `minutes` is working time (the gaps of more than IDLE seconds between two
transcript lines — a question waiting for the person, a pause — left out), `wall_minutes` the clock.

Nothing here may stop the work: a transcript that cannot be read gives `usage: null` and a note.
Stdlib only, Python 3.9+.
"""
import collections
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

FIELDS = ("input", "output", "cache_read", "cache_write")
KEYS = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
        "cache_write": "cache_creation_input_tokens"}
RECORD = "usage.jsonl"
IDLE = 600                      # a gap longer than this between two transcript lines is not working time


# --- time -----------------------------------------------------------------------------------

def utc(value):
    """An ISO string (transcripts: UTC with Z; the task tool: local time without an offset) or a
    datetime → an aware UTC datetime, or None."""
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()             # a naive value is this machine's local time
    return dt.astimezone(datetime.timezone.utc)


def iso(dt):
    """UTC to the millisecond, as the transcripts write it: a window that ends here and the next one
    that opens here share no line."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


# --- transcripts ----------------------------------------------------------------------------

def transcripts_dir(project):
    base = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                        "projects")
    for path in (os.path.realpath(project), os.path.abspath(project)):
        d = os.path.join(base, re.sub(r"[^A-Za-z0-9]", "-", path))
        if os.path.isdir(d):
            return d
    return None


def transcript_files(d):
    out = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if name.endswith(".jsonl") and os.path.isfile(p):
            out.append(p)
        sub = os.path.join(p, "subagents")
        if os.path.isdir(sub):
            out += [os.path.join(sub, s) for s in sorted(os.listdir(sub)) if s.endswith(".jsonl")]
    return out


def empty():
    return {"models": {}, "turns": 0, "tool_calls": 0, "tool_errors": 0, "compactions": 0,
            "compacted_context": 0, "versions": []}


def usage(project, since=None, until=None):
    """Counters for what happened in the project's transcripts in [since, until). None when the
    project has no transcripts on this machine."""
    d = transcripts_dir(project)
    if not d:
        return None
    since, until = utc(since), utc(until)
    u = empty()
    seen, versions, stamps = set(), set(), []
    for path in transcript_files(d):
        try:
            if since and datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc) < since:
                continue                 # not written since the window opened
            f = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict):
                    continue
                t = utc(r.get("timestamp"))
                if t is None or (since and t < since) or (until and t >= until):
                    continue
                stamps.append(t)
                if r.get("subtype") == "compact_boundary":
                    u["compactions"] += 1
                    pre = (r.get("compactMetadata") or {}).get("preTokens")
                    u["compacted_context"] += pre if isinstance(pre, int) else 0
                m = r.get("message") if isinstance(r.get("message"), dict) else {}
                use, model = m.get("usage"), m.get("model")
                reply = m.get("id") or r.get("requestId")
                if isinstance(use, dict) and isinstance(model, str) and model and not model.startswith("<") \
                        and not (reply and reply in seen):
                    if reply:
                        seen.add(reply)
                    c = u["models"].setdefault(model[:60], {**dict.fromkeys(FIELDS, 0), "turns": 0})
                    for k in FIELDS:
                        v = use.get(KEYS[k])
                        c[k] += v if isinstance(v, int) else 0
                    c["turns"] += 1
                    u["turns"] += 1
                    if isinstance(r.get("version"), str):
                        versions.add(r["version"][:20])
                for b in m.get("content") if isinstance(m.get("content"), list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        u["tool_calls"] += 1
                        u["tool_errors"] += bool(b.get("is_error"))
    u["versions"] = sorted(versions)
    u["active_seconds"] = active_seconds(stamps)
    return u


def active_seconds(stamps):
    """Working time: the sum of the gaps between consecutive lines, a gap over IDLE left out."""
    stamps = sorted(stamps)
    return int(sum(g for g in ((b - a).total_seconds() for a, b in zip(stamps, stamps[1:])) if g <= IDLE))


def first_stamp(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    t = utc(json.loads(line).get("timestamp"))
                except (ValueError, AttributeError):
                    continue
                if t:
                    return t
    except OSError:
        pass
    return None


def one_session(project, a, b):
    """True when one main transcript (one Claude session) was written both at or before `a` and at
    or after `b`."""
    d = transcripts_dir(project)
    if not d:
        return False
    for name in os.listdir(d):
        path = os.path.join(d, name)
        if not name.endswith(".jsonl") or not os.path.isfile(path):
            continue
        try:
            last = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)
        except OSError:
            continue
        if last < b:
            continue
        first = first_stamp(path)
        if first and first <= a:
            return True
    return False


def stamps_between(project, a, b):
    """The times of the main transcripts' lines in [a, b]."""
    d = transcripts_dir(project)
    out = []
    for name in os.listdir(d) if d else []:
        path = os.path.join(d, name)
        try:
            if not name.endswith(".jsonl") or \
                    datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc) < a:
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        t = utc(json.loads(line).get("timestamp"))
                    except (ValueError, AttributeError):
                        continue
                    if t and a <= t <= b:
                        out.append(t)
        except OSError:
            continue
    return sorted(out)


def window_start(root, issued, rows=None):
    """Where a task's window opens: at `next`, or — when the previous task ended earlier in the same
    Claude session — where the work leading to this `next` began: the previous task's end, or the
    end of the last pause over IDLE between the two (a night, a question to the person) when there
    was one. `next`'s time has whole seconds, so an end up to a second after it is the same moment."""
    start = utc(issued)
    if not start:
        return None
    rows = read_rows(root) if rows is None else rows
    ends = [utc(r.get("to")) for r in rows if r.get("type") == "task"]
    prev = max((t for t in ends if t and t <= start + datetime.timedelta(seconds=1)), default=None)
    if not prev or not one_session(root, prev, start):
        return start
    if prev >= start:
        return prev
    opened = prev
    stamps = [prev] + stamps_between(root, prev, start) + [start]
    for x, y in zip(stamps, stamps[1:]):
        if (y - x).total_seconds() > IDLE:
            opened = y
    return opened


def task_label(name):
    """A task's short name for the record: `Task 3.2: …` → 3.2, `Test: 3.2 — …` → 3.2/test."""
    name = str(name or "?").strip()
    m = re.match(r"(?:-\s*\[.\]\s*)?Test:\s*([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)", name)
    if m:
        return m.group(1) + "/test"
    m = re.match(r"(?:-\s*\[.\]\s*)?Task\s+([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)", name)
    return m.group(1) if m else name[:40]


def sums(u):
    """{field: n} over every model of a usage dict (or of a row's `usage`)."""
    out = dict.fromkeys(FIELDS, 0)
    for c in ((u or {}).get("models") or {}).values():
        for k in FIELDS:
            out[k] += c.get(k, 0)
    return out


def total(u):
    return sum(sums(u).values())


def main_model(u):
    models = (u or {}).get("models") or {}
    return max(models, key=lambda m: models[m].get("output", 0)) if models else None


# --- the record -----------------------------------------------------------------------------

def record_path(root):
    r = subprocess.run(["git", "-C", root, "rev-parse", "--git-path", "telesma-usage"], capture_output=True, text=True)
    d = r.stdout.strip()
    if r.returncode != 0 or not d:
        return None
    d = d if os.path.isabs(d) else os.path.join(root, d)
    return os.path.join(d, RECORD)


def read_rows(root):
    path = record_path(root)
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("type"):
                    rows.append(r)
    except (OSError, TypeError):
        pass
    return rows


def append(root, row):
    """One row at the end of the record, atomically (temp file in the same directory, rename)."""
    path = record_path(root)
    if not path:
        raise OSError("no git directory")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    if text and not text.endswith("\n"):
        text += "\n"
    fd, tmp = tempfile.mkstemp(prefix=".usage-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text + json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)


def count_window(root, row, issued, end, rows=None):
    """Fill a task row's window, time and usage from the transcripts. Never raises."""
    row.pop("note", None)
    try:
        start = window_start(root, issued, rows)
    except Exception:                # noqa: BLE001
        start = utc(issued)
    row.update({"from": iso(start) if start else None, "issued": iso(utc(issued)) if utc(issued) else None,
                "wall_minutes": int((end - start).total_seconds() // 60) if start else None})
    row["minutes"] = row["wall_minutes"]
    try:
        u = usage(root, start, end) if start else None
        row["usage"] = u
        if u is None:
            row["note"] = "no transcripts of this project on this machine" if start else "no issue time"
        else:
            row["minutes"] = u["active_seconds"] // 60
    except Exception as e:           # noqa: BLE001 — the record never stops a task
        row["usage"], row["note"] = None, f"transcripts not readable: {type(e).__name__}"
    return row


def task_row(root, task, phase, since, commit=None, tests=None, attempts=None, refusals=None, fmt=None):
    """The `task` row for the task's window up to now. Never raises: a failure is a row without usage."""
    end = now_utc()
    row = {"type": "task", "task": task_label(task), "phase": phase, "to": iso(end),
           "commit": (commit or "")[:12] or None,
           "attempts": attempts, "refusals": refusals, "tests": (tests or None) and str(tests)[:80], "format": fmt}
    count_window(root, row, since, end)
    if commit:
        r = subprocess.run(["git", "-C", root, "show", "--shortstat", "--format=", commit], capture_output=True, text=True)
        s = r.stdout
        row["diff"] = {k: int(m.group(1)) if m else 0 for k, m in
                       (("files", re.search(r"(\d+) files? changed", s)), ("insertions", re.search(r"(\d+) insertion", s)),
                        ("deletions", re.search(r"(\d+) deletion", s)))}
    return row


def record_task(root, **kw):
    """`done`: write the task row; a failure is one line of output, never a refusal."""
    try:
        row = task_row(root, **kw)
        append(root, row)
        return row
    except Exception as e:           # noqa: BLE001
        print(f"note: the usage record was not written ({type(e).__name__}: {e})")
        return None


def session_row(root, since, mode=None):
    end = now_utc()
    return session_row_between(root, utc(since) or end, end, mode)


def session_row_between(root, start, end, mode=None, rows=None):
    u = usage(root, start, end)
    tasks = [r for r in (read_rows(root) if rows is None else rows) if r.get("type") == "task" and r.get("to")
             and start <= (utc(r["to"]) or start) <= end]
    in_tasks = dict.fromkeys(FIELDS, 0)
    for r in tasks:
        for k, v in sums(r.get("usage")).items():
            in_tasks[k] += v
    return {"type": "session", "from": iso(start), "to": iso(end), "mode": mode or None,
            "minutes": (u or {}).get("active_seconds", int((end - start).total_seconds())) // 60,
            "wall_minutes": int((end - start).total_seconds() // 60), "tasks": len(tasks), "usage": u,
            "in_tasks": in_tasks}


def rebuild(root):
    """Recount every task and session row from the transcripts still on this machine; the record is
    rewritten atomically. Returns (rows recounted, rows kept as they were)."""
    rows = read_rows(root)
    done, kept = [], 0
    for r in rows:
        if r["type"] == "task" and utc(r.get("to")) and transcripts_dir(root):
            r["task"] = task_label(r.get("task"))
            count_window(root, r, r.get("issued") or r.get("from"), utc(r["to"]), done)
        elif r["type"] == "session" and utc(r.get("from")) and utc(r.get("to")):
            fresh = session_row_between(root, utc(r["from"]), utc(r["to"]), r.get("mode"), done)
            if fresh["usage"] is not None:
                r.update(fresh)
        else:
            kept += 1
        done.append(r)
    path = record_path(root)
    fd, tmp = tempfile.mkstemp(prefix=".usage-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        for r in done:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return len(done) - kept, kept


# --- the report -----------------------------------------------------------------------------

def human(n):
    n = n or 0
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))


def hours(minutes):
    minutes = int(minutes or 0)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def cache_share(s):
    """Share of the input side served from the cache."""
    seen = s["input"] + s["cache_read"] + s["cache_write"]
    return round(100 * s["cache_read"] / seen) if seen else 0


def add(acc, s):
    for k in FIELDS:
        acc[k] += s.get(k, 0)
    return acc


def table(head, rows):
    w = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
    line = lambda r: "  " + "  ".join(str(x).rjust(w[i]) if i else str(x).ljust(w[i]) for i, x in enumerate(r))  # noqa: E731
    return "\n".join([line(head)] + [line(r) for r in rows])


def week(row):
    t = utc(row.get("from") or row.get("to"))
    if not t:
        return "?"
    y, wk, _ = t.isocalendar()
    return f"{y}-W{wk:02d}"


def report(root):
    rows = read_rows(root)
    tasks = [r for r in rows if r["type"] == "task"]
    sessions = [r for r in rows if r["type"] == "session"]
    releases = sorted((r for r in rows if r["type"] == "release" and r.get("at")), key=lambda r: r["at"])
    if not tasks and not sessions:
        return ("No usage recorded yet for this project on this machine. Telesma writes a row when a task is "
                "finished (`done`) and after each Claude session; the record is .git/telesma-usage/usage.jsonl.")
    out = []
    grand = add(dict.fromkeys(FIELDS, 0), {})
    for s in sessions:
        add(grand, sums(s.get("usage")))
    task_sum = dict.fromkeys(FIELDS, 0)
    for t in tasks:
        add(task_sum, sums(t.get("usage")))
    if not sessions:                     # tasks recorded, the sessions not (a start outside the launcher)
        grand = dict(task_sum)
    g_total, t_total = sum(grand.values()), sum(task_sum.values())
    first = min((r.get("from") or r.get("to") or "") for r in tasks + sessions)[:10]
    last = max((r.get("to") or "") for r in tasks + sessions)[:10]
    out.append(f"Telesma usage — {first} … {last} (this machine; tokens as Claude Code recorded them)")
    out.append("")
    out.append(f"  Sessions: {len(sessions)}, {hours(sum(s.get('minutes') or 0 for s in sessions))}")
    wall = sum(t.get("wall_minutes", t.get("minutes")) or 0 for t in tasks)
    out.append(f"  Tasks finished: {len(tasks)}, {hours(sum(t.get('minutes') or 0 for t in tasks))} of work "
               f"({hours(wall)} on the clock; a pause over {IDLE // 60} min is not work)")
    out.append(f"  Tokens: {human(g_total)} — input {human(grand['input'])}, output {human(grand['output'])}, "
               f"cache read {human(grand['cache_read'])}, cache write {human(grand['cache_write'])} "
               f"({cache_share(grand)}% of the input side from the cache)")
    if tasks:
        out.append(f"  Per task: {human(t_total / len(tasks))} tokens, output {human(task_sum['output'] / len(tasks))}, "
                   f"{hours(sum(t.get('minutes') or 0 for t in tasks) / len(tasks))}")
    if sessions and g_total:
        over = max(g_total - sum(sum(s.get("in_tasks", {}).values()) for s in sessions), 0)
        out.append(f"  Outside tasks (start, compactions, clarification, modes 2/3/4): {human(over)} "
                   f"({round(100 * over / g_total)}%)")
    comp = sum((s.get("usage") or {}).get("compactions", 0) for s in sessions) or \
        sum((t.get("usage") or {}).get("compactions", 0) for t in tasks)
    if comp:
        ctx = sum((s.get("usage") or {}).get("compacted_context", 0) for s in sessions) or \
            sum((t.get("usage") or {}).get("compacted_context", 0) for t in tasks)
        out.append(f"  Compactions: {comp}, {human(ctx)} tokens of context summarised (their own usage is not in "
                   "the transcripts, so not in the numbers above)")
    blind = [t for t in tasks if t.get("usage") is None]
    if blind:
        out.append(f"  Tasks without numbers: {len(blind)} ({blind[0].get('note') or 'no transcript'})")

    def group(title, key, source):
        acc = collections.OrderedDict()
        for r in source:
            k = key(r)
            a = acc.setdefault(k, {"n": 0, "min": 0, **dict.fromkeys(FIELDS, 0)})
            a["n"] += 1
            a["min"] += r.get("minutes") or 0
            add(a, sums(r.get("usage")))
        if not acc:
            return
        out.append("")
        out.append(title)
        out.append(table([title.split()[1].capitalize() if " " in title else "", "tasks", "time", "tokens", "output",
                          "per task", "cache"],
                         [[k, a["n"], hours(a["min"]), human(sum(a[f] for f in FIELDS)), human(a["output"]),
                           human(sum(a[f] for f in FIELDS) / a["n"]), f"{cache_share(a)}%"] for k, a in acc.items()]))

    by_phase = sorted(tasks, key=lambda t: [int(x) if x.isdigit() else x for x in re.split(r"[.]", str(t.get("phase") or "?"))])
    group("By phase", lambda t: str(t.get("phase") or "?"), by_phase)
    group("By model", lambda t: main_model(t.get("usage")) or ("no responses" if t.get("usage") else "?"), tasks)
    group("By week", week, sorted(tasks, key=lambda t: t.get("to") or ""))
    if releases:
        def release_of(t):
            for r in releases:
                if (t.get("to") or "") <= r["at"]:
                    return r.get("version") or "?"
            return "unreleased"
        group("By release", release_of, sorted(tasks, key=lambda t: t.get("to") or ""))

    if tasks:
        out.append("")
        out.append("Most tokens")
        top = sorted(tasks, key=lambda t: -total(t.get("usage")))[:5]
        out.append(table(["task", "tokens", "output", "time", "attempts", "model"],
                         [[t.get("task"), human(total(t.get("usage"))), human(sums(t.get("usage"))["output"]),
                           hours(t.get("minutes")), t.get("attempts") or 1, main_model(t.get("usage")) or "?"]
                          for t in top]))
        out.append("")
        out.append("Longest")
        top = sorted(tasks, key=lambda t: -(t.get("minutes") or 0))[:5]
        out.append(table(["task", "time", "clock", "tokens", "refusals", "attempts"],
                         [[t.get("task"), hours(t.get("minutes")), hours(t.get("wall_minutes", t.get("minutes"))),
                           human(total(t.get("usage"))), t.get("refusals") or 0, t.get("attempts") or 1] for t in top]))
        again = [t for t in tasks if (t.get("attempts") or 1) > 1 or (t.get("refusals") or 0) > 0]
        out.append("")
        out.append(f"Tasks that needed more than one try: {len(again)} of {len(tasks)}"
                   + (f" (refused done {sum(t.get('refusals') or 0 for t in again)} times in all)" if again else ""))
    out.append("")
    out.append("Every row: telesma.sh --usage --csv <project>")
    return "\n".join(out)


CSV_HEAD = ["type", "from", "to", "task", "phase", "mode", "version", "model", "minutes", "wall_minutes", "input", "output",
            "cache_read", "cache_write", "turns", "tool_calls", "tool_errors", "compactions", "compacted_context",
            "attempts", "refusals", "files", "insertions", "deletions", "commit", "claude_code"]


def write_csv(root, stream):
    w = csv.writer(stream)
    w.writerow(CSV_HEAD)
    for r in read_rows(root):
        u = r.get("usage") or {}
        s = sums(u)
        d = r.get("diff") or {}
        w.writerow([r.get("type"), r.get("from") or r.get("at"), r.get("to"), r.get("task"), r.get("phase"),
                    r.get("mode"), r.get("version"), main_model(u), r.get("minutes"), r.get("wall_minutes"),
                    s["input"], s["output"],
                    s["cache_read"], s["cache_write"], u.get("turns"), u.get("tool_calls"), u.get("tool_errors"),
                    u.get("compactions"), u.get("compacted_context"), r.get("attempts"), r.get("refusals"),
                    d.get("files"), d.get("insertions"), d.get("deletions"), r.get("commit"),
                    ",".join(u.get("versions") or [])])


# --- command line ---------------------------------------------------------------------------

def project_root(start):
    r = subprocess.run(["git", "-C", start or os.getcwd(), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main(argv):
    args, opts = [], {}
    it = iter(argv)
    for a in it:
        if a in ("--since", "--mode", "--project"):
            opts[a] = next(it, "")
        elif a == "--csv":
            opts[a] = True
        elif a in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return 0
        else:
            args.append(a)
    cmd = args[0] if args else None
    if cmd == "report":
        root = project_root(opts.get("--project") or (args[1] if len(args) > 1 else None))
        if not root:
            print("not a git work tree — give the project directory")
            return 2
        if opts.get("--csv"):
            write_csv(root, sys.stdout)
        else:
            print(report(root))
        return 0
    if cmd == "rebuild":
        root = project_root(args[1] if len(args) > 1 else opts.get("--project"))
        if not root or not record_path(root) or not os.path.exists(record_path(root)):
            print("no usage record in this project on this machine")
            return 2
        n, kept = rebuild(root)
        print(f"recounted {n} rows from the transcripts" + (f", {kept} kept as they were" if kept else ""))
        return 0
    if cmd == "session":
        root = project_root(opts.get("--project"))
        if not root or not utc(opts.get("--since")):
            return 2
        try:
            row = session_row(root, opts["--since"], opts.get("--mode"))
            if row["usage"] is None or not row["usage"]["turns"]:
                return 0                 # nothing reached Claude (an error at the start): no row, no line
            append(root, row)
        except Exception:                # noqa: BLE001 — the record never stops the launcher
            return 0
        s = sums(row["usage"])
        models = ",".join(sorted(row["usage"]["models"], key=lambda m: -row["usage"]["models"][m]["output"]))
        print(row["tasks"], hours(row["minutes"]), human(sum(s.values())), f"{cache_share(s)}%", models, sep="\t")
        return 0
    sys.stdout.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
