# Known limitations and documentation risks

Purpose: record material uncertainty so agents do not mistake a design intention or a mocked test for a production guarantee.

Read when: a task depends on deployment, a live portal, optional tooling, or a claim inherited from older documentation.

Source of truth: current source, configuration, tests, and workflow files. Entries are static observations and should be revisited when the referenced code changes.

## Current observations

| Area | Observation | Consequence |
| --- | --- | --- |
| EURES | `EURESFetcher` imports Playwright lazily, but Playwright is not listed in `requirements.txt` or `pyproject.toml`. | A live EURES scan requires an additional environment setup step that packaging metadata does not declare. |
| EURES dates | `EURESParser.parse_raw` accepts `target_date` but does not use it to filter vacancies. | Lambda passes the execution date, but EURES results can include records that would be excluded by the date-aware EPSO and eu-LISA parsers. |
| Gemini retries | [`GeminiValidator._validate_chunk`](../src/job_finder/gemini_validator.py) makes up to three total attempts (at most two retries). Each 429 failure sleeps 60 seconds and each 503 failure sleeps 10 seconds, including after the final attempt. Other errors sleep 2 seconds only when another attempt remains. | These are fixed delays, not exponential backoff. Three 429 failures add 180 seconds of sleep per chunk, excluding request and scan time; include this path when sizing Lambda timeouts. |
| Local `--no-ai` | The flag skips Gemini validation only. `main()` still calls `send_notifications` when findings exist. | Disabling AI does not make a run side-effect free. |
| Lambda output | `lambda_handler` sends configured notifications and returns a status object; it does not persist the findings report through the CLI exporters. | Operational documentation must distinguish Lambda notifications from local report files. |
| External services | Most tests use local fixtures and mocked HTTP or SDK calls. | A passing test suite does not validate current portal, API, credential, browser, or AWS availability. |
| Guaguas document scope | The integration preserves the bases URL but does not download bases PDFs or include the `Avisos` history in normalized text. | An IT role mentioned only inside a bases PDF can be missed, and a deadline extension published only in an aviso is not interpreted automatically. |
| Guaguas historical dates | A historical target date is applied to the Guaguas HTML currently available at scan time. | The scanner cannot reconstruct what the portal displayed on that historical date. |
| GEURSA section inclusion | GEURSA includes every process under the current page's `Convocatorias en vigor` section, regardless of its application deadline. | Section membership is not evidence that applications remain open; past, future, and missing deadline wording is retained as information. |
| GEURSA historical dates | GEURSA accepts `target_date` for shared interface compatibility but does not use it to filter records or retrieve historical page state. | Supplying a historical date does not reproduce the website as it appeared then. |
| GEURSA HTML scope | GEURSA extraction is HTML-only and does not inspect requirements or IT roles found only in Bases or other linked PDFs. | A relevant role present only in an attachment can be missed. Attachment captions are kept out of normalized filter text. |
| GEURSA live fetch | A separate read-only check fetched one live response through `GeursaFetcher` on 2026-09-09, parsed one active card, and found zero IT matches; it did not invoke AI, notifications, or attachment downloads. | This is a single runtime observation, not a guarantee of future reachability, complete portal coverage, or unchanged markup. |
| GSC HTML scope | `GSCParser` reads only direct articles under the owned `.projects_holder.portfolio_main_holder` inside `#seleccion` and uses only the owned title heading/anchor. It does not inspect detail pages, PDFs, attachment captions, category text, or unrelated holders. | IT requirements, status changes, or application information visible only outside the title can be missed. |
| GSC date heuristic | GSC inclusion uses the leading publication date through publication plus seven calendar days, with inclusive boundaries. The inferred end date is a user-defined monitoring heuristic, not an official application deadline. | A listing can be monitored after an official deadline or excluded before an official process ends; detail/PDF deadlines were not inspected. |
| GSC historical dates | A historical target date is applied to the current GSC HTML response. | The scanner cannot reconstruct what the portal displayed on that historical date. |
| GSC pagination | The implementation scans all direct cards in the bounded holder but adds no pagination or load-more retrieval. The inspected snapshot had no pagination controls; a generic `infinitescroll.min.js` include was not treated as proof of more records. | Future markup that hides records behind pagination or client-side loading may be missed until separately supported. |
| GSC repeated scans | No persistent cross-run deduplication has been introduced for GSC. | Repeated scans within the inferred window can repeat findings or notifications. |
| GSC live verification | The implementation run used synthetic fixtures and did not establish a new live GSC runtime check. | Fixture tests do not prove current reachability, browser parity, official application status, future availability, or completeness of the external archive. |
| Deployment | `.github/workflows/deploy.yml` builds in the AWS SAM Python 3.14 image, uploads to S3, updates the function, waits, and invokes the production function after qualifying pushes. | Documentation must treat a push to the configured branch as an operational action. |
| Dependency policy | `AGENTS.md` requires exact requirement pins, while `requirements.txt` currently uses `python-dotenv>=1.2.2`. | This is a policy/configuration mismatch; documentation should expose it rather than imply compliance. |
| Index evidence | The codebase-memory index is useful for discovery but may report stale metadata or partial parsing. | Agents must verify material conclusions against source and coverage status. |

## How to report a new limitation

Record the affected path, the observed behaviour, the evidence type, and the practical consequence. Do not speculate about an external system without a check. Remove or revise an entry when the implementation and relevant verification demonstrate that it no longer applies.
