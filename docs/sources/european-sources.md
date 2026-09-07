# European sources

Purpose: describe EPSO, EURES, and eu-LISA ingestion and the EU-specific matching path.

Read when: changing an EU source, browser interception, CSV/JSON/HTML mapping, deadline filtering, or the English IT keyword set.

Source of truth: the six EU fetcher/parser modules, `keyword_filter.py`, `main.py`, and `tests/test_eu_sources.py`.

## Shared matching

The three parsers normalize source data into `BOPage` objects with a source of `EPSO`, `EURES`, or `EULISA`. `KeywordFilter` then uses strict English IT patterns for EU pages and does not require Spanish public-contest anchors. The source parsers can filter expired records when a target date is supplied.

## EPSO

`EPSOFetcher` reads the EU Data Portal repository metadata, finds a CSV distribution, and downloads it. `EPSOParser` dynamically maps changing CSV column names to agency, title, location, contract, grade, deadline, and URL fields. A deadline earlier than the target date is filtered out when a target date exists.

## EURES

`EURESFetcher` launches a headless Playwright Chromium session, navigates to the EURES search page, and intercepts the page's successful search response. It returns the captured JSON to `EURESParser`, which supports the expected vacancy-list shapes and maps title, employer, location, description, and application URL. Playwright is imported lazily and is not declared in the repository's current requirements metadata; a live setup must account for that separately.

## eu-LISA

`EULISAFetcher` downloads the vacancies page. `EULISAParser` uses both table-row and link-list strategies, avoids duplicate links already represented by a table row, normalizes dates, and filters expired deadlines when requested.

## Date semantics

These sources use closing/deadline dates when available. That is different from a publication-date guarantee. In Lambda, `run_scan` passes the resolved execution date to the source parsers, so current code can exclude listings that have already closed; it does not create a durable history of previously sent EU findings.
