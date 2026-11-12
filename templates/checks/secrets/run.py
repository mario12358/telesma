#!/usr/bin/env python3
"""Check `secrets` — list of files on stdin, findings as JSON lines on stdout.

The secret's content never leaves this process: a finding carries the rule, the place, the
LENGTH of the value and a fingerprint — not one character of the value itself.

The runner hands this module every file in scope (`filter: none` in CHECK.md): no size limit,
lockfiles, minified bundles and `.claude/` included. Files are read as a stream and long lines
in overlapping windows, so a key on a 2 MB line of JSON is a key like any other.
"""
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# A token boundary that also stops at `_` and `-`: `MY_ghp_…` is not a GitHub token, but `"ghp_…"` is.
B = r'(?<![A-Za-z0-9_-])'
# (rule, pattern, severity) — formats with a low false-positive rate block
PATTERNS = [
    ('private-key', r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----', 'block'),
    ('aws-access-key', r'(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])', 'block'),
    ('github-token', B + r'(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})', 'block'),
    ('gitlab-token', B + r'glpat-[A-Za-z0-9_-]{20,}', 'block'),
    ('slack-token', B + r'xox[abposr]-[A-Za-z0-9-]{10,}', 'block'),
    ('slack-webhook', r'https://hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/[A-Za-z0-9]{20,}', 'block'),
    ('anthropic-key', B + r'sk-ant-[A-Za-z0-9_-]{20,}', 'block'),
    ('openai-key', B + r'sk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}', 'block'),
    ('google-api-key', B + r'AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])', 'block'),
    ('stripe-live-key', B + r'(?:[rs]k_live_[0-9a-zA-Z]{20,}|whsec_[0-9a-zA-Z]{24,})', 'block'),
    ('huggingface-token', B + r'hf_[A-Za-z0-9]{30,}', 'block'),
    ('npm-token', B + r'npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])', 'block'),
    ('pypi-token', B + r'pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}', 'block'),
    ('sendgrid-key', B + r'SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}', 'block'),
    ('digitalocean-token', B + r'do[opr]_v1_[a-f0-9]{64}', 'block'),
    ('jwt', r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', 'warn'),
]
COMPILED = [(r, re.compile(w), g) for r, w, g in PATTERNS]
BLOCKING = [(r, w) for r, w, g in COMPILED if g == 'block' and r != 'private-key']

# `scheme://user:password@host` — a login inside an address (database URL, broker, registry)
URL_CREDENTIALS = re.compile(r'''(?<![A-Za-z0-9])([a-z][a-z0-9+.-]{1,20})://([^\s:/@"'<>{}$]+):([^\s:/@"'<>{}$]{3,})@'''
                             r'''([A-Za-z0-9._-]+)''')
LOCAL_HOST = re.compile(r'^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|host\.docker\.internal|[A-Za-z0-9_-]+)$|'
                        r'(^|\.)(example\.(com|org|net)|test|local|invalid)$', re.I)

# A name that says "this holds a secret", with any prefix or suffix: `password`, `DB_PASSWORD`,
# `aws_secret_access_key`, `SECRET_KEY`, `stripe.apiKey`. The old rule anchored the word with
# `\b`, and `_` is a word character — so only the bare word ever matched.
# `haslo` is the Polish word for "password" — kept as detection data for codebases with Polish identifiers.
SECRET_WORD = (r'(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|access[_-]?token|auth[_-]?token|'
               r'client[_-]?secret|private[_-]?key|token|haslo|has\u0142o)')
# What may follow the word in a name (`SECRET_KEY`, `aws_secret_access_key`, `secret_key_base`) —
# a closed list, so `tokenizer` and `password_field` are not secrets. What stands BEFORE the word
# is read backwards from the match in plain Python: a pattern for it would backtrack on long lines.
NAME_TAIL = r'(?:[_-]?(?:access[_-]?key|key|value|secret|token|password|base|string|plain|raw))*'
ASSIGNMENT = re.compile(r'(?i)(' + SECRET_WORD + NAME_TAIL + r''')["']?\s*[:=]\s*["']([^"'\s]{8,})["']''')
# In an environment file the value stands bare: `PASSWORD=Tr0ub4dor3horse`
ENV_ASSIGNMENT = re.compile(r'(?i)^\s*(?:export\s+)?[A-Za-z0-9_.-]{0,80}?(' + SECRET_WORD + NAME_TAIL
                            + r''')\s*=\s*([^\s"'#$]{8,})\s*$''')
NAME_CHARS = re.compile(r'[A-Za-z0-9_.-]{0,80}$')
ENV_FILE = re.compile(r'(^|/)[^/]*\.env(\.[\w-]+)?$')

# Values that look like placeholders, not secrets
PLACEHOLDER = re.compile(r'(?i)^(?:x+|\*+|changeme|change[_-]?me|example|sample|dummy|placeholder|'
                         r'your[_-].*|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|test|testing|fake|secret|password|pass|passwd|pwd|todo|none|null|'
                         r'true|false|undefined|required|optional|string|redacted)$')
# Deliberately without `test.*`: "Test1234Password" is a classic weak password, not a placeholder
# (the first live test let it through silently).
# A value that is a reference, not a secret: an address, a path, a dotted name
REFERENCE = re.compile(r'^(?:https?://|/|\./|~/|[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+$)')

# Key from documentation / a test fixture: a marker in the value or too few distinct characters
FAKE = re.compile(r'(?i)example|test|fake|dummy|sample|placeholder|x{5}|0{5}|1234|abcd')
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e|fixtures?)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
# A test-file NAME is a claim; this is the evidence. Without it a file called `handler_spec.py`
# or one put into `src/e2e/` is production code and gets no exemption.
TEST_EVIDENCE = re.compile(r'\bimport\s+(?:pytest|unittest)\b|\bfrom\s+(?:pytest|unittest)\b|@pytest\.|\bdef\s+test_\w*\s*\(|'
                           r'\b(?:describe|it|test)\s*\(\s*[\'"`]|\bexpect\s*\(|\bfunc\s+Test\w+\s*\(|#\[(?:test|cfg\(test\))\]|'
                           r'@Test\b|\bRSpec\.|\bassert_\w+\s*\(|(^|/)fixtures?/')
BASE64_LINE = re.compile(r'^[A-Za-z0-9+/=]{40,}$')
BASE64_LITERAL = re.compile(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,400}={0,2}(?![A-Za-z0-9+/=])')
KEY_HEADER = re.compile(r'^(Version|Comment|Proc-Type|DEK-Info|Hash|Charset)\s*:', re.I)
ADJACENT_LITERALS = re.compile(r'''["'`]\s*(?:\+|\\|\.|,)?\s*["'`]''')

SECRET_FILE = re.compile(r'(^|/)([^/]*\.env(\.[\w-]+)?|id_(rsa|dsa|ecdsa|ed25519)|[^/]*\.(pem|p12|pfx|key|keystore|jks)|'
                         r'credentials\.json|secrets?\.(ya?ml|json|toml))$')
EXAMPLE_FILE = re.compile(r'(?i)(\.|_|-)(example|sample|template|dist|defaults?)(\.|$)')
WINDOW = 20000          # a longer physical line is scanned in windows of this size
OVERLAP = 600           # … overlapping by more than the longest token


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def hidden(rule, value):
    """The only thing a message says about a value: how long it is."""
    return f'{rule} ({len(value)} characters, content hidden)'


def file_names(files):
    for p in files:
        if SECRET_FILE.search(p) and not EXAMPLE_FILE.search(os.path.basename(p)):
            emit(file=p, line=None, rule='secret-file', severity='block',
                 message='file named like a secret (key / .env / credentials) — do not commit it, '
                         'add it to .gitignore; keep a template as *.example',
                 content_fingerprint=fingerprint('file:' + p))


def chunks(f):
    """(line number, text) for every line of a binary stream; a long line comes in overlapping windows."""
    for nr, raw in enumerate(f, 1):
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if len(line) <= WINDOW:
            yield nr, line
            continue
        for start in range(0, len(line), WINDOW - OVERLAP):
            yield nr, line[start:start + WINDOW]


def with_lookahead(items, n=6):
    """(nr, line, [the next n lines]) — a private key's body and a string continued on the next line."""
    buffer = []
    for item in items:
        buffer.append(item)
        if len(buffer) > n:
            nr, line = buffer.pop(0)
            yield nr, line, [x[1] for x in buffer]
    while buffer:
        nr, line = buffer.pop(0)
        yield nr, line, [x[1] for x in buffer]


def key_body(line, following):
    """The first line of key material after a BEGIN header, or None (the header alone — in
    documentation, in a message — is not a key). Quotes, `\\n` and concatenation around the
    body do not hide it; armour headers (Version:, Proc-Type:) and blank lines are skipped."""
    m = re.search(r'KEY(?: BLOCK)?-----\s*(?:\\n|\\r)*\s*([A-Za-z0-9+/=]{40,})', line)
    if m:
        return m.group(1)
    for l in following:
        cleaned = re.sub(r'\\[nr]|["\'`\s,+()]', '', l)
        if not cleaned or KEY_HEADER.match(l.strip().strip('"\'')):
            continue
        return cleaned if BASE64_LINE.match(cleaned) else None
    return None


def plausible(value):
    return not FAKE.search(value) and len(set(value)) >= 6


def decoded_tokens(line):
    """Text hidden one layer deep: base64 literals that decode to printable ASCII."""
    for m in BASE64_LITERAL.finditer(line):
        try:
            t = base64.b64decode(m.group(0) + '=' * (-len(m.group(0)) % 4), validate=True)
        except (binascii.Error, ValueError):
            continue
        if t and all(32 <= c < 127 for c in t):
            yield t.decode('ascii')


def scan_line(p, nr, line, following, test, env_file, found):
    """Findings of one line into `found` [(rule, severity, value, fingerprint source)]."""
    hit = set()
    for rule, pattern, severity in COMPILED:
        for m in pattern.finditer(line):
            value = m.group(0)
            if rule == 'private-key':
                value = key_body(line, following)
                if not value:
                    continue
            elif severity == 'block' and not plausible(value):
                continue
            hit.add(rule)
            found.append((rule, severity, value, value))
    # The same formats one step away: a literal split into pieces (`"AKIA" + "…"`, also across
    # the line end) and a literal wrapped in base64
    after = following[0].strip() if following else ''
    joined = ADJACENT_LITERALS.sub('', line + after)
    hidden_in = [('split', joined)] if joined != line + after or after else []
    hidden_in += [('base64', t) for t in decoded_tokens(line)]
    for how, text in hidden_in:
        for rule, pattern in BLOCKING:
            if rule in hit:
                continue
            m = pattern.search(text)
            if m and plausible(m.group(0)) and (how == 'base64' or (m.group(0) not in line and m.group(0) not in after)):
                hit.add(rule)
                found.append((f'{rule}-{how}', 'block', m.group(0), m.group(0)))
    for m in URL_CREDENTIALS.finditer(line):
        scheme, user, password, host = m.groups()
        if PLACEHOLDER.match(password) or FAKE.search(password) or password.lower() == user.lower():
            continue
        local = bool(LOCAL_HOST.search(host)) or test
        found.append(('url-credentials', 'warn' if local else 'block', password,
                      f'url:{scheme}://{user}@{host}'.lower()))
    m = ASSIGNMENT.search(line) or (ENV_ASSIGNMENT.match(line) if env_file else None)
    if m and not test:
        name = NAME_CHARS.search(line[:m.start(1)]).group(0) + m.group(1)
        value = m.group(2)
        if not (PLACEHOLDER.match(value) or REFERENCE.match(value)):
            # the fingerprint is the NAME, not the value: a short hash of a weak password can be
            # guessed from a dictionary, and the exceptions file is committed
            found.append(('secret-assignment', 'warn', value, 'name:' + name.lower()))


def builtin(root, files, skip):
    """`skip` = {(file, line)} already reported by gitleaks."""
    for p in files:
        try:
            f = open(os.path.join(root, p), 'rb')
        except OSError:
            continue
        with f:
            head = f.read(65536)
            f.seek(0)
            test = bool(TEST_FILE.search(p)) and bool(TEST_EVIDENCE.search(p + '\n' + head.decode('utf-8', 'replace')))
            env_file = bool(ENV_FILE.search(p))
            seen = set()
            for nr, line, following in with_lookahead(chunks(f)):
                if (p, nr) in skip:
                    continue
                found = []
                scan_line(p, nr, line, following, test, env_file, found)
                for rule, severity, value, source in found:
                    if (nr, rule, source) in seen:
                        continue                 # the same token in two overlapping windows
                    seen.add((nr, rule, source))
                    emit(file=p, line=nr, rule=rule, severity=severity, message=hidden(rule, value),
                         content_fingerprint=fingerprint(source))


def with_gitleaks(root, files):
    """Copies the files into a temporary directory and scans it with a single call.
    Returns {(file, line)} of what it reported, or None when gitleaks could not be used."""
    reported = set()
    with tempfile.TemporaryDirectory(prefix='telesma-secrets-') as tmp:
        for p in files:
            target = os.path.join(tmp, p)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                shutil.copyfile(os.path.join(root, p), target)
            except OSError:
                pass
        report = os.path.join(tmp, '.report.json')
        # The project's configuration (rules, allowlist) and its .gitleaksignore — the scan runs
        # from the temporary directory, so gitleaks would not find them on its own. They can only
        # silence gitleaks: the built-in rules run on every line gitleaks did not report.
        project = []
        if os.path.isfile(os.path.join(root, '.gitleaks.toml')):
            project += ['--config', os.path.join(root, '.gitleaks.toml')]
        if os.path.isfile(os.path.join(root, '.gitleaksignore')):
            project += ['--gitleaks-ignore-path', os.path.join(root, '.gitleaksignore')]
        for args in (['dir', tmp], ['detect', '--no-git', '--source', tmp]):
            try:
                r = subprocess.run(['gitleaks', *args, *project, '--report-format', 'json', '--report-path', report,
                                    '--exit-code', '0', '--no-banner', '--redact'],
                                   capture_output=True, text=True, timeout=240)
            except (OSError, subprocess.TimeoutExpired):
                return None
            if r.returncode == 0 and os.path.exists(report):
                break
        else:
            return None
        try:
            with open(report, encoding='utf-8') as f:
                results = json.load(f) or []
        except (OSError, ValueError):
            return None
        for w in results:
            path = os.path.relpath(w.get('File', ''), tmp)
            # with --redact the Secret field is masked; the fingerprint comes from the original line
            nr = w.get('StartLine')
            try:
                with open(os.path.join(root, path), encoding='utf-8', errors='replace') as f:
                    content = f.read().splitlines()[nr - 1] if nr else ''
            except (OSError, IndexError):
                content = w.get('Fingerprint', '')
            emit(file=path, line=nr, rule='gitleaks:' + w.get('RuleID', '?'), severity='block',
                 message=f'{w.get("Description") or w.get("RuleID")} (content hidden)',
                 content_fingerprint=fingerprint(content.strip()))
            reported.add((path, nr))
    return reported


def main():
    if '--check' in sys.argv:
        if shutil.which('gitleaks'):
            r = subprocess.run(['gitleaks', 'version'], capture_output=True, text=True)
            print(f'ok: gitleaks {r.stdout.strip()} + built-in rules')
        else:
            # Built-in mode is a supported mode, not a misconfiguration — no startup warning;
            # the setup wizard and the docs mention gitleaks as an optional upgrade.
            print('ok: built-in rules (gitleaks not installed)')
        return 0
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l for l in sys.stdin.read().split('\n') if l.strip()]
    if not files:
        return 0
    file_names(files)
    reported = (with_gitleaks(root, files) if shutil.which('gitleaks') else None) or set()
    builtin(root, files, reported)
    return 0


if __name__ == '__main__':
    sys.exit(main())
