---
tag: csharp
keywords: c#, csharp, dotnet, .net, asp.net core, minimal api, controller, entity framework, ef core, xunit, fluentassertions, nullable, async, dependency injection, nuget
---

# Guidelines: C# / .NET

## Style

- `dotnet format` is the formatter; `.editorconfig` at the repository root holds the rules — run it; do not argue with it
- Analyzers on: `<EnableNETAnalyzers>true</EnableNETAnalyzers>`, `<AnalysisLevel>latest</AnalysisLevel>`, `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>` in `Directory.Build.props`
- Nullable reference types enabled everywhere (`<Nullable>enable</Nullable>`); no `!` null-forgiving operator except in tests with a comment; `ArgumentNullException.ThrowIfNull(x)` at public boundaries
- `PascalCase` for types, methods, properties and public fields; `camelCase` for locals and parameters; `_camelCase` for private fields; interfaces start with `I`; async methods end with `Async`
- File-scoped namespaces (`namespace App.Orders;`), one public type per file, `global using` in a single `GlobalUsings.cs`
- `record` for immutable data (DTOs, commands, events): `public sealed record CreateOrder(Guid CustomerId, IReadOnlyList<OrderLine> Lines);`; `class` for entities and services; `sealed` by default
- `var` when the type is obvious from the right-hand side, explicit type otherwise; target-typed `new()` for fields and properties
- Pattern matching and `switch` expressions over `if`/`else` chains; exhaustive handling of your own enums (no `_ =>` arm that hides a new value)
- Async all the way: `async Task`/`Task<T>`, never `async void` (except event handlers), never `.Result`/`.Wait()`/`GetAwaiter().GetResult()`; pass `CancellationToken` through every async signature
- `ConfigureAwait(false)` in library code, not in ASP.NET Core application code
- Exceptions for exceptional conditions; expected failures as a result type (`Result<T>`/`OneOf`) or `TryX(out ...)`; custom exceptions derive from `Exception` and end in `Exception`
- Logging via `ILogger<T>` with message templates and named placeholders: `_logger.LogInformation("Order {OrderId} created", order.Id)` — never string interpolation in the template

## Project structure

- `src/<Project>/` and `tests/<Project>.Tests/`; one `.sln` at the root; `Directory.Build.props` + `Directory.Packages.props` (central package management) at the root
- Group by feature/vertical slice (`Features/Orders/CreateOrder.cs` holds endpoint + handler + validator), not by technical layer (`Controllers/`, `Services/`, `Repositories/`)
- Minimal APIs by default: `app.MapGroup("/orders").MapPost("/", CreateOrder.Handle).WithName(...)`; endpoint methods take dependencies as parameters, return `TypedResults.Ok(...)`/`TypedResults.NotFound()`, typed `Results<Ok<T>, NotFound>`
- Controllers only when the project already uses them or needs their filter pipeline; then `[ApiController]`, `ActionResult<T>`, thin actions
- DI: register in `Program.cs` through extension methods per feature (`services.AddOrders()`); constructor injection only, no service locator (`IServiceProvider.GetService` in business code); lifetimes: `Scoped` for `DbContext`-dependent services, `Singleton` for stateless, never a `Scoped` dependency in a `Singleton`
- `IOptions<T>` bound from configuration sections with `services.AddOptions<MailSettings>().BindConfiguration("Mail").ValidateDataAnnotations().ValidateOnStart()`
- Configuration layering: `appsettings.json` (defaults, no secrets) → `appsettings.{Environment}.json` → environment variables → user secrets in Development (`dotnet user-secrets set "Db:Password" ...`); production secrets from environment or a vault, never in any `appsettings*.json`
- `HttpClient` via `IHttpClientFactory` typed clients with resilience (`AddStandardResilienceHandler()`), never `new HttpClient()` per call
- Validation of request DTOs with `FluentValidation` or data annotations in an endpoint filter — one approach per project; return `ValidationProblem`
- Entities: private setters, behaviour on the entity, factories/constructors enforcing invariants; EF Core `IEntityTypeConfiguration<T>` classes in `Infrastructure/Persistence/Configurations/`

## Tests

- xUnit + FluentAssertions (`result.Should().BeEquivalentTo(expected)`); `NSubstitute` for mocks of boundaries you own as interfaces
- Layout mirrors `src/`: `tests/App.Tests/Features/Orders/CreateOrderTests.cs`; test class per subject, `[Fact]` for single cases, `[Theory]` + `[InlineData]`/`[MemberData]` for variants
- Run all: `dotnet test`; one test: `dotnet test --filter "FullyQualifiedName~CreateOrderTests.Rejects_empty_lines"`
- Names describe behaviour: `Rejects_order_without_lines`, `Returns_404_when_order_missing`
- HTTP endpoints tested through `WebApplicationFactory<Program>` (`Microsoft.AspNetCore.Mvc.Testing`) with a real pipeline and swapped infrastructure; `public partial class Program {}` at the end of `Program.cs` to make it visible
- Never mock `DbContext`/`DbSet` — use a real database (Testcontainers for the production engine) or SQLite in-memory for pure query logic; the EF in-memory provider is not a database and skips constraints
- Time through an injected `TimeProvider` (`FakeTimeProvider` in tests); random through an injected source
- Test failure modes: validation errors return `400` with the field name in `ProblemDetails.Errors`, cancelled tokens are honoured, concurrency conflicts surface as `409`, options validation fails at startup with a clear message
- `dotnet test --collect:"XPlat Code Coverage"` in CI; no test without an assertion

## EF Core

- `DbContext` registered `Scoped`; queries are `async` with `CancellationToken`; `AsNoTracking()` for read-only queries
- Project to DTOs in the query (`.Select(o => new OrderSummary(...))`) instead of loading entities for reads; explicit `Include` only when the entity is modified
- Migrations with `dotnet ef migrations add <Name>` checked into source; applied as a deployment step (`dotnet ef database update` or a migration bundle), never `Database.EnsureCreated()` or `Migrate()` at startup in production
- Raw SQL only through `FromSql`/`ExecuteSql` interpolated handlers (parameterised), never `FromSqlRaw` with concatenated strings
- One `SaveChangesAsync` per unit of work; transactions via `BeginTransactionAsync` only when spanning multiple contexts or external calls
- Concurrency tokens (`rowversion`) on entities edited by several users; handle `DbUpdateConcurrencyException` explicitly

## Security

- Authentication/authorisation via the built-in middleware (`AddAuthentication().AddJwtBearer()`, `RequireAuthorization("Policy")` on groups); authorise by policy, not by role string comparison in handlers
- Bind request bodies to dedicated DTOs, never to entities (over-posting); `[FromBody]`/`[FromRoute]` explicit on ambiguous parameters
- Anti-forgery for cookie-authenticated forms (`AddAntiforgery()`); CORS with an explicit origin list, never `AllowAnyOrigin()` with credentials
- Data protection keys persisted to shared storage in multi-instance deployments; connection strings and keys through configuration providers, never literals
- `System.Text.Json` with the default (safe) settings; never `BinaryFormatter`; `JsonSerializerOptions` reused as a static instance
- Return `ProblemDetails` without stack traces in production (`UseExceptionHandler` + `AddProblemDetails()`)

## What to avoid

- `async void`, `.Result`, `.Wait()`, `Task.Run` to "make it async" in ASP.NET Core
- Catching `Exception` and logging without rethrowing; `throw ex;` (loses the stack — use `throw;`)
- Static mutable state, static `HttpClient` without the factory, `DateTime.Now` (use `TimeProvider`/`DateTimeOffset.UtcNow`)
- Repository + unit-of-work wrappers around EF Core — `DbContext` already is both
- `dynamic`, reflection-based mapping in hot paths, `object` parameters
- Enums serialised as integers over the wire — use `JsonStringEnumConverter`
- Fat `Program.cs` with hundreds of registrations; business logic in middleware or filters
- `#region`, commented-out code, `TODO` without an issue reference
- Floating package versions or packages outside `Directory.Packages.props`
