#!/usr/bin/env python3
"""Check `sast` — file list on stdin, JSON findings one per line on stdout.

With semgrep in PATH: `p/owasp-top-ten` + `p/security-audit` + a language pack for the extensions
present on input. Without it (or when it does not finish in time / has no network for the rules) — built-in
mode: a dozen per-line patterns. The built-in patterns also run ALONGSIDE semgrep: they add lines
it did not report (semgrep with the OWASP pack does not know e.g. `tempfile.mktemp`).

The env `TELESMA_SEMGREP=none` disables semgrep (harness tests must give the same result with and without it).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
# Migrations and seeds build SQL from constants (table names in f-strings) — the SQL rule would only be noise there
MIGRATION = re.compile(r'(^|/)(migrations?|migrate|seeds?|alembic)/|\.sql$')
# A deliberate decision by the author — should be rare; the preferred marker is `telesma: weakening <id> — <reason>`,
# because it is a register visible at release time, while `nosec` disappears into the code
NOSEC = re.compile(r'(#|//|/\*)\s*(nosec|nosemgrep|noqa:\s*S\d*)\b')
COMMENT = re.compile(r'^\s*(#|//|/\*|\*|<!--)')
IMPORT = re.compile(r'^\s*(import\s|from\s+[\w.]+\s+import\s|require\()')

LANGUAGES = {'py': 'py', 'pyi': 'py',
             'js': 'js', 'jsx': 'js', 'ts': 'js', 'tsx': 'js', 'mjs': 'js', 'cjs': 'js', 'vue': 'js', 'svelte': 'js',
             'java': 'java', 'kt': 'java', 'scala': 'java', 'go': 'go', 'rb': 'rb', 'php': 'php', 'cs': 'cs',
             'html': 'template', 'htm': 'template', 'jinja': 'template', 'jinja2': 'template', 'j2': 'template',
             'ejs': 'template', 'hbs': 'template', 'njk': 'template', 'sql': 'sql'}
SEMGREP_PACK = {'py': 'p/python', 'js': 'p/javascript', 'go': 'p/golang'}
TS_EXTENSIONS = ('ts', 'tsx')

# --- Recognising the argument ------------------------------------------------------------

LITERAL = re.compile(r'''^\s*[rRuUbB]{0,2}(?:"""|\'\'\'|"|')''')
FSTRING = re.compile(r'''^\s*(?:[rRbB]?[fF][rRbB]?)(?:"""|\'\'\'|"|')''')
FSTRING_INSIDE = re.compile(r'''(?<![\w.])[fF](?:"|')[^"']*\{''')
CONCATENATION = re.compile(r'''["'`]\s*\+|\+\s*["'`]''')
FORMATTING = re.compile(r'''["']\s*%\s*[\(\w]|\.format\(''')
JS_TEMPLATE = re.compile(r'`[^`]*\$\{')


LITERALS = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`''')


def find(pattern, line):
    """The first match that does NOT start inside a string literal — `r'--exec(=|$)'`
    in the judge's regex is text, not a call (first run over the Telesma repo)."""
    spans = None
    for m in pattern.finditer(line):
        if spans is None:
            spans = [s.span() for s in LITERALS.finditer(line)]
        if not any(a < m.start() < b for a, b in spans):
            return m
    return None


def argument(line, pattern):
    """Text from the first parenthesis of a call matching the pattern (without the parenthesis), or None."""
    m = find(pattern, line)
    return line[m.end():] if m else None


def assembled(arg):
    """Whether the argument is ASSEMBLED from data: an f-string with {}, concatenation, % / .format, a template
    literal with ${}. A variable on its own is not — it may be a prepared query."""
    s = arg.lstrip()
    if FSTRING.match(s):
        return '{' in s
    if s.startswith('`'):
        return '${' in s
    if LITERAL.match(s):
        return bool(CONCATENATION.search(s) or FORMATTING.search(s))
    return False


def dynamic(arg):
    """Like `assembled`, but a variable / expression instead of a literal counts too (shell command,
    eval: there is no "prepared" variant there — a literal is the only safe one)."""
    s = arg.lstrip()
    if not s or s.startswith(')'):
        return False
    if FSTRING.match(s):
        return '{' in s
    if s.startswith('`'):
        return '${' in s
    if LITERAL.match(s) or s.startswith('['):
        return bool(CONCATENATION.search(s) or FORMATTING.search(s) or JS_TEMPLATE.search(s)
                    or FSTRING_INSIDE.search(s))
    return True


# `urllib.request.urlopen` is not request data; `requests.get` has an `s` before the dot, so \b filters it out
REQUEST_SOURCE = re.compile(r'(?<!urllib\.)\brequest\.(?!urlopen|Request\b)|\breq\.(?:params|query|body|headers)\b'
                            r'|\bparams\[|\bquery\[|\bbody\[|flask\.request|\bargs\.get\(')

# --- Blocking rules ------------------------------------------------------------------

SQL_CALL = re.compile(r'(?:\b|\.)(?:execute|executemany|executescript|raw|query)\(|(?<![\w.])text\(')
SQL_CALL_JS = re.compile(r'(?:\b|\.)(?:execute|query|raw|unsafe|\$queryRawUnsafe|\$executeRawUnsafe)\(')
SHELL_PY = re.compile(r'\bsubprocess\.(?:run|call|Popen|check_output|check_call|getoutput|getstatusoutput)\(')
SHELL_OS = re.compile(r'\bos\.(?:system|popen)\(')
SHELL_JS = re.compile(r'(?<![\w])(?:exec|execSync)\(')
# `(?<!def )`: a method definition `def exec(self, …)` is not a call (a false block on a production project,
# scripts/prod_probe.py); `self.exec(` / `docker.exec(` is already cut off by `(?<![\w.])`
EVAL_PY = re.compile(r'(?<![\w.])(?<!def )(?:eval|exec)\(')
EVAL_JS = re.compile(r'(?<![\w.])eval\(')
EVAL_JS_ALWAYS = re.compile(r'\bnew\s+Function\(|\b(?:setTimeout|setInterval)\(\s*["\']|\bvm\.runIn(?:New|This)Context\(')
DESERIALIZATION = re.compile(r'\b(?:pickle|_pickle|cPickle)\.loads?\(|\bcPickle\b|\bmarshal\.loads?\(|\bshelve\.open\('
                             r'|\bjsonpickle\.decode\(|\bunserialize\(|\bObjectInputStream\b')
YAML_LOAD = re.compile(r'\byaml\.(?:load|load_all|unsafe_load)\(')
YAML_SAFE = re.compile(r'SafeLoader|BaseLoader|safe_load')
PATH_SINK = re.compile(r'(?<![\w.])(?:open|Path)\(|\bsend_file\(|\bsendFile\(|\bFileResponse\(|\bos\.path\.join\('
                       r'|\breadFile(?:Sync)?\(|\bcreateReadStream\(|\bwriteFile(?:Sync)?\(')
PATH_SANITIZATION = re.compile(r'secure_filename\(|\bbasename\(|safe_join\(|realpath\(|send_from_directory\(')
PATH_RESOLVE_WITH_CHECK = re.compile(r'path\.resolve\(.*(?:startsWith|startswith|relative_to|is_relative_to)\(')

# --- Warning rules -----------------------------------------------------------------

XSS = re.compile(r'\.(?:innerHTML|outerHTML)\s*=(?!=)|\binsertAdjacentHTML\(|dangerouslySetInnerHTML|document\.write(?:ln)?\('
                 r'|\bv-html\s*=|\{@html\b|\|\s*safe\b|\bMarkup\(|\bmark_safe\(|\bbypassSecurityTrust\w+\(')
XSS_EMPTY = re.compile(r'''=\s*(["'`])\s*\1\s*;?\s*$''')
CORS_CREDENTIALS = re.compile(r'(?i)credentials\s*[:=]\s*true|supports_credentials\s*=\s*True|allow_credentials\s*=\s*True'
                              r'|Access-Control-Allow-Credentials["\']?\s*[:,=]\s*["\']?true')
CORS_ANY = re.compile(r'''(?i)origins?\s*[:=]\s*\[?\s*["']\*["']|origins?\s*[:=]\s*true\b'''
                      r'''|Access-Control-Allow-Origin["']?\s*[:,=]\s*["']\*|allow_origins?\s*=\s*\[?\s*["']\*''')
WEAK_HASH = re.compile(r'''\bhashlib\.(?:md5|sha1)\(|\bhashlib\.new\(\s*["'](?:md5|sha1)["']|\bcreateHash\(\s*["'](?:md5|sha1)["']'''
                       r'''|MessageDigest\.getInstance\(\s*["'](?:MD5|SHA-?1)["']|(?<![\w.])(?:md5|sha1)\(''')
PASSWORD_IN_LINE = re.compile(r'(?i)password|passwd|token|secret|\bpin\b')
RANDOMNESS = re.compile(r'(?<![\w.])random\.(?:random|randint|choice|choices|randrange|getrandbits|sample|uniform)\('
                        r'|Math\.random\(|(?<![\w.])(?:rand|mt_rand)\(')
SECRET_IN_LINE = re.compile(r'(?i)token|secret|session|\botp\b|nonce|password|reset|csrf|salt')
REDIRECT = re.compile(r'\b(?:redirect|RedirectResponse|HttpResponseRedirect)\(|\.(?:redirect)\(')
REDIRECT_SOURCE = re.compile(r'(?<!urllib\.)\brequest\.(?:args|form|values|GET|POST|query_params|headers|referrer|params|get\()'
                             r'|\breq\.(?:query|params|body|headers)\b|\bargs\.get\(|(?<![/"\'\w])next\b|\breturn_?to\b'
                             r'|\breturn_?url\b|\bredirect_?(?:to|url|uri)\b')
REDIRECT_SAFE = re.compile(r'url_has_allowed_host|is_safe_url|starts[wW]ith\(\s*["\']/|url_for\(|safe_redirect|validate_redirect|reverse\(')
STACKTRACE = re.compile(r'traceback\.format_exc(?:eption)?\(|\b(?:e|err|error|exc|exception|ex)\.stack\b')
RESPONSE = re.compile(r'\breturn\b|\bres\.(?:send|json|status|write|end)\(|\bjsonify\(|JSONResponse\(|HttpResponse\('
                      r'|\brender(?:_template)?\(|(?<![\w.])Response\(|\bctx\.body\b|\breply\.send\(')
JWT = re.compile(r'''verify_signature["']?\s*[:=]\s*False|algorithms\s*[:=]\s*\[[^\]]*["']none["']|\bjwt\.decode\(''')
JWT_VERIFY_FALSE = re.compile(r'\bverify\s*=\s*False')
XXE = re.compile(r'\betree\.(?:parse|fromstring|XML|iterparse|XMLParser)\(|\bminidom\.parse(?:String)?\(|\bxml\.sax\.'
                 r'|\bpulldom\.|\bexpatbuilder\b|\bresolve_entities\s*=\s*True|DocumentBuilderFactory\.newInstance\('
                 r'|\bSAXParserFactory\b|libxml_disable_entity_loader\(\s*false')
SSRF_SINK = re.compile(r'\brequests\.(?:get|post|put|patch|delete|head|request)\(|\bhttpx\.(?:get|post|put|patch|delete|request)\('
                       r'|(?<![\w.])fetch\(|\baxios(?:\.(?:get|post|put|patch|delete|request))?\(|\burlopen\(|\bgot(?:\.\w+)?\(')
TMP = re.compile(r'''\btempfile\.mktemp\(|(?<![\w.])open\(\s*["']/tmp/|\bos\.t(?:mp|emp)nam\(''')
LOG_SINK = re.compile(r'(?<![\w.])print\(|\b(?:log|logger|logging|console|LOG|LOGGER|_log|_logger|self\.log|self\.logger)'
                      r'\.(?:debug|info|warn|warning|error|critical|exception|log|fatal|trace|verbose)\('
                      r'|\b(?:log|fmt)\.Print(?:f|ln)?\(')
LOG_SECRET_ID = re.compile(r'(?i)^(?:[a-z0-9]+_)*[a-z0-9]*(?:password|passwd|secret|api_?key|token|authorization'
                           r'|private_?key|client_?secret|credentials?)$')
# `key_marker(api_key)` (a production project, create-paddle-catalog.py) is masking too — the function name says
# a marker comes out, not the value
LOG_MASK = re.compile(r'\blen\(|\bbool\(|\bhash\(|mask|redact|marker|fingerprint|\*\*\*|\[:\d\]|\[-\d:\]|\.length\b', re.I)
def identifiers_outside_literals(s):
    """Identifiers in code; of literals only the {…} / ${…} insertions remain (f-string, template)."""
    def insertions(m):
        return ' '.join(re.findall(r'\$?\{([^{}]*)\}', m.group(0)))
    return re.findall(r'[A-Za-z_][\w.]*', LITERALS.sub(insertions, s))


def rule_sql(lang, line):
    arg = argument(line, SQL_CALL_JS if lang == 'js' else SQL_CALL)
    if arg is not None and assembled(arg):
        return 'SQL query assembled from data (f-string / concatenation / % / .format / ${}) — use query parameters'


def rule_shell(lang, line):
    if lang == 'js':
        arg = argument(line, SHELL_JS)
        # `re.exec(x)` gets caught here too — we require a trace of assembly, not a bare variable
        if arg is not None and (JS_TEMPLATE.search(arg) or CONCATENATION.search(arg)):
            return 'shell command assembled from data (exec/execSync with ${} or +) — use execFile/spawn with an argument array'
        return None
    arg = argument(line, SHELL_PY)
    if arg is not None and re.search(r'shell\s*=\s*True', line) and dynamic(arg):
        return 'subprocess with shell=True and a command built from data — pass an argument list without shell=True'
    arg = argument(line, SHELL_OS)
    if arg is not None and dynamic(arg):
        return 'os.system/os.popen with a command built from data — use subprocess.run([...]) without a shell'


def rule_eval(lang, line):
    if lang == 'js':
        if find(EVAL_JS_ALWAYS, line):
            return 'executing code from a string (new Function / setTimeout("…") / vm.runIn*Context) — this cannot be safely fed from data'
        arg = argument(line, EVAL_JS)
    else:
        arg = argument(line, EVAL_PY)
    if arg is not None and dynamic(arg):
        return 'eval/exec on an expression that is not a literal — replace it with a parser / a dictionary of allowed operations'


def rule_deserialization(lang, line):
    if find(DESERIALIZATION, line):
        return 'deserialization of a code-executing format (pickle / marshal / shelve / unserialize / ObjectInputStream) — use JSON'
    if find(YAML_LOAD, line) and not YAML_SAFE.search(line):
        return 'yaml.load without SafeLoader — use yaml.safe_load'


def rule_path(lang, line):
    if find(PATH_SINK, line) and REQUEST_SOURCE.search(line) \
            and not PATH_SANITIZATION.search(line) and not PATH_RESOLVE_WITH_CHECK.search(line):
        return 'file path from request data without sanitization — secure_filename / basename / safe_join and a check that the result lies inside the base directory'


def rule_xss(lang, line):
    m = find(XSS, line)
    if m and not XSS_EMPTY.search(line):
        return f'HTML inserted without escaping ({m.group(0).strip()}) — textContent / escaping / a sanitizer (DOMPurify)'


def rule_weak_hash(lang, line):
    if find(WEAK_HASH, line) and PASSWORD_IN_LINE.search(line):
        return 'md5/sha1 for a password or token — argon2 / bcrypt / scrypt (passwords), sha256+ (tokens)'


def rule_randomness(lang, line):
    if find(RANDOMNESS, line) and SECRET_IN_LINE.search(line):
        return 'non-cryptographic randomness for a token / session / OTP — secrets (Python) / crypto.randomBytes (Node)'


def rule_redirect(lang, line):
    arg = argument(line, REDIRECT)
    if arg is not None and REDIRECT_SOURCE.search(arg) and not REDIRECT_SAFE.search(line):
        return 'redirect to an address from the request without a host check — allow only relative paths or a domain list'


def rule_stacktrace(lang, line):
    if find(STACKTRACE, line) and RESPONSE.search(line):
        return 'stack trace goes into the HTTP response — keep it in the log, return an error id to the client'


def rule_jwt(lang, line):
    m = find(JWT, line)
    if m:
        if m.group(0).startswith('jwt.decode'):
            if lang == 'js':
                return 'jwt.decode does not check the signature — use jwt.verify for authentication'
            if 'algorithms' in line:
                return None
            return 'jwt.decode without algorithms=[…] — pass the list of algorithms, otherwise "none" gets through'
        return 'JWT verification disabled (verify_signature=False / algorithms none)'
    if find(JWT_VERIFY_FALSE, line) and re.search(r'\bjwt\b|decode\(', line):
        return 'JWT signature verification disabled (verify=False)'


def rule_xxe(lang, line):
    if find(XXE, line):
        return 'XML parser without protection against external entities (XXE) — defusedxml / resolve_entities=False / DTD disabled'


def rule_ssrf(lang, line):
    arg = argument(line, SSRF_SINK)
    if arg is not None and REQUEST_SOURCE.search(arg):
        return 'HTTP request to an address from request data (SSRF) — an allowlist of hosts, no private addresses'


def rule_tmp(lang, line):
    if find(TMP, line):
        return 'insecure temporary file (mktemp / fixed path in /tmp) — tempfile.NamedTemporaryFile / mkstemp'


def rule_logging(lang, line):
    arg = argument(line, LOG_SINK)
    if arg is None or LOG_MASK.search(arg):
        return None
    for ident in identifiers_outside_literals(arg):
        if LOG_SECRET_ID.match(ident.rsplit('.', 1)[-1]):
            return f'secret in the log (`{ident[:40]}`) — log the fact, not the value'


# (rule, severity, function) — order = order of checking; one line can hit several rules
RULES = [
    ('sql-concatenation', 'block', rule_sql),
    ('shell-command', 'block', rule_shell),
    ('eval-exec', 'block', rule_eval),
    ('deserialization', 'block', rule_deserialization),
    ('path-traversal', 'block', rule_path),
    ('xss-innerhtml', 'warn', rule_xss),
    ('weak-hash', 'warn', rule_weak_hash),
    ('non-crypto-randomness', 'warn', rule_randomness),
    ('open-redirect', 'warn', rule_redirect),
    ('stacktrace-in-response', 'warn', rule_stacktrace),
    ('jwt-without-verification', 'warn', rule_jwt),
    ('xxe', 'warn', rule_xxe),
    ('ssrf', 'warn', rule_ssrf),
    ('insecure-tmp', 'warn', rule_tmp),
    ('secret-in-log', 'warn', rule_logging),
]
# Rules that make no sense in a given language (eval in an HTML template is text, not code)
CODE_ONLY = {'sql-concatenation', 'shell-command', 'eval-exec', 'deserialization', 'path-traversal',
             'weak-hash', 'non-crypto-randomness', 'open-redirect', 'stacktrace-in-response',
             'jwt-without-verification', 'xxe', 'ssrf', 'insecure-tmp', 'secret-in-log'}


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def is_binary(data):
    return b'\0' in data[:8192]


def language(p):
    return LANGUAGES.get(p.rsplit('.', 1)[-1].lower() if '.' in os.path.basename(p) else '')


def load(root, p):
    try:
        with open(os.path.join(root, p), 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if is_binary(data):
        return None
    return data.decode('utf-8', 'replace').splitlines()


def built_in(root, files, skipped_lines):
    """Per-line patterns. `skipped_lines` = {(file, nr)} already reported by semgrep."""
    for p in files:
        lang = language(p)
        if lang is None or lang == 'sql':
            continue
        rows = load(root, p)
        if rows is None:
            continue
        content = '\n'.join(rows)
        no_sql = bool(MIGRATION.search(p))
        no_xxe = 'defusedxml' in content     # the file already uses a safe parser — the rest is noise
        hits = {}      # rule → [(nr, line, message)]
        for nr, line in enumerate(rows, 1):
            if len(line) > 4000 or COMMENT.match(line) or IMPORT.match(line) or NOSEC.search(line):
                continue
            if (p, nr) in skipped_lines:
                continue
            for rule, severity, fn in RULES:
                if lang == 'template' and rule in CODE_ONLY:
                    continue
                if (rule == 'sql-concatenation' and no_sql) or (rule == 'xxe' and no_xxe):
                    continue
                message = fn(lang, line)
                # `jwt.decode(` with arguments on the following lines: `algorithms=[…]` stands below
                # (backend/app/auth/oauth_clients.py on a production project) — we look at the call window
                if message and rule == 'jwt-without-verification' and message.startswith('jwt.decode without') \
                        and any('algorithms' in w for w in rows[nr:nr + 5]):
                    message = None
                if message:
                    hits.setdefault(rule, []).append((nr, line, message))
            # The only rule with context: origin and credentials usually stand on neighbouring lines
            if find(CORS_CREDENTIALS, line):
                window = rows[max(0, nr - 4):nr + 3]
                if any(CORS_ANY.search(w) for w in window):
                    hits.setdefault('cors-any-origin-with-credentials', []).append(
                        (nr, line, 'CORS: any origin together with credentials — any site can '
                                   'call the API with the user\'s cookies; list specific domains'))
        # A rule once per file with a counter (as in weakenings). The fingerprint is computed from ALL hit
        # lines, not from the first: an exception by fingerprint has to clear exactly the lines the human saw —
        # a new injection added to a file with an exception must block again
        severities = {r: w for r, w, _ in RULES}
        for rule, found in hits.items():
            nr, line, message = found[0]
            more = f' (+{len(found) - 1} more in the file)' if len(found) > 1 else ''
            hit_lines = sorted({l.strip() for _, l, _ in found})
            emit(file=p, line=nr, rule=rule, severity=severities.get(rule, 'warn'),
                 message=f'{message}{more}', content_fingerprint=fingerprint('\n'.join(hit_lines)))


# --- Semgrep ----------------------------------------------------------------------------

BLOCKING_IDS = ('injection', 'sqli', 'sql-injection', 'command', 'subprocess', 'eval', 'exec', 'deserial',
                'pickle', 'yaml-load', 'path-traversal', 'tainted-path', 'ssrf')


def semgrep_available():
    return bool(shutil.which('semgrep')) and os.environ.get('TELESMA_SEMGREP', '').lower() != 'none'


def from_semgrep(root, files, point):
    """Returns ({(file, nr)} of reported lines, None) or (set(), reason) when semgrep could not be used."""
    packs = ['p/owasp-top-ten', 'p/security-audit']
    extensions = {p.rsplit('.', 1)[-1].lower() for p in files if '.' in os.path.basename(p)}
    for lang, pack in SEMGREP_PACK.items():
        if any(LANGUAGES.get(r) == lang for r in extensions):
            packs.append(pack)
    if extensions & set(TS_EXTENSIONS):
        packs.append('p/typescript')
    cmd = ['semgrep', 'scan']
    for pk in packs:
        cmd += ['--config', pk]
    cmd += ['--json', '--quiet', '--metrics=off', '--timeout', '10', *files]
    limit = 15 if point == 'commit' else 240
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        return set(), f'semgrep did not finish within {limit} s'
    except OSError as e:
        return set(), f'semgrep did not start ({e})'
    if r.returncode not in (0, 1):
        reason = (r.stderr.strip().splitlines() or ['?'])[-1][:120]
        return set(), f'semgrep exited with code {r.returncode} ({reason}) — no network for the p/… rules?'
    try:
        data = json.loads(r.stdout)
        results = data['results']
    except (ValueError, KeyError, TypeError):
        return set(), 'semgrep returned an unreadable result'
    reported = set()
    for w in results:
        file = os.path.relpath(os.path.join(root, w.get('path', '')), root)
        nr = (w.get('start') or {}).get('line')
        check_id = w.get('check_id', '')
        extra = w.get('extra') or {}
        severity = (extra.get('severity') or '').upper()
        rule = check_id.rsplit('.', 1)[-1] or 'semgrep'
        # Migrations build SQL from constants — the same principle as for the built-in pattern
        # (`sqlalchemy.text` in alembic/versions/ gave three contentless warnings on a production project)
        if MIGRATION.search(file) and 'sql' in check_id.lower():
            reported.add((file, nr))
            continue
        blocks = severity == 'ERROR' and any(k in check_id.lower() for k in BLOCKING_IDS)
        code = ((extra.get('lines') or '').strip().splitlines() or [''])[0].strip()
        msg = ' '.join((extra.get('message') or rule).split())[:200]
        fragment = f' — `{code[:80]}`' if code else ''
        emit(file=file, line=nr, rule=rule, severity='block' if blocks else 'warn',
             message=f'{msg}{fragment}', content_fingerprint=fingerprint(code))
        reported.add((file, nr))
    return reported, None


def main():
    if '--check' in sys.argv:
        if semgrep_available():
            r = subprocess.run(['semgrep', '--version'], capture_output=True, text=True)
            print(f'ok: semgrep {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"} '
                  f'(p/owasp-top-ten, p/security-audit + language pack)')
        else:
            print('warning: sast in built-in mode (a dozen patterns) — install semgrep '
                  '(pip install semgrep / brew install semgrep) for the full OWASP rules')
        return 0
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    point = os.environ.get('TELESMA_POINT', 'commit')
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    # Test files entirely outside the check: a test legitimately does eval, assembled SQL and pickle
    files = [p for p in files if not TEST_FILE.search(p) and language(p)]
    if not files:
        return 0
    reported = set()
    if semgrep_available():
        reported, reason = from_semgrep(root, files, point)
        if reason:
            emit(file=files[0], line=None, rule='not-checked', severity='warn', file_fingerprint=False,
                 message=f'{reason} — checked with the built-in patterns only', content_fingerprint='semgrep')
    built_in(root, files, reported)
    return 0


if __name__ == '__main__':
    sys.exit(main())
