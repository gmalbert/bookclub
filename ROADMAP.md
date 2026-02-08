# Book Club Selections — Roadmap

This roadmap gives a prioritized list of suggested ongoing changes and improvements for the `bookclub` app. Tasks are written to be actionable and specific to the current single-file Streamlit app in `selections.py` and the CSV-based datastore in `data_files/`.

## Goals (why)
- Improve reliability and error handling of the Hardcover API integration.
- Make the app easier to maintain by addressing technical debt in `selections.py` while keeping changes small and surgical.
- Improve developer experience: tests, CI, formatting, and a local debug mode.
- Harden persistence (CSV) behavior and prepare for a later migration to a lightweight DB if/when needed.

## Short-term (0–4 weeks) — High priority, low-risk
- Add a small config constants section at top of `selections.py`:
  - `DEBUG_TIMEOUT = 3`, `API_TIMEOUT = 10`, `DATA_DIR = 'data_files/'` (already present) — centralize and use for `requests.post` calls.
  - Why: makes timeouts and behavior easier to change for local testing.

- Improve token handling messages and dev UX:
  - Update `load_api_token()` to return explicit error codes or raise a small custom exception when no token found so the UI can show a friendly banner and a link to `DEPLOYMENT.md`.
  - Add a short doc comment in `DEPLOYMENT.md` with the exact `.streamlit/secrets.toml` example (already present — expand with copy/paste example).

- Add defensive CSV write patterns:
  - Wrap `to_csv()` calls with a safe write helper (write to `*.tmp` then move/rename) to avoid corrupt CSV on interrupted writes.
  - Implement a small `backup_book_selections()` helper used before destructive operations (clear, remove duplicates).

- Add basic unit tests for pure logic (no Streamlit UI):
  - Test `_apply_field_filters()` with example payloads.
  - Test `get_primary_genre()` and `get_eligible_books_for_selection()` with small DataFrames.
  - Store tests under `tests/test_search_filters.py` and run with `pytest`.

- Logging & debug helpers:
  - Add `logger = logging.getLogger(__name__)` + basic `logging` usage in failure paths (search, CSV read/write) to aid debugging.

## Medium-term (1–3 months) — Moderate effort
- Modularize code (surgical split):
  - Extract API/search helpers into `bookclub/search.py` (functions: `search_hardcover_api`, `_perform_single_search`, `_apply_field_filters`, `_simplified_fallback_search`).
  - Extract persistence helpers into `bookclub/storage.py` (functions: `load_book_list`, `save_book_to_list`, `load_selection_history`, `save_book_selection`, `clean_duplicate_books`).
  - Keep `selections.py` as the Streamlit UI only; this reduces merge conflicts and improves testability.

- Add caching for API responses (in-memory TTL cache):
  - Cache per-query results for short TTL (e.g., 10 minutes) to reduce repeated API calls during testing and demos.

- Add CI (GitHub Actions):
  - Basic workflow: install Python from `requirements.txt`, run `flake8`/`ruff` (or `black --check`), run `pytest`.
  - Run safety checks to ensure `token.txt` or `.streamlit/secrets.toml` are not checked into commits.

- Improve error handling and UX:
  - When API fails, show a clear non-blocking info box with actions: (1) switch to manual entry, (2) retry, (3) view last cached results.

## Long-term (3–12 months) — Larger features / optional
- Concurrency-safe persistence or light DB migration:
  - Migrate CSVs to SQLite or TinyDB behind a small adapter layer. Keep CSV adapter for backward compatibility.

- Multi-user / authentication:
  - Add simple authentication or sessions if the app becomes multi-user; or deploy behind an authenticated proxy (Streamlit Cloud + team).

- Better export templates and accessibility:
  - Improve `generate_pdf_data()` to use templated layouts, add accessibility (text alternatives), and support multi-page tables with consistent headers.

- Observability & monitoring:
  - Add lightweight telemetry: counts of searches, API failures, export usage (respect privacy and secrets).

## Technical debt / risks
- Single-file app: `selections.py` mixes UI and logic making targeted changes riskier; prefer small, tested refactors.
- CSV atomicity: current `to_csv()` calls can corrupt files if interrupted. Implement safe-write pattern before production use.
- Token exposure: current fallback to `token.txt` is handy for local dev but may encourage bad practices; emphasize `st.secrets` in docs and CI checks.
- Session keys: many `st.session_state` keys are used in the UI. If you rename keys, make a compatibility shim to avoid breaking UX.

## Suggested PR checklist (include in PR template)
- **Scope**: Short description + list of edited files.
- **Tests**: Unit tests added/updated for non-UI logic.
- **Local test steps** (PowerShell):
  ```pwsh
  .\\.venv\\Scripts\\Activate.ps1
  pip install -r requirements.txt
  pytest -q
  streamlit run selections.py
  ```
- **Secrets**: Confirm `HARDCOVER_API_TOKEN` not committed; add `.streamlit/secrets.toml` instructions if needed.
- **CSV schema**: If any column names changed, update `ROADMAP.md` and `selections.py` usages.

## Example small tasks (good first PRs)
- Add `DEBUG_TIMEOUT` constant and use in `requests.post` calls.
- Implement `safe_write_csv(path, df)` helper and replace direct `to_csv()` usages in two places (`save_book_to_list`, `clear_all_selections` or removal flows).
- Add `tests/test_filters.py` to validate `_apply_field_filters()` behaviors for author/title/genre combinations.

---
If you'd like, I can open PR-ready diffs for any of the short-term tasks above — tell me which item to prioritize and I will implement it and add tests where applicable.
