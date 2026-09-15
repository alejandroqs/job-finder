# Indra fixture provenance

`indra_search_page.html`, `indra_detail_remote.html`, and
`indra_detail_flexible.html` are reduced, deterministic fixtures based on the
server-rendered structures observed in the Indra Group careers portal on
2026-09-15. The selectors, duplicate desktop/mobile title anchors, labelled
detail fields, `.jobdescription`, canonical URL, Unicode text, and pagination
shape are retained; the displayed dates, totals, titles, and numeric IDs are
fixture data and are not live assertions.

`indra_detail_observed_sections.html` retains the observed description-section
shape, including formatted paragraphs, punctuation/emoji headings, bounded
benefits and recruitment sections, and a nested `.job` record. Its section
headings are source-derived; its job wording, title, location, and numeric ID
are synthetic so the fixture does not claim to reproduce either live vacancy.

The parser tests also generate synthetic responses for malformed links,
nested rows, empty and missing tables, repeated pages, changing page sizes,
contradictory totals, retrieval failures, category/detail URL variants, and
geographic edge cases. Those synthetic cases are deliberately separate from
the reduced observed-layout fixtures.
