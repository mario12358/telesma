---
tag: php
keywords: php, laravel, composer, artisan, eloquent, blade, migration, psr-12, pint, phpstan, pest, phpunit, livewire, symfony
---

# Guidelines: PHP (Laravel)

## Style

- PSR-12 via Laravel Pint (`vendor/bin/pint`), or `php-cs-fixer` outside Laravel — run it; do not argue with it
- PHPStan (with Larastan) at level 8 or higher: `vendor/bin/phpstan analyse` passes before every commit; baseline only for legacy code
- `declare(strict_types=1);` as the first statement of every PHP file; typed properties, parameters and return types everywhere (`public function find(int $id): ?User`); `mixed` is a smell
- `camelCase` for methods and variables, `PascalCase` for classes, `snake_case` for database columns and config keys; one class per file, file name = class name
- `readonly` classes/properties for value objects and DTOs (`final readonly class Money { public function __construct(public int $amount, public string $currency) {} }`); `final` by default
- Enums (`enum Status: string { case Active = 'active'; }`) instead of string constants; cast on the model (`protected $casts = ['status' => Status::class]`)
- Constructor promotion, named arguments for calls with more than two parameters, `match` over `switch`, short closures (`fn`) for one-liners
- Exceptions: domain exceptions extend a base `DomainException`; never `catch (\Throwable $e) {}` without rethrowing or reporting (`report($e)`)
- Logging through `Log::info('order created', ['order_id' => $id])` with context arrays, never string interpolation; no `dd()`/`dump()`/`var_dump()` committed

## Project structure

- Composer for all dependencies; `composer.lock` committed; PSR-4 autoload (`App\\` → `app/`); `composer validate` in CI
- Standard Laravel layout extended with intent-revealing namespaces: `app/Actions/` (one class, one `handle()` — the unit of business logic), `app/Data/` (DTOs), `app/Http/Requests/` (Form Requests), `app/Http/Resources/` (API resources), `app/Models/`, `app/Policies/`, `app/Jobs/`, `app/Events/` + `app/Listeners/`
- Controllers are thin: validate via a Form Request, call an Action, return a Resource/view/redirect; no queries, no business rules, no `Request::all()`
- Routes in `routes/web.php` / `routes/api.php` with route groups, middleware and `->name()`; resource controllers for CRUD; no closures in route files beyond prototypes
- Configuration only through `config/*.php` reading `env()`; `env()` is never called outside `config/`; `.env.example` lists every key with a safe default; `php artisan config:cache` in production
- Services bound in a service provider (`$this->app->bind(PaymentGateway::class, StripeGateway::class)`); constructor injection; no `app()->make()` or facades inside domain classes (facades are fine in controllers, jobs and tests)
- Queued jobs for anything slower than a request should be (`implements ShouldQueue`), with `$tries`, `$backoff`, idempotent `handle()`; events + listeners for cross-module side effects
- Blade components (`<x-order-row :order="$order" />`) for reusable markup; Livewire or Inertia chosen once per project for interactivity

## Tests

- Pest (`vendor/bin/pest`) on top of PHPUnit; `tests/Feature/` for HTTP and job tests, `tests/Unit/` for pure classes; file per subject (`tests/Feature/Orders/CreateOrderTest.php`)
- Run one test: `vendor/bin/pest --filter="rejects order without lines"`; `php artisan test --parallel` in CI
- `it('rejects order without lines', function () { ... })`; `uses(RefreshDatabase::class)` in `tests/Pest.php` for feature tests; datasets (`->with([...])`) for variants
- Feature tests go through HTTP: `$this->actingAs($user)->postJson('/api/orders', $payload)->assertCreated()->assertJsonPath('data.status', 'pending')`; `assertDatabaseHas` for persistence
- Real database in tests (SQLite in memory is acceptable for logic, the production engine in CI for anything with JSON columns, constraints or raw SQL); never mock Eloquent models or the query builder
- Fake only the boundaries: `Mail::fake()`, `Queue::fake()`, `Event::fake()`, `Http::fake(['api.example/*' => Http::response([...], 200)])`, `Storage::fake('s3')`; `$this->mock(PaymentGateway::class)` for your own interfaces; `Carbon::setTestNow()` / `$this->travelTo()` for time
- Test failure modes: validation returns `422` with the field name, unauthenticated → `401`, unauthorised (Policy) → `403`, missing model → `404`, job failure after `$tries` lands in `failed_jobs`, N+1 raises under `preventLazyLoading`
- Architecture tests (`arch()->expect('App\Models')->not->toUse('Illuminate\Http')`) to keep layering honest

## Eloquent and migrations

- Mass assignment: `protected $fillable` with an explicit list on every model — never `$guarded = []`; create from validated data only (`Order::create($request->validated())`)
- Relationships declared with return types (`public function lines(): HasMany`); eager load what you iterate (`Order::with('lines')->get()`); `Model::preventLazyLoading(! app()->isProduction())` in `AppServiceProvider` to catch N+1 in development and tests
- Query scopes for reusable filters (`scopeActive`), query builder for anything complex; `DB::raw` only with bound parameters, never with interpolated input
- Models carry casts, relationships, scopes and accessors — not business workflows; those are Actions
- Migrations: one per change, never edit a migration that has run anywhere else; `php artisan make:migration`, explicit `down()`; foreign keys with `->constrained()` and `cascadeOnDelete()` chosen deliberately; indexes for every column used in `where`/`orderBy`
- Seeders and factories for every model (`User::factory()->count(3)->create()`); factory states for variants (`->suspended()`)
- Transactions around multi-table writes (`DB::transaction(fn () => ...)`); `lockForUpdate()` where concurrent writes compete; `chunkById()` for batch processing
- Soft deletes only when the spec requires restore; `UUID`/`ULID` primary keys via `HasUlids` when ids are exposed

## Validation

- Form Requests for every write endpoint: `rules()` with typed arrays (`'email' => ['required', 'email:rfc', 'max:254']`), `authorize()` delegating to a Policy
- Rule objects (`php artisan make:rule`) for domain rules; `Rule::enum(Status::class)`, `Rule::exists(...)->where(...)` for references; `bail` on expensive rules
- Validated data flows as `$request->validated()` or a typed DTO built from it — never `$request->all()` or `$request->input()` into the model
- API errors return the framework's `422` shape unchanged; web forms redirect back with `@error` in Blade

## Security

- CSRF: `@csrf` in every Blade form; `VerifyCsrfToken` exceptions only for signed webhooks that verify their own signature
- Blade: `{{ $value }}` escapes; `{!! !!}` only for HTML you sanitised yourself (and say so in a comment); never build HTML strings in PHP
- Authorisation through Policies (`php artisan make:policy`) and `Gate`/`$this->authorize()`/`can` middleware on every route touching a resource; never trust an id from the request without a Policy check
- Authentication via the framework (Breeze/Fortify/Sanctum/Passport) — never hand-rolled password handling; `Hash::make`, rate limiting (`throttle`) on login and API routes
- Uploads: validate `mimes`/`max`, store outside `public/` (`Storage::disk('private')`), serve through a controller with authorisation; never trust the client file name
- SQL only via the query builder/Eloquent with bindings; `whereRaw` with `?` placeholders; `DB::statement` never with user input
- `APP_DEBUG=false` and `APP_KEY` set in production; secrets only in environment, never in `config/*.php` literals or the repository; `php artisan key:generate` once per environment
- Hidden attributes (`protected $hidden = ['password', 'remember_token']`) and API Resources so models never serialise whole; no `->toArray()` of a model in a response

## What to avoid

- `$guarded = []`, `Model::unguard()`, `Request::all()` into `create()`/`update()`
- Business logic in controllers, models, Blade views or route closures; "fat model" workflows
- `env()` outside `config/`; `config()` values changed at runtime
- Facades and `app()` inside domain classes; static helper classes with state
- Raw SQL with string interpolation; `DB::select("... $id")`
- Lazy loading in loops (N+1); `->get()` then filtering in PHP; `count($collection)` where `->count()` on the query fits
- `@php` blocks in Blade, HTML in PHP strings, `{!! !!}` with request data
- `sleep()` in jobs or tests; `php artisan migrate:fresh` on anything but a disposable database
- Untyped arrays as data carriers across layers; `array` return types where a DTO or Collection fits; `mixed`
- Committing `.env`, `vendor/`, `storage/*.key`, or `public/build` without a reason
