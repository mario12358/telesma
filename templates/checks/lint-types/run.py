#!/usr/bin/env python3
"""Check `lint-types` — the project's linter and typechecker as a guard + typographic quotes.

File list on stdin, JSON findings one per line on stdout. Commands come from `## Tests`
in telesma/config.md (`Linter/formatter`, `Typecheck command`); the quote rule works without
any tool. The hook never changes files: `--fix` is stripped, formatters
get `--check`.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

PY = ('py',)
JS = ('js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'vue', 'svelte')
# A word boundary that also splits on `_` and `-`: `fake_ruff.py` and `ruff-wrapper` are still ruff
G = r'(?<![A-Za-z0-9])', r'(?![A-Za-z0-9])'
# (pattern in the command, extensions, whether it gets a file list, JSON flag, parser)
TOOLS = [
    ('ruff', PY, True, ['--output-format', 'json'], 'ruff'),
    ('flake8', PY, True, None, 'text'),
    ('pylint', PY, True, ['--output-format=json'], 'pylint'),
    ('black', PY, True, None, 'format'),
    ('isort', PY, True, None, 'format'),
    ('eslint', JS, True, ['-f', 'json'], 'eslint'),
    ('biome', JS, True, ['--reporter=json'], 'biome'),
    ('prettier', JS, True, None, 'format'),
    ('golangci-lint', ('go',), False, ['--out-format', 'json'], 'golangci'),
    (r'go\s+vet', ('go',), False, None, 'text'),
    (r'cargo\s+clippy', ('rs',), False, ['--message-format', 'json'], 'cargo'),
    (r'cargo\s+fmt', ('rs',), False, None, 'format'),
    ('rubocop', ('rb',), True, ['--format', 'json'], 'rubocop'),
    ('shellcheck', ('sh', 'bash'), True, ['-f', 'json'], 'shellcheck'),
]
TOOLS = [(re.compile(G[0] + pattern + G[1]), *rest) for pattern, *rest in TOOLS]
# Formatters: without `--check` the hook would rewrite files before the commit
FORMATTER_CHECK = {'black': '--check', 'isort': '--check-only', 'prettier': '--check', 'fmt': '--check',
                   'format': '--check'}
COMMIT_LIMIT = 15
FULL_LIMIT = 240
BUDGET = {'commit': 18, 'phase': 270, 'release': 270, 'ci': 270}   # the runner gives 20 s / 300 s per module
MAX_FINDINGS = 100
MAX_LIST = 500          # above this: the tool runs without a list (its own scope), we do not risk ARG_MAX
START = time.monotonic()

# --- Typographic quote ---------------------------------------------------------
TYPO = '„”“‚’‹›«»'
CODE = re.compile(r'\.(py|js|jsx|ts|tsx|mjs|cjs|go|rs|java|kt|rb|php|sh|bash|sql|ya?ml|toml|json)$')
LINE_COMMENT = {'py': ('#',), 'rb': ('#',), 'sh': ('#',), 'bash': ('#',), 'yaml': ('#',), 'yml': ('#',),
                'toml': ('#',), 'php': ('//', '#'), 'sql': ('--',), 'json': ()}
BLOCK_COMMENT = {'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'go', 'rs', 'java', 'kt', 'php', 'sql'}
TRIPLE = {'py'}
BACKTICK = {'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'go'}
# Languages in which an ordinary string cannot continue onto the next line — there `"text”`
# (opened with ASCII, "closed" typographically) is always a syntax error
SINGLE_LINE = {'py', 'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'go', 'java', 'kt', 'toml', 'json', 'yaml', 'yml',
               'sh', 'bash'}
# In shell and YAML a typographic quote outside a string is a legitimate character (heredoc, translations
# in i18n) — only the mixed variant and the assignment `X=„…”` remain
MIXED_ONLY = {'sh', 'bash', 'yaml', 'yml'}
# JSX / PHP have text outside strings (`<p>He said „yes”, </p>`) — no closing rule
NO_CLOSING = {'jsx', 'tsx', 'php'}
OPENING = ('=', '(', '[', '{', ',', ':', '+')
CLOSING = ')]},;'
OPENING_WORD = re.compile(r'\b(return|yield)$')
TYPO_MESSAGE = 'typographic quote as a string delimiter — replace it with " (a pitfall that came back 9 times on the reference project)'


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def extension(p):
    m = CODE.search(p)
    return m.group(1) if m else None


def comment_at(s, i, ext):
    """Whether a line comment starts at position i."""
    for k in LINE_COMMENT.get(ext, ('//',)):
        if s.startswith(k, i):
            # in shell / YAML `#` is a comment only at the start of a word (`$#`, `a#b` are not)
            if k == '#' and ext in ('sh', 'bash', 'yaml', 'yml') and i > 0 and not s[i - 1].isspace():
                return False
            return True
    return False


def typo_in_line(s, ext, state):
    """Column number of the first typographic quote acting as a delimiter, or None.
    `state` carries a block comment / multi-line string across lines."""
    i, n = 0, len(s)
    in_str, typo_in_str = None, False
    while i < n:
        c = s[i]
        if state['block']:
            if s.startswith('*/', i):
                state['block'] = False
                i += 2
            else:
                i += 1
            continue
        if state['multi']:
            if c == '\\':
                i += 2
            elif s.startswith(state['multi'], i):
                i += len(state['multi'])
                state['multi'] = None
            else:
                i += 1
            continue
        if in_str:
            if c == '\\':
                i += 2
            elif c == in_str:
                in_str = None
                i += 1
            else:
                typo_in_str = typo_in_str or c in TYPO
                i += 1
            continue
        if comment_at(s, i, ext):
            break
        if ext in BLOCK_COMMENT and s.startswith('/*', i):
            state['block'] = True
            i += 2
            continue
        if ext in TRIPLE and (s.startswith('"""', i) or s.startswith("'''", i)):
            state['multi'] = s[i:i + 3]
            i += 3
            continue
        if c == '`' and ext in BACKTICK:
            state['multi'] = '`'
            i += 1
            continue
        if c in '"\'':
            in_str = c
            i += 1
            continue
        if c in TYPO:
            before = s[:i].rstrip()
            if ext in ('sh', 'bash'):
                opens = bool(re.search(r'[A-Za-z_]\w*=$', before))
            elif ext in MIXED_ONLY:
                opens = False
            else:
                opens = before.endswith(OPENING) or bool(OPENING_WORD.search(before))
            closes = False
            if not opens and ext not in MIXED_ONLY and ext not in NO_CLOSING:
                j = next((k for k in range(i + 1, n) if s[k] in TYPO), None)
                rest = s[j + 1:].lstrip() if j is not None else ''
                closes = bool(rest) and rest[0] in CLOSING
            if opens or closes:
                return i + 1
        i += 1
    # `"text”` — a string opened with ASCII, not closed by the end of the line, a typographic quote inside:
    # this is exactly the pitfall ("a typographic closing quote truncates the string")
    if in_str and typo_in_str and ext in SINGLE_LINE and not s.rstrip().endswith('\\') \
            and not (ext in ('jsx', 'tsx') and in_str == "'"):
        return n
    return None


def quotes(root, files):
    for p in files:
        ext = extension(p)
        if not ext:
            continue
        try:
            with open(os.path.join(root, p), 'rb') as f:
                data = f.read()
        except OSError:
            continue
        if b'\0' in data[:8192]:
            continue
        if not any(ch in data.decode('utf-8', 'replace') for ch in TYPO):
            continue
        state = {'block': False, 'multi': None}
        hits = []
        for nr, line in enumerate(data.decode('utf-8', 'replace').splitlines(), 1):
            if len(line) > 4000:
                continue
            if typo_in_line(line, ext, state) is not None:
                hits.append((nr, line))
        for k, (nr, line) in enumerate(hits[:20]):
            more = f' (+{len(hits) - 20} more in the file)' if k == 19 and len(hits) > 20 else ''
            emit(file=p, line=nr, rule='typographic-quote', severity='block',
                 message=TYPO_MESSAGE + more, content_fingerprint=fingerprint(line.strip()))


# --- Config -----------------------------------------------------------------------------

def config_path(root):
    if root:
        return os.path.join(root, 'telesma', 'config.md')
    # --check: the runner calls with cwd = the module directory and without TELESMA_ROOT;
    # the module lives in <project>/telesma/checks/lint-types/
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', '..', 'config.md'))


def load_tests_section(path):
    """Fields of the ## Tests section of telesma/config.md (without <!-- --> comments)."""
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return {}
    m = re.search(r'^## Tests[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not m:
        return {}
    section = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.S)
    return {k.strip(): v.strip() for k, v in re.findall(r'^- \*\*(.+?)\*\*:[ \t]*(.*?)[ \t]*$', section, re.M)}


def command_from_field(fields, name):
    """The field value, or None for a placeholder `[e.g. …]`, `none`, empty."""
    w = (fields.get(name) or '').strip()
    if not w or w.startswith('[') or w.lower() in ('none', 'no', '-'):
        return None
    return w


def commands(field):
    """List of commands from the field. A project with several parts writes several commands, each with its own
    `cd` — e.g. `cd backend && ruff check app tests` · `cd frontend && npx eslint src`.
    Commands in backticks or separated by ` · ` / ` and ` / ` ; ` (spaces around the semicolon:
    a bare `;` can be part of a command)."""
    if not field:
        return []
    in_backticks = re.findall(r'`([^`]+)`', field)
    if in_backticks:
        return [k.strip() for k in in_backticks if k.strip()]
    return [k.strip() for k in re.split(r'\s+·\s+|\s+and\s+|\s+;\s+', field) if k.strip()]


def without_paths(tokens, cwd):
    """Tokens without the paths written into the command (`ruff check app tests`), when the hook passes its own
    file list — otherwise the linter at commit would check the whole directory and block for others' errors.
    A path after an option that takes a value (`--config ruff.toml`) stays."""
    # Only AFTER the tool token: `python3 ../tools/fake_ruff.py check app` — the tool's script
    # is itself a path and has to stay
    start = next((i for i, t in enumerate(tokens) if any(n[0].search(t) for n in TOOLS)), None)
    if start is None:
        return tokens
    out = tokens[:start + 1]
    for i in range(start + 1, len(tokens)):
        t, previous = tokens[i], tokens[i - 1]
        after_option = previous.startswith('-') and '=' not in previous
        if not t.startswith('-') and not after_option and os.path.exists(os.path.join(cwd, t)):
            continue
        out.append(t)
    return out


# --- Running commands ---------------------------------------------------------------

def remaining(point):
    return max(1.0, BUDGET.get(point, 270) - (time.monotonic() - START))


def split_command(cmd):
    """(directory from `cd X &&` or None, tokens) — or None when the command is compound
    (a pipe, several members): then files or a flag cannot be appended."""
    m = re.match(r'^\s*cd\s+(\S+)\s*&&\s*(.+)$', cmd, re.S)
    directory, rest = (m.group(1), m.group(2)) if m else (None, cmd)
    if re.search(r'&&|\|\||[|;]|\$\(|`|\n', rest):
        return None
    try:
        tokens = shlex.split(rest)
    except ValueError:
        return None
    return (directory, tokens) if tokens else None


def run(tokens, cwd, limit):
    """(process, None) or (None, 'missing' | 'timeout')."""
    env = {**os.environ, 'NO_COLOR': '1', 'FORCE_COLOR': '0', 'CLICOLOR': '0', 'TERM': 'dumb',
           'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        r = subprocess.run(tokens, cwd=cwd, env=env, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None, 'missing'
    except OSError:
        return None, 'missing'
    if r.returncode in (126, 127):
        return None, 'missing'
    return r, None


def relative(root, cwd, p):
    """A path from the tool's output (absolute or relative to cwd) → relative to root.
    realpath on both sides: on macOS ruff returns /private/var/…, and root can be /var/… ."""
    if not p:
        return p
    full = p if os.path.isabs(p) else os.path.join(cwd, p)
    return os.path.relpath(os.path.realpath(full), os.path.realpath(root))


_lines = {}


def line_content(root, file, nr):
    if file not in _lines:
        try:
            with open(os.path.join(root, file), encoding='utf-8', errors='replace') as f:
                _lines[file] = f.read().splitlines()
        except OSError:
            _lines[file] = []
    w = _lines[file]
    return w[nr - 1].strip() if nr and 0 < nr <= len(w) else f'{file}:{nr}'


def output_excerpt(r):
    text = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
    first = [l.strip() for l in text.strip().splitlines() if l.strip()][:3]
    return ' | '.join(first)[:300]


# --- Output parsers -----------------------------------------------------------------

CODE_BLOCKS = re.compile(r'^(E9\d*|F\d*|B\d*|PLE|E0|F0)')
# `file:line[:col][:] rest` (ruff/flake8/mypy/go vet/pyright) or `file(l,c): rest` (tsc)
TEXT_LINE = re.compile(r'^\s*(?P<file>(?:[A-Za-z]:)?[^\s:(][^:(\n]*?)'
                       r'(?:\((?P<l2>\d+),\d+\)|:(?P<l1>\d+)(?::\d+)?):?\s*-?\s*(?P<rest>\S.*)$')


def _json(r):
    text = (r.stdout or '').strip()
    if not text:
        return None
    # a tool can print a warning before the JSON — take it from the first bracket
    for start in ('[', '{'):
        k = text.find(start)
        if k >= 0:
            try:
                return json.loads(text[k:])
            except ValueError:
                continue
    return None


def code_severity(code, severity=None):
    if severity in ('error', 'fatal', 2):
        return 'block'
    if code and CODE_BLOCKS.match(code):
        return 'block'
    return 'warn'


def parse_ruff(r):
    d = _json(r)
    if not isinstance(d, list):
        return None
    out = []
    for z in d:
        if not isinstance(z, dict):
            continue
        code = z.get('code') or 'syntax-error'
        nr = (z.get('location') or {}).get('row')
        out.append((z.get('filename', ''), nr, code, z.get('message', ''),
                    'block' if code == 'syntax-error' else code_severity(code)))
    return out


def parse_pylint(r):
    d = _json(r)
    if not isinstance(d, list):
        return None
    return [(z.get('path', ''), z.get('line'), z.get('message-id') or z.get('symbol') or 'pylint',
             z.get('message', ''), 'block' if z.get('type') in ('error', 'fatal') else 'warn')
            for z in d if isinstance(z, dict)]


def parse_eslint(r):
    d = _json(r)
    if not isinstance(d, list):
        return None
    out = []
    for file in d:
        for m in file.get('messages') or []:
            code = m.get('ruleId') or ('parse-error' if m.get('fatal') else 'eslint')
            out.append((file.get('filePath', ''), m.get('line'), code, m.get('message', ''),
                        'block' if m.get('severity') == 2 or m.get('fatal') else 'warn'))
    return out


def parse_biome(r):
    d = _json(r)
    if not isinstance(d, dict) or 'diagnostics' not in d:
        return None
    out = []
    for z in d['diagnostics'] or []:
        loc = z.get('location') or {}
        file = (loc.get('path') or {}).get('file', '') if isinstance(loc.get('path'), dict) else loc.get('path', '')
        nr = None
        span, src = loc.get('span'), loc.get('sourceCode')
        if isinstance(span, list) and span and isinstance(src, str):
            nr = src[:span[0]].count('\n') + 1
        out.append((file, nr, z.get('category') or 'biome', z.get('description', ''),
                    'block' if z.get('severity') == 'error' else 'warn'))
    return out


def parse_golangci(r):
    d = _json(r)
    if not isinstance(d, dict) or 'Issues' not in d:
        return None
    out = []
    for z in d.get('Issues') or []:
        pos = z.get('Pos') or {}
        out.append((pos.get('Filename', ''), pos.get('Line'), z.get('FromLinter') or 'golangci',
                    z.get('Text', ''), 'block' if z.get('Severity') == 'error' else 'warn'))
    return out


def parse_cargo(r):
    out, seen = [], False
    for line in (r.stdout or '').splitlines():
        try:
            z = json.loads(line)
        except ValueError:
            continue
        if not isinstance(z, dict) or z.get('reason') != 'compiler-message':
            continue
        seen = True
        m = z.get('message') or {}
        sp = (m.get('spans') or [{}])[0]
        code = (m.get('code') or {}).get('code') or m.get('level') or 'cargo'
        out.append((sp.get('file_name', ''), sp.get('line_start'), code, m.get('message', ''),
                    'block' if m.get('level') == 'error' else 'warn'))
    return out if seen or (r.stdout or '').strip().startswith('{') else None


def parse_rubocop(r):
    d = _json(r)
    if not isinstance(d, dict) or 'files' not in d:
        return None
    out = []
    for file in d.get('files') or []:
        for o in file.get('offenses') or []:
            out.append((file.get('path', ''), (o.get('location') or {}).get('line'), o.get('cop_name') or 'rubocop',
                        o.get('message', ''), 'block' if o.get('severity') in ('error', 'fatal') else 'warn'))
    return out


def parse_shellcheck(r):
    d = _json(r)
    if not isinstance(d, list):
        return None
    return [(z.get('file', ''), z.get('line'), f'SC{z.get("code")}', z.get('message', ''),
             'block' if z.get('level') == 'error' else 'warn') for z in d if isinstance(z, dict)]


def parse_pyright(r):
    d = _json(r)
    if not isinstance(d, dict) or 'generalDiagnostics' not in d:
        return None
    out = []
    for z in d.get('generalDiagnostics') or []:
        if z.get('severity') not in ('error', 'warning'):
            continue
        out.append((z.get('file', ''), ((z.get('range') or {}).get('start') or {}).get('line', -1) + 1,
                    z.get('rule') or 'pyright', z.get('message', ''),
                    'block' if z.get('severity') == 'error' else 'warn'))
    return out


def parse_text(r, cwd, types=False):
    """`file:line: …` and `file(l,c): …` — flake8, ruff without JSON, go vet, mypy, tsc, pyright."""
    out = []
    for line in ((r.stdout or '') + '\n' + (r.stderr or '')).splitlines():
        m = TEXT_LINE.match(line)
        if not m:
            continue
        file = m.group('file').strip()
        if not os.path.isfile(file if os.path.isabs(file) else os.path.join(cwd, file)):
            continue
        nr = int(m.group('l1') or m.group('l2'))
        rest = m.group('rest').strip()
        if re.match(r'note:', rest):
            continue
        level = None
        pm = re.match(r'(error|warning)\b:?\s*', rest)
        if pm:
            level = pm.group(1)
            rest = rest[pm.end():]
        code = None
        km = re.match(r'(TS\d+)\s*:\s*', rest)             # tsc: error TS2322: …
        if km:
            code, rest = km.group(1), rest[km.end():]
        else:
            km = re.search(r'\s+\[([\w.-]+)\]\s*$', rest)    # mypy: …  [assignment]
            if km:
                code, rest = km.group(1), rest[:km.start()]
            else:
                km = re.match(r'([A-Z]{1,4}\d{2,4})\s+', rest)   # flake8/ruff: E501 …
                if km:
                    code, rest = km.group(1), rest[km.end():]
                else:
                    km = re.search(r'\((report\w+)\)\s*$', rest)   # pyright as text
                    if km:
                        code, rest = km.group(1), rest[:km.start()]
        if types:
            if level is None and code is None:
                continue
            severity = 'block' if level in ('error', None) else 'warn'
            code = code or 'error'
        else:
            severity = 'block' if level == 'error' else code_severity(code)
            code = code or ('vet' if 'vet' in (r.args[0:2] if isinstance(r.args, list) else []) else 'linter')
        out.append((file, nr, code, rest.strip(), severity))
    return out


def parse_format(r):
    """black / isort / prettier / cargo fmt / ruff format: a file to reformat → warn."""
    out = []
    for line in ((r.stdout or '') + '\n' + (r.stderr or '')).splitlines():
        m = (re.match(r'^would reformat (.+)$', line.strip())                      # black, ruff format
             or re.match(r'^ERROR: (.+?) Imports are incorrectly sorted', line.strip())   # isort
             or re.match(r'^\[warn\] (\S.*)$', line.strip())                        # prettier
             or re.match(r'^Diff in (.+?) at line', line.strip()))                  # cargo fmt
        if m:
            out.append((m.group(1).strip(), None, 'format', 'file needs formatting — run the formatter', 'warn'))
    return out


PARSERS = {'ruff': parse_ruff, 'pylint': parse_pylint, 'eslint': parse_eslint, 'biome': parse_biome,
           'golangci': parse_golangci, 'cargo': parse_cargo, 'rubocop': parse_rubocop,
           'shellcheck': parse_shellcheck, 'format': parse_format}


# --- Linter ---------------------------------------------------------------------------

def tool(cmd):
    for pattern, exts, with_list, flag, parser in TOOLS:
        if pattern.search(cmd):
            if parser == 'ruff' and re.search(r'\bruff\s+format\b', cmd):
                return exts, with_list, None, 'format'
            return exts, with_list, flag, parser
    return None


def prepare(tokens, flag, parser):
    """Strips `--fix`, adds `--check` for a formatter and the JSON flag (before `--`, when present)."""
    tokens = [t for t in tokens if t not in ('--fix', '--fix-only', '--unsafe-fixes', '-w', '--write')]
    if parser == 'format':
        for word, check in FORMATTER_CHECK.items():
            if word in tokens and not any(t in ('--check', '--check-only', '-c') for t in tokens):
                tokens.append(check)
                break
    if flag and not any('json' in t for t in tokens):
        k = tokens.index('--') if '--' in tokens else len(tokens)
        tokens = tokens[:k] + flag + tokens[k:]
    return tokens


def emit_results(root, cwd, results, prefix):
    count = 0
    seen = set()
    for file, nr, code, message, severity in results:
        file = relative(root, cwd, file)
        key = (file, nr, code)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        if count > MAX_FINDINGS:
            emit(file=file, line=None, rule=f'{prefix}-more', severity='warn', file_fingerprint=False,
                 message=f'… and {len(results) - MAX_FINDINGS} more tool reports', content_fingerprint=prefix)
            break
        emit(file=file, line=nr, rule=f'{prefix}/{code}', severity=severity, message=(message or code)[:300],
             content_fingerprint=fingerprint(line_content(root, file, nr) if nr else f'{file}:{code}'))


def linter(root, point, cmd, files):
    found = tool(cmd)
    first = files[0] if files else 'telesma/config.md'
    split = split_command(cmd)
    if found is None or split is None:
        # Unknown tool: we do not know which files to give it or how to read its output.
        # At phase we run it as it stands; at commit one warning.
        if point == 'commit':
            emit(file=first, line=None, rule='linter-unknown', severity='warn', file_fingerprint=False,
                 message=f'unknown tool in "Linter/formatter" ({cmd[:60]}) — skipped at commit; '
                         f'run in full at phase / CI. Known: ruff, flake8, pylint, black, isort, '
                         f'eslint, biome, prettier, golangci-lint, go vet, cargo clippy/fmt, rubocop, shellcheck',
                 content_fingerprint='linter-unknown')
            return
        if not files:
            return
        tokens, cwd, parser = ['bash', '-c', cmd], root, 'text'
    else:
        exts, with_list, flag, parser = found
        directory, tokens = split
        cwd = os.path.normpath(os.path.join(root, directory)) if directory else root
        matching = [p for p in files if any_extension(p) in exts]
        if not matching:
            return
        tokens = prepare(tokens, flag, parser)
        if with_list:
            # The scope (changed / all) is computed by the runner — the module gets a ready list. Paths
            # relative to the directory the tool will run in (`cd backend && ruff check`).
            paths = [os.path.relpath(os.path.join(root, p), cwd) for p in matching]
            paths = [p for p in paths if not p.startswith('..')]
            if not paths:
                return
            if len(paths) <= MAX_LIST:
                tokens = without_paths(tokens, cwd)
                k = tokens.index('--') if '--' in tokens else len(tokens)
                tokens = tokens[:k] + paths + tokens[k:]
    limit = min(COMMIT_LIMIT if point == 'commit' else FULL_LIMIT, remaining(point))
    r, error = run(tokens, cwd, limit)
    if error == 'missing':
        emit(file=first, line=None, rule='linter-unavailable', severity='warn', file_fingerprint=False,
             message=f'the tool from "Linter/formatter" is not available ({tokens[0]}) — the operation passed without '
                     f'the linter; install it or fix the field in telesma/config.md',
             content_fingerprint='linter-unavailable:' + tokens[0])
        return
    if error == 'timeout':
        emit(file=first, line=None, rule='linter-timeout', severity='warn', file_fingerprint=False,
             message=f'the linter did not finish within {int(limit)} s — the operation passed without it; narrow the command',
             content_fingerprint='linter-timeout')
        return
    results = PARSERS[parser](r) if parser in PARSERS else None
    if results is None:
        results = parse_text(r, cwd)
    if results:
        emit_results(root, cwd, results, 'linter')
    elif r.returncode != 0:
        emit(file=first, line=None, rule='linter-failed', severity='warn', file_fingerprint=False,
             message=f'the linter exited with code {r.returncode}, its output could not be parsed: {output_excerpt(r)}',
             content_fingerprint='linter-failed:' + output_excerpt(r))


def any_extension(p):
    return p.rsplit('.', 1)[-1].lower() if '.' in os.path.basename(p) else ''


# --- Typechecker ------------------------------------------------------------------------

def types(root, point, cmd, first):
    split = split_command(cmd)
    if split is None:
        tokens, cwd = ['bash', '-c', cmd], root
    else:
        directory, tokens = split
        cwd = os.path.normpath(os.path.join(root, directory)) if directory else root
        if re.search(r'\bpyright\b', cmd) and not any('json' in t for t in tokens):
            tokens = tokens + ['--outputjson']
    limit = min(FULL_LIMIT, remaining(point))
    r, error = run(tokens, cwd, limit)
    if error == 'missing':
        emit(file=first, line=None, rule='types-unavailable', severity='warn', file_fingerprint=False,
             message=f'the typechecker from "Typecheck command" is not available ({tokens[0]}) — the operation passed without it',
             content_fingerprint='types-unavailable:' + tokens[0])
        return
    if error == 'timeout':
        emit(file=first, line=None, rule='types-timeout', severity='warn', file_fingerprint=False,
             message=f'the typechecker did not finish within {int(limit)} s — the operation passed without it',
             content_fingerprint='types-timeout')
        return
    results = parse_pyright(r) if re.search(r'\bpyright\b', cmd) else None
    if results is None:
        results = parse_text(r, cwd, types=True)
    if results:
        emit_results(root, cwd, results, 'types')
    elif r.returncode != 0:
        emit(file=first, line=None, rule='types-failed', severity='warn', file_fingerprint=False,
             message=f'the typechecker exited with code {r.returncode}, its output could not be parsed: {output_excerpt(r)}',
             content_fingerprint='types-failed:' + output_excerpt(r))


# --- Main ------------------------------------------------------------------------------

def check():
    fields = load_tests_section(config_path(os.environ.get('TELESMA_ROOT')))
    lint = command_from_field(fields, 'Linter/formatter')
    typ = command_from_field(fields, 'Typecheck command')
    if not lint and not typ:
        print('warning: lint-types: no linter and no typechecker in ## Tests — only the quote rule runs; '
              'set e.g. "ruff check" / "npx eslint ." and "mypy src" / "npx tsc --noEmit"')
        return 0
    notes = []
    for name, cmd in [('linter', k) for k in commands(lint)] + [('typechecker', k) for k in commands(typ)]:
        split = split_command(cmd)
        if split is None:
            notes.append(f'{name} "{cmd[:40]}" is a compound command — no file list and no parsing')
            continue
        prog = split[1][0]
        if '/' not in prog and not shutil.which(prog):
            notes.append(f'{name}: "{prog}" is not in PATH')
        if name == 'linter' and tool(cmd) is None:
            notes.append(f'linter "{cmd[:40]}" unknown — skipped at commit, run only at phase / CI')
    if notes:
        print('warning: lint-types: ' + '; '.join(notes))
    else:
        print(f'ok: linter: {lint or "none"}; types: {typ or "none"}')
    return 0


def main():
    if '--check' in sys.argv:
        return check()
    point = os.environ.get('TELESMA_POINT', 'commit')
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    quotes(root, files)
    fields = load_tests_section(config_path(root))
    lint = command_from_field(fields, 'Linter/formatter')
    typ = command_from_field(fields, 'Typecheck command')
    # Each command separately: `cd backend && ruff …` gets only files from backend/, eslint from frontend/
    if files:
        for cmd in commands(lint):
            linter(root, point, cmd, files)
    # tsc / mypy cannot sensibly do "only these files", and on a large project they do not fit
    # in the commit budget — full run at phase / CI
    if point in ('phase', 'ci'):
        for cmd in commands(typ):
            types(root, point, cmd, files[0] if files else 'telesma/config.md')
    return 0


if __name__ == '__main__':
    sys.exit(main())
