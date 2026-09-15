# Configuration reference

Purpose: document the inputs that select sources, dates, filtering, AI validation, exports, and notifications.

Read when: changing CLI options, Lambda events, environment variables, YAML configuration, or prompt behaviour.

Source of truth: [`main.py`](../src/job_finder/main.py), [`.env.example`](../.env.example), [`keywords.yaml`](../src/job_finder/keywords.yaml), [`config_prompts.yaml`](../src/job_finder/config_prompts.yaml), [`keyword_filter.py`](../src/job_finder/keyword_filter.py), [`gemini_validator.py`](../src/job_finder/gemini_validator.py), and [`notifier.py`](../src/job_finder/notifier.py).

## CLI options

`python -m job_finder.main` accepts:

| Option | Values/default | Effect |
| --- | --- | --- |
| `--date` | `YYYY-MM-DD`, omitted by default | Scans the supplied target date. Mutually exclusive with `--file`. |
| `--file` | local path, omitted by default | Parses an offline PDF, XML/RSS, HTML, CSV, or JSON file and auto-detects the source. Mutually exclusive with `--date`. Indra routing accepts a bounded detail signature or an explicitly named `indra` file, while detail parsing still requires a reliable official identity; listing snapshots do not infer missing modality. |
| `--source`, `-s` | one of `BOP`, `BOC`, `BOE`, `SAGULPA`, `GUAGUAS`, `GEURSA`, `GSC`, `AENA`, `INDRA`, `EPSO`, `EURES`, `EULISA`, `EU`, `ES`, `ALL`; default `ALL` | Selects individual sources or a group. |
| `--config` | optional path | Replaces the default `src/job_finder/keywords.yaml`. |
| `--no-ai` | false by default | Skips the Gemini validation stage. It does not disable fetching, exports, or notifications. |
| `--output` | `findings.md` | Destination overwritten by the selected exporter. |
| `--format` | `markdown` or `html`; default `markdown` | Selects the exporter. An `.html` output suffix overrides the format. |

The CLI exits with status `0` when it has findings and `1` when it has none. This behaviour is implemented in `main.py` and may matter to schedulers.

## Lambda event

`lambda_handler(event, context)` reads two optional keys from a dictionary:

```json
{"sources": ["ALL"], "no_ai": false}
```

Missing or non-dictionary input defaults to all sources and AI enabled. Lambda always passes `target_date=None`, so the resolved date is the current date. The source grouping rules are the same as the CLI, including `ES` and `EU`. GEURSA accepts the resolved date for the shared fetch/parse interface but does not use it to select cards. GSC applies the resolved date to its current list using its synthetic publication-plus-seven-day window.

Source selection is branch-based in `run_scan`: `ALL` takes precedence, then `EU`, then `ES`, and only otherwise is the supplied list used as individual sources. A Lambda event containing both `EU` and `ES` therefore runs `EU` and ignores the `ES` branch; the groups are not merged. The CLI supplies one `--source` value at a time.

The `ES` group contains nine sources, including Guaguas Municipales, GEURSA, GSC, and Indra Group; `EU` remains the three-source European group; `ALL` contains twelve sources. Indra's inclusion in `ES` is a grouping convention, not a country filter. Guaguas always evaluates its inclusive application interval against the resolved execution date in online scans, including a CLI run without `--date`. GEURSA includes every process under the website's `Convocatorias en vigor` heading regardless of its application deadline, and a historical target date does not retrieve historical page state. GSC uses the current `#seleccion` list, skips administrative/cancelled notices and invalid or missing leading dates, and does not treat its inferred end date as an official deadline.

For offline GSC HTML, `.html` and `.htm` files are routed by a bounded `gsc` filename token or the parser's structural `#seleccion` plus holder signature; unknown-extension HTML signatures use the same structural recognition. A programmatic `run_scan(local_file=..., target_date=...)` passes that date to GSC; otherwise local GSC parsing uses `date.today()`. Future scheduled `ALL`/default and `ES` scans will include GSC and Indra after deployment. `EU` and explicit selections of other individual sources will not. No schedule change is required or performed by this integration. Because no persistent cross-run deduplication exists, repeated scans during the same GSC or Indra run window can repeat findings and notifications.

## Environment variables

`.env.example` contains the application secrets and notification placeholders. The code also reads the Lambda runtime marker below:

| Variable | Used by | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | `GeminiValidator` | Enables Gemini validation when the SDK is available and the key initializes a client. |
| `DISCORD_WEBHOOK_URL` | `notifier.py` | Enables Discord notifications. |
| `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` | `notifier.py` | Enable Telegram notifications when both are present. |
| `AWS_LAMBDA_FUNCTION_NAME` | `main.py` | Selects `/tmp` as the temporary directory base. |

Do not commit real values. `python-dotenv` is loaded opportunistically by the local CLI; Lambda configuration is supplied by the runtime environment.

## YAML configuration

[`keywords.yaml`](../src/job_finder/keywords.yaml) supplies general-source IT patterns, employment anchors, boilerplate exclusions, and absolute or relative title-rejection patterns. Matching strips accents and is case-insensitive. Patterns include Spanish and English corporate roles and selected Portuguese cybersecurity terms. Cybersecurity coverage includes operations, engineering, offensive security, identity/access management and information-security governance, risk and compliance. Dedicated EU sources use the separate English patterns defined in [`KeywordFilter`](../src/job_finder/keyword_filter.py); expanding this YAML does not expand their initial filtering.

`portal_search_keywords` is an independent, discovery-only list consumed by
Indra. A missing key or empty list performs one blank full-catalogue search.
Non-empty values are trimmed, blank entries are discarded, exact duplicates are
removed in order, and one exact portal query is run per remaining value. The
list must contain only strings. It does not expand `it_keywords`, does not
change include/exclude regex behaviour, does not append query text to candidate
descriptions or matched keywords, and does not change the Gemini prompt. A
non-empty list deliberately narrows discovery and cannot claim complete
catalogue coverage.

[`config_prompts.yaml`](../src/job_finder/config_prompts.yaml) supplies the system prompt and user prompt template for Gemini. The validator inserts a JSON job list into the template and expects a structured response matching its Pydantic schema. Prompt changes can alter filtering outcomes and should be reviewed as behaviour changes.

The general path requires an IT keyword after boilerplate removal and an
employment anchor in the paragraph. Anchors include corporate requirements
and responsibilities as well as public recruitment terms. Exclusions remove
incidental computer-skills phrases, not entire candidates. Broad anchors can
admit non-vacancy text; keyword matching alone does not establish relevance.
Matching operates per paragraph, so an advert with separate matching summary
and detail paragraphs can produce multiple results (as in the Sagulpa fixture).

Gemini receives at most the first 1,500 characters of the normalized paragraph.
The prompt covers public and private employment, including cybersecurity roles
without coding or data/AI duties. It distinguishes cyber work from physical
security and unrelated compliance, treats source instructions as untrusted,
and retains plausible ambiguous recruitment with low confidence. It does not
establish international contractual eligibility or personal suitability.
These are prompt instructions, not guarantees of live model behaviour.
