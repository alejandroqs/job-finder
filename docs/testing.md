# Testing and evidence

Purpose: explain the local test suite and what its results can establish.

Read when: changing parsers, filters, exporters, fixtures, or test commands.

Source of truth: [`tests/`](../tests/), [`tests/conftest.py`](../tests/conftest.py), and the development dependencies in [`pyproject.toml`](../pyproject.toml).

## Run the suite

From the repository root in PowerShell:

```powershell
python -m pytest tests/ -v --tb=short
```

The repository uses pytest fixtures and local samples. Do not hard-code a test count in documentation; the count changes as coverage evolves.

## Test groups

| File | Scope |
| --- | --- |
| `test_bop_parser.py` | Text cleaning, accent handling, keyword/anchor filtering, BOP URL construction, PDF parsing, and mocked latest-bulletin fetching. |
| `test_boc_parser.py` | RSS section filtering, keyword filtering, URL construction, date filtering, and mocked latest-feed behaviour. |
| `test_boe_parser.py` | Section and heuristic filtering, XML parsing, API headers, 404 behaviour, fallback probing, and PDF deep-scan paths. |
| `test_sagulpa_parser.py` | List/detail extraction, active closing-date boundaries, and injected-fetcher behaviour. |
| `test_aena_parser.py` | List rejection and expiration, detail/PDF extraction, and injected-fetcher behaviour. |
| `test_eu_sources.py` | EPSO, EURES, and eu-LISA parsing/filtering plus Gemini validation, retries, structured output, deduplication, and fallback behaviour. |
| `test_keyword_filter.py` | Early title-rejection rules. |
| `test_html_exporter.py` | HTML rendering, empty findings, and overwrite behaviour. |

Fixtures are synthetic or local samples. Network calls are generally mocked. A passing suite therefore establishes deterministic parser and orchestration behaviour for the covered cases; it does not establish that official portals, Playwright, Gemini, Discord, Telegram, AWS, or the deployment workflow currently work in production.

When a documentation question depends on a test, inspect the test and fixture as well as its result. A test name or comment is not proof of an external integration.
