#!/usr/bin/env python3
"""Check `dependencies` — new packages in manifests vs registries (npm, PyPI, JSR).

List of files on stdin; only manifests are taken from it. A package is "new" when it was
not in the HEAD version of the file. Findings as JSON lines on stdout.
"""
import datetime
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
except ImportError:          # Python < 3.11 — pyproject.toml is skipped, the rest works
    tomllib = None

AGE_BLOCKS = 7
AGE_WARNS = 30
FEW_DOWNLOADS = 50
TYPO_SHARE = 0.01

# The most used packages — the reference for typos. Deliberately a short list: a typo
# of a name nobody uses tempts nobody.
POPULAR = {
    'npm': '''react react-dom next vue svelte angular express fastify koa hono axios lodash underscore
        moment dayjs date-fns uuid nanoid zod yup joi ajv dotenv chalk commander yargs debug
        typescript ts-node tsx esbuild vite webpack rollup babel-core eslint prettier jest vitest
        mocha chai sinon supertest playwright puppeteer cypress jsonwebtoken bcrypt bcryptjs
        passport cors helmet body-parser cookie-parser multer mongoose sequelize prisma typeorm
        knex pg mysql mysql2 sqlite3 redis ioredis socket.io ws graphql apollo-server rxjs
        tailwindcss postcss autoprefixer sass styled-components classnames clsx immer zustand
        redux react-redux react-router react-router-dom swr node-fetch cross-fetch form-data
        semver glob rimraf mkdirp fs-extra minimist inquirer ora execa nodemon concurrently
        cross-env husky lint-staged pino winston bunyan morgan sharp jimp cheerio jsdom
        marked markdown-it highlight.js crypto-js nodemailer stripe openai i18next'''.split(),
    'pypi': '''requests urllib3 httpx aiohttp flask django fastapi starlette uvicorn gunicorn
        pydantic sqlalchemy alembic psycopg2 psycopg2-binary psycopg asyncpg pymysql redis celery
        numpy pandas scipy matplotlib seaborn scikit-learn torch tensorflow keras transformers
        pillow opencv-python beautifulsoup4 lxml selenium playwright pytest pytest-cov
        pytest-asyncio mock coverage tox black ruff flake8 pylint mypy isort pre-commit
        python-dotenv pyyaml toml click typer rich tqdm jinja2 markupsafe werkzeug itsdangerous
        cryptography pyjwt bcrypt passlib paramiko boto3 botocore awscli google-cloud-storage
        azure-storage-blob openai anthropic tiktoken langchain python-dateutil pytz arrow
        attrs dataclasses-json marshmallow orjson ujson simplejson six setuptools wheel pip
        certifi idna charset-normalizer chardet docker kubernetes grpcio protobuf sentry-sdk
        structlog loguru prometheus-client opentelemetry-api tomli typing-extensions anyio'''.split(),
}


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


# --- Manifest parsing ------------------------------------------------------------

def norm_py(n):
    return re.sub(r'[-_.]+', '-', n).lower()


def outside_registry(spec):
    s = spec.strip()
    return bool(re.match(r'^(git\+|git:|github:|gitlab:|bitbucket:|https?:|ssh:)', s)
                or re.match(r'^[\w.-]+/[\w.-]+(#.*)?$', s))     # npm: user/repo


def from_package_json(text):
    """{name: spec} from all dependency groups."""
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    out = {}
    for group in ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'):
        for n, spec in (d.get(group) or {}).items():
            if isinstance(spec, str):
                out[n] = spec
    return out


def from_requirements(text):
    """({name: spec}, extra indexes)."""
    out, indexes = {}, []
    for line in text.splitlines():
        l = line.split(' #', 1)[0].strip()
        if not l or l.startswith('#'):
            continue
        if re.match(r'^(--extra-index-url|--index-url|-i)\b', l):
            indexes.append(l)
            continue
        if l.startswith('-e ') or l.startswith('--editable'):
            target = l.split(None, 1)[1] if ' ' in l else ''
            m = re.search(r'#egg=([\w.-]+)', target)
            if m and outside_registry(target):
                out[norm_py(m.group(1))] = target
            continue
        if l.startswith('-'):
            continue
        m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$', l)
        if m:
            rest = m.group(3).strip()
            out[norm_py(m.group(1))] = rest[1:].strip() if rest.startswith('@') else rest
    return out, indexes


def pep508_name(s):
    m = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(@\s*(\S+))?', s)
    if not m:
        return None, ''
    return norm_py(m.group(1)), (m.group(4) or '')


def from_pyproject(text):
    if tomllib is None:
        return {}
    try:
        d = tomllib.loads(text)
    except Exception:
        return {}
    out = {}
    proj = d.get('project') or {}
    lists = [proj.get('dependencies') or []]
    lists += list((proj.get('optional-dependencies') or {}).values())
    lists += [g for g in (d.get('dependency-groups') or {}).values()]
    for lst in lists:
        for s in lst:
            if isinstance(s, str):
                n, url = pep508_name(s)
                if n:
                    out[n] = url
    poetry = (d.get('tool') or {}).get('poetry') or {}
    groups = [poetry.get('dependencies') or {}, poetry.get('dev-dependencies') or {}]
    groups += [g.get('dependencies') or {} for g in (poetry.get('group') or {}).values()]
    for g in groups:
        for n, spec in g.items():
            if n.lower() == 'python':
                continue
            if isinstance(spec, dict) and (spec.get('git') or spec.get('url')):
                out[norm_py(n)] = spec.get('git') or spec.get('url')
            elif isinstance(spec, dict) and spec.get('path'):
                continue
            else:
                out[norm_py(n)] = spec if isinstance(spec, str) else ''
    for n, src in (((d.get('tool') or {}).get('uv') or {}).get('sources') or {}).items():
        if isinstance(src, dict) and (src.get('git') or src.get('url')):
            out[norm_py(n)] = src.get('git') or src.get('url')
    return out


def strip_jsonc_comments(t):
    t = re.sub(r'/\*.*?\*/', '', t, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$|(?<=[,{\[\s])//[^\n"]*$', '', t)


def from_deno(text):
    """{(ecosystem, name): spec} from the imports map."""
    try:
        d = json.loads(strip_jsonc_comments(text))
    except ValueError:
        return {}
    out = {}
    for spec in (d.get('imports') or {}).values():
        if not isinstance(spec, str):
            continue
        m = re.match(r'^(npm|jsr):(@?[^@/]+(?:/[^@/]+)?)(?:@.*)?$', spec)
        if m:
            out[('npm' if m.group(1) == 'npm' else 'jsr', m.group(2))] = spec
        elif spec.startswith('http'):
            out[('url', spec)] = spec
    return out


def manifest(path, text):
    """[(ecosystem, name, spec)], [index warnings]"""
    base = os.path.basename(path)
    if base == 'package.json':
        return [('npm', n, s) for n, s in from_package_json(text).items()], []
    if re.match(r'^requirements.*\.(txt|in)$', base):
        d, indexes = from_requirements(text)
        return [('pypi', n, s) for n, s in d.items()], indexes
    if base == 'pyproject.toml':
        return [('pypi', n, s) for n, s in from_pyproject(text).items()], []
    if base in ('deno.json', 'deno.jsonc'):
        return [(e, n, s) for (e, n), s in from_deno(text).items()], []
    return None, []


def from_head(root, path):
    try:
        r = subprocess.run(['git', '-C', root, 'show', f'HEAD:{path}'], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return r.stdout if r.returncode == 0 else ''


def private_scopes(root):
    """npm scopes with their own registry in .npmrc — their packages are not in the public one."""
    try:
        with open(os.path.join(root, '.npmrc'), encoding='utf-8') as f:
            return set(re.findall(r'^\s*(@[\w.-]+):registry\s*=', f.read(), re.M))
    except OSError:
        return set()


# --- Registries ------------------------------------------------------------------------

def days_since(iso):
    try:
        t = datetime.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - t).days


def npm_info(name):
    code, d = fetch(f'{address("npm")}/{name.replace("/", "%2F")}')
    if code == 404 or not d:
        return {'exists': False}
    latest = (d.get('dist-tags') or {}).get('latest')
    version = (d.get('versions') or {}).get(latest) or {}
    scripts = sorted(k for k in (version.get('scripts') or {}) if k in ('preinstall', 'install', 'postinstall'))
    info = {'exists': True, 'created': (d.get('time') or {}).get('created'),
            'scripts': scripts, 'deprecated': bool(version.get('deprecated'))}
    try:
        code, p = fetch(f'{address("npm_downloads")}/{name}')
        info['downloads'] = (p or {}).get('downloads') if code != 404 else 0
    except NoNetwork:
        info['downloads'] = None
    return info


def pypi_info(name):
    code, d = fetch(f'{address("pypi")}/{name}/json')
    if code == 404 or not d:
        return {'exists': False}
    times = [f.get('upload_time_iso_8601') for files in (d.get('releases') or {}).values()
             for f in files if f.get('upload_time_iso_8601')]
    return {'exists': True, 'created': min(times) if times else None}


def jsr_info(name):
    m = re.match(r'^@([^/]+)/(.+)$', name)
    if not m:
        return {'exists': False}
    code, d = fetch(f'{address("jsr")}/scopes/{m.group(1)}/packages/{m.group(2)}')
    if code == 404 or not d:
        return {'exists': False}
    return {'exists': True, 'created': d.get('createdAt')}


INFO = {'npm': npm_info, 'pypi': pypi_info, 'jsr': jsr_info}
REGISTRY = {'npm': 'npm', 'pypi': 'PyPI', 'jsr': 'JSR'}


def levenshtein(a, b):
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similar(eco, name):
    if name.startswith('@'):
        return None      # a scope is a separate namespace; `@nestjs/core` is not a typo of `cors`
    lst = POPULAR.get('pypi' if eco == 'pypi' else 'npm', [])
    bare = name.lower()
    if bare in lst or name.lower() in lst:
        return None
    for p in lst:
        threshold = 1 if len(p) < 8 else 2
        if len(bare) >= 4 and levenshtein(bare, p) <= threshold:
            return p
        if re.sub(r'[-_.]', '', bare) == re.sub(r'[-_.]', '', p):
            return p
    return None


# --- Main ------------------------------------------------------------------------------

def main():
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    files = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    new = {}            # (eco, name) → (file, spec)
    for p in files:
        base = os.path.basename(p)
        if base == '.npmrc':
            try:
                with open(os.path.join(root, p), encoding='utf-8') as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            for m in re.finditer(r'^\s*registry\s*=\s*(\S+)', text, re.M):
                if 'registry.npmjs.org' not in m.group(1):
                    emit(file=p, line=None, rule='other-registry', severity='warn',
                         message=f'default npm registry changed to {m.group(1)} — make sure that is intended',
                         content_fingerprint=m.group(1))
            continue
        if manifest(p, '')[0] is None:
            continue                  # not a manifest — not read (WAV, PNG in a commit broke decoding)
        try:
            with open(os.path.join(root, p), encoding='utf-8') as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        now, indexes = manifest(p, text)
        if now is None:
            continue
        old, _ = manifest(p, from_head(root, p))
        before = {(e, n) for e, n, _ in (old or [])}
        for ix in indexes:
            emit(file=p, line=None, rule='extra-index', severity='warn',
                 message=f'"{ix.split()[0]}" — a package of the same name in two indexes is the '
                         f'dependency confusion route; make sure internal names are reserved',
                 content_fingerprint=ix)
        for eco, name, spec in now:
            if (eco, name) not in before:
                new[(eco, name)] = (p, spec)

    private = private_scopes(root)
    to_check = []
    for (eco, name), (path, spec) in sorted(new.items()):
        if eco == 'url' or outside_registry(spec or ''):
            emit(file=path, line=None, rule='outside-registry', severity='warn',
                 message=f'{name}: dependency from outside the registry ({(spec or name)[:80]}) — no version '
                         f'history and no registry checks; pin it to a commit/checksum',
                 content_fingerprint=f'{eco}:{name}')
            continue
        if eco == 'npm' and name.startswith('@') and name.split('/')[0] in private:
            continue
        if re.match(r'^(file|link|workspace|portal|patch):', spec or ''):
            continue
        to_check.append((eco, name, path))
    if not to_check:
        return 0

    cache = Cache('registries')

    def check(el):
        eco, name, _ = el
        key = f'{eco}:{name}'
        cached = cache.get(key)
        if cached is not None:
            return el, cached
        try:
            info = INFO[eco](name)
        except NoNetwork:
            return el, None
        cache.put(key, info, 86400 if info.get('exists') else 3600)
        return el, info

    unchecked = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check, to_check))

    def original_downloads(pair):
        eco, model = pair
        key = f'downloads:{eco}:{model}'
        z = cache.get(key)
        if z is not None:
            return pair, z
        try:
            code, d = fetch(f'{address("npm_downloads")}/{model}')
        except NoNetwork:
            return pair, None
        n = (d or {}).get('downloads') if code != 404 else None
        if n is not None:
            cache.put(key, n, 7 * 86400)
        return pair, n

    models = {(eco, w) for (eco, name, _), info in results
              if eco == 'npm' and info and info.get('exists') for w in [similar(eco, name)] if w}
    with ThreadPoolExecutor(max_workers=4) as ex:
        model_downloads = dict(ex.map(original_downloads, sorted(models)))
    cache.save()

    for (eco, name, path), info in results:
        reg = REGISTRY[eco]
        fp = f'{eco}:{name}'
        if info is None:
            unchecked.append(name)
            continue
        if not info.get('exists'):
            emit(file=path, line=None, rule='not-found', severity='block',
                 message=f'{name}: the package is not in the {reg} registry — an invented name or a typo; '
                         f'anyone can register such a name',
                 content_fingerprint=fp + ':not-found')
            continue
        age = days_since(info.get('created'))
        downloads = info.get('downloads')
        model = similar(eco, name)
        if model:
            # A typosquat has downloads precisely because people make mistakes (`expres`: ~8.5k/week
            # against 169M for `express`) — an absolute threshold let it through. What counts is the
            # ratio to the original: < 1% of its downloads is a package that lives off typos.
            original = model_downloads.get((eco, model))
            small_share = (downloads is not None and original and downloads < original * TYPO_SHARE)
            suspicious = ((age is not None and age < 90) or (downloads is not None and downloads < 1000)
                          or bool(small_share))
            emit(file=path, line=None, rule='similar-to-popular',
                 severity='block' if suspicious else 'warn',
                 message=f'{name}: name deceptively similar to "{model}"'
                         + (f' (the package is {age} days old' + (f', {downloads} downloads/week' if downloads is not None else '')
                            + (f' against {original} for the original' if original else '') + ')'
                            if suspicious else '') + ' — are you sure this is the package?',
                 content_fingerprint=fp + ':similar')
        if age is not None and age < AGE_BLOCKS:
            emit(file=path, line=None, rule='fresh-package', severity='block',
                 message=f'{name}: the package has existed in {reg} for {age} days — too young to trust; '
                         f'wait or ask the human for an exception',
                 content_fingerprint=fp + ':fresh')
        elif age is not None and age < AGE_WARNS:
            emit(file=path, line=None, rule='young-package', severity='warn',
                 message=f'{name}: the package is {age} days old', content_fingerprint=fp + ':young')
        if downloads is not None and downloads < FEW_DOWNLOADS:
            emit(file=path, line=None, rule='few-downloads', severity='warn',
                 message=f'{name}: {downloads} downloads last week — hardly anyone uses it',
                 content_fingerprint=fp + ':downloads')
        if info.get('scripts'):
            emit(file=path, line=None, rule='install-scripts', severity='warn',
                 message=f'{name}: {", ".join(info["scripts"])} — code run on install',
                 content_fingerprint=fp + ':scripts')
        if info.get('deprecated'):
            emit(file=path, line=None, rule='deprecated', severity='warn',
                 message=f'{name}: the latest version is marked deprecated in {reg}',
                 content_fingerprint=fp + ':deprecated')

    if unchecked:
        emit(file=to_check[0][2], line=None, rule='not-checked', severity='warn',
             message=f'registry unreachable — not checked: {", ".join(unchecked[:10])}'
                     + (' …' if len(unchecked) > 10 else ''),
             content_fingerprint='not-checked:' + ','.join(sorted(unchecked)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
