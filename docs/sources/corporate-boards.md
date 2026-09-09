# Corporate employment boards

Purpose: describe Sagulpa, Guaguas Municipales, and Aena list/detail scraping, active-window rules, and attachment handling.

Read when: changing a web-board parser, HTML selector, closing-date rule, title rejection, or temporary PDF flow.

Source of truth: the Sagulpa, Guaguas, and Aena fetcher/parser modules under [`src/job_finder`](../../src/job_finder/), [`keyword_filter.py`](../../src/job_finder/keyword_filter.py), and the corresponding tests under [`tests`](../../tests/).

## Shared pattern

The web-board interfaces separate list retrieval from detail retrieval. Parsers identify active entries, fetch or receive detail HTML, extract text, and convert the result to `BOPage`. A failing detail or attachment operation is handled inside the parser so one listing does not necessarily terminate a source scan.

## Sagulpa

`SagulpaFetcher` reads the employment list and detail pages from `sagulpa.com`. `SagulpaParser` extracts the closing date from Spanish text and, when a target date is supplied, retains listings where the target date is on or before the closing date. It uses a Spanish month mapping rather than relying on the host operating system locale. Details become normalized page text for the common keyword filter.

## Guaguas Municipales

`GuaguasFetcher` reads the official list at [`guaguas.com/empresa/trabaja-con-nosotros`](https://www.guaguas.com/empresa/trabaja-con-nosotros). `GuaguasParser` selects either supported employment container variant, `.contenido_seccion.carnets` or `.contenido-seccion.carnets`, and processes each `.panel` independently. It extracts labelled application fields from the card content before the structural `Avisos` section boundary, so notice content cannot fill or replace `Puesto`, `Vacantes`, or `Convocatoria`. Metadata may appear before or after the `Bases reguladoras` heading. A link is accepted as the bases URL only when it is inside that bounded section and identifies bases material in its text or link metadata; when no bases link exists, a deterministic title-and-interval fragment identifies the record without claiming card scrolling support. The page's `<base href>` is used when resolving relative links.

Guaguas uses the list metadata only. It does not fetch one detail page per card, download PDFs, or include the `Avisos` history in the text sent to the shared Spanish filter or Gemini. The parser uses `target_date` when supplied and otherwise the current date; cards with missing, invalid, or inverted intervals are skipped with a diagnostic.

## Aena

`AenaFetcher` uses the Aena employment list, detail pages, and linked PDFs. `AenaParser.parse_list` applies title rejection and a hard expiration check before detail downloads. Absolute rejection patterns always drop a title; relative rejection patterns drop it unless an IT keyword overrides them. Detail extraction selects links whose text or title suggests bases or requirements. PDFs are written to unique temporary paths and cleaned up. If a detail page or individual PDF fails, the parser can return a fallback block containing the title and closing date.

## Operational caveats

All three portals are external SSR websites whose markup and availability can change. The local tests use fixtures and injected mock fetchers. They establish parser behaviour for covered HTML, dates, and errors; they do not prove that either live portal is reachable or unchanged.
