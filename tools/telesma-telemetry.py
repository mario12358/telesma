#!/usr/bin/env python3
"""Collector of events about the quality of Telesma's work — client of the Telesma hub server (payload: docs/TELEMETRY.md).

  python3 tools/telesma-telemetry.py <project>          # summary: what can be read out
  python3 tools/telesma-telemetry.py <project> --json   # events as JSONL on stdout
  python3 tools/telesma-telemetry.py <project> --send   # send per `## Telemetry` in config.md
                                                      # (telesma.sh does it in the background at startup)

Reads files Telesma leaves in the project anyway, which nobody reads with an eye on the
QUALITY OF THE FRAMEWORK: problem log, tries per task, bugfixes, reviews, blockers, outcomes
of interactive sessions, spec changes, manual scenario results, pitfalls, judge decisions.
Zero tokens, reads only — changes nothing in the project.

Two sources beyond the state files, because the report only says what Claude remembered to
write: git history (task id from the commit subject → time, files, later fixes) and this
machine's Claude Code transcripts (counters only: mode, model, tokens, tool errors).

What does NOT leave the machine: `telesma/spec/`, code, `telesma/changes/` (written by a human about the
product) or commands from PERMISSIONS.jsonl (they may hold secrets) — only counters go out
of the judge log. What goes out is text Telesma wrote about its own work, after `scrub()`.

An event id is a NATURAL key (project + type + entry opener), not a content hash: rotation
moves an entry from REPORT.md to the archive, Claude appends a lesson to it — it is still the
same event, and the server must overwrite it, not receive it a second time. What was already
sent is remembered in a file in ~/.cache/telesma/ (outside the repo: a state file in the project
would dirty the tree at every start and block release tagging). A failed send marks nothing
as sent, so the next start retries on its own — no separate queue is needed.
"""
import argparse
import collections
import datetime
import getpass
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = 2
TASK_ID = r"[0-9]+[A-Z]?(?:\.Z[0-9]+)?\.[0-9]+[a-z]?"
OPEN = re.compile(r"^-?\s*\[(\d{4}-\d{2}-\d{2})\]")
TASK = re.compile(r"^- \[( |x|X)\]\s*(\W*)(?:Task|Test)\s*(" + TASK_ID + r")")
ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?: \d{2}:\d{2})?\s*[—-]\s*(.+)$")
CHANGE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s+(.+)$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TASK_IN_TEXT = re.compile(r"(?:[Tt]asks?)\s*(" + TASK_ID + r")")
RESULT = re.compile(r"^- \[(.)\] \*\*Result ([\d.]+)")
FIELD = re.compile(r"^- \*\*(.+?)\*\*:\s*(.*)$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
STATE_FILES = ("PLAN.md", "REPORT.md", "PROJECT_CONTEXT.md", "DECISIONS.md", "BACKLOG.md")
ID_IN_SUBJECT = re.compile(r"(?<![\w.])(" + TASK_ID + r")(?!\w|\.\d)")
FIX = re.compile(r"\b(fix|hotfix|revert|repair)", re.I)
# Repository integration (section `## Integrations`): a task with a PR carries the `(pr: #12)`
# tag, and the merge (always squash) leaves a commit on main with `(#12)` at the end of the
# subject — the GitHub standard.
PR_TAG = re.compile(r"\(pr:\s*#?(\d+)\)")
PR_IN_SUBJECT = re.compile(r"\(#(\d+)\)\s*$|^Merge pull request #(\d+)")
PR_IN_TEXT = re.compile(r"#(\d+)")
FIX_WINDOW_S = 14 * 24 * 3600
KIND = re.compile(r"\*\*Kind\*\*:\s*`?([a-z]+)", re.I)
KINDS = {"bug", "correction", "feature", "question", "operations"}
DETECTED = re.compile(r"\*\*Detected by\*\*:\s*`?([a-z]+)", re.I)
LINES_OF_DEFENCE = {"test", "scenario", "review", "telesma", "owner", "production"}
TEST_CHANGE = re.compile(r"(chang\w*|modif\w*|delet\w*|remov\w*|rewr\w*) (\w+ ){0,3}"
                         r"(other\w* |existing )?(test|assert|setup)", re.I)
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|e2e|spec)/|\.test\.|\.spec\.|(^|/)test_[^/]*$|_test\.[a-z]+$")
BUG_SOURCE = re.compile(r"\*\*Bug source\*\*:\s*(?:tasks?\s*)?`?(" + TASK_ID + r")", re.I)
MODE = re.compile(r"MODE:\s*(autonomous|bugfix|review|artifacts)")
GAP_MIN = 180
COUNTERS_VERSION = 2    # bump when session_counters counts something new — invalidates the cache
TEST_RUN = re.compile(r"^\*\*[^*\n]*?(\d{4}-\d{2}-\d{2})")
# "api+shared 276/0, web 185/0, e2e 45/45" — that is how projects on Deno, Vitest and
# Playwright record runs: suite name, then passed/failed (e2e is sometimes passed/total). The
# parser used to know only pytest output ("3401 passed"), so half of the runs went without
# numbers, and a run with "web 250/1" was green to telemetry. The name starts with a letter
# but may contain a digit ("e2e"); the parenthesis before the numbers excludes
# "(3/8 failures on repeats)".
SUITE_PAIRS = re.compile(r"(?<![\w/(])([A-Za-z][\w+ ]{1,29}?)\s+(\d+)/(\d+)(?![\w/])")
# Extensions and tools are stronger evidence of a technology than guideline keywords
# ("state", "index", "role" appear in every text) — they count double.
TECH_EVIDENCE = {
    "python": r"\.py\b|\bpytest\b|\bpoetry\b|\bpip\b|\basyncio\b",
    "typescript": r"\.tsx?\b|\btsc\b|\btsconfig\b",
    "react": r"\.[jt]sx\b|\bvitest\b|\buse[A-Z]\w+\b|\bhook\w*\b",
    "sql": r"\.sql\b|\balembic\b|\bmigration\w*|\bSELECT\b|\bINSERT\b",
    "postgres": r"\bpostgres\w*|\bRLS\b|\bpgtap\b",
    "playwright": r"\bplaywright\b|\.spec\.ts\b",
    "docker": r"\bdocker\w*|\bcompose\b|\bcontainer\w*",
    "java": r"\.java\b|\bmaven\b|\bgradle\b",
    "react-native": r"\breact[- ]native\b|\bdetox\b|\bexpo\b",
}
BATCH_BYTES = 400_000
CACHE = Path.home() / ".cache" / "telesma"

SECRETS = [
    re.compile(r"\b(sk|pk|ghp|gho|glpat|xox[abp])[-_][A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s`'\"]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


# --- shared -------------------------------------------------------------------
def read_lines(p):
    return COMMENT.sub("", p.read_text(encoding="utf-8")).split("\n") if p.is_file() else []


def scrub(s):
    for r in SECRETS:
        s = r.sub(lambda m: (m.group(1) + " " if m.groups() else "") + "[removed]", s)
    return s.replace(str(Path.home()), "~").strip()


def cells(row):
    """Markdown table row → cells. `|` inside backticks and `\\|` do not split — Claude writes
    `accept|reject` in cells, and a naive split shifted the Tries column."""
    out, cur, code, k = [], "", False, 0
    while k < len(row):
        c = row[k]
        if c == "\\" and row[k + 1:k + 2] == "|":
            cur, k = cur + "|", k + 1
        elif c == "`":
            code, cur = not code, cur + c
        elif c == "|" and not code:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
        k += 1
    return out[1:]


def sections(t, prefix):
    """[(i, j)] of all `## ` sections whose title starts with the prefix."""
    out = []
    for i, l in enumerate(t):
        if l.startswith("## ") and l[3:].strip().startswith(prefix):
            out.append((i, next((k for k in range(i + 1, len(t)) if t[k].startswith("## ")),
                                len(t))))
    return out


def heading_blocks(t, pattern, i=0, j=None):
    """[(match, text)] — a block runs to the next heading of the same or a higher level."""
    j = len(t) if j is None else j
    level = None
    out, cur = [], None
    for k in range(i, j):
        m = pattern.match(t[k])
        if m:
            level = len(t[k]) - len(t[k].lstrip("#"))
            cur = [m, []]
            out.append(cur)
        elif cur and re.match(r"^#{1,%d} " % level, t[k]):
            cur = None
        elif cur:
            cur[1].append(t[k])
    return [(m, "\n".join(b).strip()) for m, b in out]


def phase_of(task):
    return task.rsplit(".", 1)[0] if task else None


# --- project ------------------------------------------------------------------
def git(project, *a):
    try:
        r = subprocess.run(["git", "-C", str(project), *a], capture_output=True, text=True,
                           timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def project_id(project):
    """Hash of the origin URL — the same project at two team members' machines must give the
    same id. Without git, the directory name is used."""
    url = re.sub(r"^\w+://[^@/]*@", "", git(project, "remote", "get-url", "origin"))
    url = re.sub(r"\.git$", "", url).lower()
    return hashlib.sha256((url or project.resolve().name).encode()).hexdigest()[:16]


def sender(project):
    """Who is sending. A write token may be shared by a whole team, so this — together with
    `project` in every event — is the only thing the server can tell people apart by. The
    identity comes from git (`user.email` as seen from the project, so with a local override),
    because it is the same on every machine of that person; the e-mail goes out as a hash, only
    the name stays readable. Without git: OS user + host. A signature, not authentication —
    access is guarded by the token."""
    try:
        os_user = getpass.getuser()
    except (OSError, KeyError):
        os_user = "unknown"
    email = git(project, "config", "user.email") or f"{os_user}@{socket.gethostname()}"
    name = git(project, "config", "user.name") or os_user
    return dict(id=hashlib.sha256(email.lower().encode()).hexdigest()[:12], name=name[:40])


def versions_over_time(project):
    """[(date, version)] ascending — from the history of telesma/state/.telesma-version. An event from May
    must carry the framework version from May, otherwise "before / after a change" means nothing."""
    out = []
    for l in git(project, "log", "--format=%H %ad", "--date=short", "--",
                 "telesma/state/.telesma-version").split("\n"):
        if " " in l:
            h, d = l.split(" ", 1)
            v = git(project, "show", f"{h}:telesma/state/.telesma-version")
            if v.isdigit():
                out.append((d, int(v)))
    return sorted(out)


def config(project):
    """{section: {field: value}} from telesma/config.md, without comment bodies."""
    out, sec = collections.defaultdict(dict), ""
    for l in read_lines(project / "telesma" / "config.md"):
        if l.startswith("## "):
            sec = l[3:].strip()
        m = FIELD.match(l)
        if m:
            out[sec][m.group(1)] = m.group(2).strip().strip("`")
    return out


def task_tags(state):
    """{task id: [tech]} from the plan and its archive — tags are what shows patterns ACROSS
    projects ("problems with postgres"); a log entry does not carry them by itself."""
    out = {}
    for n in ("PLAN_ARCHIVE.md", "PLAN.md"):
        for l in read_lines(state / n):
            m = TASK.match(l)
            if m:
                tech = re.search(r"\(tech:\s*([^)]*)\)", l)
                out[m.group(3)] = [x.strip() for x in tech.group(1).split(",")] if tech else []
    return out


def tech_dictionary(project, tags):
    """{tag: regex} only for technologies the project ACTUALLY uses (tags from the plan).
    A pitfall, a bugfix or a log entry without a task id carries no technology, and without it
    a retro session does not know which guideline to patch. Narrowing to the project's tags is
    the main source of precision: `role` in a project without postgres will not turn an entry
    into a postgres pitfall."""
    used = {t for tech in tags.values() for t in tech} - {"general"}
    out = {}
    for tag in used:
        words = []
        for d in (project / "telesma/guidelines", Path(__file__).resolve().parent.parent
                  / "templates/guidelines"):
            m = re.search(r"^keywords:\s*(.+)$", "\n".join(read_lines(d / f"{tag}.md")[:8]), re.M)
            if m:
                words = [x.strip() for x in m.group(1).split(",") if len(x.strip()) > 3]
                break
        out[tag] = (re.compile(TECH_EVIDENCE.get(tag, r"(?!x)x")),
                    re.compile(r"\b(" + "|".join(map(re.escape, words or [tag])) + r")\b", re.I))
    return out


def tech_from_text(text, dictionary):
    """Tags backed by at least 2 points: hard evidence = 2, keyword = 1.
    Measured on the reference project's log entries that know their technology from the task
    tag: precision 0.87, recall 0.53 (threshold 3: recall 0.03 — an entry rarely names two
    pieces of evidence)."""
    out = []
    for tag, (hard, words) in dictionary.items():
        if 2 * len(set(hard.findall(text))) + len({x.lower() for x in words.findall(text)}) >= 2:
            out.append(tag)
    return sorted(out)


def checked_off(state):
    return {m.group(3) for n in ("PLAN_ARCHIVE.md", "PLAN.md") for l in read_lines(state / n)
            for m in [TASK.match(l)] if m and m.group(1).lower() == "x"}


def task_prs(state):
    """{task id: PR number} from the `(pr: #n)` tag in the plan and archive. The tag stays after
    the merge, so it shows which tasks went through a PR at all — the denominator for the
    integration metrics."""
    out = {}
    for n in ("PLAN_ARCHIVE.md", "PLAN.md"):
        for l in read_lines(state / n):
            m, p = TASK.match(l), PR_TAG.search(l)
            if m and p:
                out[m.group(3)] = int(p.group(1))
    return out


# --- sources ------------------------------------------------------------------
def from_log(state):
    for n in ("REPORT_ARCHIVE.md", "REPORT.md"):
        t = read_lines(state / n)
        # In the archive the entries sit under `## Rotation <date>` mixed with everything
        # else, so there we search the whole file; in the report only the section, so as not
        # to catch unrelated lists.
        ranges = [(0, len(t))] if "ARCHIVE" in n else sections(t, "Problem log")
        for i, j in ranges:
            k = i
            while k < j:
                m = OPEN.match(t[k])
                if not m:
                    k += 1
                    continue
                e = k + 1
                while e < j and not OPEN.match(t[e]) and not t[e].startswith(("#", "|", ">")) \
                        and (t[e].startswith((" ", "\t")) or not t[e].strip()):
                    e += 1
                text = "\n".join(t[k:e]).strip()
                task = TASK_IN_TEXT.search(t[k])
                # A task that had to change an EXISTING test measures the fragility of the
                # suite (tests pinned to the implementation), not just discipline.
                metrics = dict(test_changed=bool(TEST_CHANGE.search(t[k])))
                if "[check]" in t[k]:
                    # A red required check on a PR (git integration): the fix goes to the same
                    # branch, and the log entry is the only trace that the check failed at all.
                    pr = PR_IN_TEXT.search(t[k])
                    metrics.update(red_check=True, pr=int(pr.group(1)) if pr else None)
                yield dict(type="problem", key=t[k][:160], date=m.group(1),
                           task=task.group(1) if task else None,
                           title=re.sub(r"^-?\s*\[[\d-]+\]\s*", "", t[k])[:200], text=text,
                           metrics=metrics)
                k = e


def from_history(state):
    for n in ("REPORT_ARCHIVE.md", "REPORT.md"):
        for l in read_lines(state / n):
            if not l.startswith("|"):
                continue
            c = cells(l)
            m = re.match(TASK_ID, c[0]) if len(c) >= 6 else None
            if not m:
                continue
            tries = re.match(r"\D{0,3}(\d+)", c[3])
            d = DATE.search(c[5]) or DATE.search(l)
            yield dict(type="task", key=m.group(0), date=d.group(0) if d else None,
                       task=m.group(0), title=c[0][:200], text="",
                       metrics=dict(tries=int(tries.group(1)) if tries else None,
                                    status=c[1][:20]))


def attempt(opener):
    """"GREEN on the first attempt" → 1, "only on the third attempt" → 3, none → None."""
    m = re.search(r"on the (first|second|third|fourth|fifth) (?:try|attempt|run)", opener, re.I)
    return ("first", "second", "third", "fourth", "fifth").index(m.group(1).lower()) + 1 \
        if m else None


def suite_duration(text):
    """Seconds of the longest run in the block: «(949 s)», «(08:10)», «(17:01 — …)». A full
    suite that takes longer with every phase is a growing cost of EVERY phase — and nobody was
    tracking it."""
    times = [int(s) for s in re.findall(r"\((\d{2,5}) s\b", text)]
    times += [int(m) * 60 + int(s) for m, s in re.findall(r"\((\d{1,2}):(\d{2})\b", text)]
    return max(times) if times else None


def from_test_runs(state):
    """Full-suite runs from `## Test status` (and `### Test status` in the archive).
    Regression at phase end is a central notion of Telesma's loop, and it was not in the data.
    Block = paragraph opened by bold text with a date; a paragraph without a date continues the
    previous one — the same definition as the rotation in telesma.sh. The key is date +
    phases, not the opener text: Claude renames "Run …" to "Previous run …" over time and that
    would make two events."""
    for n in ("REPORT_ARCHIVE.md", "REPORT.md"):
        in_section, block = False, None
        blocks = []
        for l in read_lines(state / n) + ["## end"]:
            if re.match(r"^#{2,3} ", l):
                in_section = l.lstrip("# ").startswith("Test status")
                block = None
                continue
            if not in_section or l.startswith("|"):
                continue
            m = TEST_RUN.match(l)
            if m:
                block = [m.group(1), [l]]
                blocks.append(block)
            elif block:
                block[1].append(l)
        for date, lines in blocks:
            text = "\n".join(lines).strip()
            opener = re.match(r"\*\*(.+?)\*\*", text, re.S)
            opener = re.sub(r"\s+", " ", opener.group(1) if opener else lines[0])
            # Phases stand between the word "Phase…" and a dash/parenthesis; `2.Z21.4/.5` is
            # phase 2.Z21.
            after_phase = re.search(r"Phases?\s+([^—):]*)", re.sub(r"\d{4}-\d{2}-\d{2}", "", opener),
                                    re.I)
            phases = sorted(set(re.findall(r"(?<![\w.])(\d+[A-Z]?(?:\.Z\d+)?)",
                                           after_phase.group(1)))) if after_phase else []
            numbers = {k: [int(x) for x in re.findall(r"(\d+) " + k, text)]
                       for k in ("passed", "failed", "skipped")}
            if not any(numbers.values()):
                pairs = SUITE_PAIRS.findall(text)
                if pairs:
                    # equal numbers > 0 are passed/total ("e2e 45/45"), not 45 failed
                    numbers["passed"] = [sum(int(a) for _, a, _ in pairs)]
                    numbers["failed"] = [sum(0 if (a == b and int(a) > 0) else int(b)
                                             for _, a, b in pairs)]
            verdict = "red" if re.search(r"\bRED\b", opener) else \
                "green" if re.search(r"\bGREEN\b", opener) else None
            yield dict(type="test_run", key=f"{date} {' '.join(phases) or opener[:80]}", date=date,
                       title=opener[:200], text=text[:3000],
                       metrics=dict(verdict=verdict, phases=phases,
                                    passed=max(numbers["passed"], default=None),
                                    failed=max(numbers["failed"], default=None),
                                    skipped=max(numbers["skipped"], default=None),
                                    # Red on the way: the final verdict is often green, while
                                    # the text says "3 failed" or "RED on the first attempt".
                                    red_on_the_way=bool(max(numbers["failed"], default=0)
                                                        or re.search(r"\bRED\b", text)),
                                    attempt=attempt(opener), duration_s=suite_duration(text)))


def kind(text):
    """`**Kind**: bug | correction | feature | question | operations` — a field of DECISIONS
    entries and of the Change history. `telesma/changes/` is the main channel through which a project
    GROWS, so neither the number of changes nor the share of rework says anything about the
    quality of the work; only how many of them are `bug` does. Entries written before the field
    existed get None — we do not guess."""
    m = KIND.search(text)
    return m.group(1).lower() if m and m.group(1).lower() in KINDS else None


def from_entries(state, file, typ):
    for m, text in heading_blocks(read_lines(state / file), ENTRY):
        task = TASK_IN_TEXT.search(m.group(2) + " " + text)
        ev = dict(type=typ, key=m.group(0)[:160], date=m.group(1), title=m.group(2)[:200],
                  task=task.group(1) if task else None, text=text)
        if typ == "decision":
            ev["metrics"] = dict(kind=kind(text))
        if typ == "bugfix":
            test = re.search(r"\*\*Test\*\*:\s*(.*)", text)
            # We do NOT assume `bug`: on the reference project 9 of 33 BUGFIXES.md entries were
            # new features and redesigns reported in bugfix mode.
            ev["metrics"] = dict(kind=kind(text), no_test=bool(
                test and re.search(r"no test|manual", test.group(1), re.I)))
        if typ == "review":
            f = re.search(r"🔴\s*(\d+).*?🟡\s*(\d+).*?🟢\s*(\d+)", text)
            if f:
                ev["metrics"] = dict(zip(("red", "yellow", "green"), map(int, f.groups())))
        yield ev


def from_change_history(state):
    for n in ("REPORT_ARCHIVE.md", "REPORT.md"):
        t = read_lines(state / n)
        for m, text in heading_blocks(t, CHANGE):
            if not m.group(2).strip().endswith(".md"):
                continue
            yield dict(type="change", key=m.group(2).strip()[:160], date=m.group(1),
                       title=m.group(2).strip()[:200], text=text,
                       metrics=dict(kind=kind(text),
                                    rework=bool(re.search(r"Phases? [\w.]*\.Z\d+", text))))


def from_pitfalls(state):
    title = "Known problems and solutions"
    for n in ("CONTEXT_ARCHIVE.md", "PROJECT_CONTEXT.md"):
        t, in_section = read_lines(state / n), False
        for l in t:
            if l.startswith("#"):
                in_section = l.lstrip("# ").strip() == title
            elif in_section and l.startswith("|"):
                c = cells(l)
                if len(c) >= 2 and c[0] not in ("Problem", "") and not set(c[0]) <= set("-: "):
                    d = DATE.search(l)
                    task = TASK_IN_TEXT.search(l)
                    yield dict(type="pitfall", key=c[0][:160], date=d.group(0) if d else None,
                               task=task.group(1) if task else None, title=c[0][:200],
                               text=f"{c[0]}\n→ {c[1]}", metrics=dict(pinned="📌" in c[0]))


def from_scenarios(project):
    for p in sorted((project / "docs" / "test-scenarios").glob("v*.md")):
        t = read_lines(p)
        count, bad, heading = collections.Counter(), [], ""
        for k, l in enumerate(t):
            if l.startswith("### "):
                heading = l[4:].strip()
            m = RESULT.match(l)
            if m:
                state = {"x": "works", "X": "works", "-": "broken", " ": "unchecked"} \
                    .get(m.group(1), "partial")
                count[state] += 1
                if state in ("broken", "partial"):
                    note = " ".join(x.strip() for x in t[k + 1:k + 4] if x.strip()
                                    and not x.startswith(("#", "- [", "---")))
                    bad.append(f"[{m.group(1)}] {m.group(2)} {heading} — {note}".strip(" —"))
        if not count:
            continue
        d = next((DATE.search(l) for l in t if l.startswith("- **Date")), None)
        yield dict(type="scenario", key=p.stem, date=d.group(0) if d else None,
                   title=p.stem, text="\n".join(bad), metrics=dict(count))


def blocker_episodes(project):
    """[(hash, ts_start, ts_end|None, text)] from the git history of telesma/state/BLOCKED.md.
    Telesma deletes the file once a blocker is resolved, so the directory shows the LAST one at
    best — and the question "how often and for how long does the loop wait on a human" needs
    all of them. Adding the file opens an episode, deleting it closes one; the text comes from
    the last version before deletion (Telesma appends progress to the blocker)."""
    head = git(project, "rev-parse", "HEAD")
    if not head:
        return []
    mem, save = cache_file(f"blockers-{project_id(project)}.json")
    if mem.get("head") == head:
        return mem["episodes"]
    episodes, open_ep = [], None
    for l in git(project, "log", "--reverse", "--format=%x01%H %at", "--name-status",
                 "--", "telesma/state/BLOCKED.md").split("\n"):
        if l.startswith("\x01"):
            h, ts = l[1:].split()
        elif l[:1] in "AM" and l.endswith("telesma/state/BLOCKED.md"):
            open_ep = [open_ep[0] if open_ep else h, open_ep[1] if open_ep else int(ts), None, h]
        elif l[:1] == "D" and open_ep:
            episodes.append(open_ep[:2] + [int(ts), open_ep[3]])
            open_ep = None
    if open_ep:
        episodes.append(open_ep)
    episodes = [[h, start, end, git(project, "show", f"{last}:telesma/state/BLOCKED.md")]
                for h, start, end, last in episodes]
    save(dict(head=head, episodes=episodes))
    return episodes


def describe_blocker(t):
    """(title, no_task, task id). A "Task: none" blocker means the loop ran out of work it can
    do and waits for the owner — not the same as being stuck on a task after the tries ran
    out, and only the latter says anything about the quality of the work."""
    problem = re.search(r"^(?:Problem|Reason):\s*(.+(?:\n[ \t]+.+)*)", t, re.M)
    task = re.search(r"^Task:\s*(.*)", t, re.M)
    # The format from the instructions is `Task: 7.3 …` — with a colon TASK_IN_TEXT does not know.
    nr = re.search(TASK_ID, task.group(1)) if task else TASK_IN_TEXT.search(t)
    title = re.sub(r"\s+", " ", problem.group(1)) if problem else \
        next((l for l in t.split("\n")[1:] if l.strip()), "blocker")
    # "No task" = the `Task:` line does not point at a specific id. The word "none" alone is not
    # enough: on the reference project Telesma wrote "items needing a business decision" there.
    return title[:200], not (task and nr), (nr.group(1) if nr and nr.groups() else
                                            nr.group(0) if nr else None)


def from_blockers(project, state):
    episodes = blocker_episodes(project)
    for h, start, end, text in episodes:
        t = COMMENT.sub("", text).strip()
        title, no_task, nr = describe_blocker(t)
        yield dict(type="blocker", key=h[:16],
                   date=datetime.date.fromtimestamp(start).isoformat(), task=nr,
                   title=title, text=t,
                   metrics=dict(hours=round((end - start) / 3600, 1) if end else None,
                                open=end is None, no_task=no_task))
    # The file exists, but git does not know it (not committed yet, or a project without git).
    t = "\n".join(read_lines(state / "BLOCKED.md")).strip()
    if t and not any(e[2] is None for e in episodes):
        d = DATE.search(t)
        title, no_task, nr = describe_blocker(t)
        yield dict(type="blocker", key=hashlib.sha256(t.encode()).hexdigest()[:16],
                   date=d.group(0) if d else str(datetime.date.today()), task=nr,
                   title=title, text=t,
                   metrics=dict(hours=None, open=True, no_task=no_task))


def from_permissions(state):
    """Counters per day only — commands from the judge log never leave the machine."""
    p = state / "PERMISSIONS.jsonl"
    if not p.is_file():
        return
    days = collections.defaultdict(collections.Counter)
    with p.open(encoding="utf-8") as f:
        for l in f:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            days[str(r.get("ts", ""))[:10]][f"{r.get('mode', '?')}/l{r.get('layer', '?')}/"
                                            f"{r.get('decision', '?')}"] += 1
    for d, count in days.items():
        if DATE.fullmatch(d):
            yield dict(type="permissions", key=d, date=d, title=f"judge decisions {d}",
                       text="", metrics=dict(count))


def cache_file(name):
    """(read, write) of a file in ~/.cache/telesma — outside the repo, like the send state."""
    path = CACHE / name

    def save(data):
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
    try:
        return json.loads(path.read_text(encoding="utf-8")), save
    except (OSError, ValueError):
        return {}, save


def numstat_counts(lines):
    """A single commit from `git log --numstat` → counters. From the path we take only the
    answer «test or not» — the file name does not leave."""
    n = dict(files=0, plus=0, minus=0, plus_tests=0)
    for l in lines:
        if l.count("\t") >= 2:
            added, deleted, path = l.split("\t", 2)
            if added.isdigit():             # binary files have «-»
                n["files"] += 1
                n["plus"] += int(added)
                n["minus"] += int(deleted)
                n["plus_tests"] += int(added) if TEST_FILE.search(path) else 0
    return n


def git_commits(project):
    """Commits without merges, oldest first: time, task ids from the subject, whether it is a
    fix, numstat counts. Shared by `from_git` and `from_prs`; cached by HEAD."""
    head = git(project, "rev-parse", "HEAD")
    if not head:
        return []
    mem, save = cache_file(f"git-{project_id(project)}.json")
    if mem.get("head") != head or mem.get("format") != 3:
        commits, cur = [], None
        for l in git(project, "log", "--no-merges", "--reverse", "--format=%x01%at%x00%s",
                     "--numstat").split("\n"):
            if l.startswith("\x01"):
                ts, _, subject = l[1:].partition("\x00")
                cur = dict(ts=int(ts), ids=sorted(set(ID_IN_SUBJECT.findall(subject))),
                           fix=bool(FIX.search(subject)), files=0, plus=0, minus=0, plus_tests=0)
                commits.append(cur)
            elif cur:
                for k, v in numstat_counts([l]).items():
                    cur[k] += v
        mem = dict(head=head, format=3, commits=commits)
        save(mem)
    return mem["commits"]


def pr_merges(project):
    """[{number, ts, ids, files, plus, minus, hours}] — commits closing a PR on the first-parent
    line of the current branch: a squash with `(#n)` at the end of the subject or a merge commit
    `Merge pull request #n`. ONLY the PR number and the task id come out of the subject.
    `hours` = from the branch's first commit to the merge — computable only for a merge commit
    (the second parent points at the branch); after a squash the branch does not exist in
    history → None."""
    head = git(project, "rev-parse", "HEAD")
    if not head:
        return []
    mem, save = cache_file(f"pr-{project_id(project)}.json")
    if mem.get("head") == head and mem.get("format") == 2:
        return mem["prs"]
    out, cur = [], None
    # --diff-merges=first-parent (git ≥ 2.31): a merge commit gets numstat against main;
    # older git does not know the flag → without it merges go without numbers, the rest as before.
    log = git(project, "log", "--first-parent", "--format=%x01%H%x00%at%x00%P%x00%s",
              "--numstat", "--diff-merges=first-parent") \
        or git(project, "log", "--first-parent", "--format=%x01%H%x00%at%x00%P%x00%s", "--numstat")
    for l in log.split("\n"):
        if l.startswith("\x01"):
            h, ts, parents, subject = l[1:].split("\x00", 3)
            m = PR_IN_SUBJECT.search(subject)
            cur = None
            if not m:
                continue
            cur = dict(number=int(m.group(1) or m.group(2)), ts=int(ts),
                       ids=sorted(set(ID_IN_SUBJECT.findall(subject))), hours=None,
                       files=0, plus=0, minus=0, plus_tests=0)
            p = parents.split()
            if len(p) >= 2:
                starts = [int(x) for x in git(project, "log", "--format=%at",
                                              f"{p[0]}..{p[1]}").split() if x.isdigit()]
                if starts:
                    cur["hours"] = round((int(ts) - min(starts)) / 3600, 1)
            out.append(cur)
        elif cur:
            for k, v in numstat_counts([l]).items():
                cur[k] += v
    save(dict(head=head, format=2, prs=out))
    return out


def from_prs(project, known):
    """One event per merged PR. Fixes = commits of that task from the 14 days before the merge
    minus the first — how many times the branch had to be revisited before the checks passed."""
    commits = git_commits(project)
    for p in pr_merges(project):
        task = next((z for z in p["ids"] if z in known), None)
        fixes = None
        if task:
            n = sum(1 for c in commits if task in c["ids"]
                    and p["ts"] - FIX_WINDOW_S <= c["ts"] <= p["ts"])
            fixes = max(n - 1, 0)
        yield dict(type="pr", key=f"pr:{p['number']}",
                   date=datetime.date.fromtimestamp(p["ts"]).isoformat(), task=task,
                   title=f"PR #{p['number']}", text="",
                   metrics=dict(number=p["number"], task=task, files=p["files"],
                                lines_added=p["plus"], lines_deleted=p["minus"],
                                hours_to_merge=p["hours"], fixes=fixes))


def from_git(project, known):
    """{task id: metrics from commit history}. A second source, INDEPENDENT of what Claude
    wrote in the report: on the reference project 35% of completed tasks had a row in
    `Task history` (in phases 40–119: 14 of 664), while a commit with the id in its subject —
    most of them. ONLY the id is taken from the subject; the commit text does not leave.
    A candidate counts only if it exists in the plan — otherwise `v0.27.0` would give task 0.27."""
    out, previous = {}, None
    for c in git_commits(project):
        for z in c["ids"]:
            if z not in known:
                continue
            if z not in out:
                gap = (c["ts"] - previous) // 60 if previous else None
                out[z] = dict(date=datetime.date.fromtimestamp(c["ts"]).isoformat(), commits=0,
                              fixes=0, files=c["files"], plus=c["plus"], minus=c["minus"],
                              plus_tests=c.get("plus_tests", 0),
                              # The gap from the previous commit approximates the task time;
                              # longer than a work break it says nothing, so then None.
                              minutes=gap if gap is not None and gap <= GAP_MIN else None)
            else:
                out[z]["fixes"] += c["fix"]
            out[z]["commits"] += 1
        previous = c["ts"]
    return out


def transcripts_dir(project):
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    for path in (project.resolve(), project.absolute()):
        d = base / re.sub(r"[^A-Za-z0-9]", "-", str(path))
        if d.is_dir():
            return d
    return None


def session_counters(file):
    """Claude Code transcript → COUNTERS ONLY. The conversation content is the client's code and
    product — nothing leaves it except the name of Telesma's mode (`MODE: …` from the startup
    prompt)."""
    n = dict(turns=0, tool_calls=0, tool_errors=0, compactions=0, models={}, mode=None,
             start=None, end=None, input=0, output=0, cache_read=0, cache_write=0,
             startup_prompt_chars=None, by_name={})
    with file.open(encoding="utf-8", errors="ignore") as f:
        for l in f:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            ts = r.get("timestamp")
            if isinstance(ts, str):
                n["start"] = n["start"] or ts
                n["end"] = ts
            if r.get("isCompactSummary") or r.get("subtype") == "compact_boundary":
                n["compactions"] += 1
            m = r.get("message") if isinstance(r.get("message"), dict) else {}
            u, model = m.get("usage"), m.get("model")
            if isinstance(u, dict) and model and not model.startswith("<"):
                n["turns"] += 1
                n["models"][model] = n["models"].get(model, 0) + 1
                for field, key in (("input", "input_tokens"), ("output", "output_tokens"),
                                   ("cache_read", "cache_read_input_tokens"),
                                   ("cache_write", "cache_creation_input_tokens")):
                    n[field] += u.get(key) or 0
            content = m.get("content")
            if n["startup_prompt_chars"] is None and r.get("type") == "user":
                text = content if isinstance(content, str) else " ".join(
                    b.get("text", "") for b in content or [] if isinstance(b, dict))
                # The first message of a session = the prompt assembled by telesma.sh. Its
                # SIZE is the fixed cost of every start (state files go into it in full) — a
                # number only.
                n["startup_prompt_chars"] = len(text)
                t = MODE.search(text)
                n["mode"] = t.group(1) if t else None
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("name"), str):
                    # Tool name, never arguments: shows whether a session reads (Read/Grep),
                    # writes (Edit/Write) or sits in the shell — with no trace of content.
                    name = b["name"].split("__")[0][:40]
                    n["by_name"][name] = n["by_name"].get(name, 0) + 1
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    n["tool_calls"] += 1
                    n["tool_errors"] += bool(b.get("is_error"))
    return n


def from_sessions(project):
    """One event per Claude Code session in this project, on THIS machine. Without it a
    framework change cannot be told apart from a model change (three different ones worked on
    the reference project within one month), and neither the cost nor how many tool calls end
    in an error is visible. A file is parsed once — then from the cache until its size or
    mtime changes."""
    d = transcripts_dir(project)
    if not d:
        return
    mem, save = cache_file(f"sessions-{project_id(project)}.json")
    new = {}
    for file in sorted(d.glob("*.jsonl")):
        st = file.stat()
        file_fingerprint = [st.st_size, int(st.st_mtime), COUNTERS_VERSION]
        old = mem.get(file.stem)
        new[file.stem] = old if old and old[0] == file_fingerprint \
            else [file_fingerprint, session_counters(file)]
    if new != mem:
        save(new)
    for sid, (_, n) in new.items():
        if not n["turns"] or not n["start"]:
            continue
        try:
            minutes = int((datetime.datetime.fromisoformat(n["end"].replace("Z", "+00:00"))
                           - datetime.datetime.fromisoformat(n["start"].replace("Z", "+00:00"))
                           ).total_seconds() // 60)
        except ValueError:
            minutes = None
        model = max(n["models"], key=n["models"].get)
        yield dict(type="session", key=sid, date=n["start"][:10],
                   title=f"session {n['start'][:10]} {n['mode'] or 'no mode'} {model}", text="",
                   metrics=dict(mode=n["mode"], model=model, models=n["models"], turns=n["turns"],
                                tool_calls=n["tool_calls"], tool_errors=n["tool_errors"],
                                compactions=n["compactions"], wall_minutes=minutes,
                                startup_prompt_chars=n.get("startup_prompt_chars"),
                                tools_by_name=dict(sorted(n.get("by_name", {}).items(),
                                                          key=lambda x: -x[1])[:12]),
                                tokens=dict(input=n["input"], output=n["output"],
                                            cache_read=n["cache_read"],
                                            cache_write=n["cache_write"])))


def state_file_diagnosis(project):
    """{damage: n, notice: m} from tools/telesma-repair.py (read-only). The findings' text stays
    local — only the number leaves: are the project's state files in shape, or are they
    swelling and breaking."""
    tool = Path(__file__).resolve().parent / "telesma-repair.py"
    if not tool.is_file():
        return None
    try:
        r = subprocess.run([sys.executable, str(tool), str(project)], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    counter = collections.Counter(l.split("\t", 1)[0] for l in r.stdout.split("\n") if "\t" in l)
    return dict(damage=counter.get("damage", 0), notice=counter.get("notice", 0))


def pr_statuses(state):
    """{posted, red, errors} from `pr-status` entries in telesma/state/CHECKS.jsonl."""
    out = collections.Counter()
    for l in read_lines(state / "CHECKS.jsonl"):
        try:
            w = json.loads(l)
        except ValueError:
            continue
        if w.get("check") != "pr-status":
            continue
        if w.get("decision") == "posted":
            out["posted"] += 1
            if w.get("state") == "failure":
                out["red"] += 1
        else:
            out["errors"] += 1
    return dict(out)


def from_state(project, state, cfg, tags):
    """Snapshot of the day: denominators for metrics (how many tasks) and the shape of the
    installation."""
    today = str(datetime.date.today())
    plan, pr = collections.Counter(), collections.Counter()
    for l in read_lines(state / "PLAN.md"):
        m = TASK.match(l)
        if m:
            plan["waiting_for_human" if "⛔" in m.group(2) and m.group(1) == " "
                 else "done" if m.group(1) != " " else "todo"] += 1
            if PR_TAG.search(l):
                # `[ ]` with the tag = PR open, waiting for merge; `[x]` = merged (the tag stays).
                pr["merged" if m.group(1) != " " else "open"] += 1
    q = collections.Counter(m.group(1) for l in read_lines(state / "QUESTIONS.md")
                            for m in [re.match(r"^### ([SAQ])\d", l)] if m)
    tests, loop, auto, integ = cfg.get("Tests", {}), cfg.get("Telesma loop", {}), \
        cfg.get("Auto-approval", {}), cfg.get("Integrations", {})
    yield dict(type="state", key=today, date=today, title=f"state {today}", text="", metrics=dict(
        plan=dict(plan), tasks_in_history=len(tags),
        # Shape of the integration (field values only) + how many tasks sit in PRs: without it
        # a project where the loop merges by itself cannot be told from one where PRs wait for
        # a human.
        integrations=dict(repository=integ.get("Repository"), merge=integ.get("Merge"),
                          tracker=integ.get("Tracker")),
        pr_open=pr["open"], pr_merged=pr["merged"],
        # "Telesma: checks (local)" statuses posted on PRs (counters from the checks log only):
        # red = a commit without evidence or a check that did not run.
        pr_statuses=pr_statuses(state),
        tech=dict(collections.Counter(x for v in tags.values() for x in v).most_common(15)),
        questions=dict(q),
        kb={n: (state / n).stat().st_size // 1024 for n in STATE_FILES if (state / n).is_file()},
        diagnosis=state_file_diagnosis(project),
        # Instructions go into the prompt in full at every start — every added rule is a fixed
        # token cost in every session of every project. Mode 1 loads CORE + INTERACTIVE.
        instructions_kb={f.name: f.stat().st_size // 1024 for f in sorted(
            (Path(__file__).resolve().parent.parent / "templates/instructions").glob("*.md"))},
        smoke=tests.get("Smoke suite", "none").lower() not in ("none", ""),
        max_tries=loop.get("Max tries per task"), judge=auto.get("Judge"),
        auto_approve=auto.get("Auto-approve")))


def from_git_tasks(project, state, tags):
    """Tasks seen in commits. Goes LAST in `collect`: a task with a row in the report gets
    `metrics.git` attached, and a task checked off in the plan without a row gets an event from
    git alone (`tries: None` — git does not know that)."""
    done = checked_off(state)
    for z, g in from_git(project, set(tags)).items():
        data = {k: v for k, v in g.items() if k != "date"}
        yield dict(type="task", key=z, date=g["date"], task=z, title=z, text="",
                   metrics=dict(tries=None, status="✅" if z in done else "?",
                                source="git", git=data))


def collect(project):
    state = project / "telesma" / "state"
    cfg = config(project)
    tags = task_tags(state)
    pid = project_id(project)
    # Empty label = the project directory name: on the server a project without a label is a
    # bare hash, and the directory name is the same for everyone who cloned the repo under it.
    label = cfg.get("Telemetry", {}).get("Project label", "").strip() \
        or project.resolve().name
    versions = versions_over_time(project)
    dictionary = tech_dictionary(project, tags)
    current = (state / ".telesma-version").read_text().strip() \
        if (state / ".telesma-version").is_file() else ""
    current = int(current) if current.isdigit() else None
    sources = (from_log(state), from_history(state), from_entries(state, "BUGFIXES.md", "bugfix"),
               from_entries(state, "REVIEWS.md", "review"),
               from_entries(state, "DECISIONS.md", "decision"),
               from_change_history(state), from_pitfalls(state), from_test_runs(state),
               from_scenarios(project),
               from_blockers(project, state), from_permissions(state), from_sessions(project),
               from_state(project, state, cfg, tags), from_prs(project, set(tags)),
               from_git_tasks(project, state, tags))
    pr = task_prs(state)
    out = {}
    for source in sources:
        for ev in source:
            ev["id"] = hashlib.sha256(f"{pid}|{ev['type']}|{ev['key']}".encode()).hexdigest()[:32]
            ev.update(schema=SCHEMA, project=pid, label=label,
                      phase=phase_of(ev.get("task")), tech=tags.get(ev.get("task"), []),
                      title=scrub(ev["title"]), text=scrub(ev["text"]),
                      key=scrub(ev["key"]))
            ev.setdefault("task", None)
            ev.setdefault("metrics", {})
            if not ev["tech"] and ev["type"] in ("problem", "pitfall", "bugfix"):
                # Technology from the text when the task tag did not give one — flagged,
                # because it is an inference, not a fact from the plan.
                ev["tech"] = tech_from_text(ev["title"] + "\n" + ev["text"], dictionary)
                if ev["tech"]:
                    ev["metrics"]["tech_from_text"] = True
            # An event older than the first commit of telesma/state/.telesma-version has an UNKNOWN version.
            # Stamping it with the first known one put 719 events (341 tasks from four months)
            # of the reference project into a "v2" bucket — and the version comparison lied.
            earlier = [v for d, v in versions if ev["date"] and d <= ev["date"]]
            # An event WITHOUT a date (a pitfall with no date in its row) must not get the current
            # version — an old pitfall would count toward the newest one. The current version is
            # given only in a project with no .telesma-version history at all (everything is "now").
            ev["format_version"] = earlier[-1] if earlier else (current if not versions else None)
            # The same entry may be in the report and in the archive (from before version 6 —
            # as a stump): the longer one stays.
            old = out.get(ev["id"])
            if old and ev["metrics"].get("source") == "git":
                # The task already has a row from the report: git only adds its numbers.
                old["metrics"]["git"] = ev["metrics"]["git"]
                old["date"] = old["date"] or ev["date"]
            elif not old or len(ev["text"]) > len(old["text"]):
                out[ev["id"]] = ev
    for ev in out.values():
        if ev["type"] == "task":
            # PR number from the tag in the plan (None = a task without a PR or a project
            # without the integration).
            ev["metrics"]["pr"] = pr.get(ev["task"])
    assign_bug_sources(out.values())
    return list(out.values())


def assign_bug_sources(events):
    """A bug is charged to the framework version under which it was INTRODUCED, not the one
    under which it was reported — otherwise every new version looks bad because of defects
    inherited from earlier ones, and measuring "did the change help" is worthless for the first
    months. The `**Bug source**` field points at the task that built the faulty thing; version
    and date come from THAT task's event. `source_version: None` with a known task = a task
    from before the project was versioned."""
    events = list(events)
    tasks = {e["task"]: e for e in events if e["type"] == "task"}
    for e in events:
        if e["metrics"].get("kind") != "bug":
            continue
        w = DETECTED.search(e["text"])
        e["metrics"]["detected_by"] = w.group(1).lower() \
            if w and w.group(1).lower() in LINES_OF_DEFENCE else None
        m = BUG_SOURCE.search(e["text"])
        source = tasks.get(m.group(1)) if m else None
        e["metrics"]["source_task"] = m.group(1) if m else None
        if source:
            e["metrics"].update(source_version=source["format_version"], source_date=source["date"],
                                source_tech=source["tech"])


# --- sending ------------------------------------------------------------------
def api_key(spec):
    """env:NAME | file:<path> | cmd:<command> | literal value; empty = no key."""
    if not spec.strip():
        return ""
    if spec.startswith("env:"):
        return os.environ.get(spec[4:].strip(), "")
    if spec.startswith("file:"):
        p = Path(os.path.expandvars(spec[5:].strip())).expanduser()
        return p.read_text(encoding="utf-8").split("\n")[0].strip() if p.is_file() else ""
    if spec.startswith("cmd:"):
        try:
            return subprocess.run(spec[4:], shell=True, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return spec


def ssl_contexts():
    """Python from python.org on macOS has no CA certificates and fails the handshake where
    `curl` works. With an `https://` endpoint the send would stay silent on some machines.
    Same order as the permission judge: default store → certifi → system bundle.
    Verification stays on in every variant — only the source of trusted CAs changes."""
    out = [None]
    try:
        import certifi
        out.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                 "/etc/pki/tls/certs/ca-bundle.crt"):
        if os.path.exists(path):
            try:
                out.append(ssl.create_default_context(cafile=path))
            except Exception:
                pass
    return out


def send_batch(req, timeout):
    error = None
    for ctx in ssl_contexts():
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                if r.status // 100 != 2:
                    raise OSError(f"HTTP {r.status}")
                try:
                    resp = json.loads(r.read() or b"{}")
                except ValueError:
                    resp = {}
            return set(resp.get("rejected_ids") or []) if isinstance(resp, dict) else set()
        except urllib.error.URLError as e:
            error = e
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                continue        # another CA store may help
            raise
    raise error


def error_file(project):
    return CACHE / f"telemetry-{project_id(project)}.error"


def fingerprint(ev):
    return hashlib.sha1(json.dumps(ev, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def send(project, events, limit_s):
    """→ (code, message). Code: 0 sent/nothing to send, 1 disabled, 2 error."""
    tel = config(project).get("Telemetry", {})
    if tel.get("Send", "no").lower() != "yes":
        return 1, "telemetry disabled (`Send: no`)"
    endpoint = tel.get("Endpoint", "")
    if not endpoint.startswith(("http://", "https://")):
        return 1, "endpoint not set"
    key = api_key(tel.get("API key", ""))
    if not key:
        return 2, (f"cannot read the key (`{tel.get('API key', '')}`) — "
                   f"set `API key` in telesma/config.md (env:NAME, file:<path> or cmd:<command>)")

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"telemetry-{project_id(project)}.json"
    try:
        sent = json.loads(path.read_text())
    except (OSError, ValueError):
        sent = {}
    new = [e for e in events if sent.get(e["id"]) != fingerprint(e)]
    if not new:
        return 0, "nothing new"

    batches, cur, size = [], [], 0
    for e in new:
        b = len(json.dumps(e, ensure_ascii=False).encode())
        if cur and size + b > BATCH_BYTES:
            batches.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += b
    batches.append(cur)

    deadline = datetime.datetime.now() + datetime.timedelta(seconds=limit_s)
    who = sender(project)
    delivered = refused = 0
    for batch in batches:
        left = (deadline - datetime.datetime.now()).total_seconds()
        if left <= 0:
            break
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/ingest", method="POST",
            data=json.dumps({"schema": SCHEMA, "sender": who, "events": batch},
                            ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            rejected = send_batch(req, min(15, left))
        except (OSError, ValueError) as e:
            path.write_text(json.dumps(sent))
            return 2, f"sent {delivered} of {len(new)}, then: {e}"
        # A hub older than the client does not know a new event type and rejects it. Such an
        # event is NOT sent — it goes again until the server is updated.
        for e in batch:
            if e["id"] not in rejected:
                sent[e["id"]] = fingerprint(e)
        delivered += len(batch) - len(rejected)
        refused += len(rejected)
    path.write_text(json.dumps(sent))
    waiting = len(new) - delivered - refused
    rest = f" (remaining {waiting} at the next start)" if waiting > 0 else ""
    old_hub = f"; {refused} rejected by the server — older hub version?" \
        if refused else ""
    return 0, f"sent {delivered}{rest}{old_hub}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", action="store_true", help="events as JSONL on stdout")
    ap.add_argument("--send", action="store_true", help="send per `## Telemetry`")
    ap.add_argument("--last-error", action="store_true",
                    help="show the error of the last send (empty = it got through)")
    ap.add_argument("--limit", type=int, default=60, help="time budget for sending [s]")
    a = ap.parse_args()
    if a.last_error:
        if error_file(a.project).is_file():
            print(error_file(a.project).read_text(encoding="utf-8").strip())
        return
    if not (a.project / "telesma").is_dir():
        sys.exit(f"No directory {a.project / 'telesma'}")
    events = collect(a.project)

    if a.json:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
    elif a.send:
        code, msg = send(a.project, events, a.limit)
        # The error lives until the first successful send — telesma.sh shows it at startup,
        # because the send itself runs in the background and has nowhere to complain.
        err = error_file(a.project)
        if code == 2:
            CACHE.mkdir(parents=True, exist_ok=True)
            err.write_text(f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}\n", encoding="utf-8")
        elif err.is_file():
            err.unlink()
        print(msg)
        sys.exit(code)
    else:
        types = collections.defaultdict(list)
        for e in events:
            types[e["type"]].append(e)
        print(f"Project {project_id(a.project)} — {len(events)} events")
        for typ, evs in sorted(types.items(), key=lambda x: -len(x[1])):
            dates = sorted(e["date"] for e in evs if e["date"])
            span = f"{dates[0]} … {dates[-1]}" if dates else "no dates"
            kb = sum(len(e["text"].encode()) for e in evs) // 1024
            print(f"  {typ:<12} {len(evs):>5}   {span}   {kb} KB of text")
        tg = [e["metrics"]["git"] for e in types["task"] if e["metrics"].get("git")]
        if tg:
            print(f"  tasks with numbers from git: {len(tg)} of {len(types['task'])}")
        no_kind = sum(1 for e in types["decision"] + types["change"] if not e["metrics"].get("kind"))
        if no_kind:
            print(f"  decisions and changes without a Kind field: {no_kind} "
                  f"(older than the field — not counted)")
        tries = [e["metrics"]["tries"] for e in types["task"] if e["metrics"].get("tries")]
        if tries:
            print(f"  tries/task: {sum(tries) / len(tries):.2f} "
                  f"(>1 try: {sum(1 for p in tries if p > 1)} of {len(tries)})")


if __name__ == "__main__":
    main()
