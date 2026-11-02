---
tag: wpf
keywords: wpf, xaml, mvvm, communitytoolkit.mvvm, desktop, windows, data binding, dispatcher, flaui, ui automation, single-file, self-contained, exe, smartscreen, smart app control
---

# Guidelines: WPF desktop app (Windows)

## Style

- MVVM with `CommunityToolkit.Mvvm` source generators: `public partial class MainViewModel : ObservableObject`, `[ObservableProperty] public partial string Title { get; set; }` (partial properties, C# 14 / .NET 10 — no hand-written `OnPropertyChanged`)
- Commands with `[RelayCommand]` on a method (`private async Task SaveAsync(CancellationToken token)` → `SaveCommand`, an `AsyncRelayCommand` that is disabled while running); `CanExecute = nameof(CanSave)` + `[NotifyCanExecuteChangedFor(nameof(SaveCommand))]` on the properties it reads
- Code-behind (`*.xaml.cs`) holds only `InitializeComponent()` and pure view concerns (focus, scrolling, animation); no business logic, no file or database access
- ViewModels never reference `System.Windows` types (`MessageBox`, `Window`, `Brush`, `Visibility`) — dialogs and navigation go through a small interface (`IDialogService`) implemented in the WPF project
- Every interactive control has `AutomationProperties.AutomationId`; icon-only buttons also `AutomationProperties.Name` (screen readers and FlaUI both need them)
- Styles and colours in `App.xaml` resource dictionaries referenced with `{DynamicResource ...}` / `SystemColors`; no literal colours, font sizes or fixed pixel widths in views
- Text the person reads lives in one place (`Resources/Strings.resx` or the ViewModel), not scattered through XAML

## Project structure

- `src/App/` (WPF, `net10.0-windows`, `<UseWPF>true</UseWPF>`, `<OutputType>WinExe</OutputType>`): `App.xaml`, `Views/`, `Services/` (WPF-side implementations), `Assets/app.ico`
- `src/App.Core/` (plain `net10.0` class library): `ViewModels/`, `Models/`, `Services/` interfaces and file/data logic — no WPF reference, so its tests run on any OS, including a Mac
- `tests/App.Core.Tests/` (xUnit, `net10.0`) and `tests/App.UiTests/` (FlaUI, `net10.0-windows`)
- Composition in `App.OnStartup`: build a `ServiceCollection`, resolve `MainWindow` with its ViewModel as `DataContext`; remove `StartupUri` from `App.xaml`
- Global error handlers in `App`: `DispatcherUnhandledException`, `TaskScheduler.UnobservedTaskException`, `AppDomain.CurrentDomain.UnhandledException` — log to a file, show one plain-language message, never a stack trace
- Settings in `%APPDATA%\<App>\settings.json` (`Environment.SpecialFolder.ApplicationData`); data, logs and caches in `%LOCALAPPDATA%\<App>\` (`LocalApplicationData`); never next to the `.exe`, in `Program Files` or on the Desktop
- Files the person chooses go through `Microsoft.Win32.OpenFileDialog` / `SaveFileDialog` / `OpenFolderDialog`; remember the last folder in settings
- Writes are atomic: write `file.tmp`, then `File.Move(tmp, path, overwrite: true)` — a crash mid-write must not destroy the person's data
- `AppContext.BaseDirectory` for the exe folder; `Assembly.Location` is empty in a single-file app

## Tests

- ViewModels tested directly in `App.Core.Tests`: construct with fakes, set properties, `await vm.SaveCommand.ExecuteAsync(null)`, assert state and `PropertyChanged` events — no window, no UI thread
- Check `CanExecute` transitions (`vm.SaveCommand.CanExecute(null)` before and after input) and that a failing service shows an error state instead of throwing
- FlaUI (`FlaUI.UIA3`) only for the few end-to-end flows from `APP_FLOW.md`: `Application.Launch(exePath)`, `new UIA3Automation()`, `app.GetMainWindow(automation)`, `FindFirstDescendant(cf => cf.ByAutomationId("SaveButton")).AsButton().Invoke()`
- Wait with `Retry.WhileNull(...)` / `Retry.WhileFalse(...)` and a timeout, never `Thread.Sleep`; close the app in `Dispose` (`app.Close()`, then `Kill` on timeout)
- UI tests need a real, unlocked, interactive Windows desktop session (a logged-in user or a `windows-*` CI runner); they do not run on a Mac, in a service account or over a minimised RDP window
- UI tests run serially (`[assembly: CollectionBehavior(DisableTestParallelization = true)]`), carry `[Trait("Category", "UI")]`, and the fast suite excludes them: `dotnet test --filter "Category!=UI"`
- Each UI test starts with an empty data folder: pass a temp directory through an environment variable or command-line argument the app honours
- In Debug builds a binding error throws (a `TraceListener` on `PresentationTraceSources.DataBindingSource` with `SourceLevels.Error`) so FlaUI runs surface broken bindings

## Binding and threading

- `{Binding Name}` paths match ViewModel properties exactly; `d:DataContext="{d:DesignInstance vm:MainViewModel}"` in every view so the designer and IntelliSense check paths
- `UpdateSourceTrigger=PropertyChanged` for text boxes that drive validation or `CanExecute`; `INotifyDataErrorInfo` (`ObservableValidator`) for field errors shown next to the field
- Lists bound to `ObservableCollection<T>`, modified only on the UI thread; replace the whole collection for large reloads instead of thousands of `Add` calls
- Value converters only for pure view mapping (`bool` → `Visibility`); a converter with logic belongs in the ViewModel
- ViewModel code awaits without `ConfigureAwait(false)` so it continues on the UI thread; CPU-heavy work goes into `await Task.Run(...)` (correct here, unlike in ASP.NET Core)
- Background code reaches the UI with `Dispatcher.InvokeAsync`, never `Dispatcher.Invoke` (deadlocks) or a cross-thread property write
- Long operations show progress (`IProgress<T>`) and offer cancel via the command's `CancellationToken`

## Look, DPI and packaging

- Fluent theme (Windows 11 look, light/dark following the system): `ThemeMode="System"` on `Application` in `App.xaml`; it is experimental (`WPF0001`) — add `<NoWarn>$(NoWarn);WPF0001</NoWarn>` deliberately, since warnings are errors
- `app.manifest` with `<dpiAwareness>PerMonitorV2</dpiAwareness>`; vector icons or multi-size `.ico`; test at 150 % scaling and with a high-contrast theme on
- csproj holds `<Version>1.0.0</Version>`, `<Product>`, `<Company>`, `<ApplicationIcon>Assets\app.ico</ApplicationIcon>` (16/32/48/256 px); the window uses the same icon
- Publish settings in the csproj: `<RuntimeIdentifier>win-x64</RuntimeIdentifier>`, `<SelfContained>true</SelfContained>`, `<PublishSingleFile>true</PublishSingleFile>`, `<IncludeNativeLibrariesForSelfExtract>true</IncludeNativeLibrariesForSelfExtract>` (without it WPF's native DLLs land next to the exe), `<PublishReadyToRun>true</PublishReadyToRun>` (faster start)
- Build with `dotnet publish src/App -c Release`; the result is one `.exe` in `bin/Release/net10.0-windows/win-x64/publish/`, tens of MB — expected for a self-contained app
- WPF builds, runs and tests only on Windows; `<EnableWindowsTargeting>true</EnableWindowsTargeting>` lets a Mac compile it but not start or test it — never ship an exe nobody started on Windows
- An unsigned exe that was downloaded or received by mail/chat shows SmartScreen "Windows protected your PC": tell the person to click "More info" → "Run anyway" (or Properties → Unblock); a file built on the same PC shows nothing
- **Smart App Control** (Windows 11, Windows Security → App & browser control) is not SmartScreen: when it is on it refuses every unsigned exe and DLL, the one just built on this PC included — the app, and `dotnet test` too (the test host loads the project's own DLLs). The error says "An Application Control policy has blocked this file" (0x800711C7) or a toast names Smart App Control. It has no "run anyway", there is no per-file exception and nothing in the project works around it — so never retry, rename, move the output or try another build path. Stop with `TELESMA BLOCKED` and tell the person, in plain words: turning it off (Windows Security → App & browser control → Smart App Control settings → Off) lets the build run, and on many Windows versions it cannot be turned back on without reinstalling Windows; the other ways are another computer or a stack that runs in a signed interpreter. The launcher checks this before a build session; a person who decides to keep it on keeps it on
- Code signing (Azure Artifact Signing, formerly Trusted Signing, or a certificate) is optional and paid; never block a release on it

## What to avoid

- Logic in code-behind, `x:Name` lookups from ViewModels, ViewModels creating windows
- `PublishTrimmed` and Native AOT — WPF does not support them
- `async void` outside event handlers; `.Result` on the UI thread (freezes the window)
- Writing to the exe folder or `Program Files`; registry for app settings
- Hand-rolled `INotifyPropertyChanged`/`ICommand` boilerplate when the toolkit generates it
- `Thread.Sleep` in tests, UI tests that depend on screen coordinates or window position
- Third-party control suites and MVVM frameworks (Prism, Caliburn) for a small app
- WinForms interop and `System.Drawing` in WPF views
