---
tag: go
keywords: go, golang, go.mod, goroutine, channel, context, net/http, chi, sqlc, pgx, gofmt, golangci-lint, slog, testify
---

# Guidelines: Go

## Style

- `gofmt` and `goimports` are the formatter — run them; do not argue with them
- `golangci-lint run` passes before every commit; fix findings, do not `//nolint` them without a reason in the comment (`//nolint:errcheck // close on read-only file`)
- `MixedCaps` for identifiers, no underscores; exported = capitalised and documented with a comment starting with the name (`// Server handles ...`)
- Short names in small scopes (`i`, `r`, `ctx`), descriptive names in wide ones; receiver names 1-2 letters, consistent across methods of a type
- Accept interfaces, return structs; define interfaces where they are consumed, not where they are implemented
- Keep interfaces small (1-3 methods); a `Repository` with 15 methods is a struct, not an interface
- Wrap errors with context and `%w`: `return fmt.Errorf("load user %d: %w", id, err)`; check with `errors.Is` / `errors.As`, never by string comparison
- Sentinel errors as package-level `var ErrNotFound = errors.New("not found")`; typed errors when the caller needs fields
- `context.Context` is always the first parameter (`func (s *Service) Get(ctx context.Context, id int64) (User, error)`); never store it in a struct
- Zero values are useful: design types so `var b bytes.Buffer` / `var mu sync.Mutex` work without a constructor
- Logging with `log/slog` and structured attributes: `slog.InfoContext(ctx, "order created", "order_id", id)`; never `fmt.Println` in library code

## Project structure

- One module per repository: `go.mod` at the root, module path = import path; `go mod tidy` after every dependency change
- `cmd/<binary>/main.go` — wiring only (flags, config, construct dependencies, `run(ctx) error`); `internal/<domain>/` — everything not meant to be imported by other modules; `pkg/` only for code intentionally exported
- Package names: short, lowercase, singular, no `util`/`common`/`helpers`; the package name is part of the call site (`user.New`, not `user.NewUser`)
- `main` returns through `func run(ctx context.Context, args []string) error` so it can be tested; `os.Exit` only in `main`
- Configuration from environment variables parsed once at start into a struct; fail fast on a missing required value
- Dependencies passed explicitly via constructors (`NewServer(db *pgxpool.Pool, log *slog.Logger)`); no DI framework, no global singletons
- HTTP: standard `net/http` with the `ServeMux` method+path patterns (`mux.HandleFunc("GET /users/{id}", h.getUser)`); add `chi` only when middleware groups or sub-routers are needed
- Handlers are methods on a struct holding dependencies; decode → validate → call service → encode; no business logic in handlers
- Database: `pgx`/`pgxpool` driver + `sqlc` generated queries from `.sql` files in `internal/db/queries/`; never hand-build SQL with string concatenation
- Migrations as versioned SQL files (`migrations/0001_init.sql`) run by a tool (`goose`/`migrate`), not by `init()`

## Tests

- Standard `testing` package, `go test ./...`; one test: `go test ./internal/user -run TestService_Get/not_found`
- Table-driven tests with named subtests: `tests := []struct{ name string; in X; want Y; wantErr error }{...}` + `for _, tt := range tests { t.Run(tt.name, func(t *testing.T) {...}) }`
- `testify/require` for assertions that must stop the test (`require.NoError`), `assert` for the rest; or plain `if got != want { t.Fatalf(...) }` — pick one per repository
- Test files next to the code (`user_test.go`); external test package (`package user_test`) for black-box tests of the public API
- `t.Helper()` in every test helper; `t.Cleanup` instead of manual defers; `t.TempDir()` for files
- `t.Parallel()` in tests that do not share state; capture loop variables if the toolchain predates per-iteration loop variables
- HTTP handlers tested with `httptest.NewRecorder` + `http.NewRequestWithContext`; full server tested with `httptest.NewServer`
- Mock only the boundaries you own as interfaces (payment gateway, mailer); never mock the database driver — run queries against a real database in a container or a test schema, never against the production one
- Test failure modes: cancelled context (`ctx, cancel := context.WithCancel(ctx); cancel()`), timeouts, wrapped errors (`errors.Is(err, ErrNotFound)`), concurrent access with `go test -race`
- Integration tests behind a build tag or `testing.Short()` skip; `go test -race ./...` is part of CI
- Golden files in `testdata/` with an `-update` flag; `testdata/` is ignored by the Go tool

## Concurrency

- Do not start a goroutine without knowing how it stops: every `go func()` has a cancellation path (`ctx.Done()`) and an owner that waits (`sync.WaitGroup`, `errgroup.Group`)
- `errgroup.WithContext` for fan-out with error propagation; `semaphore` or a buffered channel to bound parallelism
- Channels for ownership transfer and signalling; `sync.Mutex` for protecting shared state — do not use channels as a mutex
- The sender closes the channel, never the receiver; `select` with `ctx.Done()` on every blocking send/receive
- Never pass a mutex by value; a struct with a mutex is used through a pointer; keep the critical section minimal and do not call out of it
- `time.After` in loops leaks until it fires — use `time.NewTimer` and `Stop`, or `context.WithTimeout`
- Always set `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout` on `http.Server`; `http.ListenAndServe` with defaults is not production code
- Graceful shutdown: `signal.NotifyContext` → `srv.Shutdown(ctx)` with a deadline

## Security

- Parameterised queries only (`$1`, `$2`) — `sqlc` enforces this; never `fmt.Sprintf` into SQL
- Validate request bodies after decoding; `http.MaxBytesReader` on every body-reading handler; `json.Decoder.DisallowUnknownFields` for strict APIs
- Secrets from environment or a secret manager, never in source or flags visible in `ps`
- `crypto/rand` for tokens and ids, never `math/rand`; constant-time comparison (`subtle.ConstantTimeCompare`) for secrets
- `html/template` for HTML output (auto-escaping), never `text/template`
- Run `govulncheck ./...` in CI

## What to avoid

- `_ = err` or an ignored error return; `panic` for expected failures (only for programmer errors at startup)
- `init()` functions with side effects; package-level mutable state
- `interface{}`/`any` where a concrete type or generic parameter fits; reflection in business code
- Returning `nil, nil` — return a zero value plus an error, or a value plus `nil`
- Naked returns, named results used for anything but documentation or deferred modification
- Deep package trees mirroring "layers" (`controllers/`, `services/`, `models/`) — group by domain
- `goroutine` + `WaitGroup` for a single piece of work; `context.Background()` deep inside call chains instead of the passed `ctx`
- Shadowing `err` with `:=` inside `if` blocks so the outer error is never checked
- `time.Sleep` to synchronise tests; `log.Fatal` outside `main`
