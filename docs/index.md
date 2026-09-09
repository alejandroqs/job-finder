# Agent documentation index

Purpose: route agents to the smallest set of project context needed for a task.

Read when: entering the repository, choosing a task-specific document, or checking whether a document belongs in this system.

Source of truth: the current source under [`src/job_finder`](../src/job_finder/), tests and fixtures under [`tests`](../tests/), deployment configuration under [`.github`](../.github/), and the explicit policies in [`AGENTS.md`](../AGENTS.md).

## Task routes

| If you need to... | Read |
| --- | --- |
| Understand the end-to-end flow | [architecture.md](architecture.md) |
| Change CLI, Lambda, environment, YAML, or prompt configuration | [configuration.md](configuration.md) |
| Work on BOP, BOC, or BOE | [sources/spanish-gazettes.md](sources/spanish-gazettes.md) |
| Work on Sagulpa, Guaguas, or Aena | [sources/corporate-boards.md](sources/corporate-boards.md) |
| Work on EPSO, EURES, or eu-LISA | [sources/european-sources.md](sources/european-sources.md) |
| Run or extend local checks | [testing.md](testing.md) and [workflows/local-development.md](workflows/local-development.md) |
| Operate or change scheduled Lambda execution | [workflows/lambda-operations.md](workflows/lambda-operations.md) |
| Add another source | [workflows/adding-a-source.md](workflows/adding-a-source.md) |
| Keep docs synchronized | [maintenance.md](maintenance.md) |
| Understand uncertainty or drift | [known-limitations.md](known-limitations.md) |

## Document boundaries

`AGENTS.md` contains mandatory agent rules and navigation. This directory contains detailed project knowledge. `README.md` is the human-facing introduction and usage guide. Source files, tests, and deployment configuration remain authoritative when these documents disagree.

## Source families

See [sources/index.md](sources/index.md) for the complete source inventory and the mapping from each source to its fetcher, parser, and tests.
