---
tag: spring
keywords: spring boot, spring, controller, service, repository, jpa, hibernate, spring data, spring security, application.yml, webmvctest, datajpatest, testcontainers, actuator
---

# Guidelines: Spring Boot

## Style

- Constructor injection into `private final` fields; a single constructor needs no `@Autowired`; Lombok `@RequiredArgsConstructor` is acceptable, field and setter injection are not
- Layers: `@RestController` (mapping, validation, DTO ↔ command) → `@Service` (use case, transaction boundary) → Spring Data repository; a controller never calls a repository, a service never sees `HttpServletRequest`
- Typed, immutable configuration: `@ConfigurationProperties(prefix = "app.mail") public record MailProperties(@NotBlank String host, @Positive int port) {}` + `@ConfigurationPropertiesScan` and `@Validated`; `@Value` only for a single one-off value
- `application.yml` (not `.properties`) + `application-dev.yml`, `application-test.yml`, `application-prod.yml`; secrets as placeholders `${DB_PASSWORD}` resolved from the environment, never literal
- `@Transactional` on public service methods, `readOnly = true` for queries; it does nothing on `private` or self-invoked methods, so annotate the public entry point
- Controllers return the record directly with `@ResponseStatus(HttpStatus.CREATED)`; `ResponseEntity<T>` only when status or headers vary at runtime
- Spotless with `google-java-format` or `palantir-java-format` wired into the build; run it, do not argue with it

## Project structure

- Package by feature: `com.example.app.orders` holds `OrderController`, `OrderService`, `OrderRepository`, `Order` (entity), `dto/`, `OrderProperties`; cross-cutting code in `com.example.app.common` (error handling, security config, Jackson config)
- `@SpringBootApplication` in the root package so component scanning covers every feature; no `scanBasePackages`
- Gradle Kotlin DSL (`build.gradle.kts`) with the Spring Boot plugin and the BOM, or Maven with `spring-boot-starter-parent` — one tool per repository, wrapper (`./gradlew`, `./mvnw`) committed
- Starters only (`spring-boot-starter-web`, `-data-jpa`, `-validation`, `-security`, `-actuator`); pin a version only for libraries the BOM does not manage
- Flyway scripts in `src/main/resources/db/migration/V1__init.sql`; `spring.jpa.hibernate.ddl-auto: validate` in every profile including test
- `spring.jpa.open-in-view: false` in `application.yml`

## Tests

- JUnit 5 + AssertJ + Mockito; Testcontainers Postgres with `@ServiceConnection` on the container field, no datasource properties in test config
- Slices by layer: `@WebMvcTest(OrderController.class)` + `MockMvc` + `@MockitoBean OrderService` for mapping, validation and advice; `@DataJpaTest` + `@AutoConfigureTestDatabase(replace = NONE)` + the container for repositories and queries; plain JUnit without Spring for services: `new OrderService(mock(OrderRepository.class), new FixedClock())`
- A handful of `@SpringBootTest(webEnvironment = RANDOM_PORT)` tests with `TestRestTemplate` for critical flows only; same configuration everywhere so the context is cached; no `@DirtiesContext`
- Security in slices: `@WithMockUser(roles = "ADMIN")` or `.with(jwt().authorities(new SimpleGrantedAuthority("SCOPE_orders:write")))`; every protected endpoint has a 401-without-principal and a 403-wrong-role test
- Run one: `./gradlew test --tests "com.example.app.orders.OrderControllerTest.createOrder_missingItems_returns400"` (`./mvnw -Dtest=OrderControllerTest#createOrder_missingItems_returns400 test`)
- Cover: 400 with field-level `ProblemDetail` errors, 404 as `ProblemDetail`, 409 on `OptimisticLockingFailureException`, pagination defaults and max page size, `@ConfigurationProperties` validation failing fast on a missing value
- Never mock the repository inside `@DataJpaTest`; never mock `EntityManager` or `JdbcTemplate`; H2 only when the project has no Postgres-specific SQL

## Spring Data JPA

- Entities: `@Id @GeneratedValue(strategy = GenerationType.IDENTITY)` or UUID, `@Version Long version`, `@ManyToOne(fetch = FetchType.LAZY)` on every association (the default EAGER is a trap), `protected` no-arg constructor, no Lombok `@Data` / `@EqualsAndHashCode`
- Load what the use case needs inside the transaction: `@EntityGraph(attributePaths = "items")` or `@Query("select o from Order o join fetch o.items where o.id = :id")`, then map to a DTO before the transaction ends
- Derived queries for one or two conditions (`findByCustomerIdAndStatus`), `@Query` JPQL beyond that, interface or record projections for read models
- `Pageable` on list endpoints with `@PageableDefault(size = 20)` and `spring.data.web.pageable.max-page-size`; return `Page<OrderDto>`
- `@Modifying(clearAutomatically = true) @Query("update ...")` for bulk changes; never load-and-loop
- Batches: `saveAll` in one transaction with `spring.jpa.properties.hibernate.jdbc.batch_size: 50` and `order_inserts: true`
- Repository returns `Optional<T>`; the service throws a domain `OrderNotFoundException` on empty

## Validation, errors, security

- `@Valid @RequestBody CreateOrderRequest request` with Bean Validation on the record components (`@NotBlank`, `@Positive`, `@Size(max = 100)`); `@Validated` on the controller for `@PathVariable` / `@RequestParam` constraints
- One `@RestControllerAdvice extends ResponseEntityExceptionHandler` producing `ProblemDetail`: domain exceptions → explicit status, `MethodArgumentNotValidException` → 400 with an `errors` property of `{field, message}`; `server.error.include-stacktrace: never`, `include-message: never`
- One `SecurityFilterChain` bean: explicit `authorizeHttpRequests` ending in `.anyRequest().authenticated()`, `oauth2ResourceServer(o -> o.jwt(...))` for token APIs; `csrf(AbstractHttpConfigurer::disable)` only on stateless token APIs, never on cookie-session apps
- `@EnableMethodSecurity` + `@PreAuthorize("hasRole('ADMIN') or @orderAuth.owns(#id)")` on services for rules a URL pattern cannot express
- `PasswordEncoder` bean via `PasswordEncoderFactories.createDelegatingPasswordEncoder()`; never `NoOpPasswordEncoder`
- Actuator: `management.endpoints.web.exposure.include: health,info,prometheus`, `health.show-details: when-authorized`, the rest behind the security chain

## What to avoid

- Field injection; `@Autowired` collaborators in a test that could be a slice or a plain unit test
- JPA entities as request or response bodies; Jackson annotations on entities
- `@Transactional` on controllers or repositories; catching an exception inside a transaction and continuing (it is already rollback-only)
- `ddl-auto: update/create`, `open-in-view: true`, `FetchType.EAGER`, `CascadeType.ALL` on `@ManyToOne`
- `@SpringBootTest` for every test; `@MockitoBean` replacing a bean a slice would provide for free
- `@Scheduled` in a multi-instance deployment without ShedLock; static mutable state in a `@Component`
- `Map<String, Object>` or `ResponseEntity<?>` from controllers; `Object` in DTOs
- `permitAll()` on `/**` as a shortcut; `http://localhost` or ports hardcoded in `application.yml` outside the `dev` profile
