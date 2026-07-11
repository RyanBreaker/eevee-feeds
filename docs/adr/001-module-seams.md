# ADR 001: Domain module seams for the feeding tracker

## Status

Accepted

## Context

`app/routes.py` had become a catch-all: HTTP routing, database queries, period/summary calculations, ntfy notification logic, CSV parsing, and response rendering all lived in one file. This made the file hard to navigate and the logic hard to test in isolation.

We needed clear seams so that:

- Unit tests can exercise business logic without spinning up a FastAPI `TestClient`.
- Route handlers stay focused on HTTP concerns: parsing request input, calling domain modules, and choosing a response.
- Future changes (new notification backends, new CSV formats, new charting) change one module at a time.

## Decision

Split the domain into focused modules with single responsibilities, leaving `app/routes.py` as a thin HTTP adapter.

| Module | Responsibility |
|--------|----------------|
| `app/repository.py` | Data access for `Feeding` and `TargetConfig`: lookups, defaults, and period-scoped queries. |
| `app/summary.py` | Assembly of period summaries and chart data from repository results. |
| `app/notification_service.py` | Threshold parsing, notification status, test sends, and the background check that decides when to send ntfy alerts. |
| `app/csv_import.py` | Orchestration of CSV import: uses the reader and repository. |
| `app/csv_io.py` | Shared CSV schema, `FeedingCsvReader`, and `FeedingCsvWriter`. |
| `app/notifier.py` | Async lifecycle wrapper around `NotificationService` (start/stop background loop). |
| `app/routes.py` | Thin HTTP adapter. |

### Dependencies between modules

- `app/routes.py` depends on `app.repository`, `app.summary`, `app.notification_service`, `app.csv_import`, and `app.csv_io`.
- `app.summary` depends on `app.repository` and `app.period`.
- `app.notification_service` depends on `app.repository` and `app.period`.
- `app.csv_io` depends only on `app.models`.
- `app.csv_import` depends on `app.csv_io` and `app.repository`.

### Test seams

- Pure logic lives in `tests/test_*.py` against the public module interface.
- Integration tests for routes use the `client` fixture in `tests/conftest.py`.
- The global notifier is reset between tests so background tasks do not leak state.

## Consequences

- Adding a new chart metric means changing `app/summary.py` and `tests/test_summary.py`, not `routes.py`.
- Adding a new notification backend means changing `app/notification_service.py`, not the route handler.
- CSV format changes are owned by `app/csv_io.py`, and round-trip tests in `tests/test_csv_io.py` guarantee import/export consistency.
- Route handlers are shorter and easier to read, but they still perform simple request validation (e.g., "timestamp cannot be in the future") that is inherently an HTTP concern.

## Alternatives considered

- **Keep everything in routes.py**: Rejected because it discourages unit testing and couples unrelated features.
- **Split by layer (controllers, services, repositories)**: Rejected as over-engineered for this small codebase; modules are named by domain concept rather than architectural layer.
- **One module per model**: Rejected because `Feeding` and `TargetConfig` access patterns are small enough to share `app.repository.py`, and `Summary`/`Chart` are logically one seam.
