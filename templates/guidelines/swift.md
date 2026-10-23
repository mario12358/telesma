---
tag: swift
keywords: swift, ios, swiftui, xcode, xcodeproj, swift package manager, spm, async, await, actor, mainactor, mvvm, xctest, swift testing, keychain, swiftlint, swiftformat, uikit
---

# Guidelines: Swift / iOS

## Style

- `SwiftFormat` is the formatter and `SwiftLint` the linter, both configured at the repository root (`.swiftformat`, `.swiftlint.yml`) and run as a build phase or pre-commit — run them; do not argue with them
- `lowerCamelCase` for functions, properties, cases and locals; `UpperCamelCase` for types and protocols; no Hungarian prefixes; argument labels read as a sentence (`func move(to point: CGPoint)`)
- `let` by default; `struct` by default, `class` only for identity or reference semantics; `final class` when you do use a class; `enum` with associated values for closed states
- Optionals: `guard let x else { return }` at the top of the function; `if let` for a short branch; `!` force-unwrap is forbidden outside tests and `@IBOutlet`
- Protocols for behaviour contracts at boundaries (`protocol OrderRepository: Sendable { func orders() async throws -> [Order] }`); protocol-oriented generics over class inheritance
- Errors: `enum StoreError: Error, LocalizedError` with cases per failure; `throws` + `do/catch` for recoverable failures; typed throws (`throws(StoreError)`) where the compiler version supports it; `try?` only when losing the error is the intended behaviour
- Strict concurrency checking on (`SWIFT_STRICT_CONCURRENCY = complete`); types that cross isolation boundaries are `Sendable`
- Access control explicit: `private` for implementation details, `internal` (default) within a module, `public` only in packages exposing an API
- `Codable` models with `CodingKeys` only when the wire names differ; `keyDecodingStrategy = .convertFromSnakeCase` configured once on the decoder
- Logging through `os.Logger(subsystem:category:)` with privacy annotations (`logger.info("loaded \(count, privacy: .public) orders")`); never `print` outside scripts

## Project structure

- Swift Package Manager for all code that is not the app shell: `Package.swift` with `Sources/<Target>/` and `Tests/<Target>Tests/`; the Xcode project contains only the app target, assets and entitlements and depends on local packages
- Split by feature and layer into targets: `Domain` (models, protocols, pure logic — no UIKit/SwiftUI import), `Data` (networking, persistence), `Features/<Name>` (views + view models), `App` (composition root)
- MVVM: `@Observable @MainActor final class OrderListViewModel` holds state and intent methods (`func load() async`); `struct OrderListView: View` renders state and calls intents; views never touch repositories or `URLSession`
- Dependencies injected through initialisers (`init(repository: any OrderRepository)`); a composition root in the `App` struct builds the graph; SwiftUI `Environment` for truly ambient values only
- Navigation with `NavigationStack` + a typed `path: [Route]` owned by a coordinator or the root view model; sheets and alerts driven by optional state, not booleans scattered through views
- Views small and composed: extract subviews as `private struct` or `@ViewBuilder private var`; a view body longer than ~40 lines is split
- Configuration per environment through `.xcconfig` files feeding `Info.plist` keys read once into a `Config` struct; no `#if DEBUG` scattered in business code
- Resources via asset catalogs and `String(localized:)`/string catalogs (`.xcstrings`); never hardcoded user-visible strings

## Tests

- Swift Testing (`import Testing`, `@Test("rejects empty cart") func rejectsEmptyCart() async throws`, `#expect(...)`, `#require(...)`, `@Suite`) for new unit tests; XCTest stays for UI tests and existing suites — do not mix styles within one target
- Layout: `Tests/<Target>Tests/` mirrors `Sources/<Target>/`; UI tests in the `<App>UITests` target
- Run all: `swift test` for packages, `xcodebuild test -scheme App -destination 'platform=iOS Simulator,name=<simulator>'` for the app; one test: `swift test --filter OrderListViewModelTests/loadsOrders`
- Parameterised tests with `@Test(arguments: [...])`; async tests are plain `async throws` functions awaited directly — no `XCTestExpectation` dance in Swift Testing
- Mock through protocols with hand-written fakes (`final class FakeOrderRepository: OrderRepository { var result: Result<[Order], Error> }`); never mock `URLSession` by subclassing — inject a `URLProtocol` stub or a protocol over the client; never hit the real network
- Time and randomness injected (`clock: any Clock<Duration>`, `ContinuousClock` in production, a test clock in tests)
- Test failure modes: repository throws → view model exposes an error state, cancellation mid-load leaves state consistent, decoding of a malformed payload fails with a typed error, empty results render the empty state
- UI tests: `XCUIApplication()` with `launchArguments = ["-uiTesting"]` to swap in fakes; locate elements only by accessibility identifier (`app.buttons["order.submit"]`), never by label text; `waitForExistence(timeout:)` instead of `sleep`
- Every interactive SwiftUI element gets `.accessibilityIdentifier("screen.element")` and a sensible `.accessibilityLabel`; identifiers are constants in one `enum AccessibilityID`
- Snapshot tests for screens when the project has them; run tests with Thread Sanitizer on in a CI configuration

## Concurrency

- `async/await` and structured concurrency only; no completion handlers in new code (`withCheckedThrowingContinuation` to wrap legacy APIs exactly once)
- UI state is `@MainActor`; view models are `@MainActor`; data layer types are `actor`s or `Sendable` structs; never `DispatchQueue.main.async` to "fix" a warning
- Child work through `async let` and `TaskGroup`; `Task { }` only at the boundary where a synchronous context (a button action) starts async work, and then stored and cancelled when the view disappears (`.task { }` modifier does this for you — prefer it)
- Check `Task.isCancelled` / call `try Task.checkCancellation()` in loops; cancellation is cooperative
- `Task.detached` is almost never right; `Task.sleep(for:)` instead of `DispatchQueue.asyncAfter`
- Streams of values as `AsyncSequence`/`AsyncStream`, consumed with `for await` inside `.task`

## Security

- Secrets (tokens, refresh tokens, keys) in the Keychain through a small `KeychainStore` wrapper (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`); never in `UserDefaults`, `Info.plist`, or source
- API keys that must ship in the binary are treated as public — move the privileged call behind a backend
- `URLSession` with App Transport Security on; certificate pinning only with a rotation plan; no `NSAllowsArbitraryLoads`
- Validate and bound everything decoded from the network before it reaches the UI; never `unsafeBitCast`/`unsafeFlags`
- Biometric/`LocalAuthentication` gates for sensitive screens where the spec asks; sensitive data hidden in the app switcher snapshot (`.privacySensitive()`)

## What to avoid

- Force unwraps and `try!` in production; `as!` casts; `fatalError` for recoverable conditions
- Massive view bodies, `AnyView` erasure, `GeometryReader` wrapping everything
- `@State` holding reference types or shared data; `@ObservedObject` where `@StateObject`/`@Observable` ownership is meant
- Singletons (`.shared`) as hidden dependencies in view models; `NotificationCenter` as an app-wide event bus
- Combine for new async code where `async/await` fits; completion-handler pyramids
- `DispatchQueue.main.async` sprinkled to silence concurrency warnings; `@unchecked Sendable` without a comment stating the invariant
- CocoaPods or Carthage for new dependencies; committing `xcuserdata/`, `DerivedData/`
- Storyboards for new screens; string-typed segues or navigation
- Testing view models through the UI only, or UI tests that depend on label text and locale
