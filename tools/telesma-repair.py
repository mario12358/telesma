#!/usr/bin/env python3
"""Diagnosis and repair of a Telesma project's state files.

Runs in two ways:

  python3 tools/telesma-repair.py <project>          # diagnosis only (telesma.sh does this
                                                   # at every start, silent when clean)
  python3 tools/telesma-repair.py <project> --fix    # repair (./telesma.sh --repair)

Repairs the damage left by the rotation from before version 6, which matched ONE LINE of an
entry instead of the whole block and therefore cut entries in half. The source of truth is git
history: an entry is restored from the commit in which it appeared (at that point its
neighbour had not been rotated yet, so nothing had been glued onto it). Without a git
repository content repair is impossible — only the diagnosis remains.
"""
import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

OPEN = re.compile(r"^-?\s*\[\d{4}-")
TASK_ID = r"[0-9]+[A-Z]?(?:\.Z[0-9]+)?\.[0-9]+[a-z]?"
TASK = re.compile(r"^- \[( |x|X)\]\s*\W*(?:Task|Test)\s*(" + TASK_ID + r"|[0-9]+)?\s*:?")
CHECKBOX = re.compile(r"^- \[[ xX]\]")
PHASE = re.compile(r"^### Phase ([\w.]+)")
ARCHIVED = re.compile(r"^<!--\s*telesma-archived:")
COMMENT = re.compile(r"\s*(<!--.*?-->)\s*$")
TAGS = re.compile(r"((?:\s*\([a-z-]+:[^)]*\))+)\s*$", re.I)
TASK_LIMIT = 400
# Warning thresholds. After rotation a large project fits within these numbers; exceeding them
# means it is not the NUMBER of entries that grows (rotation cuts that), but the size of a
# single entry.
THRESHOLDS_KB = {"PROJECT_CONTEXT.md": 40, "REPORT.md": 120, "PLAN.md": 250}
BOUNDARIES = ((".** ", ". ", "! ", "? "), ("; ", " — "), (": ", ") "))


# --- shared -----------------------------------------------------------------
def section(t, title):
    i = next((k for k, l in enumerate(t) if l.strip() == title), None)
    if i is None:
        return None
    return i, next((k for k in range(i + 1, len(t)) if t[k].startswith("## ")), len(t))


def blocks(t, i, j, start):
    starts = [k for k in range(i + 1, j) if start(t[k])]
    out = []
    for n, p in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else j
        while e - 1 > p and (not t[e - 1].strip() or t[e - 1].lstrip().startswith("<!--")):
            e -= 1
        out.append((p, e))
    return out


def squeeze_blanks(lines):
    """Three or more blank lines in a row → two."""
    out = []
    for l in lines:
        if not l.strip() and len(out) >= 2 and not out[-1].strip() and not out[-2].strip():
            continue
        out.append(l)
    return out


def paragraphs(t, i, j):
    out, cur = [], []
    for k in range(i + 1, j):
        if not t[k].strip():
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(t[k])
    if cur:
        out.append(cur)
    return out


# --- diagnosis --------------------------------------------------------------
def diagnose(state):
    """[(severity, message)] — severity 'damage' goes to repair, 'notice' is for information only."""
    out = []
    report, arch = state / "REPORT.md", state / "REPORT_ARCHIVE.md"

    if report.is_file():
        t = report.read_text(encoding="utf-8").split("\n")
        s = section(t, "## Problem log")
        if s:
            par = paragraphs(t, *s)
            orphans = [p for p in par if not OPEN.match(p[0].lstrip())
                       and not p[0].lstrip().startswith("<!--")]
            if orphans:
                out.append(("damage", f"{len(orphans)} paragraphs in `## Problem log` without an "
                                      f"entry of their own — bodies of entries whose first line "
                                      f"the old rotation took away (first one: line "
                                      f"{t.index(orphans[0][0]) + 1})"))
        s = section(t, "## Task history")
        if s:
            empty = 0
            for a, b in blocks(t, s[0], s[1], lambda l: l.startswith("### ")):
                rows = [k for k in range(a, b) if t[k].startswith("|")
                        and not t[k].replace(" ", "").startswith(("|Task", "|-"))]
                header = [k for k in range(a, b) if t[k].replace(" ", "").startswith("|Task")]
                if header and not rows:
                    empty += 1
            if empty:
                out.append(("notice", f"{empty} `### Phase …` subsections in `## Task history` "
                                      f"have a table header without a single row — either the old "
                                      f"rotation tore the rows out (--repair will restore them), "
                                      f"or the header is superfluous"))

    # Stumps in REPORT_ARCHIVE.md are NOT counted here: a one-line log entry is sometimes simply
    # short, and without git history a stump cannot be told apart from a complete one-liner.
    # --repair heals them along the way, because it compares against the version from the
    # commit in which they were created.

    plan_arch = state / "PLAN_ARCHIVE.md"
    if plan_arch.is_file():
        pend = [k + 1 for k, l in enumerate(plan_arch.read_text(encoding="utf-8").split("\n"))
                if l.startswith("- [ ]")]
        if pend:
            out.append(("damage", f"{len(pend)} unfinished tasks `- [ ]` in PLAN_ARCHIVE.md "
                                  f"(lines {', '.join(str(x) for x in pend[:5])}) — a phase went "
                                  f"to the archive with unfinished work and the loop cannot see it"))

    plan = state / "PLAN.md"
    if plan.is_file():
        t = plan.read_text(encoding="utf-8").split("\n")
        long_ = [k + 1 for k, l in enumerate(t) if TASK.match(l) and len(l) > TASK_LIMIT]
        if long_:
            out.append(("damage", f"{len(long_)} tasks longer than {TASK_LIMIT} characters "
                                  f"(lines {', '.join(str(x) for x in long_[:5])})"))
        done = [k + 1 for k, l in enumerate(t)
                if CHECKBOX.match(l) and not TASK.match(l) and l.startswith("- [x]")]
        if done:
            out.append(("damage", f"{len(done)} `- [x]` items without the word Task/Test "
                                  f"(lines {', '.join(str(x) for x in done[:5])}) — implementation "
                                  f"notes written down as tasks; invisible to the loop, yet they "
                                  f"read like finished work"))
        open_ = [k + 1 for k, l in enumerate(t)
                 if CHECKBOX.match(l) and not TASK.match(l) and l.startswith("- [ ]")]
        if open_:
            out.append(("notice", f"{len(open_)} `- [ ]` items without the word Task/Test "
                                  f"(lines {', '.join(str(x) for x in open_[:5])}) — something "
                                  f"unfinished that is not a task: either give it a number and "
                                  f"tags, or move it to telesma/state/BACKLOG.md. This cannot be decided "
                                  f"mechanically."))

    ctx = state / "PROJECT_CONTEXT.md"
    if ctx.is_file():
        t = ctx.read_text(encoding="utf-8").split("\n")
        if any(l.strip() == "## Known pitfalls" for l in t):
            out.append(("notice", "PROJECT_CONTEXT.md has both `## Known pitfalls` and `## Known "
                                  "problems and solutions` — one job in two places, and only the "
                                  "latter is rotated (fold the list into the table)"))
        for title in ("## Key decisions", "## Known problems and solutions"):
            s = section(t, title)
            if s:
                long_ = [l for l in t[s[0]:s[1]] if l.startswith("|") and not l.startswith("|-") and len(l) > 400]
                if long_:
                    out.append(("notice", f"{len(long_)} `{title[3:]}` rows longer than 400 "
                                          f"characters — only the first 400 go into the prompt; "
                                          f"a decision or a pitfall is one or two sentences, the "
                                          f"rationale belongs in the Problem log"))
        s = section(t, "## Current state")
        if s and sum(len(l) + 1 for l in t[s[0]:s[1]]) > 2000:
            out.append(("notice", "`## Current state` in PROJECT_CONTEXT.md exceeds 2 KB — it is "
                                  "current state to be overwritten, not a chronicle of turns; "
                                  "nothing rotates it"))

    for name, threshold in THRESHOLDS_KB.items():
        f = state / name
        if f.is_file():
            kb = f.stat().st_size / 1024
            if kb > threshold:
                out.append(("notice", f"{name} weighs {kb:.0f} KB (threshold {threshold} KB) — "
                                      f"rotation cuts the NUMBER of entries, not their size; "
                                      f"shorten individual entries"))
    return out


# --- content repair (needs git) ---------------------------------------------
def versions_from_git(repo):
    """{first line of an entry: full block} — from the commit in which the entry appeared, and
    {subsection header: longest block} for Task history (rows are added legitimately)."""
    shas = subprocess.run(["git", "-C", str(repo), "log", "--format=%H", "--", "telesma/state/REPORT.md"],
                          capture_output=True, text=True).stdout.split()
    log, hist = {}, {}
    for s in reversed(shas):                     # oldest first
        txt = subprocess.run(["git", "-C", str(repo), "show", f"{s}:telesma/state/REPORT.md"],
                             capture_output=True, text=True).stdout
        t = txt.split("\n")
        for title, target, start in (("## Problem log", log, lambda l: OPEN.match(l.lstrip())),
                                     ("## Task history", hist, lambda l: l.startswith("### "))):
            s_ = section(t, title)
            if not s_:
                continue
            for a, b in blocks(t, s_[0], s_[1], start):
                block, key = "\n".join(t[a:b]), t[a].strip()
                if target is log:
                    target.setdefault(key, block)
                elif len(block) > len(target.get(key, "")):
                    target[key] = block
    return log, hist


def repair_report(state, log, hist, in_archive=""):
    """Repair NEVER deletes content that git does not know — it may have been written after the
    last commit or (like notes moved from PLAN.md) by a previous repair run. Hence two different
    operations, both conservative:

    - Task history: we ADD table rows missing from a subsection. Nothing is removed — prose
      under the table and anything written later stays untouched.
    - Problem log: we replace a block with the git version only when EVERY disappearing line
      is already in the archive. Otherwise the block stays as it is.
    """
    changes = []
    report = state / "REPORT.md"
    if not report.is_file():
        return changes
    t = report.read_text(encoding="utf-8").split("\n")

    # --- Task history: add missing table rows ---
    s_ = section(t, "## Task history")
    if s_:
        i, j = s_
        filled = 0
        for a_, b_ in reversed(blocks(t, i, j, lambda l: l.startswith("### "))):
            canon = hist.get(t[a_].strip())
            if not canon:
                continue
            def rows(lines):
                return [l for l in lines if l.startswith("|")
                        and not l.replace(" ", "").startswith(("|Task", "|-"))]
            missing = [w for w in rows(canon.split("\n")) if w not in t[a_:b_]]
            if not missing:
                continue
            present = rows(t[a_:b_])
            if present:
                where = a_ + max(k for k in range(b_ - a_) if t[a_ + k] in present) + 1
            else:
                headers = [k for k in range(a_, b_)
                           if t[k].replace(" ", "").startswith("|-")]
                where = (headers[-1] + 1) if headers else a_ + 1
            t = t[:where] + missing + t[where:]
            filled += 1
        if filled:
            changes.append(f"Task history: {filled} subsections completed with missing "
                           f"table rows")

    # --- Problem log: replace a block, but only when nothing gets lost ---
    s_ = section(t, "## Problem log")
    if s_:
        i, j = s_
        bl = blocks(t, i, j, lambda l: OPEN.match(l.lstrip()))
        covered = {k for a_, b_ in bl for k in range(a_, b_)}
        replace = dict(bl)
        new_lines, restored, removed, skip = [], 0, 0, set()
        for k in range(i, j):
            if k in skip:
                continue
            if k in replace:
                canon = log.get(t[k].strip())
                old = t[k:replace[k]]
                lost = [l for l in old if l.strip() and l not in (canon or "").split("\n")]
                if canon and canon.rstrip() != "\n".join(old).rstrip() \
                        and all(l.strip() in in_archive for l in lost):
                    new_lines += canon.split("\n")
                    restored += 1
                    removed += len(lost)
                else:
                    new_lines += old
                skip |= set(range(k, replace[k]))
                new_lines.append("")
                continue
            if k in covered:
                continue
            # A line outside any entry is an orphan of an entry whose first line the old
            # rotation took away. We remove it ONLY when its text is already in the archive.
            if (t[k].strip() and not t[k].lstrip().startswith(("<!--", "|", "#"))
                    and t[k].strip() in in_archive):
                removed += 1
                continue
            new_lines.append(t[k])
        if restored or removed:
            changes.append(f"Problem log: {restored} entries restored from history, "
                           f"{removed} orphaned lines removed")
        t = t[:i] + new_lines + t[j:]

    report.write_text("\n".join(squeeze_blanks(t)), encoding="utf-8")
    return changes


def repair_archive(state, log):
    """Stump → full entry. We compare the WHOLE archive block (entry up to the next entry or
    header), not just the first line — otherwise a second run would append the text again."""
    arch = state / "REPORT_ARCHIVE.md"
    if not arch.is_file():
        return []
    a = arch.read_text(encoding="utf-8").split("\n")
    bounds = [k for k, l in enumerate(a)
              if l.startswith(("### ", "## ")) or (l.strip() and OPEN.match(l.strip()))]
    in_log, healed, out, skip = False, 0, [], set()
    for k, l in enumerate(a):
        if k in skip:
            continue
        if l.startswith(("### ", "## ")):
            in_log = l.strip() == "### Problem log"
            out.append(l)
            continue
        if in_log and l.strip() and OPEN.match(l.strip()):
            end = next((g for g in bounds if g > k), len(a))
            while end - 1 > k and not a[end - 1].strip():
                end -= 1
            canon, old = log.get(l.strip()), "\n".join(a[k:end])
            if canon and canon.rstrip() != old.rstrip():
                out += canon.split("\n")
                healed += 1
                skip |= set(range(k, end))
                continue
        out.append(l)
    if not healed:
        return []
    out += ["", f"## Repair {datetime.date.today().isoformat()}", "",
            "Stumps in `### Problem log` blocks completed with full text from git history.",
            "Reason: the rotation from before version 6 archived the first line of an entry "
            "instead of the block.", ""]
    arch.write_text("\n".join(out), encoding="utf-8")
    return [f"REPORT_ARCHIVE.md: {healed} stumps completed with full text"]



# --- restoring phases archived with unfinished work -------------------------
def restore_phases(state):
    """A phase with a `- [ ]` task HAD NO RIGHT to go to the archive. It went there because
    `TASK_RE` did not see a task marked ⛔ — the phase then looked 100% complete.

    Undoing it is not a decision about content: the block in PLAN_ARCHIVE.md is literally what
    rotation cut out of the plan, and the `### Phase N … — ✅ completed` stub is what it put in
    its place. We swap one for the other. Phases with no stub in the plan are left alone —
    someone has already edited there by hand, and guessing the place would be worse than
    reporting it."""
    plan, arch = state / "PLAN.md", state / "PLAN_ARCHIVE.md"
    if not (plan.is_file() and arch.is_file()):
        return []
    a = arch.read_text(encoding="utf-8").split("\n")
    starts = [k for k, l in enumerate(a) if PHASE.match(l)]
    candidates = []
    for n, k in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(a)
        e = min(e, next((m for m in range(k + 1, e) if a[m].startswith("## ")), e))
        while e - 1 > k and not a[e - 1].strip():
            e -= 1
        if any(l.startswith("- [ ]") for l in a[k:e]):
            candidates.append((PHASE.match(a[k]).group(1), k, e))
    if not candidates:
        return []

    t = plan.read_text(encoding="utf-8").split("\n")
    restored, skipped, taken = [], [], set()
    for pid, k, e in candidates:
        stub = next((m for m, l in enumerate(t)
                     if PHASE.match(l) and PHASE.match(l).group(1) == pid
                     and "✅ completed" in l), None)
        if stub is None:
            skipped.append(pid)
            continue
        end = stub + 1
        while end < len(t) and (ARCHIVED.match(t[end]) or not t[end].strip()):
            end += 1
        t = t[:stub] + a[k:e] + [""] + t[end:]
        taken |= {pid}
        restored.append(pid)
    if not restored:
        return [f"PLAN_ARCHIVE.md: phases {', '.join(skipped)} have unfinished tasks, "
                f"but PLAN.md has no stub for them — restore them by hand"] if skipped else []

    plan.write_text("\n".join(t), encoding="utf-8")
    drop = {i for pid, k, e in candidates if pid in taken for i in range(k, e)}
    marker = {k: pid for pid, k, e in candidates if pid in taken}
    out = []
    for i, l in enumerate(a):
        if i in marker:
            out.append(f"> Phase {marker[i]} restored to PLAN.md "
                       f"({datetime.date.today().isoformat()}) — it had unfinished tasks, "
                       f"so it must not have been archived.")
        if i not in drop:
            out.append(l)
    arch.write_text("\n".join(out), encoding="utf-8")
    msgs = [f"PLAN.md: phases with unfinished work restored from the archive: {', '.join(restored)}"]
    if skipped:
        msgs.append(f"PLAN_ARCHIVE.md: phases {', '.join(skipped)} have no stub in the plan — "
                    f"restore them by hand")
    return msgs


# --- notes posing as tasks --------------------------------------------------
def line_date(repo, file, line):
    """Date of the commit that introduced this line. `-S` counts changes in the number of
    occurrences, so for a line added once it points at exactly that commit."""
    r = subprocess.run(["git", "-C", str(repo), "log", "-S", line, "--format=%ad",
                        "--date=short", "--", file], capture_output=True, text=True)
    dates = [x for x in r.stdout.split() if x]
    return dates[-1] if dates else ""


def move_notes(state, repo):
    """A `- [x]` without the word Task/Test is an implementation note written down as a task.
    Its place is `## Task history` in REPORT.md, under the phase in which it was written —
    the phase comes from its position in the plan, the date from the commit that introduced
    the note. `- [ ]` notes are NOT touched: something unfinished that is not a task needs a
    human's decision."""
    plan, report = state / "PLAN.md", state / "REPORT.md"
    if not (plan.is_file() and report.is_file()):
        return []
    t = plan.read_text(encoding="utf-8").split("\n")
    phase, notes = "?", []
    for i, l in enumerate(t):
        m = PHASE.match(l)
        if m:
            phase = m.group(1)
        if CHECKBOX.match(l) and not TASK.match(l) and l.startswith("- [x]"):
            notes.append((i, phase, l))
    if not notes:
        return []
    dates = {i: line_date(repo, "telesma/state/PLAN.md", l) for i, _, l in notes}
    if not all(dates.values()):
        return ["PLAN.md: notes posing as tasks left alone — not every one can be dated "
                "from git history (the date drives the entry's rotation in REPORT.md)"]

    r = report.read_text(encoding="utf-8").split("\n")
    s = section(r, "## Task history")
    if not s:
        return ["REPORT.md: no `## Task history` section — the notes stay in PLAN.md"]
    i, j = s
    sub = {}
    for a_, b_ in blocks(r, i, j, lambda l: l.startswith("### ")):
        m = re.match(r"^### Phases? ([\w.]+)", r[a_])
        if m:
            sub[m.group(1)] = b_
    groups = {}
    for idx, f, l in notes:
        g = groups.setdefault(f, {"date": "", "lines": []})
        g["lines"].append(re.sub(r"^- \[[ xX]\]\s*", "", l).strip())
        g["date"] = max(g["date"], dates[idx])

    inserts, new_sections = {}, []
    for f, g in groups.items():
        lines = [x if x.startswith((">", "⚠", "**", "`")) else f"⚠ {x}" for x in g["lines"]]
        lines = [f"> {x}" for x in lines]
        if f in sub:
            inserts.setdefault(sub[f], []).extend([""] + lines)
        else:
            new_sections += ["", f"### Phase {f} — implementation notes moved from PLAN.md "
                                 f"({g['date']})", ""] + lines
    out = []
    for k, l in enumerate(r):
        if k in inserts:
            out += inserts[k]
        if k == j:
            out += new_sections + [""]
        out.append(l)
    if j >= len(r):
        out += new_sections
    report.write_text("\n".join(squeeze_blanks(out)), encoding="utf-8")
    plan.write_text("\n".join(l for k, l in enumerate(t) if k not in {i for i, _, _ in notes}),
                    encoding="utf-8")
    return [f"PLAN.md → REPORT.md: {len(notes)} notes posing as tasks moved "
            f"to `## Task history` ({len(groups)} phases)"]


# --- PLAN.md repair ---------------------------------------------------------
def balanced(s):
    return (s.count("**") % 2 == 0 and s.count("`") % 2 == 0
            and s.count("(") == s.count(")")
            and s.count("„") <= s.count("”") + s.count('"'))


def split(body, limit, at_word=True):
    if len(body) <= limit:
        return body, ""
    p = body.find("⚠")
    if 40 < p <= limit and balanced(body[:p]):
        return body[:p].rstrip(), body[p:].strip()
    for kind in BOUNDARIES:
        best = -1
        for g in kind:
            k = body.rfind(g, 40, limit + 1)
            while k >= 40:
                if k + len(g) > best and balanced(body[:k + len(g)]):
                    best = k + len(g)
                    break
                k = body.rfind(g, 40, k)
        if best >= 40:
            return body[:best].rstrip(), body[best:].strip()
    if not at_word:
        return body, ""
    best = body.rfind(" ", 40, limit + 1)
    return (body, "") if best < 40 else (body[:best].rstrip(), body[best:].strip())


def repair_plan(state):
    plan = state / "PLAN.md"
    if not plan.is_file():
        return []
    t = plan.read_text(encoding="utf-8").split("\n")
    phase, notes, new, extracted, wrapped = "?", [], [], 0, 0
    for line in t:
        m = re.match(r"^### Phase ([\w.]+)", line)
        if m:
            phase = m.group(1)
        if not TASK.match(line):
            new.append(line)
            continue
        cm = COMMENT.search(line)
        if cm and len(line) > TASK_LIMIT:
            tid = TASK.match(line).group(2) or "?"
            notes.append((phase, tid, cm.group(1)))
            line = COMMENT.sub("", line)
            extracted += 1
        if len(line) <= TASK_LIMIT:
            new.append(line)
            continue
        tm = TAGS.search(line)
        tags = tm.group(1).strip() if tm else ""
        body = line[:tm.start()].rstrip() if tm else line
        head, rest = split(body, TASK_LIMIT - (len(tags) + 1 if tags else 0))
        new.append((head + " " + tags).rstrip() if tags else head)
        while rest:
            head, rest = split(rest, TASK_LIMIT - 4, at_word=False)
            new.append("  - " + head)
        wrapped += 1
    if not (extracted or wrapped):
        return []
    plan.write_text("\n".join(new), encoding="utf-8")
    if notes:
        with (state / "PLAN_ARCHIVE.md").open("a", encoding="utf-8") as f:
            f.write(f"\n## Implementation notes moved from PLAN.md "
                    f"({datetime.date.today().isoformat()})\n\n"
                    "Appended as `<!-- … -->` to task lines: the plan carried a record of HOW\n"
                    "the work went, not just its scope, and took it into every session's prompt.\n"
                    "Text unchanged.\n\n")
            for phase, tid, note in notes:
                f.write(f"- **Phase {phase}, task {tid}**: {note}\n")
    return [f"PLAN.md: {extracted} `<!-- -->` notes → PLAN_ARCHIVE.md, "
            f"{wrapped} tasks broken into continuation lines"]


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("project")
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    project = Path(a.project).expanduser().resolve()
    state = project / "telesma" / "state"
    if not state.is_dir():
        print(f"No directory {telesma}", file=sys.stderr)
        return 2

    findings = diagnose(state)
    if not a.fix:
        for severity, msg in findings:
            print(f"{severity}\t{msg}")
        return 0

    is_git = (project / ".git").exists()
    changes = []
    if is_git:
        log, hist = versions_from_git(project)
        # Archive first: only once it carries full entries may orphans be removed from the
        # report (the condition for removal is that the text already exists somewhere).
        changes += repair_archive(state, log)
        a = state / "REPORT_ARCHIVE.md"
        changes += repair_report(state, log, hist,
                                 a.read_text(encoding="utf-8") if a.is_file() else "")
    else:
        print("⚠ This is not a git repository — entries cut in half cannot be restored. "
              "Repairing PLAN.md only.")
    changes += repair_plan(state)
    changes += restore_phases(state)
    if is_git:
        changes += move_notes(state, project)
    print("\n".join(f"  ✓ {c}" for c in changes) if changes else
          "Nothing needed changing — the state files are consistent.")
    left = [m for s, m in diagnose(state) if s == "damage"]
    if left:
        print("\nLeft for a human to decide (cannot be repaired mechanically):")
        print("\n".join(f"  • {m}" for m in left))
    return 0


if __name__ == "__main__":
    sys.exit(main())
