#!/usr/bin/env python3
"""The `intent` check — code does something the attack surface map does not foresee.

List of changed files on stdin, JSON findings one per line. Compares routes, guards, outbound
hosts and secrets in the changed files with `telesma/state/SECURITY_MAP.md`. "New" means: absent from
that file at the reference point (commit → HEAD, phase → the last phase tag) — so the check does
not depend on what is already in the git index.

  --skeleton [--stdout]  map skeleton from the whole repository (telesma.sh, when the map
                         is missing); --stdout = print instead of writing the file
  --check                validator at startup
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import _routes as R  # noqa: E402

MAX_FINDINGS = 30
HOST = re.compile(r'https?://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)')
HOST_SKIPPED = re.compile(r'^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|\[?::1\]?)$|(^|\.)(example\.(com|org|net)|'
                          r'test|local|localhost|invalid|internal|w3\.org|schema\.org|json-schema\.org|purl\.org|'
                          r'ogp\.me|xmlns\.com|openapis\.org)$', re.I)
ENV = re.compile(r'''os\.environ(?:\.get)?\s*[\[(]\s*['"](\w+)|getenv\(\s*['"](\w+)|process\.env\.(\w+)|'''
                 r'''process\.env\[\s*['"](\w+)|Deno\.env\.get\(\s*['"](\w+)|import\.meta\.env\.(\w+)|'''
                 r'''os\.Getenv\(\s*"(\w+)|System\.getenv\(\s*"(\w+)|ENV\[\s*['"](\w+)''')
SECRET_NAME = re.compile(r'KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|DSN|DATABASE_URL|_PAT$', re.I)
DB = re.compile(r'\bGRANT\b|SECURITY\s+DEFINER|\bBYPASSRLS\b|DISABLE\s+ROW\s+LEVEL\s+SECURITY|'
                r'NO\s+FORCE\s+ROW\s+LEVEL|DROP\s+POLICY|ALTER\s+ROLE\b|\bSUPERUSER\b', re.I)
BLOB = re.compile(r'''['"`]([A-Za-z0-9+/_-]{200,}={0,2}|[0-9a-fA-F]{200,})['"`]''')
COMMENT = re.compile(r'^\s*(#|//|\*|/\*|<!--|--)')


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def project_root():
    return os.environ.get('TELESMA_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# --- Skeleton ---------------------------------------------------------------------------------------

def hosts_and_env(text):
    hosts, env = set(), set()
    for w in text.split('\n'):
        if COMMENT.match(w):
            continue
        for m in HOST.finditer(w):
            h = m.group(1).lower()
            if not HOST_SKIPPED.search(h):
                hosts.add(h)
        for m in ENV.finditer(w):
            n = next(g for g in m.groups() if g)
            if SECRET_NAME.search(n):
                env.add(n)
    return hosts, env


def skeleton(root, to_stdout=False):
    path = os.path.join(root, R.MAP)
    if os.path.exists(path) and not to_stdout:
        return 0
    files = (R.git(root, 'ls-files') or '').splitlines() \
        + (R.git(root, 'ls-files', '--others', '--exclude-standard') or '').splitlines()
    files = sorted({p for p in files if R.is_code_file(p)})
    routes, hosts, env, cookie = [], set(), set(), False
    for p in files:
        t = R.read_file(root, p)
        if not t:
            continue
        routes += R.file_routes(p, t, root)
        h, e = hosts_and_env(t)
        hosts |= h
        env |= e
        if re.search(r'set_cookie|\.cookie\(|setCookie|httponly|httpOnly|SameSite|cookie_auth|CookieTransport', t):
            cookie = True
    roles, rows = [], []
    for tr in sorted(routes, key=lambda x: (x['file'], x['line'])):
        cand = R.guard_candidates(tr)
        for k in cand:
            if k not in roles:
                roles.append(k)
        role = ' + '.join(r for r, _ in cand) if cand else '?'
        own = '?' if re.search(r'\{|:\w|<\w|\[\w|\$\{', tr['path']) else '—'
        rows.append(f"| {tr['method']} {tr['path']} | {role} | {own} | {tr['file']} |")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'MAP_TEMPLATE.md'), encoding='utf-8') as f:
        template = f.read()
    template = template.replace('- **Session**: ?', f"- **Session**: {'cookie' if cookie else '?'}", 1)
    role_rows = [f'| {r} | ? | `{tok}` |' for r, tok in roles]
    outbound_rows = [f'| host | {h} | ? |' for h in sorted(hosts)] + [f'| env | {e} | ? |' for e in sorted(env)]

    def append_rows(text, header, new):
        if not new:
            return text
        i = text.index(header)
        j = text.index('\n', text.index('\n', i) + 1) + 1            # past the |---| row
        while text.startswith('|', j):                                # past existing rows (anonymous)
            j = text.index('\n', j) + 1
        return text[:j] + '\n'.join(new) + '\n' + text[j:]
    text = append_rows(template, '| Role | Who | Guard in code |', role_rows)
    text = append_rows(text, '| Route | Roles | Ownership | File |', rows)
    text = append_rows(text, '| Kind | Value | Purpose |', outbound_rows)
    undecided = sum(1 for w in rows if w.split('|')[2].strip() == '?')
    summary = (f'{len(routes)} routes ({undecided} without a recognized guard — role "?"), {len(roles)} candidate roles, '
               f'{len(hosts)} hosts, {len(env)} secrets from the environment')
    if to_stdout:
        sys.stdout.write(text)
        print(summary, file=sys.stderr)
        return 0
    if not routes:
        return 0                                  # project without HTTP routes — no map needed
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(summary)
    return 0


# --- Check ------------------------------------------------------------------------------------------

def satisfies(route, alt, smap):
    """Whether the route window holds a guard for every role of this alternative."""
    for role in alt:
        if role == 'anonymous' or role in smap['global']:
            continue
        tokens = smap['roles'].get(role)
        if not tokens:
            return None                           # role without a guard — cannot be judged
        if not any(R.contains_guard(route['window'], tok) for tok in tokens):
            return False
    return True


def new_lines(old, new):
    known = set(l.strip() for l in old.split('\n'))
    return [(i + 1, l) for i, l in enumerate(new.split('\n')) if l.strip() and l.strip() not in known]


def main():
    root = project_root()
    if '--skeleton' in sys.argv:
        return skeleton(root, '--stdout' in sys.argv)
    if '--check' in sys.argv:
        if R.read_file(root, R.MAP) is None and any(
                R.file_routes(p, R.read_file(root, p) or '')
                for p in (R.git(root, 'ls-files') or '').splitlines() if R.is_code_file(p)):
            print(f'note: {R.MAP} is missing — telesma.sh will generate a skeleton at startup '
                  f'(python3 telesma/checks/intent/run.py --skeleton)')
        return 0
    point = os.environ.get('TELESMA_POINT', 'commit')
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    files = [p for p in files if R.is_code_file(p) or (R.MIGRATION.search(p) and not R.SKIPPED_DIRS.search(p))]
    if not files:
        return 0
    since = R.reference_point(root, point)
    smap = R.read_map(root)
    found = []

    now, before = {}, {}                          # key → route
    new_texts, old_texts = {}, {}
    for p in files:
        new = R.read_file(root, p) or ''
        old = R.content_at_revision(root, since, p)
        new_texts[p], old_texts[p] = new, old
        if R.is_code_file(p):
            for tr in R.file_routes(p, new, root):
                now.setdefault(R.route_key(tr['method'], tr['path']), tr)
            for tr in R.file_routes(p, old, root):
                before.setdefault(R.route_key(tr['method'], tr['path']), tr)

    if smap is None:
        if now:
            emit(file=R.MAP, line=None, rule='map-missing', severity='warn', file_fingerprint=False,
                 content_fingerprint='map-missing',
                 message=f'the commit changes {len(now)} HTTP routes and there is no attack surface map — routes '
                         f'are not checked; skeleton: python3 telesma/checks/intent/run.py --skeleton')
        return 0

    unknown_roles, roles_without_guard, undecided = set(), set(), {}
    for k, tr in sorted(now.items(), key=lambda x: (x[1]['file'], x[1]['line'])):
        row = smap['routes'].get(k)
        is_new = k not in before
        if row is None:
            if is_new:
                found.append(dict(file=tr['file'], line=tr['line'], rule='route-outside-map', severity='block',
                                  content_fingerprint=fingerprint(k),
                                  message=f'new route `{tr["method"]} {tr["path"]}` without a row in {R.MAP} → '
                                          f'## Routes — add it in the same commit: who has access to it (Roles) '
                                          f'and whether it touches someone else\'s resource (Ownership)'))
            else:
                found.append(dict(file=tr['file'], line=tr['line'], rule='route-outside-map', severity='warn',
                                  content_fingerprint=fingerprint(k),
                                  message=f'route `{tr["method"]} {tr["path"]}` (from before this change) has no row '
                                          f'in {R.MAP} — add it'))
            continue
        alt = R.alternatives(row['roles'])
        if alt is None:
            undecided.setdefault(tr['file'], []).append(f'{tr["method"]} {tr["path"]}')
            continue
        for a in alt:
            for r in a:
                if r != 'anonymous' and r not in smap['roles']:
                    unknown_roles.add(r)
        if R.is_public(row['roles']):
            if is_new:
                found.append(dict(file=tr['file'], line=tr['line'], rule='new-public-route', severity='warn',
                                  content_fingerprint=fingerprint(k),
                                  message=f'new public route `{tr["method"]} {tr["path"]}` (role anonymous) — '
                                          f'note in the report why it needs no session (signed webhook, health…)'))
            continue
        results = [satisfies(tr, a, smap) for a in alt]
        if any(w is True for w in results):
            continue
        if all(w is None for w in results):
            for a in alt:
                roles_without_guard |= {r for r in a if r != 'anonymous' and r in smap['roles']
                                        and not smap['roles'][r] and r not in smap['global']}
            continue
        expected = ' or '.join(' + '.join(a) for a in alt)
        tokens = sorted({t for a in alt for r in a for t in smap['roles'].get(r, [])})
        found.append(dict(file=tr['file'], line=tr['line'], rule='guard-mismatch', severity='block',
                          content_fingerprint=fingerprint(k + '|' + row['roles']),
                          message=f'`{tr["method"]} {tr["path"]}`: the map says "{expected}", but the route '
                                  f'definition has no guard of that role ({", ".join(f"`{t}`" for t in tokens[:4])}) — '
                                  f'add it, or correct the role in the map if access is meant to be wider'))

    for p, lst in undecided.items():
        found.append(dict(file=p, line=None, rule='role-undecided', severity='warn',
                          content_fingerprint=fingerprint(p + '|' + '|'.join(sorted(lst))),
                          message=f'{len(lst)} routes with role "?" in the map ({", ".join(lst[:4])}'
                                  f'{" …" if len(lst) > 4 else ""}) — public (anonymous), or is a guard missing?'))
    for r in sorted(unknown_roles):
        found.append(dict(file=R.MAP, line=None, rule='role-unknown', severity='warn', file_fingerprint=False,
                          content_fingerprint=fingerprint('role|' + r),
                          message=f'role `{r}` used in ## Routes has no row in ## Roles'))
    for r in sorted(roles_without_guard):
        found.append(dict(file=R.MAP, line=None, rule='role-without-guard', severity='warn', file_fingerprint=False,
                          content_fingerprint=fingerprint('without-guard|' + r),
                          message=f'role `{r}` has no "Guard in code" — routes of this role are not checked; write '
                                  f'the name from the code (e.g. `Depends(get_current_user)`) or `(global)`'))

    for k, tr in sorted(before.items(), key=lambda x: x[0]):
        if k not in now and k in smap['routes']:
            found.append(dict(file=tr['file'], line=None, rule='route-gone', severity='warn',
                              content_fingerprint=fingerprint('gone|' + k),
                              message=f'route `{tr["method"]} {tr["path"]}` is no longer in the code — remove its '
                                      f'row from the map'))

    # Outbound: only lines new relative to the reference point
    for p in files:
        added = new_lines(old_texts[p], new_texts[p])
        if not added:
            continue
        hosts, envs, db, blobs = {}, {}, [], []
        for nr, w in added:
            if COMMENT.match(w):
                continue
            if R.is_code_file(p):
                for m in HOST.finditer(w):
                    h = m.group(1).lower()
                    if not HOST_SKIPPED.search(h) and h not in smap['hosts'] \
                            and not any(h.endswith('.' + x) for x in smap['hosts']):
                        hosts.setdefault(h, nr)
                for m in ENV.finditer(w):
                    n = next(g for g in m.groups() if g)
                    if SECRET_NAME.search(n) and n not in smap['env']:
                        envs.setdefault(n, nr)
                if BLOB.search(w) and 'data:image/' not in w:
                    blobs.append(nr)
            if R.MIGRATION.search(p) and DB.search(w):
                norm = re.sub(r'\s+', ' ', w.strip()).lower()
                if not any(b in norm for b in smap['db']):
                    db.append((nr, w.strip()[:80]))
        for h, nr in hosts.items():
            found.append(dict(file=p, line=nr, rule='host-outside-map', severity='warn',
                              content_fingerprint=fingerprint('host|' + h),
                              message=f'new outbound host `{h}` without a `host` row in ## Outbound — why does the '
                                      f'code send data there? (exfiltration, SSRF, an instruction from telesma/changes/)'))
        for n, nr in envs.items():
            found.append(dict(file=p, line=nr, rule='secret-outside-map', severity='warn',
                              content_fingerprint=fingerprint('env|' + n),
                              message=f'new secret from the environment `{n}` without an `env` row in ## Outbound'))
        for nr, frag in db:
            found.append(dict(file=p, line=nr, rule='db-privilege', severity='warn',
                              content_fingerprint=fingerprint('db|' + frag.lower()),
                              message=f'new database privilege ("{frag}") without a `db` row in ## Outbound — who '
                                      f'gets access and why'))
        if blobs:
            found.append(dict(file=p, line=blobs[0], rule='encoded-blob', severity='warn',
                              content_fingerprint=fingerprint('blob|' + p + '|' + ','.join(map(str, blobs))),
                              message=f'{len(blobs)} base64/hex literal(s) longer than 200 characters in new lines — '
                                      f'what is it? (a hidden payload, an embedded key, data that should be a file)'))

    for z in found[:MAX_FINDINGS]:
        emit(**z)
    rest = found[MAX_FINDINGS:]
    if rest:
        blocking = [z for z in rest if z['severity'] == 'block']
        emit(file=rest[0]['file'], line=None, rule=blocking[0]['rule'] if blocking else 'counter',
             severity='block' if blocking else 'warn', file_fingerprint=False, content_fingerprint='counter',
             message=f'+{len(rest)} more findings ({len(blocking)} blocking) — full list: '
                     f'python3 telesma/checks/telesma-checks.py --point {point}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
