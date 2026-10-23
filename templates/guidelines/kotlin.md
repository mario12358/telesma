---
tag: kotlin
keywords: kotlin, kt, kts, gradle, coroutines, flow, suspend, android, jetpack compose, viewmodel, hilt, ktor, spring boot, junit5, kotest, ktlint, detekt
---

# Guidelines: Kotlin

## Style

- `ktlint` is the formatter (official Kotlin style, `.editorconfig` at the root); `detekt` is the linter — run both; do not argue with them. Baseline files only for legacy code, never for new findings
- `camelCase` for functions, properties and locals; `PascalCase` for classes, objects and Composables; `SCREAMING_SNAKE` for `const val`; file name = the single public class it holds
- `val` by default, `var` only when mutation is required; immutable collections in APIs (`List`, `Map`), mutable ones (`MutableList`) only as local builders
- Null safety: non-null types by default; `?.`, `?:` and `let` for nullable handling; `!!` is forbidden outside tests (`requireNotNull(x) { "reason" }` when an invariant guarantees it)
- `data class` for values (DTOs, state, events); `sealed interface` for closed hierarchies (`sealed interface Result { data class Ok(val v: T): Result; data class Err(val e: Error): Result }`); `when` over a sealed type is exhaustive — no `else` branch
- Expression bodies for one-liners (`fun area() = width * height`), named arguments for calls with more than two parameters or booleans (`load(force = true)`)
- Extension functions for utilities on types you do not own; keep them in a file named after the receiver (`StringExt.kt`); no `Utils.kt`
- Scope functions deliberately: `apply` for configuration, `let` for nullable transforms, `also` for side effects; never nest more than one
- Errors: exceptions for programmer errors and unrecoverable failures; expected failures as a `sealed` result or `Result<T>`; never `catch (e: Exception)` without rethrowing or mapping; never catch `CancellationException`
- Logging through a facade injected or a `private val log = KotlinLogging.logger {}`; no `println` outside `main`

## Project structure

- Gradle Kotlin DSL (`build.gradle.kts`, `settings.gradle.kts`) with a version catalog (`gradle/libs.versions.toml`) — every dependency version lives there; Gradle wrapper committed
- Multi-module from the start when there is more than one deployable or a shared domain: `:app`, `:core:domain`, `:core:data`, `:feature:<name>`; `internal` visibility for everything not meant to cross a module
- Package by feature (`com.example.orders`), not by layer (`com.example.repositories`)
- Configuration via typed objects bound at startup (`@ConfigurationProperties` in Spring, `ApplicationConfig` in Ktor, `BuildConfig`/`local.properties` on Android); secrets never in source or committed property files

## Tests

- JUnit 5 (`@Test`, `@ParameterizedTest` + `@CsvSource`/`@MethodSource`) with `kotlin.test` or AssertJ assertions; Kotest only if the project already uses it — one framework per repository
- `MockK` for mocks of boundaries you own (`every { repo.find(1) } returns order`, `coEvery` for suspend); never mock data classes, the database, or the framework
- Layout: `src/test/kotlin/` mirroring main packages; Android instrumented tests in `src/androidTest/`; names in backticks describing behaviour: `` fun `rejects order without lines`() ``
- Run all: `./gradlew test`; one class: `./gradlew :feature:orders:test --tests "com.example.orders.OrderServiceTest"`; Android UI: `./gradlew connectedAndroidTest`
- Coroutines: `kotlinx-coroutines-test` — `runTest { }`, inject `StandardTestDispatcher(testScheduler)`, `advanceUntilIdle()`; `Turbine` for `Flow` assertions (`flow.test { assertEquals(x, awaitItem()) }`); a `MainDispatcherRule` for ViewModels
- Compose: `createComposeRule()`, `onNodeWithTag("retry").performClick()`, `onNodeWithText(...).assertIsDisplayed()`; screenshot tests for screen-level Composables when the project has them
- Backend: Ktor `testApplication { client.get("/orders") }`; Spring `@SpringBootTest` + `MockMvc`/`WebTestClient` for the HTTP layer, `@DataJpaTest` with Testcontainers for repositories — never an in-memory H2 standing in for the production engine
- Test failure modes: cancellation of a running coroutine, a failing `Flow` upstream surfaced as error state, timeout handling, validation producing `400` with field names, `null` from the network mapped to a domain error

## Coroutines

- `suspend fun` for one-shot async work, `Flow<T>` for streams; never return `Deferred` from a public API
- Structured concurrency only: launch inside a scope you own (`viewModelScope`, `lifecycleScope`, an injected `CoroutineScope`, Ktor's call scope); `GlobalScope` is forbidden
- Inject `CoroutineDispatcher`s (`@IoDispatcher`), never hardcode `Dispatchers.IO` inside a class; switch with `withContext(ioDispatcher)` at the boundary that does blocking work, not in callers
- `supervisorScope`/`SupervisorJob` where one child's failure must not cancel siblings; `coroutineScope` otherwise
- Cooperative cancellation: long loops call `ensureActive()` or `yield()`; cleanup in `finally` with `withContext(NonCancellable)` only for essential writes
- `StateFlow` for state, `SharedFlow` for events; `stateIn(scope, SharingStarted.WhileSubscribed(5_000), initial)` for UI-exposed flows; `collectLatest` when only the newest value matters
- Never block a coroutine thread with `runBlocking` (tests and `main` only), `Thread.sleep`, or synchronous I/O

## Android (Jetpack Compose)

- UI = Composables; state in a `ViewModel` exposed as a single `StateFlow<UiState>` (`data class UiState(val items: List<Item> = emptyList(), val loading: Boolean = false, val error: String? = null)`); events via `fun onEvent(e: UiEvent)`
- State hoisting: Composables receive state and callbacks (`fun OrderList(state: UiState, onRetry: () -> Unit)`), they do not take the ViewModel; a thin `OrderScreen(viewModel = hiltViewModel())` wires them
- `collectAsStateWithLifecycle()` to observe flows; `remember`/`rememberSaveable` for local UI state; keys on `LazyColumn` items (`items(list, key = { it.id })`)
- Side effects only in `LaunchedEffect`/`DisposableEffect` with correct keys; no network or database calls inside composition
- Hilt for DI: `@HiltAndroidApp`, `@AndroidEntryPoint`, `@HiltViewModel` + `@Inject constructor`; modules with `@Binds` for interfaces, `@Provides` for third-party types; `@Singleton` only for app-wide objects
- Repository pattern between ViewModel and data sources (Room, Retrofit/Ktor client); Room entities and network DTOs mapped to domain models — Composables never see them
- Resources through `stringResource(R.string.x)`; `Modifier` is the first optional parameter of every Composable; `@Preview` for every screen-level Composable
- `testTag` on interactive elements for UI tests; `contentDescription` on images and icon buttons (null only for decorative ones)

## Backend (Ktor / Spring Boot)

- Ktor: `embeddedServer(...) { module() }` with `fun Application.module()` installing plugins (`ContentNegotiation` with `kotlinx.serialization`, `StatusPages`, `CallLogging`, `Authentication`); routes grouped in `fun Route.orderRoutes(service: OrderService)`; dependencies passed as constructor/function parameters or Koin
- Spring Boot: constructor injection only (no `@Autowired` on fields), `@ConfigurationProperties` data classes, `@RestController` + `@Validated` request bodies, `@Transactional` on service methods not repositories, Spring Data JDBC/JPA with `suspend` or WebFlux chosen once per project
- Request/response DTOs are `@Serializable` data classes separate from entities; validation at the boundary (`require`, `jakarta.validation`), typed error responses via `StatusPages`/`@ControllerAdvice`
- Database migrations with Flyway or Liquibase as versioned files, applied at deployment; no `ddl-auto=update` outside local development

## What to avoid

- `!!`, `lateinit var` for anything but DI/Android lifecycle fields, platform types leaking from Java APIs without explicit nullability
- `GlobalScope.launch`, `runBlocking` in production code, `Dispatchers.Main` in ViewModels without injection
- Passing a `ViewModel`, `Context` or `Activity` into Composables; business logic inside Composables
- `LiveData` in new code; `AsyncTask`, `Handler` post chains, callbacks where `suspend` fits
- Mutable `var` properties in `data class`; `Any`/`Object` typed maps as models
- `companion object` as a static-utility dumping ground; Java-style getters/setters
- Groovy `build.gradle` files, hardcoded dependency versions outside the version catalog
- Spring: field injection, `@Transactional` on private methods, `Optional` in Kotlin APIs (use nullable types)
- Catching `Throwable` or `CancellationException`; swallowing errors in `Flow.catch { }` without emitting a state
