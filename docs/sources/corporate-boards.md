# Corporate employment boards

Purpose: describe Sagulpa and Aena list/detail scraping, active-window rules, and attachment handling.

Read when: changing a web-board parser, HTML selector, closing-date rule, title rejection, or temporary PDF flow.

Source of truth: the Sagulpa and Aena fetcher/parser modules under [`src/job_finder`](../../src/job_finder/), [`keyword_filter.py`](../../src/job_finder/keyword_filter.py), and the corresponding tests under [`tests`](../../tests/).

## Shared pattern

The web-board interfaces separate list retrieval from detail retrieval. Parsers identify active entries, fetch or receive detail HTML, extract text, and convert the result to `BOPage`. A failing detail or attachment operation is handled inside the parser so one listing does not necessarily terminate a source scan.

## Sagulpa

`SagulpaFetcher` reads the employment list and detail pages from `sagulpa.com`. `SagulpaParser` extracts the closing date from Spanish text and, when a target date is supplied, retains listings where the target date is on or before the closing date. It uses a Spanish month mapping rather than relying on the host operating system locale. Details become normalized page text for the common keyword filter.

## Aena

`AenaFetcher` uses the Aena employment list, detail pages, and linked PDFs. `AenaParser.parse_list` applies title rejection and a hard expiration check before detail downloads. Absolute rejection patterns always drop a title; relative rejection patterns drop it unless an IT keyword overrides them. Detail extraction selects links whose text or title suggests bases or requirements. PDFs are written to unique temporary paths and cleaned up. If a detail page or individual PDF fails, the parser can return a fallback block containing the title and closing date.

## Operational caveats

Both portals are external SSR websites whose markup and availability can change. The local tests use fixtures and injected mock fetchers. They establish parser behaviour for covered HTML, dates, and errors; they do not prove that either live portal is reachable or unchanged.
