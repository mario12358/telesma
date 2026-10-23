---
kind: command
run: python3 run.py
check: python3 run.py --check
when: commit, phase, ci
scope: changed
on_failure: block
---

# Check: sast

"Watch out for OWASP" in the guidelines works on errors of ignorance, not on errors made by reflex: the model knows
parameterised queries and still pastes an f-string into `execute()`, because in that one line it was
quicker. This check reads changed files **before** the commit and looks for code shapes that are
an injection or lead to one.

**Tool.** When `semgrep` is in PATH, the check runs it with the `p/owasp-top-ten`,
`p/security-audit` packs and a language pack for the extensions present in scope (`p/python`,
`p/javascript`, `p/typescript`, `p/golang`). Semgrep downloads `p/…` packs from the network on first
use; no network, an error or a timeout (15 s at commit, 240 s at phase / CI) is **not** a
block — the check falls back to the built-in patterns and adds a `not-checked` warning, so it is
visible that the run was shallower. Without semgrep only the built-in mode runs (the validator at startup says
which mode is active). The built-in patterns also run **alongside** semgrep — they add lines it
did not report (the same line reported by semgrep is not counted twice).
`TELESMA_SEMGREP=none` in the environment disables semgrep (harness tests).

## What blocks and what warns

The severity is set by the rule, not by the tool: injections (SQL, command, code), deserialization
and a path from the request block — classes in which one hit is a ready exploit. The rest warns, because it
needs a judgement of the context. The config can soften the whole module to `warn`, never harden it.

| Rule | Severity | What it catches (on the same line) |
|---|---|---|
| `sql-concatenation` | **block** | `execute(` / `executemany(` / `raw(` / `text(` / `query(` with an argument that is **assembled**: an f-string with `{}`, `"…" +`, `% (`, `.format(`; in JS a template literal with `${}`. A variable alone (`execute(query)`) passes — it may be a prepared query. Parameters (`execute("… %s", (x,))`) pass |
| `shell-command` | **block** | `subprocess.*(…, shell=True)` and `os.system` / `os.popen` with anything other than a literal (a variable, f-string, `+`, `.format`); JS `exec(` / `execSync(` with `${}` or `+` |
| `eval-exec` | **block** | Python `eval(` / `exec(` with a non-literal (`eval("1+1")` passes, `model.eval()`, `self.exec(…)` and a method definition `def exec(` are not counted); JS `eval(` with a non-literal, `new Function(`, `setTimeout("…")`, `vm.runIn*Context(` |
| `deserialization` | **block** | `pickle.load(s)`, `cPickle`, `marshal.loads`, `shelve.open`, `jsonpickle.decode`, `yaml.load(` without `SafeLoader` / `BaseLoader` (`safe_load` passes), JS `unserialize(`, Java `ObjectInputStream` |
| `path-traversal` | **block** | `open(` / `Path(` / `send_file(` / `sendFile(` / `FileResponse(` / `os.path.join(` / `readFile(` with `request.` / `req.params` / `req.query` / `req.body` / `params[` / `args.get(` in the argument — unless the line has `secure_filename(` / `basename(` / `safe_join(` / `realpath(` / `path.resolve(` with `startsWith(` |
| `xss-innerhtml` | warn | `innerHTML =` / `outerHTML =` (except an empty literal), `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `document.write`, `v-html`, `{@html`, Jinja `\|safe`, `Markup(`, `mark_safe(`, Angular `bypassSecurityTrust*` |
| `cors-any-origin-with-credentials` | warn | `credentials: true` / `supports_credentials=True` / `allow_credentials=True` and `origin: "*"` (or `true`) on the same line or ±3 lines. `*` alone without credentials is reported by `weakenings` |
| `weak-hash` | warn | `hashlib.md5/sha1`, `createHash('md5'/'sha1')`, `MessageDigest MD5/SHA-1`, PHP `md5(` — only on a line with the word `password` / `passwd` / `token` / `secret`. `md5(file_bytes)` for checksums passes |
| `non-crypto-randomness` | warn | `random.random/randint/choice/…`, `Math.random(`, `rand(` — on a line with the word `token` / `secret` / `session` / `otp` / `nonce` / `password` / `reset` / `csrf` / `salt` |
| `open-redirect` | warn | `redirect(` / `res.redirect(` / `RedirectResponse(` with `request.args` / `req.query` / `args.get(` / `next` / `return_to` / `redirect_url` — without `url_has_allowed_host` / `is_safe_url` / `startswith("/")` / `url_for(` |
| `stacktrace-in-response` | warn | `traceback.format_exc()` / `err.stack` on a line with `return` / `res.send` / `jsonify` / `JSONResponse` / `render`. The same stack in `logger.error` passes |
| `jwt-without-verification` | warn | `verify_signature: False`, `algorithms: ['none']`, `verify=False` next to `jwt` / `decode(`, Python `jwt.decode(` without `algorithms=` in the whole call (arguments on the following lines count), JS `jwt.decode(` (does not verify the signature — `jwt.verify` does) |
| `xxe` | warn | `etree.parse/fromstring/XMLParser`, `minidom.parse`, `xml.sax`, `pulldom`, `resolve_entities=True`, Java `DocumentBuilderFactory` / `SAXParserFactory`. A file that imports `defusedxml` anywhere is exempt from this rule |
| `ssrf` | warn | `requests.get/post/…`, `httpx.*`, `fetch(`, `axios`, `urlopen(`, `got(` with `request.` / `req.query` / `req.body` / `params[` / `args.get(` in the argument |
| `insecure-tmp` | warn | `tempfile.mktemp(`, `open("/tmp/…")`, `os.tmpnam` |
| `secret-in-log` | warn | `print(` / `logger.*(` / `console.log(` / `log.Printf(` with an identifier whose **last word** is `password` / `secret` / `api_key` / `token` / `authorization` / `private_key` / `credentials` (also `user.password`, `${accessToken}`, `{token}` in an f-string). The message `"password changed"` is a literal — passes; `token_count`, `tokens` — do not end with the word — pass; `len(password)` / `mask(` / `***` pass |
| `not-checked` | warn | Semgrep was available but gave no result (network, time, error code) — the run was done with the built-in patterns only |

In semgrep mode the rule is the last segment of `check_id`; only a finding of severity ERROR **blocks**,
and only when its `check_id` contains `injection` / `sqli` / `sql-injection` / `command` / `subprocess` / `eval` /
`exec` / `deserial` / `pickle` / `yaml-load` / `path-traversal` / `tainted-path` / `ssrf` — the rest
(ERROR included) is reduced to a warning. The message carries semgrep's message and a line fragment of ≤ 80 characters,
never the whole `extra.lines` block.

## What it skips

- **Test files** entirely (`tests/`, `__tests__/`, `spec/`, `e2e/`, `test_*`, `*_test.*`, `*.spec.*`,
  `*.test.*`) — a test legitimately does `eval`, assembled SQL and `pickle`.
- `migrations/`, `alembic/`, `seeds/`, `*.sql` — only the `sql-concatenation` rule and semgrep's SQL rules
  (`check_id` containing "sql", e.g. `avoid-sqlalchemy-text`): migrations build SQL from constants (table
  names in f-strings), there is nothing to parameterise there.
- `secret-in-log`: a value passing through a masking function (`len(`, `mask`, `redact`,
  `marker` — e.g. `key_marker(api_key)`, `fingerprint`, `[:4]`) is not a secret in the log.
- Files outside the list of code extensions (`.py .js .jsx .ts .tsx .mjs .cjs .vue .svelte .java .kt .scala
  .go .rb .php .cs` + templates `.html .jinja .j2 .ejs .hbs .njk`), binaries, lines > 4000 characters,
  comment lines and `import` / `require(` lines.
- A line with a `# nosec`, `// nosec`, `# nosemgrep`, `// nosemgrep`, `# noqa: S…` comment —
  a deliberate decision by the author. **It should be rare**: `nosec` disappears into the code and nobody counts it later,
  while `telesma: weakening <id> — <reason>` is a register that reminds of itself at phase end and blocks
  the release. Mark a deliberate weakening with the marker, keep `nosec` for a false hit on a line
  that cannot be rewritten.
- `verify=False` for TLS, `DEBUG = True`, `csrf_exempt`, CORS `*` without credentials — that is `weakenings`' job,
  deliberately not duplicated here. ReDoS — skipped (without automaton analysis it is only noise).

## What it does not do

The built-in patterns look at **one line** (CORS: ±3). `url = request.args["u"]` on the line above
and `requests.get(url)` below will pass — that is a job for semgrep with data-flow analysis, not for a regex.
It does not track types: `execute(query)` passes, because it is unknown where `query` comes from. That is why the first
run on a project that did not have this check is worth doing by hand
(`python3 telesma/checks/telesma-checks.py --point phase`) to calibrate exceptions before it reaches commits.

## False positives

One finding per rule per file, with a `(+N more in the file)` counter. The fingerprint is computed from
**all** hit lines of that rule in the file (not from the first): an exception in
`telesma/state/CHECK_EXCEPTIONS.md` clears exactly the lines the human saw. It survives
line shifts; a new hit line in the same file changes the fingerprint and blocks again — that is
deliberate. The exception is written by a human; Telesma reports a false hit as TELESMA BLOCKED with the fingerprint.
