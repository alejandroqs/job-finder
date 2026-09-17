# Corporate employment boards

Purpose: describe Sagulpa, Guaguas Municipales, GEURSA, GSC, Aena, Indra Group, and FULP list/detail scraping, active-window rules, and attachment handling.

Read when: changing a web-board parser, HTML selector, closing-date rule, title rejection, or temporary PDF flow.

Source of truth: the Sagulpa, Guaguas, GEURSA, GSC, Aena, Indra, and FULP fetcher/parser modules under [`src/job_finder`](../../src/job_finder/), [`keyword_filter.py`](../../src/job_finder/), and the corresponding tests under [`tests`](../../tests/).

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

## Indra Group

`IndraFetcher` reads the official server-rendered search endpoint at
[`careers.indragroup.com/search/`](https://careers.indragroup.com/search/) and
official detail pages. `IndraParser` performs a full blank search by default.
The optional `portal_search_keywords` YAML key causes one exact search per
configured term; it deliberately narrows discovery and cannot claim complete
catalogue coverage. Terms are sent through `requests` parameters, so quoting
and punctuation are not interpreted locally.

Search ownership is bounded to `table#searchresults tr.data-row`. The parser
associates each title, location, and date with its nearest row; foreign
nested-row text is excluded. It validates duplicate desktop/mobile title
anchors, recognises `#noresults` before any
recommendation rows, and treats a missing table without a genuine empty state
as a structural error. It follows official `.pagination a[href]` search links,
resolves them against the current page, preserves the chosen query and locale,
inherits omitted sort parameters from the current page (or the portal default
when sorting is omitted), rejects conflicting ordering and narrower filters,
and deduplicates scheduled page identities and job IDs. Short pages do not
terminate traversal; ordinary navigation cycles are ignored after their
covered page is scheduled.
Advertised totals are compared with discovered identities before intentional
title rejection, while rejected and malformed rows remain visible in the
diagnostics. Repeated result sets or bodies, contradictory totals, failed
pages, and safety-bound exits are reported as incomplete coverage.

Detail extraction is bounded to the owning `.job` element and the verified
`data-careersite-propertyid` fields, with local `.joblayouttoken-label`
fallbacks for wrapping changes. The normalized `BOPage` retains raw location,
country, raw and normalized work mode, profile, experience, role, description,
responsibilities, and requirements early in one cohesive paragraph. Generic
navigation, cookies, benefits, and recruitment boilerplate are excluded only at
narrow, evidenced section boundaries; description blocks are traversed once in
document order; text from nested `.job` records is not owned by the outer
record. Recognised observed headings include
`¿Qué harás?`, `¿Qué buscamos en ti?`, `Requisitos imprescindibles`, `Lo que
te ofrecemos`, and `¿Cómo es nuestro proceso de selección?`. A paragraph is
not discarded merely because it begins with the company name. A contradictory
canonical job ID quarantines the detail response instead of relabelling it as
the listing ID, and a valid missing or malformed canonical can still use the
listing fallback. Candidate identity accepts official `/job/<slug>/<numeric-id>/`
paths with an optional division prefix; `/go/` category URLs are not jobs, even
when their numeric suffix matches a job. No synthetic `convocatoria` or
`selección` anchor is added.

The geographic prefilter accepts explicit `Remoto`/`Remote`, explicit
`Indiferente` as `FLEXIBLE_OR_UNSPECIFIED`, or an actual structured location
that explicitly names `Gran Canaria` or `Las Palmas de Gran Canaria`. Work-mode
normalisation accepts only explicit supported values; negated, mixed, unknown,
or conflicting values remain `UNKNOWN` and never imply remote. Madrid hybrid,
Spain with unknown mode, ambiguous `Las Palmas`, and unsupported `LPGC` are
rejected or remain unknown. Country is metadata rather than a rejection rule,
so Mexico plus Remote is retained. A failed or identity-mismatched detail is
skipped with a diagnostic and never treated as geographic evidence. The source
uses the unchanged shared title, IT-keyword, and employment-anchor filter both
offline and after online detail extraction, then the existing optional Gemini
stage; its role-relevance prompt does not establish international
contractual eligibility.

## Aena

`AenaFetcher` uses the Aena employment list, detail pages, and linked PDFs. `AenaParser.parse_list` applies title rejection and a hard expiration check before detail downloads. Absolute rejection patterns always drop a title; relative rejection patterns drop it unless an IT keyword overrides them. Detail extraction selects links whose text or title suggests bases or requirements. PDFs are written to unique temporary paths and cleaned up. If a detail page or individual PDF fails, the parser can return a fallback block containing the title and closing date.

## FULP

`FulpFetcher` reads the public listing at [`fulp.es/ofertas`](https://www.fulp.es/ofertas) and public detail paths of the form `/ofertas/<numeric-id>/<slug>`. It upgrades the exact official host to HTTPS, removes recognised tracking parameters, rejects credentials, private hosts, unsafe ports, path traversal, unsupported paths, and non-detail redirects, and validates every redirect target before scheduling another request. Relative `Location` values are resolved against the current validated request URL; a fetchable trailing slash may be preserved even though canonical identity normalisation removes it. It does not enable automatic requests redirects. One logical scan begins with a fresh budget and schedules at most 200 HTTP attempts within 180 seconds; the scheduling deadline prevents new requests but does not cancel a request already in flight. There is no retry policy.

`FulpParser` first parses one current listing response, records the advertised total when it can be reconciled, counts malformed and duplicate rows, and deduplicates by numeric offer ID before serial detail retrieval. It treats discovery completeness and detail completeness as separate states. Unsupported pagination or continuation evidence is reported and not followed. A failed detail is isolated with a diagnostic; a budget stop records the unattempted IDs. The parser does not invoke the shared early title-rejection heuristic, so relevant ordinary employment, university internship, Programa Inserta Universitario, and Programa Inserta FP Superior offers remain eligible for the shared IT/employment filter.

Listing extraction is bounded to `.panel_ofertas` and top-level `.row.oferta` cards; nested cards, links, and fields cannot establish a foreign identity or contaminate the outer record. Detail extraction is bounded to the owning top-level `.Content-Oferta`; nested roots cannot supply identity or content. It uses owned `h3`/`h2.titulo`, `h5`, `.container-details`, `.Descripcion`, `.Tareas`, `.Perfil`, and `.Requisitos` content, excludes actual controls/sharing/footer/policy boilerplate while retaining ordinary offer links and role text, preserves unlabeled summary values, and uses the neutral employer value `Empresa no identificada` when no employer is published. Listing type comes from owned `.tipo` badges, while contract badges remain separate; conflicting owned types are diagnosed. Detail identity is taken from a validated canonical or `og:url` value and cross-checked against the requested/listing/response numeric ID. Offline details without that identity are quarantined; offline listing snapshots are explicitly listing-evidence-only and do not fetch details. Findings retain the evidenced employer as `detected_organism` while keeping `source=FULP`; locality recognition does not infer a place from company text.

`target_date` is used only to evaluate explicit application-deadline evidence in the current HTML. Publication dates are metadata, not deadlines; closure words in qualifications or duties are not offer status, and an interval uses its closing date. Closed, expired, conflicting, invalid, or ambiguous availability is not silently converted into an open offer. The normalized output places bounded, source-backed requirements, description, tasks, and profile sentence units early, then appends each section's continuation. Allocation stops before the next complete unit would exceed that section's budget, so words and multiword eligibility or role phrases are not split by unrelated labels. This is deterministic ordering, not summarization, and evidence beyond the validator window remains unavailable to AI. No geographic or personal-fit restriction is added and no persistent cross-run deduplication is introduced.

## Operational caveats

All seven portals are external SSR websites whose markup and availability can change. The local tests use fixtures and injected mock fetchers. They establish parser behaviour for covered HTML, dates, and errors; they do not prove that any live portal remains reachable or unchanged. The GSC implementation does not add pagination or load-more retrieval; the inspected snapshot had no pagination controls, and a generic `infinitescroll.min.js` include is not evidence of additional records. A historical GSC target date filters the current page response and does not reconstruct historical website state. Repeated scans within the same inferred window can produce repeated findings or notifications because no persistent cross-run deduplication is introduced. FULP likewise has no persistent cross-run deduplication, and its current-page discovery, detail failures, 200-attempt/180-second scheduling guard, and source markup are not deployment guarantees. The implementation's bounded read-only FULP check on 2026-09-16 used one public listing response and six distinct detail URLs; it did not follow private/application links, invoke AI, send notifications, or deploy. Indra has no persistent cross-run deduplication either: IDs are deduplicated within one scan before detail fetching and AI only. A 2026-09-15 read-only Indra discovery check reached the portal but was incomplete after 31 pages, 763 genuine rows, 733 unique IDs, contradictory totals, and a repeated-page diagnostic. That observation does not establish that the portal itself repeated the page: client-side navigation and identity handling can generate the diagnostic, so the historical counts remain observations rather than a causal explanation. A separate bounded discovery-only check after the repair parsed 30 pages, discovered 732 unique IDs, and reported complete coverage at that moment; it did not fetch the detail pages. It sampled three detail pages and made no AI calls. These are source-runtime observations, not a deployment or Lambda validation.
