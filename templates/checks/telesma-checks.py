#!/usr/bin/env python3
"""
Telesma — quality checks. Runner of the modules in `telesma/checks/<name>/`.

A check is a verification that does not depend on the model remembering to run it:
it fires on its own at a TRIGGER POINT — a git operation Telesma performs anyway.

  commit   before `git commit`                (PreToolUse hook)
  phase    before `git tag telesma/phase-*`     (PreToolUse hook)
  release  before `git tag … vX.Y.Z`          (PreToolUse hook)
  ci       in the PR/MR pipeline              (by hand: --point ci)

A check with severity `block` stops the operation (deny — Claude sees the reason),
`warn` only goes to the log. Unlike the permission judge, this hook DELIBERATELY
adds blocks — which is why it is a separate module with its own switch
(`## Checks` → `Enabled: yes`).

Check module (`telesma/checks/<name>/`):
  CHECK.md     frontmatter: kind, run, check, when, scope, on_failure
  run.py       reads the list of files from stdin (one relative path per line),
               variables TELESMA_POINT / TELESMA_ROOT (and TELESMA_SINCE with `--since`);
               prints findings as JSON lines:
               {file, line, rule, message, severity?, content_fingerprint?, file_fingerprint?}.
               Exit 0 = checked (findings may exist), 3 = tool missing.
               It NEVER prints a secret's content — only its fingerprint.
               With `--check` it prints one line about its readiness; a line starting with
               `warning:` becomes a validator warning.

A finding the human considers "not applicable" goes into `telesma/state/CHECK_EXCEPTIONS.md`
(a line with the fingerprint in backticks). Writes to that file, to the check modules and to
the `## Checks` section of the config always ask the human — the author of the code does not
close the findings that block it.

Evidence and PR status (`PR status: yes`, repository integration):
  The PreToolUse hook saves the result of the `commit`-point checks as pending evidence;
  the PostToolUse hook, after a successful `git commit`, assigns it to the new commit's SHA
  (`.git/telesma-checks/<sha>.json` — this machine's data, nothing to commit), and after a
  successful `git push` to a task branch it collects the evidence of the `origin/main..HEAD`
  commits and posts the commit status "Telesma: checks (local)" on the branch tip via
  `gh api`. A commit without evidence (made outside the hook) = red status: missing
  evidence is not green. This is an attestation from this machine, not verification —
  hence "local" in the name. After a rebase the SHA changes; the evidence is found by
  `git patch-id`, because the content of the change stayed the same.

What the hook cannot see beforehand, it checks afterwards: a commit made in a form it could not
read (a script, a subshell, a merge, a cherry-pick) or an amend gets the commit-point checks run
on its CONTENT in PostToolUse; findings come back as blocking context and the evidence says so.
An internal error of the hook stops a commit / tag instead of letting it through.

Integrity: hashes of the check modules, the exceptions file and the `## Checks` section are kept
in `.git/telesma-checks/baseline.json`. A difference that did not come through an edit the human
was asked about stops the next commit / tag until the human approves it (`--approve`).

Modes:
  --pretooluse            hook: JSON on stdin; Bash → points from the git command,
                          Edit/Write → protection of the check files
  --posttooluse           hook: after `git commit` evidence → SHA, unseen commits verified,
                          after `git push` PR status; after an approved Edit/Write the baseline follows
  --point P [--since REF] by hand / in CI; exit code 1 when something blocks
  --files-commit          tools/telesma-task.py (`done`, `commit`): the commit-point checks on exactly
                          the files named on stdin (NUL-separated), integrity first; the result waits
                          as pending evidence; exit code 1 when something blocks
  --record-commit         tools/telesma-task.py, right after its commit: pending evidence → the new SHA,
                          and HEAD is marked as seen (the commit was checked before it was made)
  --validate [DIR]        E:/W: lines for the config validator in telesma.sh
  --baseline [DIR] [--templates DIR] [--config-section]
                          launcher, at start: create the integrity baseline when missing; record
                          module files identical to the delivered templates; with --config-section
                          (right after the launcher's own wizard wrote it) also the ## Checks section
  --approve [DIR]         the human, in a terminal: approve the current state of the check files
"""
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='backslashreplace')
    except (AttributeError, ValueError):
        pass

POINTS = ('commit', 'phase', 'release', 'ci')
DIRECTORY = 'telesma/checks'
EXCEPTIONS = 'telesma/state/CHECK_EXCEPTIONS.md'
LOG = 'telesma/state/CHECKS.jsonl'
CONFIG = 'telesma/config.md'
PHASE_TAG = 'telesma/phase-'
# Files whose scanning yields nothing but costs: lockfiles and minified bundles.
SKIPPED = re.compile(r'(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|'
                     r'Cargo\.lock|go\.sum|deno\.lock|composer\.lock|Gemfile\.lock)$|\.min\.(js|css)$')
DEFAULT_LIMIT = {'commit': 20, 'phase': 300, 'release': 300, 'ci': 600}
MAX_BYTES = 1_000_000
STATUS_CONTEXT = 'Telesma: checks (local)'
EVIDENCE = 'telesma-checks'          # directory in .git/ (git rev-parse --git-path)
PENDING = 'pending.json'
MAX_STATUS_DESCRIPTION = 140       # GitHub's limit for a status description
YES = ('yes', 'true')
BASELINE = 'baseline.json'         # integrity baseline of the check files (in .git/telesma-checks/)
APPROVALS = 'approvals.json'       # edits the human was asked about, waiting for PostToolUse
SEEN_HEAD = 'seen-head'            # HEAD at the previous PostToolUse — what moved since then is verified
POST_BUDGET = 270                  # seconds for verifying commits after the fact (hook limit: 300)
MAX_VERIFIED = 10                  # commits verified after the fact in one go
# Overrides of service addresses, the cache directory and the gh binary exist for the self-tests.
# They are honoured only together with this flag: a variable alone must not move a check elsewhere.
TEST_FLAG = 'TELESMA_CHECKS_TEST'


def test_mode():
    return os.environ.get(TEST_FLAG) == '1'


class GitError(Exception):
    """git did not answer where the answer decides what gets checked — an unknown scope is not an
    empty scope, so the operation is refused instead of passing unchecked."""


def read_text(path):
    """File content, or None. Undecodable bytes are replaced: one stray byte in config.md must not
    switch the checks off."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


# --- Configuration ----------------------------------------------------------------

def strip_comments(t):
    return re.sub(r'<!--.*?-->', '', t, flags=re.S)


def load_config(root):
    """{'enabled': bool, 'checks': {name: {field: value}}} — the ## Checks section."""
    text = read_text(os.path.join(root, CONFIG))
    if text is None:
        return {'enabled': False, 'checks': {}}
    m = re.search(r'^## Checks[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not m:
        return {'enabled': False, 'checks': {}}
    section = strip_comments(m.group(1))
    head, *rest = re.split(r'^### ', section, flags=re.M)

    def fields(block):
        return {k.strip(): v.strip() for k, v in
                re.findall(r'^- \*\*(.+?)\*\*:[ \t]*(.*?)[ \t]*$', block, re.M)}

    checks = {}
    for block in rest:
        name, _, body = block.partition('\n')
        name = name.strip().strip('`')
        if name:
            checks[name] = fields(body)
    enabled = fields(head).get('Enabled', 'no').lower() in YES
    return {'enabled': enabled, 'checks': checks}


def section_fields(root, section):
    """{field: value} from the config's `## <section>` (without comments); {} when missing."""
    text = read_text(os.path.join(root, CONFIG))
    if text is None:
        return {}
    m = re.search(r'^## ' + re.escape(section) + r'[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not m:
        return {}
    block = strip_comments(m.group(1)).split('\n### ')[0]
    return {k.strip(): v.strip() for k, v in
            re.findall(r'^- \*\*(.+?)\*\*:[ \t]*(.*?)[ \t]*$', block, re.M)}


def pr_status_enabled(root):
    """Whether to post the commit status: the `PR status` field (default yes) and a repository
    integration (`## Integrations` → `Repository` ≠ none)."""
    k = section_fields(root, 'Checks')
    if k.get('PR status', 'yes').lower() not in YES:
        return False
    return section_fields(root, 'Integrations').get('Repository', 'none').lower() not in ('', 'none')


def load_module(root, name):
    """CHECK.md frontmatter, or None when the module does not exist."""
    path = os.path.join(root, DIRECTORY, name, 'CHECK.md')
    text = read_text(path)
    if text is None:
        return None
    m = re.match(r'^---\n(.*?)\n---', text, re.S)
    meta = {}
    for line in (m.group(1) if m else '').splitlines():
        k, sep, v = line.partition(':')
        if sep:
            meta[k.strip()] = v.strip()
    meta['dir'] = os.path.dirname(path)
    return meta


def value_list(s):
    return [x.strip().lower() for x in re.split(r'[,\s]+', s or '') if x.strip()]


def settings(root, name, cfg_fields):
    """Fields from the config override the module's defaults."""
    module = load_module(root, name)
    if module is None:
        return None
    when = value_list(cfg_fields.get('When') or module.get('when'))
    on_failure = (cfg_fields.get('On failure') or module.get('on_failure') or 'block').lower()
    scope = (cfg_fields.get('Scope') or module.get('scope') or 'changed').lower()
    limit = cfg_fields.get('Time limit') or ''
    lm = re.match(r'^(\d+)\s*(s|sec|min)?', limit)
    sec = (int(lm.group(1)) * (60 if lm.group(2) == 'min' else 1)) if lm else None
    return {'name': name, 'module': module, 'when': when, 'on_failure': on_failure,
            'scope': scope, 'limit': sec}


# --- Validate ----------------------------------------------------------------------

def validate(root):
    cfg = load_config(root)
    if not cfg['enabled']:
        return []
    out = []
    if not cfg['checks']:
        out.append('W:## Checks: Enabled: yes, but no check (### <name>) — nothing will run')
    k = section_fields(root, 'Checks')
    sp = k.get('PR status', 'yes').lower()
    if sp not in ('yes', 'no', 'true', 'false'):
        out.append(f'E:## Checks → PR status = {sp} — allowed: yes, no')
    elif pr_status_enabled(root):
        integ = section_fields(root, 'Integrations')
        if not gh_available():
            out.append('W:## Checks → PR status: yes, but there is no `gh` in PATH — the status will not be posted')
        if STATUS_CONTEXT not in (integ.get('Required checks') or ''):
            out.append(f'W:## Integrations → Required checks: "{STATUS_CONTEXT}" is missing — the judge will merge '
                       f'a PR without check evidence; add this name (the wizard does it on its own)')
    if evidence_dir(root):
        for x in integrity_drift(root):
            out.append(f'W:## Checks: differs from the approved state: {x} — commits and tags stop until you '
                       f'approve it in a terminal: python3 {DIRECTORY}/telesma-checks.py --approve')
    for name, cfg_fields in cfg['checks'].items():
        u = settings(root, name, cfg_fields)
        if u is None:
            available = sorted(d for d in os.listdir(os.path.join(root, DIRECTORY))
                               if os.path.isfile(os.path.join(root, DIRECTORY, d, 'CHECK.md'))) \
                if os.path.isdir(os.path.join(root, DIRECTORY)) else []
            out.append(f'E:## Checks → {name}: there is no module {DIRECTORY}/{name}/ '
                       f'(available: {", ".join(available) or "none"})')
            continue
        bad = [k for k in u['when'] if k not in POINTS]
        if bad:
            out.append(f'E:## Checks → {name}: When = {", ".join(bad)} — allowed: {", ".join(POINTS)}')
        if not u['when']:
            out.append(f'W:## Checks → {name}: empty "When" — the check will never run')
        if u['on_failure'] not in ('block', 'warn'):
            out.append(f'E:## Checks → {name}: On failure = {u["on_failure"]} — allowed: block, warn')
        if u['scope'] not in ('changed', 'all'):
            out.append(f'E:## Checks → {name}: Scope = {u["scope"]} — allowed: changed, all')
        if u['module'].get('kind') == 'agent' and 'commit' in u['when']:
            out.append(f'E:## Checks → {name}: a check of kind agent cannot run at commit '
                       f'(minutes and tokens on every commit) — use phase / release')
        check = u['module'].get('check')
        if check:
            try:
                r = subprocess.run(shlex.split(check), cwd=u['module']['dir'],
                                   capture_output=True, text=True, timeout=15)
                info = (r.stdout.strip() or r.stderr.strip()).splitlines()[:1]
                info = info[0] if info else ''
                if r.returncode == 3:
                    out.append(f'E:## Checks → {name}: {info or "required tool missing"}')
                elif r.returncode != 0:
                    out.append(f'E:## Checks → {name}: the module self-check failed ({info or r.returncode})')
                elif info.startswith('warning:'):
                    out.append(f'W:## Checks → {name}: {info[8:].strip()}')
            except (OSError, subprocess.TimeoutExpired) as e:
                out.append(f'E:## Checks → {name}: cannot run the module self-check ({e})')
    return out


# --- Git ------------------------------------------------------------------------------

def git(root, *args):
    try:
        r = subprocess.run(['git', '-C', root, '-c', 'core.quotepath=off', *args], capture_output=True,
                           encoding='utf-8', errors='replace', timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def git_z(root, *args):
    """Paths from a NUL-separated listing (the caller passes `-z`). Names are taken as git stores
    them — no quoting, so a non-ASCII name or one with a quote is a path like any other.
    Raises GitError when git fails."""
    try:
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f'git {args[0]}: {type(e).__name__}')
    if r.returncode != 0:
        raise GitError(f'git {args[0]} exited with {r.returncode}')
    return [p for p in r.stdout.decode('utf-8', 'surrogateescape').split('\0') if p]


# A path the line protocol of the modules (one path per line on stdin) cannot carry: a line break
# of any kind, a control character, whitespace at either end, bytes that are not UTF-8.
UNSAFE_PATH = re.compile(r'[\x00-\x1f\x7f\x85\u2028\u2029]|^\s|\s$')


def unsafe_path(p):
    if UNSAFE_PATH.search(p):
        return True
    try:
        p.encode('utf-8')
    except UnicodeEncodeError:
        return True
    return False


def lines(s):
    return [x for x in (s or '').splitlines() if x.strip()]


def sha(root, ref):
    r = git(root, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
    return r.strip() if r else ''


def gh_binary():
    return (os.environ.get('TELESMA_GH') if test_mode() else None) or 'gh'


def gh_available():
    return bool(shutil.which(gh_binary()) or os.path.isfile(gh_binary()))


# --- Evidence per commit ---------------------------------------------------------------

def evidence_dir(root):
    p = git(root, 'rev-parse', '--git-path', EVIDENCE)
    if not p:
        return None
    p = p.strip()
    if not os.path.isabs(p):
        p = os.path.join(root, p)
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        return None
    return p


def save_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def checks_summary(root, point, log, errors):
    """What stays in the evidence from a run: per check the worst decision and the counts,
    without the content of findings (evidence goes into the status description, not the log)."""
    cfg = load_config(root)
    configured = [n for n, p in cfg['checks'].items()
                  if (u := settings(root, n, p)) and point in u['when']]
    rank = {'clean': 0, 'warn': 1, 'error': 2, 'block': 3}
    checks = {}
    for w in log:
        k = checks.setdefault(w['check'], {'decision': 'clean', 'warnings': 0, 'exceptions': 0})
        d = w.get('decision')
        if d == 'exception':
            k['exceptions'] += 1
            continue
        if d == 'warn':
            k['warnings'] += 1
        elif d == 'block':
            k['blocks'] = k.get('blocks', 0) + 1
        elif d == 'error':
            k['message'] = w.get('message', '')
        if rank.get(d, 0) > rank[k['decision']]:
            k['decision'] = d
    for n in configured:
        checks.setdefault(n, {'decision': 'error', 'warnings': 0, 'exceptions': 0, 'message': 'not run'})
    return {'point': point, 'checks': checks, 'configured': configured}


def blob_hashes(root, files):
    """{path: blob id} of the files as they stand in the working tree — what the checks read. The
    evidence is later given only to a commit that holds exactly these blobs."""
    present = [p for p in files if os.path.isfile(os.path.join(root, p))]
    if not present:
        return {}
    try:
        r = subprocess.run(['git', '-C', root, 'hash-object', '--stdin-paths'], cwd=root,
                           input='\n'.join(present) + '\n', capture_output=True, encoding='utf-8',
                           errors='surrogateescape', timeout=60)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return {}
    ids = r.stdout.split()
    return dict(zip(present, ids)) if r.returncode == 0 and len(ids) == len(present) else {}


def commit_parents(root, commit):
    r = git(root, 'rev-list', '--parents', '-n', '1', commit)
    return r.split()[1:] if r else []


def commit_blobs(root, commit):
    """{path: blob id} of what the commit adds or changes against its parent (nothing for a
    deletion); None for a merge or when git does not answer."""
    if len(commit_parents(root, commit)) > 1:
        return None
    try:
        raw = git_z(root, 'diff-tree', '-r', '-z', '--no-renames', '--root', '--no-commit-id', commit)
    except GitError:
        return None
    out = {}
    for i in range(0, len(raw) - 1, 2):
        meta = raw[i].split()
        if len(meta) >= 5 and meta[4][:1] != 'D':
            out[raw[i + 1]] = meta[3]
    return out


def save_pending(root, log, errors, files):
    """PreToolUse before a commit: the check result waits for the SHA that is about to exist,
    together with the blob ids of the files the checks read."""
    d = evidence_dir(root)
    if not d:
        return
    head = sha(root, 'HEAD')
    data = checks_summary(root, 'commit', log, errors)
    data.update({'head': head, 'parent': sha(root, 'HEAD~1') if head else '',
                 'files': blob_hashes(root, files),
                 'ts': datetime.datetime.now().isoformat(timespec='seconds')})
    save_json(os.path.join(d, PENDING), data)


def drop_pending(root):
    d = evidence_dir(root)
    if d:
        try:
            os.remove(os.path.join(d, PENDING))
        except OSError:
            pass


def patch_id(root, commit):
    try:
        a = subprocess.run(['git', '-C', root, 'diff-tree', '-p', '--no-commit-id', '--root', commit],
                           capture_output=True, text=True, timeout=30)
        b = subprocess.run(['git', '-C', root, 'patch-id', '--stable'], input=a.stdout,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return ''
    return b.stdout.split()[0] if b.stdout.split() else ''


def evidence_after_commit(root, cmd):
    """PostToolUse after `git commit`: pending evidence → file <sha>.json — only when the new
    commit holds exactly the blobs the checks read. Anything else in it (an amend carries the
    whole earlier commit, a pathspec commit, a file changed in between) was not seen by the
    checks; such a commit gets its evidence from `verify_unseen`, which checks its content."""
    d = evidence_dir(root)
    if not d:
        return None
    pending = load_json(os.path.join(d, PENDING))
    if not pending:
        return None
    new = sha(root, 'HEAD')
    if not new or new == pending.get('head'):
        return None                      # the commit did not happen — the evidence keeps waiting
    drop_pending(root)                   # HEAD moved: this result belongs to this moment or to nothing
    parents = commit_parents(root, new)
    if len(parents) > 1:
        return None
    parent = parents[0] if parents else ''
    amend = bool(re.search(r'--amend\b', cmd))
    if not (parent == (pending.get('head') or '') or (amend and parent == (pending.get('parent') or ''))):
        return None                      # HEAD changed some other way (checkout, pull) — not this commit
    blobs = commit_blobs(root, new)
    read = pending.get('files') or {}
    if blobs is None or any(read.get(p) != h for p, h in blobs.items()):
        return None
    evidence = {'sha': new, 'parent': parent, 'patch_id': patch_id(root, new), 'ts': pending.get('ts'),
                'checks': pending.get('checks', {}), 'configured': pending.get('configured', [])}
    save_json(os.path.join(d, new + '.json'), evidence)
    return evidence


def commit_evidence(root, d, commit):
    """Evidence by SHA, and when there is none — by patch-id (rebase/squash changes the SHA, not the content)."""
    e = load_json(os.path.join(d, commit + '.json'))
    if e:
        return e
    pid = patch_id(root, commit)
    if not pid:
        return None
    for name in os.listdir(d):
        if not re.match(r'^[0-9a-f]{40,64}\.json$', name):
            continue
        e = load_json(os.path.join(d, name))
        if e and e.get('patch_id') == pid:
            e = dict(e, sha=commit, rewritten_from=e.get('sha'))
            save_json(os.path.join(d, commit + '.json'), e)
            return e
    return None


# --- Commits the hook did not see beforehand -------------------------------------------------

# Reflog subjects of operations that create commits. A checkout or a reset moves HEAD without
# creating anything — verifying every commit of a branch just switched to would be noise.
CREATES_COMMITS = ('commit', 'merge', 'cherry-pick', 'revert', 'rebase', 'am', 'pull')


def snapshot_check(root, commit, limit):
    """Runs the commit-point checks on the CONTENT of a commit: a temporary worktree at the
    commit, HEAD moved back to its first parent — the state "about to be committed", read from
    git objects, not from the working tree. Returns (evidence, blocking entries)."""
    parents = commit_parents(root, commit)
    tmp = tempfile.mkdtemp(prefix='telesma-verify-')
    wt = os.path.join(tmp, 'w')

    def g(*args, cwd=root):
        return subprocess.run(['git', '-C', cwd, *args], capture_output=True, timeout=120)
    try:
        if g('worktree', 'add', '--detach', '--quiet', wt, commit).returncode != 0:
            raise GitError('git worktree add failed')
        moved = g('reset', '--soft', parents[0], cwd=wt) if parents \
            else g('checkout', '--quiet', '--orphan', 'telesma-verify-' + commit[:12], cwd=wt)
        if moved.returncode != 0:
            raise GitError('cannot move the verification worktree to the parent')
        files = None
        if len(parents) > 1:
            # a merge: only what differs from EVERY parent (conflict resolutions, changes made in
            # the merge itself) — the rest was checked in the commits being merged
            files = [p for p in git_z(root, 'diff-tree', '-r', '-z', '-c', '--name-only', '--no-commit-id', commit)
                     if os.path.isfile(os.path.join(wt, p))]
        b, w, e, lg = run_point(root, 'commit', commit_plan={}, files_root=wt, files=files, budget=limit)
    finally:
        g('worktree', 'remove', '--force', wt)
        shutil.rmtree(tmp, ignore_errors=True)
        g('worktree', 'prune')
    summary = checks_summary(root, 'commit', lg, e)
    evidence = {'sha': commit, 'parent': parents[0] if parents else '', 'patch_id': patch_id(root, commit),
                'ts': datetime.datetime.now().isoformat(timespec='seconds'), 'verified': 'after the commit',
                'checks': summary['checks'], 'configured': summary['configured']}
    return evidence, b


def verify_unseen(root):
    """PostToolUse after any Bash command: commits that appeared since the previous command and
    have no evidence (made in a form the hook could not read: a script, a subshell, a merge, a
    cherry-pick, an amend) get their content checked now. Returns text for Claude when something
    blocks or could not be verified, else None. A commit that stays unverified stays without
    evidence — and missing evidence is red."""
    d = evidence_dir(root)
    head = sha(root, 'HEAD')
    if not d or not head:
        return None
    path = os.path.join(d, SEEN_HEAD)
    seen = (read_text(path) or '').strip()

    def remember():
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(head + '\n')
        except OSError:
            pass
    if not seen or seen == head:
        if not seen:
            remember()
        return None
    subject = (git(root, 'reflog', '-1', '--format=%gs', 'HEAD') or '').strip()
    if not subject.startswith(CREATES_COMMITS):
        remember()
        return None
    listing = git(root, 'rev-list', '--reverse', head, '--not', seen, '--remotes') if sha(root, seen) else head
    commits, carried = [], []
    for c in lines(listing):
        e = commit_evidence(root, d, c)
        if not e:
            commits.append(c)
        elif any(k.get('decision') == 'block' for k in (e.get('checks') or {}).values()):
            carried.append(c)             # the same change under a new SHA (amend without a fix, rebase)
    start = datetime.datetime.now()
    blocking, unverified = [], []
    for c in commits:
        left = POST_BUDGET - (datetime.datetime.now() - start).total_seconds()
        if commits.index(c) >= MAX_VERIFIED or left < 20:
            unverified.append(c)
            continue
        try:
            evidence, b = snapshot_check(root, c, left)
        except (GitError, OSError, subprocess.TimeoutExpired):
            unverified.append(c)
            continue
        save_json(os.path.join(d, c + '.json'), evidence)
        if b:
            blocking.append((c, b))
    remember()
    if not blocking and not unverified and not carried:
        return None
    text = 'Telesma - quality checks, after the fact:'
    if carried:
        text += (f'\ncommit(s) {", ".join(c[:7] for c in carried[:5])} still carry the blocking findings of the '
                 f'change they were made from - a new SHA does not clear them ({LOG} has the list).')
    for c, b in blocking:
        text += (f'\ncommit {c[:7]} was not checked before it was made (a command shape the hook cannot read, '
                 f'an amend, a merge, another tool). Its content was checked now - {len(b)} blocking:\n'
                 + describe(b))
    if blocking or carried:
        text += ('\nThe commit already exists and its status is red. Fix the cause and amend it with a plain '
                 '`git commit --amend --no-edit` (the amended commit is checked again as a whole). A secret that '
                 'reached a commit has to be revoked - tell the human. If a finding is wrong: TELESMA BLOCKED '
                 f'with the fingerprint - the human writes the exception into {EXCEPTIONS}.')
    if unverified:
        text += (f'\n{len(unverified)} commit(s) could not be verified here ({", ".join(c[:7] for c in unverified[:5])}) '
                 f'- they have no check evidence and the PR status stays red. Run '
                 f'`python3 {DIRECTORY}/telesma-checks.py --point ci --since {seen[:12]}` and tell the human.')
    return text


# --- PR status ---------------------------------------------------------------------------

def branch_from_push(cmd):
    """Branch name from the `git push …` member of the command, or '' (push without arguments);
    None when the command does not push."""
    members = command_members(cmd) or []
    for tokens in members:
        pk = git_subcommand(tokens)
        if not pk or pk[0] != 'push':
            continue
        args = [a for a in pk[1] if not a.startswith('-')]
        if len(args) >= 2:
            return args[1].split(':')[-1].replace('refs/heads/', '')
        return ''
    if re.search(r'\bgit\b[^;&|\n]*\bpush\b', cmd):
        return ''
    return None


def github_repo(root):
    r = section_fields(root, 'Integrations').get('Repo', '')
    if re.match(r'^[\w.-]+/[\w.-]+$', r):
        return r
    url = (git(root, 'remote', 'get-url', 'origin') or '').strip()
    m = re.search(r'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$', url)
    return m.group(1) if m else ''


def base_branch(root):
    for ref in ('origin/main', 'origin/master'):
        if sha(root, ref):
            return ref
    h = (git(root, 'symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD') or '').strip()
    return h.replace('refs/remotes/', '') if h else 'origin/main'


def last_audit(root):
    """(date, decision) of the last dependency-audit run from the log — it is in the status
    description, because the audit runs at tags, not at commit, and without a date "clean" says nothing."""
    try:
        with open(os.path.join(root, LOG), encoding='utf-8') as f:
            rows = f.read().splitlines()
    except OSError:
        return None
    for line in reversed(rows[-5000:]):
        try:
            w = json.loads(line)
        except ValueError:
            continue
        if w.get('check') == 'dependency-audit' and w.get('decision') in ('clean', 'warn', 'block', 'exception'):
            return (w.get('ts', '')[:10], w['decision'])
    return None


def collect_status(root, d, commits):
    """(state, description) of the status for a list of branch commits (oldest first)."""
    no_evidence, not_run, blocked, checks, warnings, ts = [], [], [], set(), 0, ''
    for c in commits:
        e = commit_evidence(root, d, c)
        if not e:
            no_evidence.append(c[:7])
            continue
        ts = max(ts, e.get('ts') or '')
        for n, k in (e.get('checks') or {}).items():
            checks.add(n)
            warnings += k.get('warnings', 0)
            if k.get('decision') == 'error':
                not_run.append(f'{n}@{c[:7]}')
            elif k.get('decision') == 'block':
                blocked.append(f'{n}@{c[:7]}')
    audit = last_audit(root)
    a_txt = f' · OSV audit {audit[0]} {audit[1]}' if audit else ''
    if no_evidence:
        desc = (f'no check evidence for {len(no_evidence)} of {len(commits)} commits '
                f'({", ".join(no_evidence[:3])}{"…" if len(no_evidence) > 3 else ""}) — commit outside the hook')
        return 'failure', desc[:MAX_STATUS_DESCRIPTION]
    if blocked:
        desc = f'blocking findings: {", ".join(blocked[:3])}{"…" if len(blocked) > 3 else ""} — commit made outside the hook'
        return 'failure', desc[:MAX_STATUS_DESCRIPTION]
    if not_run:
        desc = f'check did not run: {", ".join(not_run[:3])}{"…" if len(not_run) > 3 else ""}'
        return 'failure', desc[:MAX_STATUS_DESCRIPTION]
    when = ts.replace('T', ' ')[:16]
    n_c = f'{len(commits)} commit' + ('' if len(commits) == 1 else 's')
    result = 'clean' if not warnings else f'{warnings} warn.'
    names = ', '.join(sorted(checks)) or 'no checks'
    desc = f'{result}: {names} · {n_c} · {when}{a_txt}'
    if len(desc) > MAX_STATUS_DESCRIPTION:
        desc = f'{result}: {len(checks)} checks · {n_c} · {when}{a_txt}'
    return 'success', desc[:MAX_STATUS_DESCRIPTION]


def post_status(root, repo, commit, state, desc):
    """POST /repos/{repo}/statuses/{sha} via gh (token from `gh auth login`). Returns an error or None."""
    gh = gh_binary()
    try:
        r = subprocess.run([gh, 'api', f'repos/{repo}/statuses/{commit}', '-f', f'state={state}',
                            '-f', f'context={STATUS_CONTEXT}', '-f', f'description={desc}', '--silent'],
                           capture_output=True, text=True, timeout=25, cwd=root)
    except FileNotFoundError:
        return 'no gh in PATH'
    except (OSError, subprocess.TimeoutExpired) as e:
        return f'gh api: {e}'
    if r.returncode != 0:
        return 'gh api: ' + ' '.join((r.stderr or r.stdout).strip().splitlines()[-2:])[:200]
    return None


def status_after_push(root, cmd):
    """PostToolUse after `git push`: evidence of the branch's commits → one status on its tip.
    Returns text for Claude, or None (not applicable)."""
    branch = branch_from_push(cmd)
    if branch is None or not pr_status_enabled(root):
        return None
    if not branch:
        branch = (git(root, 'branch', '--show-current') or '').strip()
    if not branch or branch in ('main', 'master'):
        return None
    local, remote = sha(root, branch), sha(root, 'refs/remotes/origin/' + branch)
    if not local or local != remote:
        return None                      # the push failed or went somewhere else
    base = base_branch(root)
    commits = lines(git(root, 'rev-list', '--reverse', f'{base}..{branch}'))
    if not commits:
        return None
    d = evidence_dir(root)
    if not d:
        return None
    state, desc = collect_status(root, d, commits)
    repo = github_repo(root)
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    entry = {'ts': ts, 'point': 'push', 'head': local[:7], 'check': 'pr-status', 'branch': branch,
             'state': state, 'description': desc, 'commits': len(commits)}
    if not repo:
        entry['decision'] = 'error'
        entry['error'] = 'repository unknown (neither ## Integrations → Repo nor remote origin)'
    else:
        error = post_status(root, repo, local, state, desc)
        entry['decision'] = 'error' if error else 'posted'
        if error:
            entry['error'] = error
    write_log(root, [entry])
    if entry['decision'] == 'error':
        return (f'Telesma — status "{STATUS_CONTEXT}" on {branch}@{local[:7]} was NOT posted '
                f'({entry["error"]}). Content: {state} — {desc}. Tell the human at the next report.')
    return f'Telesma — status "{STATUS_CONTEXT}" on {branch}@{local[:7]}: {state} — {desc}'


def last_tag(root, pattern):
    t = git(root, 'describe', '--tags', '--abbrev=0', '--match', pattern, 'HEAD')
    return t.strip() if t else None


def plan_paths(root, plan):
    """(files, directories, wide) from the `git add` arguments of the commit plan. An argument that
    is not a file or a directory under the project root at hook time (a path relative to another
    directory, a file that does not exist yet) makes the scope wide instead of being dropped."""
    files, dirs, wide = [], [], bool(plan.get('wide'))
    for sc in plan.get('added', []):
        full = os.path.normpath(os.path.join(root, sc))
        rel = os.path.relpath(full, root)
        if rel.startswith('..') or os.path.isabs(sc):
            wide = True
        elif os.path.isdir(full):
            dirs.append(rel)
        elif os.path.isfile(full):
            files.append(rel)
        else:
            wide = True
    return files, dirs, wide


def scope_files(root, point, scope, commit_plan=None, since=None):
    """List of (relative) paths to check. Raises GitError when git does not answer.

    At commit the list is never narrower than what the command can commit: whenever the plan
    cannot be read exactly (a flag, a glob, a pathspec, a command that did not parse) the scope
    is everything modified plus everything untracked."""
    if scope == 'all':
        return git_z(root, 'ls-files', '-z')
    if point == 'commit':
        p = commit_plan or {}
        has_head = bool(sha(root, 'HEAD'))
        found = set(git_z(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'))
        files, dirs, wide = plan_paths(root, p)
        if (p.get('all_tracked') or wide) and has_head:
            found |= set(git_z(root, 'diff', '--name-only', '--diff-filter=ACMR', '-z', 'HEAD'))
        if wide:
            found |= set(git_z(root, 'ls-files', '--modified', '--others', '--exclude-standard', '-z'))
        for sc in dirs:
            found |= set(git_z(root, 'ls-files', '--modified', '--others', '--exclude-standard', '-z', '--', sc))
            if p.get('force'):
                found |= set(git_z(root, 'ls-files', '--others', '-z', '--', sc))
        found |= set(files)
        return sorted(found)
    if point == 'phase':
        since = since or last_tag(root, PHASE_TAG + '*')
    elif point == 'release':
        since = since or last_tag(root, 'v[0-9]*')
    if not since:
        return git_z(root, 'ls-files', '-z')
    return git_z(root, 'diff', '--name-only', '--diff-filter=ACMR', '-z', f'{since}...HEAD')


def staged_mismatch(root, plan):
    """Paths staged in one version while the working tree holds another, and which this command
    does not stage again. The checks read the working tree; for such a path they would read
    something else than what gets committed."""
    staged = set(git_z(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'))
    if not staged:
        return []
    differs = staged & set(git_z(root, 'diff', '--name-only', '-z'))
    if not differs or plan.get('readd_all'):
        return []
    files, dirs, _ = plan_paths(root, plan)
    covered = set(files)
    return sorted(p for p in differs
                  if p not in covered and not any(p == d or p.startswith(d.rstrip('/') + '/') for d in dirs if d != '.')
                  and '.' not in dirs)


# Framework files in the project, not project code: the judge hook in .claude/hooks/ is updated
# at startup and goes into the session's first commit — sast blocked it for a deliberate `shell=True`
SKIPPED_DIRS = (DIRECTORY + '/', '.claude/')


def filter_files(root, files, everything=False):
    """`everything` (a module with `filter: none` — secrets): only the check modules themselves
    are left out; no size limit, no name skips, `.claude/` included. A secret is a secret in a
    lockfile, in a minified bundle and in a 3 MB dump."""
    out = []
    for p in files:
        if unsafe_path(p) or p.startswith(DIRECTORY + '/'):
            continue
        full = os.path.join(root, p)
        try:
            if not os.path.isfile(full):
                continue
            if not everything and (p.startswith(SKIPPED_DIRS) or SKIPPED.search(p)
                                   or os.path.getsize(full) > MAX_BYTES):
                continue
        except OSError:
            continue
        out.append(p)
    return out


# --- Running the checks -------------------------------------------------------------------

def fingerprint(name, z):
    # `file_fingerprint: false` — the finding is about a thing, not a place (one weakening
    # marked in several files); moving the marker to another file does not invalidate the exception
    path = z.get('file', '') if z.get('file_fingerprint', True) else ''
    base = '|'.join([name, z.get('rule', ''), path,
                     z.get('content_fingerprint') or z.get('message', '')])
    return hashlib.sha1(base.encode('utf-8')).hexdigest()[:12]


def load_exceptions(root):
    try:
        with open(os.path.join(root, EXCEPTIONS), encoding='utf-8') as f:
            return set(re.findall(r'^\s*-\s*`([0-9a-f]{12})`', f.read(), re.M))
    except OSError:
        return set()


# Claude Code runs the hook without the user's shell profile, so PATH lacks the directories of
# tool installers: on one project clippy, fmt and cargo check passed as "tool missing", because
# the hook did not see ~/.cargo/bin. We add the ones that exist, at the end — the user's PATH
# (e.g. a chosen Node version) wins.
TOOL_DIRS = ('~/.cargo/bin', '~/.local/bin', '~/go/bin', '~/.deno/bin', '~/.bun/bin',
             '~/.volta/bin', '/opt/homebrew/bin', '/usr/local/bin')


def tool_path():
    parts = [c for c in os.environ.get('PATH', '').split(os.pathsep) if c]
    for k in TOOL_DIRS:
        d = os.path.expanduser(k)
        if d not in parts and os.path.isdir(d):
            parts.append(d)
    return os.pathsep.join(parts)


def run_check(root, u, point, files, budget, since=None, files_root=None, vouched=False):
    """Returns (findings, error or None, crashed). `crashed` = the module broke (an exit code other
    than 0 and 3): that is not "tool missing", so it is not waved through."""
    run = u['module'].get('run')
    if not run:
        return [], 'module without a "run" field', False
    limit = min(u['limit'] or DEFAULT_LIMIT[point], max(budget, 1))
    env = {**os.environ, 'TELESMA_POINT': point, 'TELESMA_ROOT': files_root or root, 'TELESMA_PROJECT': root,
           'PATH': tool_path(), 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    # Only the runner says whether the config's commands are vouched for (by hand / CI); a variable
    # inherited from the environment must not.
    env.pop('TELESMA_CONFIG_VOUCHED', None)
    if vouched:
        env['TELESMA_CONFIG_VOUCHED'] = '1'
    if since:
        env['TELESMA_SINCE'] = since      # reference point from `--since` (CI) — modules computing "new since…" need it
    try:
        r = subprocess.run(shlex.split(run), cwd=u['module']['dir'], env=env,
                           input='\n'.join(files) + '\n', capture_output=True, encoding='utf-8',
                           errors='replace', timeout=limit)
    except subprocess.TimeoutExpired:
        return [], f'time limit exceeded ({limit} s)', False
    except OSError as e:
        return [], f'cannot run: {e}', False
    if r.returncode == 3:
        return [], (r.stderr.strip().splitlines() or ['required tool missing'])[0], False
    if r.returncode != 0:
        return [], f'exit {r.returncode}: ' + ' '.join(r.stderr.strip().splitlines()[-2:])[:300], True
    out = []
    for line in r.stdout.splitlines():
        try:
            z = json.loads(line)
        except ValueError:
            continue
        if isinstance(z, dict) and z.get('file') is not None:
            out.append(z)
    return out, None, False


def write_log(root, entries):
    if not entries:
        return
    try:
        path = os.path.join(root, LOG)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            for w in entries:
                f.write(json.dumps(w, ensure_ascii=False) + '\n')
    except OSError:
        pass    # the log must never block work


def run_point(root, point, commit_plan=None, since=None, files_root=None, files=None, budget=None, vouched=False):
    """Runs the checks assigned to the point. Returns (blocking, warnings, errors, log).

    `files_root` = where the files are read from when it is not the project itself (a snapshot of
    a commit); the config, the exceptions, the modules and the log always belong to `root`.
    `files` = an explicit list instead of the computed scope. Raises GitError when the scope
    cannot be read."""
    cfg = load_config(root)
    if not cfg['enabled']:
        return [], [], [], []
    froot = files_root or root
    exceptions = load_exceptions(root)
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    head = (git(froot, 'rev-parse', '--short', 'HEAD') or '').strip()
    block, warn, errors, log = [], [], [], []
    if budget is None:
        budget = 570 if point != 'commit' else 120   # the hook has 600 s; margin for the rest
    start = datetime.datetime.now()
    scopes = {}

    def scope_of(kind):
        if kind not in scopes:
            scopes[kind] = list(files) if files is not None and kind != 'all' \
                else scope_files(froot, point, kind, commit_plan, since)
        return scopes[kind]

    def record(name, z, on_failure):
        severity = z.get('severity') or on_failure
        if on_failure == 'warn':
            severity = 'warn'          # the config can only soften a module, never harden it
        fp = fingerprint(name, z)
        entry = {'ts': ts, 'point': point, 'head': head, 'check': name,
                 'rule': z.get('rule', ''), 'file': z.get('file', ''),
                 'line': z.get('line'), 'message': z.get('message', ''), 'fingerprint': fp}
        if fp in exceptions:
            entry['decision'] = 'exception'
        elif severity == 'block':
            entry['decision'] = 'block'
            block.append(entry)
        else:
            entry['decision'] = 'warn'
            warn.append(entry)
        log.append(entry)

    reported_unsafe = False
    for name, cfg_fields in cfg['checks'].items():
        u = settings(root, name, cfg_fields)
        if u is None or point not in u['when']:
            continue
        raw = scope_of(u['scope'])
        if not reported_unsafe:
            # once per run: a path the modules cannot be given is not a path that goes unchecked
            reported_unsafe = True
            for p in raw:
                if unsafe_path(p):
                    record('runner', {'rule': 'unsafe-path', 'file': ascii(p)[1:-1], 'severity': 'block',
                                      'message': 'a file name with a control character, a line break, whitespace '
                                                 'at either end or bytes that are not UTF-8 cannot be handed to '
                                                 'the checks - rename the file'}, 'block')
        selected = filter_files(froot, raw, everything=u['module'].get('filter') == 'none')
        used = (datetime.datetime.now() - start).total_seconds()
        found, error, crashed = run_check(root, u, point, selected, budget - used, since=since, files_root=froot,
                                          vouched=vouched)
        if crashed:
            # A module that broke did not check anything. The finding has a fingerprint like any
            # other, so the human can let it through — the author of the commit cannot.
            record(name, {'rule': 'check-crashed', 'file': f'{DIRECTORY}/{name}', 'severity': 'block',
                          'file_fingerprint': False, 'content_fingerprint': 'check-crashed',
                          'message': f'the check broke and checked nothing ({error})'}, u['on_failure'])
            continue
        if error:
            errors.append(f'{name}: {error}')
            log.append({'ts': ts, 'point': point, 'head': head, 'check': name,
                        'decision': 'error', 'message': error})
            continue
        for z in found:
            record(name, z, u['on_failure'])
        if not found:
            log.append({'ts': ts, 'point': point, 'head': head, 'check': name,
                        'decision': 'clean', 'files': len(selected)})
    write_log(root, log)
    return block, warn, errors, log


def describe(entries, limit=25):
    out = []
    for w in entries[:limit]:
        where = w['file'] + (f':{w["line"]}' if w.get('line') else '')
        rule = f'/{w["rule"]}' if w.get('rule') else ''
        out.append(f'  - [{w["check"]}{rule}] {where} — {w["message"]} (fingerprint `{w["fingerprint"]}`)')
    if len(entries) > limit:
        out.append(f'  … and {len(entries) - limit} more ({LOG})')
    return '\n'.join(out)


# --- Command parsing -------------------------------------------------------------------

GIT_OPTIONS_WITH_ARGUMENT = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--config-env'}
# The body of a heredoc with a quoted delimiter is text, not shell: nothing in it is expanded.
# It is cut out before parsing, so an apostrophe or a quote in a commit message cannot make the
# whole command unreadable (and with it the list of files `git add` stages).
HEREDOC_QUOTED = re.compile(r"(<<-?\s*(['\"])(\w+)\2[^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)
HEREDOC_MESSAGE = re.compile(r"\$\(\s*cat\s+<<-?\s*(['\"])(\w+)\1[ \t]*\n.*?\n[ \t]*\2[ \t]*\n?\s*\)", re.S)


def command_members(cmd):
    """List of members (token lists) separated by &&, ||, ;, |, newline."""
    cmd = HEREDOC_QUOTED.sub(lambda m: m.group(1), cmd)
    try:
        lex = shlex.shlex(cmd.replace('\n', ' ; '), posix=True, punctuation_chars=';&|')
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    out, cur = [], []
    for t in tokens:
        if t and set(t) <= set(';&|'):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def live_substitution(cmd):
    """Whether the command contains something the shell RUNS while expanding it: `$(…)`, backticks,
    `<(…)` — outside single quotes and outside the one inert form, a message read from a heredoc
    with a quoted delimiter (`$(cat <<'EOF' … EOF)`)."""
    s = HEREDOC_MESSAGE.sub(' MESSAGE ', cmd)
    s = HEREDOC_QUOTED.sub(lambda m: m.group(1), s)
    quote, i = None, 0
    while i < len(s):
        c = s[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == '\\':
            i += 2
            continue
        elif c == "'" and quote is None:
            quote = "'"
        elif c == '"':
            quote = None if quote == '"' else '"'
        elif c == '`' or (c == '$' and s[i + 1:i + 2] == '('):
            return True
        elif quote is None and c in '<>' and s[i + 1:i + 2] == '(':
            return True
        i += 1
    return False


def skip_assignments(tokens):
    i = 0
    while i < len(tokens) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[i]):
        i += 1                                  # VAR=x git …
    return i


def git_subcommand(tokens):
    """(subcommand, arguments, directory from -C) for a `git …` member, or None."""
    i = skip_assignments(tokens)
    if i >= len(tokens) or os.path.basename(tokens[i]) != 'git':
        return None
    i += 1
    directory = None
    while i < len(tokens) and tokens[i].startswith('-'):
        if tokens[i] in GIT_OPTIONS_WITH_ARGUMENT and i + 1 < len(tokens):
            if tokens[i] == '-C':
                directory = tokens[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return None
    return tokens[i], tokens[i + 1:], directory


def inline_alias(tokens):
    """`git -c alias.z=commit z …` — an alias defined in the command itself."""
    i = skip_assignments(tokens)
    if i >= len(tokens) or os.path.basename(tokens[i]) != 'git':
        return False
    rest = tokens[i + 1:]
    return any(t in ('-c', '--config-env') and k + 1 < len(rest) and rest[k + 1].lower().startswith('alias.')
               or re.match(r'^(-c|--config-env=)alias\.', t, re.I) for k, t in enumerate(rest))


VERSION = re.compile(r'^v\d+\.\d+\.\d+')
# Members that may stand BEFORE a commit in the same command: they change at most the
# index, not the content of files. Anything else (printf >>, sed -i, python, npm) writes to
# files AFTER the hook has read them — the check would see the state from before the change.
GIT_BEFORE_COMMIT = {'add', 'rm', 'mv', 'status', 'diff', 'log', 'show'}
# Commands that only read — section 4 of the instructions prescribes `grep MUTANT` before `git add`,
# and the command-shape check used to reject exactly that (the first live session). A write through
# a redirect or an option that executes a command (`find -exec`, `-delete`) is still rejected.
READ_BEFORE_COMMIT = {'grep', 'egrep', 'fgrep', 'rg', 'ls', 'cat', 'head', 'tail', 'wc', 'find', 'echo', 'test', '['}
WRITE_OPTIONS = {'-exec', '-execdir', '-delete', '-ok', '-okdir', '-fprint', '-fprintf', '-fls'}
NEUTRAL = {'cd', 'pushd', 'popd', 'true', ':'}
# Operations that create commits. A member that mentions git together with one of these words
# but is not itself a plain `git …` member (a subshell, a brace group, `!`, a variable in the
# command position, an interpreter one-liner) cannot be read — it is refused, not waved through.
CREATING = r'(?:commit|tag|merge|cherry-pick|rebase|revert|am|pull)'
GIT_CREATING = re.compile(r'(?<![\w.-])git(?![\w.-])[^\n]*?(?<![\w-])' + CREATING + r'(?![\w-])')
WORD_CREATING = re.compile(r'(?<![\w-])' + CREATING + r'(?![\w-])')


def read_only(tokens):
    tokens = tokens[skip_assignments(tokens):]
    if not tokens or os.path.basename(tokens[0]) not in READ_BEFORE_COMMIT:
        return False
    return not any('>' in t or t in WRITE_OPTIONS for t in tokens)


WRAPPERS = {'bash', 'sh', 'zsh', 'dash', 'eval', 'xargs', 'env', 'command', 'nice', 'time',
            'nohup', 'timeout', 'watch', 'sudo', 'exec', 'script', 'parallel'}


def git_aliases(root):
    """{alias: expansion} from the git configuration — `git ci` is a commit too."""
    try:
        r = subprocess.run(['git', '-C', root, 'config', '--get-regexp', r'^alias\.'],
                           capture_output=True, encoding='utf-8', errors='replace', timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition(' ')
        out[k[len('alias.'):]] = v.strip()
    return out


def subcommand(tokens, aliases):
    """Like git_subcommand, but with the alias expanded. A shell alias (`!…`) mentioning
    commit/tag returns the subcommand '!shell' — it cannot be analysed."""
    pk = git_subcommand(tokens)
    if not pk:
        return None
    sub, args, d = pk
    exp = (aliases or {}).get(sub)
    if exp:
        if exp.startswith('!'):
            return ('!shell' if WORD_CREATING.search(exp) else sub), args, d
        try:
            t = shlex.split(exp)
        except ValueError:
            t = []
        if t:
            return t[0], t[1:] + args, d
    return sub, args, d


def tag_names(args):
    if any(a in ('-d', '--delete', '-l', '--list', '-v', '--verify') for a in args):
        return []
    names = [a for a in args if not a.startswith('-')]
    for flag in ('-m', '-F', '--message', '--file'):     # the argument after -m is the message
        if flag in args:
            k = args.index(flag)
            if k + 1 < len(args) and args[k + 1] in names:
                names.remove(args[k + 1])
    return names


def member_target(tokens, aliases):
    """'commit' | 'tag' (phase/release) | None — whether the member triggers checks."""
    pk = subcommand(tokens, aliases)
    if not pk:
        return None
    sub, args, _ = pk
    if sub in ('commit', '!shell'):
        return 'commit'
    if sub == 'tag' and any(n.startswith(PHASE_TAG) or VERSION.match(n) for n in tag_names(args)):
        return 'tag'
    return None


def order_problem(cmd, aliases=None):
    """The reason the command cannot be checked reliably, or None.

    The hook reads files BEFORE the command runs. `printf … >> file && git add file && git commit`
    used to pass: the check saw the file without the appended content (the first live test)."""
    members = command_members(cmd)
    if members is None:
        m = re.search(r'\bgit\b[^;&|\n]*\b(commit|tag)\b', cmd)
        if not m:
            return 'unseen' if GIT_CREATING.search(cmd) else None
        if live_substitution(cmd):
            return 'substitution'
        prefix = re.sub(r'[\s;&|]+$', '', cmd[:m.start()])
        members = command_members(prefix) if prefix.strip() else []
        if members is None:
            return 'order'
        before = members
    else:
        for tokens in members:
            i = skip_assignments(tokens)
            if i >= len(tokens) or tokens[i] in NEUTRAL:
                continue
            text = ' '.join(tokens[i:])
            if os.path.basename(tokens[i]) in WRAPPERS and GIT_CREATING.search(' '.join(tokens[i + 1:])):
                return 'wrapper'
            if inline_alias(tokens):
                return 'alias'
            pk = subcommand(tokens, aliases)
            if pk:
                if pk[0] == '!shell':
                    return 'alias'
                continue
            if read_only(tokens):
                continue
            if GIT_CREATING.search(text) or (tokens[i][:1] in '$`' and WORD_CREATING.search(text)):
                return 'unseen'
        # EVERY target, not just the first: `git commit && git tag telesma/phase-N` tags a commit
        # the phase check never saw (at hook time HEAD was still the previous one)
        targets = [k for k, t in enumerate(members) if member_target(t, aliases)]
        if not targets:
            return None
        if live_substitution(cmd):
            return 'substitution'
        before = members[:targets[-1]]
    for tokens in before:
        i = skip_assignments(tokens)
        if i >= len(tokens) or tokens[i] in NEUTRAL:
            continue
        pk = subcommand(tokens, aliases)
        if pk and pk[0] in GIT_BEFORE_COMMIT:
            if any(a.startswith('--output') for a in pk[1]):
                return 'output'            # `git diff --output=file` writes a file
            continue
        if read_only(tokens):
            continue
        return 'order'
    return None


# Options of `git commit` whose value is the next argument (a short one may end a cluster: `-am`)
COMMIT_VALUE_LONG = {'--message', '--file', '--reuse-message', '--reedit-message', '--author', '--date',
                     '--fixup', '--squash', '--template', '--cleanup', '--trailer', '--pathspec-from-file'}
COMMIT_VALUE_SHORT = 'mFCct'
ADD_EVERYTHING = {'-A', '--all', '-u', '--update', '--no-ignore-removal'}


def add_arguments(args, plan):
    """`git add` arguments into the plan. A plain path is remembered; anything the hook cannot
    turn into an exact list of files (a flag, a glob, pathspec magic, a variable) makes the scope wide."""
    for a in args:
        if a == '--':
            continue
        if a in ADD_EVERYTHING:
            plan['wide'] = plan['readd_all'] = True
        elif a in ('-f', '--force'):
            plan['force'] = True
        elif a in ('-v', '--verbose', '-n', '--dry-run'):
            continue
        elif a.startswith('-'):
            plan['wide'] = True
        elif a in ('.', './', ':/'):
            plan['wide'] = plan['readd_all'] = True
        elif a.startswith(':') or re.search(r'[*?\[\]{}$`~]', a):
            plan['wide'] = True
        else:
            plan['added'].append(a)


def commit_arguments(args, plan):
    """`git commit` arguments into the plan: -a, --amend, and any pathspec (wide scope)."""
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == '--':
            if i < len(args):
                plan['wide'] = True
            break
        if a.startswith('--'):
            name = a.split('=', 1)[0]
            if name == '--all':
                plan['all_tracked'] = True
            elif name == '--amend':
                plan['amend'] = True
            elif name in ('--include', '--only', '--patch', '--interactive', '--pathspec-from-file'):
                plan['wide'] = True
            if name in COMMIT_VALUE_LONG and '=' not in a:
                i += 1
        elif a.startswith('-') and len(a) > 1:
            if a[1] in 'S':                      # -S[<keyid>]: the value is attached
                continue
            for k, ch in enumerate(a[1:], 1):
                if ch == 'a':
                    plan['all_tracked'] = True
                elif ch in 'iop':
                    plan['wide'] = True
                if ch in COMMIT_VALUE_SHORT:
                    if k == len(a) - 1:
                        i += 1                   # the value is the next argument
                    break                        # the rest of the cluster is the value
        else:
            plan['wide'] = True                  # a pathspec: `git commit -m x file.py`
    if plan.get('all_tracked'):
        plan['readd_all'] = True


def new_plan():
    return {'added': [], 'all_tracked': False, 'wide': False, 'readd_all': False, 'force': False, 'amend': False}


def points_from_command(cmd, aliases=None):
    """{point: plan} — what this command will do to the repository. Commit plan: files
    added in the same command (`git add a b && git commit` — at hook time nothing is in
    the index yet), and whether the list is exact (`wide` = it is not: check everything modified)."""
    members = command_members(cmd)
    if members is None:
        # Unparseable (unclosed quote) — a coarse regex. What `git add` stages is unknown, so
        # the commit scope is everything modified and untracked.
        p = {}
        if re.search(r'\bgit\b[^;&|\n]*\bcommit\b', cmd):
            p['commit'] = dict(new_plan(), wide=True, unparsed=True, amend=bool(re.search(r'--amend\b', cmd)),
                               all_tracked=bool(re.search(r'\bcommit\b[^;&|\n]*\s-(a|-all)\b', cmd)))
        if re.search(r'\bgit\b[^;&|\n]*\btag\b[^;&|\n]*\b' + re.escape(PHASE_TAG), cmd):
            p['phase'] = {}
        if re.search(r'\bgit\b[^;&|\n]*\btag\b[^;&|\n]*\sv\d+\.\d+\.\d+', cmd):
            p['release'] = {}
        return p
    plan, points = new_plan(), {}
    for tokens in members:
        i = skip_assignments(tokens)
        if i < len(tokens) and tokens[i] in ('cd', 'pushd', 'popd'):
            plan['wide'] = True                  # paths after a `cd` are not relative to the project root
            continue
        pk = subcommand(tokens, aliases)
        if not pk:
            continue
        sub, args, directory = pk
        if directory and sub in ('add', 'commit'):
            plan['wide'] = True
        if sub == 'add':
            add_arguments(args, plan)
        elif sub in ('commit', '!shell'):
            if sub == '!shell':
                plan['wide'] = True
            else:
                commit_arguments(args, plan)
            points['commit'] = dict(plan, added=list(plan['added']))
        elif sub == 'tag':
            names = tag_names(args)
            if any(n.startswith(PHASE_TAG) for n in names):
                points['phase'] = {}
            if any(VERSION.match(n) for n in names):
                points['release'] = {}
    return points


# --- Protection of the check files ------------------------------------------------------

EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')


def project_relative(root, path):
    """The path relative to the project root with symlinks resolved, `/` as the separator and in
    lower case — or None when it lies outside. Lower case on purpose: on a case-insensitive file
    system (macOS, Windows) `Telesma/State/check_exceptions.md` IS the exceptions file."""
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(root, path)
    a = os.path.realpath(full).replace('\\', '/').lower()
    r = os.path.realpath(root).replace('\\', '/').lower().rstrip('/')
    if a == r:
        return ''
    return a[len(r) + 1:] if a.startswith(r + '/') else None


def protected(root, path):
    rel = project_relative(root, path)
    if rel is None:
        return False
    return (rel == EXCEPTIONS.lower() or rel == DIRECTORY or rel.startswith(DIRECTORY + '/')
            or rel.startswith('.git/' + EVIDENCE + '/'))


def checks_section(text):
    m = re.search(r'^## Checks[ \t]*\n.*?(?=^## |\Z)', text or '', re.M | re.S)
    return m.group(0) if m else ''


def content_after(current, tool, tool_input):
    """The file content the tool call would leave behind, or None when it cannot be computed
    (the old text is not there — the call fails on its own)."""
    if tool == 'Write':
        return tool_input.get('content', '')
    text = current or ''
    for e in (tool_input.get('edits') or [tool_input]):
        old, new = e.get('old_string') or '', e.get('new_string') or ''
        if not old:
            text = new if not text else text
            continue
        if old not in text:
            return None
        text = text.replace(old, new) if e.get('replace_all') else text.replace(old, new, 1)
    return text


def touches_config(root, tool, tool_input):
    """Whether an edit of telesma/config.md changes the ## Checks section: the edit is applied
    in memory and the section compared before and after — where the old text starts or ends
    does not matter."""
    if project_relative(root, tool_input.get('file_path') or '') != CONFIG.lower():
        return False
    current = read_text(os.path.join(root, CONFIG))
    if current is None:
        return False
    after = content_after(current, tool, tool_input)
    return after is not None and checks_section(after) != checks_section(current)


PROTECTED_MENTION = re.compile(r'telesma/checks(?![\w-])|CHECK_EXCEPTIONS|telesma-checks/', re.I)
BASH_WRITE = re.compile(r'>|\btee\b|\bsed\s+(-[a-zA-Z]*i|--in-place)|\b(mv|cp|rm|truncate|install)\b|\bperl\s+-[a-zA-Z]*i')
WRITE_COMMANDS = {'tee', 'mv', 'cp', 'rm', 'truncate', 'install', 'ln', 'chmod', 'chown', 'dd', 'patch',
                  'touch', 'rsync', 'unlink', 'shred'}
INTERPRETER = re.compile(r'^(python[\d.]*|node|deno|bun|ruby|perl|php|sh|bash|zsh|dash|awk|gawk|osascript)$')
GIT_PATH_WRITES = {'checkout', 'restore', 'apply', 'stash', 'reset', 'clean', 'rm', 'mv'}
REDIRECT_TO_PROTECTED = re.compile(r'>>?\|?\s*\S*(?:telesma/checks(?![\w-])|CHECK_EXCEPTIONS|telesma-checks/)', re.I)


def bash_touches_protected(cmd):
    """Whether a Bash command writes to the check files, as far as a command can be read: a
    redirect INTO them, a writing command or an interpreter one-liner that names them, a git
    operation that rewrites them. Reading them (also with `2>/dev/null`) does not ask. What a
    command hides from this reading is caught by the integrity baseline at the next commit."""
    if not PROTECTED_MENTION.search(cmd):
        return False
    if re.search(r'telesma-checks\.py[^\n;&|]*--(approve|baseline)\b', cmd):
        return True
    members = command_members(cmd)
    if members is None:
        return bool(BASH_WRITE.search(cmd))
    inside = False                              # after `cd telesma/checks` relative names count
    for tokens in members:
        i = skip_assignments(tokens)
        if i >= len(tokens):
            continue
        word, text = os.path.basename(tokens[i]), ' '.join(tokens[i:])
        mention = bool(PROTECTED_MENTION.search(text))
        if word in ('cd', 'pushd'):
            inside = inside or mention
            continue
        if REDIRECT_TO_PROTECTED.search(text) or (inside and re.search(r'(^|\s)\d*>>?', text)
                                                  and not re.search(r'>>?\s*/dev/null', text)):
            return True
        if not (mention or inside):
            continue
        if word in WRITE_COMMANDS:
            return True
        if word in ('sed', 'perl') and any(re.match(r'^(-[a-zA-Z]*i|--in-place)', t) for t in tokens[i + 1:]):
            return True
        if INTERPRETER.match(word) and any(t in ('-c', '-e', '--eval', '-') for t in tokens[i + 1:]):
            return True
        pk = git_subcommand(tokens)
        if pk and pk[0] in GIT_PATH_WRITES:
            return True
    return False


# --- Integrity of the check files ---------------------------------------------------------
#
# A Bash command can write to a file in ways no reading of the command reveals. So the check
# modules, the exceptions file and the ## Checks section are also compared with a baseline of
# hashes kept in .git/telesma-checks/ (this machine's data, never committed). A difference that
# did not come through an edit the human was asked about stops the next commit / tag until the
# human approves it in a terminal (`--approve`) or the launcher records delivered modules.

def file_hash(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ''


def text_hash(t):
    return hashlib.sha256((t or '').encode('utf-8', 'replace')).hexdigest()


def integrity_state(root):
    modules = {}
    base = os.path.join(root, DIRECTORY)
    for dp, dns, fns in os.walk(base):
        dns[:] = sorted(d for d in dns if d != '__pycache__')
        for fn in sorted(fns):
            if fn.endswith(('.pyc', '.pyo')) or fn == '.DS_Store':
                continue
            full = os.path.join(dp, fn)
            modules[os.path.relpath(full, root).replace(os.sep, '/')] = file_hash(full)
    return {'modules': modules,
            'exceptions': file_hash(os.path.join(root, EXCEPTIONS)),
            'checks_section': text_hash(checks_section(read_text(os.path.join(root, CONFIG)) or ''))}


def baseline_file(root):
    d = evidence_dir(root)
    return os.path.join(d, BASELINE) if d else None


def load_baseline(root):
    p = baseline_file(root)
    b = load_json(p) if p else None
    return b if isinstance(b, dict) and isinstance(b.get('modules'), dict) else None


def integrity_drift(root):
    """[description] of what differs from the baseline; one entry when there is no baseline."""
    base = load_baseline(root)
    if base is None:
        return [f'no integrity baseline for the check files (.git/{EVIDENCE}/{BASELINE})']
    now = integrity_state(root)
    out = []
    for p in sorted(set(now['modules']) | set(base['modules'])):
        a, b = base['modules'].get(p), now['modules'].get(p)
        if a != b:
            out.append(f'{p} ({"added" if a is None else "removed" if b is None else "changed"})')
    if now['exceptions'] != base.get('exceptions', ''):
        out.append(f'{EXCEPTIONS} (changed)')
    if now['checks_section'] != base.get('checks_section', ''):
        out.append(f'{CONFIG} -> ## Checks (changed)')
    return out


def write_baseline(root, state=None):
    p = baseline_file(root)
    return bool(p) and save_json(p, state or integrity_state(root))


def integrity_text(drift):
    return ('Telesma - quality checks: the check files differ from what the human approved:\n'
            + '\n'.join(f'  - {x}' for x in drift[:20])
            + (f'\n  ... and {len(drift) - 20} more' if len(drift) > 20 else '')
            + '\nThe operation is stopped until the human looks at it. This is not a finding in the code and '
              'not something to fix or to get around: report TELESMA BLOCKED with this list. The human reviews '
              f'the difference and approves it in a terminal: python3 {DIRECTORY}/telesma-checks.py --approve')


def baseline_key(root, path):
    """Which baseline entry a protected path belongs to: ('modules', rel) | ('exceptions',) | ('checks_section',)."""
    rel = project_relative(root, path)
    if rel is None:
        return None
    if rel == EXCEPTIONS.lower():
        return ('exceptions',)
    if rel == CONFIG.lower():
        return ('checks_section',)
    if rel.startswith(DIRECTORY + '/'):
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
        return ('modules', os.path.relpath(full, os.path.realpath(root)).replace(os.sep, '/'))
    return None


def baseline_get(base, key):
    return (base.get('modules') or {}).get(key[1]) if key[0] == 'modules' else base.get(key[0], '')


def baseline_set(base, key, value):
    if key[0] == 'modules':
        if value:
            base['modules'][key[1]] = value
        else:
            base['modules'].pop(key[1], None)
    else:
        base[key[0]] = value


def integrity_state_entry(root, key):
    if key[0] == 'exceptions':
        return file_hash(os.path.join(root, EXCEPTIONS))
    if key[0] == 'checks_section':
        return text_hash(checks_section(read_text(os.path.join(root, CONFIG)) or ''))
    return file_hash(os.path.join(root, key[1]))


def remember_asked_edit(root, tool, tool_input):
    """PreToolUse, right before the hook asks the human about an edit of a protected file: what
    the file will hold if the human agrees. PostToolUse runs only when the edit was carried out;
    if the file then holds exactly this, the baseline follows. An edit on top of a file that had
    already drifted is not recorded — the earlier change was never shown to anybody."""
    path = tool_input.get('file_path') or ''
    key = baseline_key(root, path)
    base = load_baseline(root)
    d = evidence_dir(root)
    if not key or base is None or not d or tool not in ('Edit', 'Write', 'MultiEdit'):
        return
    if baseline_get(base, key) != integrity_state_entry(root, key):
        return
    full = path if os.path.isabs(path) else os.path.join(root, path)
    after = content_after(read_text(full), tool, tool_input)
    if after is None:
        return
    expected = text_hash(checks_section(after)) if key[0] == 'checks_section' \
        else hashlib.sha256(after.encode('utf-8')).hexdigest()
    asked = load_json(os.path.join(d, APPROVALS)) or []
    asked = [x for x in asked if isinstance(x, dict)][-19:] + [{'key': list(key), 'expected': expected}]
    save_json(os.path.join(d, APPROVALS), asked)


def baseline_after_edit(root, tool_input):
    """PostToolUse of Edit/Write: an edit the human was asked about and that left exactly the
    announced content moves the baseline."""
    key = baseline_key(root, tool_input.get('file_path') or '')
    d = evidence_dir(root)
    base = load_baseline(root)
    if not key or not d or base is None:
        return
    asked = load_json(os.path.join(d, APPROVALS)) or []
    now = integrity_state_entry(root, key)
    hit = [x for x in asked if isinstance(x, dict) and x.get('key') == list(key) and x.get('expected') == now]
    if not hit:
        return
    baseline_set(base, key, now)
    write_baseline(root, base)
    save_json(os.path.join(d, APPROVALS), [x for x in asked if x not in hit])


def mode_baseline(root, templates, config_section=False):
    """Launcher, at every start, after it has synced the delivered modules: creates the baseline
    when there is none; otherwise records only module files identical to the delivered template —
    a file the launcher itself just wrote. Everything else that differs stays a difference.
    `--config-section`: also record the current `## Checks` section — for the launcher right after
    its own wizard wrote it (the person chose those values in the terminal a moment ago)."""
    base = load_baseline(root)
    now = integrity_state(root)
    # From here on every commit that appears is one the hook has to account for: without a
    # remembered HEAD the first PostToolUse of the session would only take note of it.
    d, head = evidence_dir(root), sha(root, 'HEAD')
    if d and head and not os.path.exists(os.path.join(d, SEEN_HEAD)):
        try:
            with open(os.path.join(d, SEEN_HEAD), 'w', encoding='utf-8') as f:
                f.write(head + '\n')
        except OSError:
            pass
    if base is not None and config_section and base.get('checks_section') != now['checks_section']:
        base['checks_section'] = now['checks_section']
        write_baseline(root, base)
    if base is None:
        ok = write_baseline(root, now)
        print('integrity baseline created' if ok else 'integrity baseline: no git repository yet')
        return 0
    changed = False
    if templates and os.path.isdir(templates):
        for rel, h in now['modules'].items():
            delivered = file_hash(os.path.join(templates, os.path.relpath(rel, DIRECTORY)))
            if delivered and delivered == h and base['modules'].get(rel) != h:
                base['modules'][rel] = h
                changed = True
    if changed:
        write_baseline(root, base)
    for x in integrity_drift(root):
        print('differs: ' + x)
    return 0


def mode_approve(root):
    """The human, in a terminal: shows what differs and records the current state as approved."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write('--approve records what the HUMAN has reviewed: run it yourself in a terminal '
                         '(it needs a terminal on stdin and stdout).\n')
        return 2
    drift = integrity_drift(root)
    if not drift:
        print('Nothing differs from the approved state.')
        return 0
    print('Differs from the approved state:')
    for x in drift:
        print('  - ' + x)
    try:
        answer = input('Approve all of the above? [y/N] ').strip().lower()
    except EOFError:
        answer = ''
    if answer not in ('y', 'yes'):
        print('Nothing recorded.')
        return 1
    if not write_baseline(root):
        print('Cannot write the baseline (no git repository?).')
        return 1
    print('Approved.')
    return 0


# --- Hook ---------------------------------------------------------------------------------

def respond(decision, reason):
    # ensure_ascii: the answer must survive any console code page — a deny lost to an encoding
    # error is an operation let through
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': decision,
        'permissionDecisionReason': reason,
    }}))
    sys.exit(0)


SHAPE_REASONS = {
    'order': 'something that can change files stands before the commit/tag in the same command — '
             'the check reads files BEFORE the command runs and would check the state from before the change',
    'wrapper': 'a git operation that creates commits is run through another command (bash -c, xargs, env…) — '
               'the check cannot see what exactly will be committed',
    'alias': 'a git alias that is a shell script or is defined in the command itself (-c alias.…) calls '
             'commit/tag — it cannot be checked',
    'unseen': 'git commit/tag/merge/… stands where the hook cannot read it (a subshell, a brace group, `!`, '
              'a variable instead of `git`, an interpreter one-liner)',
    'substitution': 'the command contains `$(…)`, backticks or `<(…)`, which run before the commit — after '
                    'the check has read the files. A commit message goes as -m "…" or as '
                    '"$(cat <<\'EOF\' … EOF)" with the delimiter in quotes',
    'output': '`--output` before the commit writes a file after the check has read the files',
    'force': '`git add -f` together with a glob, a flag or a path that does not exist yet — the hook cannot '
             'list ignored files that way; name the files',
}


def shape_denial(problem):
    respond('deny', f'Telesma — quality checks: {SHAPE_REASONS[problem]}. Split it: first the file change '
                    f'as a separate command, then just `git add <files> && git commit …` (a tag — also '
                    f'as a separate command, after the commit). This is not a finding in the code, only the shape of the command.')


def pretooluse(data):
    root = os.environ.get('CLAUDE_PROJECT_DIR') or data.get('cwd') or os.getcwd()
    if not load_config(root)['enabled']:
        sys.exit(0)
    tool = data.get('tool_name', '')
    tool_input = data.get('tool_input') or {}

    if tool in EDIT_TOOLS:
        path = tool_input.get('file_path') or tool_input.get('notebook_path') or ''
        if protected(root, path):
            remember_asked_edit(root, tool, tool_input)
            respond('ask', 'Telesma: write to quality-check files (modules / exceptions / evidence) — '
                           'the decision belongs to the human, not to the author of the code')
        if touches_config(root, tool, tool_input):
            remember_asked_edit(root, tool, tool_input)
            respond('ask', 'Telesma: change to the ## Checks section of telesma/config.md — the decision belongs to the human')
        sys.exit(0)

    if tool != 'Bash':
        sys.exit(0)
    cmd = tool_input.get('command') or ''
    if bash_touches_protected(cmd):
        respond('ask', 'Telesma: the command changes quality-check files (modules / exceptions / evidence) — '
                       'the decision belongs to the human')
    aliases = git_aliases(root)
    problem = order_problem(cmd, aliases)
    if problem:
        shape_denial(problem)
    points = points_from_command(cmd, aliases)
    if not points:
        sys.exit(0)

    if load_baseline(root) is None and evidence_dir(root) and not (git(root, 'rev-list', '-n', '1', '--all') or '').strip():
        # A repository without a single commit (created during this session, after the launcher
        # ran): there is no earlier approved state to differ from. With history, a missing
        # baseline is a difference like any other.
        write_baseline(root)
    drift = integrity_drift(root)
    if drift:
        respond('deny', integrity_text(drift))
    plan = points.get('commit')
    if plan is not None:
        _, _, wide = plan_paths(root, plan)
        if plan.get('force') and wide:
            shape_denial('force')
        mismatch = staged_mismatch(root, plan)
        if mismatch:
            listed = ', '.join(ascii(p)[1:-1] for p in mismatch[:8]) + (' ...' if len(mismatch) > 8 else '')
            respond('deny', 'Telesma - quality checks: staged in one version, different in the working tree: '
                            f'{listed}. The checks read the working tree, so they would not see what gets '
                            'committed. Stage the current version (`git add <file>`) or restore it '
                            '(`git restore <file>`) as a separate command, then commit. This is not a finding '
                            'in the code, only the state of the index.')

    all_block, all_warn, all_errors, commit_log = [], [], [], None
    for point in ('commit', 'phase', 'release'):
        if point in points:
            b, w, e, lg = run_point(root, point, commit_plan=points[point] if point == 'commit' else None)
            all_block += b
            all_warn += w
            all_errors += [f'{point}/{x}' for x in e]
            if point == 'commit':
                commit_log = (lg, e)
    if commit_log is not None:
        if all_block:
            drop_pending(root)            # a result from an earlier attempt must not wait for this commit
        else:
            # the commit is about to exist — the evidence waits for its SHA
            save_pending(root, *commit_log, scope_files(root, 'commit', 'changed', plan))
    if all_block:
        text = (f'Telesma — quality checks stopped this operation ({len(all_block)} blocking):\n'
                + describe(all_block) +
                '\nFix it and retry. If the finding is wrong, do NOT get around the check: report '
                'TELESMA BLOCKED with the fingerprint and a justification — the human writes the exception '
                f'into {EXCEPTIONS}.')
        if all_warn:
            text += f'\nAlso warnings ({len(all_warn)}):\n' + describe(all_warn, 10)
        respond('deny', text)
    # No block: no decision — the operation goes the usual permission route. Warnings
    # and check errors reach Claude as additionalContext (they do not block).
    if all_warn or all_errors:
        text = ''
        if all_warn:
            text += (f'Telesma — quality checks: {len(all_warn)} warnings (not blocking — '
                     f'the severity of each rule is set by the module in telesma/checks/<check>/CHECK.md, '
                     f'and "On failure" in the config can only soften it; this is intended, not a defect. '
                     f'Note them in REPORT.md if they concern your change):\n' + describe(all_warn, 15))
        if all_errors:
            text += ('\nChecks that did not run (the operation passed WITHOUT them — tell '
                     'the human): ' + '; '.join(all_errors))
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'additionalContext': text.strip(),
        }}))
    sys.exit(0)


# A git operation that creates a commit or a tag, however the command is shaped — used only to
# decide whether an internal error of the hook has to stop the operation.
GIT_OPERATION = re.compile(r'(?<![\w.-])git(?![\w.-])[^\n]*?(?<![\w-])(?:commit|tag)(?![\w-])')


def mode_pretooluse():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    try:
        pretooluse(data)
    except SystemExit:
        raise
    except Exception as e:                  # noqa: BLE001 — the hook must end with a decision
        cmd = (data.get('tool_input') or {}).get('command') or '' if isinstance(data, dict) else ''
        if isinstance(data, dict) and data.get('tool_name') == 'Bash' and GIT_OPERATION.search(cmd):
            detail = ascii(str(e))[1:-1][:200]
            respond('deny', 'Telesma - quality checks could not run (internal error of the hook: '
                            f'{type(e).__name__}: {detail}). A commit / tag is not let through unchecked. '
                            'This is not a finding in the code: retry once; if it repeats, report TELESMA BLOCKED '
                            'with this message.')
        sys.exit(0)


def mode_posttooluse():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    root = os.environ.get('CLAUDE_PROJECT_DIR') or data.get('cwd') or os.getcwd()
    if not load_config(root)['enabled']:
        sys.exit(0)
    tool = data.get('tool_name')
    if tool in EDIT_TOOLS:
        try:
            baseline_after_edit(root, data.get('tool_input') or {})
        except Exception:                   # noqa: BLE001 — a missed baseline update shows up as a difference
            pass
        sys.exit(0)
    if tool != 'Bash':
        sys.exit(0)
    cmd = (data.get('tool_input') or {}).get('command') or ''
    blocking = None
    try:
        if 'commit' in points_from_command(cmd, git_aliases(root)):
            evidence_after_commit(root, cmd)
        blocking = verify_unseen(root)
    except Exception as e:                  # noqa: BLE001
        blocking = ('Telesma - quality checks: commits made by this command could not be verified '
                    f'({type(e).__name__}) - they have no check evidence; tell the human.')
    text = status_after_push(root, cmd)
    out = {}
    if blocking:
        out.update({'decision': 'block', 'reason': blocking})
    if text or blocking:
        out['hookSpecificOutput'] = {'hookEventName': 'PostToolUse', 'additionalContext': text or blocking}
        print(json.dumps(out))
    sys.exit(0)


def mode_point(point, since):
    root = os.getcwd()
    if not load_config(root)['enabled']:
        print('Checks disabled (## Checks → Enabled: no).')
        return 0
    try:
        b, w, e, _ = run_point(root, point, since=since, vouched=True)
    except GitError as err:
        print(f'CHECK ERROR: {err} - the scope could not be read, nothing was checked')
        return 1
    if b:
        print(f'BLOCK ({len(b)}):\n' + describe(b, 200))
    if w:
        print(f'WARN ({len(w)}):\n' + describe(w, 200))
    for x in e:
        print(f'CHECK ERROR: {x}')
    if not (b or w or e):
        print(f'Checks ({point}): clean.')
    return 1 if (b or e) else 0


def mode_files_commit():
    """`done` / `commit` of tools/telesma-task.py: the script, not the model, chose the files and
    will commit exactly them — so the checks read exactly them, and nothing has to be guessed from
    the shape of a git command."""
    root = os.getcwd()
    if not load_config(root)['enabled']:
        print('Checks disabled (## Checks → Enabled: no).')
        return 0
    raw = sys.stdin.buffer.read().decode('utf-8', 'surrogateescape')
    files = [p for p in raw.split('\0') if p]
    if load_baseline(root) is None and evidence_dir(root) and not (git(root, 'rev-list', '-n', '1', '--all') or '').strip():
        write_baseline(root)
    drift = integrity_drift(root)
    if drift:
        print('BLOCK (integrity):\n' + integrity_text(drift))
        return 1
    try:
        b, w, e, log = run_point(root, 'commit', files=files)
    except GitError as err:
        print(f'CHECK ERROR: {err} - the scope could not be read, nothing was checked')
        return 1
    if b:
        drop_pending(root)
        print(f'BLOCK ({len(b)}):\n' + describe(b, 200))
    else:
        save_pending(root, log, e, files)
    if w:
        print(f'WARN ({len(w)}):\n' + describe(w, 50))
    for x in e:
        print(f'CHECK DID NOT RUN: {x}')
    if not (b or w or e):
        print('Checks (commit): clean.')
    return 1 if b else 0


def mode_record_commit():
    root = os.getcwd()
    if not load_config(root)['enabled']:
        return 0
    evidence = evidence_after_commit(root, '')
    d = evidence_dir(root)
    head = sha(root, 'HEAD')
    # Only a commit that holds exactly what was checked is marked as seen; anything else stays
    # for the after-the-fact verification of the next PostToolUse.
    if evidence and d and head:
        try:
            with open(os.path.join(d, SEEN_HEAD), 'w', encoding='utf-8') as f:
                f.write(head + '\n')
        except OSError:
            pass
    print('evidence recorded' if evidence else 'no evidence (the commit differs from what was checked)')
    return 0 if evidence else 1


def argument_after(argv, flag, default=None):
    i = argv.index(flag)
    return argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith('--') else default


def main(argv):
    if '--pretooluse' in argv:
        mode_pretooluse()
        return 0
    if '--posttooluse' in argv:
        mode_posttooluse()
        return 0
    if '--validate' in argv:
        print('\n'.join(validate(argument_after(argv, '--validate', os.getcwd()))))
        return 0
    if '--baseline' in argv:
        return mode_baseline(argument_after(argv, '--baseline', os.getcwd()),
                             argument_after(argv, '--templates') if '--templates' in argv else None,
                             config_section='--config-section' in argv)
    if '--approve' in argv:
        return mode_approve(argument_after(argv, '--approve', os.getcwd()))
    if '--files-commit' in argv:
        return mode_files_commit()
    if '--record-commit' in argv:
        return mode_record_commit()
    if '--point' in argv:
        point = argument_after(argv, '--point', '')
        if point not in POINTS:
            sys.stderr.write(f'--point: one of {", ".join(POINTS)}\n')
            return 2
        return mode_point(point, argument_after(argv, '--since') if '--since' in argv else None)
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
