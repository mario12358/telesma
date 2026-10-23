#!/usr/bin/env python3
"""Specky release snapshots for `vX.Y.Z` tags created before Telesma made them itself (18.7).

For every tag with a `docs/test-scenarios/<tag>.md` file it calls the Specky REST endpoint
`POST /api/projects/{id}/snapshots` with the tag, the SHA of the tagged commit, the tag message
and the full text of the file — the same payload that goes through MCP `create_snapshot` in the
loop. Specky shows it under its versions view → "what's new" → "how to test".

Order: **oldest tag first**. "What's new" compares a snapshot with the adjacent one on the list
(sorted by creation date), so snapshots added retroactively must be created in release order.

Authentication: REST does not accept a bearer token — e-mail + password login
(`POST /api/auth/login`, session cookie) and CSRF double-submit (`GET /api/auth/csrf` → header
`X-CSRF-Token`). The password comes from `SPECKY_PASSWORD` or from a terminal prompt; never from
an argument (it would end up in shell history) and never in the output.

Usage:
  python3 tools/telesma-specky-snapshots.py <project> v0.38.0 v0.38.1    # the given tags
  python3 tools/telesma-specky-snapshots.py <project> --all              # every v* with a file
  python3 tools/telesma-specky-snapshots.py <project> --all --dry-run    # list only, send nothing

The Specky address and project_id come from `telesma/config.md` → `## Integrations` (`Tracker MCP`
without the `/mcp` path, `Tracker project`); `--url` / `--project-id` override them. 409
`snapshot_tag_exists` = the snapshot already exists, tag skipped; that is not an error.
"""
from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHAR_LIMIT = 200_000            # TEST_SCENARIOS_MAX_CHARS on the Specky side
SCENARIOS_DIR = Path("docs/test-scenarios")
RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


# --- configuration ------------------------------------------------------------------------------

def config_field(text: str, section: str, field: str) -> str | None:
    """`- **Field**: value` in section `## Section` (<!-- --> comments skipped)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    m = re.search(rf"^## {re.escape(section)}\s*$(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
    if not m:
        return None
    w = re.search(rf"^- \*\*{re.escape(field)}\*\*:\s*(.*?)\s*$", m.group(1), flags=re.M)
    return w.group(1).strip() or None if w else None


def base_from_mcp(mcp_url: str) -> str:
    u = urllib.parse.urlparse(mcp_url)
    if not u.scheme or not u.netloc:
        fail(f"Tracker MCP does not look like an address: {mcp_url!r}")
    return f"{u.scheme}://{u.netloc}"


# --- git --------------------------------------------------------------------------------------

def git(project: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(project), *args], check=True,
                          capture_output=True, text=True).stdout


def release_tags(project: Path) -> list[str]:
    """`v*` tags, oldest first (by version number, not by date)."""
    out = git(project, "tag", "-l", "v*", "--sort=v:refname")
    return [t for t in out.split() if RELEASE_TAG.match(t)]


def tag_message(project: Path, tag: str) -> str | None:
    """Message of an annotated tag (without a GPG signature); lightweight tag → None."""
    out = git(project, "for-each-ref", "--format=%(objecttype)%0a%(contents)", f"refs/tags/{tag}")
    kind, _, body = out.partition("\n")
    if kind.strip() != "tag":         # lightweight tag: %(contents) is the commit message, not the tag's
        return None
    body = body.split("-----BEGIN PGP SIGNATURE-----")[0].strip()
    return body or None


# --- HTTP --------------------------------------------------------------------------------------

def ssl_contexts() -> list[ssl.SSLContext | None]:
    """As in the telemetry collector: default store → certifi → system bundle.
    Verification is always on — only the source of trusted CAs changes."""
    out: list[ssl.SSLContext | None] = [None]
    try:
        import certifi  # type: ignore
        out.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                 "/etc/pki/tls/certs/ca-bundle.crt"):
        if os.path.exists(path):
            try:
                out.append(ssl.create_default_context(cafile=path))
            except Exception:
                pass
    return out


class Specky:
    def __init__(self, base: str, timeout: float = 30.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self._opener = None
        self.csrf: str | None = None

    def _build(self, ctx):
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ctx) if ctx else urllib.request.HTTPSHandler(),
        )

    def _send(self, req: urllib.request.Request) -> tuple[int, bytes]:
        if self._opener is not None:
            return self._open(self._opener, req)
        last: Exception | None = None
        for ctx in ssl_contexts():
            opener = self._build(ctx)
            try:
                result = self._open(opener, req)
            except (ssl.SSLError, urllib.error.URLError) as e:
                if isinstance(e, urllib.error.URLError) and not isinstance(e.reason, ssl.SSLError):
                    raise
                last = e
                continue
            self._opener = opener      # this context works — keep it for the rest of the session
            return result
        fail(f"TLS: no CA store verified {self.base} ({last})")

    def _open(self, opener, req) -> tuple[int, bytes]:
        try:
            with opener.open(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def login(self, email: str, password: str) -> None:
        data = urllib.parse.urlencode({"username": email, "password": password}).encode()
        req = urllib.request.Request(f"{self.base}/api/auth/login", data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        status, body = self._send(req)
        if status not in (200, 204):
            fail(f"login: HTTP {status} — {_short(body)}")
        status, body = self._send(urllib.request.Request(f"{self.base}/api/auth/csrf"))
        if status != 200:
            fail(f"CSRF: HTTP {status} — {_short(body)}")
        self.csrf = json.loads(body).get("csrf_token")
        if not self.csrf:
            fail("CSRF: response without csrf_token")

    def snapshot(self, project_id: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{self.base}/api/projects/{urllib.parse.quote(project_id)}/snapshots",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf or ""})
        status, body = self._send(req)
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            data = {"raw": _short(body)}
        return status, data


def _short(b: bytes, n: int = 300) -> str:
    return b.decode("utf-8", "replace")[:n]


def fail(message: str) -> None:
    """Message to stderr and exit code 1 — `SystemExit("text")` prints only at the top of the process."""
    print(message, file=sys.stderr)
    raise SystemExit(1)


# --- main flow --------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("project", type=Path, help="Telesma project directory (with telesma/config.md and .git)")
    ap.add_argument("tags", nargs="*", help="vX.Y.Z tags to freeze (default: none)")
    ap.add_argument("--all", action="store_true",
                    help="every v* tag that has a docs/test-scenarios/<tag>.md file")
    ap.add_argument("--url", help="Specky address, e.g. https://app.specky.app (default: from Tracker MCP)")
    ap.add_argument("--project-id", dest="project_id", help="project_id in Specky (default: Tracker project)")
    ap.add_argument("--email", default=os.environ.get("SPECKY_EMAIL"),
                    help="Specky account (or SPECKY_EMAIL)")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="print what would be sent; send nothing")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args(argv)

    project: Path = a.project.resolve()
    config = project / "telesma" / "config.md"
    if not config.exists():
        print(f"missing {config}", file=sys.stderr)
        return 1
    text = config.read_text(encoding="utf-8")
    if (config_field(text, "Integrations", "Tracker") or "none") != "specky" and not a.project_id:
        print("telesma/config.md → ## Integrations has no `Tracker: specky` — pass --project-id, "
              "or run the wizard: ./telesma.sh --integrations <project>", file=sys.stderr)
        return 1
    project_id = a.project_id or config_field(text, "Integrations", "Tracker project")
    if not project_id:
        print("missing project_id (field `Tracker project` or --project-id)", file=sys.stderr)
        return 1
    base = a.url or base_from_mcp(config_field(text, "Integrations", "Tracker MCP") or "")

    # Tag list — always oldest first, regardless of the order of the arguments.
    available = release_tags(project)
    if a.all:
        chosen = [t for t in available if (project / SCENARIOS_DIR / f"{t}.md").exists()]
    else:
        unknown = [t for t in a.tags if t not in available]
        if unknown:
            print(f"no such v* tags in the repo: {', '.join(unknown)}", file=sys.stderr)
            return 1
        chosen = [t for t in available if t in set(a.tags)]
    if not chosen:
        print("nothing to do: no v* tag with a docs/test-scenarios/<tag>.md file"
              if a.all else "give tags or --all")
        return 0

    items = []
    for tag in chosen:
        path = project / SCENARIOS_DIR / f"{tag}.md"
        if not path.exists():
            print(f"  {tag}: missing {path.relative_to(project)} — skipping", file=sys.stderr)
            continue
        body = path.read_text(encoding="utf-8")
        if len(body) > CHAR_LIMIT:
            print(f"  {tag}: the file has {len(body)} characters, limit {CHAR_LIMIT} — skipping",
                  file=sys.stderr)
            continue
        sha = git(project, "rev-parse", f"{tag}^{{}}").strip()
        items.append((tag, {
            "name": tag,
            "description": tag_message(project, tag),
            "git_tag": tag,
            "git_commit_sha": sha,
            "test_scenarios_md": body,
        }))

    print(f"Specky {base}, project {project_id}: {len(items)} snapshots (oldest first)")
    for tag, p in items:
        print(f"  {tag}  commit {p['git_commit_sha'][:7]}  scenarios {len(p['test_scenarios_md'])} chars"
              f"{'' if p['description'] else '  (tag without a message)'}")
    if a.dry_run or not items:
        return 0

    email = a.email or input("Specky e-mail: ").strip()
    password = os.environ.get("SPECKY_PASSWORD") or getpass.getpass("Specky password: ")
    if not email or not password:
        print("missing e-mail or password", file=sys.stderr)
        return 1

    client = Specky(base, timeout=a.timeout)
    client.login(email, password)
    del password

    code = 0
    for tag, payload in items:
        status, data = client.snapshot(project_id, payload)
        if status == 201:
            print(f"  ✓ {tag}: snapshot {data.get('id', '?')}")
        elif status == 409 and (data.get("detail") or {}).get("code") == "snapshot_tag_exists":
            print(f"  = {tag}: snapshot already exists ({(data['detail']).get('snapshot_id', '?')}) — skipped")
        else:
            code = 1
            print(f"  ✗ {tag}: HTTP {status} — {json.dumps(data, ensure_ascii=False)[:300]}",
                  file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
