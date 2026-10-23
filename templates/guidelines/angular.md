---
tag: angular
keywords: angular, standalone component, signals, rxjs, observable, httpclient, interceptor, router, reactive forms, ngrx, angular cli, spec.ts, jest, testing library
---

# Guidelines: Angular

## Style

- Standalone components, directives and pipes only — no `NgModule` in application code; bootstrap with `bootstrapApplication(AppComponent, { providers: [provideRouter(routes), provideHttpClient(...)] })`
- `changeDetection: ChangeDetectionStrategy.OnPush` on every component
- Signals for component state: `count = signal(0)`, `total = computed(() => ...)`; `effect()` only for side effects (logging, sync to storage), never to derive state
- Signal inputs/outputs: `name = input.required<string>()`, `saved = output<User>()`, `model()` for two-way binding; no `@Input()` / `@Output()` decorators in new code
- New control flow in templates: `@if`, `@for (item of items(); track item.id)`, `@switch`, `@defer` — not `*ngIf` / `*ngFor`; `track` is mandatory and must be a stable id, not `$index`
- `private readonly http = inject(HttpClient)` in field initialisers instead of constructor parameters
- `host: { '(click)': 'onClick()', '[class.active]': 'active()' }` in the decorator instead of `@HostBinding` / `@HostListener`
- `@Injectable({ providedIn: 'root' })` for singletons; component-level `providers` only for per-instance state
- Run `ng lint` (angular-eslint) and Prettier; do not argue with them

## Project structure

- `src/app/core/` (singleton services, interceptors, guards), `src/app/shared/` (presentational components, pipes, validators), `src/app/features/<name>/` (routed feature: components, services, models, `<name>.routes.ts`)
- One component per directory: `user-list.component.ts|html|css|spec.ts`; selector prefix from `angular.json` (`app-user-list`); generate with `ng generate component features/users/user-list` to get the standard layout and spec
- Feature routes lazy-loaded: `{ path: 'users', loadChildren: () => import('./features/users/users.routes').then(m => m.USERS_ROUTES) }`
- Smart (routed) component talks to services and owns state; presentational component has only `input()` / `output()`
- Route params bound to inputs with `withComponentInputBinding()`: `id = input.required<string>()` instead of reading `ActivatedRoute`
- Environment values in `src/environments/environment*.ts` via `fileReplacements`; no secrets — the bundle is public

## Tests

- Jest with `jest-preset-angular` (or Vitest through `@analogjs/vite-plugin-angular`) + Angular Testing Library; one runner per project, no Karma
- Spec beside the unit: `user-list.component.spec.ts`; run one with `npx jest src/app/features/users/user-list.component.spec.ts -t "shows empty state"`
- Components: `await render(UserListComponent, { inputs: { users: [...] }, providers: [...] })`, query with `screen.getByRole`, interact with `userEvent`; never read private fields or call lifecycle hooks by hand
- HTTP: `provideHttpClient()` + `provideHttpClientTesting()`, `httpMock.expectOne('/api/users').flush(body)`, `httpMock.verify()` in `afterEach`; never a real server
- Services: `TestBed.inject(UsersService)`, assert with `await firstValueFrom(service.load())`; time-dependent streams with `TestScheduler` marbles or `fakeAsync` + `tick()`
- Routing: `provideRouter(routes)` + `RouterTestingHarness.create('/users/1')` to assert the rendered component; functional guards tested with `TestBed.runInInjectionContext(() => authGuard(route, state))`
- Failure modes to cover: HTTP error renders the error state, empty list state, invalid form blocks submit, interceptor adds the header and handles 401
- Mock only HTTP, time and browser APIs; do not mock the component's own services when a fake HTTP response is enough

## RxJS

- Signals for state; Observables for events, HTTP and time (`debounceTime`, `switchMap`)
- In templates `| async` or convert once with `toSignal(obs$, { initialValue: [] })`; a manual `subscribe()` in a component only with `takeUntilDestroyed()` in the pipe
- Compose with `pipe(map, filter, switchMap)`; one `subscribe` at the end of the chain, never a `subscribe` inside a `subscribe`
- Flattening operator by intent: `switchMap` for search/latest-wins, `concatMap` for ordered writes, `exhaustMap` for submit buttons, `mergeMap` only when order and cancellation do not matter
- `catchError` inside the inner stream — `switchMap(id => this.api.get(id).pipe(catchError(() => of(null))))` — so one failed request does not complete the outer stream
- Share expensive streams with `shareReplay({ bufferSize: 1, refCount: true })`

## HTTP and forms

- `provideHttpClient(withInterceptors([authInterceptor, errorInterceptor]))`; functional interceptors `const authInterceptor: HttpInterceptorFn = (req, next) => next(req.clone({ setHeaders: { Authorization: ... } }))`
- Typed calls `this.http.get<User[]>('/api/users')`; one service per API resource; components never inject `HttpClient` directly
- Reactive, typed forms: `inject(NonNullableFormBuilder).group({ email: ['', [Validators.required, Validators.email]] })`; custom validators as pure functions in `shared/validators/`
- Show field errors only after `touched` or submit; disable the submit button while a request is in flight (`exhaustMap`)
- Guards and resolvers as functions: `export const authGuard: CanActivateFn = () => inject(AuthService).isLoggedIn() || inject(Router).createUrlTree(['/login'])`
- Auth token in memory or an `HttpOnly` cookie, never `localStorage`; `bypassSecurityTrustHtml` never on user-provided content

## What to avoid

- Method calls with work in templates (`{{ computeTotal(items) }}` runs on every change detection) — use a `computed` signal; calling a signal `{{ total() }}` is fine
- Logic in templates beyond a simple condition — move it to `computed` or the class
- `subscribe()` without `takeUntilDestroyed`; `subscribe` in `ngOnInit` to copy a value into a field that could be `toSignal`
- `ngOnChanges` to derive values — `computed` over signal inputs
- Mutable service state as plain fields — expose `signal` with `.asReadonly()` and update methods
- Template-driven forms (`ngModel`) for anything beyond a single toggle
- `@ViewChild` to reach into a child's internals — inputs/outputs
- Importing `CommonModule` wholesale — import `DatePipe`, `NgClass` individually or use control flow
- `any` on HTTP responses; `as` casts on route params
