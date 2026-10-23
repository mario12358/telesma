#!/usr/bin/env python3
"""Check `hygiene` — file list on stdin, JSON findings one per line on stdout.

Things that should not end up in the repository: build directories, a 5 MB file,
a manifest changed without its lockfile, floating versions, binaries in code directories,
a minified bundle, IDE files, visual artifacts while committing them is off,
no .gitignore.

The runner filters files > 1 MB, lockfiles and `*.min.*` out of stdin, and with
`git add x && git commit` the file x is not in the index yet — so the list for the
path and size rules is assembled from three sources: stdin ∪ index ∪ changes
against HEAD (at ci: the diff from the branch base). Only that way does a 6 MB database
dump added a moment earlier with `git add` stand a chance of being noticed.
"""
import json
import os
import re
import subprocess
import sys

TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|e2e)/|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$|_test\.[^/]+$')
BUILD_DIR = re.compile(r'(^|/)(node_modules|dist|build|out|\.venv|venv|__pycache__|coverage|htmlcov|'
                       r'\.next|\.nuxt|\.pytest_cache|\.mypy_cache|\.ruff_cache)/')
# `target/` is a build directory only in Rust/Java — in other projects it can be an ordinary directory
TARGET = re.compile(r'(^|/)target/')
TARGET_MANIFESTS = ('Cargo.toml', 'pom.xml', 'build.gradle', 'build.gradle.kts')
JUNK = [('*.pyc', re.compile(r'\.pyc$')), ('*.pyo', re.compile(r'\.pyo$')),
        ('.DS_Store', re.compile(r'(^|/)\.DS_Store$'))]
CODE_DIR = re.compile(r'(^|/)(src|app|lib|backend|frontend|pkg|cmd)/')
ASSET = re.compile(r'\.(png|jpe?g|gif|webp|ico|svg|woff2?|ttf|otf|wasm)$|(^|/)bun\.lockb$')
PDF_IN_DOCS = re.compile(r'(^|/)docs/.*\.pdf$')
BUNDLE = re.compile(r'\.(m?js|cjs|css)$')
MINIFIED_BY_NAME = re.compile(r'\.min\.[^/]+$')
VENDOR = re.compile(r'(^|/)vendor/')
MAX_BUNDLE_LINE = 5000
IDEA = re.compile(r'(^|/)\.idea/')
VSCODE = re.compile(r'(^|/)\.vscode/([^/]+)$')
VSCODE_ALLOWED = {'extensions.json', 'launch.json', 'tasks.json', 'settings.json'}
ABSOLUTE_PATH = re.compile(r'/Users/|/home/|[A-Za-z]:\\')
IDE_LOOSE = re.compile(r'\.sw[po]$|~$|(^|/)Thumbs\.db$')
CODE = re.compile(r'\.(py|js|jsx|ts|tsx|mjs|cjs|java|kt|go|rb|php|rs|cs|swift|scala|sh|sql|vue|svelte)$')
# manifest → lockfiles in the same directory, in search order
LOCKFILE = {
    'package.json': ['package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lockb', 'bun.lock'],
    'pyproject.toml': ['poetry.lock', 'uv.lock', 'pdm.lock'],
    'Cargo.toml': ['Cargo.lock'],
    'go.mod': ['go.sum'],
    'Gemfile': ['Gemfile.lock'],
    'composer.json': ['composer.lock'],
    'deno.json': ['deno.lock'],
    'deno.jsonc': ['deno.lock'],
}
REQUIREMENTS = re.compile(r'(^|/)requirements[^/]*\.txt$')
NPM_KEYS = ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies')
GIT_WITHOUT_REF = re.compile(r'^(git\+|git://|github:|gitlab:|bitbucket:|https?://(github|gitlab|bitbucket)\.(com|org)/)')
# TOML sections whose change requires a lockfile rebuild (pyproject + Cargo)
TOML_DEPENDENCY_SECTION = re.compile(
    r'^(project|project\.optional-dependencies|dependency-groups|tool\.poetry\.dependencies|'
    r'tool\.poetry\.dev-dependencies|tool\.poetry\.group\.[^.\]]+\.dependencies|tool\.uv\.sources|'
    r'dependencies|dev-dependencies|build-dependencies|workspace\.dependencies|target\..+\.dependencies|'
    r'(dev-|build-)?dependencies\.[^\]]+)$')
# TOML sections with PRODUCTION dependencies — only there does a floating version warn
TOML_PRODUCTION_SECTION = re.compile(r'^(tool\.poetry\.dependencies|dependencies|dependencies\.[^\]]+)$')


def emit(**z):
    print(json.dumps(z, ensure_ascii=False))


def git(root, *args):
    try:
        r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def lines(s):
    return [x for x in (s or '').splitlines() if x.strip()]


def read(root, p, size=None):
    try:
        with open(os.path.join(root, p), 'rb') as f:
            return f.read(size) if size else f.read()
    except OSError:
        return None


def text(root, p):
    data = read(root, p)
    return None if data is None or b'\0' in data[:8192] else data.decode('utf-8', 'replace')


def name_list(names, max_=5):
    return ', '.join(names[:max_]) + (f' (+{len(names) - max_})' if len(names) > max_ else '')


class Scope:
    """What actually goes into the commit / CI scope — beyond what the runner passed."""

    def __init__(self, root, point):
        self.root, self.point = root, point
        self.index = set(lines(git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR')))
        self.vs_head = set(lines(git(root, 'diff', '--name-only', '--diff-filter=ACMR', 'HEAD')))
        self.base = self.ci_base() if point == 'ci' else None
        self.ci_scope = set(lines(git(root, 'diff', '--name-only', '--diff-filter=ACMR',
                                      f'{self.base}...HEAD'))) if self.base else set()

    def ci_base(self):
        since = os.environ.get('TELESMA_SINCE')
        if since:
            return since
        head = (git(self.root, 'rev-parse', 'HEAD') or '').strip()
        for ref in ('origin/HEAD', 'origin/main', 'origin/master', 'main', 'master'):
            mb = (git(self.root, 'merge-base', 'HEAD', ref) or '').strip()
            if mb and mb != head:
                return mb
        return 'HEAD~1' if git(self.root, 'rev-parse', '--verify', '-q', 'HEAD~1') else None

    def extra(self):
        return self.index | self.vs_head | self.ci_scope

    def changed(self, p):
        """Whether the file has ANY change in scope — at commit also an unstaged one:
        `git add package.json package-lock.json && git commit` has both outside the index
        at hook time, and the runner cut the lockfile from stdin; the working-tree change is the only trace."""
        return p in (self.ci_scope if self.point == 'ci' else self.vs_head | self.index)

    def tracked(self, p):
        return bool(lines(git(self.root, 'ls-files', '--', p)))

    def previous_version(self, p):
        ref = self.base if self.point == 'ci' else 'HEAD'
        return git(self.root, 'show', f'{ref}:{p}') if ref else None


# --- build-dir / file-too-large ----------------------------------------------

def build_dir(p, root):
    """Group key (directory path or file pattern) or None."""
    m = BUILD_DIR.search(p)
    if m:
        return p[:m.end() - 1]
    m = TARGET.search(p)
    if m:
        above = os.path.join(root, p[:m.start()].rstrip('/') if m.start() else '')
        if any(os.path.isfile(os.path.join(above, mf)) for mf in TARGET_MANIFESTS):
            return p[:m.end() - 1]
    for key, pattern in JUNK:
        if pattern.search(p):
            return key
    return None


def by_group(groups, rule, severity, message):
    """One finding per directory: first file + counter. Fingerprint = group key, without the file —
    the exception "this directory is deliberately in the repo" has to survive a change of the first file in the group."""
    for key, files in sorted(groups.items()):
        more = f' (+{len(files) - 1} more in {key})' if len(files) > 1 else ''
        emit(file=files[0], line=None, rule=rule, severity=severity, file_fingerprint=False,
             message=message(key) + more, content_fingerprint=key)


def build_dirs(root, files):
    groups = {}
    for p in files:
        key = build_dir(p, root)
        if key:
            groups.setdefault(key, []).append(p)
    by_group(groups, 'build-dir', 'block',
             lambda k: f'build output / cache ({k}) in the commit — `git rm -r --cached {k}` and add it to .gitignore')


def sizes(root, files, artifacts_dir, commit_artifacts):
    limit_mb = float(os.environ.get('TELESMA_HYGIENE_MAX_MB') or 5)
    for p in files:
        try:
            mb = os.path.getsize(os.path.join(root, p)) / 1_000_000
        except OSError:
            continue
        if mb <= limit_mb:
            continue
        # A recording from telesma/artifacts/flows/ with `Commit artifacts: yes` is a deliberate decision (section 0.5):
        # we do not block, we remind about LFS from 50 MB
        if commit_artifacts and artifacts_dir and p.startswith(artifacts_dir):
            if mb > 50:
                emit(file=p, line=None, rule='file-too-large', severity='warn',
                     message=f'artifact {mb:.1f} MB — above 50 MB consider Git LFS (section 0.5)', content_fingerprint=p)
            continue
        emit(file=p, line=None, rule='file-too-large', severity='block',
             message=f'file {mb:.1f} MB (limit {limit_mb:g} MB) — do not commit it: keep the data outside the repo or in Git LFS, '
                     f'add it to .gitignore (limit: TELESMA_HYGIENE_MAX_MB)', content_fingerprint=p)


# --- lockfile-stale ------------------------------------------------------------

def json_without_comments(t):
    try:
        return json.loads(t)
    except ValueError:
        try:
            return json.loads(re.sub(r'^\s*//.*$', '', t, flags=re.M))      # deno.jsonc
        except ValueError:
            return None


def toml_lines(t):
    """[(section, logical line)] — multi-line arrays joined, comments and blanks skipped."""
    out, section, buffer, depth = [], '', '', 0
    for line in t.splitlines():
        s = re.sub(r'(^|\s)#.*$', '', line).strip()
        if not s:
            continue
        if not buffer and s.startswith('['):
            m = re.match(r'^\[\[?\s*([^\]]+?)\s*\]\]?', s)
            section = m.group(1).strip() if m else s
            continue
        buffer = (buffer + ' ' + s).strip() if buffer else s
        depth += s.count('[') - s.count(']') + s.count('{') - s.count('}')
        if depth <= 0:
            out.append((section, buffer))
            buffer, depth = '', 0
    if buffer:
        out.append((section, buffer))
    return out


def manifest_dependencies(name, t):
    """The set of dependency-section entries — equal old and new sets mean the manifest change
    (project version, scripts) does not need the lockfile. None = cannot read it."""
    if name in ('package.json', 'composer.json', 'deno.json', 'deno.jsonc'):
        d = json_without_comments(t)
        if not isinstance(d, dict):
            return None
        keys = {'package.json': NPM_KEYS, 'composer.json': ('require', 'require-dev')}.get(name, ('imports', 'scopes'))
        out = set()
        for k in keys:
            block = d.get(k) or {}
            out |= {f'{k}:{n}={json.dumps(w, sort_keys=True)}' for n, w in (block.items() if isinstance(block, dict) else [])}
        return out
    if name in ('pyproject.toml', 'Cargo.toml'):
        out = set()
        for section, line in toml_lines(t):
            if not TOML_DEPENDENCY_SECTION.match(section):
                continue
            if section == 'project' and not re.match(r'^dependencies\s*=', line):
                continue
            out.add(f'{section}|{line}')
        return out
    if name == 'go.mod':
        out, in_block = set(), None
        for line in t.splitlines():
            s = line.split('//')[0].strip()
            if not s:
                continue
            if re.match(r'^(require|replace|exclude)\s*\($', s):
                in_block = s.split()[0]
            elif s == ')':
                in_block = None
            elif in_block:
                out.add(f'{in_block} {s}')
            elif re.match(r'^(require|replace|exclude)\s', s):
                out.add(s)
        return out
    if name == 'Gemfile':
        return {s.strip() for s in t.splitlines() if re.match(r'^\s*(gem|gemspec|git|github|path)\b', s)}
    return None


def lockfile_stale(root, files, scope):
    for p in files:
        name = os.path.basename(p)
        if name not in LOCKFILE:
            continue
        directory = os.path.dirname(p)
        lock = next((os.path.join(directory, l) if directory else l for l in LOCKFILE[name]
                     if scope.tracked(os.path.join(directory, l) if directory else l)), None)
        if not lock:
            continue                # the project keeps no lockfile — not our business
        if scope.changed(lock):
            continue
        new = text(root, p)
        if new is None:
            continue
        new_deps = manifest_dependencies(name, new)
        if new_deps is None:
            continue
        old = scope.previous_version(p)
        old_deps = manifest_dependencies(name, old) if old is not None else set()
        if old_deps is None or old_deps == new_deps:
            continue
        emit(file=p, line=None, rule='lockfile-stale', severity='block',
             message=f'dependencies in {name} changed, {lock} did not — run the install '
                     f'(npm install / poetry lock / cargo update …) and add {lock} to the same commit',
             content_fingerprint=f'{p}|{lock}')


# --- floating-version ----------------------------------------------------------------

def floats_npm(version):
    w = str(version).strip()
    if w in ('', '*', 'latest', 'x', 'X'):
        return True
    if re.match(r'^>=?\s*[\w.*-]+$', w):                       # >=1.2 without `,<` / `<`
        return True
    return bool(GIT_WITHOUT_REF.match(w) and '#' not in w)


def floats_pip(spec):
    """Package name when the PEP 508 specifier has no upper bound; None when it has one or it is not a package."""
    s = spec.split(';')[0].split(' #')[0].strip().strip('"\'')
    if not s or s.startswith(('-', '#')):
        return None
    m = re.match(r'^([A-Za-z0-9][\w.-]*)', s)
    if not m:
        return None
    name = m.group(1)
    if '@' in s and '://' in s:                                 # pkg @ url — only git without a ref floats
        url = s.split('@', 1)[1].strip()
        return name if 'git+' in url and not re.search(r'\.git@[^/]+$|@[0-9a-f]{7,40}$|@v?\d[\w.]*$|#', url) else None
    return None if re.search(r'===|==|~=|<', s) else name


def floats_toml(value):
    """Dependency value in pyproject (poetry) / Cargo: a string or an inline table."""
    w = value.strip()
    if w.startswith('{'):
        g = re.search(r'\bgit\s*=', w)
        if g and not re.search(r'\b(rev|tag|branch)\s*=', w):
            return True
        v = re.search(r'\bversion\s*=\s*["\']([^"\']*)["\']', w)
        return bool(v) and floats_toml(f'"{v.group(1)}"')
    if w.startswith('['):                                        # poetry: a list of variants
        return any(floats_toml(x) for x in re.findall(r'\{[^}]*\}', w))
    w = w.strip('"\'')
    if w in ('', '*', 'latest'):
        return True
    return bool(re.match(r'^>=?\s*[\w.*-]+$', w))


def floating_versions(root, files):
    for p in files:
        name = os.path.basename(p)
        floating = []
        if name == 'package.json':
            d = json_without_comments(text(root, p) or '')
            deps = (d or {}).get('dependencies') if isinstance(d, dict) else None
            floating = [n for n, w in (deps or {}).items() if isinstance(w, str) and floats_npm(w)] \
                if isinstance(deps, dict) else []
        elif REQUIREMENTS.search(p):
            floating = [n for n in (floats_pip(l) for l in (text(root, p) or '').splitlines()) if n]
        elif name in ('pyproject.toml', 'Cargo.toml'):
            for section, line in toml_lines(text(root, p) or ''):
                if section == 'project' and re.match(r'^dependencies\s*=', line):
                    floating += [n for n in (floats_pip(x) for x in re.findall(r'"([^"]*)"|\'([^\']*)\'', line)
                                             for x in x if x) if n]
                elif TOML_PRODUCTION_SECTION.match(section) and not section.startswith('dependencies.'):
                    m = re.match(r'^([\w.-]+|"[^"]+")\s*=\s*(.+)$', line)
                    if m and m.group(1).strip('"') != 'python' and floats_toml(m.group(2)):
                        floating.append(m.group(1).strip('"'))
            # Cargo: [dependencies.name] as a separate table — floats when version has no bound
            # or git has no rev/tag/branch
            tables = {}
            for section, line in toml_lines(text(root, p) or ''):
                m = re.match(r'^dependencies\.([^\]]+)$', section)
                if m:
                    tables.setdefault(m.group(1).strip('"'), []).append(line)
            for n, ls in tables.items():
                if any(re.match(r'^(rev|tag|branch)\s*=', l) for l in ls):
                    continue
                v = next((l for l in ls if re.match(r'^version\s*=', l)), None)
                if (v and floats_toml(v.split('=', 1)[1])) or (not v and any(re.match(r'^git\s*=', l) for l in ls)):
                    floating.append(n)
        else:
            continue
        if floating:
            emit(file=p, line=None, rule='floating-version', severity='warn',
                 message=f'production dependencies without an upper version bound: {name_list(floating)} — '
                         f'pin the version (a lockfile does not help on a fresh install from the manifest)',
                 content_fingerprint=f'{p}|' + ','.join(sorted(floating)))


# --- binary-file / minified-bundle ----------------------------------------------

def binaries(root, files):
    for p in files:
        if not CODE_DIR.search(p) or ASSET.search(p) or PDF_IN_DOCS.search(p) or TEST_FILE.search(p):
            continue
        if build_dir(p, root):
            continue
        data = read(root, p, 8192)
        if data and b'\0' in data:
            emit(file=p, line=None, rule='binary-file', severity='warn',
                 message='binary file in a code directory — not an image or a font; if it is data/a model, '
                         'keep it outside the repo or in LFS', content_fingerprint=p)


def bundle(root, files):
    for p in files:
        if not BUNDLE.search(p) or VENDOR.search(p) or TEST_FILE.search(p) or build_dir(p, root):
            continue
        if MINIFIED_BY_NAME.search(os.path.basename(p)):
            reason = 'named *.min.*'
        else:
            data = read(root, p, 1_000_000) or b''
            if b'\0' in data[:8192] or max((len(l) for l in data.split(b'\n')), default=0) <= MAX_BUNDLE_LINE:
                continue
            reason = f'a line > {MAX_BUNDLE_LINE} characters'
        emit(file=p, line=None, rule='minified-bundle', severity='warn',
             message=f'minified bundle ({reason}) — build output belongs in dist/ and .gitignore; '
                     f'an external library → vendor/', content_fingerprint=p)


# --- ide-file / visual-artifacts / missing-gitignore -----------------------------------

def ide_files(root, files):
    groups = {}
    for p in files:
        m = IDEA.search(p)
        if m:
            groups.setdefault(p[:m.end() - 1], []).append(p)
            continue
        m = VSCODE.search(p)
        if m:
            if m.group(2) not in VSCODE_ALLOWED:
                emit(file=p, line=None, rule='ide-file', severity='warn',
                     message='.vscode/ file outside the shared ones (extensions/launch/tasks/settings) — a personal setting, '
                             'add it to .gitignore', content_fingerprint=p)
                continue
            t = text(root, p) or ''
            for nr, line in enumerate(t.splitlines(), 1):
                if ABSOLUTE_PATH.search(line):
                    emit(file=p, line=nr, rule='ide-file', severity='warn',
                         message='absolute path from one machine in a .vscode/ file — use ${workspaceFolder}',
                         content_fingerprint=line.strip())
                    break
            continue
        if IDE_LOOSE.search(p):
            emit(file=p, line=None, rule='ide-file', severity='warn',
                 message='editor / OS temporary file — add it to .gitignore', content_fingerprint=p)
    by_group(groups, 'ide-file', 'warn',
             lambda k: f'IDE directory ({k}) in the commit — personal settings, add it to .gitignore')


def config_field(root, section, field):
    """Value of a config section field; None when there is no config or section, '' when there is no field."""
    try:
        with open(os.path.join(root, 'telesma', 'config.md'), encoding='utf-8') as f:
            t = re.sub(r'<!--.*?-->', '', f.read(), flags=re.S)
    except OSError:
        return None
    m = re.search(r'^## ' + re.escape(section) + r'[ \t]*\n(.*?)(?=^## |\Z)', t, re.M | re.S)
    if not m:
        return None
    p = re.search(r'^- \*\*' + re.escape(field) + r'\*\*:[ \t]*(.*?)[ \t]*$', m.group(1), re.M)
    return p.group(1) if p else ''


def artifacts(files, artifacts_dir, commit_artifacts):
    if commit_artifacts or not artifacts_dir:
        return
    groups = {}
    for p in files:
        if p.startswith(artifacts_dir):
            groups.setdefault(artifacts_dir.rstrip('/'), []).append(p)
    by_group(groups, 'visual-artifacts', 'warn',
             lambda k: f'visual artifact in the commit with "Commit artifacts: no" — add {k}/ to .gitignore '
                       f'or set "yes" in telesma/config.md (## Visual artifacts)')


def missing_gitignore(root, files):
    if os.path.isfile(os.path.join(root, '.gitignore')) or '.gitignore' in files:
        return
    code = next((p for p in files if CODE.search(p)), None)
    if code:
        emit(file='.gitignore', line=None, rule='missing-gitignore', severity='warn', file_fingerprint=False,
             message=f'repository without .gitignore, and the commit already has code ({code}) — add a .gitignore '
                     f'(build directories, .env, telesma/artifacts/) before any of that reaches history',
             content_fingerprint='missing-gitignore')


def main():
    point = os.environ.get('TELESMA_POINT', 'commit')
    root = os.environ.get('TELESMA_ROOT') or os.getcwd()
    from_stdin = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    scope = Scope(root, point)
    files = sorted(p for p in set(from_stdin) | scope.extra()
                   if not p.startswith('telesma/checks/') and os.path.isfile(os.path.join(root, p)))
    if not files:
        return 0
    commit_art = config_field(root, 'Visual artifacts', 'Commit artifacts')
    art_dir = (config_field(root, 'Visual artifacts', 'Artifacts dir') or 'telesma/artifacts/').strip().rstrip('/') + '/' \
        if commit_art is not None else None
    commit_art = (commit_art or '').lower() in ('yes', 'true')

    build_dirs(root, files)
    sizes(root, files, art_dir, commit_art)
    lockfile_stale(root, files, scope)
    floating_versions(root, files)
    binaries(root, files)
    bundle(root, files)
    ide_files(root, files)
    artifacts(files, art_dir, commit_art)
    missing_gitignore(root, files)
    return 0


if __name__ == '__main__':
    sys.exit(main())
