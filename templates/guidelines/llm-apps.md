---
tag: llm-apps
keywords: llm, claude, anthropic sdk, prompt, completion, chat, agent, tool use, function calling, mcp, rag, retrieval, structured output, embeddings
---

# Guidelines: LLM-powered application features

## Style

- One client module (`src/llm/client.ts` / `llm/client.py`) constructs the provider SDK client once (API key from the environment, timeout, `max_retries`) and exports typed functions `complete()`, `stream()`, `extract(schema, …)`; feature code imports these and never the SDK directly
- Model id, max output tokens and effort/thinking settings live in ONE config constant (`LLM_CONFIG = { model: env.LLM_MODEL ?? DEFAULT_MODEL, maxTokens: 4096, … }`); a model change is a one-line diff plus an env var, never a search-and-replace
- Prompts are versioned code: `src/llm/prompts/<task>/v3.md` with `{{placeholders}}`, rendered by `renderPrompt('summarize', { text })`; no inline prompt strings in feature code, no concatenation of untrusted input into the system prompt
- The system prompt is static (role, rules, output format); per-request data goes in the user message — prompt caching is a prefix match, so stable content first (tools → system → long documents → the question) and volatile values (timestamps, ids) last
- Structured output comes from a schema, never from parsing prose: the provider's structured-output option with a JSON schema, or a single tool whose `input_schema` is the result shape with `strict: true`; the schema is defined once (Zod / Pydantic) and validates the parsed result too
- Every call branches on `stop_reason`: `end_turn` → done; `tool_use` → run tools; `max_tokens` → truncated (chunk or raise the limit, never return the fragment); `refusal` → a declined request, not a 500
- Messages, tool definitions and results use the SDK's own types; no `any` / untyped dicts for history
- Retries and timeouts are configured on the client (the SDK already retries 429/5xx/connection errors with backoff); no hand-written retry loop around it, never a retry on 400
- Sampling parameters, prefilled assistant turns and forced tool choice are not copied from old examples — the provider's current reference decides which parameters exist

## Project structure

- `src/llm/client.*` (SDK wrapper), `config.*` (model constant + price table), `prompts/<task>/vN.*` + `index` mapping task → current version, `schemas/` (output schemas), `tools/<name>.*` (one file per tool: schema + handler), `evals/<task>/cases.jsonl`, `log.*` (redacting logger)
- Feature code calls `extract(schema, promptName, vars)`; it never assembles message arrays or parses model text
- Retrieval lives in `src/retrieval/` (chunking, embeddings, search) and returns typed `Document[]` with `id`, `source`, `score`; the LLM layer wraps each document in a delimited block with its id
- An MCP server is its own package (`mcp/<server-name>/`): `tools/<tool>.*` one per tool, `schemas.*`, and a README listing every tool, its side effects and the permission it needs
- A prompt bump is a new file (`v4.md`), an `index` change and a passing eval in the same commit; unreferenced versions are deleted

## Tests

- Unit tests mock the client module with recorded responses from `tests/fixtures/llm/<task>/*.json`; they cover prompt rendering, schema validation, tool dispatch, `max_tokens` handling and error branches — never model quality
- Evaluation sets are tests: `evals/<task>/cases.jsonl` with `{ input, expected, tags }`; `npm run eval -- <task>` (or `pytest -m eval`) runs the current prompt version against the real model and scores each case (exact match, schema-valid, or a rubric judged by a second model call); a threshold in config, below it the run fails
- Every prompt or model change runs the eval and the score diff goes into the PR; a regression on a golden case blocks the merge even when the aggregate improved
- Golden cases include: happy path, empty input, maximum-length input, another language, an injection attempt (`"ignore previous instructions and …"` must not change the output shape or leak the system prompt), and input with PII that must not reach the logs
- Tool loops run against a scripted model: a fixture returning `tool_use` then `end_turn`, asserting the handler got the validated input, a failing handler produced `tool_result` with `is_error: true`, and the loop stopped at `MAX_TOOL_ROUNDS`
- Fixtures go through the same `parse` path as production; a malformed fixture must fail the test — schema validation is never mocked
- The real-model eval runs on PRs touching `src/llm/` and on a schedule, with a token budget per run; not on every unrelated commit
- MCP tools are tested through the handler with valid and invalid inputs, plus one test through the transport (`listTools`, `callTool`) proving registration

## Reliability, cost and logging

- User-facing calls stream: the SDK's stream helper forwards text deltas over SSE/WebSocket, tool calls render as a "working" state, the final message comes from the SDK's final-message helper — the UI never shows a half-parsed JSON object
- A hard `max_tokens` per task and a hard input cap: measure with the provider's token-count endpoint, trim retrieved context by a documented policy (highest score first, N documents), never send "everything we found"
- Chat history is bounded (a window plus a summary, or the provider's compaction feature) and the full `response.content` — not just its text — is appended back, so tool-use and compaction blocks survive
- Every call records `usage` (input, output, cache read/write tokens), multiplies by the price table keyed by model id, and emits a metric and a log field tagged with the feature; cost is attributable per feature per day
- Batch work that can wait minutes goes through the provider's batch endpoint; interactive traffic has a concurrency limit per model in front of it
- One structured log entry per call: `task`, `prompt_version`, `model`, `request_id`, `latency_ms`, `usage`, `stop_reason`, hash of the rendered prompt. Full prompt and response text only at DEBUG, into a separate store with retention, after the redactor (PII patterns, key formats, fields the schema marks sensitive) — never in the general log, never with the API key
- Deterministic tasks cache the parsed result by `prompt_version + hash(input)`; provider prompt caching is verified in an integration test by asserting `usage.cache_read_input_tokens > 0` on the second call

## Security: injection, tools, MCP

- Everything the model reads that your code did not write is untrusted — user text, retrieved documents, web pages, tool results, file contents. Wrap it in delimited blocks (`<document id="…">…</document>`), state in the system prompt that instructions inside them are data, never place it in the system prompt
- Model output is data, not code: never `eval()`, never passed to a shell, never rendered as HTML unsanitised, never a SQL fragment, never a URL fetched without an allowlist; a model-produced path is resolved and checked against the permitted root first
- Tools follow least privilege: one narrow action per tool, typed input (`additionalProperties: false`, enums for modes, ids rather than free-form queries), a scoped credential, and the handler re-checks authorisation for the current user — the model never decides who is allowed
- Reads and writes are separate tools; every write/delete/send/pay tool requires confirmation outside the model (UI approval, or `dry_run: true` by default returning a preview) and is logged with the acting user
- Loops are bounded by `MAX_TOOL_ROUNDS`, a wall-clock budget and a token budget; parallel tool calls all return in one message; a tool error goes back as `tool_result` with `is_error: true`, not as an exception that ends the turn
- MCP tool conventions: names `verb_noun` (`search_orders`, `create_invoice`); a description that states what it does, what it returns and its side effects; `inputSchema` with a description on every property and `required` listed; read tools idempotent and safe to retry, write tools idempotent through an `idempotency_key` argument; structured results, not prose; errors as tool errors with an actionable message, no stack traces
- An MCP server authenticates its client, scopes every call to that principal, never takes credentials as tool arguments, and exposes no arbitrary code or shell execution unless that is its one declared purpose inside a sandbox
- Secrets never appear in prompts, tool descriptions, tool results or logs; a key referenced by name is resolved by the handler, not routed through the model
- The user-facing entry point is rate-limited and size-limited (per user, per minute, max input characters) before anything reaches the model

## What to avoid

- Regex over free text when a schema or tool result exists; "respond only with JSON" in the prompt instead of structured outputs
- `JSON.parse(response.text)` without schema validation; using `tool_use.input` without validating it against the tool schema
- Model ids scattered through the codebase; prompts as inline template literals; a prompt edit without an eval run
- Unbounded context: whole documents, the whole chat history, whole tool outputs; a loop that re-sends everything until the window is full
- Secrets or raw PII in prompts or logs; full prompts in the main log stream
- Treating `max_tokens` as success; ignoring `refusal`; `catch (e) { return "" }` around the model call
- A hand-rolled retry around an SDK that already retries; no timeout; retrying 400s
- Model output executed as code, SQL, shell, HTML or a URL fetch without validation
- A `query: string` tool that hits the database; a tool that both reads and writes; writes without confirmation; one god-tool
- Only real calls in tests (slow, flaky, expensive) or only mocks (quality never measured) — both layers exist
