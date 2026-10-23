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

Modes:
  --pretooluse            hook: JSON on stdin; Bash → points from the git command,
                          Edit/Write → protection of the check files
  --posttooluse           hook: after `git commit` evidence → SHA, after `git push` PR status
  --point P [--since REF] by hand / in CI; exit code 1 when something blocks
  --validate              E:/W: lines for the config validator in telesma.sh
"""
import datetime
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

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


# --- Configuration ----------------------------------------------------------------

def strip_comments(t):
    return re.sub(r'<!--.*?-->', '', t, flags=re.S)


def load_config(root):
    """{'enabled': bool, 'checks': {name: {field: value}}} — the ## Checks section."""
    try:
        with open(os.path.join(root, CONFIG), encoding='utf-8') as f:
            text = f.read()
    except OSError:
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
    try:
        with open(os.path.join(root, CONFIG), encoding='utf-8') as f:
            text = f.read()
    except OSError:
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
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
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
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def lines(s):
    return [x for x in (s or '').splitlines() if x.strip()]


def sha(root, ref):
    r = git(root, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
    return r.strip() if r else ''


def gh_available():
    import shutil
    return bool(os.environ.get('TELESMA_GH') or shutil.which('gh'))


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
    checks = {}
    for w in log:
        k = checks.setdefault(w['check'], {'decision': 'clean', 'warnings': 0, 'exceptions': 0})
        d = w.get('decision')
        if d == 'error':
            k['decision'] = 'error'
            k['message'] = w.get('message', '')
        elif d == 'warn':
            k['warnings'] += 1
            if k['decision'] == 'clean':
                k['decision'] = 'warn'
        elif d == 'exception':
            k['exceptions'] += 1
    for n in configured:
        checks.setdefault(n, {'decision': 'error', 'warnings': 0, 'exceptions': 0, 'message': 'not run'})
    return {'point': point, 'checks': checks, 'configured': configured}


def save_pending(root, log, errors):
    """PreToolUse before a commit: the check result waits for the SHA that is about to exist."""
    d = evidence_dir(root)
    if not d:
        return
    head = sha(root, 'HEAD')
    data = checks_summary(root, 'commit', log, errors)
    data.update({'head': head, 'parent': sha(root, 'HEAD~1') if head else '',
                 'ts': datetime.datetime.now().isoformat(timespec='seconds')})
    save_json(os.path.join(d, PENDING), data)


def patch_id(root, commit):
    try:
        a = subprocess.run(['git', '-C', root, 'diff-tree', '-p', '--no-commit-id', '--root', commit],
                           capture_output=True, text=True, timeout=30)
        b = subprocess.run(['git', '-C', root, 'patch-id', '--stable'], input=a.stdout,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return b.stdout.split()[0] if b.stdout.split() else ''


def evidence_after_commit(root, cmd):
    """PostToolUse after `git commit`: pending evidence → file <sha>.json, if the new HEAD
    grew out of the HEAD the hook saw (or out of its parent with --amend)."""
    d = evidence_dir(root)
    if not d:
        return None
    pending = load_json(os.path.join(d, PENDING))
    if not pending:
        return None
    new = sha(root, 'HEAD')
    if not new or new == pending.get('head'):
        return None                      # the commit did not happen — the evidence keeps waiting
    parent = sha(root, 'HEAD~1')
    amend = bool(re.search(r'--amend\b', cmd))
    if not (parent == pending.get('head') or (amend and parent == pending.get('parent'))):
        return None                      # HEAD changed some other way (checkout, pull) — not this commit
    evidence = {'sha': new, 'parent': parent, 'patch_id': patch_id(root, new), 'ts': pending.get('ts'),
                'checks': pending.get('checks', {}), 'configured': pending.get('configured', [])}
    save_json(os.path.join(d, new + '.json'), evidence)
    try:
        os.remove(os.path.join(d, PENDING))
    except OSError:
        pass
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
        if not name.endswith('.json') or name == PENDING:
            continue
        e = load_json(os.path.join(d, name))
        if e and e.get('patch_id') == pid:
            e = dict(e, sha=commit, rewritten_from=e.get('sha'))
            save_json(os.path.join(d, commit + '.json'), e)
            return e
    return None


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
    no_evidence, not_run, checks, warnings, ts = [], [], set(), 0, ''
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
    audit = last_audit(root)
    a_txt = f' · OSV audit {audit[0]} {audit[1]}' if audit else ''
    if no_evidence:
        desc = (f'no check evidence for {len(no_evidence)} of {len(commits)} commits '
                f'({", ".join(no_evidence[:3])}{"…" if len(no_evidence) > 3 else ""}) — commit outside the hook')
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
    gh = os.environ.get('TELESMA_GH') or 'gh'
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


def scope_files(root, point, scope, commit_plan=None, since=None):
    """List of (relative) paths to check."""
    if scope == 'all':
        return lines(git(root, 'ls-files'))
    if point == 'commit':
        p = commit_plan or {}
        found = set(lines(git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR')))
        if p.get('all_tracked'):
            found |= set(lines(git(root, 'diff', '--name-only', '--diff-filter=ACMR', 'HEAD')))
        for sc in p.get('added', []):
            if sc in ('.', '-A', '--all', ':/'):
                found |= set(lines(git(root, 'diff', '--name-only', '--diff-filter=ACMR', 'HEAD')))
                found |= set(lines(git(root, 'ls-files', '--others', '--exclude-standard')))
                continue
            full = os.path.join(root, sc)
            if os.path.isdir(full):
                found |= set(lines(git(root, 'ls-files', '--modified', '--others',
                                       '--exclude-standard', '--', sc)))
            elif os.path.isfile(full):
                found.add(os.path.relpath(full, root))
        return sorted(found)
    if point == 'phase':
        since = since or last_tag(root, PHASE_TAG + '*')
    elif point == 'release':
        since = since or last_tag(root, 'v[0-9]*')
    if not since:
        return lines(git(root, 'ls-files'))
    return lines(git(root, 'diff', '--name-only', '--diff-filter=ACMR', f'{since}...HEAD'))


# Framework files in the project, not project code: the judge hook in .claude/hooks/ is updated
# at startup and goes into the session's first commit — sast blocked it for a deliberate `shell=True`
SKIPPED_DIRS = (DIRECTORY + '/', '.claude/')


def filter_files(root, files):
    out = []
    for p in files:
        if p.startswith(SKIPPED_DIRS) or SKIPPED.search(p):
            continue
        full = os.path.join(root, p)
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_BYTES:
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


def run_check(root, u, point, files, budget, since=None):
    """Returns (findings, error or None)."""
    run = u['module'].get('run')
    if not run:
        return [], 'module without a "run" field'
    limit = min(u['limit'] or DEFAULT_LIMIT[point], max(budget, 1))
    env = {**os.environ, 'TELESMA_POINT': point, 'TELESMA_ROOT': root, 'PATH': tool_path()}
    if since:
        env['TELESMA_SINCE'] = since      # reference point from `--since` (CI) — modules computing "new since…" need it
    try:
        r = subprocess.run(shlex.split(run), cwd=u['module']['dir'], env=env,
                           input='\n'.join(files) + '\n', capture_output=True, text=True,
                           timeout=limit)
    except subprocess.TimeoutExpired:
        return [], f'time limit exceeded ({limit} s)'
    except OSError as e:
        return [], f'cannot run: {e}'
    if r.returncode == 3:
        return [], (r.stderr.strip().splitlines() or ['required tool missing'])[0]
    if r.returncode != 0:
        return [], f'exit {r.returncode}: ' + ' '.join(r.stderr.strip().splitlines()[-2:])
    out = []
    for line in r.stdout.splitlines():
        try:
            z = json.loads(line)
        except ValueError:
            continue
        if isinstance(z, dict) and z.get('file') is not None:
            out.append(z)
    return out, None


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


def run_point(root, point, commit_plan=None, since=None):
    """Runs the checks assigned to the point. Returns (blocking, warnings, errors, log)."""
    cfg = load_config(root)
    if not cfg['enabled']:
        return [], [], [], []
    exceptions = load_exceptions(root)
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    head = (git(root, 'rev-parse', '--short', 'HEAD') or '').strip()
    block, warn, errors, log = [], [], [], []
    budget = 570 if point != 'commit' else 120   # the hook has 600 s; margin for the rest
    start = datetime.datetime.now()
    for name, cfg_fields in cfg['checks'].items():
        u = settings(root, name, cfg_fields)
        if u is None or point not in u['when']:
            continue
        files = filter_files(root, scope_files(root, point, u['scope'], commit_plan, since))
        used = (datetime.datetime.now() - start).total_seconds()
        found, error = run_check(root, u, point, files, budget - used, since=since)
        if error:
            errors.append(f'{name}: {error}')
            log.append({'ts': ts, 'point': point, 'head': head, 'check': name,
                        'decision': 'error', 'message': error})
            continue
        for z in found:
            severity = z.get('severity') or u['on_failure']
            if u['on_failure'] == 'warn':
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
        if not found:
            log.append({'ts': ts, 'point': point, 'head': head, 'check': name,
                        'decision': 'clean', 'files': len(files)})
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

GIT_OPTIONS_WITH_ARGUMENT = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'}


def command_members(cmd):
    """List of members (token lists) separated by &&, ||, ;, |, newline."""
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


def git_subcommand(tokens):
    """(subcommand, arguments, directory from -C) for a `git …` member, or None."""
    i = 0
    while i < len(tokens) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[i]):
        i += 1                                  # VAR=x git …
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


def read_only(tokens):
    if not tokens or os.path.basename(tokens[0]) not in READ_BEFORE_COMMIT:
        return False
    return not any('>' in t or t in WRITE_OPTIONS for t in tokens)


WRAPPERS = {'bash', 'sh', 'zsh', 'dash', 'eval', 'xargs', 'env', 'command', 'nice', 'time',
            'nohup', 'timeout', 'watch', 'sudo', 'exec', 'script', 'parallel'}


def git_aliases(root):
    """{alias: expansion} from the git configuration — `git ci` is a commit too."""
    try:
        r = subprocess.run(['git', '-C', root, 'config', '--get-regexp', r'^alias\.'],
                           capture_output=True, text=True, timeout=10)
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
            return ('!shell' if re.search(r'\b(commit|tag)\b', exp) else sub), args, d
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
            return None
        prefix = re.sub(r'[\s;&|]+$', '', cmd[:m.start()])
        members = command_members(prefix) if prefix.strip() else []
        if members is None:
            return 'order'
        before = members
    else:
        for tokens in members:
            i = 0
            while i < len(tokens) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[i]):
                i += 1
            if i < len(tokens) and os.path.basename(tokens[i]) in WRAPPERS \
                    and re.search(r'\bgit\b.*\b(commit|tag)\b', ' '.join(tokens[i + 1:])):
                return 'wrapper'
            pk = subcommand(tokens, aliases)
            if pk and pk[0] == '!shell':
                return 'alias'
        # EVERY target, not just the first: `git commit && git tag telesma/phase-N` tags a commit
        # the phase check never saw (at hook time HEAD was still the previous one)
        targets = [k for k, t in enumerate(members) if member_target(t, aliases)]
        if not targets:
            return None
        before = members[:targets[-1]]
    for tokens in before:
        if tokens and tokens[0] in ('cd', 'pushd', 'true', ':'):
            continue
        pk = subcommand(tokens, aliases)
        if pk and pk[0] in GIT_BEFORE_COMMIT:
            continue
        if read_only(tokens):
            continue
        return 'order'
    return None


def points_from_command(cmd, aliases=None):
    """{point: plan} — what this command will do to the repository. Commit plan: files
    added in the same command (`git add a b && git commit` — at hook time nothing is in
    the index yet)."""
    members = command_members(cmd)
    if members is None:
        # Unparseable (heredoc, unclosed quote) — a coarse regex, without the add plan.
        p = {}
        if re.search(r'\bgit\b[^;&|\n]*\bcommit\b', cmd):
            p['commit'] = {'added': [], 'all_tracked': bool(re.search(r'\bcommit\b[^;&|\n]*\s-(a|-all)\b', cmd))}
        if re.search(r'\bgit\b[^;&|\n]*\btag\b[^;&|\n]*\b' + re.escape(PHASE_TAG), cmd):
            p['phase'] = {}
        if re.search(r'\bgit\b[^;&|\n]*\btag\b[^;&|\n]*\sv\d+\.\d+\.\d+', cmd):
            p['release'] = {}
        return p
    added, points = [], {}
    for tokens in members:
        pk = subcommand(tokens, aliases)
        if not pk:
            continue
        sub, args, _d = pk
        if sub == 'add':
            for a in args:
                if a in ('-A', '--all'):
                    added.append('-A')
                elif a == '--':
                    continue
                elif not a.startswith('-'):
                    added.append(a)
        elif sub == 'commit':
            everything = any(a in ('-a', '--all') or (re.match(r'^-[a-zA-Z]*a[a-zA-Z]*$', a) and not a.startswith('--'))
                             for a in args if a not in ('-m', '--amend'))
            points['commit'] = {'added': list(added), 'all_tracked': everything}
        elif sub == 'tag':
            names = tag_names(args)
            if any(n.startswith(PHASE_TAG) for n in names):
                points['phase'] = {}
            if any(VERSION.match(n) for n in names):
                points['release'] = {}
    return points


# --- Protection of the check files ------------------------------------------------------

def protected(root, path):
    if not path:
        return False
    full = os.path.normpath(os.path.join(root, path)) if not os.path.isabs(path) else os.path.normpath(path)
    rel = os.path.relpath(full, root)
    return rel == EXCEPTIONS or rel == DIRECTORY or rel.startswith(DIRECTORY + os.sep)


def checks_section(text):
    m = re.search(r'^## Checks[ \t]*\n.*?(?=^## |\Z)', text or '', re.M | re.S)
    return m.group(0) if m else ''


def touches_config(root, tool, tool_input):
    """Whether an edit of telesma/config.md changes the ## Checks section."""
    path = tool_input.get('file_path') or ''
    if os.path.normpath(os.path.join(root, path)) != os.path.normpath(os.path.join(root, CONFIG)):
        return False
    try:
        with open(os.path.join(root, CONFIG), encoding='utf-8') as f:
            current = f.read()
    except OSError:
        return False
    sec = checks_section(current)
    if tool == 'Write':
        return checks_section(tool_input.get('content', '')) != sec
    edits = tool_input.get('edits') or [tool_input]
    for e in edits:
        old = e.get('old_string') or ''
        if old and old in sec:
            return True
        if '## Checks' in (e.get('new_string') or '') or '## Checks' in old:
            return True
    return False


BASH_WRITE = re.compile(r'>|\btee\b|\bsed\s+(-[a-zA-Z]*i|--in-place)|\b(mv|cp|rm|truncate|install)\b|\bperl\s+-[a-zA-Z]*i')


def bash_touches_protected(cmd):
    if not re.search(re.escape(DIRECTORY) + r'/|CHECK_EXCEPTIONS', cmd):
        return False
    return bool(BASH_WRITE.search(cmd))


# --- Hook ---------------------------------------------------------------------------------

def respond(decision, reason):
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': decision,
        'permissionDecisionReason': reason,
    }}, ensure_ascii=False))
    sys.exit(0)


def mode_pretooluse():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    root = os.environ.get('CLAUDE_PROJECT_DIR') or data.get('cwd') or os.getcwd()
    if not load_config(root)['enabled']:
        sys.exit(0)
    tool = data.get('tool_name', '')
    tool_input = data.get('tool_input') or {}

    if tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        path = tool_input.get('file_path') or tool_input.get('notebook_path') or ''
        if protected(root, path):
            respond('ask', 'Telesma: write to quality-check files (modules / exceptions) — '
                           'the decision belongs to the human, not to the author of the code')
        if touches_config(root, tool, tool_input):
            respond('ask', 'Telesma: change to the ## Checks section of telesma/config.md — the decision belongs to the human')
        sys.exit(0)

    if tool != 'Bash':
        sys.exit(0)
    cmd = tool_input.get('command') or ''
    if bash_touches_protected(cmd):
        respond('ask', 'Telesma: the command changes quality-check files (modules / exceptions) — '
                       'the decision belongs to the human')
    aliases = git_aliases(root)
    problem = order_problem(cmd, aliases)
    if problem:
        reasons = {
            'order': 'something that can change files stands before the commit/tag in the same command — '
                     'the check reads files BEFORE the command runs and would check the state from before the change',
            'wrapper': 'git commit/tag run through another command (bash -c, xargs, env…) — '
                       'the check cannot see what exactly will be committed',
            'alias': 'a git alias that is a shell script calls commit/tag — it cannot be checked',
        }
        respond('deny', f'Telesma — quality checks: {reasons[problem]}. Split it: first the file change '
                        f'as a separate command, then just `git add <files> && git commit …` (a tag — also '
                        f'as a separate command, after the commit). This is not a finding in the code, only the shape of the command.')
    points = points_from_command(cmd, aliases)
    if not points:
        sys.exit(0)

    all_block, all_warn, all_errors, commit_log = [], [], [], None
    for point in ('commit', 'phase', 'release'):
        if point in points:
            b, w, e, lg = run_point(root, point, commit_plan=points[point] if point == 'commit' else None)
            all_block += b
            all_warn += w
            all_errors += [f'{point}/{x}' for x in e]
            if point == 'commit':
                commit_log = (lg, e)
    if not all_block and commit_log is not None:
        save_pending(root, *commit_log)   # the commit is about to exist — the evidence waits for its SHA
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
        }}, ensure_ascii=False))
    sys.exit(0)


def mode_posttooluse():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    root = os.environ.get('CLAUDE_PROJECT_DIR') or data.get('cwd') or os.getcwd()
    if data.get('tool_name') != 'Bash' or not load_config(root)['enabled']:
        sys.exit(0)
    cmd = (data.get('tool_input') or {}).get('command') or ''
    if 'commit' in points_from_command(cmd, git_aliases(root)):
        evidence_after_commit(root, cmd)
    text = status_after_push(root, cmd)
    if text:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse',
                                                 'additionalContext': text}}, ensure_ascii=False))
    sys.exit(0)


def mode_point(point, since):
    root = os.getcwd()
    if not load_config(root)['enabled']:
        print('Checks disabled (## Checks → Enabled: no).')
        return 0
    b, w, e, _ = run_point(root, point, since=since)
    if b:
        print(f'BLOCK ({len(b)}):\n' + describe(b, 200))
    if w:
        print(f'WARN ({len(w)}):\n' + describe(w, 200))
    for x in e:
        print(f'CHECK ERROR: {x}')
    if not (b or w or e):
        print(f'Checks ({point}): clean.')
    return 1 if (b or e) else 0


def main(argv):
    if '--pretooluse' in argv:
        mode_pretooluse()
        return 0
    if '--posttooluse' in argv:
        mode_posttooluse()
        return 0
    if '--validate' in argv:
        root = argv[argv.index('--validate') + 1] if len(argv) > argv.index('--validate') + 1 else os.getcwd()
        print('\n'.join(validate(root)))
        return 0
    if '--point' in argv:
        i = argv.index('--point')
        point = argv[i + 1] if i + 1 < len(argv) else ''
        if point not in POINTS:
            sys.stderr.write(f'--point: one of {", ".join(POINTS)}\n')
            return 2
        since = argv[argv.index('--since') + 1] if '--since' in argv and argv.index('--since') + 1 < len(argv) else None
        return mode_point(point, since)
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
