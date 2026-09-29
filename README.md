# InfluxDB Manager

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.5+-41CD52?logo=qt)](https://doc.qt.io/qtforpython/)
[![InfluxDB](https://img.shields.io/badge/InfluxDB-1.x-22ADF6?logo=influxdb)](https://docs.influxdata.com/influxdb/v1/)
[![httpx](https://img.shields.io/badge/httpx-0.24+-370617?logo=python)](https://www.python-httpx.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D6?logo=windows)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

A desktop UI management tool for InfluxDB (1.x time series database) — inspired by the original [CymaticLabs/InfluxDBStudio](https://github.com/CymaticLabs/InfluxDBStudio) (C#/WinForms), **rebuilt from scratch in Python/PySide6** and extended with a host of new features: DBeaver-style result grid editing, pagination, row deletion, persisted query scripts, and a bilingual UI (**Chinese by default**, English available).

**Author**: Yuyang.Wang | **Repository**: [IYeaSakura/InfluxDB-Manager](https://github.com/IYeaSakura/InfluxDB-Manager)

[Features](#features) | [Tech Stack](#tech-stack) | [Project Structure](#project-structure) | [Getting Started](#getting-started) | [Usage](#usage) | [Development](#development) | [Build & Deployment](#build--deployment) | [Core Design](#core-design) | [Testing](#testing) | [Troubleshooting](#troubleshooting) | [Contributing](#contributing) | [License](#license)

---

## Features

Core features inherited from the original project's design and reimplemented in Python:

### Connection Management

- Create, edit, delete, and clone InfluxDB connections (host, port, credentials, database, SSL)
- **Read-only connections**: mark a connection read-only to block all edits, row deletions, and point writes (menu items disable automatically)
- **Connection categories (1.3.0)**: tag a connection as Development / Test / Production; the tree colors the connection node accordingly (green / orange / red), DBeaver-style environment marking
- Test / Ping a connection before saving it
- Optional "allow untrusted SSL certificates" setting per application
- Connection tree browser: Connection -> Databases -> Measurements, lazily expanded on demand
- Multiple concurrent connections, each with its own client instance

### Query Window

- Monospace SQL editor with syntax highlighting (keywords, strings, numbers, comments)
- Run with **Ctrl+Enter** (main and numpad Enter both bound); executes on a worker thread so the GUI never freezes, with a running indicator and response-time display
- GROUP BY queries automatically split results into multiple tabs
- **Ctrl+/** toggles line comments on the current or selected lines; commented lines render gray; scripts starting with `--` comment headers still paginate and count correctly
- Query script tabs: rename via right-click tab menu; all open scripts (name, connection, database, content, active tab) are **persisted and automatically restored on the next launch**
- **Query history**: every successful execution is recorded (deduplicated, most-recent first, up to 200 entries, persisted in settings.json); the grid toolbar's history button opens a browsable list — double-click an entry to load it back into the editor, with per-entry and bulk delete
- **Multi-statement execution**: statements separated by `;` run one-by-one on a worker thread, each producing its own result tab (with row counts); a failing statement stops the run with its error highlighted while other results stay
- **SQL autocomplete**: keywords (SELECT/FROM/WHERE/LIMIT…) plus the current database's measurements / tag keys / field keys (5-minute TTL metadata cache, graceful degradation to partial results); auto-popup after 2 characters, Ctrl+Space forces a refresh
- **Query plans**: toolbar buttons send `EXPLAIN` / `EXPLAIN ANALYZE` for a single SELECT and show the plan in a monospace text dialog

### Result Grid (DBeaver-Style)

- **Pagination**: plain SELECTs automatically get `LIMIT/OFFSET` injected; page size selectable from presets (100/500/1000/5000/10000) or typed manually (1-1,000,000); total row count fetched with a read-only `COUNT(*)`; first/prev/next/last navigation
- **Cell editing (overwrite)**: double-click a field cell to edit; InfluxDB has no UPDATE, so saving rewrites the point with the same measurement + tags + timestamp (nanosecond precision preserved); string-typed fields stay strings to avoid field-type conflicts; dirty cells highlighted in yellow
- **Row deletion**: select rows and press **Delete** (or use the context menu) to stage them (red highlight); on save, generates precise `DELETE FROM "m" WHERE time = '...ns RFC3339...' AND "tag" = '...'` statements; reverts cleanly with the rollback action
- **Second-confirmation save**: a confirmation dialog lists every overwrite and every staged row deletion before anything touches the database; successful save reports overwritten/deleted row counts
- **Visible save/revert bar**: always shown above the results, enabled only while changes exist; also available via context menu and Ctrl+S
- **Header context menu**: copy column name / copy all column names, sort the current page ascending or descending (numeric-aware, disabled while dirty), **filter this column** (see below), **server-side time sort** on the `time` column (injects `ORDER BY time DESC` and re-queries; click again to cancel), column width fit-values, hide column / show all columns, refresh, export
- **Column filtering (server-side)**: the filter dialog supports `=` / `!=` / `>` / `>=` / `<` / `<=` / `=~` / `!~`; conditions are injected into the query's WHERE clause and re-executed — active filters show as removable chips above the grid, with a clear-all button; pagination and the `COUNT(*)` total always respect the filters (numeric fields compare unquoted, tags/strings/leading-zero values are quoted, `time` accepts raw expressions like `now() - 1h`); switching query text clears the filters automatically
- **Calc panel**: selecting numeric cells shows count / average / sum / min / max below the grid
- **Body context menu**: copy/paste, save/revert changes, delete selected rows, and **Copy as SQL** (turns selected rows into `SELECT * FROM "m" WHERE time = …` or `DELETE FROM "m" WHERE time = …` statements on the clipboard); the Export Selected Rows entry appears only when rows are selected
- Selection highlight in blue; copy/paste integrates with the system clipboard (TSV)
- **Export results**: six formats — CSV / XLSX / XML / Markdown / JSON / HTML; CSV allows a custom delimiter (default `,`) and is written as UTF-8 with BOM for Excel compatibility
- **Result charting**: the toolbar chart button renders the current query result (numeric columns) as a line chart with time on the X axis and column selection — handy for visualizing monitoring data such as `_internal`
- **Export All**: re-runs the original query without the pagination `LIMIT` on a worker thread and exports the **complete query result** (not just the current page); the GUI stays responsive with a busy cursor
- **Export Selected Rows**: exports only the selected rows, available from the body context menu
- **Export location memory**: the last export directory is remembered across launches
- **Editor font zoom**: Ctrl+= to enlarge, Ctrl+- to shrink, Ctrl+0 to reset

### Database Administration

- Create and drop databases
- Retention policies: list, create, alter, drop, with default-policy fallback logic matching the C# version
- Continuous queries: list, create (with RESAMPLE EVERY/FOR advanced syntax), drop, backfill
- Backfill builder: visually compose a backfill query and run it
- Running queries: `SHOW QUERIES` browser with `KILL QUERY` support (with the C#-compatible "query interrupted" error swallowing)
- **Write data point**: right-click a database or measurement and compose a single point (measurement, tags, fields, time, retention policy) with line-protocol preview and a second confirmation before writing
- **CSV import wizard (1.3.0)**: pick a file (custom delimiter or auto-detect, optional header row), preview the first 50 rows, map each column to time / tag / field (auto-typed) / field (forced string) / ignore — roles are auto-guessed from the column names and numeric content; then import in batches (default 5,000 points per write) on a worker thread with a cancelable progress dialog and a per-line failure report
- **Delete by condition (1.3.0)**: compose `DELETE FROM "m" WHERE time-range AND conditions` with a live statement preview; refuses to run without any time bound or condition (would wipe the whole measurement); double-confirmed before execution
- **SHOW SHARDS / SHOW SUBSCRIPTIONS**: right-click a connection to browse shards and subscriptions (read-only)

### Measurement Exploration

- Series, tag keys, tag values, and field keys browsers per measurement
- Export of exploration results to CSV / JSON

### Users and Privileges

- List users, create users, rename, change passwords, drop users
- Grant / revoke database privileges (ALL, READ, WRITE), edit and revoke existing privileges

### Server Information

- Server diagnostics (`SHOW DIAGNOSTICS`) browser
- Server statistics (`SHOW STATS`) browser with human-readable formatting

### Application Settings

- 12/24-hour time format and date format (month-first or day-first)
- Language switch: **Chinese (default) / English**, applied live
- Settings import / export as JSON, **compatible with the C# version** (PascalCase keys, interchangeable in both directions)
- **Passwords encrypted at rest (1.3.0)**: connection passwords in settings.json are protected with Windows DPAPI (current-user scope, no extra dependencies); in memory they stay plaintext and exported setting files remain plaintext for C# interoperability
- Settings stored per-user via `platformdirs` (no admin rights required)

---

## Tech Stack

### Core Technologies

| Category | Technology | Version |
|----------|------------|---------|
| Language | Python | >= 3.9 |
| GUI Framework | PySide6 (Qt for Python) | >= 6.5 |
| HTTP Client | httpx | >= 0.24 |
| Config Directory | platformdirs | >= 3.0 |
| Test Runner | pytest | >= 7.0 |
| Packaging | PyInstaller | >= 6.0 |

### Design Notes

- **Qt Widgets** (not QML) for a native desktop feel and a faithful port of the WinForms layout
- **QThread + signals/slots** worker pattern for all network I/O; the UI thread never blocks
- **QSyntaxHighlighter** for SQL highlighting; `QPlainTextEdit` as the editor core
- **Pure-stdlib + httpx** InfluxDB HTTP API client (query/write/ping), no InfluxDB Python driver dependency

---

## Project Structure

```
InfluxDBStudio/
├── main.py                                    # Root entry: `python main.py`
├── sakurain.ico                               # Application / taskbar icon
├── pyproject.toml                             # Packaging metadata (setuptools)
├── LICENSE                                    # MIT (CymaticLabs original)
├── README.md                                  # This file (English)
├── README_zh.md                               # Chinese README
├── src/
│   └── net/sakurain/influxdbstudio/           # Unified package: net.sakurain.*
│       ├── __init__.py                        # __version__
│       ├── __main__.py                        # `python -m` entry, app/icon setup
│       ├── app.py                             # Globals: settings, active clients, main window
│       ├── i18n.py                            # zh_CN / en_US translation tables + tr()
│       ├── core/                              # Backend, no Qt dependencies (except async glue)
│       │   ├── client.py                      # InfluxDbClient: HTTP query/write/ping/drop/kill
│       │   ├── models.py                      # Connection/Series/Point/RP/CQ models
│       │   ├── query_tools.py                 # Pagination, COUNT, overwrite points, DELETE builder
│       │   ├── settings.py                    # AppSettings: JSON persistence (C#-compatible)
│       │   ├── async_utils.py                 # run_async worker-thread helper
│       │   └── helper.py                      # Formatting / validation helpers
│       ├── ui/
│       │   ├── main_window.py                 # Main window: menus, toolbar, tree, tabs
│       │   ├── controls.py                    # All data controls (query, grid, RP, CQ, ...)
│       │   ├── dialogs.py                     # Connection manager, about, create DB, backfill
│       │   └── common.py                      # SQL editor + highlighter, icons, error boxes
│       └── resources/
│           ├── sakurain.ico                   # App icon (bundled copy)
│           └── icons/                         # 41 toolbar/tree PNG icons
├── tests/
│   ├── test_core.py                           # Unit tests: models, statements, settings
│   ├── test_query_tools.py                    # Unit tests: pagination, overwrite, DELETE
│   ├── e2e_gui.py                             # GUI end-to-end suite (offscreen, FakeClient)
│   ├── e2e_dbeaver.py                         # DBeaver-style feature suite (part1 real / part2 fake)
│   ├── e2e_readonly.py                        # Read-only checks against a real server
│   └── shot_feature_ui.py                     # Real-platform screenshot generator
└── .venv/                                     # Project virtual environment (git-ignored)
```

---

## Getting Started

### Prerequisites

- **Python**: 3.9 or higher (3.12 recommended)
- **InfluxDB**: 1.x server (1.7+ recommended) reachable over HTTP
- **OS**: Windows 10/11 (primary), Linux and macOS also work (offscreen CI tested)

### Installation

```bash
# Clone the repository
git clone https://github.com/IYeaSakura/InfluxDB-Manager.git
cd InfluxDBStudio

# Create and activate a virtual environment in the project root
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

# Install in editable mode
python -m pip install -e .
```

### Run

```bash
# Option 1: project-root entry (works without installing)
python main.py

# Option 2: installed console script
influxdb-manager

# Option 3: module execution
python -m net.sakurain.influxdbstudio
```

On first launch (no saved connections) the connection manager dialog opens automatically; create a connection (e.g. `localhost:8086`, user/password for your InfluxDB) and test it. When saved connections exist, they are rendered directly into the tree at startup and no dialog pops up.

### Connection Parameters

The application stores connections in the per-user settings file (no `.env` needed):

| Field | Description | Example |
|-------|-------------|---------|
| Name | Display name in the tree | `prod-cluster` |
| Host | InfluxDB HTTP host | `10.82.10.103` |
| Port | InfluxDB HTTP port | `31123` |
| Username / Password | HTTP authentication | `sa` / `sa` |
| Database | Default database (optional) | `zn_data` |
| Use SSL | HTTPS transport | off |

---

## Usage

### Run a Query

1. Select a database (or measurement) in the tree, then click **New Query** (toolbar) or press the menu item.
2. Type InfluxQL, e.g. `SELECT * FROM "curveData3761"`.
3. Press **Ctrl+Enter**. The query runs in the background; the status line shows progress, and the result grid appears with pagination controls.

### Edit and Save Results

1. Wait for the grid to finish loading field metadata (only true field columns are editable; tags, time, and the row-number column are read-only).
2. Double-click a cell, type the new value, press Enter. The cell turns yellow.
3. To delete whole rows, select them and press **Delete** (they turn red).
4. Click **Save Changes (N rows)** (or Ctrl+S / context menu). Review the confirmation dialog listing every overwrite and deletion, then confirm.
5. To discard everything, click **Revert Changes**.

### Navigate Large Result Sets

- Set the page size in the pager (choose a preset or type any value, e.g. `37`).
- Use `|<`, `<`, `>`, `>|` to move between pages; the label shows `rows start-end / total`.
- Sort the current page by any column via the header right-click menu.

### Filter and Re-Sort Server-Side

- Right-click a column header and choose **Filter This Column...** to add a WHERE condition; the query re-runs on the server and the condition appears as a chip above the grid. Click a chip to remove it, or **Clear All** to drop every filter. The row total is recounted with the filters applied.
- Right-click the `time` column header and choose **Sort by Time Descending (Re-query)** to inject `ORDER BY time DESC`; choose it again to cancel.
- Select numeric cells to see count / average / sum / min / max in the Calc panel below the grid.

### Reuse Queries

- The **Query History** button in the grid toolbar lists every query executed on the current connection (newest first, persisted across launches). Double-click an entry to load it back into the editor, or remove entries you no longer need.

### Persist Query Scripts

- Open as many query tabs as needed; each gets a unique script name.
- Right-click a tab and choose **Rename** to give it a meaningful name.
- Scripts are saved automatically (on tab close and on application exit) and restored — including the active tab — the next time you start the application.

### Export Results

- Click **Export All** in the grid toolbar (or the header context menu) to export the **complete query result**: the original query is re-executed without the pagination `LIMIT` on a worker thread, so even millions of rows do not freeze the UI.
- Right-click selected rows and choose **Export Selected Rows** to export only the selection.
- Pick a format (CSV / XLSX / XML / Markdown / JSON / HTML); for CSV you can set a custom delimiter (default `,`).
- The last export directory is remembered for the next export.

---

## Development

### Run Tests

```bash
# Unit tests (fast, no server needed)
.venv\Scripts\python -m pytest tests/ -q --ignore=tests/e2e_gui.py --ignore=tests/e2e_readonly.py

# Full GUI e2e suite (offscreen platform, FakeClient — no real server touched)
set QT_QPA_PLATFORM=offscreen          # Windows
.venv\Scripts\python tests/e2e_gui.py

# DBeaver-style feature suite (part 2 uses FakeClient; part 1 is read-only against a real server)
.venv\Scripts\python tests/e2e_dbeaver.py --part2
.venv\Scripts\python tests/e2e_dbeaver.py --part1
```

### Available Commands

| Command | Description |
|---------|-------------|
| `python main.py` | Start the application from the source tree |
| `pytest tests/ -q` | Run the unit test suite |
| `python tests/e2e_gui.py` | Run the 40-check GUI regression suite |
| `python tests/e2e_dbeaver.py --part1/--part2` | Run the DBeaver-style feature suites |
| `python tests/shot_feature_ui.py` | Generate a real-platform feature screenshot |

### Code Style

- **Naming**: `snake_case` functions/variables, `PascalCase` classes, `SCREAMING_SNAKE_CASE` constants; public class attributes kept PascalCase where they mirror the C# models (e.g. `series.Values`) for port fidelity
- **Port parity**: behavior and InfluxQL statements are byte-compatible with the C# client unless a feature is explicitly marked as an enhancement
- **i18n**: all user-facing strings go through `tr("key", **kwargs)`; new keys must be added to both `zh_CN` and `en_US` tables in `i18n.py`
- **Threading**: network access only inside `run_async(work, done, failed)` workers; never block the GUI thread
- **Safety**: destructive operations (drop, delete rows, save overwrites) always require an explicit confirmation dialog

### Versioning

- Current version: `1.1.0` (`net.sakurain.influxdbstudio.__version__`)
- Settings files carry a `Version` field; migrations should be added to `AppSettings.load_all`

---

## Build & Deployment

### Build a Windows Executable

The build uses a checked-in PyInstaller spec (`InfluxDBManager.spec`) that trims unused Qt modules (Qml/Quick/Pdf/OpenGL/3D/…) and plugins, cutting the bundle from ~120 MB of binaries to a ~30 MB single-file exe.

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller InfluxDBManager.spec --distpath dist_slim --workpath build_slim --clean -y
```

Note: the managed Python runtime used for development keeps its OpenSSL DLLs outside the standard library folder; the spec already bundles `libssl-3-x64.dll` / `libcrypto-3-x64.dll` explicitly. If you build with a standard python.org interpreter, you can drop those two `--add-binary` entries from the spec.

Output: `dist_slim/InfluxDBManager.exe` (single file, windowed, sakurain icon, embedded version info `1.1.0.0`). The window and the Windows taskbar show the sakurain icon (an explicit `AppUserModelID` is set at startup so taskbar grouping shows the correct icon).

### Build a Windows Installer

The installer is built with [Inno Setup](https://jrsoftware.org/isdl.php) 7.x from `installer/setup.iss` (LZMA2/ultra64 solid compression, bilingual installer UI, optional desktop icon, signed uninstaller entry):

```bash
"path\to\ISCC.exe" installer\setup.iss
```

Output: `dist/InfluxDBManager-Setup-1.1.0.exe` (~31 MB).

### Build Stages

| Stage | Description |
|-------|-------------|
| 1. Collect | Bundle PySide6 Qt libraries (trimmed to Core/Gui/Widgets) and resources |
| 2. Analyze | Follow imports from `net.sakurain.influxdbstudio.__main__` |
| 3. Package | Produce the single-file `InfluxDBManager.exe`, then the Inno Setup installer |

### First-Run Notes

- Settings are stored under the per-user config directory (`platformdirs`), e.g. `%APPDATA%\InfluxDBStudio\settings.json` on Windows; the executable does not need write access to its own folder
- The config directory key is intentionally unchanged from previous releases so existing connections survive upgrades
- When a tree lazy-load fails (server down, network error, timeout), the loading placeholder is replaced by a red inline error node — double-click it to retry; no modal error dialog appears

---

## Core Design

### Overwrite Instead of Update

InfluxDB 1.x has no `UPDATE`. Cell edits are persisted by rewriting the whole point:

1. The original row provides measurement, tags, and the exact nanosecond timestamp.
2. Edited fields are coerced to the type reported by `SHOW FIELD KEYS` (strings stay strings, integers get the `i` suffix in line protocol).
3. The point is written through the `/write` API; identical measurement + tags + timestamp replace the stored point.

Time is always carried as raw nanoseconds end-to-end (`timestamp_to_ns` / `ns_to_rfc3339`), so round-tripping through the UI cannot corrupt sub-second precision.

### Precise Row Deletion

Deleted rows generate one statement per row:

```sql
DELETE FROM "curveData3761"
WHERE time = '2026-09-27T16:00:00.000000001Z' AND "nmunicateAddr" = '042760236'
```

Tag equality conditions are included so that only the intended point is removed, not every point sharing the timestamp. Single quotes inside tag values are escaped (`\'`), matching the C# client.

### Pagination Injection

```
plain SELECT (no LIMIT/OFFSET/GROUP BY/INTO)  ->  append LIMIT n OFFSET m
total count                                    ->  SELECT COUNT(*) FROM ... [WHERE ...]
```

Whole-line `--` comments are stripped before deciding whether a query is paginatable, so commented script headers do not disable pagination. Queries with their own `LIMIT` or `GROUP BY` are sent unchanged.

### Concurrency Model

```
GUI thread  --signal/slot-->  run_async  -->  worker thread (httpx I/O)
GUI thread  <--queued signal--  done(result) / failed(exception)
```

Every control inherits `RequestControl`, which wraps `run_async` and marshals results back to the GUI thread. Long queries keep the UI responsive and report progress in the status bar.

---

## Testing

### Coverage Overview

| Suite | Checks | Server Required | What It Verifies |
|-------|--------|-----------------|------------------|
| `test_core.py` + `test_query_tools.py` | 109 | No | Statements, line protocol, settings round-trip, pagination, DELETE builder, comment stripping, filter/order injection, query history, read-only connections, CSV import mapping, ranged DELETE, DPAPI secrets, connection categories |
| `e2e_gui.py` | 40 | No (FakeClient) | Full GUI regression: tree, dialogs, controls, exports |
| `e2e_dbeaver.py --part2` | 144 | No (FakeClient) | Editing, dirty marks, row deletion, confirm dialog, pager input, header menu, sorting, comments, edit bar, column filters, time ordering, Calc panel, history, write dialog, shards browser, import/delete wizards, category colors, multi-statement runs, EXPLAIN plans, copy-as-SQL, result charting, autocomplete |
| `e2e_dbeaver.py --part1` | 7 | Yes (read-only) | Real-server pagination, LIMIT/OFFSET injection, COUNT totals |
| `e2e_readonly.py` | - | Yes (read-only) | Read-only guarantees against a production-like server |

### Safety Guarantees for Production Testing

- Write paths (`write`, `execute_command`) are verified exclusively through a recording `FakeClient`; the test suites never send writes or deletes to a real server
- The read-only suite asserts that only `SELECT`/`SHOW` statements are issued
- Screenshot generation uses FakeClient rendering on the real platform for accurate fonts; production data is never accessed

---

## Troubleshooting

### The Application Will Not Start

**Problem**: `ModuleNotFoundError: No module named 'PySide6'`

**Solution**:

```bash
.venv\Scripts\python -m pip install -e .
```

Make sure you launched `python main.py` with the interpreter from the project-root `.venv`.

### Connection Test Fails

**Problem**: Ping returns an error or times out.

**Solution**:
- Verify the InfluxDB HTTP port is reachable: `curl http://<host>:<port>/ping`
- Check username/password; InfluxDB auth must be enabled server-side for non-admin users
- If using SSL with a self-signed certificate, enable **Allow Untrusted SSL** in Settings
- Confirm the database name exists: run `SHOW DATABASES` in the query window against the connection level

### Query Results Look Frozen

**Problem**: The grid stays empty for a long time on large measurements.

**Solution**: Deep `OFFSET` scans are slow on loaded InfluxDB servers. Reduce the page size (e.g. 100) and avoid jumping to the last page on multi-million-row measurements; the total count still appears once the background `COUNT(*)` finishes. The window remains responsive during the wait — check the status bar running indicator.

### Field Edit Is Rejected / Save Fails with Type Conflict

**Problem**: Saving an edited cell fails with a field-type conflict from the server.

**Solution**: The grid preserves the type reported by `SHOW FIELD KEYS` (e.g. fields stored as strings stay strings). If the server-side type changed since the metadata was loaded, re-run the query to refresh metadata, then edit again.

### Taskbar Shows the Wrong Icon on Windows

**Problem**: The taskbar groups the app under a generic Python icon.

**Solution**: The app sets an explicit `AppUserModelID` (`net.sakurain.InfluxDBManager`) at startup. If you launch via a custom wrapper, set the same ID in the wrapper, or launch `InfluxDBManager.exe` produced by the PyInstaller build.

---

## Contributing

Contributions are welcome. Please follow this workflow:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes following the code style guidelines above
4. Run the full test suite: `pytest tests/ -q` plus the GUI suites
5. Commit: `git commit -m 'feat: add new feature'`
6. Push: `git push origin feature/your-feature`
7. Open a Pull Request

### Code Quality Checklist

Before submitting a PR:

- [ ] All unit tests pass (`pytest tests/ -q`)
- [ ] GUI regression passes (`e2e_gui.py`, `e2e_dbeaver.py --part2`)
- [ ] New user-facing strings added to both language tables in `i18n.py`
- [ ] Destructive operations still require confirmation
- [ ] No network I/O on the GUI thread
- [ ] README (both languages) updated for behavior changes

---

## Changelog

See [CHANGELOG](CHANGELOG.md) for the release history. Notable 1.0.0 additions over the original C# version:

- DBeaver-style result grid: pagination, cell overwrite, row deletion, second-confirmation save, header context menu
- Query script tabs with rename and automatic restore across launches
- Ctrl+/ line comments with gray rendering
- Blue selection styling, always-visible save/revert bar
- Bilingual UI (Chinese default / English)
- Renamed to **InfluxDB Manager** with the sakurain application icon

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2016 CymaticLabs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Acknowledgments

This project is built with the help of many open-source projects:

- [CymaticLabs/InfluxDBStudio](https://github.com/CymaticLabs/InfluxDBStudio) - The original C#/WinForms application (MIT)
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) - Desktop GUI framework
- [httpx](https://www.python-httpx.org/) - Modern HTTP client for the InfluxDB API
- [platformdirs](https://platformdirs.readthedocs.io/) - Per-user config directories
- [pytest](https://pytest.org/) - Test framework
- [InfluxDB 1.x](https://docs.influxdata.com/influxdb/v1/) - The time series database this tool manages

---

## Contact

- **Author**: Yuyang.Wang
- **Website**: [https://sakurain.net](https://sakurain.net)
- **Email**: [Yae_SakuRain@outlook.com](mailto:Yae_SakuRain@outlook.com)
- **GitHub**: [https://github.com/IYeaSakura](https://github.com/IYeaSakura)
- **Repository**: [https://github.com/IYeaSakura/InfluxDB-Manager](https://github.com/IYeaSakura/InfluxDB-Manager)

---

<p align="center">
  Made by Yuyang.Wang
</p>
