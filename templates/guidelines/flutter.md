---
tag: flutter
keywords: flutter, dart, widget, stateless, stateful, riverpod, bloc, go_router, pubspec, build_runner, freezed, widget test, integration_test, platform channel
---

# Guidelines: Flutter

## Style

- `const` constructors and `const` widget instances wherever possible; `prefer_const_constructors` is on
- Extract widgets, not methods: `class _OrderRow extends StatelessWidget`, never `Widget _buildOrderRow()` — a method rebuilds with the parent and cannot be `const`
- `StatelessWidget` by default; `StatefulWidget` only for ephemeral UI state (animation and text controllers, scroll position, focus); application state lives in Riverpod providers
- Immutable models with `freezed` (`@freezed class Order with _$Order { const factory Order({required String id}) = _Order; factory Order.fromJson(...) = _$OrderFromJson; }`) + `json_serializable`; no hand-written `copyWith` / `==`
- No `!` on nullable values — `if (order case Order(:final id))`, `?.`, `??`, or an early return
- Theme values only: `Theme.of(context).colorScheme.primary`, `textTheme.bodyMedium`; no literal `Color(0xFF...)` or font sizes in widgets
- `dart format .` and `dart analyze` with `flutter_lints` (or `very_good_analysis`) in `analysis_options.yaml`; run them, do not argue with them; `dart fix --apply` for autofixable lints

## Project structure

- `lib/main.dart` (`ProviderScope` + `runApp`), `lib/app/` (`app.dart` with `MaterialApp.router`, `router.dart`, `theme.dart`), `lib/features/<name>/` with `presentation/` (screens, widgets), `application/` (providers, controllers), `domain/` (models), `data/` (repositories, DTOs), `lib/core/` (networking, storage, shared widgets, extensions)
- Absolute imports `package:my_app/features/...`; never `../../`
- Environments through `--dart-define-from-file=env/dev.json` read with `const String.fromEnvironment('API_URL')`; no secrets in Dart or assets — the binary is public
- Assets declared in `pubspec.yaml` and referenced through generated constants (`flutter_gen`), not string paths
- Generated files (`*.g.dart`, `*.freezed.dart`) committed; `dart run build_runner build --delete-conflicting-outputs` after model or provider changes

## Tests

- `flutter_test` under `test/` mirroring `lib/` (`test/features/orders/orders_controller_test.dart`); `integration_test/` with `IntegrationTestWidgetsFlutterBinding.ensureInitialized()` for on-device flows
- Run one file: `flutter test test/features/orders/orders_controller_test.dart`; one test: `flutter test --plain-name "shows error when load fails"`
- Providers: `final container = ProviderContainer(overrides: [orderRepositoryProvider.overrideWithValue(FakeOrderRepository())]); addTearDown(container.dispose);` then assert `container.read(ordersProvider)` and `AsyncValue` transitions via `container.listen`
- Widgets: `await tester.pumpWidget(ProviderScope(overrides: [...], child: MaterialApp(home: OrdersScreen())))`, find with `find.text`, `find.byType`, `find.bySemanticsLabel`; `await tester.tap(...)` then `await tester.pump()`; `pumpAndSettle()` after async work
- Fakes over mocks: hand-written `FakeOrderRepository implements OrderRepository`; `mocktail` only to verify calls; never mock widgets or `BuildContext`
- Never hit real network, storage or platform channels: `TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, handler)`, `SharedPreferences.setMockInitialValues({})`
- Golden tests (`await expectLater(find.byType(OrderCard), matchesGoldenFile('order_card.png'))`) for design-critical widgets, goldens generated on one platform in CI
- Cover: error state, empty state, pull-to-refresh, navigation after an action (`GoRouter(initialLocation: ...)` in the test), large text (`MediaQuery(data: ..., textScaler: TextScaler.linear(2))`) and small screens (`tester.view.physicalSize`)

## State and async

- Riverpod with code generation: `@riverpod Future<List<Order>> orders(Ref ref)` for reads, `@riverpod class OrdersController extends _$OrdersController` (an `AsyncNotifier`) for mutations; `ref.watch` in `build`, `ref.read` only in callbacks, `ref.listen` for side effects (snackbars, navigation)
- The UI receives `AsyncValue<T>` and renders with `.when(data:, loading:, error:)`; no `FutureBuilder` / `StreamBuilder` for application data
- Repositories are the only layer that talks to `dio`/`http`, databases or channels; providers depend on repository providers, widgets depend on providers
- `autoDispose` by default (code generation does it), `ref.keepAlive()` deliberately; `ref.onDispose` for subscriptions and controllers
- Bloc (`flutter_bloc`) only when the project already uses it: one `Cubit`/`Bloc` per feature, events as sealed classes, `BlocBuilder` with `buildWhen`; never Bloc and Riverpod in one app
- Platform channels: `MethodChannel('com.example.app/battery')` wrapped in a Dart class with typed methods and `PlatformException` mapped to a domain error; the native side registered in `MainActivity` / `AppDelegate`; look for an existing plugin before writing a channel
- After any `await` in a `State`, `if (!context.mounted) return;` before using `context`; `unawaited()` for intentional fire-and-forget

## Navigation

- `go_router`: routes declared once in `router.dart` — `GoRoute(path: '/orders/:id', builder: (context, state) => OrderScreen(id: state.pathParameters['id']!))`; `StatefulShellRoute.indexedStack` for bottom navigation
- `context.go` for top-level switches (replaces the stack), `context.push` for drill-down; `redirect` on the router for auth, reading auth state through `refreshListenable`
- Every screen has a route, so deep links and web URLs work; no `Navigator.push(MaterialPageRoute(...))` in feature code

## What to avoid

- `setState` for application state; a `StatefulWidget` longer than a screen
- Business logic in widgets; `BuildContext` passed into providers or repositories
- `GlobalKey` to reach another widget's state; a hand-written `InheritedWidget`
- `ListView(children: [...])` for long or paginated lists — `ListView.builder` / `.separated`
- `print` in production code — `log()` from `dart:developer`; `dynamic` and `as Map<String, dynamic>` chains on JSON — generated `fromJson`
- `Timer`s and `StreamSubscription`s not cancelled in `dispose`; `context` after an `await` without `mounted`
- `// ignore_for_file:` to silence the analyzer; `MediaQuery.of(context).size` for layout decisions where `LayoutBuilder` belongs
- `Expanded` / `Flexible` outside a `Row` / `Column`; unbounded `Column` inside a scroll view without `shrinkWrap` or `SliverList`
