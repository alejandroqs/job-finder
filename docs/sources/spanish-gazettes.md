# Spanish official gazettes

Purpose: describe the BOP Las Palmas, BOC, and BOE integrations and their different publication formats.

Read when: changing a Spanish gazette fetcher/parser, date fallback, PDF/XML handling, or section filtering.

Source of truth: the BOP, BOC, and BOE fetcher/parser modules under [`src/job_finder`](../../src/job_finder/), [`keyword_filter.py`](../../src/job_finder/keyword_filter.py), and their tests under [`tests`](../../tests/).

## Shared filtering

The parsers produce `BOPage` objects. `KeywordFilter.search_page` splits page text into paragraphs, removes configured Spanish boilerplate, matches accent-insensitive IT patterns, and requires employment anchors for Spanish sources. It assigns the page's detected organism and source to each `ParsedAnnouncement`.

## BOP Las Palmas

`BOPFetcher` builds the unpadded date URL under `www.boplaspalmas.net/boletines/{year}/{day}-{month}-{yy}/...pdf`. A missing current bulletin can trigger `fetch_latest`, which reads the official index and, in the orchestration fallback, may use a recent bulletin. `BOPParser` reads the PDF page by page, retains the local-administration section, cleans text, and carries the last detected organism across page boundaries. In Lambda, the orchestration writes the downloaded bytes to a temporary PDF path before parsing and removes it in cleanup code.

## BOC

`BOCFetcher` requests the official RSS feeds, filters items by the requested date, and combines matching items. If the requested date has no items, the orchestration can ask for the latest available feed date. `BOCParser` reads the section hierarchy from feed descriptions and retains II.B Oposiciones y concursos, all III Otras Resoluciones, and V Administración Local entries. It normalizes title, paragraphs, organism, source, and link into `BOPage` objects.

## BOE

`BOEFetcher` requests the daily sumario API with an XML `Accept` header and a `YYYYMMDD` path. A 404 can trigger backward probing for a latest publication. `BOEParser` retains section `2B`, extracts department and epigraph context, and uses HTML or PDF links. The BOE orchestration may deep-scan candidate PDFs in parallel and falls back to title/XML data when a PDF cannot be processed.

## Date and Lambda distinction

Local CLI scans may fall back to the latest bulletin when today's publication is unavailable. Lambda mode applies additional checks so an older fallback does not create an obvious duplicate for the current execution date. This is a date-based safeguard, not a general persistent deduplication store.
