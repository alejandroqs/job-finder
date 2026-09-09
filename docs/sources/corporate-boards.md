# Corporate employment boards

Purpose: describe Sagulpa, Guaguas Municipales, GEURSA, GSC, and Aena list/detail scraping, active-window rules, and attachment handling.

Read when: changing a web-board parser, HTML selector, closing-date rule, title rejection, or temporary PDF flow.

Source of truth: the Sagulpa, Guaguas, GEURSA, GSC, and Aena fetcher/parser modules under [`src/job_finder`](../../src/job_finder/), [`keyword_filter.py`](../../src/job_finder/keyword_filter.py), and the corresponding tests under [`tests`](../../tests/).

## Shared pattern

The web-board interfaces separate list retrieval from detail retrieval. Parsers identify active entries, fetch or receive detail HTML, extract text, and convert the result to `BOPage`. A failing detail or attachment operation is handled inside the parser so one listing does not necessarily terminate a source scan. GEURSA and GSC are intentionally list-only and do not fetch a detail page or PDF while parsing their lists.

## Sagulpa

`SagulpaFetcher` reads the employment list and detail pages from `sagulpa.com`. `SagulpaParser` extracts the closing date from Spanish text and, when a target date is supplied, retains listings where the target date is on or before the closing date. It uses a Spanish month mapping rather than relying on the host operating system locale. Details become normalized page text for the common keyword filter.

## Guaguas Municipales

`GuaguasFetcher` reads the official list at [`guaguas.com/empresa/trabaja-con-nosotros`](https://www.guaguas.com/empresa/trabaja-con-nosotros). `GuaguasParser` selects either supported employment container variant, `.contenido_seccion.carnets` or `.contenido-seccion.carnets`, and processes each `.panel` independently. It extracts labelled application fields from the card content before the structural `Avisos` section boundary, so notice content cannot fill or replace `Puesto`, `Vacantes`, or `Convocatoria`. Metadata may appear before or after the `Bases reguladoras` heading. A link is accepted as the bases URL only when it is inside that bounded section and identifies bases material in its text or link metadata; when no bases link exists, a deterministic title-and-interval fragment identifies the record without claiming card scrolling support. The page's `<base href>` is used when resolving relative links.

Guaguas uses the list metadata only. It does not fetch one detail page per card, download PDFs, or include the `Avisos` history in the text sent to the shared Spanish filter or Gemini. The parser uses `target_date` when supplied and otherwise the current date; cards with missing, invalid, or inverted intervals are skipped with a diagnostic.

## GEURSA

`GeursaFetcher` reads one HTML page from [`geursa.es/procesos-de-seleccion`](https://www.geursa.es/procesos-de-seleccion/). `GeursaParser` finds the normalized `h4` heading `Convocatorias en vigor`, then processes only stable `.x-acc-item` cards before the next equal-or-higher heading and owning section boundary. It includes collapsed cards and retains cards with past, future, or missing deadline wording because section membership, not the deadline, determines inclusion. `Convocatorias finalizadas` is never traversed.

The parser keeps card-local descriptive and deadline text separate from attachment captions, prefers a card-local link labelled `Bases`, resolves relative links against the GEURSA list URL, and falls back to that source page when no Bases link exists. Local titles, bodies, controls, and links belong only to their nearest `.x-acc-item`; nested-card text and attachments cannot populate an outer record. Exact repeated card content is deduplicated without using generated IDs or DOM position; distinct processes may therefore share the fallback URL. A referenced accordion panel is used only when it remains inside the active section and is not owned by another card; invalid references fall back to valid local content or title-only metadata with the source-page URL. `target_date` is accepted for interface compatibility but is not used to filter records or reconstruct historical page state. No publication date is fabricated.

## GSC

`GSCFetcher` reads one current HTML list from [`gsccanarias.com/gsc/ofertas-de-empleo/`](https://www.gsccanarias.com/gsc/ofertas-de-empleo/). `GSCParser` is a `BaseParser` implementation rather than a web-board detail parser. It accepts only the holder `.projects_holder.portfolio_main_holder` owned by `#seleccion` and reads direct `article` children. Each record must have exactly one owned `h5.portfolio_title.entry_title` and one owned title anchor; image links, decorative links, category text, attachment captions, nested articles, and other holders cannot supply record fields.

The parser reads an anchored, validated `DD/MM/YYYY` or `DD-MM-YYYY` prefix from the owned title. It includes a record only when `publication_date <= reference_date <= publication_date + 7 days`, with both boundaries inclusive. This is a synthetic monitoring window, not an official application deadline; the inferred end date is labelled separately from the publication date. Missing, ambiguous, malformed, impossible, or unsupported publication dates are skipped with a contextual diagnostic. Results, provisional or definitive applicant/admission lists, corrections, rectifications, subsanación notices, exam/stage summons, and clear cancellation or annulment wording are excluded before shared IT filtering using narrow accent-insensitive and case-insensitive title rules. A legitimate title such as `Técnico de Gestión Administrativa` is not rejected merely because of that wording.

One included record becomes one `BOPage` for the shared Spanish keyword filter. The normalized paragraph contains the title, `Fecha de publicación`, and `Fin de ventana de seguimiento inferida` labels and explicitly states that the inferred date is not an official application deadline. Only text and links owned by the current article's title anchor are used, so nested records cannot populate or exclude the outer record. The title anchor is resolved against the list URL only when it is a usable HTTP(S) navigation URL; empty, fragment-only, non-navigation, or malformed links retain the record with the actual list URL and a diagnostic. Exact title/publication-date/resolved-URL duplicates are removed, while distinct records sharing a URL remain separate. Parsing makes no detail, PDF, or additional network request.

## Aena

`AenaFetcher` uses the Aena employment list, detail pages, and linked PDFs. `AenaParser.parse_list` applies title rejection and a hard expiration check before detail downloads. Absolute rejection patterns always drop a title; relative rejection patterns drop it unless an IT keyword overrides them. Detail extraction selects links whose text or title suggests bases or requirements. PDFs are written to unique temporary paths and cleaned up. If a detail page or individual PDF fails, the parser can return a fallback block containing the title and closing date.

## Operational caveats

All five portals are external SSR websites whose markup and availability can change. The local tests use fixtures and injected mock fetchers. They establish parser behaviour for covered HTML, dates, and errors; they do not prove that any live portal remains reachable or unchanged. The GSC implementation does not add pagination or load-more retrieval; the inspected snapshot had no pagination controls, and a generic `infinitescroll.min.js` include is not evidence of additional records. A historical GSC target date filters the current page response and does not reconstruct historical website state. Repeated scans within the same inferred window can produce repeated findings or notifications because no persistent cross-run deduplication is introduced. A separate read-only GEURSA check fetched one live list response through `GeursaFetcher` and parsed one active card with zero IT findings at that run; it did not use AI, notifications, or attachment downloads.
