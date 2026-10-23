---
tag: rust
keywords: rust, cargo, crate, rustfmt, clippy, tokio, serde, thiserror, anyhow, async, trait, ownership, borrow, unsafe, nextest
---

# Guidelines: Rust

## Style

- `cargo fmt` is the formatter — run it; do not argue with it. `cargo clippy --all-targets -- -D warnings` passes before every commit
- `snake_case` for functions, variables, modules and crates; `CamelCase` for types and traits; `SCREAMING_SNAKE` for consts and statics
- Suppress a lint only with a reason: `#[allow(clippy::too_many_arguments)] // builder follows`; never a crate-wide `#![allow(...)]`
- Document every public item with `///` and an `# Examples` block where it helps; `//!` at the top of `lib.rs`
- Prefer borrowing in parameters: `fn render(items: &[Item]) -> String`, not `Vec<Item>`; `&str` not `&String`, `impl AsRef<Path>` for paths
- Return owned types from constructors and builders; take `self` by value in builder methods
- Clone deliberately: a `.clone()` to satisfy the borrow checker needs a one-line justification or a redesign (`Rc`/`Arc`, indices, splitting the struct)
- Make invalid states unrepresentable: enums with data instead of `Option<A>` + `Option<B>` pairs; newtypes for ids (`struct UserId(u64)`)
- `match` must be exhaustive — no `_ =>` arm on your own enums; let the compiler find the missing variant when one is added
- Iterators and combinators over index loops; `collect::<Result<Vec<_>, _>>()` to fail on the first error
- `impl Trait` in argument position for simple generics, explicit type parameters when the type appears twice; `dyn Trait` only for heterogeneous collections or plugin boundaries

## Project structure

- `Cargo.toml` with `edition` set to the current edition, `[lints]` table for shared clippy configuration; `Cargo.lock` committed for binaries and applications
- `src/main.rs` is thin: parse args (`clap` with derive), build config, call `lib::run(config)`; all logic in `src/lib.rs` and modules so it is testable
- Modules as `src/<name>.rs` + `src/<name>/` for children (no `mod.rs`); `pub(crate)` by default, `pub` only for the intended API
- Multi-crate work uses a workspace: `crates/<name>/`, shared `[workspace.dependencies]`, one `Cargo.lock` at the root
- Configuration from environment variables or a file deserialised with `serde` into a `Config` struct validated at startup
- `serde` derives on DTOs with `#[serde(rename_all = "camelCase", deny_unknown_fields)]` for strict input; keep wire types separate from domain types
- Async runtime: `tokio` with `#[tokio::main]`, `tracing` + `tracing-subscriber` for logs (`tracing::info!(user_id = %id, "created")`); never `println!` in library code
- Web services: `axum` + `tower` middleware; database: `sqlx` with compile-time checked queries (`sqlx::query_as!`) or `sea-orm` — pick one per project
- Features in `Cargo.toml` are additive and default-off for optional heavy dependencies

## Tests

- Unit tests in the same file under `#[cfg(test)] mod tests { use super::*; ... }`; integration tests in `tests/<feature>.rs` using only the public API
- Run with `cargo test`; one test: `cargo test store::tests::not_found_returns_error`; `cargo nextest run` when installed (per-test process isolation, faster)
- Test names describe behaviour: `fn expired_token_is_rejected()`; `#[should_panic(expected = "...")]` only for documented panics
- Async tests with `#[tokio::test]`; use `tokio::time::pause()` and `advance()` for timeouts instead of real sleeps
- Doc tests (` ``` ` blocks in `///`) are tests — keep them compiling or mark `no_run`/`ignore` with a reason
- Mock boundaries by trait: define `trait Clock { fn now(&self) -> Instant; }`, inject a fake in tests; `mockall` only when hand-written fakes grow large
- Never mock the database driver — integration tests use a real database (`sqlx::test` macro or a container) and a fresh schema per test
- Test failure modes: every error variant has a test that triggers it; `Result` of a fallible function is matched with `assert!(matches!(err, StoreError::NotFound(_)))`
- Property tests with `proptest` for parsers, serialisers and arithmetic; snapshot tests with `insta` for rendered output
- `cargo test` in CI runs with `RUSTFLAGS="-D warnings"`; `cargo deny check` or `cargo audit` for dependency advisories

## Error handling

- Library crates: a dedicated error enum per module derived with `thiserror` (`#[derive(Debug, thiserror::Error)] enum StoreError { #[error("user {0} not found")] NotFound(UserId), #[error(transparent)] Db(#[from] sqlx::Error) }`)
- Binary crates and tests: `anyhow::Result<T>` with `.context("reading config")?`; never `anyhow` in a library's public API
- `?` everywhere; `unwrap()`/`expect()` only in tests, examples and for invariants the type system cannot express — `expect` with a message saying why it cannot fail
- Never `panic!` for runtime conditions (bad input, I/O failure, missing data); panics are for programmer errors
- Implement `std::error::Error` sources correctly (`#[source]` / `#[from]`) so the chain prints with `{:#}`

## Unsafe policy

- No `unsafe` in application code; `#![forbid(unsafe_code)]` in `lib.rs` of every crate that does not need FFI
- Where FFI requires it: minimal `unsafe` block, a `// SAFETY:` comment above it stating the invariant that makes it sound, a safe wrapper function around it, and a test exercising it under `cargo miri test` when possible
- Never use `unsafe` to silence the borrow checker, to transmute between types, or for performance without a benchmark proving the need

## Concurrency

- `Arc<Mutex<T>>` only for genuinely shared mutable state; prefer message passing (`tokio::sync::mpsc`) and ownership transfer
- `tokio::sync::Mutex` only when the lock is held across an `.await`; otherwise `std::sync::Mutex` (or `parking_lot`) and release before awaiting
- Never block the async runtime: CPU-heavy or blocking I/O goes through `tokio::task::spawn_blocking`
- Every spawned task has an owner that awaits its `JoinHandle` or a cancellation token (`tokio_util::sync::CancellationToken`); no fire-and-forget tasks
- `Send + 'static` bounds appear in signatures only where tasks are actually spawned

## What to avoid

- `.unwrap()` on `Option`/`Result` outside tests; `.clone()` sprinkled to make the borrow checker quiet
- Stringly-typed errors (`Result<T, String>`, `Box<dyn Error>` in library APIs)
- `Rc`/`RefCell` in multithreaded code; `static mut`
- `as` casts between integer widths where `try_from` / `From` fit — silent truncation
- Giant `main.rs`; a `utils` module; `mod.rs` files mixed with the modern layout
- `#[derive(Clone)]` on large structs holding `Vec`s "just in case"; `String` where `&str` or `Cow<str>` fits
- Blocking `std::thread::sleep` / `std::fs` inside async functions
- `#[allow(dead_code)]` to hide unused code — delete it
- Wildcard dependency versions (`"*"`) and unpinned git dependencies
