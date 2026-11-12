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
# The same thing spelled so that no pattern above sees it: both sides identical, or two literals
TAUTOLOGY = re.compile(r'\bassert\s+(\S.*?)\s*(?:==|is)\s*\1\s*(?:,|$)|\bassert\s+[\d.]+\s*==\s*[\d.]+\s*(?:,|$)|'
                       r'expect\(\s*([^()]+?)\s*\)\.(?:toBe|toEqual|toStrictEqual)\(\s*\2\s*\)')
ONLY = re.compile(r'\.only\s*\(|\b(fit|fdescribe)\s*\(')
# xfail is a skip with a green result: the test runs, fails, and the suite stays green
SKIP_DECORATOR = re.compile(r'^\s*@((?:pytest\.)?mark\.(?:skip(?:if)?|xfail)|(?:unittest\.)?skip(?:If|Unless)?|'
                            r'(?:unittest\.)?expectedFailure)\b(.*)$')
# `pytestmark = pytest.mark.skip` switches off the whole module without touching a single test
SKIP_MODULE = re.compile(r'^pytestmark\s*=\s*(.*\bmark\.(?:skip(?:if)?|xfail)\b.*)$')
# A skip from inside the body: pytest.skip() / pytest.xfail() / self.skipTest() / raise SkipTest
SKIP_CALL = re.compile(r'^\s*(?:pytest\.(?:skip|xfail)|self\.skipTest)\s*\((.*)$|^\s*raise\s+(?:unittest\.)?SkipTest\b\(?(.*)$')
SKIP_JS = re.compile(r'\b(it|test|describe)(?:\.\w+)*\.(skip|fixme|failing)\s*\(|\b(xit|xtest|xdescribe)\s*\(')
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
        r = subprocess.run(['git', '-C', root, '-c', 'core.quotepath=off', *args], capture_output=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
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


def conditional_skip(full):
    """`skipif(<condition>, reason=…)` / `skipIf` / `skipUnless` with a real condition: the test runs
    wherever the condition does not hold (root, Windows, a missing tool) — that is not a switched-off
    test, and a warning on every commit would only teach the reader to skip the warnings. A constant
    condition (`True`, `1`, `not False`) switches it off everywhere and still counts."""
    m = re.search(r'\b(?:skipif|skipIf|skipUnless)\s*\(\s*(.*)', full, re.S)
    if not m:
        return False
    cond = re.split(r',\s*(?:reason\s*=|["\'])', m.group(1), maxsplit=1)[0].strip()
    return bool(cond) and not re.fullmatch(r'(?:not\s+)?(?:True|False|None|\d+|["\'].*["\'])', cond)


def skip_has_reason(p, rows, nr, line):
    """None = not a skip (or a conditional one with a reason); True = skip with a reason; False = skip
    without a reason."""
    previous = rows[nr - 2] if nr > 1 else ''
    if p.endswith('.py'):
        m = SKIP_DECORATOR.match(line)
        if not m:
            mm = SKIP_MODULE.match(line)
            if mm:
                full = full_decorator(rows, nr - 1)
                if not re.search(r'\breason\s*=', full):
                    return False
                return None if conditional_skip(full) else True
            mc = SKIP_CALL.match(line)
            if mc:
                literal = re.search(r'''["'][^"']{2,}["']''', mc.group(1) or mc.group(2) or '')
                return bool(literal or REASON_IN_COMMENT.search(line) or REASON_IN_COMMENT.search(previous))
            return None
        if m.group(1).endswith('expectedFailure'):
            return bool(REASON_IN_COMMENT.search(line) or REASON_IN_COMMENT.search(previous))
        full = full_decorator(rows, nr - 1)
        if re.search(r'\breason\s*=', full) or (m.group(1).endswith(('skipIf', 'skipUnless'))
                                                 and re.findall(r'''["'][^"']{2,}["']''', m.group(2))):
            return None if conditional_skip(full) else True
        # pytest.mark.skip("…") and unittest.skip("…") take the reason positionally; skipif / skipIf —
        # the first argument is the condition, the reason only via reason= (skipIf: second literal)
        if m.group(1).endswith(('skipif', 'xfail')):
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
            indent, j = len(m.group(1)), i
            while j < len(rows) - 1 and not code_part(rows[j]).rstrip().endswith(':'):
                j += 1                   # a signature spread over several lines: `) -> None:` sits at the def's indent
            j += 1
            while j < len(rows) and (not rows[j].strip() or len(rows[j]) - len(rows[j].lstrip()) > indent):
                j += 1
            out.append((i + 1, m.group(2), rows[i:j]))
        elif JS.search(p):
            m = re.match(r'''^\s*(it|test)((?:\.\w+)*)\s*[(`]\s*(?:['"`]([^'"`]*))?''', l)
            if not m or any(k in m.group(2) for k in ('.skip', '.todo', '.fixme', '.failing')):
                continue
            if '{' not in l and '=>' not in l and 'function' not in l:
                continue        # it('x', checkFoo) — body out of reach, we do not guess
            out.append((i + 1, m.group(3) or 'it', brace_body(rows, i)))
        elif p.endswith('_test.go'):
            m = re.match(r'^func\s+(Test\w+)\s*\(', l)
            if m:
                out.append((i + 1, m.group(1), brace_body(rows, i)))
    return out


def code_part(line):
    """The line without its comment: an assertion that was commented out is not an assertion."""
    s = line.lstrip()
    if s.startswith(('#', '//', '/*', '*')) and not s.startswith('#['):
        return ''
    return re.split(r'\s(?:#|//)\s', line, maxsplit=1)[0]


def empty_assertion(l):
    return bool(EMPTY.search(l) or TAUTOLOGY.search(l))


def first_statement(body):
    """The first statement of a Python test body (after the signature and a docstring)."""
    k = 1
    while k < len(body) and not body[k - 1].rstrip().endswith(':'):
        k += 1                                   # a signature spread over several lines
    rest = [l.strip() for l in body[k:] if l.strip() and not l.strip().startswith('#')]
    if rest and rest[0][:3] in ('"""', "'''"):
        quote, closed = rest[0][:3], rest[0].count(rest[0][:3]) >= 2
        rest = rest[1:]
        while rest and not closed:
            closed = quote in rest[0]
            rest = rest[1:]
    return rest[0] if rest else ''


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
        if p.endswith('.py') and re.match(r'^return(\s+None)?\s*$', first_statement(body)):
            hits.setdefault('skip-without-reason', []).append((nr, f'{name}: return as the first statement', None))
        code = [code_part(l) for l in body]
        real = [l for l in code if ASSERTION.search(l) and not empty_assertion(l)]
        if real:
            continue
        if any(empty_assertion(l) for l in code):
            hits.setdefault('test-without-assertion', []).append((nr, name, 'has an empty assertion (assert True / expect(true).toBe(true) / both sides identical)'))
        else:
            hits.setdefault('test-without-assertion', []).append((nr, name, 'has no assertion at all'))


# (the rule `tests-removed` is emitted directly in main — it speaks about the whole change)
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


def name_status(root, *args):
    """[(status letter, old path, new path)] from `git diff --name-status -z -M`."""
    raw = (git(root, 'diff', '--name-status', '-z', '-M', *args) or '').split('\0')
    out, i = [], 0
    while i < len(raw) - 1:
        st = raw[i][:1]
        if st in ('R', 'C') and i + 2 < len(raw):
            out.append((st, raw[i + 1], raw[i + 2]))
            i += 3
        else:
            out.append((st, raw[i + 1], raw[i + 1]))
            i += 2
    return out


def deleted(root, point, base):
    """({paths that stop being tests}, {new test path: old test path}). A test file renamed to a
    name outside the test pattern (`tests/test_calc.py` → `attic/calc_old.txt`) is not run any
    more — for the suite that is a deletion."""
    if point == 'ci':
        changes = name_status(root, base, 'HEAD')
    else:
        # `git rm` → in the index; `rm` + `git add -A` in the command → still only in the working tree
        changes = name_status(root, '--cached') + name_status(root, 'HEAD')
    gone, moved = set(), {}
    for st, old, new in changes:
        if st == 'D':
            gone.add(old)
        elif st == 'R':
            if TEST_FILE.search(old) and not TEST_FILE.search(new):
                gone.add(old)
            elif TEST_FILE.search(old):
                moved[new] = old
    return gone, moved


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
    return sum(len(ASSERTION.findall(code_part(l))) for l in rows if len(l) <= 4000)


def count_tests(p, text):
    """Number of test functions the runner would collect from the file (py / js / go), or None
    for a language this module does not parse."""
    if not (p.endswith('.py') or JS.search(p) or p.endswith('_test.go')):
        return None
    return len(test_functions(p, (text or '').splitlines()))


# --- Main loop ------------------------------------------------------------------------

def main():
    point = os.environ.get('TELESMA_POINT', 'commit')
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l for l in sys.stdin.read().split('\n') if l.strip()]
    dirs = code_dirs(root)
    base = comparison_base(root, point)
    in_base = set(lines(git(root, 'ls-tree', '-r', '--name-only', base))) if base else set()
    status = {p: ('M' if p in in_base else 'A') for p in files}

    tests, code = {}, {}     # stem → path
    now_tests = {}           # test file in scope → number of test functions now
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
        n = count_tests(p, '\n'.join(rows))
        if n is not None:
            now_tests[p] = n
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
        removed, moved = deleted(root, point, base)
        existing = {}
        for p in in_base - removed:
            if CODE.search(p) and not TEST_FILE.search(p):
                existing.setdefault(stem(p), p)
        paired = False
        for t in sorted(removed):
            if not TEST_FILE.search(t) or not CODE.search(t):
                continue
            k = existing.get(stem(t))
            if not k:
                continue        # the tested module goes too (or cannot be identified) — cleanup
            paired = True
            emit(file=t, line=None, rule='test-deleted', severity='block',
                 message=f'test file deleted (or renamed out of the test pattern) while the tested module {k} '
                         f'stays — restore the test or move its cases; deleting a test does not fix the code',
                 content_fingerprint=fingerprint(f'{t}|{k}'))

        # tests-removed: fewer test functions than before, counted over the whole commit — tests
        # moved between files do not count as removed, tests that disappeared do, however it was
        # done (deleted, renamed so the runner no longer collects them, a file without a pair)
        gone_modules = {stem(p) for p in removed if CODE.search(p) and not TEST_FILE.search(p)}
        before, sources = 0, []
        for p in sorted(set(now_tests) | {t for t in removed if TEST_FILE.search(t)}):
            old_path = moved.get(p, p)
            if old_path not in in_base:
                continue
            if p in removed and stem(p) in gone_modules:
                continue        # the tested module goes in the same change — cleanup, not a weakened suite
            n = count_tests(old_path, git(root, 'show', f'{base}:{old_path}'))
            if n:
                before += n
                sources.append(old_path)
        after = sum(now_tests.values())
        if after < before and not paired:
            emit(file=sources[0], line=None, rule='tests-removed', severity='block', file_fingerprint=False,
                 message=f'{before - after} test function(s) disappeared in this change ({before} → {after} in '
                         f'{", ".join(sources[:4])}{" …" if len(sources) > 4 else ""}) — a test that fails says '
                         f'something about the code; restore it, or have the human accept the removal',
                 content_fingerprint=fingerprint(f'{before}>{after}|' + '|'.join(sources)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
