# Agent Notes

## Testing

This project has automated tests. Always run them before finishing a task or claiming correctness.

### Install dependencies

```bash
. .venv/bin/activate
pip install -r requirements-dev.txt
```

### Run tests

```bash
. .venv/bin/activate
pytest
```

Run with verbose output:

```bash
pytest -v
```

### Test layout

- Unit tests for pure logic live in `tests/test_*.py`.
- Integration tests use the `client` fixture from `tests/conftest.py`, which is a FastAPI `TestClient` backed by a fresh in-memory SQLite database per test.
- The global notifier is reset between tests so ntfy background tasks do not leak state.
- To test ntfy calls, mock the `httpx` client and set `notifier.topic` in the test.

### When to add or update a test

- Add or update a test when you fix a bug, add a feature, or change behavior.
- For route changes, add integration tests in `tests/test_routes.py`.
- For notifier/message formatting changes, add tests in `tests/test_notifier.py`.
- For period/volume logic, add tests in `tests/test_period.py`.
- For summary/chart logic, add tests in `tests/test_summary.py`.
- For CSV import logic, add tests in `tests/test_csv_import.py`.

### Manual testing

Avoid manual testing as a substitute for automated tests. Only run manual checks for one-off verification that cannot be easily automated (for example, verifying idempotent database connection behavior in a specific environment).

If you do run a manual check, briefly note why it was needed and whether an automated test should replace it later.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues. Use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo. Read `CONTEXT.md` at the repo root and `docs/adr/` before exploring. See `docs/agents/domain.md`.
