#!/usr/bin/env python3
"""Check `dependency-audit` — versions from lockfiles vs the OSV vulnerability database.

Ignores the list of files on stdin: a vulnerability appears in the database without any
change in the project, so it always reads every tracked lockfile. Findings as JSON lines on stdout.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from _net import NoNetwork, Cache, address, fetch  # noqa: E402

try:
    import tomllib
except ImportError:
    tomllib = None

SERIOUS = ('CRITICAL', 'HIGH')


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def norm_py(n):
    return re.sub(r'[-_.]+', '-', n).lower()


# --- Lockfiles → [(OSV ecosystem, name, version, dev)] ---------------------------------

def npm_lock(t):
    d = json.loads(t)
    out = []
    for path, p in (d.get('packages') or {}).items():
        if not path or not isinstance(p, dict) or p.get('link'):
            continue
        name = p.get('name') or path.split('node_modules/')[-1]
        if p.get('version'):
            out.append(('npm', name, p['version'], bool(p.get('dev'))))
    if not out:                                   # lockfileVersion 1
        def walk(deps):
            for n, p in (deps or {}).items():
                if isinstance(p, dict) and p.get('version'):
                    out.append(('npm', n, p['version'], bool(p.get('dev'))))
                    walk(p.get('dependencies'))
        walk(d.get('dependencies'))
    return out


def pnpm_lock(t):
    out = []
    for m in re.finditer(r"^\s{2}'?/?((?:@[^/@\s]+/)?[^@/\s:']+)@(\d[^(:'\s]*)", t, re.M):
        out.append(('npm', m.group(1), m.group(2), False))
    return out


def yarn_lock(t):
    out = []
    for block in re.split(r'\n\s*\n', t):
        m = re.match(r'^"?((?:@[^@/\s]+/)?[^@\s"]+)@', block.strip())
        w = re.search(r'^\s+version:?\s+"?([^"\s]+)"?', block, re.M)
        if m and w:
            out.append(('npm', m.group(1), w.group(1), False))
    return out


def deno_lock(t):
    d = json.loads(t)
    npm = d.get('npm') or (d.get('packages') or {}).get('npm') or {}
    out = []
    for key in npm:
        m = re.match(r'^((?:@[^@/]+/)?[^@]+)@([^_]+)', key)
        if m:
            out.append(('npm', m.group(1), m.group(2), False))
    return out


def toml_lock(t):
    if tomllib is None:
        return []
    d = tomllib.loads(t)
    out = []
    for p in d.get('package') or []:
        if p.get('name') and p.get('version'):
            source = p.get('source') or {}
            if isinstance(source, dict) and (source.get('editable') or source.get('virtual')
                                             or source.get('type') in ('directory', 'git', 'file')):
                continue                           # local / git package — not in OSV
            out.append(('PyPI', norm_py(p['name']), p['version'], p.get('category') == 'dev'))
    return out


def pipfile_lock(t):
    d = json.loads(t)
    out = []
    for group, dev in (('default', False), ('develop', True)):
        for n, p in (d.get(group) or {}).items():
            w = (p or {}).get('version', '')
            if w.startswith('=='):
                out.append(('PyPI', norm_py(n), w[2:], dev))
    return out


def requirements(t):
    out = []
    for l in t.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s;#,]+)', l)
        if m:
            out.append(('PyPI', norm_py(m.group(1)), m.group(3), False))
    return out


READERS = [
    (re.compile(r'(^|/)(package-lock|npm-shrinkwrap)\.json$'), npm_lock),
    (re.compile(r'(^|/)pnpm-lock\.yaml$'), pnpm_lock),
    (re.compile(r'(^|/)yarn\.lock$'), yarn_lock),
    (re.compile(r'(^|/)deno\.lock$'), deno_lock),
    (re.compile(r'(^|/)(poetry|uv)\.lock$'), toml_lock),
    (re.compile(r'(^|/)Pipfile\.lock$'), pipfile_lock),
    (re.compile(r'(^|/)requirements[^/]*\.txt$'), requirements),
]


def lockfiles(root):
    try:
        r = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True, timeout=30)
        files = r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        files = []
    for p in files:
        for pattern, reader in READERS:
            if pattern.search(p):
                yield p, reader
                break


# --- OSV -------------------------------------------------------------------------------

def severity_of(v):
    s = ((v.get('database_specific') or {}).get('severity') or '').upper()
    if s == 'MODERATE':
        s = 'MEDIUM'
    if s:
        return s
    for a in v.get('affected') or []:
        s = str(((a.get('ecosystem_specific') or {}).get('severity')) or '').upper()
        if s:
            return 'MEDIUM' if s == 'MODERATE' else s
    return ''


def fixes(v, eco, name):
    out = []
    for a in v.get('affected') or []:
        pk = a.get('package') or {}
        n = norm_py(pk.get('name', '')) if eco == 'PyPI' else pk.get('name')
        if pk.get('ecosystem') != eco or n != name:
            continue
        for r in a.get('ranges') or []:
            for e in r.get('events') or []:
                if e.get('fixed'):
                    out.append(e['fixed'])
    return out


def version_key(w):
    """A comparable tuple from a version (1.10.2 > 1.9.0; suffixes like rc/post pushed down)."""
    parts = []
    for c in re.split(r'[.+-]', str(w)):
        m = re.match(r'^(\d+)(.*)$', c)
        parts.append((int(m.group(1)), m.group(2)) if m else (-1, c))
    return parts


def newer(fixes_, version):
    """Only fixes newer than the installed version — OSV lists them per branch (1.88.6, 1.89.7…),
    and a branch older than the installed version cannot be used."""
    kv = version_key(version)
    return sorted({f for f in fixes_ if version_key(f) > kv}, key=version_key)


def group(ids, details):
    """The same bug is sometimes in OSV under two ids (GHSA and PYSEC with the same CVE). Merges
    by aliases; the group's representative is the entry with a severity rating."""
    groups = []
    for vid in ids:
        v = details.get(vid) or {'id': vid}
        names = {vid, *(v.get('aliases') or [])}
        for g in groups:
            if g['names'] & names:
                g['names'] |= names
                g['entries'].append(v)
                break
        else:
            groups.append({'names': names, 'entries': [v]})
    for g in groups:
        g['entries'].sort(key=lambda v: (not severity_of(v), not v['id'].startswith('GHSA'), v['id']))
    return groups


RANK = {'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, '': 0}


def main():
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    sys.stdin.read()
    packages = {}                          # (eco, name, version) → (file, dev)
    for path, reader in lockfiles(root):
        try:
            with open(os.path.join(root, path), encoding='utf-8') as f:
                found = reader(f.read())
        except (OSError, ValueError, Exception):
            emit(file=path, line=None, rule='unreadable-lockfile', severity='warn',
                 message='could not read the lockfile — its dependencies were not checked',
                 content_fingerprint=path)
            continue
        for eco, name, version, dev in found:
            k = (eco, name, version)
            if k not in packages or (packages[k][1] and not dev):
                packages[k] = (path, dev)      # production wins over development
    if not packages:
        return 0

    cache = Cache('osv')
    keys = sorted(packages)
    vulns = {}                             # (eco, name, version) → [id]
    to_query = []
    for k in keys:
        z = cache.get('q:' + '|'.join(k))
        if z is None:
            to_query.append(k)
        else:
            vulns[k] = z
    try:
        for i in range(0, len(to_query), 500):
            batch = to_query[i:i + 500]
            _, d = fetch(f'{address("osv")}/v1/querybatch', {'queries': [
                {'package': {'ecosystem': e, 'name': n}, 'version': w} for e, n, w in batch]}, timeout=30)
            for k, result in zip(batch, (d or {}).get('results') or []):
                ids = sorted({v['id'] for v in (result or {}).get('vulns') or [] if v.get('id')})
                vulns[k] = ids
                cache.put('q:' + '|'.join(k), ids, 12 * 3600)
    except NoNetwork as e:
        cache.save()
        emit(file=next(iter(packages.values()))[0], line=None, rule='not-checked', severity='warn',
             message=f'OSV database unreachable — {len(to_query)} packages not checked ({str(e)[:80]})',
             content_fingerprint='not-checked')
        return 0

    details = {}

    def download(vid):
        z = cache.get('v:' + vid)
        if z is not None:
            return vid, z, False
        try:
            _, z = fetch(f'{address("osv")}/v1/vulns/{vid}')
        except NoNetwork:
            z = None
        return vid, z, True

    with ThreadPoolExecutor(max_workers=8) as ex:
        for vid, z, fresh in ex.map(download, sorted({i for ids in vulns.values() for i in ids})):
            if z and fresh:
                cache.put('v:' + vid, z, 12 * 3600)
            details[vid] = z or {'id': vid}
    cache.save()

    # One finding per package: the decision is one anyway (bump the version or accept the
    # risk), and pyjwt with 12 vulnerabilities is not 12 problems. The fingerprint covers the
    # vulnerability list — a new vulnerability in the same package blocks again despite an exception.
    for k in keys:
        eco, name, version = k
        path, dev = packages[k]
        groups = group(vulns.get(k, []), details)
        if not groups:
            continue
        descriptions, fixed, max_sev, blocks = [], set(), '', False
        for g in sorted(groups, key=lambda g: -RANK.get(severity_of(g['entries'][0]), 0)):
            v = g['entries'][0]
            sev = severity_of(v)
            fix = newer([f for w in g['entries'] for f in fixes(w, eco, name)], version)
            if RANK.get(sev, 0) > RANK.get(max_sev, 0):
                max_sev = sev
            if fix:
                fixed.add(fix[0])
            if sev in SERIOUS and fix and not dev:
                blocks = True
            cve = next((a for a in sorted(g['names']) if a.startswith('CVE-')), v['id'])
            descriptions.append(f'{cve} ({sev.lower() or "unrated"}{"" if fix else ", no fix"})')
        target = max(fixed, key=version_key) if fixed else ''
        message = (f'{name} {version}: {len(groups)} vuln. (highest: {max_sev.lower() or "unrated"})'
                   + (f' — bump to ≥ {target}' if target else ' — no fixed version')
                   + (' — development dependency' if dev else '')
                   + ': ' + ', '.join(descriptions[:6]) + (' …' if len(descriptions) > 6 else ''))
        fp = hashlib.sha1('|'.join(sorted(n for g in groups for n in g['names'])).encode()).hexdigest()[:12]
        emit(file=path, line=None, rule='vulnerability', severity='block' if blocks else 'warn',
             message=message, content_fingerprint=f'{eco}:{name}:{version}:{fp}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
