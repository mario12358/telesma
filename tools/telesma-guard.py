#!/usr/bin/env python3
"""PreToolUse hook: the "code only" profile (change plan Z7).

Since format 21 the task tool (tools/telesma-task.py) commits, ticks tasks and writes the report's
history; the agent writes code. This hook refuses what would route around that:

- Bash: git operations that write history or move refs (`add`, `commit`, `tag` other than a
  release version, `push`, `pull`, `merge`, `rebase`, `reset` of a ref, `cherry-pick`, `revert`,
  `am`, `update-ref`, …) and `gh` calls that change something on GitHub — with the command that
  does it instead;
- Edit / Write / MultiEdit on telesma/state/PLAN.md that ticks or unticks a task;
- Edit / Write / MultiEdit on the `Task history`, `Test status` or `Change history` sections of
  telesma/state/REPORT.md.

Session budget (change plan K2): when the task tool has marked the session as out of its budget,
everything but reads and writing telesma/state/BLOCKED.md is refused, whatever the integration.
With `--post` (PostToolUse) it counts the tool calls since the last `next` and, past a threshold,
tells the model once per step that the task is taking long — a warning, never a refusal.

It is inactive when the project's format is older than 21. With `## Integrations → Repository:
github` the task tool branches, pushes, opens and merges the PRs (section 17), so the agent has no
git or gh write left there either. A refusal is a deny with a reason; anything
it cannot read in a command that mentions a git write is refused too, never waved through.

It runs from the Telesma clone (the launcher registers it in .claude/settings.local.json with an
absolute path), reuses the command parsing of the quality checks runner, and never calls a model.
Stdlib only, Python 3.9+. Any internal error lets the call through (exit 0, no decision): the
guard keeps a careless model on the scripted path; the checks hook and CI remain the layers that
verify what was committed.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TELESMA = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import telesma_state as ts  # noqa: E402

FORMAT = 21
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")
GUARDED_REPORT = ("## Task history", "## Test status", "## Change history")
# git subcommands that write history or move refs
GIT_WRITES = {"add", "commit", "push", "pull", "merge", "rebase", "cherry-pick", "revert", "am",
              "update-ref", "commit-tree", "mktag", "symbolic-ref", "filter-branch", "filter-repo",
              "replace", "notes"}
WRAPPERS = {"env", "command", "exec", "nohup", "time", "nice", "timeout", "sudo", "doas", "xargs",
            "stdbuf", "caffeinate", "chronic"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "eval", "python", "python3", "node", "perl",
          "ruby", "deno", "bun", "pwsh", "powershell"}
GH_WRITES = {
    "pr": {"create", "merge", "close", "edit", "comment", "review", "ready", "reopen", "lock", "unlock"},
    "release": {"create", "delete", "edit", "upload", "delete-asset"},
    "repo": {"create", "delete", "edit", "fork", "rename", "archive", "unarchive", "sync", "set-default"},
    "issue": {"create", "close", "edit", "comment", "delete", "reopen", "transfer", "lock", "unlock", "pin",
              "unpin", "develop"},
    "workflow": {"run", "enable", "disable"}, "run": {"rerun", "cancel", "delete"},
    "secret": {"set", "delete", "remove"}, "variable": {"set", "delete", "remove"},
    "label": {"create", "edit", "delete", "clone"}, "gist": {"create", "edit", "delete", "clone"},
    "ruleset": {"create", "delete", "edit"}, "cache": {"delete"},
}
VERSION = re.compile(r"^v\d+\.\d+\.\d+")
CALLS_WARN, CALLS_EVERY = 150, 50
GIT_READS = {"status", "log", "diff", "show", "blame", "describe", "rev-parse", "ls-files", "grep", "branch"}


def load_checks():
    path = os.path.join(TELESMA, "templates", "checks", "telesma-checks.py")
    spec = importlib.util.spec_from_file_location("telesma_checks_for_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": "Telesma: " + reason}}))
    sys.exit(0)


def task_tool():
    path = os.path.join(HERE, "telesma-task.py")
    return f"python3 {path}" if " " not in path else f'python3 "{path}"'


def scripted(root):
    """A Telesma project on format 21 or later."""
    if not os.path.isfile(os.path.join(root, ts.CONFIG)):
        return False
    try:
        with open(os.path.join(root, "telesma", "state", ".telesma-version"), encoding="utf-8") as f:
            return int(f.read().strip() or "0") >= FORMAT
    except (OSError, ValueError):
        return False


def active(root):
    return scripted(root)


def session_file(root):
    r = subprocess.run(["git", "-C", root, "rev-parse", "--git-path", "telesma-task"], capture_output=True, text=True)
    d = r.stdout.strip()
    if r.returncode != 0 or not d:
        return None
    return os.path.join(d if os.path.isabs(d) else os.path.join(root, d), "session.json")


def load_session(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def exhausted_check(root, tool, tool_input, checks):
    """Out of budget: reads and BLOCKED.md only."""
    data = load_session(session_file(root))
    ex = data.get("exhausted")
    if not ex:
        return
    why = (f"the session budget is used up ({ex.get('reason')}) — report TELESMA BLOCKED and stop; the next start "
           "of the launcher asks the person whether to go on. Only reads and telesma/state/BLOCKED.md now.")
    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or ""
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
        if os.path.relpath(full, os.path.realpath(root)).replace(os.sep, "/") != ts.BLOCKED:
            deny(why)
        return
    members = checks.command_members(tool_input.get("command") or "")
    if members is None:
        deny(why)
    for m in members:
        t = unwrap(m)
        if not t:
            continue
        if os.path.basename(t[0]) == "git":
            pk = checks.git_subcommand(t)
            if pk and pk[0] in GIT_READS and not any(">" in x for x in t):
                continue
            deny(why)
        if len(t) > 1 and t[1].endswith("telesma-task.py"):
            continue
        if not checks.read_only(t):
            deny(why)


# --- Bash -----------------------------------------------------------------------------------

def unwrap(tokens):
    """The member's command after wrappers (`env A=1`, `timeout 60`, `nice -n 5`, `xargs`)."""
    i = 0
    while i < len(tokens):
        t = os.path.basename(tokens[i])
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
            i += 1
        elif t in WRAPPERS:
            i += 1
            while i < len(tokens) and (tokens[i].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", tokens[i])):
                i += 1
        else:
            break
    return tokens[i:]


def git_refusal(sub, args):
    tool = task_tool()
    if sub in ("add", "commit"):
        return (f"`git {sub}` is done by the task tool — finish the task with `{tool} done`, or commit other "
                f"work with `{tool} commit --kind <kind> -m \"…\"` (section 4). It commits exactly what git "
                "status shows, minus `Ignore on commit`.")
    if sub == "tag":
        listing = not args or any(a in ("-l", "--list", "--contains", "--no-contains", "--merged", "--no-merged",
                                        "--points-at", "-n", "--sort", "--column") or a.startswith(("--sort=", "-n"))
                                  for a in args)
        names = [a for a in args if not a.startswith("-")]
        release = ("-a" in args or "--annotate" in args) and names and VERSION.match(names[0]) \
            and not any(a in ("-f", "--force", "-d", "--delete") for a in args)
        if listing and not any(a in ("-a", "-s", "-f", "-d", "--delete", "--force") for a in args):
            return None
        if release:
            return (f"a release version is created with `{tool} release vX.Y.Z -m \"…\"` — it checks the "
                    "conditions of section 15.5 and asks the person.")
        return (f"phase tags are placed by `{tool} suite`, a release version by `{tool} release` — "
                "no other tag, no -f, no delete.")
    if sub == "reset":
        if "--" in args or not [a for a in args if a not in ("-q", "--quiet")]:
            return None          # unstaging paths
        return ("`git reset` of a ref rewrites history — unstage a file with `git restore --staged <file>`, "
                "discard a change with `git restore <file>`.")
    if sub == "branch" and any(a in ("-f", "--force", "-D", "-M", "-C", "-m", "-c", "-d", "--delete", "--move")
                               for a in args):
        return "branches are not moved, renamed or deleted in this project's loop."
    if sub == "push":
        return (f"the agent never pushes. With `Repository: github`, `{tool} done` pushes the task branch and "
                "opens its PR (section 17); without it, pushing is the person's — they type `! git push` "
                "themselves.")
    if sub == "pull":
        return "a pull merges or rebases — ask the person to update the branch, or report TELESMA BLOCKED."
    if sub == "revert":
        return (f"undo a change by editing the files back, then `{tool} commit --kind <kind> -m \"revert …\"` — "
                "the checks see what is committed.")
    if sub in GIT_WRITES:
        return f"`git {sub}` writes history; the task tool commits (`{tool} done` / `commit --kind`)."
    return None


def release_question(cmd, checks, mode):
    """`telesma-task.py release …` always reaches the person: an `ask` even where an allow rule or
    the permission mode would let it through, and a refusal where a question reaches nobody."""
    members = checks.command_members(cmd) or []
    for m in members:
        t = unwrap(m)
        if len(t) > 2 and t[1].endswith("telesma-task.py") and "release" in t[2:3]:
            tag = t[3] if len(t) > 3 else "?"
            if mode in ("bypassPermissions", "dontAsk"):
                deny(f"a release version ({tag}) needs the person's answer, and in `{mode}` nobody is asked — "
                     "propose it in a 📦 RELEASE PROPOSAL and stop; the person creates it in an interactive session.")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                     "permissionDecisionReason": f"Telesma: create the release version "
                                                     f"{tag}? (annotated tag, not pushed — section 15)"}}))
            sys.exit(0)
    if re.search(r"telesma-task\.py[^\n]*\brelease\b", cmd) and not members:
        deny("a release command that cannot be read — run it on its own.")


def check_bash(root, cmd, checks):
    members = checks.command_members(cmd)
    creating = checks.GIT_CREATING.search(cmd) or re.search(r"(?<![\w.-])git(?![\w.-])[^\n]*?(?<![\w-])"
                                                            r"(?:add|push|reset|update-ref)(?![\w-])", cmd)
    if members is None:
        if creating:
            deny("this command mentions a git write in a form that cannot be read (unbalanced quotes?) — "
                 f"commits go through `{task_tool()} done`.")
        return
    if creating and checks.live_substitution(cmd):
        # `$(git commit …)`, backticks: what the shell runs while expanding is not a member we see
        if re.search(r"(\$\(|`)[^)`]*(?<![\w.-])git(?![\w.-])", cmd):
            deny(f"a git write inside a substitution — commits go through `{task_tool()} done`.")
    aliases = checks.git_aliases(root)
    for member in members:
        tokens = unwrap(member)
        if not tokens:
            continue
        head = os.path.basename(tokens[0])
        if head == "git":
            if checks.inline_alias(tokens):
                deny("a git alias defined in the command — commits go through the task tool.")
            pk = checks.subcommand(tokens, aliases)
            if not pk:
                continue
            sub, args, _ = pk
            if sub == "!shell":
                deny("a git alias that runs a shell command and mentions a git write — commits go through the task tool.")
            why = git_refusal(sub, args)
            if why:
                deny(why)
        elif head == "gh":
            sub = tokens[1] if len(tokens) > 1 else ""
            act = tokens[2] if len(tokens) > 2 else ""
            if sub == "api":
                rest = tokens[2:]
                method = next((rest[i + 1] for i, t in enumerate(rest[:-1]) if t in ("-X", "--method")), None) \
                    or next((t.split("=", 1)[1] for t in rest if t.startswith("--method=")), None)
                writes = (method and method.upper() != "GET") or any(
                    t in ("-f", "-F", "--field", "--raw-field", "--input") or t.startswith(("--field=", "--raw-field=",
                                                                                          "--input=")) for t in rest)
                if writes:
                    deny("`gh api` that changes something on GitHub — the task tool does the GitHub side (section 17).")
            elif act in GH_WRITES.get(sub, ()):
                deny(f"`gh {sub} {act}` changes something on GitHub — PRs are opened, merged and re-pointed by the "
                     f"task tool (`{task_tool()} next` / `done`, section 17).")
        elif head in SHELLS:
            # only the code given inline: a script path (the task tool's own, say under ~/git/) is
            # not a git command
            code = " ".join(tokens[1:]) if head == "eval" else " ".join(
                tokens[i + 1] for i, t in enumerate(tokens[:-1])
                if t in ("-c", "-e", "--eval", "-Command", "-p", "--print") or re.fullmatch(r"-[a-zA-Z]*c", t))
            if code and checks.GIT_CREATING.search(code):
                deny(f"a git write inside `{head}` cannot be read — commits go through `{task_tool()} done`.")


# --- state files ----------------------------------------------------------------------------

def section(text, header):
    lines = (text or "").split("\n")
    start = next((i for i, l in enumerate(lines) if l.rstrip() == header), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return "\n".join(l.rstrip() for l in lines[start:end]).strip()


def check_edit(root, tool, tool_input, checks):
    path = tool_input.get("file_path") or ""
    if not path:
        return
    full = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    rel = os.path.relpath(full, os.path.realpath(root)).replace(os.sep, "/")
    if rel not in (ts.PLAN, ts.REPORT):
        return
    before = ts.read_text(full)
    if before is None:
        return                          # a new file: nothing to compare with
    after = checks.content_after(before, tool, tool_input)
    if after is None:
        return                          # the edit does not apply; it fails on its own
    if rel == ts.PLAN:
        old, new = ts.Plan(before), ts.Plan(after)
        flipped = [t for t, o in old.tasks.items() if t in new.tasks and not o.get("archived")
                   and o["done"] != new.tasks[t]["done"]]
        done_old = sum(1 for o in old.order if o["done"])
        done_new = sum(1 for o in new.order if o["done"])
        if flipped or done_new != done_old:
            deny(f"a task is ticked by `{task_tool()} done` only, and never unticked (rework goes into a `.Z` "
                 "phase, section 0.3)" + (f" — this edit flips {', '.join(flipped)}" if flipped else "")
                 + ". Edit the task's text, not its checkbox.")
        return
    changed = [h[3:] for h in GUARDED_REPORT if section(before, h) != section(after, h)]
    if changed:
        deny(f"`{', '.join(changed)}` in REPORT.md is written by the task tool (done, suite, changes-done) — "
             "write your notes into `## Problem log`, decisions into PROJECT_CONTEXT.md.")


def count_call(root):
    """PostToolUse: one more tool call on the task in progress; past the threshold one line for the
    model. The counter is reset by `next`."""
    path = session_file(root)
    data = load_session(path)
    if not path or not data.get("task"):
        return 0
    n = int(data.get("calls_since_next", 0)) + 1
    data["calls_since_next"] = n
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".session-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    if n >= CALLS_WARN and (n - CALLS_WARN) % CALLS_EVERY == 0:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
            f"Telesma: {n} tool calls on {data.get('name', 'this task')} since `next`. Finish it with `done`, "
            "or, if it is stuck, write telesma/state/BLOCKED.md and report TELESMA BLOCKED (section 5).")}}))
    return 0


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        if not isinstance(data, dict):
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        if not scripted(root):
            return 0
        tool = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        if "--post" in sys.argv[1:]:
            return count_call(root)
        if tool == "Bash" or tool in EDIT_TOOLS:
            exhausted_check(root, tool, tool_input, load_checks())
        if tool == "Bash" and "release" in (tool_input.get("command") or ""):
            release_question(tool_input.get("command") or "", load_checks(), data.get("permission_mode"))
        if not active(root):
            return 0
        if tool == "Bash":
            check_bash(root, tool_input.get("command") or "", load_checks())
        elif tool in EDIT_TOOLS:
            check_edit(root, tool, tool_input, load_checks())
    except SystemExit:
        raise
    except Exception:                    # noqa: BLE001 — see the docstring: no decision on an internal error
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
