#!/usr/bin/env python3
"""The `red-team` check — every protected route changed in the phase has a test that attacks it.

List of changed files on stdin (diff since the previous phase tag), JSON findings one per line.
For routes from `telesma/state/SECURITY_MAP.md` with a role other than `anonymous` whose definition or
body changed in the phase, it looks in test files for the marker:

    telesma: red-team <METHOD> <path> — no-session, foreign-role, foreign-owner, csrf

The required cases follow from the map, not from memory: `no-session` always, `foreign-role` when
the map has more roles than the route admits, `foreign-owner` when the Ownership column ≠ —,
`csrf` for writes with a cookie session. Missing → blocks the phase tag, and the finding's
message is the task text. The marker does not prove the test guards anything — mutation checks
that (general.md), and so does the auditor (E4); this check makes sure the test was written at all.

The first phase after the map is created only warns: the map was not there at the reference
point, so some routes carry roles from the skeleton and the project has not had time to review it.
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import _routes as R  # noqa: E402

MAX_FINDINGS = 30
MARKER = re.compile(r'telesma:\s*red-team\s+([A-Za-z]+|\*)\s+(\S+)\s*(.*)$')
CASES = ('no-session', 'foreign-role', 'foreign-owner', 'csrf')
ALIASES = {'other-organization': 'foreign-owner', 'foreign-organization': 'foreign-owner',
           'no-session': 'no-session', 'anonymous': 'no-session',
           'foreign-role': 'foreign-role', 'foreign-owner': 'foreign-owner', 'csrf': 'csrf'}


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def changed_lines(root, since, p):
    """Line numbers (new side) touched in the since..HEAD diff; a pure deletion = the line where it was."""
    d = R.git(root, 'diff', '-U0', '--no-color', since, 'HEAD', '--', p) or ''
    out = set()
    for m in re.finditer(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', d, re.M):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        out.update(range(start, start + count) if count else (start, start + 1))
    return out


def markers(root):
    """[(method, path, {cases}, file)] from every test file in the repository."""
    out = []
    for p in (R.git(root, 'ls-files') or '').splitlines():
        if not R.TEST_FILE.search(p) or R.SKIPPED_DIRS.search(p):
            continue
        t = R.read_file(root, p)
        if not t or 'red-team' not in t:
            continue
        for w in t.split('\n'):
            m = MARKER.search(w)
            if not m:
                continue
            words = re.findall(r'[\w-]+', m.group(3).lower())
            out.append((m.group(1).upper(), m.group(2).strip('`"\''), {ALIASES[s] for s in words if s in ALIASES}, p))
    return out


def covers(marker, path):
    """`/registrar/*` = every route under the prefix — a test that iterates over a module's route
    list (a medical project: "CSRF on 26 write routes") does not need a line for each one."""
    if marker.endswith('/*'):
        pref = [x for x in R.canonical(marker[:-2]).split('/') if x]
        seg = [x for x in R.canonical(path).split('/') if x]
        return seg[:len(pref)] == pref
    return R.path_matches(marker, path)


def required(route, row, smap):
    alt = R.alternatives(row['roles']) or []
    needed = ['no-session']
    route_roles = {r for a in alt for r in a}
    others = {r for r in smap['roles'] if r != 'anonymous'}
    if len(others) >= 2 and not others <= route_roles:
        needed.append('foreign-role')
    if not R.is_empty(row.get('ownership', '?')):
        needed.append('foreign-owner')
    if route['method'] in R.WRITE_METHODS and smap['session'] not in ('header', 'bearer'):
        needed.append('csrf')
    return needed


def main():
    root = os.environ.get('TELESMA_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if '--check' in sys.argv:
        return 0
    point = os.environ.get('TELESMA_POINT', 'phase')
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    files = [p for p in files if R.is_code_file(p)]
    smap = R.read_map(root)
    if not files or smap is None:
        return 0                                  # without a map nobody knows what is protected — `intent` reports that
    since = R.reference_point(root, 'phase' if point == 'commit' else point)
    first = since == R.EMPTY_TREE or R.git(root, 'cat-file', '-e', f'{since}:{R.MAP}') is None

    touched = []
    for p in files:
        lines = changed_lines(root, since, p)
        if not lines:
            continue
        for tr in R.file_routes(p, R.read_file(root, p) or '', root):
            if any(tr['start'] <= n <= tr['end'] for n in lines):
                touched.append(tr)
    if not touched:
        return 0
    mk = markers(root)
    found, undecided = [], 0
    for tr in sorted(touched, key=lambda x: (x['file'], x['line'])):
        k = R.route_key(tr['method'], tr['path'])
        row = smap['routes'].get(k)
        if row is None or R.is_public(row['roles']):
            continue                              # a missing row is reported by `intent`; a public route has nobody to exclude
        if R.alternatives(row['roles']) is None:
            undecided += 1
            continue
        needed = required(tr, row, smap)
        have = set()
        for met, sc, cases, _ in mk:
            if met in (tr['method'], 'ALL', '*') and covers(sc, tr['path']):
                have |= cases
        missing = [x for x in needed if x not in have]
        if not missing:
            continue
        found.append(dict(file=tr['file'], line=tr['line'], rule='red-team-missing',
                          severity='warn' if first else 'block',
                          content_fingerprint=fingerprint(k + '|' + ','.join(missing)),
                          message=(('(first phase with the map — blocks from the next one) ' if first else '')
                                   + f'`{tr["method"]} {tr["path"]}` changed in the phase, red team missing: '
                                   f'{", ".join(missing)} — a test that attacks the route and expects refusal, '
                                   f'with the line `telesma: red-team {tr["method"]} {tr["path"]} — {", ".join(needed)}`')))
    if undecided:
        found.append(dict(file=R.MAP, line=None, rule='red-team-undecided', severity='warn', file_fingerprint=False,
                          content_fingerprint=fingerprint(f'undecided|{undecided}'),
                          message=f'{undecided} routes changed in the phase have the role "?" in the map — the red '
                                  f'team does not cover them until the role is decided'))
    for z in found[:MAX_FINDINGS]:
        emit(**z)
    rest = found[MAX_FINDINGS:]
    if rest:
        emit(file=rest[0]['file'], line=None, rule='red-team-missing', severity=rest[0]['severity'],
             file_fingerprint=False, content_fingerprint='counter',
             message=f'+{len(rest)} more routes without a red team — full list: '
                     f'python3 telesma/checks/telesma-checks.py --point {point}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
