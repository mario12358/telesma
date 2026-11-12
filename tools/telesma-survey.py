#!/usr/bin/env python3
"""Git digest of an existing project for `telesma.sh --adopt` (docs/ARCHITECTURE.md §21).

Code is the truth about WHAT a system does; git is the only source of WHY — and the only cheap
one. This tool mines the history with git plumbing, no model, and prints a few dozen lines the
survey session distils into PROJECT_CONTEXT.md (key decisions, known problems) instead of
reading `git log` itself. Standard library only; Python 3.9+.

    telesma-survey.py <project>           the SURVEY: block for the startup prompt (plain text)
    telesma-survey.py <project> --parts   the survey units, one per line: name<TAB>files<TAB>tests<TAB>sample
    telesma-survey.py <project> --json    everything as JSON (tests, tooling)
    telesma-survey.py <project> --test-results --since <epoch> [--log <file>]
                                          the numbers of the baseline run: JUnit XML written since
                                          <epoch> (Gradle, Maven, pytest --junitxml, …), else the
                                          summary line of the log (pytest, jest/vitest, cargo, dotnet);
                                          prints `total=N pass=N fail=N skip=N source=…` or nothing

What it never prints: author names or e-mails (a count only), commit subjects, file contents.
Paths of files and directories do appear — they are what the survey session reads next.
A directory without git gets a block that says so; nothing fails.
"""
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter

LOG_LIMIT = 3000            # commits read with --name-only; enough for churn, cheap on monorepos
TOP = 8                     # rows per ranking
PARTS_MAX = 10              # survey units → Phase 0 tasks; the rest is merged into one

CODE_EXT = ('.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.go', '.java', '.kt', '.cs',
            '.php', '.rb', '.swift', '.dart', '.vue', '.svelte', '.sql', '.c', '.cc', '.cpp', '.h', '.hpp',
            '.ex', '.exs', '.scala', '.clj', '.lua', '.sh', '.ps1')
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|specs|e2e|cypress|__snapshots__)/|(^|/)test_[^/]*$'
                       r'|[._-](test|spec|tests)\.[^/]+$|_test\.[^/]+$|(^|/)conftest\.py$')
SKIPPED_DIRS = re.compile(r'(^|/)(node_modules|vendor|dist|build|out|target|\.venv|venv|__pycache__|'
                          r'\.next|\.nuxt|\.svelte-kit|coverage|site-packages|telesma|\.claude|\.git|'
                          r'\.idea|\.vscode|bower_components|Pods|DerivedData)(/|$)')
CONTAINER_DIRS = {'src', 'lib', 'app', 'apps', 'pkg', 'packages', 'internal', 'cmd', 'services', 'modules'}
TEST_DIRS = {'test', 'tests', '__tests__', 'spec', 'specs', 'e2e', 'cypress', 'fixtures', 'testdata'}
MANIFESTS = re.compile(r'(^|/)(package\.json|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|'
                       r'requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|uv\.lock|Pipfile(\.lock)?|setup\.py|'
                       r'Cargo\.(toml|lock)|go\.(mod|sum)|pom\.xml|build\.gradle(\.kts)?|gradle\.lockfile|'
                       r'composer\.(json|lock)|Gemfile(\.lock)?|pubspec\.(yaml|lock)|Package\.(swift|resolved)|'
                       r'[^/]*\.csproj|packages\.lock\.json|deno\.(json|jsonc|lock))$')
FIX_SUBJECT = re.compile(r'\b(fix|fixes|fixed|bug|bugfix|hotfix|regression|repair)\b', re.I)
TAG_V = re.compile(r'^v\d+\.\d+\.\d+')
TAG_N = re.compile(r'^\d+\.\d+\.\d+')
TODO = re.compile(r'\b(TODO|FIXME|HACK|XXX)\b')


def git(root, *args, check=False):
    try:
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 and check:
        return None
    return r.stdout


def lines(text):
    return [l for l in (text or '').split('\n') if l.strip()]


def regular(path):
    """A plain file — not a symlink, a FIFO or a device. A repository can track a link named
    `x.py` that points at a pipe or at /dev/zero; opening it would hang the launcher or read
    something outside the project."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def is_code(p):
    return p.endswith(CODE_EXT) and not SKIPPED_DIRS.search(p)


def top_dir(p):
    return p.split('/', 1)[0] if '/' in p else '(root)'


# --- history -----------------------------------------------------------------------------------

def commits(root):
    """[(date, subject, [files])] for the newest LOG_LIMIT commits, newest first."""
    out = git(root, 'log', f'-n{LOG_LIMIT}', '--format=%x00%cs%x01%s', '--name-only', '--no-renames')
    if not out:
        return []
    result = []
    for chunk in out.split('\x00')[1:]:
        head, _, body = chunk.partition('\n')
        date, _, subject = head.partition('\x01')
        files = [l for l in body.split('\n') if l.strip()]
        result.append((date, subject, files))
    return result


def digest(root):
    d = {'git': False}
    root = os.path.abspath(root)
    inside = git(root, 'rev-parse', '--is-inside-work-tree', check=True)
    if not inside or inside.strip() != 'true':
        return d
    d['git'] = True
    head = git(root, 'rev-parse', '--short', 'HEAD', check=True)
    if head is None:
        d['empty'] = True            # a repository without a commit
        d['tracked'] = []
        return d
    d['head'] = head.strip()
    d['branch'] = (git(root, 'rev-parse', '--abbrev-ref', 'HEAD') or '').strip()
    d['total_commits'] = int((git(root, 'rev-list', '--count', 'HEAD') or '0').strip() or 0)
    dates = lines(git(root, 'log', '--format=%cs', '--reverse'))
    d['first_date'] = dates[0] if dates else ''
    d['last_date'] = dates[-1] if dates else ''
    d['commits_90d'] = len(lines(git(root, 'log', '--format=%h', '--since=90 days ago')))
    d['authors'] = len(set(lines(git(root, 'log', '--format=%aE'))))     # a count; no name leaves this function

    tags = lines(git(root, 'tag', '--list'))
    d['tags'] = len(tags)
    scheme = 'none'
    if any(TAG_V.match(t) for t in tags):
        scheme = 'vX.Y.Z'
    elif any(TAG_N.match(t) for t in tags):
        scheme = 'X.Y.Z'
    elif tags:
        scheme = 'other'
    d['tag_scheme'] = scheme
    last_tag = (git(root, 'describe', '--tags', '--abbrev=0', check=True) or '').strip()
    d['last_tag'] = last_tag
    if last_tag:
        d['last_tag_date'] = (git(root, 'log', '-1', '--format=%cs', f'{last_tag}^{{}}') or '').strip()
        d['since_tag'] = int((git(root, 'rev-list', '--count', f'{last_tag}..HEAD') or '0').strip() or 0)

    log = commits(root)
    d['log_sampled'] = len(log)
    reverts = [c for c in log if c[1].startswith('Revert ')]
    d['reverts'] = len(reverts)
    d['last_revert'] = reverts[0][0] if reverts else ''
    d['big_bang'] = sum(1 for c in log if len(c[2]) > 50)
    churn, fix_density = Counter(), Counter()
    dep_commits, dep_last = 0, ''
    for date, subject, files in log:
        code_files = [f for f in files if not SKIPPED_DIRS.search(f)]
        for t in sorted({top_dir(f) for f in code_files}):     # sorted: ties in most_common() keep insertion order
            churn[t] += 1
        if FIX_SUBJECT.search(subject):
            for f in code_files:
                if is_code(f):
                    fix_density[f] += 1
        if any(MANIFESTS.search(f) for f in files):
            dep_commits += 1
            dep_last = dep_last or date
    d['churn'] = churn.most_common(TOP)
    d['fix_commits'] = sum(1 for c in log if FIX_SUBJECT.search(c[1]))
    d['fix_density'] = [(f, n) for f, n in fix_density.most_common(TOP) if n >= 2]
    d['dep_commits'] = dep_commits
    d['dep_last'] = dep_last

    tracked = lines(git(root, 'ls-files'))
    d['tracked'] = tracked
    d.update(inventory(root, tracked))
    return d


# --- the tree --------------------------------------------------------------------------------------

def inventory(root, tracked):
    d = {}
    code = [p for p in tracked if is_code(p)]
    tests = [p for p in code if TEST_FILE.search(p)]
    d['code_files'] = len(code)
    d['test_files'] = len(tests)
    d['extensions'] = Counter(os.path.splitext(p)[1] for p in code).most_common(5)
    low = {p.lower(): p for p in tracked}
    present = []
    if any(re.match(r'^readme(\.|$)', p) for p in low):
        present.append('README')
    if any(re.match(r'^(changelog|changes|history|news)(\.|$)', p) for p in low):
        present.append('CHANGELOG')
    for name in ('claude.md', 'agents.md', '.cursorrules', 'contributing.md'):
        if name in low:
            present.append(low[name])
    if any('.cursor/rules' in p for p in low):
        present.append('.cursor/rules')
    adr = sorted({p.split('/')[0] + '/' + p.split('/')[1] for p in low
                  if re.search(r'(^|/)(adrs?|decisions|architecture-decisions)/', p) and p.count('/') >= 1})
    d['docs_present'] = present
    d['adr_dirs'] = adr[:3]
    ci = []
    if any(p.startswith('.github/workflows/') for p in low):
        ci.append(f".github/workflows ({sum(1 for p in low if p.startswith('.github/workflows/'))} files)")
    for name, label in (('.gitlab-ci.yml', '.gitlab-ci.yml'), ('jenkinsfile', 'Jenkinsfile'),
                        ('.circleci/config.yml', '.circleci'), ('azure-pipelines.yml', 'azure-pipelines.yml'),
                        ('bitbucket-pipelines.yml', 'bitbucket-pipelines.yml')):
        if name in low:
            ci.append(label)
    d['ci'] = ci
    containers = [low[p] for p in low if re.match(r'^(dockerfile|docker-compose(\.[\w-]+)?\.ya?ml|compose\.ya?ml)$', p)]
    d['containers'] = sorted(containers)[:4]
    manifests = sorted({p for p in tracked if MANIFESTS.search(p) and not SKIPPED_DIRS.search(p)})
    d['manifests'] = manifests[:8]
    # TODO / FIXME / HACK in code — a count and the files with most of them (never the text)
    todo_files = Counter()
    for p in code[:2000]:
        if not regular(os.path.join(root, p)):
            continue
        try:
            with open(os.path.join(root, p), encoding='utf-8', errors='replace') as f:
                n = sum(1 for l in f if TODO.search(l))
        except OSError:
            continue
        if n:
            todo_files[p] = n
    d['todo_total'] = sum(todo_files.values())
    d['todo_files'] = todo_files.most_common(5)
    d['parts'] = parts_of(code, tests)
    return d


SPLIT_ABOVE = 8             # a unit with more source files than this is split one level deeper


def split_deep(groups, test_set):
    """A unit whose files all sit under one deep directory (app/src/main/java/com/x/… on Android,
    src/main/java/com/x/… with Maven) is split by the children of that directory — once, when
    there are at least two of them. Files directly in the common directory keep its name."""
    out = {}
    for key, files in groups.items():
        src = [f for f in files if f not in test_set]
        if len(src) <= SPLIT_ABOVE:
            out[key] = files
            continue
        common = os.path.commonpath(src).replace(os.sep, '/') if len(src) > 1 else os.path.dirname(src[0])
        if not common or common == key:
            out[key] = files
            continue
        children = {}
        for f in files:
            rest = f[len(common) + 1:] if f.startswith(common + '/') else ''
            child = common + '/' + rest.split('/')[0] if '/' in rest else common
            children.setdefault(child, []).append(f)
        if len(children) < 2:
            out[key] = files
        else:
            out.update(children)
    return out


def parts_of(code, tests):
    """Survey units: one per directory that holds code, one level deep (two under src/ and
    friends); test directories and root files are grouped on their own. Capped — a monorepo
    with forty packages gets ten units and one "other"."""
    test_set = set(tests)
    groups = {}
    for p in code:
        segs = p.split('/')
        if len(segs) == 1:
            key = '(root)'
        elif segs[0] in CONTAINER_DIRS and len(segs) > 2:
            key = segs[0] + '/' + segs[1]
        else:
            key = segs[0]
        groups.setdefault(key, []).append(p)
    groups = split_deep(groups, test_set)
    units = []
    for key, files in groups.items():
        last = key.split('/')[-1].lower()
        if last in TEST_DIRS:
            continue
        own_tests = [f for f in files if f in test_set]
        src = [f for f in files if f not in test_set]
        if not src:
            continue
        # tests kept apart (tests/<module>/…) count for the unit they name
        stem = last.rstrip('s')
        related = [t for t in tests if t not in files and (f'/{last}/' in t or f'/{stem}' in t.lower())]
        units.append({'name': key, 'files': len(src), 'tests': len(own_tests) + len(related),
                      'sample': [os.path.basename(f) for f in src[:4]]})
    units.sort(key=lambda u: (-u['files'], u['name']))
    if len(units) > PARTS_MAX:
        rest = units[PARTS_MAX:]
        units = units[:PARTS_MAX] + [{'name': 'other (' + ', '.join(u['name'] for u in rest[:6])
                                      + (', …' if len(rest) > 6 else '') + ')',
                                      'files': sum(u['files'] for u in rest),
                                      'tests': sum(u['tests'] for u in rest), 'sample': []}]
    return units


# --- the numbers of a test run ------------------------------------------------------------------

RESULT_DIRS = re.compile(r'(^|/)(test-results|surefire-reports|failsafe-reports|test-reports|TestResults)(/|$)')
JUNIT_FILE = re.compile(r'(^|/)(TEST-[^/]*\.xml|junit[^/]*\.xml|[^/]*\.trx)$', re.I)
SUITE_RE = re.compile(r'<testsuite\b[^>]*>')
ATTR_RE = re.compile(r'\b(tests|failures|errors|skipped|disabled)="(\d+)"')
PYTEST_LINE = re.compile(r'^.*\b\d+ (?:passed|failed|skipped|errors?|xfailed|xpassed)\b.* in [\d.]+s.*$', re.M)
PYTEST_TOKEN = re.compile(r'(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)\b')
LOG_PATTERNS = (
    # jest / vitest: "Tests: 1 failed, 3 passed, 4 total" / "Tests  3 passed | 1 skipped (4)"
    ('jest', re.compile(r'Tests:?\s+(?:(\d+) failed[,|\s]*)?(?:(\d+) passed[,|\s]*)?(?:(\d+) skipped[,|\s]*)?(?:(\d+) total|\((\d+)\))')),
    # cargo: "test result: ok. 5 passed; 1 failed; 2 ignored"
    ('cargo', re.compile(r'test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored')),
    # dotnet: "Passed! - Failed: 0, Passed: 3, Skipped: 0, Total: 3"
    ('dotnet', re.compile(r'Failed:\s+(\d+),\s+Passed:\s+(\d+),\s+Skipped:\s+(\d+),\s+Total:\s+(\d+)')),
)


def junit_counts(root, since):
    total = fail = skip = 0
    seen = 0
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = [d for d in dirnames if not SKIPPED_DIRS.search(d + '/') or d in ('build', 'target', 'dist')]
        rel = os.path.relpath(dirpath, root).replace(os.sep, '/')
        for n in names:
            p = os.path.join(dirpath, n)
            if not (RESULT_DIRS.search(rel + '/') or JUNIT_FILE.search(n)):
                continue
            if not n.lower().endswith('.xml') or not regular(p):
                continue
            try:
                if os.path.getmtime(p) < since:
                    continue
                with open(p, encoding='utf-8', errors='replace') as f:
                    head = f.read(200000)
            except OSError:
                continue
            # a <testsuites> root repeats the totals of its suites: count the suites only
            suites = SUITE_RE.findall(head)
            if not suites:
                continue
            seen += 1
            for s in suites:
                a = {k: int(v) for k, v in ATTR_RE.findall(s)}
                total += a.get('tests', 0)
                fail += a.get('failures', 0) + a.get('errors', 0)
                skip += a.get('skipped', 0) + a.get('disabled', 0)
    if not seen:
        return None
    return dict(total=total, pass_=max(0, total - fail - skip), fail=fail, skip=skip, source='junit-xml')


def log_counts(text):
    # pytest: "1 failed, 4 passed, 2 skipped, 1 error in 0.31s" — the tokens come in any order
    lines = PYTEST_LINE.findall(text)
    if lines:
        n = {}
        for count, kind in PYTEST_TOKEN.findall(lines[-1]):
            n[kind.rstrip('s')] = n.get(kind.rstrip('s'), 0) + int(count)
        p, f, s = n.get('passed', 0) + n.get('xpassed', 0) + n.get('xfailed', 0), n.get('failed', 0) + n.get('error', 0), n.get('skipped', 0)
        return dict(total=p + f + s, pass_=p, fail=f, skip=s, source='log:pytest')
    for name, rx in LOG_PATTERNS:
        last = None
        for m in rx.finditer(text):
            if any(m.groups()):
                last = m
        if not last:
            continue
        g = [int(x) if x else 0 for x in last.groups()]
        if name == 'jest':
            f, p, s, t, t2 = g
            return dict(total=t or t2 or (p + f + s), pass_=p, fail=f, skip=s, source='log:jest')
        if name == 'cargo':
            p, f, s = g
            return dict(total=p + f + s, pass_=p, fail=f, skip=s, source='log:cargo')
        if name == 'dotnet':
            f, p, s, t = g
            return dict(total=t, pass_=p, fail=f, skip=s, source='log:dotnet')
    return None


def test_results(root, since, log_path):
    counts = junit_counts(root, since)
    if counts is None and log_path and regular(log_path):
        with open(log_path, encoding='utf-8', errors='replace') as f:
            counts = log_counts(f.read())
    if not counts:
        return ''
    return f"total={counts['total']} pass={counts['pass_']} fail={counts['fail']} skip={counts['skip']} source={counts['source']}"


# --- rendering -----------------------------------------------------------------------------------

def months_between(a, b):
    try:
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
    except ValueError:
        return 0
    return max(0, (yb - ya) * 12 + (mb - ma))


def render(d):
    out = ['SURVEY: git digest of the existing system (computed by telesma.sh, read-only; distil it '
           'into PROJECT_CONTEXT.md — do not copy it, and do not read git log yourself for what it already says)']
    if not d.get('git'):
        out.append('- No git history: the directory is not a repository. Only the code can be read; '
                   'every "why" has to be asked (an open question in AS_BUILT.md).')
    elif d.get('empty'):
        out.append('- The repository has no commit yet: no history to mine.')
    else:
        out += render_history(d)
    out += render_tree(d)
    return '\n'.join(out)


def render_history(d):
    out = []
    span = months_between(d['first_date'], d['last_date'])
    out.append(f"- History: {d['total_commits']} commits by {d['authors']} author(s), {d['first_date']} → "
               f"{d['last_date']} ({span} months); last 90 days: {d['commits_90d']} commits; "
               f"branch {d['branch']}, HEAD {d['head']}")
    if d['tags']:
        tag = f", last {d['last_tag']}" + (f" ({d['last_tag_date']})" if d.get('last_tag_date') else '')
        tag += f"; {d.get('since_tag', 0)} commits since"
        out.append(f"- Releases: {d['tags']} tags, scheme {d['tag_scheme']}{tag}"
                   + ('' if d['tag_scheme'] == 'vX.Y.Z' else
                      ' — Telesma proposes vX.Y.Z tags; the launcher counts only v* tags as releases'))
    else:
        out.append('- Releases: no tags — the first version Telesma proposes is v0.1.0 (or ask the owner)')
    sampled = '' if d['log_sampled'] >= d['total_commits'] else f" (of the newest {d['log_sampled']} commits)"
    rev = f"- Reverts: {d['reverts']}" + (f" (last {d['last_revert']})" if d['last_revert'] else '')
    out.append(f"{rev}; fix/bug commits: {d['fix_commits']}; commits touching > 50 files: {d['big_bang']}{sampled}")
    if d['churn']:
        out.append('- Churn (commits touching, top): ' + ', '.join(f'{k} {n}' for k, n in d['churn']))
    if d['fix_density']:
        out.append('- Fix density (fix/bug commits per file, top): ' + ', '.join(f'{f} {n}' for f, n in d['fix_density']))
    else:
        out.append('- Fix density: no file appears in two or more fix/bug commits')
    out.append(f"- Dependency changes: {d['dep_commits']} commits touched manifests or lockfiles"
               + (f"; last {d['dep_last']}" if d['dep_last'] else '')
               + (f"; manifests: {', '.join(d['manifests'])}" if d['manifests'] else '; no manifest found'))
    return out


def render_tree(d):
    if 'code_files' not in d:
        return []
    out = []
    docs = ', '.join(d['docs_present']) or 'none'
    adr = f"ADRs in {', '.join(d['adr_dirs'])}" if d['adr_dirs'] else 'no ADRs'
    out.append(f"- Documentation in repo: {docs}; {adr}")
    out.append(f"- CI: {', '.join(d['ci']) or 'none'}; containers: {', '.join(d['containers']) or 'none'}")
    ext = ', '.join(f'{e} {n}' for e, n in d['extensions'])
    ratio = (d['test_files'] / d['code_files']) if d['code_files'] else 0
    todo = f"{d['todo_total']} in {len(d['todo_files'])}+ files" if d['todo_total'] else '0'
    if d['todo_files']:
        todo += ' (top: ' + ', '.join(f'{f} {n}' for f, n in d['todo_files'][:3]) + ')'
    out.append(f"- Code: {d['code_files']} files ({ext}); test files: {d['test_files']} (ratio {ratio:.2f}); "
               f"TODO/FIXME/HACK: {todo}")
    if d['parts']:
        out.append('- Parts (one Phase 0 task each): ' + ', '.join(
            f"{u['name']} ({u['files']} files, {u['tests']} tests)" for u in d['parts']))
    else:
        out.append('- Parts: no code files recognised by extension — survey by directory')
    return out


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__.strip())
        return 0
    root = argv[0]
    if '--test-results' in argv:
        since = float(argv[argv.index('--since') + 1]) if '--since' in argv else 0.0
        log = argv[argv.index('--log') + 1] if '--log' in argv else None
        print(test_results(os.path.abspath(root), since, log))
        return 0
    d = digest(root)
    if not d.get('git') or d.get('empty'):
        # no history, but the tree still gives the units — from the working directory
        files = []
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [x for x in dirnames if not SKIPPED_DIRS.search(x + '/') and not x.startswith('.')]
            for n in names:
                p = os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, '/')
                if is_code(p):
                    files.append(p)
            if len(files) > 5000:
                break
        d.update(inventory(root, sorted(files)))
    if '--json' in argv:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    if '--parts' in argv:
        for u in d.get('parts', []):
            print(f"{u['name']}\t{u['files']}\t{u['tests']}\t{', '.join(u['sample'])}")
        return 0
    print(render(d))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
