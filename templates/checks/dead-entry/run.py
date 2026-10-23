#!/usr/bin/env python3
"""Check `dead-entry` — file list on stdin (the reference corpus), JSON findings one per line.

Checks ONLY symbols new since the reference point (phase / release tag / TELESMA_SINCE / first
commit): a new function, class, export, HTTP route or component that nothing outside its own
test refers to. Existing dead code is a separate problem — a full list at every
phase would be noise. It never blocks: dead code does not break anything, and the precision of this
check has not been measured yet.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
STORIES = re.compile(r'\.stories\.[^/]+$')
# Reference corpus: code + files in which entry points are registered (entry points in pyproject,
# commands in Makefile / Dockerfile / scripts, class names in configuration). No .md — a mention
# in documentation is not a call.
CODE = re.compile(r'\.(py|pyi|js|jsx|ts|tsx|mjs|cjs|vue|svelte|go|html|htm|toml|cfg|ini|ya?ml|json|sh|bash|'
                  r'tf|proto|graphql|sql)$|(^|/)(Makefile|Dockerfile|Procfile|Justfile)$')
# Front-end / client / API documentation files — only here do we look for references to HTTP routes
FRONT = re.compile(r'\.(ts|tsx|js|jsx|mjs|vue|svelte|html|htm|md|ya?ml|json)$')
# The repo "has a front end" = there is something to call a route with. A backend alone (client in another repo) → routes not checked
HAS_FRONT = re.compile(r'\.(tsx|jsx|vue|svelte|html|htm)$|(^|/)(openapi|swagger)[^/]*$|'
                       r'(^|/)(frontend|client|clients|web|webapp|ui|www|static|public)/.*\.(ts|js|mjs)$')
SKIPPED_DIRS = re.compile(r'(^|/)(node_modules|vendor|dist|build|out|target|\.venv|venv|__pycache__|'
                          r'\.next|\.nuxt|\.svelte-kit|coverage|site-packages)/')
SKIPPED_FILES = re.compile(r'\.min\.(js|css)$|\.map$|\.lock$|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|'
                           r'poetry\.lock|Cargo\.lock|go\.sum|deno\.lock|composer\.lock|Gemfile\.lock)$')
MAX_BYTES = 1_000_000
MAX_FINDINGS = 30
TOOL_LIMIT = 60
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

# --- Python ---------------------------------------------------------------------------
PY_DEF = re.compile(r'^(?:async\s+)?def\s+(\w+)\s*\(|^class\s+(\w+)\b')
# Files in which the framework registers handlers by convention — a definition without a reference is the norm here
PY_CONVENTION_FILE = re.compile(r'(^|/)(migrations|alembic|commands|management)/|'
                                r'(^|/)(manage|wsgi|asgi|conftest|setup|__main__|settings|urls|admin|apps|signals)\.py$')
# Decorators that register the function elsewhere (CLI, tasks, signals, fixtures) — no call by name
PY_CONVENTION_DECORATOR = re.compile(r'^@(?:\w+\.)*(shared_task|task|celery|click|command|group|option|argument|'
                                     r'receiver|fixture|on_event|exception_handler|middleware|websocket|'
                                     r'filter|simple_tag|inclusion_tag|tag|'
                                     r'event|listens_for|register|hookimpl|validator|field_validator|model_validator|'
                                     r'property|staticmethod|classmethod|overload|lifespan|subscriber|consumer|'
                                     r'job|scheduled|cron|periodic_task|dataclass_transform|pytest\.\w+|'
                                     r'app\.(?:cli|command|task|errorhandler|before_request|after_request|teardown\w*|'
                                     r'context_processor|template_filter))\b')
PY_ROUTE = re.compile(r'^@(\w+)\.(get|post|put|patch|delete|route|api_route|head|options)\(\s*[\'"]([^\'"]*)[\'"]')
PY_PREFIX = re.compile(r'(?:APIRouter|Blueprint|Router)\([^)]*?(?:prefix|url_prefix)\s*=\s*[\'"]([^\'"]*)[\'"]')
# Registration by name in the definition file: `admin.site.register(Model)`, `app.add_command(cmd)` — that is an entry
PY_REGISTRATION = re.compile(r'\b(register|setup|add_command|add_typer|include_router|add_api_route|add_url_rule|'
                             r'register_blueprint|connect|add_handler|add_middleware|mount)\s*\(')

# --- JS / TS ---------------------------------------------------------------------------
JS_DEF = re.compile(r'^export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)|'
                    r'^export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)|'
                    r'^export\s+(?:const|let)\s+(\w+)')
JS_EXPORT_LIST = re.compile(r'^export\s*\{([^}]*)\}\s*;?\s*$')      # without `from` — a re-export is not a definition
JS_SKIPPED_FILE = re.compile(r'(^|/)(index|main)\.(ts|tsx|js|jsx|mjs|cjs)$|\.d\.ts$|\.config\.[^/]+$|'
                             r'(^|/)(vite|next|nuxt|svelte|remix|astro|tailwind|postcss|jest|vitest|playwright|'
                             r'eslint|prettier|babel|webpack|rollup|tsup)\.[^/]*(config|rc)[^/]*$|'
                             r'(^|/)(setupTests|vite-env|global)\.[^/]+$')
JS_FILE_ROUTING = re.compile(r'(^|/)(pages|app|routes)/')
# Which frameworks route through files — only then are pages/ app/ routes/ entry points
FILE_ROUTING_CFG = re.compile(r'(^|/)(next|svelte|remix|nuxt|astro|react-router)\.config\.[^/]+$')
FILE_ROUTING_DEP = re.compile(r'"(next|@sveltejs/kit|@remix-run/[\w-]+|nuxt|astro|@tanstack/react-router|'
                              r'@tanstack/start|react-router|@react-router/dev|solid-start|qwik-city)"')
JS_ROUTE = re.compile(r'\b(?:app|router|server|fastify|hono|api|r)\.(get|post|put|patch|delete|all)\(\s*[\'"`](/[^\'"`]*)[\'"`]')
NEST_ROUTE = re.compile(r'^\s*@(Get|Post|Put|Patch|Delete|All|Head|Options)\(\s*(?:[\'"`]([^\'"`]*)[\'"`])?\s*\)')
NEST_CONTROLLER = re.compile(r'@Controller\(\s*(?:[\'"`]([^\'"`]*)[\'"`])?')
COMPONENT_FILE = re.compile(r'\.(tsx|jsx)$')
COMPONENT_CONST = re.compile(r'^export\s+(?:const|let)\s+([A-Z]\w*)\s*(?::\s*[\w.<>,\s\[\]|]+)?=\s*'
                             r'(?:\(|async\s*\(|React\.memo|memo|forwardRef|React\.forwardRef|styled|observer|function)')

# --- Go ---------------------------------------------------------------------------------
GO_DEF = re.compile(r'^func\s+([A-Z]\w*)\s*\(')
GO_METHOD = re.compile(r'^func\s*\(')
GO_SKIPPED = re.compile(r'^(main|init|Test\w*|Benchmark\w*|Example\w*|Fuzz\w*)$')

# --- Tools -------------------------------------------------------------------------
VULTURE = re.compile(r'^(.+?):(\d+):\s+unused\s+(?:function|class|method|variable|import|property|attribute)\s+'
                     r"'(\w+)'")
TS_PRUNE = re.compile(r'^(.+?):(\d+)\s+-\s+(\w+)')


def fingerprint(t):
    return hashlib.sha256(t.encode('utf-8', 'replace')).hexdigest()[:16]


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def git(root, *args, limit=30):
    try:
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=limit)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def language(p):
    if p.endswith(('.py', '.pyi')):
        return 'py'
    if p.endswith(('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')):
        return 'js'
    if p.endswith('.go'):
        return 'go'
    return None


# --- Reference point and diff -----------------------------------------------------------

def reference_point(root, point):
    """The revision from which a symbol is "new". TELESMA_SINCE (CI: origin/main) beats everything;
    then the phase / release tag; without a tag — the first commit (only one commit → the empty tree)."""
    since = os.environ.get('TELESMA_SINCE', '').strip()
    if since and git(root, 'rev-parse', '--verify', '-q', since + '^{commit}'):
        return since
    patterns = {'release': ['v[0-9]*'], 'phase': ['telesma/phase-*'], 'ci': ['telesma/phase-*'], 'commit': ['telesma/phase-*']}
    for pattern in patterns.get(point, ['telesma/phase-*']):
        t = git(root, 'describe', '--tags', '--abbrev=0', '--match', pattern, 'HEAD')
        if t and t.strip():
            return t.strip()
    first = (git(root, 'rev-list', '--max-parents=0', 'HEAD') or '').split()
    head = (git(root, 'rev-parse', 'HEAD') or '').strip()
    if not first or not head:
        return None
    if head in first:
        return EMPTY_TREE
    return first[-1]


def added_lines(root, since):
    """{file: [(line_number, content)]} — lines added between the reference point and HEAD."""
    span = f'{since}...HEAD' if since != EMPTY_TREE else f'{since} HEAD'
    args = ['diff', '-U0', '--no-color', '--diff-filter=AMR', '--find-renames', *span.split()]
    d = git(root, *args, limit=120)
    if d is None and since != EMPTY_TREE:              # no merge-base (shallow clone) — a plain range
        d = git(root, 'diff', '-U0', '--no-color', '--diff-filter=AMR', since, 'HEAD', limit=120)
    if not d:
        return {}
    out, file, nr = {}, None, 0
    for line in d.split('\n'):
        if line.startswith('+++ '):
            file = line[6:] if line.startswith('+++ b/') else None
            continue
        if line.startswith('@@'):
            m = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)', line)
            nr = int(m.group(1)) if m else 0
            continue
        if file is None or line.startswith(('---', 'diff ', 'index ', 'Binary', 'new file', 'deleted', 'similarity',
                                            'rename ', 'old mode', 'new mode')):
            continue
        if line.startswith('+'):
            out.setdefault(file, []).append((nr, line[1:]))
            nr += 1
    return out


# --- Corpus --------------------------------------------------------------------------------

def load(root, p):
    try:
        if os.path.getsize(os.path.join(root, p)) > MAX_BYTES:
            return None
        with open(os.path.join(root, p), 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if b'\0' in data[:8192]:
        return None
    return data.decode('utf-8', 'replace')


def corpus_files(files):
    return [p for p in files if CODE.search(p) and not SKIPPED_DIRS.search(p) and not SKIPPED_FILES.search(p)]


def file_routing(root, corpus, contents):
    """Whether the project routes through files (Next, SvelteKit, Remix…) — then pages/app/routes are entries."""
    if any(FILE_ROUTING_CFG.search(p) for p in corpus):
        return True
    for p in corpus:
        if os.path.basename(p) == 'package.json' and FILE_ROUTING_DEP.search(contents.get(p) or ''):
            return True
    return False


# --- Definitions -------------------------------------------------------------------------------

def normalize_route(path):
    """`/api/v1/items/{id}/` → a regex matching `/items/5`, `/api/items/${id}`, `/items/:id` and a
    server-side template expression `/items/{{ item.id }}` (Jinja, Django, Twig, Liquid, Nunjucks)
    or `/items/<%= id %>` (ERB, EJS). An empty path or the root alone → None (cannot be judged)."""
    s = re.sub(r'^/api(?:/v\d+)?', '', path.strip()).rstrip('/')
    if not s or s == '/':
        return None
    parts = []
    for seg in s.strip('/').split('/'):
        if re.match(r'^(:\w+|\{[^}]*\}|<[^>]*>|\[[^\]]*\]|\*.*|\$\{.*\})$', seg):
            parts.append(r'(?:\{\{[^}]*\}\}|\{%[^%]*%\}|<%=?[^%]*%>|[^/\s\'"`?#]+)')
        else:
            parts.append(re.escape(seg))
    return re.compile(r'(?<![\w/])(?:/api(?:/v\d+)?)?/' + '/'.join(parts) + r'(?![\w-])')


def definitions_py(p, added, rows):
    """[(name, nr, kind)] — kind: 'symbol' | ('route', path)."""
    if PY_CONVENTION_FILE.search(p):
        return []
    text = '\n'.join(rows)
    base = os.path.basename(p)
    # Celery tasks and CLI commands register through a decorator — nobody calls them by name
    if base in ('tasks.py', 'celery.py', 'worker.py') and re.search(r'\bshared_task\b|\bcelery\b', text, re.I):
        return []
    if base in ('cli.py', 'commands.py', '__main__.py') and re.search(r'@click|@app\.command|@cli\.|typer\.', text):
        return []
    m_all = re.search(r'^__all__\s*[:=]\s*\[([^\]]*)\]', text, re.M | re.S)
    in_all = set(re.findall(r'[\'"](\w+)[\'"]', m_all.group(1))) if m_all else set()
    prefix = PY_PREFIX.search(text)
    prefix = prefix.group(1) if prefix else ''
    out = []
    for nr, line in added:
        m = PY_DEF.match(line)
        if not m:
            continue
        name = m.group(1) or m.group(2)
        # Test* is a unittest class discovered by name — like test_* (TestHTTP in the Telesma benchmark)
        if name.startswith('_') or name == 'main' or name.startswith('test_') or name in in_all \
                or re.match(r'^Test[A-Z_]', name):
            continue
        # Context (decorators) from the file on disk — diff -U0 does not have it. When the line at that number
        # is not this definition (the working tree differs from HEAD), we look it up by content.
        idx = nr - 1
        if not (0 <= idx < len(rows) and rows[idx] == line):
            idx = next((i for i, w in enumerate(rows) if w == line), None)
            if idx is None:
                continue
        decorators = []
        i = idx - 1
        while i >= 0 and (rows[i].startswith('@') or (decorators and rows[i].strip() == '')):
            if rows[i].startswith('@'):
                decorators.append(rows[i])
            i -= 1
        if any(PY_CONVENTION_DECORATOR.match(dk) for dk in decorators):
            continue
        route = next((PY_ROUTE.match(dk) for dk in decorators if PY_ROUTE.match(dk)), None)
        if route:
            out.append((name, nr, ('route', prefix + route.group(3))))
            continue
        if any(PY_REGISTRATION.search(w) and re.search(r'\b%s\b' % re.escape(name), w)
               for w in rows if w != line):
            continue
        out.append((name, nr, 'symbol'))
    return out


def definitions_js(p, added, rows, routing_files):
    if JS_SKIPPED_FILE.search(p) or (routing_files and JS_FILE_ROUTING.search(p)):
        return []
    text = '\n'.join(rows)
    components = bool(COMPONENT_FILE.search(p))
    controller = NEST_CONTROLLER.search(text)
    prefix = ('/' + controller.group(1).strip('/')) if controller and controller.group(1) else ''
    out = []
    for nr, line in added:
        m = JS_ROUTE.search(line)
        if m:
            out.append((m.group(2), nr, ('route', m.group(2))))
            continue
        m = NEST_ROUTE.match(line)
        if m and controller:
            sc = prefix + ('/' + m.group(2).strip('/') if m.group(2) else '')
            out.append((sc or '/', nr, ('route', sc)))
            continue
        m = JS_EXPORT_LIST.match(line)
        if m:
            for el in m.group(1).split(','):
                el = el.strip()
                if not el or el == 'default' or el.startswith('type '):
                    continue
                name = el.split(' as ')[-1].strip()
                if re.match(r'^\w+$', name) and name != 'default':
                    out.append((name, nr, 'symbol'))
            continue
        m = JS_DEF.match(line)
        if not m:
            continue
        name = m.group(1) or m.group(2) or m.group(3)
        if name.startswith('_'):
            continue
        if components and name[0].isupper() and (m.group(1) or COMPONENT_CONST.match(line)):
            out.append((name, nr, 'component'))
        else:
            out.append((name, nr, 'symbol'))
    return out


def definitions_go(p, added):
    out = []
    for nr, line in added:
        if GO_METHOD.match(line):
            continue
        m = GO_DEF.match(line)
        if m and not GO_SKIPPED.match(m.group(1)):
            out.append((m.group(1), nr, 'symbol'))
    return out


# --- Tools -----------------------------------------------------------------------------

def run(cmd, cwd):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TOOL_LIMIT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout


def from_vulture(root, py_files):
    """{(file, name)} reported by vulture (min. 80% confidence)."""
    if not py_files or not shutil.which('vulture'):
        return set()
    out = run(['vulture', *py_files, '--min-confidence', '80'], root)
    result = set()
    for line in (out or '').splitlines():
        m = VULTURE.match(line)
        if m:
            result.add((os.path.normpath(m.group(1)), m.group(3)))
    return result


def from_knip(root, corpus, contents):
    """{(file, name)} from knip / ts-prune — only when the project has them in devDependencies (we install nothing)."""
    result = set()
    for p in corpus:
        if os.path.basename(p) != 'package.json' or SKIPPED_DIRS.search(p):
            continue
        try:
            dev = json.loads(contents.get(p) or '{}').get('devDependencies') or {}
        except ValueError:
            continue
        directory = os.path.dirname(p)
        cwd = os.path.join(root, directory) if directory else root
        if 'knip' in dev and shutil.which('npx'):
            out = run(['npx', '--no-install', 'knip', '--reporter', 'json', '--no-progress'], cwd)
            try:
                data = json.loads(out or '')
            except ValueError:
                data = None
            if isinstance(data, dict):
                for iss in data.get('issues') or []:
                    file = os.path.normpath(os.path.join(directory, iss.get('file', '')))
                    for key in ('exports', 'types', 'nsExports', 'nsTypes', 'classMembers'):
                        for el in iss.get(key) or []:
                            name = el.get('name') if isinstance(el, dict) else el
                            if name:
                                result.add((file, ('knip', str(name))))
                for file in data.get('files') or []:
                    result.add((os.path.normpath(os.path.join(directory, file)), ('knip', '*')))
        if 'ts-prune' in dev and shutil.which('npx'):
            out = run(['npx', '--no-install', 'ts-prune'], cwd)
            for line in (out or '').splitlines():
                m = TS_PRUNE.match(line)
                if m:
                    result.add((os.path.normpath(os.path.join(directory, m.group(1))), ('ts-prune', m.group(3))))
    return result


# --- Main run -----------------------------------------------------------------------

def check(root, files):
    """--check: built-in mode is normal (no note). A note only when the project
    declares a tool that is neither in PATH nor in node_modules/.bin next to package.json."""
    # From the raw list, not from the corpus: requirements*.txt is not a code file, yet it declares vulture
    contents = {p: load(root, p) or '' for p in files
                if not SKIPPED_DIRS.search(p) and (
                    os.path.basename(p) in ('package.json', 'pyproject.toml', 'setup.cfg', 'tox.ini',
                                            '.pre-commit-config.yaml') or os.path.basename(p).startswith('requirements'))}
    missing = []
    for p, t in contents.items():
        if os.path.basename(p) == 'package.json':
            try:
                dev = json.loads(t).get('devDependencies') or {}
            except ValueError:
                continue
            for n in ('knip', 'ts-prune'):
                local = os.path.join(root, os.path.dirname(p), 'node_modules', '.bin', n)
                if n in dev and not (shutil.which(n) or os.path.exists(local)):
                    missing.append(n)
        elif re.search(r'\bvulture\b', t) and not shutil.which('vulture'):
            missing.append('vulture')
    if missing:
        print(f'warning: the project has {", ".join(sorted(set(missing)))} in its dependencies, but they are not in PATH — '
              f'built-in mode is running (grep over definitions); install them to add the tool signal')
    return 0


def main():
    root = os.environ.get('TELESMA_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if '--check' in sys.argv:
        files = (git(root, 'ls-files') or '').splitlines()
        return check(root, [p for p in files if p.strip()])
    point = os.environ.get('TELESMA_POINT', 'phase')
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    if not files:
        return 0
    since = reference_point(root, point)
    if not since:
        return 0                                  # without git there is nothing "new" — nothing to check
    added = added_lines(root, since)
    if not added:
        return 0

    corpus = corpus_files(files)
    corpus_set = set(corpus)
    contents = {}
    for p in corpus:
        t = load(root, p)
        if t is not None:
            contents[p] = t
    has_front = any(HAS_FRONT.search(p) for p in corpus)
    routing_files = file_routing(root, corpus, contents)

    # 1. New definitions in code files in scope (outside tests, stories, generated directories)
    definitions = []                               # (file, name, nr, kind)
    for p, new_lines in added.items():
        if p not in corpus_set or p not in contents or TEST_FILE.search(p) or STORIES.search(p):
            continue
        lang = language(p)
        rows = contents[p].split('\n')
        if lang == 'py':
            defs = definitions_py(p, new_lines, rows)
        elif lang == 'js':
            defs = definitions_js(p, new_lines, rows, routing_files)
        elif lang == 'go':
            defs = definitions_go(p, new_lines)
        else:
            continue
        for name, nr, kind in defs:
            if isinstance(kind, tuple) and not has_front:
                continue                           # backend alone — the route's client is elsewhere
            definitions.append((p, name, nr, kind))
    if not definitions:
        return 0

    # 2. References: one pass over the corpus with an alternation of all names (not N × corpus)
    names = sorted({d[1] for d in definitions if not isinstance(d[3], tuple)}, key=len, reverse=True)
    names_re = re.compile(r'\b(' + '|'.join(map(re.escape, names)) + r')\b') if names else None
    routes = {}
    for p, name, nr, kind in definitions:
        if isinstance(kind, tuple):
            pattern = normalize_route(kind[1])
            if pattern:
                routes[(p, name)] = pattern
    references = {}                                # name → {files with an occurrence}
    route_references = {k: set() for k in routes}
    # An occurrence in the definition file counts when it is on a line other than the definition (and not in a comment):
    # the first measurement on the Telesma repo gave 146 "dead" functions, every one of them a helper called
    # in its own module. The retro's toolbar still gets caught — its name stands only on the `def` line.
    def_lines = {}                                 # (file, name) → {definition line numbers}
    for p, name, nr, kind in definitions:
        if not isinstance(kind, tuple):
            def_lines.setdefault((p, name), set()).add(nr)
    for p, t in contents.items():
        if TEST_FILE.search(p) or STORIES.search(p):
            continue
        if names_re:
            in_this_file = {k[1] for k in def_lines if k[0] == p}
            if not in_this_file:
                for m in names_re.finditer(t):
                    references.setdefault(m.group(1), set()).add(p)
            else:
                for nr, line in enumerate(t.split('\n'), 1):
                    if line.lstrip().startswith(('#', '//', '*', '/*')):
                        continue
                    for m in names_re.finditer(line):
                        n = m.group(1)
                        if n in in_this_file and (nr in def_lines[(p, n)] or re.match(
                                r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:def|class|function\s*\*?|const|let|func)\s+'
                                + re.escape(n) + r'\b', line)):
                            continue
                        references.setdefault(n, set()).add(p)
        if routes and FRONT.search(p):
            for k, pattern in routes.items():
                if k[0] != p and pattern.search(t):
                    route_references[k].add(p)

    # 3. Tools as an extra signal (only for symbols new in the diff)
    py_files = sorted({d[0] for d in definitions if language(d[0]) == 'py'})
    tools = {(f, ('vulture', n)) for f, n in from_vulture(root, py_files)} | from_knip(root, corpus, contents)
    by_symbol = {}
    for f, (tool, n) in tools:
        by_symbol.setdefault((f, n), set()).add(tool)
        if n == '*':
            by_symbol.setdefault((f, '*'), set()).add(tool)

    # 4. Findings
    findings = []
    for p, name, nr, kind in sorted(definitions, key=lambda d: (d[0], d[2])):
        tool_names = sorted(by_symbol.get((p, name), set()) | by_symbol.get((p, '*'), set()))
        if isinstance(kind, tuple):
            k = (p, name)
            if k not in routes or route_references[k]:
                continue
            findings.append(dict(file=p, line=nr, rule='route-without-client',
                                 message=f'route `{kind[1]}` added in this phase — no front-end / client / '
                                         f'API documentation file calls it; wire up an entry (AC: entry) or remove it',
                                 content_fingerprint=fingerprint(f'{p}:{kind[1]}')))
            continue
        if references.get(name):                   # in the definition file only lines outside the definition count
            continue
        rule = 'component-without-parent' if kind == 'component' else 'symbol-without-entry'
        what = 'component' if kind == 'component' else 'symbol'
        confirmed = f' (confirmed by: {", ".join(tool_names)})' if tool_names else ''
        verb = 'renders' if kind == 'component' else 'calls'
        findings.append(dict(file=p, line=nr, rule=rule,
                             message=f'{what} `{name}` added in this phase — nothing outside its own test {verb} it{confirmed}; '
                                     f'wire up an entry (AC: entry) or remove it',
                             content_fingerprint=fingerprint(f'{p}:{name}')))
    # A tool sees a dead symbol our grep did not catch (e.g. the name hit inside a string) — a separate rule
    reported = {(z['file'], z['content_fingerprint']) for z in findings}
    for p, name, nr, kind in sorted(definitions, key=lambda d: (d[0], d[2])):
        if isinstance(kind, tuple) or (p, fingerprint(f'{p}:{name}')) in reported:
            continue
        tool_names = sorted(by_symbol.get((p, name), set()))
        if tool_names:
            findings.append(dict(file=p, line=nr, rule='dead-symbol-tool',
                                 message=f'`{name}` added in this phase — {", ".join(tool_names)} sees no use of it '
                                         f'(our grep found the name elsewhere, maybe in a string); check the entry',
                                 content_fingerprint=fingerprint(f'{p}:{name}')))

    for z in findings[:MAX_FINDINGS]:
        emit(severity='warn', **z)
    rest = findings[MAX_FINDINGS:]
    if rest:
        found = ', '.join(f'{z["file"]}:{z["line"]}' for z in rest[:8]) + (' …' if len(rest) > 8 else '')
        emit(file=rest[0]['file'], line=rest[0]['line'], rule='symbol-without-entry', severity='warn',
             file_fingerprint=False,
             message=f'+{len(rest)} more symbols without an entry ({found}) — full list: '
                     f'python3 telesma/checks/telesma-checks.py --point phase',
             content_fingerprint='counter')
    return 0


if __name__ == '__main__':
    sys.exit(main())
