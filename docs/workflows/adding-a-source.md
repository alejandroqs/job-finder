# Adding a source

Purpose: provide a bounded checklist for adding another job source without bypassing the existing contracts.

Read when: introducing a new portal, feed, API, or bulletin.

Source of truth: [`interfaces.py`](../../src/job_finder/interfaces.py), [`main.py`](../../src/job_finder/main.py), existing source families, and the test suite under [`tests`](../../tests/).

## Implementation sequence

1. Classify the source as a gazette, web board, or European feed and identify its raw format, publication/deadline semantics, and external failure modes.
2. Choose the matching abstract interface in `interfaces.py`. Keep fetching separate from parsing.
3. Implement a fetcher with explicit timeout, response/error handling, and no secrets in source.
4. Implement a parser that normalizes records into `BOPage` with a stable source label, text, organism, page/item number, and URL.
5. Decide whether the common Spanish or EU keyword path is correct. Add source-specific configuration only when it cannot be expressed by existing rules.
6. Add the source to `_scan_single_source`, source selection groups, CLI choices, and local-file detection if offline parsing is supported.
7. Add deterministic fixtures and tests for normal extraction, filtering, dates, malformed/empty input, and expected failure fallbacks.
8. Update `docs/sources/index.md`, the relevant family document, `configuration.md`, `architecture.md`, and `README.md` if the human usage surface changes.
9. Update `known-limitations.md` for optional dependencies or unverified live behaviour.
10. Run the focused tests and the full suite where practical, then review the diff and document unrun external checks.

## Acceptance questions

- Can an agent identify the source's fetcher, parser, input fixture, and test from the source index?
- Does the parser produce the same domain model used by existing filters and exporters?
- Is the date rule explicit and tested at its boundary?
- Is a temporary file path safe for Lambda if binary data is involved?
- Does a live failure degrade in the same controlled way as neighbouring sources?
- Are external dependencies and production side effects visible in the documentation?
