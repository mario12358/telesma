#!/usr/bin/env python3
"""Check `tests` — file list on stdin, JSON findings one per line on stdout.

A suite that is green because some tests were quietly switched off, deleted or stripped of
their assertions is worse than a red one — someone looks at a red one. This check catches it
at commit time, before it reaches history. Deleted files do NOT come on stdin (the runner only
passes ACMR), so the module asks git about deletions itself.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

# The same rule as in weakenings/run.py — one definition of "test file" across the framework
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
CODE = re.compile(r'\.(py|js|jsx|ts|tsx|mjs|cjs|go|rs|java|kt|rb|php)$')
JS = re.compile(r'\.(js|jsx|ts|tsx|mjs|cjs)$')
# A TS test may check a TSX component — pairing by name stem within a language family
FAMILY = {'js': 'js', 'jsx': 'js', 'ts': 'js', 'tsx': 'js', 'mjs': 'js', 'cjs': 'js', 'java': 'jvm', 'kt': 'jvm'}

CODE_DIRS = ('src', 'app', 'lib', 'backend', 'frontend', 'server', 'client', 'api', 'pkg', 'internal',
             'cmd', 'packages', 'apps', 'services', 'core', 'domain', 'web', 'mobile')
# Files without logic — a change without a test is the norm there, not a signal
NO_LOGIC = re.compile(r'(^|/)(\.[^/]*|[^/]*config[^/]*|settings\.py|conftest\.py|__init__\.py|setup\.py|manage\.py|'
                      r'types?\.(py|ts|tsx|js)|constants?\.(py|ts|js)|enums?\.(py|ts)|[^/]*\.d\.ts)$'
                      r'|(^|/)(migrations|alembic|scripts|tools|docs?|\.github)/', re.I)

# An asserting helper behind a test (`self.check_error(...)`, `self.verify_response(...)`) counts as an
# assertion — the first run over the benchmark tests gave 10 false warnings exactly on those
ASSERTION = re.compile(r'\bassert\w*\b|\bassert\w*!\(|\bexpect\s*\(|\bshould\b|\bt\.(Error|Fatal|Fail)\w*\(|'
                       r'\brequire\.\w+\(|pytest\.raises|\.toThrow|\.toMatchSnapshot|\.rejects\b|'
                       r'\bself\.\w*(check|verif|ensure)\w*\(')
# An assertion that checks nothing — the test is green by definition
EMPTY = re.compile(r'\bassert\s+(True|1)\s*(,|$|#)|expect\((true|1)\)\.(toBe|toEqual|toStrictEqual)\(\2\)|'
                   r'expect\(true\)\.toBeTruthy\(\)|assertTrue\(True\)|assert!\(true\)')
# `.only` switches off the rest of the suite — a green result speaks about one test. Deliberately
# without `fit:` (an object key `{ fit: 'cover' }` in a fixture is not a test focus).
ONLY = re.compile(r'\.only\s*\(|\b(fit|fdescribe)\s*\(')
SKIP_DECORATOR = re.compile(r'^\s*@((?:pytest\.)?mark\.skip(?:if)?|(?:unittest\.)?skip(?:If|Unless)?)\b(.*)$')
SKIP_JS = re.compile(r'\b(it|test|describe)\.skip\s*\(|\b(xit|xtest|xdescribe)\s*\(')
SKIP_GO_EMPTY = re.compile(r'\bt\.Skip\(\s*\)|\bt\.SkipNow\(\)')
SKIP_GO_WITH_REASON = re.compile(r'\bt\.Skipf?\(\s*\S')
IGNORE_RS = re.compile(r'^\s*#\[ignore(\s*=\s*"[^"]+")?\s*\]')
DISABLED_JVM = re.compile(r'^\s*@(Disabled|Ignore)\b(\s*\(\s*"[^"]+")?')
# JS/Go have no place for a reason in the API — the reason is a comment on the same line or the line above
REASON_IN_COMMENT = re.compile(r'(//|/\*|#)\s*(skip|reason)\s*:', re.I)


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def git(root, *args, timeout=15):
    try:
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def lines(s):
    return [x for x in (s or '').splitlines() if x.strip()]


def load(root, p):
    """File lines or None (binary / unreadable)."""
    try:
        with open(os.path.join(root, p), 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if b'\0' in data[:8192]:
        return None
    return data.decode('utf-8', 'replace').splitlines()


# --- Names: test ↔ module ------------------------------------------------------------

def stem(p):
    """(name stem without the test suffix, language family) — the test ↔ code pairing key."""
    name = os.path.basename(p)
    base, _, ext = name.rpartition('.')
    if not base:
        return None
    for pattern in (r'^test_(.+)$', r'^(.+)[._-](test|spec)$', r'^(.+)(Test|Tests|Spec|IT)$'):
        m = re.match(pattern, base)
        if m:
            base = m.group(1)
            break
    return base, FAMILY.get(ext, ext)


def code_dirs(root):
    """`- **Code directories**:` from the ### tests subsection of the config, or the defaults."""
    try:
        with open(os.path.join(root, 'telesma', 'config.md'), encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return CODE_DIRS
    m = re.search(r'^### tests[ \t]*\n(.*?)(?=^##|\Z)', text, re.M | re.S)
    if not m:
        return CODE_DIRS
    block = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.S)
    k = re.search(r'^- \*\*Code directories\*\*:[ \t]*(.+?)[ \t]*$', block, re.M)
    if not k:
        return CODE_DIRS
    return tuple(x.strip().strip('`/') for x in k.group(1).split(',') if x.strip())


def code_file(p, dirs):
    """A file with logic in a code directory (or in the root — flat project)."""
    if not CODE.search(p) or TEST_FILE.search(p) or NO_LOGIC.search(p):
        return False
    first = p.split('/', 1)[0] if '/' in p else ''
    return not first or first in dirs


def reexport(rows):
    """An index.ts that only re-exports — no logic."""
    content = [l.strip() for l in rows if l.strip() and not l.strip().startswith(('//', '*', '/*'))]
    return bool(content) and all(l.startswith(('export ', 'export{', 'import ')) for l in content)


# --- Test file content ------------------------------------------------------------

def full_decorator(rows, i):
    """Decorator text with parentheses closed (reason= can sit on the next line)."""
    text, j = rows[i], i
    while text.count('(') > text.count(')') and j + 1 < len(rows) and j - i < 6:
        j += 1
        text += ' ' + rows[j].strip()
    return text


def skip_has_reason(p, rows, nr, line):
    """None = not a skip; True = skip with a reason; False = skip without a reason."""
    previous = rows[nr - 2] if nr > 1 else ''
    if p.endswith('.py'):
        m = SKIP_DECORATOR.match(line)
        if not m:
            return None
        full = full_decorator(rows, nr - 1)
        if re.search(r'\breason\s*=', full):
            return True
        # pytest.mark.skip("…") and unittest.skip("…") take the reason positionally; skipif / skipIf —
        # the first argument is the condition, the reason only via reason= (skipIf: second literal)
        if m.group(1).endswith('skipif'):
            return False        # pytest: reason only as a keyword — and there was none
        literals = re.findall(r'''["'][^"']{2,}["']''', m.group(2))
        return bool(literals)   # skipIf(cond, "…") — second literal; skip("…") — first
    if JS.search(p):
        if not SKIP_JS.search(line):
            return None
        return bool(REASON_IN_COMMENT.search(line) or REASON_IN_COMMENT.search(previous))
    if p.endswith('.go'):
        if SKIP_GO_EMPTY.search(line):
            return bool(REASON_IN_COMMENT.search(line) or REASON_IN_COMMENT.search(previous))
        if SKIP_GO_WITH_REASON.search(line):
            return True
        return None
    if p.endswith('.rs'):
        m = IGNORE_RS.match(line)
        return None if not m else bool(m.group(1))
    if p.endswith(('.java', '.kt')):
        m = DISABLED_JVM.match(line)
        return None if not m else bool(m.group(2))
    return None


def brace_body(rows, i, limit=400):
    """Lines from i to the closing of the first brace (JS / Go) — no parser, by counting."""
    depth, opened, j = 0, False, i
    while j < len(rows) and j - i < limit:
        depth += rows[j].count('{') - rows[j].count('}')
        opened = opened or depth > 0
        if opened and depth <= 0:
            break
        j += 1
    return rows[i:j + 1]


def test_functions(p, rows):
    """[(nr, name, body lines)] — tests that execute something (no .skip / .todo)."""
    out = []
    for i, l in enumerate(rows):
        if p.endswith('.py'):
            m = re.match(r'^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(', l)
            if not m:
                continue
            indent, j = len(m.group(1)), i + 1
            while j < len(rows) and (not rows[j].strip() or len(rows[j]) - len(rows[j].lstrip()) > indent):
                j += 1
            out.append((i + 1, m.group(2), rows[i:j]))
        elif JS.search(p):
            m = re.match(r'''^\s*(it|test)((?:\.\w+)*)\s*[(`]\s*(?:['"`]([^'"`]*))?''', l)
            if not m or '.skip' in m.group(2) or '.todo' in m.group(2):
                continue
            if '{' not in l and '=>' not in l and 'function' not in l:
                continue        # it('x', checkFoo) — body out of reach, we do not guess
            out.append((i + 1, m.group(3) or 'it', brace_body(rows, i)))
        elif p.endswith('_test.go'):
            m = re.match(r'^func\s+(Test\w+)\s*\(', l)
            if m:
                out.append((i + 1, m.group(1), brace_body(rows, i)))
    return out


def check_test_file(p, rows, hits):
    for nr, line in enumerate(rows, 1):
        if len(line) > 4000:
            continue
        if JS.search(p) and ONLY.search(line):
            hits.setdefault('only', []).append((nr, line.strip(), None))
        reason = skip_has_reason(p, rows, nr, line)
        if reason is True:
            hits.setdefault('skip-with-reason', []).append((nr, line.strip(), None))
        elif reason is False:
            hits.setdefault('skip-without-reason', []).append((nr, line.strip(), None))
    for nr, name, body in test_functions(p, rows):
        real = [l for l in body if ASSERTION.search(l) and not EMPTY.search(l)]
        if real:
            continue
        if any(EMPTY.search(l) for l in body):
            hits.setdefault('test-without-assertion', []).append((nr, name, 'has an empty assertion (assert True / expect(true).toBe(true))'))
        else:
            hits.setdefault('test-without-assertion', []).append((nr, name, 'has no assertion at all'))


MESSAGES = {
    'only': ('block', '`.only` / `fit` switches off the rest of the suite — a green result speaks about one test; remove it before committing'),
    'skip-without-reason': ('block', 'test disabled without a reason — add a reason (reason="…" / a `// skip: …` comment on the line above) '
                                     'or restore the test'),
    'skip-with-reason': ('warn', 'test disabled with a reason — remember the suite is green without it'),
    'test-without-assertion': ('warn', 'test {detail} — it passes regardless of the implementation; check what '
                                       'it is meant to prove and add an assertion'),
}


def emit_hits(p, hits):
    """The same pattern on 15 lines is one finding with a counter."""
    for rule, found in hits.items():
        nr, key, detail = found[0]
        severity, message = MESSAGES[rule]
        more = f' (+{len(found) - 1} more in the file)' if len(found) > 1 else ''
        if rule == 'test-without-assertion':
            message = message.format(detail=f'`{key[:60]}` {detail}')
        else:
            message = f'{message}: `{key[:80]}`'
        emit(file=p, line=nr, rule=rule, severity=severity, message=message + more, content_fingerprint=fingerprint(key))


# --- State in git: comparison base, statuses, deletions ------------------------------------

def comparison_base(root, point):
    """The revision "before the change": HEAD at commit; in CI the merge-base with TELESMA_SINCE / origin/main.
    None = nothing to compare against (rules depending on the previous version are skipped)."""
    if point != 'ci':
        return 'HEAD' if git(root, 'rev-parse', '--verify', '-q', 'HEAD^{commit}') else None
    candidates = [os.environ.get('TELESMA_SINCE')] + ['origin/main', 'origin/master']
    for k in candidates:
        if k and git(root, 'rev-parse', '--verify', '-q', k + '^{commit}'):
            mb = git(root, 'merge-base', k, 'HEAD')
            return mb.strip() if mb else None
    return None


def deleted(root, point, base):
    if point == 'ci':
        return set(lines(git(root, 'diff', '--name-only', '--diff-filter=D', base, 'HEAD')))
    # `git rm` → in the index; `rm` + `git add -A` in the command → still only in the working tree
    return (set(lines(git(root, 'diff', '--cached', '--name-only', '--diff-filter=D')))
            | set(lines(git(root, 'diff', '--name-only', '--diff-filter=D', 'HEAD'))))


# A removed line that is not test content: an import extended by another name
# (`import { render, screen }` → `… within }` gave a false "pinned" on a production project)
IMPORT_OR_BLANK = re.compile(r'^\s*(import\b|from\s+\S+\s+import\b|const\s+\{[^}]*\}\s*=\s*require\(|'
                             r'[})\]];?\s*$|$|#|//)')


def removed_test_lines(root, point, base, p):
    """Lines removed from a test file that carry test content (no imports, no blanks)."""
    args = ['diff', '-U0'] + (['HEAD'] if point != 'ci' else [base, 'HEAD']) + ['--', p]
    result = git(root, *args) or ''
    return [l[1:] for l in result.splitlines()
            if l.startswith('-') and not l.startswith('---') and not IMPORT_OR_BLANK.match(l[1:])]




def count_assertions(rows):
    return sum(len(ASSERTION.findall(l)) for l in rows if len(l) <= 4000)


# --- Main loop ------------------------------------------------------------------------

def main():
    point = os.environ.get('TELESMA_POINT', 'commit')
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    dirs = code_dirs(root)
    base = comparison_base(root, point)
    in_base = set(lines(git(root, 'ls-tree', '-r', '--name-only', base))) if base else set()
    status = {p: ('M' if p in in_base else 'A') for p in files}

    tests, code = {}, {}     # stem → path
    for p in files:
        rows = load(root, p)
        if rows is None:
            continue
        if TEST_FILE.search(p) or p.endswith('.rs'):
            hits = {}
            check_test_file(p, rows, hits)
            emit_hits(p, hits)
        if not TEST_FILE.search(p):
            if code_file(p, dirs) and not (os.path.basename(p).startswith('index.') and reexport(rows)):
                code[stem(p)] = p
            continue
        tests[stem(p)] = p
        if status[p] == 'M' and base:
            before = git(root, 'show', f'{base}:{p}')
            if before is not None:
                a, b = count_assertions(before.splitlines()), count_assertions(rows)
                if b < a:
                    emit(file=p, line=None, rule='fewer-assertions', severity='warn',
                         message=f'assertion count dropped {a} → {b} — if the test was weakened '
                                 f'to make it pass, the bug is in the implementation, not in the test',
                         content_fingerprint=f'{a}>{b}')

    # code-without-test: one finding per commit, fingerprint from the file list (not from a location)
    if code and not tests:
        found = sorted(code.values())
        emit(file=found[0], line=None, rule='code-without-test', severity='warn', file_fingerprint=False,
             message=f'{len(found)} code file(s) without any test file in the commit: '
                     f'{", ".join(found[:4])}{" …" if len(found) > 4 else ""} — '
                     f'a refactor without a behaviour change is fine; new logic is not',
             content_fingerprint=fingerprint('\n'.join(found)))

    # test-pinned-to-code: a code ↔ test pair, both modified, something removed from the test
    for key, t in tests.items():
        k = code.get(key)
        if not k or status[t] != 'M' or status[k] != 'M' or not base:
            continue
        if not removed_test_lines(root, point, base, t):
            continue
        emit(file=t, line=None, rule='test-pinned-to-code', severity='warn',
             message=f'test changed together with the code it checks ({k}) — if the test change follows '
                     f'from the implementation, not from the rule, the test guards the implementation',
             content_fingerprint=fingerprint(f'{t}|{k}'))

    # test-deleted: deleted files do not come on stdin — we ask git
    if base:
        removed = deleted(root, point, base)
        existing = {}
        for p in in_base - removed:
            if CODE.search(p) and not TEST_FILE.search(p):
                existing.setdefault(stem(p), p)
        for t in sorted(removed):
            if not TEST_FILE.search(t) or not CODE.search(t):
                continue
            k = existing.get(stem(t))
            if not k:
                continue        # the tested module goes too (or cannot be identified) — cleanup
            emit(file=t, line=None, rule='test-deleted', severity='block',
                 message=f'test file deleted while the tested module {k} stays — restore the test '
                         f'or move its cases; deleting a test does not fix the code',
                 content_fingerprint=fingerprint(f'{t}|{k}'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
