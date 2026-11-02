---
tag: pyside6
keywords: pyside6, qt, qt6, desktop, window, widgets, signals, slots, qthread, pytest-qt, qtbot, pyinstaller, gatekeeper, smartscreen, smart app control
---

# Guidelines: PySide6 desktop app (Windows and macOS)

## Style

- Qt Widgets (`QMainWindow`, `QWidget`, layouts) by default; QML only when the spec asks for animated, touch-style screens
- Imports from the submodule: `from PySide6.QtWidgets import QMainWindow, QPushButton`, `from PySide6.QtCore import Qt, Signal, Slot`; never `from PySide6.QtWidgets import *`
- Snake-case methods in your own classes; Qt method names stay camelCase (`setText`, `clicked`) — do not enable `__feature__` snake_case
- Widgets build their UI in code with layouts (`QVBoxLayout`, `QFormLayout`); no absolute positions or fixed window sizes; `.ui` files from Designer only when the project already uses them
- Custom signals as class attributes with types: `saved = Signal(str)`; connect with `button.clicked.connect(self._on_save)`, never string-based `SIGNAL()`
- Widgets are thin: they read input, call a model/service and render the result; logic lives in plain Python classes with no Qt imports, so it is testable without a window
- Every widget the tests or screen readers need has `setObjectName("saveButton")`; icon-only buttons also `setAccessibleName`
- Colours from the palette (`self.palette().color(QPalette.ColorRole.Text)`) or the style; no literal hex colours or pixel font sizes

## Project structure

- `src/<app>/`: `__main__.py` (`main()`), `app.py` (creates `QApplication`), `ui/` (windows, widgets, dialogs), `core/` (Qt-free logic and storage), `assets/` (icons, images)
- A root `run.py` that only calls `from <app>.__main__ import main; main()` — the PyInstaller entry script (relative imports break when a package module is the entry)
- `main()`: `QApplication(sys.argv)`, `setApplicationName`, `setOrganizationName`, `setWindowIcon`, show the main window, `sys.exit(app.exec())`; exactly one `QApplication` per process
- Data location: `QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)` after the names are set (`%APPDATA%\<org>\<app>` on Windows, `~/Library/Application Support/<app>` on macOS); create it with `Path.mkdir(parents=True, exist_ok=True)`
- Settings as JSON in that folder (or `QSettings` with `QSettings.Format.IniFormat` — the default format writes to the Windows registry); never next to the executable or inside the `.app`
- Writes are atomic: write `file.tmp`, then `Path.replace` — a crash mid-write must not destroy the person's data
- Assets located from the package: `Path(__file__).resolve().parent / "assets"`; works unchanged inside a PyInstaller build when the spec file bundles the folder under the same package path
- Global handler: `sys.excepthook` logs the traceback to the data folder and shows one plain-language `QMessageBox`; an exception in a slot must not silently kill the window

## Tests

- `pytest-qt` with `qt_api = "pyside6"` under `[tool.pytest.ini_options]`; logic in `core/` is tested with plain pytest, no Qt
- Widgets: `window = MainWindow(...)`, `qtbot.addWidget(window)`, `qtbot.keyClicks(window.name_edit, "Ann")`, `qtbot.mouseClick(window.save_button, Qt.MouseButton.LeftButton)`, then assert visible state
- `qtbot.keyClicks` / `QTest.keyClicks` take plain ASCII only: a letter like `ł` or `ś` makes Qt call `abort()` and the whole test process dies (on macOS with a crash window). Text with such letters goes in with `edit.setText(...)` or `edit.insert(...)`, then `edit.editingFinished.emit()` / `edit.returnPressed.emit()` when the code listens for them
- Async results: `with qtbot.waitSignal(worker.signals.finished, timeout=5000):` or `qtbot.waitUntil(lambda: ...)`; never `time.sleep`
- Modal dialogs are replaced in tests (`monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)`) — a real modal blocks the run
- macOS: the environment runs on uv's own Python (`[tool.uv]` → `python-preference = "only-managed"` in `pyproject.toml`, then `uv sync`), not python.org's: that one runs as `Python.app`, so every crashed test process puts a "Python quit unexpectedly" window in front of the person
- Headless everywhere: `QT_QPA_PLATFORM=offscreen` in CI and in the test command (set it in `conftest.py` with `os.environ.setdefault` before Qt is imported)
- Each test gets its own data folder: `QStandardPaths.setTestModeEnabled(True)` or the path injected from `tmp_path`
- The flows from `APP_FLOW.md` are tested through the main window, not only through `core/`

## Threads and responsiveness

- Never block the GUI thread: file scans, network, heavy computation go to `QThreadPool.globalInstance().start(runnable)` or a worker `QObject` moved with `moveToThread`
- Workers talk back only through signals (queued across threads); never touch a widget from a worker thread
- A worker holds no reference to widgets; it gets plain data in and emits plain data out
- Long tasks show progress (`QProgressBar` / `QProgressDialog`) and offer cancel via a flag the worker checks
- `QTimer.singleShot(0, ...)` to defer work until the event loop runs; no `processEvents()` loops

## Look, DPI and packaging

- High DPI is automatic in Qt 6 — do not set the old `AA_EnableHighDpiScaling` attributes; use SVG icons or `@2x` images
- Dark mode follows the system: read `QGuiApplication.styleHints().colorScheme()` and react to `colorSchemeChanged`; custom drawing uses palette roles so both schemes work
- Packaging with a committed `<app>.spec` (PyInstaller): `windowed` (no console), `datas` for `assets/`, `icon` = `assets/app.ico` on Windows, `assets/app.icns` on macOS, app version in `BUNDLE(..., info_plist={"CFBundleShortVersionString": ...})`
- No cross-compiling: the Windows `.exe` is built on Windows, the macOS `.app` on macOS — or both in CI with a `windows-*` and a `macos-*` runner
- `--onedir` (a folder, fast start, fewer antivirus false positives) is the default; `--onefile` only on Windows when one file is required — it unpacks on every start and is flagged by antivirus more often; on macOS always a `.app` (onedir)
- Unsigned builds that were downloaded warn on first open: Windows SmartScreen → "More info" → "Run anyway"; macOS 15+ → open once, then System Settings → Privacy & Security → "Open Anyway" (right-click → Open no longer bypasses it); a build made on the same computer opens without a warning
- Windows 11 with **Smart App Control** on: the tests pass (they run in the signed `python.exe`), but the PyInstaller exe is unsigned and is refused even on the PC that built it ("An Application Control policy has blocked this file"), with no "run anyway". Do not retry or work around it: say so in plain words before packaging — turning Smart App Control off lets it run, and on many Windows versions it cannot be turned back on without reinstalling Windows — and let the person choose; the program can still be started from its folder with `uv run` in the meantime
- PySide6 is LGPL: fine to bundle as PyInstaller does (Qt stays separate libraries); ship the Qt/PySide6 license notice with the app and do not modify Qt itself

## What to avoid

- Blocking calls (`requests.get`, `time.sleep`, large file reads) in slots
- `PyQt6` imports mixed with PySide6; Qt modules the app does not use bundled (exclude `QtWebEngine` unless needed — it adds hundreds of MB)
- Subclassing `QThread` and overriding `run` for ordinary jobs — use `QThreadPool` or a worker object
- Global widget references and module-level `QApplication` creation (breaks tests)
- Paths relative to the current working directory — a double-clicked app starts with an arbitrary one
- Storing data with `sys.executable` or `sys._MEIPASS` as the base folder
