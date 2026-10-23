---
tag: fastapi
keywords: fastapi, pydantic, starlette, uvicorn, async endpoint, apirouter, depends, sqlalchemy, sqlmodel, alembic, oauth2, jwt, httpx, openapi
---

# Guidelines: FastAPI

## Style

- Pydantic v2 only: `model_config = ConfigDict(from_attributes=True)`, `Model.model_validate(obj)`, `.model_dump()` — never v1 `class Config`, `.dict()`, `.parse_obj()`, `@validator` (use `@field_validator`)
- Separate schemas per direction: `UserCreate`, `UserUpdate` (all fields optional), `UserRead` (with `id`); the ORM model is never a request or response type
- The return annotation is the response model: `async def get_user(user_id: int) -> UserRead:`; `response_model=` only when it must differ from the annotation
- `Annotated` for parameters and dependencies, declared once and reused: `DbDep = Annotated[AsyncSession, Depends(get_db)]`, `CurrentUser = Annotated[User, Depends(get_current_user)]`, `user_id: Annotated[int, Path(gt=0)]`
- Explicit `status_code=status.HTTP_201_CREATED` on create, `HTTP_204_NO_CONTENT` with `-> None` on delete
- Endpoints are thin: parse → call a service function → return a schema; services take plain arguments and the session, never `Request`
- `ruff format`, `ruff check`, `mypy --strict` on `src/`; run them, do not argue with them

## Project structure

- `src/<app>/main.py` (`create_app()` + `lifespan`), `api/v1/<resource>.py` (one `APIRouter(prefix="/users", tags=["users"])` per resource), `api/deps.py`, `schemas/`, `models/`, `services/`, `repositories/`, `core/config.py`, `core/security.py`, `db/session.py`, `alembic/`
- Routers included in one place: `app.include_router(users.router, prefix="/api/v1")`; routers never import each other
- Startup/shutdown in `@asynccontextmanager async def lifespan(app: FastAPI)` (engine, HTTP clients, caches) — never `@app.on_event`
- Settings via `pydantic-settings`: `class Settings(BaseSettings): model_config = SettingsConfigDict(env_file=".env", extra="ignore")` + `@lru_cache def get_settings() -> Settings`; no `os.environ` reads outside `core/config.py`
- `SECRET_KEY`, `DATABASE_URL` only from the environment; `.env` ignored by git, `.env.example` committed with placeholders

## Tests

- pytest + `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml`) + `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`; the sync `TestClient` only for apps without an async database
- `tests/conftest.py` fixtures: `app`, `client`, `db_session` (one transaction per test, rolled back), `auth_headers`; `app.dependency_overrides[get_db] = lambda: session`, cleared in teardown
- Real database in tests (Postgres through Testcontainers, or SQLite only when no Postgres-specific SQL exists); never mock the session or the repository in an endpoint test
- Mock only outbound HTTP (`respx`) and time; a mocked service behind an endpoint proves nothing about wiring or serialisation
- One test module per router: `tests/api/test_users.py`; run one with `pytest tests/api/test_users.py::test_create_user_duplicate_email_returns_409 -x`
- Cover per resource: 422 on an invalid body (assert the field name in `detail[0]["loc"]`), 401 without a token, 403 wrong role, 404 missing id, 409 duplicate, pagination `limit` above the max rejected
- `client.get("/openapi.json")` returns 200 in a test — catches duplicate `operation_id`s and unserialisable models

## Async and the database

- `async def` only with async libraries (`asyncpg`, `httpx`, `redis.asyncio`); a blocking call (`requests`, `time.sleep`, a sync driver) inside `async def` stalls the whole event loop — declare the endpoint `def` (FastAPI runs it in a threadpool) or `await run_in_threadpool(fn)`
- SQLAlchemy 2.0 style: `class User(Base): id: Mapped[int] = mapped_column(primary_key=True)`, `await session.scalars(select(User).where(User.email == email))`; never legacy `session.query()`
- One session per request from `async_sessionmaker(engine, expire_on_commit=False)` in `get_db` with `async with`; `commit()` in the service, never in the repository
- Eager-load what you serialise: `select(User).options(selectinload(User.posts))` — lazy loading in async raises `MissingGreenlet`
- Alembic for every schema change: `alembic revision --autogenerate -m "add users"`, review the generated file; `Base.metadata.create_all()` only in tests; migrations run as a deploy step, not in `lifespan`
- `BackgroundTasks` for fire-and-forget after the response; a worker (arq, Celery) for anything retried or longer than a few seconds

## Auth and errors

- `OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")`; `get_current_user` decodes the JWT with an explicit `algorithms=["HS256"]`, requires `exp` and `sub`, and raises 401 with `headers={"WWW-Authenticate": "Bearer"}`
- Passwords hashed with argon2 or bcrypt (`pwdlib`/`passlib`); never logged, never in any schema's output; short-lived access tokens
- Role checks as a dependency factory: `def require_role(role: Role): def dep(user: CurrentUser) -> User: ...; return dep`, used as `Depends(require_role(Role.admin))`
- Domain exceptions (`UserNotFoundError`) raised in services and mapped once with `@app.exception_handler(UserNotFoundError)` to `{"detail": ...}`; no `HTTPException` inside services
- `CORSMiddleware` with `allow_origins=settings.cors_origins` (an explicit list); never `["*"]` together with `allow_credentials=True`
- Bound inputs: `limit: Annotated[int, Query(ge=1, le=100)] = 20`, `Field(max_length=...)` on strings; uploads checked by content type and size before reading

## OpenAPI hygiene

- `tags` on every router, `summary` on every endpoint; `description` only when the name is not enough
- `Field(examples=[...])` on request schemas; `responses={404: {"model": ErrorResponse}}` for documented error cases
- `docs_url=None, redoc_url=None` in production unless the docs are behind auth
- `generate_unique_id_function=lambda route: f"{route.tags[0]}-{route.name}"` when clients are generated from the schema

## What to avoid

- ORM models or `dict` as request/response types
- Module-level `Settings()`, engines or HTTP clients — create them in `lifespan` or cached dependencies
- A sync SQLAlchemy session or a sync HTTP client inside `async def`
- `except Exception` in an endpoint to return a 500 — the framework already does it, and the handler hides the traceback from logs
- JWT without `exp`; `SECRET_KEY` with a default value; `allow_origins=["*"]` with credentials
- Business logic in routers; routers importing routers
- `print` for diagnostics — `logging.getLogger(__name__)`
