# Documentation maintenance

Purpose: keep agent context accurate without turning `AGENTS.md` into a second README or a history dump.

Read when: code, configuration, source contracts, deployment, commands, or operational assumptions change.

Source of truth: the current repository, especially [`AGENTS.md`](../AGENTS.md), [`src/job_finder`](../src/job_finder/), [`tests`](../tests/), and [`.github/workflows`](../.github/workflows/). This procedure is policy for maintaining the documents below.

## Update procedure

1. Inspect `git status --short` and preserve unrelated user changes.
2. Identify the changed contract and its owning document from the table below.
3. Read the implementation, relevant tests, configuration, and workflow before editing prose.
4. Update the owning document and any index or cross-reference that became stale.
5. Mark unresolved behaviour in `known-limitations.md` with evidence and practical impact.
6. Check local links, referenced paths, symbols, commands, and examples.
7. Review the diff and report what was updated and what was not verified.

## Ownership map

| Change | Primary document(s) |
| --- | --- |
| CLI arguments, source groups, Lambda event, environment variables | `configuration.md` |
| Main orchestration, shared models, filtering, AI, exports, notifications | `architecture.md` |
| BOP, BOC, or BOE | `sources/spanish-gazettes.md` and `sources/index.md` |
| Sagulpa, Guaguas, or Aena | `sources/corporate-boards.md` and `sources/index.md` |
| EPSO, EURES, or eu-LISA | `sources/european-sources.md` and `sources/index.md` |
| Tests or fixtures | `testing.md` |
| Local commands or packaging | `workflows/local-development.md` |
| Lambda packaging, workflow, runtime, or notifications | `workflows/lambda-operations.md` |
| New source integration | `workflows/adding-a-source.md` |
| Agent routing or global repository constraints | `AGENTS.md` and `index.md` |

## Writing rules

- Write documentation in English.
- State implemented behaviour separately from policy and unverified external behaviour.
- Link to stable paths and symbols instead of copying large code blocks or volatile line numbers.
- Describe current code, even when a comment or older README says something else; record material contradictions as limitations.
- Avoid unsupported guarantees, fixed test totals, performance percentages, and claims of successful external operation.
- Keep one canonical explanation for each rule and link to it elsewhere.

## Completion check

Before closing a documentation task, confirm that the changed files are documentation-only unless a code change was explicitly requested, local links resolve, all source families remain represented, `AGENTS.md` still routes agents correctly, and any test or runtime checks are labelled accurately.
