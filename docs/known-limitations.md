# Known limitations and documentation risks

Purpose: record material uncertainty so agents do not mistake a design intention or a mocked test for a production guarantee.

Read when: a task depends on deployment, a live portal, optional tooling, or a claim inherited from older documentation.

Source of truth: current source, configuration, tests, and workflow files. Entries are static observations and should be revisited when the referenced code changes.

## Current observations

| Area | Observation | Consequence |
| --- | --- | --- |
| EURES | `EURESFetcher` imports Playwright lazily, but Playwright is not listed in `requirements.txt` or `pyproject.toml`. | A live EURES scan requires an additional environment setup step that packaging metadata does not declare. |
| Gemini retries | `_validate_chunk` retries up to three times and sleeps 60 seconds for 429 or 10 seconds for 503, with a shorter fixed delay for other errors. | Document the actual delays; do not call this exponential backoff. |
| Local `--no-ai` | The flag skips Gemini validation only. `main()` still calls `send_notifications` when findings exist. | Disabling AI does not make a run side-effect free. |
| Lambda output | `lambda_handler` sends configured notifications and returns a status object; it does not persist the findings report through the CLI exporters. | Operational documentation must distinguish Lambda notifications from local report files. |
| External services | Most tests use local fixtures and mocked HTTP or SDK calls. | A passing test suite does not validate current portal, API, credential, browser, or AWS availability. |
| Deployment | `.github/workflows/deploy.yml` builds in the AWS SAM Python 3.14 image, uploads to S3, updates the function, waits, and invokes the production function after qualifying pushes. | Documentation must treat a push to the configured branch as an operational action. |
| Dependency policy | `AGENTS.md` requires exact requirement pins, while `requirements.txt` currently uses `python-dotenv>=1.2.2`. | This is a policy/configuration mismatch; documentation should expose it rather than imply compliance. |
| Index evidence | The codebase-memory index is useful for discovery but may report stale metadata or partial parsing. | Agents must verify material conclusions against source and coverage status. |

## How to report a new limitation

Record the affected path, the observed behaviour, the evidence type, and the practical consequence. Do not speculate about an external system without a check. Remove or revise an entry when the implementation and relevant verification demonstrate that it no longer applies.
