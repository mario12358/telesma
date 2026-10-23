"""Shared by the `intent` and `red-team` checks: HTTP routes from code, the window of their
definition (where the guards stand) and the attack-surface map `telesma/state/SECURITY_MAP.md`.

Extraction does not understand the authentication framework — and does not need to. For every
route it returns a **window**: the text of the decorators and signature (Python), of the call
arguments before the handler (JS), of the class and method decorators (Nest), plus the router
definition and middleware with a prefix. The map says which text in that window stands for a
given role ("guard in code"), so the check comes down to a text comparison. The guard vocabulary
is written by the project, not by the framework.

First measurement on a production FastAPI project: 233 route decorators, 117 of them with the
path on the next line (`@router.get(\\n    "/x",`) — line-by-line extraction saw half. Hence
joining brackets before anything is matched.
"""
import os
import re
import subprocess

MAP = 'telesma/state/SECURITY_MAP.md'
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
MAX_BYTES = 1_000_000
WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$'
                       r'|(^|/)conftest\.py$')
SKIPPED_DIRS = re.compile(r'(^|/)(node_modules|vendor|dist|build|out|target|\.venv|venv|__pycache__|'
                          r'\.next|\.nuxt|\.svelte-kit|coverage|site-packages|telesma/checks|\.claude)/')
PY_CODE = re.compile(r'\.py$')
JS_CODE = re.compile(r'\.(ts|tsx|js|jsx|mjs|cjs)$')
CODE = re.compile(r'\.(py|ts|tsx|js|jsx|mjs|cjs|go|java|kt|rb|php|cs|vue|svelte)$')
MIGRATION = re.compile(r'(^|/)(migrations?|alembic|seeds?|db/migrate|supabase/migrations)/|\.sql$')

# --- Python: FastAPI, Flask, Starlette-like -------------------------------------------------------
PY_ROUTE_DECORATOR = re.compile(r'^\s*@(\w+)\.(get|post|put|patch|delete|head|options|api_route|route|websocket)\(')
PY_ROUTER = re.compile(r'^\s*(\w+)\s*(?::\s*[\w.\[\]]+)?\s*=\s*(?:fastapi\.|flask\.)?(APIRouter|Blueprint|FastAPI|Flask|Router)\(')
PY_DEF = re.compile(r'^\s*(?:async\s+)?def\s+\w+')
# --- JS / TS: Express, Hono, Fastify, Koa-router ------------------------------------------------
JS_ROUTE = re.compile(r'\b(\w+)\.(get|post|put|patch|delete|all|head|options)\(\s*([\'"`])(/[^\'"`]*)\3')
JS_USE = re.compile(r'\b(\w+)\.use\(\s*(?:([\'"`])([^\'"`]*)\2\s*,)?')
# --- Nest ---------------------------------------------------------------------------------------
NEST_CONTROLLER = re.compile(r'^\s*@Controller\(\s*(?:[\'"`]([^\'"`]*)[\'"`])?')
NEST_ROUTE = re.compile(r'^\s*@(Get|Post|Put|Patch|Delete|All|Head|Options)\(\s*(?:[\'"`]([^\'"`]*)[\'"`])?')

# A JS file is a server when it imports an HTTP framework — otherwise `api.get('/x')` is a client (axios)
JS_SERVER = re.compile(r'(?:\bimport\b|\brequire\(|\bfrom\b)[^\n]*[\'"](?:npm:|jsr:|https://deno\.land/x/)?@?'
                       r'(?:express|hono|fastify|koa|koa/router|koa-router|nestjs/common|elysia|polka|restify|h3|'
                       r'oak|hono/[\w-]+)[@/\'"]')
JS_CLIENTS = {'axios', 'http', 'https', 'fetch', 'client', 'request', 'superagent', 'ky', 'got', 'this', 'map',
              'cache', 'store', 'params', 'headers', 'searchParams', 'url', 'cookies', 'localStorage',
              'sessionStorage', 'formData', 'res', 'req', 'c', 'ctx'}
LITERAL = re.compile(r'''("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)''')


def git(root, *args, limit=60):
    try:
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=limit)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def read_file(root, p):
    try:
        full = os.path.join(root, p)
        if os.path.getsize(full) > MAX_BYTES:
            return None
        with open(full, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if b'\0' in data[:8192]:
        return None
    return data.decode('utf-8', 'replace')


def content_at_revision(root, rev, p):
    """File content at a revision; '' when the file was not there (new file = everything new)."""
    if rev == EMPTY_TREE:
        return ''
    t = git(root, 'show', f'{rev}:{p}')
    return t if t is not None else ''


def reference_point(root, point):
    """The revision against which something is "new". commit → HEAD; TELESMA_SINCE (CI) beats the
    rest; phase/ci → last telesma/phase-* tag, release → last v*; no tag — the first commit."""
    if point == 'commit':
        h = (git(root, 'rev-parse', '--verify', '-q', 'HEAD') or '').strip()
        return h or EMPTY_TREE
    since = os.environ.get('TELESMA_SINCE', '').strip()
    if since and git(root, 'rev-parse', '--verify', '-q', since + '^{commit}'):
        return since
    pattern = 'v[0-9]*' if point == 'release' else 'telesma/phase-*'
    t = (git(root, 'describe', '--tags', '--abbrev=0', '--match', pattern, 'HEAD') or '').strip()
    if t:
        return t
    first = (git(root, 'rev-list', '--max-parents=0', 'HEAD') or '').split()
    head = (git(root, 'rev-parse', 'HEAD') or '').strip()
    if not first or not head or head in first:
        return EMPTY_TREE
    return first[-1]


def is_code_file(p):
    return bool(CODE.search(p)) and not SKIPPED_DIRS.search(p) and not TEST_FILE.search(p)


# --- Paths ----------------------------------------------------------------------------------------

def canonical(path):
    """`/projects/{project_id}/` → `/projects/{}`; `:id`, `<int:id>`, `[id]`, `${id}` → `{}`."""
    s = re.sub(r'\$\{[^}]*\}', '{}', (path or '').strip())
    s = s.split('?')[0]
    seg = []
    for c in s.split('/'):
        if not c:
            continue
        if re.match(r'^(:\w+\??|\{[^}]*\}|<[^>]*>|\[[^\]]*\])$', c):
            seg.append('{}')
        else:
            seg.append(c)
    return '/' + '/'.join(seg)


def route_key(method, path):
    return f'{method.upper()} {canonical(path)}'


def path_matches(marker, route):
    """A red-team marker matches a route when the paths are equal or one is a suffix of the
    other on whole segments — the `/api` prefix from `include_router` is known only to the test."""
    a = [x for x in canonical(marker).split('/') if x]
    b = [x for x in canonical(route).split('/') if x]
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return bool(shorter) and longer[-len(shorter):] == shorter


# --- Joining brackets -----------------------------------------------------------------------------

def strip_literals(t):
    return LITERAL.sub('""', t)


def join_brackets(lines, i, max_lines=40):
    """From line i until the brackets opened on that line close → (text, last index)."""
    text, depth, j = [], 0, i
    while j < len(lines) and j < i + max_lines:
        w = lines[j]
        text.append(w)
        clean = strip_literals(w.split('#')[0] if PY_COMMENT_LINE.match(w) else w)
        depth += clean.count('(') + clean.count('[') + clean.count('{')
        depth -= clean.count(')') + clean.count(']') + clean.count('}')
        if depth <= 0:
            break
        j += 1
    return '\n'.join(text), min(j, len(lines) - 1)


PY_COMMENT_LINE = re.compile(r'^\s*[^\'"`]*#')


def first_literal(t):
    m = LITERAL.search(t)
    return m.group(0)[1:-1] if m else None


def indent_of(w):
    return len(w) - len(w.lstrip())


# --- Python ---------------------------------------------------------------------------------------

def py_routers(lines):
    """{variable: (prefix, call text)} — `router = APIRouter(prefix=…, dependencies=[…])`."""
    out = {}
    for i, w in enumerate(lines):
        m = PY_ROUTER.match(w)
        if not m:
            continue
        text, _ = join_brackets(lines, i)
        p = re.search(r'(?:prefix|url_prefix)\s*=\s*[\'"]([^\'"]*)[\'"]', text)
        out[m.group(1)] = (p.group(1) if p else '', text)
    return out


def py_routes(p, text):
    lines = text.split('\n')
    routers = py_routers(lines)
    out, i = [], 0
    while i < len(lines):
        w = lines[i]
        if not w.lstrip().startswith('@'):
            i += 1
            continue
        # decorator block + function signature
        start, decs, routes, j = i, [], [], i
        while j < len(lines) and lines[j].lstrip().startswith('@'):
            t, k = join_brackets(lines, j)
            decs.append(t)
            m = PY_ROUTE_DECORATOR.match(lines[j])
            if m:
                routes.append((m, t, j))
            j = k + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith('#')):
                j += 1
        if not routes or j >= len(lines) or not PY_DEF.match(lines[j]):
            i = max(j, i + 1)
            continue
        sig, k = join_brackets(lines, j)
        while k + 1 < len(lines) and not re.search(r':\s*(#.*)?$', lines[k]):
            k += 1
            sig += '\n' + lines[k]
        # end of body: first non-empty line indented ≤ the decorator
        ind = indent_of(lines[start])
        end = k + 1
        while end < len(lines):
            l2 = lines[end]
            if l2.strip() and not l2.lstrip().startswith('#') and indent_of(l2) <= ind:
                break
            end += 1
        for m, t, nr in routes:
            obj, kind = m.group(1), m.group(2)
            arg = t[t.index('(') + 1:]
            if re.match(r'\s*[rbuf]?["\']', arg):
                path = first_literal(arg) or ''
            else:
                mp = re.search(r'\b(?:path|rule)\s*=\s*[\'"]([^\'"]*)[\'"]', arg)
                path = mp.group(1) if mp else ''
            prefix, router_def = routers.get(obj, ('', ''))
            if kind in ('api_route', 'route'):
                mm = re.search(r'methods\s*=\s*[\[(]([^\])]*)', t)
                methods = re.findall(r'[\'"](\w+)[\'"]', mm.group(1)) if mm else ['GET']
            elif kind == 'websocket':
                methods = ['WS']
            else:
                methods = [kind]
            window = '\n'.join(decs) + '\n' + sig + '\n' + router_def
            for met in methods:
                out.append({'file': p, 'line': nr + 1, 'method': met.upper(),
                            'path': (prefix.rstrip('/') + '/' + path.lstrip('/')) if prefix else (path or '/'),
                            'window': window, 'start': start + 1, 'end': end, 'lang': 'py'})
        i = end
    return out


# --- JS / TS --------------------------------------------------------------------------------------

def js_window(lines, i, col):
    """Route call arguments up to where the handler starts (`=>`, `function`)."""
    text = lines[i][col:]
    j = i
    while not re.search(r'=>|\bfunction\b|\)\s*;?\s*$', text) and j + 1 < len(lines) and j < i + 12:
        j += 1
        text += '\n' + lines[j]
    m = re.search(r'=>|\bfunction\b', text)
    return text[:m.start()] if m else text


JS_FUNCTION = re.compile(r'(?:\bfunction\s+(\w+)\s*(?:<[^>]*>)?\s*\(|\b(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\()'
                         r'([^)]*)\)', re.S)


def js_uses(text):
    """[(object, prefix or None, call text)] — `x.use(…)` in the file."""
    lines = text.split('\n')
    out = []
    for i, w in enumerate(lines):
        for m in JS_USE.finditer(w):
            t, _ = join_brackets(lines, i, max_lines=8)
            out.append((m.group(1), m.group(3), t[t.find(m.group(0)):]))
    return out


_CALLERS = {}
_CONTEXT = {}
CREATES_SERVER = re.compile(r'new\s+Hono\b|\bRouter\(|\bexpress\(\)|\bfastify\(|new\s+(?:Koa)?Router\b')


def callers(root, p, name):
    k = (root, name)
    if k not in _CALLERS:
        files = (git(root, 'grep', '-l', '-w', '-e', name, '--', '*.ts', '*.tsx', '*.js', '*.jsx', '*.mjs')
                 or '').splitlines()
        _CALLERS[k] = [x for x in files if not TEST_FILE.search(x) and not SKIPPED_DIRS.search(x)]
    return [x for x in _CALLERS[k] if x != p]


def matching_uses(uses, obj, prefix):
    """Texts of `obj.use(…)` that apply under `prefix` (global, `*`, or a matching prefix)."""
    out = []
    for ob, pref, tx in uses:
        if ob != obj:
            continue
        clean = (pref or '').rstrip('*').rstrip('/')
        if pref is None or not clean or (prefix or '/').startswith(clean) or clean.startswith(prefix or '/'):
            out.append(tx)
    return out


def mount_context(root, p, text, depth=0):
    """(prefix, {object or '*': [use texts]}) — where a sub-app from file p gets its prefix and
    guards from. Two shapes, both seen on a Hono/Deno medical project:
      - mounting: `app.route("/doctor", createDoctorRoutes(…))` in main.ts → prefix `/doctor`,
        guards from the `app.use` calls that apply under it (and those inherited by main);
      - passing the object: `teamRoutes(routes, …)` in admin/index.tsx → prefix and guards of
        the calling file (`routes.use("*", requireRole("admin"))`).
    Without the prefix, routes of different modules share one key: on that project `GET /` 10
    times, the doctor's and the registrar's `GET /patients/:id` as one route. Up to three levels,
    via `git grep`."""
    k = (root, p)
    if not root or depth > 3:
        return '', {}
    if k in _CONTEXT:
        return _CONTEXT[k] or ('', {})
    _CONTEXT[k] = None                            # in progress — a call cycle ends with an empty context
    objects = {m.group(1) for m in JS_ROUTE.finditer(text)} - JS_CLIENTS
    creates = bool(CREATES_SERVER.search(text))
    result = ('', {})
    for m in JS_FUNCTION.finditer(text):
        name = m.group(1) or m.group(2)
        params = [x.split(':')[0].strip().lstrip('.') for x in m.group(3).split(',') if x.strip()]
        if not name:
            continue
        passes = objects & set(params)
        if not passes and not creates:
            continue                              # only functions that receive or build the route object
        for cp in callers(root, p, name):
            t = read_file(root, cp) or ''
            uses = js_uses(t)
            pref_c, inherited = mount_context(root, cp, t, depth + 1)
            mm = re.search(r'\b(\w+)\.(?:route|use)\(\s*([\'"`])([^\'"`]*)\2\s*,\s*(?:await\s+)?'
                           + re.escape(name) + r'\s*\(', t)
            if mm:
                lit = mm.group(3).rstrip('/')
                guards = matching_uses(uses, mm.group(1), lit) + inherited.get(mm.group(1), []) + inherited.get('*', [])
                result = ((pref_c.rstrip('/') + lit), {'*': guards})
                break
            mw = re.search(r'\b' + re.escape(name) + r'\s*\(([^)]*)\)', t)
            if mw and passes:
                args = [x.strip() for x in mw.group(1).split(',')]
                guards = {}
                for idx, arg in enumerate(args):
                    if idx < len(params) and params[idx] in objects and re.match(r'^\w+$', arg):
                        guards[params[idx]] = (matching_uses(uses, arg, '/') + inherited.get(arg, [])
                                               + inherited.get('*', []))
                if guards:
                    result = (pref_c, guards)
                    break
        if result != ('', {}):
            break
    _CONTEXT[k] = result
    return result


def js_routes(p, text, root=None):
    if not JS_SERVER.search(text):
        return []                                 # front end / HTTP client: `api.get('/users')` is a call, not a route
    lines = text.split('\n')
    uses = js_uses(text)                          # (object, prefix or None, text)
    mount_prefix, from_outside = mount_context(root, p, text)
    for ob, lst in from_outside.items():
        uses += [(ob, None, tx) for tx in lst]
    controller = None
    out, nest = [], []
    for i, w in enumerate(lines):
        if NEST_CONTROLLER.match(w):
            controller = i
        for m in JS_ROUTE.finditer(w):
            obj, method, path = m.group(1), m.group(2), m.group(4)
            if obj in JS_CLIENTS:
                continue
            window = js_window(lines, i, m.start())
            for ob, pref, t in uses:
                if ob != obj and ob != '*':
                    continue
                if pref is None or path.startswith(pref.rstrip('*').rstrip('/') or '/'):
                    window += '\n' + t
            end = i + 1
            while end < len(lines) and not JS_ROUTE.search(lines[end]) \
                    and not (lines[end].strip() and indent_of(lines[end]) == 0
                             and not lines[end].lstrip().startswith(('}', ')'))):
                end += 1
            full = (mount_prefix + ('' if path == '/' else path)) if mount_prefix else path
            out.append({'file': p, 'line': i + 1, 'method': method.upper(), 'path': full or '/',
                        'window': window, 'start': i + 1, 'end': end, 'lang': 'js'})
        m = NEST_ROUTE.match(w)
        if m and controller is not None:
            nest.append((i, m))
    if nest:
        # class decorators: the contiguous block around @Controller
        a = controller
        while a > 0 and lines[a - 1].lstrip().startswith('@'):
            a -= 1
        b = controller
        while b + 1 < len(lines) and not re.match(r'^\s*(export\s+)?(default\s+)?class\b', lines[b + 1]):
            b += 1
        cls = '\n'.join(lines[a:b + 1])
        pm = NEST_CONTROLLER.match(lines[controller])
        prefix = '/' + pm.group(1).strip('/') if pm and pm.group(1) else ''
        for n, (i, m) in enumerate(nest):
            a = i
            while a > 0 and lines[a - 1].lstrip().startswith('@'):
                a -= 1
            b = i
            while b + 1 < len(lines) and lines[b + 1].lstrip().startswith('@'):
                b += 1
            end = nest[n + 1][0] if n + 1 < len(nest) else len(lines)
            sc = prefix + ('/' + m.group(2).strip('/') if m.group(2) else '')
            out.append({'file': p, 'line': i + 1, 'method': m.group(1).upper(), 'path': sc or '/',
                        'window': cls + '\n' + '\n'.join(lines[a:b + 2]), 'start': a + 1, 'end': end,
                        'lang': 'js'})
    return out


def file_routes(p, text, root=None):
    """root (the repository) lets guards be pulled in from the calling file (JS) — without it the
    window covers only this file."""
    if not text:
        return []
    if PY_CODE.search(p):
        return py_routes(p, text)
    if JS_CODE.search(p):
        return js_routes(p, text, root)
    return []


# --- Guard candidates (for the map skeleton only) -------------------------------------------------

GUARD_LIKE = re.compile(r'auth|user|role|member|admin|super|perm|login|guard|owner|access|scope|require|'
                        r'protect|ensure|verify|tenant|context|principal|identity|claims|current|jwt|session_user',
                        re.I)
NOT_GUARD = re.compile(r'^(get_session|get_db|db|session|get_async_session|async_session|request|response|'
                       r'Depends|Security|Request|Response|async|await|function|return|const|let|var|new|true|'
                       r'false|null|undefined|UseGuards|Controller|SetMetadata)$|csrf|valid|schema|settings|config|service|repo|storage|limit|'
                       r'rate|cache|logger|json|body|query|param', re.I)


JS_TOKEN = re.compile(r'''"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`|[A-Za-z_$][\w$]*|=>|[(),.]''')
JS_SEGMENT = re.compile(r'\b\w+\.(?:get|post|put|patch|delete|all|head|options|use)\(')
PY_CANDIDATE = re.compile(r'(?:Depends|Security)\(\s*(\w+)(?:\(\s*[rbuf]?["\']([^"\']+)["\'])?')
DECORATOR_CANDIDATE = re.compile(r'^\s*@(\w+)(?:\(\s*["\'`]([^"\'`]+)["\'`])?', re.M)


def js_arguments(segment):
    """[(name, literal or None)] — TOP-LEVEL arguments of the `x.get(…)`/`x.use(…)` call: a
    middleware reference (`requireAuth`) or a factory (`requireRole("doctor")`). Names nested
    deeper are arguments of guards (`requireAuth(authorize)`) or handler parameters (`async (context)`)."""
    tok = JS_TOKEN.findall(segment)
    out, depth, i = [], 0, 0
    while i < len(tok):
        t = tok[i]
        if t == '(':
            depth += 1
        elif t == ')':
            depth -= 1
            if depth <= 0:
                break
        elif t == '=>' or (t in ('async', 'function') and depth == 1):
            break
        elif depth == 1 and re.match(r'^[A-Za-z_$]', t) and (i == 0 or tok[i - 1] != '.'):
            nxt = tok[i + 1] if i + 1 < len(tok) else ''
            if nxt == '(':
                lit = tok[i + 2] if i + 2 < len(tok) and tok[i + 2][:1] in '"\'`' else None
                out.append((t, lit[1:-1] if lit else None))
            elif nxt != '.':
                out.append((t, None))
        i += 1
    return out


def guard_candidates(route):
    """[(role id, guard token)] from the window — a heuristic ONLY for the map skeleton (the check
    takes guards from the map). A factory with a literal yields its own role:
    `requireRole("doctor")` and `requireRole("nurse")` are two roles, not one `requireRole` —
    without this, five staff roles on a Hono/Deno medical project merged into one."""
    window = route['window']
    pairs = []
    if route['lang'] == 'py':
        pairs = PY_CANDIDATE.findall(window) + DECORATOR_CANDIDATE.findall(window)
    elif '@Controller(' in window:
        pairs = DECORATOR_CANDIDATE.findall(window)
        pairs += [(n, None) for n in re.findall(r'@UseGuards\(([^)]*)\)', window) for n in re.findall(r'\w+', n)]
    else:
        for m in JS_SEGMENT.finditer(window):
            pairs += js_arguments(window[m.end() - 1:])
    out = []
    for name, lit in pairs:
        lit = lit or None
        if NOT_GUARD.search(name) or not GUARD_LIKE.search(name):
            continue
        if name in ('get', 'post', 'put', 'patch', 'delete', 'route', 'api_route', 'use', 'app', 'router') \
                or re.search(r'(router|_app|_bp|blueprint)$', name, re.I):
            continue                              # the decorator's object (`@requirement_router.get`), not a guard
        pair = (f'{name}:{lit}', f'{name}("{lit}")') if lit else (name, name)
        if pair not in out:
            out.append(pair)
    return out


def contains_guard(window, token):
    """A token from the map in the route window; any quotes (`requireRole('doctor')` = `requireRole("doctor")`)."""
    norm = lambda t: re.sub(r'[\'`]', '"', t)
    tok, window = norm(token), norm(window)
    if tok in window:
        return True
    # `requireRole("doctor")` also matches `requireRole("doctor", "nurse")` — the doctor has access too
    return tok.endswith('")') and re.search(re.escape(tok[:-1]) + r'\s*,', window) is not None


# --- Map ------------------------------------------------------------------------------------------

def table_rows(block):
    out = []
    for w in block.split('\n'):
        w = w.strip()
        if not w.startswith('|') or re.match(r'^\|[\s:|-]+\|$', w):
            continue
        out.append([k.strip() for k in w.strip('|').split('|')])
    return out[1:] if out else []                 # first row = header


def is_empty(v):
    return v.strip() in ('', '—', '-', '–', 'none', 'no')


def read_map(root):
    """None when the file is missing. Otherwise {'roles': {id: [tokens]}, 'routes': {key: {...}},
    'hosts', 'env', 'db', 'global', 'session'}."""
    t = read_file(root, MAP)
    if t is None:
        return None
    t = re.sub(r'<!--.*?-->', '', t, flags=re.S)
    sections = {}
    for m in re.finditer(r'^## +(.+?)[ \t]*\n(.*?)(?=^## |\Z)', t, re.M | re.S):
        sections[m.group(1).strip().lower()] = m.group(2)
    s = re.search(r'^- \*\*Session\*\*:[ \t]*(.*?)[ \t]*$', t, re.M)
    smap = {'roles': {}, 'routes': {}, 'hosts': set(), 'env': set(), 'db': [], 'global': set(),
            'session': (s.group(1).strip().lower() if s else '?')}
    for w in table_rows(sections.get('roles', '')):
        if not w or not w[0]:
            continue
        rid = w[0].strip('`').strip()
        guard = w[2] if len(w) > 2 else ''
        tokens = re.findall(r'`([^`]+)`', guard) or ([x.strip() for x in guard.split(',')] if not is_empty(guard) else [])
        tokens = [x for x in tokens if x and not is_empty(x)]
        if any(x.lower() in ('(global)', 'global', '(outside route)', '(outside the route)') for x in tokens):
            smap['global'].add(rid)
        smap['roles'][rid] = [x for x in tokens if not x.startswith('(')]
    for nr, w in enumerate(table_rows(sections.get('routes', ''))):
        if not w or not w[0]:
            continue
        m = re.match(r'^`?([A-Za-z]+)\s+(\S+?)`?$', w[0])
        if not m:
            continue
        smap['routes'][route_key(m.group(1), m.group(2))] = {
            'route': f'{m.group(1).upper()} {m.group(2)}',
            'roles': w[1] if len(w) > 1 else '?',
            'ownership': w[2] if len(w) > 2 else '?'}
    for w in table_rows(sections.get('outbound', '')):
        if len(w) < 2:
            continue
        kind, value = w[0].strip('`').lower(), w[1].strip('`').strip()
        if kind == 'host':
            smap['hosts'].add(value.lower())
        elif kind == 'env':
            smap['env'].add(value)
        elif kind == 'db' and value:
            smap['db'].append(re.sub(r'\s+', ' ', value).lower())
    return smap


def alternatives(roles):
    """`a + b, c` → [['a','b'], ['c']]; '?' → None (undecided)."""
    r = (roles or '').strip()
    if r in ('', '?'):
        return None
    out, alts, depth, cur = [], [], 0, ''
    for ch in r:                                  # a comma inside brackets (`role(OWNER, CLIENT)`) does not split
        depth += ch == '('
        depth -= ch == ')'
        if ch == ',' and depth <= 0:
            alts.append(cur)
            cur = ''
        else:
            cur += ch
    alts.append(cur)
    for alt in alts:
        members = [x.strip().strip('`') for x in alt.split('+') if x.strip()]
        members = [re.sub(r'\(.*\)$', '', x).strip() for x in members]
        if members:
            out.append(members)
    return out or None


def is_public(roles):
    alt = alternatives(roles)
    return bool(alt) and any(a == ['anonymous'] for a in alt)
