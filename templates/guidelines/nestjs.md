---
tag: nestjs
keywords: nestjs, nest, module, provider, controller, injectable, dto, class-validator, pipe, guard, interceptor, typeorm, prisma, decorator, backend
---

# Guidelines: NestJS

## Style

- Nest CLI generates the files (`nest g module orders`, `nest g service orders`, `nest g controller orders`); keep its naming: `orders.module.ts`, `orders.service.ts`, `orders.controller.ts`, `dto/create-order.dto.ts`, `entities/order.entity.ts`
- Classes `PascalCase` with the role suffix (`OrdersService`, `JwtAuthGuard`, `CreateOrderDto`); one class per file
- Constructor injection with `private readonly` parameters; no `new` for anything that has dependencies
- ESLint + Prettier from the Nest starter — run them; do not argue with them
- Logging through the Nest `Logger` with a context (`private readonly logger = new Logger(OrdersService.name)`), not `console.log`
- `@nestjs/swagger` decorators on DTOs and controllers when the API is consumed by others; the OpenAPI document is generated, never hand-written

## Project structure

- `src/<domain>/` per feature module: `*.module.ts`, `*.controller.ts`, `*.service.ts`, `dto/`, `entities/`, `*.spec.ts` beside each file
- `src/app.module.ts` only imports feature modules and global infrastructure (`ConfigModule`, database module); no providers of its own
- `src/common/` for cross-cutting guards, interceptors, filters, pipes, decorators; `src/config/` for the environment schema
- A module exports only what other modules need (`exports: [OrdersService]`); consumers import the module, never a provider class from another module's folder
- Controllers: route + DTO + guard → one service call → return a response DTO; services hold the logic; repositories (`Repository<T>` or `PrismaService`) are injected into services only
- `ConfigModule.forRoot({ isGlobal: true, validate })` with a zod or class-validator schema; typed access through `ConfigService<EnvSchema, true>`; no `process.env` outside `src/config/`
- `main.ts` applies the global setup through a shared `configureApp(app)` helper (reused by e2e tests): `ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })`, global exception filter, helmet, CORS with an explicit origin list, `enableShutdownHooks()`

## Tests

- Jest (the Nest default) with `*.spec.ts` beside the code and `test/*.e2e-spec.ts`; run one: `pnpm jest src/orders/orders.service.spec.ts`; e2e: `pnpm jest --config test/jest-e2e.json`
- Unit tests build the provider with `Test.createTestingModule({ providers: [OrdersService, { provide: getRepositoryToken(Order), useValue: repoMock }] })` — mock repositories and other modules' services, never the class under test
- Mocks are typed partials (`jest.Mocked<Pick<Repository<Order>, "findOne" | "save">>`), reset in `beforeEach`
- e2e: `moduleRef.createNestApplication()`, `configureApp(app)`, `await app.init()`, requests with `supertest(app.getHttpServer())`, `await app.close()` in `afterAll`
- e2e against a real database (container) with migrations applied; replace only external HTTP clients with `overrideProvider(X).useValue(...)`
- Every endpoint: valid body, unknown field (400 from `forbidNonWhitelisted`), missing auth (401), wrong role (403), foreign resource (404)
- Guards, pipes and interceptors get unit tests with a built `ExecutionContext` (`createMock<ExecutionContext>()` from `@golevelup/ts-jest`)
- Config in tests through `ConfigModule.forRoot({ load: [() => testConfig], ignoreEnvFile: true })`, not by mutating `process.env`

## DTOs, pipes, guards, interceptors

- One DTO class per request shape with `class-validator` (`@IsString() @MaxLength(200) title!: string`) and `class-transformer` (`@Type(() => Date)`, `@ValidateNested()`) for nested or converted values; `PartialType(CreateOrderDto)` for updates
- Response DTOs are separate from entities; never return a TypeORM entity or Prisma model directly (it leaks `passwordHash` and friends); `ClassSerializerInterceptor` + `@Exclude()` is a safety net, not the design
- `ParseUUIDPipe` / `ParseIntPipe` on path params: `@Param("id", ParseUUIDPipe) id: string`
- Guards decide access (`@UseGuards(JwtAuthGuard, RolesGuard)` with a `@Roles()` decorator read via `Reflector`), interceptors shape input/output and timing, filters map errors to responses; business logic in none of the three
- Services throw `NotFoundException`, `ForbiddenException`, `ConflictException`; a global `HttpExceptionFilter` formats them and turns unknown errors into a 500 without the message
- `Scope.REQUEST` providers only when nothing else works — they rebuild the whole dependency chain per request and make every consumer request-scoped

## Database

- TypeORM: `synchronize: false` everywhere except throwaway tests; migrations generated (`typeorm migration:generate`) and committed; the `DataSource` built from `ConfigService`
- TypeORM: QueryBuilder with parameters (`.where("o.status = :status", { status })`) — never template strings; `relations` / `leftJoinAndSelect` instead of lazy relations
- Prisma: `PrismaService extends PrismaClient` with `onModuleInit` connecting; `prisma migrate dev` locally, `prisma migrate deploy` in CI/production; `$queryRaw` only as a tagged template
- Transactions wrap multi-step writes (`dataSource.transaction(async (manager) => ...)` / `prisma.$transaction`); a service receives the manager or transaction client, it does not open nested transactions

## What to avoid

- `new SomeService()` inside another provider; importing a provider class from another module instead of the module
- Circular module imports patched with `forwardRef` — extract a shared module instead
- Logic in controllers; `@Res()` injected when a return value would do (it disables interceptors and serialisation)
- `ValidationPipe` without `whitelist` — unknown fields flow straight into `repository.save(dto)`
- DTOs declared as `interface` (decorators need classes), `any` in DTOs, entities used as request bodies
- Catching exceptions in controllers to re-wrap them; swallowing errors in interceptors
- `synchronize: true` or `prisma db push` against a shared database
- A second DI container or module-level singletons next to Nest's container
