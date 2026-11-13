#!/usr/bin/env python3
"""Claude Code's built-in sandbox for a Telesma project (change plan K1).

The judge and the checks read the text of a command; a wrong "allow" runs with every right the
person has. The sandbox is the layer under them that does not care what a command claims to be:
Bash and what it starts write only inside the project, the extra directories and $TMPDIR, reach the
network only through a proxy with a host list, and cannot read the person's keys.

`## Sandbox` in telesma/config.md → the `sandbox` key of .claude/settings.local.json:

    Enabled: no | yes | required      required = Claude Code stops when the sandbox cannot run
    Allowed hosts:      list          added to the hosts of the project's stacks, the checks and
                                      the repository integration
    Writable paths:     list          added to the package caches of the project's stacks
    Excluded commands:  list          run outside the sandbox (e.g. `docker compose *`)

Fixed, whatever the config says (found in the live probe of 2026-11-12):
- allowUnsandboxedCommands: false — without it a refused command is retried outside the sandbox,
  and an allow rule (the task tool's own) let that retry through without a question;
- autoAllowBashIfSandboxed: false — the sandbox is a layer under the questions, not instead of them;
- strictAllowlist in the autonomous modes — a host question there reaches nobody;
- network.allowLocalBinding: true — on macOS a sandboxed command cannot listen on a port without
  it, so no test could start a server (live run of 2026-11-12: `listen EPERM 127.0.0.1`);
- every `Excluded commands` pattern also becomes a `permissions.ask` rule (`Bash(<pattern>)`): an
  allow rule such as Bash(npx:*) must not let a command outside the sandbox through without a
  question (live run of 2026-11-12: the e2e exclusion carried a diagnostic script the agent wrote);
- ~/.config/telesma stays readable (the task tool reads the trust record from inside the sandbox),
  and so does ~/.config/gh with the GitHub integration (gh runs from the task tool).

What Telesma wanted itself and what it wrote (with the person's additions) are remembered in
.git/telesma-task/sandbox.json (this machine's): with `Enabled: no` the key is removed only when it
is still what Telesma wrote, and on an update what the person added in Claude Code (a host they
allowed for good) is kept while what only Telesma wanted and the config dropped goes.

    sandbox.py sync <project> <settings.local.json> [--autonomous]
        prints one line: off | on | unavailable <reason> | required-unavailable <reason>
        exit 0 always, except a settings file that does not parse (exit 1, nothing written)
    sandbox.py available
        prints: yes | no <reason>
    sandbox.py excluded <project>
        the `Excluded commands` of an enabled sandbox, one per line

Python 3.9+, standard library only.
"""
import json
import os
import platform
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trust  # noqa: E402  (same directory: the one config reader)

# Package registries and the caches the package managers write to (both the Linux and the macOS place).
STACK_HOSTS = {
    'python': ['pypi.org', 'files.pythonhosted.org'],
    'node': ['registry.npmjs.org', 'registry.yarnpkg.com'],
    # Browsers for e2e tests: Playwright's CDN and mirror; Chromium builds now come from Google's
    # Chrome for Testing bucket. storage.googleapis.com is all of Google Cloud Storage, so it is
    # added only for a project that uses Playwright, never for every Node project.
    'playwright': ['cdn.playwright.dev', 'playwright.download.prss.microsoft.com', 'playwright.azureedge.net',
                   'storage.googleapis.com'],
    'deno': ['deno.land', 'jsr.io', 'registry.npmjs.org'],
    'rust': ['crates.io', 'index.crates.io', 'static.crates.io'],
    'go': ['proxy.golang.org', 'sum.golang.org', 'storage.googleapis.com'],
    'java': ['repo.maven.apache.org', 'repo1.maven.org', 'plugins.gradle.org', 'services.gradle.org',
             'maven.google.com', 'dl.google.com'],
    'dotnet': ['api.nuget.org'],
    'php': ['repo.packagist.org', 'packagist.org'],
    'ruby': ['rubygems.org', 'index.rubygems.org'],
    'swift': ['cdn.cocoapods.org'],
    'flutter': ['pub.dev', 'storage.googleapis.com', 'maven.google.com', 'dl.google.com', 'repo.maven.apache.org',
                'plugins.gradle.org', 'services.gradle.org', 'cdn.cocoapods.org'],
}
STACK_WRITE = {
    'python': ['~/.cache/uv', '~/.cache/pip', '~/Library/Caches/pip', '~/.cache/pypoetry',
               '~/Library/Caches/pypoetry'],
    'node': ['~/.npm', '~/.cache/yarn', '~/Library/Caches/Yarn', '~/.local/share/pnpm', '~/Library/pnpm'],
    'playwright': ['~/.cache/ms-playwright', '~/Library/Caches/ms-playwright'],
    'deno': ['~/.cache/deno', '~/Library/Caches/deno'],
    'rust': ['~/.cargo/registry', '~/.cargo/git'],
    'go': ['~/go/pkg/mod', '~/.cache/go-build', '~/Library/Caches/go-build'],
    'java': ['~/.m2/repository', '~/.gradle', '~/.android'],
    'dotnet': ['~/.nuget/packages'],
    'php': ['~/.composer/cache', '~/.cache/composer'],
    'ruby': ['~/.gem', '~/.bundle'],
    'swift': ['~/Library/Developer/Xcode/DerivedData', '~/Library/Caches/org.swift.swiftpm', '~/.cocoapods',
              '~/Library/Caches/CocoaPods'],
    'flutter': ['~/.pub-cache', '~/.gradle', '~/.android', '~/Library/Developer/Xcode/DerivedData', '~/.cocoapods',
                '~/Library/Caches/CocoaPods', '~/.dartServer', '~/.flutter', '~/.config/flutter'],
}
# A plan's `(tech: …)` tags name the stack before the first manifest exists (a new project).
TAG_STACK = {
    'python': 'python', 'django': 'python', 'fastapi': 'python', 'pyside6': 'python', 'robotics': 'python',
    'node': 'node', 'typescript': 'node', 'react': 'node', 'react-native': 'node', 'nextjs': 'node',
    'vue': 'node', 'angular': 'node', 'svelte': 'node', 'nestjs': 'node', 'hono': 'node', 'tailwind': 'node',
    'playwright': 'playwright', 'detox': 'node', 'deno': 'deno', 'rust': 'rust', 'go': 'go', 'java': 'java',
    'kotlin': 'java', 'spring': 'java', 'csharp': 'dotnet', 'wpf': 'dotnet', 'php': 'php', 'ruby': 'ruby',
    'swift': 'swift', 'flutter': 'flutter',
}
CHECK_HOSTS = ['api.osv.dev', 'pypi.org', 'registry.npmjs.org', 'api.npmjs.org', 'jsr.io', 'api.jsr.io']
GITHUB_HOSTS = ['github.com', 'api.github.com', 'codeload.github.com', 'objects.githubusercontent.com']
ALWAYS_WRITE = ['~/.cache/telesma']
DENY_READ = ['~/.ssh', '~/.aws', '~/.gnupg', '~/.netrc', '~/.docker/config.json', '~/.kube',
             '~/.config/gcloud', '~/.azure']
GH_CONFIG = '~/.config/gh'
HOST_RE = re.compile(r'^(\*\.)?[A-Za-z0-9.-]+(:\d+)?$')


def available():
    """(True, '') or (False, reason) — whether Claude Code's sandbox can run on this machine."""
    system = platform.system()
    if system == 'Windows' or sys.platform in ('win32', 'cygwin', 'msys') or system.startswith(('MINGW', 'MSYS', 'CYGWIN')):
        return False, 'native Windows (the sandbox runs on macOS, Linux and WSL2)'
    if system == 'Darwin':
        return (True, '') if os.path.exists('/usr/bin/sandbox-exec') else (False, 'sandbox-exec is missing')
    if system == 'Linux':
        missing = [t for t in ('bwrap', 'socat') if not shutil.which(t)]
        if missing:
            return False, 'missing: ' + ', '.join(missing) + ' (install bubblewrap and socat)'
        return True, ''
    return False, f'{system} is not supported'


def section(project):
    text = trust.read_config(project) or ''
    values, lists = trust.fields(trust.section_lines(text, 'Sandbox'))
    enabled = (values.get('Enabled') or 'no').strip().lower()
    if enabled in ('true', 'on'):
        enabled = 'yes'
    if enabled not in ('yes', 'required'):
        enabled = 'no'
    clean = lambda items: [i for i in (x.strip() for x in items) if i and not trust.unset(i)]
    return text, enabled, {k: clean(lists.get(k, [])) for k in ('Allowed hosts', 'Writable paths', 'Excluded commands')}


def config_value(text, sec, label):
    return (trust.fields(trust.section_lines(text, sec))[0].get(label) or '').strip()


def stacks(project):
    found = set()
    try:
        import configure
        found.update(configure.detect_stacks(project))
    except Exception:
        pass
    try:
        with open(os.path.join(project, 'telesma', 'state', 'PLAN.md'), encoding='utf-8', errors='replace') as f:
            plan = f.read()
    except OSError:
        plan = ''
    for tags in re.findall(r'\(tech:\s*([^)]*)\)', plan):
        for tag in re.split(r'[,\s]+', tags):
            if tag.strip().lower() in TAG_STACK:
                found.add(TAG_STACK[tag.strip().lower()])
    if 'playwright' in found or uses_playwright(project):
        found.update(('playwright', 'node'))
    return sorted(s for s in found if s in STACK_HOSTS)


def uses_playwright(project):
    """A package.json at the root or one level down (a workspace) that names Playwright."""
    candidates = [os.path.join(project, 'package.json')]
    try:
        candidates += [os.path.join(project, d, 'package.json') for d in sorted(os.listdir(project))
                       if d not in ('node_modules', '.git', 'telesma') and os.path.isdir(os.path.join(project, d))]
    except OSError:
        pass
    for path in candidates:
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                if re.search(r'"(@playwright/test|playwright)"\s*:', f.read()):
                    return True
        except OSError:
            continue
    return False


def tool_homes(st):
    """An SDK that keeps its cache inside its own install (Flutter downloads the engine into
    <sdk>/bin/cache on the first build): that directory, found from the tool on PATH."""
    out = []
    if 'flutter' in st:
        tool = shutil.which('flutter')
        if tool:
            out.append(os.path.join(os.path.dirname(os.path.realpath(tool)), 'cache'))
    return out


def wanted(project, autonomous):
    text, enabled, extra = section(project)
    if enabled == 'no':
        return enabled, None
    st = stacks(project)
    github = config_value(text, 'Integrations', 'Repository').lower() == 'github'
    checks = config_value(text, 'Checks', 'Enabled').lower() in ('yes', 'true')
    hosts = [h for s in st for h in STACK_HOSTS[s]] + (CHECK_HOSTS if checks else []) \
        + (GITHUB_HOSTS if github else []) + [h for h in extra['Allowed hosts'] if HOST_RE.match(h)]
    write = ALWAYS_WRITE + [p for s in st for p in STACK_WRITE[s]] + tool_homes(st) + extra['Writable paths']
    deny = DENY_READ + ([] if github else [GH_CONFIG])
    return enabled, {
        'enabled': True,
        'autoAllowBashIfSandboxed': False,
        'allowUnsandboxedCommands': False,
        'failIfUnavailable': enabled == 'required',
        'excludedCommands': extra['Excluded commands'],
        # Tests start servers on 127.0.0.1 (an API test, an e2e run, a smoke test): on macOS a
        # sandboxed command may not listen at all without this. It reaches localhost only — and so
        # every service listening there; on Linux and WSL2 localhost is private to the command and
        # the key has no effect.
        'network': {'allowedDomains': unique(hosts), 'strictAllowlist': bool(autonomous), 'allowLocalBinding': True},
        'filesystem': {'allowWrite': unique(write), 'denyRead': unique(deny)},
    }


def unique(items):
    out = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def memory_path(project):
    return os.path.join(project, '.git', 'telesma-task', 'sandbox.json')


def load_memory(project):
    try:
        with open(memory_path(project), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save_memory(project, data):
    path = memory_path(project)
    if not os.path.isdir(os.path.join(project, '.git')):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if data is None:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    atomic_json(path, data)


def atomic_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.telesma-')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def keep_person_additions(ours, current, own_before):
    """Hosts and writable paths the person added in Claude Code ("don't ask again") stay; what an
    earlier run of Telesma wanted itself and the config no longer wants goes."""
    ours = json.loads(json.dumps(ours))
    for group, key in (('network', 'allowedDomains'), ('filesystem', 'allowWrite')):
        mine_before = set(((own_before or {}).get(group) or {}).get(key) or [])
        theirs = [x for x in (((current or {}).get(group) or {}).get(key) or [])
                  if isinstance(x, str) and x not in mine_before]
        ours[group][key] = unique(ours[group][key] + theirs)
    return ours


def ask_rules(excluded):
    return unique([f'Bash({c})' for c in excluded if c and '\n' not in c and ')' not in c])


def sync_ask(settings, ours, before):
    """permissions.ask: the person's rules stay, Telesma's are the current `Excluded commands`."""
    perms = settings.get('permissions') if isinstance(settings.get('permissions'), dict) else None
    current = (perms or {}).get('ask') if isinstance((perms or {}).get('ask'), list) else []
    kept = [r for r in current if r not in (before or [])]
    new = unique(kept + ours)
    if new == current:
        return
    if perms is None:
        if not new:
            return
        perms = settings['permissions'] = {}
    if new:
        perms['ask'] = new
    else:
        perms.pop('ask', None)


def sync(project, settings_path, autonomous):
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding='utf-8') as f:
                settings = json.load(f)
        except (OSError, ValueError):
            print('off settings.local.json does not parse')
            return 1
    if not isinstance(settings, dict):
        print('off settings.local.json is not an object')
        return 1
    enabled, ours = wanted(project, autonomous)
    memory = load_memory(project) or {}
    wrote, own_before = memory.get('wrote'), memory.get('own')
    current = settings.get('sandbox')
    ok, reason = available()
    asked_before = memory.get('ask') or []
    if ours is None:
        if wrote is not None and current == wrote:
            settings.pop('sandbox', None)
        sync_ask(settings, [], asked_before)
        if (wrote is not None and current == wrote) or asked_before:
            write_settings(settings_path, settings)
        save_memory(project, None)
        print('off')
        return 0
    if not ok and platform.system() == 'Windows':
        print(('required-unavailable ' if enabled == 'required' else 'unavailable ') + reason)
        return 0
    merged = keep_person_additions(ours, current if isinstance(current, dict) else {}, own_before)
    settings['sandbox'] = merged
    asks = ask_rules(ours['excludedCommands'])
    sync_ask(settings, asks, asked_before)
    write_settings(settings_path, settings)
    save_memory(project, {'own': ours, 'wrote': merged, 'ask': asks})
    if ok:
        print('on')
    else:
        print(('required-unavailable ' if enabled == 'required' else 'unavailable ') + reason)
    return 0


def write_settings(path, settings):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_json(path, settings)


def main(argv):
    if len(argv) >= 2 and argv[1] == 'available':
        ok, reason = available()
        print('yes' if ok else f'no {reason}')
        return 0
    if len(argv) >= 3 and argv[1] == 'excluded':
        _, enabled, extra = section(argv[2])
        if enabled != 'no':
            for c in extra['Excluded commands']:
                print(c)
        return 0
    if len(argv) >= 4 and argv[1] == 'sync':
        return sync(argv[2], argv[3], '--autonomous' in argv[4:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
