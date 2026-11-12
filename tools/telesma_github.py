"""The GitHub flow of section 17, done by the task tool instead of the model (change plan Z5).

With `## Integrations → Repository: github` a task is finished when its PR is merged. This module
holds what `next`, `done` and `commit` of tools/telesma-task.py need for that: reading the PRs
(`gh pr list`), the state of the required checks, merging (all three `Merge` modes), re-pointing a
chained successor before its predecessor is merged and rebasing it after, the task branch, the push
and the PR. The rules the instructions used to state — squash only, never `--admin`, merge only on
green required checks, a successor re-pointed before the merge, `--force-with-lease` only on a task
branch, never a push to main — are properties of this code.

Stdlib only, Python 3.9+. `TELESMA_GH` names the gh binary (the self-tests use a fake).
"""
import json
import os
import re
import subprocess

GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
RED = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE", "STALE"}
PR_FIELDS = "number,state,title,headRefName,baseRefName,mergeCommit,statusCheckRollup,url"


class GitHubError(Exception):
    pass


def gh_binary():
    return os.environ.get("TELESMA_GH") or "gh"


def gh(root, *args, check=True):
    try:
        r = subprocess.run([gh_binary(), *args], cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitHubError(f"gh {' '.join(args[:2])}: {e}")
    if check and r.returncode != 0:
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise GitHubError(f"git {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def list_prs(root):
    r = gh(root, "pr", "list", "--state", "all", "--limit", "100", "--json", PR_FIELDS)
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        raise GitHubError("gh pr list returned something that is not JSON")
    return {int(p["number"]): p for p in data if isinstance(p, dict) and "number" in p}


def required_checks(cfg):
    raw = cfg.field("Integrations", "Required checks")
    if not raw or raw.strip().lower() in ("none", "-"):
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def check_name(c):
    return c.get("name") or c.get("context") or ""


def check_result(c):
    """'green' | 'red' | 'pending' of one entry of statusCheckRollup (a CheckRun or a StatusContext)."""
    state = (c.get("conclusion") or c.get("state") or "").upper()
    status = (c.get("status") or "").upper()
    if c.get("__typename") == "CheckRun" or "status" in c:
        if status and status != "COMPLETED":
            return "pending"
    if state in GREEN:
        return "green"
    if state in RED:
        return "red"
    return "pending"


def checks_state(pr, required):
    """('green' | 'red' | 'pending', [names of red checks]). With required checks, every one of them
    must be present and green — an absent one is pending, never green. Without a list, any red check
    is red and anything still running is pending."""
    rollup = pr.get("statusCheckRollup") or []
    by_name = {}
    for c in rollup:
        by_name.setdefault(check_name(c), []).append(check_result(c))
    red = sorted(n for n, rs in by_name.items() if "red" in rs)
    if required:
        results = [("red" if "red" in by_name.get(n, []) else "green" if by_name.get(n) and
                    all(x == "green" for x in by_name[n]) else "pending") for n in required]
        if "red" in results:
            return "red", [n for n, r in zip(required, results) if r == "red"]
        return ("green" if all(r == "green" for r in results) else "pending"), []
    if red:
        return "red", red
    return ("pending" if any("pending" in rs for rs in by_name.values()) else "green"), []


def base_branch(root):
    r = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    name = r.stdout.strip()
    return name.split("/", 1)[1] if r.returncode == 0 and "/" in name else "main"


def current_branch(root):
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def slug(title):
    words = re.findall(r"[a-z0-9]+", title.lower().encode("ascii", "ignore").decode())
    return "-".join(words[:4]) or "task"


def branch_name(cfg, tid, title):
    prefix = cfg.field("Integrations", "Branch prefix") or "task-"
    ident = (tid or "x").replace(".", "-")
    return f"{prefix}{ident}-{slug(title)}"


def start_branch(root, name, base):
    """A new task branch off origin/<base> (main, or the predecessor's branch of a chain)."""
    if git(root, "rev-parse", "-q", "--verify", f"refs/heads/{name}", check=False).returncode == 0:
        git(root, "checkout", "-q", name)
        return
    git(root, "checkout", "-q", "-b", name, f"origin/{base}")


def sync_main(root, main):
    git(root, "checkout", "-q", main)
    git(root, "pull", "-q", "--ff-only", "origin", main)


def push(root, branch, force=False):
    if branch in ("main", "master"):
        raise GitHubError("refusing to push to the base branch")
    args = ["push", "-q", "-u", "origin", f"{branch}:{branch}"]
    if force:
        args.insert(2, "--force-with-lease")
    git(root, *args)


def open_pr(root, branch, base, title, body):
    r = gh(root, "pr", "create", "--head", branch, "--base", base, "--title", title, "--body", body)
    m = re.search(r"/pull/(\d+)", r.stdout) or re.search(r"#(\d+)", r.stdout)
    if not m:
        raise GitHubError(f"gh pr create did not name the PR: {r.stdout.strip()[:200]}")
    return int(m.group(1))


def merge(root, number, delete_branch):
    args = ["pr", "merge", str(number), "--squash"]
    if delete_branch:
        args.append("--delete-branch")
    gh(root, *args)


def enable_auto_merge(root, number):
    gh(root, "pr", "merge", str(number), "--auto", "--squash", "--delete-branch")


def repoint(root, number, base):
    gh(root, "pr", "edit", str(number), "--base", base)


def rebase_onto(root, main, old_base, branch):
    """`git rebase --onto origin/<main> <old_base> <branch>`; returns the conflicted files ([] = done)."""
    git(root, "fetch", "-q", "origin")
    cut = old_base if git(root, "rev-parse", "-q", "--verify", old_base, check=False).returncode == 0 \
        else f"origin/{old_base}"
    if git(root, "rev-parse", "-q", "--verify", f"refs/heads/{branch}", check=False).returncode != 0:
        git(root, "branch", "-q", branch, f"origin/{branch}")
    r = git(root, "rebase", "-q", "--onto", f"origin/{main}", cut, branch, check=False)
    if r.returncode == 0:
        return []
    return conflicted(root) or ["(rebase stopped: " + (r.stderr or r.stdout).strip()[:200] + ")"]


def conflicted(root):
    r = git(root, "diff", "--name-only", "--diff-filter=U", check=False)
    return [x for x in r.stdout.split("\n") if x]


def rebase_in_progress(root):
    d = git(root, "rev-parse", "--git-path", "rebase-merge").stdout.strip()
    d2 = git(root, "rev-parse", "--git-path", "rebase-apply").stdout.strip()
    full = [p if os.path.isabs(p) else os.path.join(root, p) for p in (d, d2)]
    return any(os.path.isdir(p) for p in full)


def continue_rebase(root):
    """After the model resolved the conflicts in the files: stage them and go on. Returns the files
    still conflicted ([] = the rebase finished)."""
    files = conflicted(root)
    marked = [f for f in files if "<<<<<<<" in (open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                                                if os.path.isfile(os.path.join(root, f)) else "")]
    if marked:
        return marked
    if files:
        git(root, "add", "--", *files)
    env = dict(os.environ, GIT_EDITOR="true")
    r = subprocess.run(["git", "-C", root, "rebase", "--continue"], capture_output=True, text=True, env=env)
    if r.returncode == 0 and not rebase_in_progress(root):
        return []
    return conflicted(root) or ["(rebase stopped: " + (r.stderr or r.stdout).strip()[:200] + ")"]


def task_prs(prs):
    """{task name prefix: PR} for the PRs `done` opened (title `Telesma: Task N.M: …`), newest last;
    a closed one counts only when nothing newer exists for the task."""
    out = {}
    for n in sorted(prs):
        pr = prs[n]
        title = (pr.get("title") or "").strip()
        if not title.startswith("Telesma: ") or not re.match(r"^Telesma: (Task|Test)\b", title):
            continue
        name = title[len("Telesma: "):].rstrip("…").strip()
        out[name] = pr
    return out


def pr_for(task_name, by_name):
    """The PR whose title names this task (titles are cut at 72 characters, so a prefix matches)."""
    if task_name in by_name:
        return by_name[task_name]
    hits = [pr for name, pr in by_name.items() if task_name.startswith(name) and len(name) >= 20]
    return hits[-1] if hits else None
