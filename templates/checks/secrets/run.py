#!/usr/bin/env python3
"""Check `secrets` — list of files on stdin, findings as JSON lines on stdout.

The secret's content never leaves this process: the output carries only its fingerprint.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# (rule, pattern, severity) — formats with a low false-positive rate block
PATTERNS = [
    ('private-key', r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----', 'block'),
    ('aws-access-key', r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b', 'block'),
    ('github-token', r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b', 'block'),
    ('gitlab-token', r'\bglpat-[A-Za-z0-9_-]{20,}\b', 'block'),
    ('slack-token', r'\bxox[abposr]-[A-Za-z0-9-]{10,}\b', 'block'),
    ('anthropic-key', r'\bsk-ant-[A-Za-z0-9_-]{20,}\b', 'block'),
    ('openai-key', r'\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}\b', 'block'),
    ('google-api-key', r'\bAIza[0-9A-Za-z_-]{35}\b', 'block'),
    ('stripe-live-key', r'\b[rs]k_live_[0-9a-zA-Z]{20,}\b', 'block'),
    ('jwt', r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', 'warn'),
    # `haslo` is the Polish word for "password" — kept as detection data for codebases
    # with Polish identifiers
    ('secret-assignment',
     r'''(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|haslo|has\u0142o)\b["']?\s*[:=]\s*["']([^"'\s]{8,})["']''',
     'warn'),
]
COMPILED = [(r, re.compile(w), g) for r, w, g in PATTERNS]

# Values that look like placeholders, not secrets
PLACEHOLDER = re.compile(r'(?i)^(?:x+|\*+|changeme|change[_-]?me|example|sample|dummy|placeholder|'
                         r'your[_-].*|<.*>|\$\{.*\}|\{\{.*\}\}|test|testing|fake|secret|password|todo|none|null)$')
# Deliberately without `test.*`: "Test1234Password" is a classic weak password, not a placeholder
# (the first live test let it through silently). Test files are skipped entirely, so this
# adds no noise.

# Key from documentation / a test fixture: a marker in the value or too few distinct characters
FAKE = re.compile(r'(?i)example|test|fake|dummy|sample|placeholder|x{5}|0{5}|1234|abcd')
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e|fixtures?)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
BASE64 = re.compile(r'^[A-Za-z0-9+/=]{40,}$')

SECRET_FILE = re.compile(r'(^|/)(\.env(\.[\w-]+)?|id_(rsa|dsa|ecdsa|ed25519)|[^/]*\.(pem|p12|pfx|key|keystore|jks)|'
                         r'credentials\.json|secrets?\.(ya?ml|json|toml))$')
EXAMPLE_FILE = re.compile(r'(?i)(\.|_|-)(example|sample|template|dist|defaults?)(\.|$)')


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def is_binary(data):
    return b'\0' in data[:8192]


def file_names(files):
    for p in files:
        if SECRET_FILE.search(p) and not EXAMPLE_FILE.search(os.path.basename(p)):
            emit(file=p, line=None, rule='secret-file', severity='block',
                 message='file named like a secret (key / .env / credentials) — do not commit it, '
                         'add it to .gitignore; keep a template as *.example',
                 content_fingerprint=fingerprint('file:' + p))


def builtin(root, files):
    for p in files:
        try:
            with open(os.path.join(root, p), 'rb') as f:
                data = f.read()
        except OSError:
            continue
        if is_binary(data):
            continue
        test = bool(TEST_FILE.search(p))
        lines = data.decode('utf-8', 'replace').splitlines()
        for nr, line in enumerate(lines, 1):
            if len(line) > 4000:
                continue
            for rule, pattern, severity in COMPILED:
                m = pattern.search(line)
                if not m:
                    continue
                value = m.group(1) if m.groups() else m.group(0)
                if rule == 'secret-assignment' and (test or PLACEHOLDER.match(value) or
                                                    re.search(r'(?i)env|getenv|process\.|os\.', line)):
                    continue
                if rule == 'private-key':
                    # the header alone (documentation, a message) is not a key — what counts is the body below it
                    following = lines[nr].strip() if nr < len(lines) else ''
                    if not BASE64.match(following) and not re.search(r'KEY-----\s*(\\n)?[A-Za-z0-9+/=]{40,}', line):
                        continue
                    value = following or line
                elif severity == 'block' and (FAKE.search(value) or len(set(value)) < 12):
                    continue
                emit(file=p, line=nr, rule=rule, severity=severity,
                     message=f'{rule}: {value[:4]}… (content hidden)',
                     content_fingerprint=fingerprint(value))


def with_gitleaks(root, files):
    """Copies the files into a temporary directory and scans it with a single call.
    Returns False when gitleaks could not be used (then the built-in mode runs)."""
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
        # from the temporary directory, so gitleaks would not find them on its own
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
                return False
            if r.returncode == 0 and os.path.exists(report):
                break
        else:
            return False
        try:
            with open(report, encoding='utf-8') as f:
                results = json.load(f) or []
        except (OSError, ValueError):
            return False
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
    return True


def main():
    if '--check' in sys.argv:
        if shutil.which('gitleaks'):
            r = subprocess.run(['gitleaks', 'version'], capture_output=True, text=True)
            print(f'ok: gitleaks {r.stdout.strip()}')
        else:
            # Built-in mode is a supported mode, not a misconfiguration — no startup warning;
            # the setup wizard and the docs mention gitleaks as an optional upgrade.
            print('ok: built-in rules (gitleaks not installed)')
        return 0
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    if not files:
        return 0
    file_names(files)
    if not (shutil.which('gitleaks') and with_gitleaks(root, files)):
        builtin(root, files)
    return 0


if __name__ == '__main__':
    sys.exit(main())
