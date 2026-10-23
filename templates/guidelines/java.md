---
tag: java
keywords: java, jdk, jvm, maven, gradle, junit, junit5, assertj, mockito, records, sealed, streams, jackson, lombok
---

# Guidelines: Java

## Style

- Modern Java (21+ LTS): `record` for DTOs and immutable value objects, `sealed interface` + pattern-matching `switch` for closed hierarchies, text blocks for multi-line strings, `var` when the type is obvious from the right-hand side
- Formatter: Spotless with `palantir-java-format` or `google-java-format`, wired into the build (`spotlessCheck` fails CI) — run it; do not argue with it
- `Optional` only as a return type — never as a field, parameter or collection element; never `Optional.get()` without `isPresent()` (use `orElseThrow`, `map`, `orElse`)
- Streams for transformations, loops for side effects; no `forEach` with mutation inside a stream
- Immutable collections by default: `List.of`, `Map.of`, `Collectors.toUnmodifiableList()`
- Exceptions: unchecked for programming/domain errors, checked only when the caller can realistically recover; wrap with context, never `catch (Exception e) { }`
- Virtual threads (`Executors.newVirtualThreadPerTaskExecutor()`) for I/O-bound concurrency instead of hand-tuned thread pools; no `synchronized` around blocking I/O inside virtual threads
- Jackson: annotate records explicitly where names differ (`@JsonProperty`), `FAIL_ON_UNKNOWN_PROPERTIES` off only for external APIs
- Lombok only for `@Slf4j`/`@Builder` on legacy classes — a `record` replaces `@Value`/`@Data`

## Project structure

- Package-by-feature (`com.example.booking`, `com.example.billing`), not package-by-layer; inside a feature: `api`, `application`, `domain`, `infrastructure` as needed
- Shared technical code in one `core`/`common` package (base exceptions, Problem Details for errors, pagination) — nothing domain-specific there
- Build with the wrapper, committed to the repo: `./mvnw` (Maven) or `./gradlew` with the Kotlin DSL (Gradle); one build tool per repo
- Dependency versions in one place (Maven `dependencyManagement` / Gradle version catalog `libs.versions.toml`)
- Business logic in the domain, not in controllers, mappers or repositories; no `Utils`, `Helper`, `GenericService` classes
- Spring Boot projects: constructor injection only, `@Transactional` at the application/service layer, Flyway or Liquibase for the schema (never `ddl-auto=create/update`), configuration via profiles and environment — nothing hardcoded

## Tests

- JUnit 5 (`@Test`, `@ParameterizedTest`, `@Nested`) + AssertJ (`assertThat(x).isEqualTo(y)`) + Mockito; `src/test/java` mirroring the main packages
- Run one test: `./mvnw -Dtest=BookingServiceTest#rejectsOverlap test` / `./gradlew test --tests 'BookingServiceTest.rejectsOverlap'`
- Unit tests without a framework context; integration tests with Testcontainers for the real database/broker — never H2 standing in for PostgreSQL
- Mock only the boundaries (HTTP clients, clock, message broker); never mock the class under test or value objects; inject `java.time.Clock` so time is controllable
- Test names describe behaviour: `rejectsBookingWhenRoomIsTaken()`; one behaviour per test

## API contracts

- Request/response as `record`s; never expose persistence entities directly
- Correct HTTP status codes; errors as Problem Details (RFC 9457) with a stable `type`/`code`
- Every enum a client sees is explicit in the contract (`code`, `label`) — never the ordinal

## What to avoid

- Public fields, public setters on domain objects, anemic entities with logic in services only
- `null` as a return value (`Optional`, empty collection or an exception instead) and `null` checks instead of types
- Raw types, unchecked casts, `instanceof` chains where a sealed type and `switch` fit
- `System.out.println` for logging — SLF4J with parameterised messages (`log.info("booked {}", id)`)
- Static mutable state, singletons by hand, `Thread.sleep` in tests
- `java.util.Date`/`Calendar` — `java.time` only
- String concatenation in SQL/JPQL — parameters always
- Catching `Throwable`/`Error`, swallowing `InterruptedException` without re-interrupting
