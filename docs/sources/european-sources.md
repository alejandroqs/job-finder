# European sources

Purpose: describe EPSO, EURES, and eu-LISA ingestion and the EU-specific matching path.

Read when: changing an EU source, browser interception, CSV/JSON/HTML mapping, deadline filtering, or the English IT keyword set.

Source of truth: the six EU fetcher/parser modules under [`src/job_finder`](../../src/job_finder/), [`keyword_filter.py`](../../src/job_finder/keyword_filter.py), [`main.py`](../../src/job_finder/main.py), and [`test_eu_sources.py`](../../tests/test_eu_sources.py).

## Shared matching

The three parsers normalize source data into `BOPage` objects with a source of `EPSO`, `EURES`, or `EULISA`. `KeywordFilter` then uses strict English IT patterns for EU pages and does not require Spanish public-contest anchors. Date handling is source-specific, as shown below.

## EPSO

`EPSOFetcher` reads the EU Data Portal repository metadata, finds a CSV distribution, and downloads it. `EPSOParser` dynamically maps changing CSV column names to agency, title, location, contract, grade, deadline, and URL fields. A deadline earlier than the target date is filtered out when a target date exists.

## EURES

`EURESFetcher` launches a headless Playwright Chromium session, navigates to the EURES search page, and intercepts the page's successful search response. It returns the captured JSON to `EURESParser`, which supports the expected vacancy-list shapes and maps title, employer, location, description, and application URL. `EURESParser.parse_raw` accepts `target_date` for interface compatibility but does not currently filter vacancies by it. Playwright is imported lazily and is not declared in the repository's current requirements metadata; a live setup must account for that separately.

## eu-LISA

`EULISAFetcher` downloads the vacancies page. `EULISAParser` uses both table-row and link-list strategies, avoids duplicate links already represented by a table row, normalizes dates, and filters expired deadlines when requested.

## Date semantics

| Source | Date behaviour |
| --- | --- |
| EPSO | Filters records whose application deadline is earlier than the supplied target date. |
| EURES | Accepts the target date but currently does not apply a date filter. |
| eu-LISA | Filters records whose parsed deadline is earlier than the supplied target date. |

These are closing/deadline checks, not publication-date guarantees. In Lambda, `run_scan` passes the resolved execution date to all three parsers, but EURES currently ignores it. The application has no durable history of previously sent EU findings.
