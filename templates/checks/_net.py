"""Shared by checks that query network services: HTTP with a timeout, a cache in
~/.cache/telesma/, service addresses overridable by environment variables (tests point
them at a local server). A module imports it via `sys.path.insert(0, '..')`.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

ADDRESSES = {
    'npm': ('TELESMA_REGISTRY_NPM', 'https://registry.npmjs.org'),
    'npm_downloads': ('TELESMA_REGISTRY_NPM_DOWNLOADS', 'https://api.npmjs.org/downloads/point/last-week'),
    'pypi': ('TELESMA_REGISTRY_PYPI', 'https://pypi.org/pypi'),
    'jsr': ('TELESMA_REGISTRY_JSR', 'https://api.jsr.io'),
    'osv': ('TELESMA_OSV', 'https://api.osv.dev'),
}


def address(name):
    variable, default = ADDRESSES[name]
    return os.environ.get(variable, default).rstrip('/')


def _ssl_contexts():
    """Python from python.org on macOS ships without CA certificates — same order as
    in the telemetry collector: default store, certifi, system bundle."""
    yield ssl.create_default_context()
    try:
        import certifi
        yield ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for p in ('/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt'):
        if os.path.exists(p):
            yield ssl.create_default_context(cafile=p)


class NoNetwork(Exception):
    pass


def fetch(url, data=None, timeout=6):
    """(status, json|None). 404 → (404, None). Network/server unavailable → NoNetwork."""
    body = json.dumps(data).encode('utf-8') if data is not None else None
    headers = {'Accept': 'application/json', 'User-Agent': 'telesma-checks'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    last = None
    for ctx in (_ssl_contexts() if url.startswith('https') else [None]):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.status, json.loads(r.read().decode('utf-8') or 'null')
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return 404, None
            last = e
            if e.code < 500:
                break
        except urllib.error.URLError as e:
            last = e
            if not isinstance(getattr(e, 'reason', None), ssl.SSLError):
                break
        except (OSError, ValueError) as e:
            last = e
            break
    raise NoNetwork(str(last))


class Cache:
    """A dict saved in ~/.cache/telesma/<name>.json; an entry expires after `ttl` s."""

    def __init__(self, name):
        directory = os.environ.get('TELESMA_CACHE') or os.path.expanduser('~/.cache/telesma')
        self.path = os.path.join(directory, name + '.json')
        try:
            with open(self.path, encoding='utf-8') as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.changed = False

    def get(self, key):
        w = self.data.get(key)
        if w and w.get('expires', 0) > time.time():
            return w.get('v')
        return None

    def put(self, key, value, ttl):
        self.data[key] = {'v': value, 'expires': time.time() + ttl}
        self.changed = True

    def save(self):
        if not self.changed:
            return
        now = time.time()
        self.data = {k: v for k, v in self.data.items() if v.get('expires', 0) > now}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass
