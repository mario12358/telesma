"""Shared reading and writing of Telesma's state files: the plan, the config, the report.

Stdlib only, Python 3.9+. Two readers use it: the launcher's plan check (the PYPLAN block in
telesma.sh: validation, the next-task hint, collapsing finished phases) and tools/telesma-task.py
(`next`, `done`, `commit`). The task the launcher names at start and the task `next` issues are
therefore chosen by the same code.

The tokens parsed here are a contract with the templates and the instructions (CLAUDE.md, "State
files are a contract"): `### Phase N: Title`, `- [ ] Task N.M:`, `(requires: X.Y)`, `(pr: #n)`,
`<!-- telesma-archived: … -->`, `- **Label**: value` in config.md, `## Task history`.
"""
import os
import re
import tempfile

PHASE_RE = re.compile(r"^### Phase ([0-9]+[A-Z]?(?:\.Z[0-9]+)?):\s*(.*)$")
# Task id: 1.2, 1M.2, 3.1a and the rework numbering 1.Z1.2 / 2M.Z1.3; a bare number (old style
# "Test 1:") is matched but NOT registered globally (it repeats per phase — that is not a duplicate)
TASK_ID = r"[0-9]+[A-Z]?(?:\.Z[0-9]+)?\.[0-9]+[a-z]?"
# Optional ✅ decoration after the checkbox — "- [x] ✅ Task..." is a checked task too
TASK_RE = re.compile(r"^- \[( |x|X)\]\s*\W*(?:Task|Test)\s*(" + TASK_ID + r"|[0-9]+)?\s*:?")
# Stub of a phase moved to telesma/state/PLAN_ARCHIVE.md (state file rotation). The list of ids in
# the comment keeps (requires: X.Y) on tasks from the archive resolvable.
ARCHIVED_RE = re.compile(r"^<!--\s*telesma-archived:\s*([^>]*?)\s*-->\s*$")
# Repository integration (section 17): `[ ]` + (pr: #n) = "waiting for the merge"
PR_RE = re.compile(r"\(pr:\s*#?([0-9]+)\)")
FIELD_RE = re.compile(r"^- \*\*(.+?)\*\*:[ \t]*(.*?)[ \t]*$")
WAITING_ON_HUMAN = "⛔"
FOOTER = "🤖 Generated with Telesma"

PLAN = "telesma/state/PLAN.md"
REPORT = "telesma/state/REPORT.md"
CONFIG = "telesma/config.md"
SPEC_INDEX = "telesma/state/SPEC_INDEX.md"
BLOCKED = "telesma/state/BLOCKED.md"
CHANGES = "telesma/changes"
CHANGES_EXAMPLE = "EXAMPLE.md"
GUIDELINES = "telesma/guidelines"
SPEC = "telesma/spec"


# --- files ----------------------------------------------------------------------------------

def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except OSError:
        return None


def atomic_write(path, text):
    """Temp file in the same directory, then rename (CLAUDE.md: state files are written
    atomically). The mode of an existing file is kept."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".telesma-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# --- config ---------------------------------------------------------------------------------

class Config:
    """`- **Label**: value` fields of telesma/config.md, by section."""

    def __init__(self, text):
        self.text = text or ""

    def section(self, name):
        m = re.search(r"^## " + re.escape(name) + r"\b.*?(?=^## |\Z)", self.text, re.M | re.S)
        return m.group(0) if m else ""

    def field(self, section, label, default=""):
        r = re.search(r"^- \*\*" + re.escape(label) + r"\*\*:[ \t]*(.*?)[ \t]*$", self.section(section), re.M)
        return r.group(1).strip() if r else default

    def anywhere(self, label, default=""):
        """A field looked up in the whole file (the launcher's older readers do it this way)."""
        r = re.search(r"^\-\s*\*\*" + re.escape(label) + r"\*\*:\s*(.+)$", self.text, re.M)
        return r.group(1).strip() if r else default


def load_config(root):
    return Config(read_text(os.path.join(root, CONFIG)))


def unset(value):
    """An empty, `none` or still-template (`[e.g. …]`) field value."""
    v = (value or "").strip()
    return not v or v.lower() in ("none", "-", "no") or v.startswith("[")


def is_yes(value):
    return (value or "").strip().lower() in ("yes", "true")


def git_integration(cfg):
    return cfg.field("Integrations", "Repository").lower() not in ("", "none")


def active_phases(cfg):
    value = cfg.anywhere("Active phases")
    if not value or value.lower() == "all":
        return None
    return {p.strip() for p in value.split(",") if p.strip()}


def phase_active(pid, active):
    if active is None or pid is None:
        return True
    return pid in active or re.sub(r"\.Z[0-9]+$", "", pid) in active


def ignore_patterns(cfg):
    """`Ignore on commit` patterns. They are written in backticks on purpose (a markdown linter
    turns a bare *.log into emphasis); bare comma-separated items are read too."""
    raw = cfg.field("Git", "Ignore on commit")
    items = re.findall(r"`([^`]+)`", raw) or [x.strip() for x in raw.split(",")]
    out = [x.strip() for x in items if x.strip() and not x.strip().startswith("[")]
    if is_yes(cfg.field("Visual artifacts", "Commit artifacts")):
        art = cfg.field("Visual artifacts", "Artifacts dir", "telesma/artifacts/").strip().rstrip("/") + "/"
        out = [p for p in out if p.rstrip("/") + "/" != art]
    return out


def ignored(path, patterns):
    """True when a repository-relative path matches an `Ignore on commit` pattern: `dir/` = that
    directory anywhere (or the path prefix when the pattern has a slash inside), otherwise a glob
    on the file name or on the whole path."""
    import fnmatch
    parts = path.split("/")
    for p in patterns:
        if p.endswith("/"):
            d = p.rstrip("/")
            if "/" in d:
                if path == d or path.startswith(d + "/"):
                    return True
            elif d in parts[:-1] or any(fnmatch.fnmatchcase(x, d) for x in parts[:-1]):
                return True
        elif "/" in p:
            if fnmatch.fnmatchcase(path, p):
                return True
        elif fnmatch.fnmatchcase(parts[-1], p):
            return True
    return False


# --- plan -----------------------------------------------------------------------------------

def tags(line, name):
    out = []
    for m in re.finditer(r"\(" + re.escape(name) + r":\s*([^)]*)\)", line):
        out += [v.strip() for v in m.group(1).split(",") if v.strip()]
    return out


def tag_values(line, name):
    """The whole tag value without splitting on commas — ui-*/flow tags have the format
    file#Id1,Id2 (commas separate identifiers, not separate files)."""
    return [m.group(1).strip() for m in re.finditer(r"\(" + re.escape(name) + r":\s*([^)]*)\)", line)]


class Plan:
    """telesma/state/PLAN.md as phases, tasks and the order of `- [ ]` / `- [x]` items.

    `order` holds one dict per item: idx (0-based line), tid (id or None), done, deps, phase, pr.
    `tasks` maps a dotted id to its item (and archived ids to a done stub)."""

    def __init__(self, text):
        self.text = text or ""
        self.lines = self.text.split("\n")
        self.phases = {}
        self.tasks = {}
        self.order = []
        self.pr_lines = {}
        self.errors = []
        cur = None
        for i, line in enumerate(self.lines):
            pm = PHASE_RE.match(line)
            if pm:
                cur = pm.group(1)
                if cur in self.phases:
                    self.errors.append(f"line {i+1}: duplicate Phase {cur}")
                self.phases[cur] = {"title": pm.group(2).strip(), "start": i, "tasks": [], "archived": False}
                continue
            am = ARCHIVED_RE.match(line)
            if am:
                if cur:
                    self.phases[cur]["archived"] = True
                for tid in am.group(1).split():
                    self.tasks.setdefault(tid, {"idx": i, "tid": tid, "done": True, "deps": [],
                                                "phase": cur, "pr": None, "archived": True})
                continue
            tm = TASK_RE.match(line)
            if not tm:
                continue
            prm = PR_RE.search(line)
            item = {"idx": i, "tid": tm.group(2), "done": tm.group(1).lower() == "x",
                    "deps": tags(line, "requires"), "phase": cur,
                    "pr": int(prm.group(1)) if prm else None, "archived": False}
            if cur:
                self.phases[cur]["tasks"].append(i)
            tid = item["tid"]
            if tid and "." in tid:
                if tid in self.tasks:
                    self.errors.append(f"line {i+1}: duplicate task id {tid}")
                else:
                    self.tasks[tid] = item
            self.order.append(item)
            if item["pr"] is not None:
                self.pr_lines[i] = item["pr"]
        self._done_at = {o["idx"]: o["done"] for o in self.order}

    def phase_complete(self, pid):
        p = self.phases.get(pid)
        if not p:
            return False
        if p["archived"]:
            return True       # a phase lands in PLAN_ARCHIVE.md only when 100% completed
        return bool(p["tasks"]) and all(self._done_at.get(j) for j in p["tasks"])

    def dep_done(self, d):
        if d in self.tasks:
            return self.tasks[d]["done"]
        if d in self.phases:
            return self.phase_complete(d)
        return False

    def pr_open(self, d):
        t = self.tasks.get(d)
        return bool(t) and not t["done"] and t.get("pr") is not None

    def label(self, item):
        tid = item["tid"]
        return tid if tid and "." in tid else f"line {item['idx']+1}"

    def find(self, key):
        """An item by a reservation key: {'tid': '2.1'} or {'phase', 'text'} for an item without a
        dotted id (`- [ ] Test: …`), found by its exact text so that a shifted line still matches."""
        if not key:
            return None
        tid = key.get("tid")
        if tid:
            t = self.tasks.get(tid)
            return t if t and not t.get("archived") else None
        for o in self.order:
            if o["phase"] == key.get("phase") and self.lines[o["idx"]] == key.get("text"):
                return o
        return None

    def key(self, item):
        tid = item["tid"]
        if tid and "." in tid:
            return {"tid": tid}
        return {"phase": item["phase"], "text": self.lines[item["idx"]]}

    def block(self, item):
        """The task line and the lines indented under it (`  - AC: …`, notes)."""
        i = item["idx"]
        out = [self.lines[i]]
        for line in self.lines[i + 1:]:
            if line.startswith((" ", "\t")) and line.strip():
                out.append(line)
            else:
                break
        return out

    def counts(self):
        """(checked, all) items, archived stubs included."""
        archived = [t for t in self.tasks.values() if t.get("archived")]
        return (sum(1 for o in self.order if o["done"]) + len(archived), len(self.order) + len(archived))


def load_plan(root):
    return Plan(read_text(os.path.join(root, PLAN)))


def title_of(line):
    """`- [ ] ⛔ Task 2.1: Login form (tech: react) <!-- … -->` → `Login form`."""
    t = re.sub(r"<!--.*?-->", "", line)
    t = re.sub(r"^- \[[ xX]\]\s*\W*", "", t)
    t = re.sub(r"^(?:Task|Test)\s*(?:" + TASK_ID + r"|[0-9]+)?\s*:?\s*", "", t)
    t = re.sub(r"\((?:requires|tech|spec|change|pr|ui-tokens|ui-component|ui-screen|screen|flow)\s*:[^)]*\)", "", t)
    t = t.replace(WAITING_ON_HUMAN, "").replace("✅", "")
    return re.sub(r"\s+", " ", t).strip(" —-")


def name_of(plan, item):
    """`Task 2.1: Login form` / `Test: …` — how a commit subject and a history row name the item."""
    line = plan.lines[item["idx"]]
    word = "Test" if re.match(r"^- \[[ xX]\]\s*\W*Test\b", line) else "Task"
    tid = item["tid"]
    head = f"{word} {tid}" if tid else word
    title = title_of(line)
    return f"{head}: {title}" if title else head


def select(plan, cfg):
    """The next item the loop takes — the rule the instructions used to state in prose (section 1,
    steps 1-3): the first unchecked item from the top of the plan, in an active phase, whose
    dependencies are complete. `⛔` ("waiting on a human") is taken only when nothing else is
    left; with a repository integration an item with (pr: #n) waits for its merge, and an item
    whose only unmet dependencies are open PRs comes back last as a "chain".

    Returns a dict: item (or None), why ('task' | 'human' | 'chain' | None), chain_waiting, and
    for the terminal states the open items that are blocked (with their unmet dependencies) and
    whether any of them depends on an inactive phase."""
    active = active_phases(cfg)
    git = git_integration(cfg)
    first = human = chain = None
    chain_waiting = []
    blocked = []
    for o in plan.order:
        if o["done"] or not phase_active(o["phase"], active):
            continue
        if o["idx"] in plan.pr_lines:
            continue                # PR open — waiting for the merge (section 17.1)
        deps = o["deps"]
        if git and chain is None and not all(plan.dep_done(d) for d in deps) \
                and all(plan.dep_done(d) or plan.pr_open(d) for d in deps):
            chain = o
            chain_waiting = [f"{d} (PR #{plan.tasks[d]['pr']})" for d in deps if plan.pr_open(d)]
        if all(plan.dep_done(d) for d in deps):
            if WAITING_ON_HUMAN in plan.lines[o["idx"]]:
                human = human or o
                continue
            first = o
            break
        blocked.append((o, [d for d in deps if not plan.dep_done(d)]))
    item, why = (first, "task") if first else (human, "human") if human else (chain, "chain") if chain \
        else (None, None)
    inactive = []
    for o, unmet in blocked:
        for d in unmet:
            pid = plan.tasks[d]["phase"] if d in plan.tasks else d if d in plan.phases else None
            if pid is not None and not phase_active(pid, active):
                inactive.append((plan.label(o), d, pid))
    open_left = [o for o in plan.order if not o["done"] and phase_active(o["phase"], active)]
    return {"item": item, "why": why, "chain_waiting": chain_waiting, "blocked": blocked,
            "inactive": inactive, "open": open_left, "git": git,
            "open_prs": open_prs(plan), "pr_limit": pr_limit(cfg)}


def open_prs(plan):
    return [(plan.pr_lines[o["idx"]], plan.label(o)) for o in plan.order
            if not o["done"] and o["idx"] in plan.pr_lines]


def pr_limit(cfg):
    v = cfg.field("Integrations", "Open PR limit")
    return int(v) if v.isdigit() else 3


def launcher_hint(plan, sel):
    """The `HINT:` line of the launcher's start prompt."""
    item, why = sel["item"], sel["why"]
    if why == "task":
        hint = plan.label(item)
    elif why == "human":
        hint = f"{plan.label(item)} (⛔ waiting on a human)"
    elif why == "chain":
        hint = f"{plan.label(item)} (chain — depends on unmerged: {', '.join(sel['chain_waiting'])}; section 17.2)"
    else:
        hint = ""
    if sel["git"]:
        prs = sel["open_prs"]
        listing = ", ".join(f"#{n}→{t}" for n, t in prs) or "none"
        if len(prs) >= sel["pr_limit"]:
            hint = (f"PR LIMIT REACHED ({len(prs)}/{sel['pr_limit']}: {listing}) — after the 17.1 reconciliation "
                    f"TELESMA WAITING, unless one of the PRs is red (17.4)" + (f"; queued: {hint}" if hint else ""))
        else:
            hint = (hint or "none — only PRs in progress") + f" | open PRs: {len(prs)}/{sel['pr_limit']} ({listing})"
    return hint


def tick(text, idx):
    """`- [ ]` → `- [x]` on line idx (0-based) of the plan text."""
    lines = text.split("\n")
    lines[idx] = re.sub(r"^- \[ \]", "- [x]", lines[idx], count=1)
    return "\n".join(lines)


# --- report ---------------------------------------------------------------------------------

def _section_bounds(lines, header):
    start = next((i for i, l in enumerate(lines) if l.rstrip() == header), None)
    if start is None:
        return None, None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return start, end


def cell(text):
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def add_history_row(text, cells):
    """A row at the end of the last table in `## Task history`. The template's empty row
    (`| | | | | | |`) is replaced; a section without a table gets the template's header."""
    lines = (text or "").split("\n")
    row = "| " + " | ".join(cell(c) for c in cells) + " |"
    start, end = _section_bounds(lines, "## Task history")
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## Task history", "", "| Task | Status | Tests | Tries | Commit | Time |",
                  "|------|--------|-------|-------|--------|------|", row, ""]
        return "\n".join(lines)
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if not rows:
        lines[start + 1:start + 1] = ["", "| Task | Status | Tests | Tries | Commit | Time |",
                                      "|------|--------|-------|-------|--------|------|", row]
        return "\n".join(lines)
    last = rows[-1]
    if re.fullmatch(r"\|(\s*\|)+\s*", lines[last].strip()):
        lines[last] = row
    else:
        lines.insert(last + 1, row)
    return "\n".join(lines)


def fill_summary(text, today):
    """The template's `Start` and `Status` placeholders, filled once by the first `done`; a value
    someone wrote stays."""
    text = re.sub(r"^(- \*\*Start\*\*:)[ \t]*\[start date\][ \t]*$", lambda m: f"{m.group(1)} {today}",
                  text or "", count=1, flags=re.M)
    return re.sub(r"^(- \*\*Status\*\*:)[ \t]*In progress \| Completed \| Blocked[ \t]*$",
                  lambda m: f"{m.group(1)} In progress", text, count=1, flags=re.M)


def resolve_history_commits(text, sha_for):
    """`this commit` in the Commit column of `## Task history` → the short SHA, once the row's commit
    exists. `sha_for(task name)` returns it or None (the row stays as it is)."""
    lines = (text or "").split("\n")
    start, end = _section_bounds(lines, "## Task history")
    if start is None:
        return text
    for i in range(start + 1, end):
        if "this commit" not in lines[i] or not lines[i].lstrip().startswith("|"):
            continue
        cells = re.split(r"(?<!\\)\|", lines[i].strip())[1:-1]
        if len(cells) < 5 or cells[4].strip() != "this commit":
            continue
        sha = sha_for(cells[0].strip().replace("\\|", "|"))
        if sha:
            cells[4] = f" {sha} "
            lines[i] = "|" + "|".join(cells) + "|"
    return "\n".join(lines)


def set_progress(text, done, total):
    return re.sub(r"^(- \*\*Progress\*\*:).*$", lambda m: f"{m.group(1)} {done}/{total} tasks completed",
                  text or "", count=1, flags=re.M)


# --- changes and blocks ---------------------------------------------------------------------

def pending_changes(root):
    d = os.path.join(root, CHANGES)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".md") and n != CHANGES_EXAMPLE
                       and os.path.isfile(os.path.join(d, n)))
    except OSError:
        return []
    return names


def frontmatter(text):
    """{key: value} of a `---` YAML-ish block at the top of a change file (flat keys only)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text or "", re.S)
    out = {}
    if m:
        for line in m.group(1).split("\n"):
            k, sep, v = line.partition(":")
            if sep and k.strip() and not k.startswith((" ", "\t")):
                out[k.strip().lower()] = v.strip().strip("'\"")
    return out


def change_order(root, names):
    """`priority: critical` first, then the rest; alphabetical within each (section 0.3)."""
    def prio(n):
        fm = frontmatter(read_text(os.path.join(root, CHANGES, n)) or "")
        return 0 if fm.get("priority", "").lower() == "critical" else 1
    return sorted(names, key=lambda n: (prio(n), n))


def dependency_errors(plan):
    """Pending tasks whose (requires:) names nothing, and dependency cycles."""
    errors = []
    for tid, t in plan.tasks.items():
        if t.get("archived") or t["done"]:
            continue
        for d in t["deps"]:
            if d not in plan.tasks and d not in plan.phases:
                errors.append(f"task {tid} (requires: {d}) — neither a task nor a phase {d} exists")
    state = {}

    def visit(tid, stack):
        state[tid] = 1
        for d in plan.tasks.get(tid, {}).get("deps", []):
            if d not in plan.tasks:
                continue
            if state.get(d) == 1:
                errors.append(f"dependency cycle: {' -> '.join(stack + [d])}")
                return True
            if state.get(d, 0) == 0 and visit(d, stack + [d]):
                return True
        state[tid] = 2
        return False
    for tid in plan.tasks:
        if state.get(tid, 0) == 0:
            visit(tid, [tid])
    return errors


# --- test status ----------------------------------------------------------------------------

def parse_counts(output):
    """{'total', 'pass', 'fail', 'skip'} from a test runner's summary, or None when nothing is
    recognised (pytest, unittest, jest/vitest, mocha, cargo, go)."""
    o = output or ""

    def last(p):
        m = re.findall(p, o, re.I | re.M)
        return int(m[-1]) if m else None
    passed = last(r"(\d+) passed") or last(r"(\d+) passing")
    failed = last(r"(\d+) failed") or last(r"(\d+) failing")
    skipped = last(r"(\d+) skipped") or last(r"(\d+) pending")
    total = last(r"Tests:.*?(\d+) total")
    ran = last(r"^Ran (\d+) tests?")
    if ran is not None:                                   # unittest
        f = (last(r"failures=(\d+)") or 0) + (last(r"errors=(\d+)") or 0)
        s = last(r"skipped=(\d+)") or 0
        return {"total": ran, "pass": ran - f - s, "fail": f, "skip": s}
    cargo = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", o)
    if cargo:
        p, f, s = (sum(int(c[i]) for c in cargo) for i in range(3))
        return {"total": p + f + s, "pass": p, "fail": f, "skip": s}
    if passed is None and failed is None:
        return None
    p, f, s = passed or 0, failed or 0, skipped or 0
    return {"total": total if total is not None else p + f + s, "pass": p, "fail": f, "skip": s}


def add_test_run(text, paragraph, counts, date):
    """A dated run paragraph above the metrics table of `## Test status`, and the table overwritten
    (the current state). The rotation keeps the three newest paragraphs by date."""
    lines = (text or "").split("\n")
    start, end = _section_bounds(lines, "## Test status")
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## Test status", "", paragraph, "", "| Metric | Value |", "|--------|-------|",
                  "| Last run | " + date + " |", ""]
        start, end = _section_bounds(lines, "## Test status")
    else:
        table = next((i for i in range(start + 1, end) if lines[i].lstrip().startswith("| Metric")), None)
        at = table if table is not None else end
        lines[at:at] = [paragraph, ""]
        end += 2
    values = {"Last run": date}
    if counts:
        values.update({"Total tests": counts["total"], "Pass": counts["pass"], "Fail": counts["fail"],
                       "Skip": counts["skip"]})
    for i in range(start + 1, end):
        m = re.match(r"^\|\s*([^|]+?)\s*\|", lines[i])
        if m and m.group(1) in values:
            lines[i] = f"| {m.group(1)} | {values[m.group(1)]} |"
    return "\n".join(lines)


def add_change_entry(text, entry):
    """A `### <date> <file>` block at the end of `## Change history` (created when missing)."""
    lines = (text or "").split("\n")
    start, end = _section_bounds(lines, "## Change history")
    block = entry.rstrip("\n").split("\n")
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines + ["", "## Change history", ""] + block + [""])
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines[at:at] = [""] + block
    return "\n".join(lines)
