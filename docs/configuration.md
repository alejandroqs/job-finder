# Configuration reference

Purpose: document the inputs that select sources, dates, filtering, AI validation, exports, and notifications.

Read when: changing CLI options, Lambda events, environment variables, YAML configuration, or prompt behaviour.

Source of truth: [`main.py`](../src/job_finder/main.py), [`.env.example`](../.env.example), [`keywords.yaml`](../src/job_finder/keywords.yaml), [`config_prompts.yaml`](../src/job_finder/config_prompts.yaml), [`keyword_filter.py`](../src/job_finder/keyword_filter.py), [`gemini_validator.py`](../src/job_finder/gemini_validator.py), and [`notifier.py`](../src/job_finder/notifier.py).

## CLI options

`python -m job_finder.main` accepts:

| Option | Values/default | Effect |
| --- | --- | --- |
| `--date` | `YYYY-MM-DD`, omitted by default | Scans the supplied target date. Mutually exclusive with `--file`. |
| `--file` | local path, omitted by default | Parses an offline PDF, XML/RSS, HTML, CSV, or JSON file and auto-detects the source. Mutually exclusive with `--date`. |
| `--source`, `-s` | one of `BOP`, `BOC`, `BOE`, `SAGULPA`, `GUAGUAS`, `AENA`, `EPSO`, `EURES`, `EULISA`, `EU`, `ES`, `ALL`; default `ALL` | Selects individual sources or a group. |
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

Missing or non-dictionary input defaults to all sources and AI enabled. Lambda always passes `target_date=None`, so the resolved date is the current date. The source grouping rules are the same as the CLI, including `ES` and `EU`.

Source selection is branch-based in `run_scan`: `ALL` takes precedence, then `EU`, then `ES`, and only otherwise is the supplied list used as individual sources. A Lambda event containing both `EU` and `ES` therefore runs `EU` and ignores the `ES` branch; the groups are not merged. The CLI supplies one `--source` value at a time.

The `ES` group contains six sources, including Guaguas Municipales; `EU` remains the three-source European group; `ALL` contains nine sources. Guaguas always evaluates its inclusive application interval against the resolved execution date in online scans, including a CLI run without `--date`.

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

[`keywords.yaml`](../src/job_finder/keywords.yaml) supplies Spanish IT patterns, employment anchors, boilerplate exclusions, and absolute or relative title-rejection patterns. Matching strips accents and is case-insensitive. Dedicated EU sources use the English patterns defined in [`KeywordFilter`](../src/job_finder/keyword_filter.py).

[`config_prompts.yaml`](../src/job_finder/config_prompts.yaml) supplies the system prompt and user prompt template for Gemini. The validator inserts a JSON job list into the template and expects a structured response matching its Pydantic schema. Prompt changes can alter filtering outcomes and should be reviewed as behaviour changes.
