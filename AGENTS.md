# Agent handbook

This repository contains `job-finder`, a Python CLI and AWS Lambda job monitor. The primary audience for this file is coding agents. Human-oriented project information remains in [README.md](README.md).

## Read the smallest useful context

Start with this file, then follow the route that matches the task:

| Task | Read next |
| --- | --- |
| Understand the system or its execution path | [docs/architecture.md](docs/architecture.md) |
| Run the CLI or configure Lambda | [docs/configuration.md](docs/configuration.md), [docs/workflows/local-development.md](docs/workflows/local-development.md), [docs/workflows/lambda-operations.md](docs/workflows/lambda-operations.md) |
| Investigate a source | [docs/sources/index.md](docs/sources/index.md), then the relevant family document |
| Change filtering, prompts, or notifications | [docs/configuration.md](docs/configuration.md), [docs/architecture.md](docs/architecture.md) |
| Add or remove a source | [docs/workflows/adding-a-source.md](docs/workflows/adding-a-source.md) |
| Change tests or fixtures | [docs/testing.md](docs/testing.md) |
| Update documentation after a code change | [docs/maintenance.md](docs/maintenance.md) |
| Check a documented uncertainty | [docs/known-limitations.md](docs/known-limitations.md) |

Read source code as the authority for implemented behaviour. The documentation describes the current repository and must not silently turn historical comments, tests with mocks, or external assumptions into guarantees.

## Repository and shell rules

- The repository is Python with a `src/job_finder` package and a `tests` suite.
- The supported local shell is Windows PowerShell. Use PowerShell commands and run Python modules with `python -m ...`.
- Preserve user-owned changes. Inspect `git status --short` and the relevant diff before editing. Do not reset, revert, stage, commit, push, or delete unrelated work.
- Use `apply_patch` for source edits. Keep changes within the requested scope.
- Do not read, print, or copy secrets from `.env`. Use `.env.example` and environment-variable names in source when documenting configuration.
- Do not invoke production services, send notifications, deploy Lambda, or modify external systems unless the task explicitly authorizes it.
- Use the repository's actual paths and symbols. Do not invent modules, commands, URLs, environment variables, or guarantees.

## Lambda packaging constraints

- Treat `requirements.txt` as the deployment dependency manifest. Its versions are expected to use exact `==` pins; if the file violates that policy, record the mismatch rather than describing it as compliant.
- Build Lambda packages inside the official `public.ecr.aws/sam/build-python3.14` image. Do not create deployment ZIPs with Windows-native archive tools or a generic Linux image.
- Lambda can write only to `/tmp`. Route temporary downloads there and clean them up when the implementation provides a cleanup path.
- Read [docs/workflows/lambda-operations.md](docs/workflows/lambda-operations.md) before changing packaging, deployment, runtime, or scheduled execution documentation.

## Investigation and codebase memory

The repository is indexed by `codebase-memory-mcp` as `C-Users-muk04-Development-Python-job-finder`. For non-trivial structural questions, use the `codebase-memory-project` workflow:

1. Confirm the project and index status.
2. Use a focused architecture, symbol, or relationship query.
3. Inspect the exact source implementation supporting the conclusion.
4. Check index coverage for the relevant paths. Treat the graph as discovery evidence, not as a substitute for source.
5. Report meaningful gaps, stale metadata, partial parsing, or external behaviour that was not tested.

Use direct search and file reads for Markdown, YAML, fixtures, exact text, and any path or range the graph reports as incomplete. Do not re-index or delete graph projects as routine investigation.

## Verification language

Distinguish these evidence levels in plans and reports:

- **Implemented:** visible in the current source or configuration.
- **Source-tested:** exercised by a local test or fixture.
- **Runtime-tested:** exercised against a real local or external runtime.
- **Documented policy:** required by this handbook or an explicit user request.
- **Unverified:** plausible or described by a comment, but not demonstrated by the available evidence.

Do not claim that a portal works, a Lambda deployment succeeded, a notification was delivered, or an index is complete unless that check actually ran.

## Documentation maintenance

When code, configuration, deployment, source contracts, commands, or operational assumptions change, update the affected document according to [docs/maintenance.md](docs/maintenance.md). Update this file only when global agent rules, routing, or repository constraints change. A task does not require a documentation edit when its documented contract is unchanged; state that decision in the task report when useful.

All documentation in this repository is written in English. Keep `AGENTS.md` concise and route detailed domain knowledge to `docs/`. Keep the README useful to human users rather than duplicating every agent instruction.

## Scope discipline

Before implementing a non-trivial change, identify the entry point, affected interfaces, callers or consumers, tests, configuration, and operational effects. Prefer a bounded plan. After editing, review the diff and run the relevant checks; report checks that could not be run.
