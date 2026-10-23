#!/usr/bin/env python3
"""Check `weakenings` — list of files on stdin, findings as JSON lines on stdout."""
import hashlib
import json
import os
import re
import sys

MARKER = re.compile(r'telesma:\s*weakening\b(.*)$', re.I)
MARKER_FULL = re.compile(r'^\s+([A-Za-z0-9][\w.-]*)\s*[—–:-]+\s*(\S.{3,})$')
MUTANT = re.compile(r'\bMUTANT\b')

# (rule, pattern, message) — typical weakenings; without a marker they only warn
PATTERNS = [
    ('tls-disabled', r'verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED'
                     r'|InsecureSkipVerify\s*:\s*true|ssl\.CERT_NONE|check_hostname\s*=\s*False'
                     r'|--insecure\b|\bcurl\b[^\n]*\s-k\b',
     'TLS verification disabled'),
    ('debug-enabled', r'^\s*DEBUG\s*=\s*True\b|\.run\([^)]*debug\s*=\s*True|app\.debug\s*=\s*True',
     'debug mode permanently enabled'),
    ('csrf-disabled', r'@csrf_exempt|csrf\s*[:=]\s*(False|false)|disable_csrf|csrf_protect\s*=\s*False',
     'CSRF protection disabled'),
    ('security-bypass', r'(?i)\b(skip|bypass|disable|disabled|no)[_-]?(auth|authn|authz|login|mfa|2fa|totp|'
                        r'otp|captcha|csrf|ratelimit|rate_limit|permission|permissions|verification)\b',
     'security bypass in an identifier'),
    ('bypass-token', r'(?i)\b\w*(dev|debug|test|local)[_-]?bypass\w*|\bbypass[_-]?(token|key|secret|user|login)\w*',
     'bypass token / mode (usually environment-dependent — a wrong variable in production opens the door)'),
    ('cors-any-origin', r'''Access-Control-Allow-Origin["']?\s*[:,=]\s*["']\*|origin\s*:\s*["']\*["']''',
     'CORS for any origin'),
    # `kod` is Polish for "code" — kept as detection data for codebases with Polish identifiers
    ('secret-in-response', r'(?i)(totp|otp|mfa)[\w.]*\s*(code|kod)\b[^\n]*(render|template|response|json|print|log)',
     'second-factor code ends up in a response / log'),
]
COMPILED = [(r, re.compile(w), o) for r, w, o in PATTERNS]
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
CODE = re.compile(r'\.(py|js|jsx|ts|tsx|mjs|cjs|java|kt|go|rb|php|rs|cs|swift|scala|sh|sql|ya?ml|toml|json|ini|cfg|conf|env|html|vue|svelte)$|(^|/)(Dockerfile|Caddyfile|Makefile)$')


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def main():
    point = os.environ.get('TELESMA_POINT', 'commit')
    open_ = {}     # weakening id → [(file, line, reason)] — one weakening, many places
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    for p in files:
        if not CODE.search(p):
            continue
        try:
            with open(os.path.join(root, p), encoding='utf-8', errors='replace') as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        test = bool(TEST_FILE.search(p))
        hits = {}
        for nr, line in enumerate(lines, 1):
            if len(line) > 4000:
                continue
            if MUTANT.search(line):
                emit(file=p, line=nr, rule='mutant', severity='block',
                     message='MUTANT in code — a mutation test was not reverted',
                     content_fingerprint=fingerprint(line.strip()))
            m = MARKER.search(line)
            if m:
                rest = m.group(1).rstrip(' */->#').rstrip()
                pm = MARKER_FULL.match(rest)
                if not pm:
                    emit(file=p, line=nr, rule='incomplete-marker', severity='block',
                         message='weakening marker without an id or without a reason — '
                                 'format: telesma: weakening <id> — <reason and removal condition>',
                         content_fingerprint=fingerprint(line.strip()))
                elif point in ('release', 'phase', 'ci'):
                    open_.setdefault(pm.group(1), []).append((p, nr, pm.group(2)))
                continue
            if test:
                continue
            for rule, pattern, message in COMPILED:
                if pattern.search(line):
                    previous = lines[nr - 2] if nr > 1 else ''
                    if MARKER.search(previous):
                        break        # marked on the line above — the register already has it
                    hits.setdefault(rule, []).append((nr, line, message))
                    break
        # A pattern once per file: a mechanism mentioned on 15 lines is one weakening,
        # not fifteen — the rest goes as a counter
        for rule, found in hits.items():
            nr, line, message = found[0]
            more = f' (+{len(found) - 1} more in the file)' if len(found) > 1 else ''
            emit(file=p, line=nr, rule=rule, severity='warn',
                 message=f'{message} without a marker{more} — remove it or mark it '
                         f'"telesma: weakening <id> — <reason>"',
                 content_fingerprint=rule)
    # One weakening = one finding, even when the marker stands in five files (module,
    # mount point, test, guard exception lists — that is how Telesma marked one on a production
    # project). The fingerprint is the id alone, without the file: a deliberate release with
    # a weakening is one exception, not five.
    for wid, places in sorted(open_.items()):
        p, nr, reason = places[0]
        where = ', '.join(f'{m[0]}:{m[1]}' for m in places[1:4]) + (' …' if len(places) > 4 else '')
        also = f'; also in: {where}' if len(places) > 1 else ''
        if point == 'release':
            emit(file=p, line=nr, rule='open-weakening', severity='block', file_fingerprint=False,
                 message=f'open weakening "{wid}" ({reason[:120]}){also} — remove it before the release '
                         f'(all markers) or ask the human for an exception',
                 content_fingerprint=wid)
        else:
            emit(file=p, line=nr, rule='open-weakening', severity='warn', file_fingerprint=False,
                 message=f'open weakening "{wid}" ({len(places)} places) — it will block the release',
                 content_fingerprint=wid)
    return 0


if __name__ == '__main__':
    sys.exit(main())
