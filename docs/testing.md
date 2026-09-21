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
| `test_deployment_workflows.py` | Static workflow safeguards: deployment never invokes Lambda, manual publishing requires consent on main, invocation retries are disabled, response errors are checked, and production workflows share a concurrency group. Does not execute GitHub Actions or AWS. |
| `test_bop_parser.py` | Text cleaning, accent handling, keyword/anchor filtering, BOP URL construction, PDF parsing, and mocked latest-bulletin fetching. |
| `test_boc_parser.py` | RSS section filtering, keyword filtering, URL construction, date filtering, and mocked latest-feed behaviour. |
| `test_boe_parser.py` | Section and heuristic filtering, XML parsing, API headers, 404 behaviour, fallback probing, and PDF deep-scan paths. |
| `test_sagulpa_parser.py` | List/detail extraction, active closing-date boundaries, and injected-fetcher behaviour. |
| `test_guaguas_parser.py` | Label-based card extraction, structural notice exclusion, inclusive application windows, bases-link resolution, deduplication, diagnostics, and Spanish filtering. |
| `test_guaguas_fetcher.py` | Mocked list/detail requests, explicit timeout, HTTP status checks, URL resolution, and contextual failures. |
| `test_guaguas_integration.py` | No-network Guaguas pipeline, source groups, structural offline detection beyond a long header, container variants, generic-page rejection, neighbouring-source routing, and `no_ai=True`. |
| `test_geursa_parser.py` | Active-section boundaries, empty semantic-owner containment, finalized-section exclusion, nearest-card ownership for nested titles/bodies/links, collapsed panels, controlled-panel containment, deadline-independent inclusion, Bases/fallback URLs, attachment separation, deduplication, diagnostics, and input parity. |
| `test_geursa_fetcher.py` | Mocked list/detail requests, explicit timeout, UTF-8 stream wrapping, HTTP status checks, URL resolution, and contextual failures. |
| `test_geursa_integration.py` | No-network GEURSA pipeline, fake AI-enabled orchestration, source groups, CLI acceptance, conservative offline detection, neighbouring-source routing, and `no_ai=True`. |
| `test_gsc_parser.py` | Bounded `#seleccion` extraction, owned title/date/link association including nested-record isolation, slash/hyphen dates, inclusive synthetic windows, case/accent-insensitive administrative/cancellation exclusions, diagnostics, malformed and other URL fallback, deduplication, input parity, and normalized date labels. |
| `test_gsc_fetcher.py` | One-request list fetching, explicit timeout, UTF-8 stream wrapping, HTTP status checks, contextual failures, and unexpected-error propagation. |
| `test_gsc_integration.py` | No-network GSC pipeline, pre-filter notice exclusion, fake AI orchestration, source groups, CLI acceptance, conservative offline detection for HTML/signatures, empty-section containment, shared-URL AI identity, payload-level deduplication, missing-verdict fallback, and failed-chunk fallback behaviour. |
| `test_aena_parser.py` | List rejection and expiration, detail/PDF extraction, and injected-fetcher behaviour. |
| `test_indra_fetcher.py` | UTF-8 search/detail fetching, exact query parameters, official-host and redirect validation, timeout/status context, and unexpected-error propagation. |
| `test_indra_parser.py` | Row and nearest-record ownership including nested-row text isolation, duplicate anchors, malformed/category URLs, no-match recommendations, structural errors, real-link pagination, inherited/matching/conflicting sort ordering and default-sort variants, duplicate navigation and repeated-result detection, totals and safety diagnostics, query/detail failure isolation, canonical identity quarantine, numeric-ID deduplication, detail field fallback, bounded document-order description sections, observed section boundaries, Unicode/mode/geography normalization including Portugal/Brazil country evidence, excluded and non-excluded conflicts, street/client-text boundaries, offline/online title-filter parity, and zero-network offline parsing. |
| `test_indra_integration.py` | Shared first-filter and optional fake-AI orchestration, source-field payload/window capture, source groups, exact CLI choice, conservative offline routing, listing-only limits, title/term separation, and one-detail-per-job behaviour. |
| `test_fulp_fetcher.py` | Public-host/list/detail URL validation, tracking-parameter normalization, current-URL relative redirects, trailing-slash fetch URLs, redirect safety, explicit timeout propagation, no-retry behaviour, scheduling/attempt budgets, and contextual request failures. |
| `test_fulp_parser.py` | Top-level listing/detail ownership, nested identity isolation, application-control boundaries, type-badge preservation, employer/source and locality metadata, summary and section extraction, numeric-ID identity, deadlines and availability diagnostics, duplicate/continuation handling, offline identity quarantine, listing-only evidence, payload ordering, and serial detail failure isolation. |
| `test_fulp_integration.py` | No-network fixture pipeline, source-group membership, CLI choice, generic-extension and long-prefix offline routing, shared keyword filtering, observed type fixtures, captured fake-AI payload evidence, and no-AI orchestration. |
| `test_eu_sources.py` | EPSO, EURES, and eu-LISA parsing/filtering plus Gemini validation, source-field and cross-source identity coverage, labelled Indra policy plumbing, retries, structured output, deduplication, and fallback behaviour. |
| `test_keyword_filter.py` | Early title-rejection rules, public/corporate technology and cybersecurity matching, role-specific Service Desk and IT-support contexts, incidental-skills exclusions, ambiguous acronym negatives, and discovery-only `portal_search_keywords` validation/normalization. |
| `test_html_exporter.py` | HTML rendering, empty findings, and overwrite behaviour. |

Fixtures are synthetic or local samples. Indra fixture provenance and the distinction between observed layout fragments and synthetic edge cases are recorded in [`tests/fixtures/indra_provenance.md`](../tests/fixtures/indra_provenance.md); the bounded FULP observations and synthetic mutations are recorded in [`tests/fixtures/fulp_provenance.md`](../tests/fixtures/fulp_provenance.md). Network calls are generally mocked. A passing suite therefore establishes deterministic parser and orchestration behaviour for the covered cases; it does not establish that official portals, Playwright, Gemini, Discord, Telegram, AWS, or the deployment workflow currently work in production. The Indra and FULP AI tests use fake validators or mocked SDK calls; they establish no successful live AI classification.

When a documentation question depends on a test, inspect the test and fixture as well as its result. A test name or comment is not proof of an external integration.
