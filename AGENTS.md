# Agent Instruction Handbook — Job Finder

This document is designed for AI coding assistants and agents working on this codebase in the future. It outlines environment constraints, architectural patterns, and domain-specific knowledge to ensure safe and efficient continuation of work.

> [!IMPORTANT]
> **Continuous Knowledge Updates**: Every agent/assistant working on this repository MUST update this `AGENTS.md` file after completing a task to capture any newly discovered environment quirks, domain knowledge, website URL changes, or coding insights. Keep this handbook evergreen!

---

## 💻 Environment & Terminal Guidelines

> [!IMPORTANT]
> The active operating system is **Windows**, and the shell environment is strictly **PowerShell**. 

To prevent execution failures, always adhere to the following command rules:
1. **Never use standard Unix/bash commands** (e.g. `export`, `grep`, `cat`, `rm -rf`, `chmod`) or cmd-style path conventions unless explicitly supported.
2. **Execute Python modules as scripts**: When running commands like `pytest` or CLI tools, always run them using `python -m <module>` (e.g. `python -m pytest` or `python -m job_finder.main`) to ensure that Windows system PATH discrepancies do not cause "CommandNotFoundException" errors.
3. **Handle terminal encoding explicitly**: Windows PowerShell environments default to regional encodings (like `cp1252`), which fail to encode box-drawing or special Spanish characters. Ensure any CLI printed borders are wrapped in try-catch encoding blocks (such as `sys.stdout.reconfigure(encoding='utf-8')`).
4. **Module Renaming & Package Root**: The project has been fully renamed from `bop_finder` to `job_finder`. All core imports, test scripts, and CLI definitions inside `pyproject.toml` reference `job_finder`. Keep any source-specific terminology localized to their modules (e.g., `BOPFetcher` should retain "BOP" as it refers specifically to the Las Palmas BOP gazette).
5. **File Searching & Manipulation**: The default Windows environment lacks `grep`. The `grep_search` tool may fail due to PATH issues. For robust searching, use PowerShell's `Get-ChildItem -Recurse -Include *.py | Select-String "pattern"`. For bulk multi-file string replacements, writing and executing a temporary Python script in the `scratch` directory is highly recommended over PowerShell regex replacements.

---

## 🤖 Execution Checkpoints & Model Selection

> [!IMPORTANT]
> **Task Complexity & Model Switching Rules**:
> 1. If you consider that any upcoming task in the task checklist is **complex**, you must **stop execution immediately** and wait for user feedback. The user will switch the agent to a more complex model (e.g., Gemini 3.5 Flash High/Pro).
> 2. After completing a complex task, if the next task is **simple**, you must also **stop execution and await user feedback** so they can downgrade the model back to a simple/medium one and type "proceed" to continue.
> 3. **Rule Reference**: "IMPORTANT: If you consider that one task in the task list is complex, stop execution and await for my feedback. I will change the model to a complex one. After the task, if the next task is simple, await for me to change again the model and write 'proceed'."

---

## 🗺️ Domain Insights: BOP Las Palmas

### 1. Daily PDF URL Structure
The BOP Las Palmas server (`www.boplaspalmas.net`) organizes PDF archives with a predictable pattern:
```
http://www.boplaspalmas.net/boletines/{YEAR}/{D-M-YY}/{D-M-YY}.pdf
```
* **Date rules**: The directory and file components use an unpadded `{day}-{month}-{2-digit-year}` format (e.g., `8-4-26` for April 8, 2026).
* **Weekend/Holidays**: The BOP does not publish on Saturdays, Sundays, or Spanish public holidays. In such cases, the server yields a `404 Not Found`.
* **Smart Fallback Scraping**: If a 404 occurs on a default current-date search, the system calls `fetch_latest()` to scrape the latest PDF link from `http://www.boplaspalmas.net/nbop2/main1.php` using the regex `boletines/(\d{4})/(\d+)-(\d+)-(\d+)/\2-\3-\4\.pdf` (which validates matched folder and file dates). On scrape failure, it programmatically probes backward day-by-day up to 7 days from today.

### 2. State-Sticky PDF Parsing
The gazette is parsed page-by-page using `pdfplumber` to control memory consumption.
* **Section filter**: We filter only pages residing within `III. ADMINISTRACIÓN LOCAL`.
* **Sticky Organism tracking**: Municipalities (organisms) are printed as prominent uppercase lines. Because an organism's announcement can span multiple pages, the parser implements a sticky state machine:
  ```python
  # Keeps track of the last seen municipality and applies it to subsequent pages
  current_organism = "Administración Local (Desconocido)"
  ```

### 3. Two-Step Noise Filtering Pipeline
Spanish public administration uses highly formal, non-English terminology. 
1. **Step 1 (IT Keywords)**: Scans paragraphs using accent-insensitive Spanish stems (e.g. `informátic`, `sistemas de redes`, `telecomunicaciones`). Both queries and targets must be accent-stripped via NFC-to-NFD decomposition to ensure robust matching.
2. **Step 2 (Contest Anchors)**: Since terms like "sistemas" are noisy (e.g., "sistemas de bases impositivas"), any matching paragraph must also contain civil service employment anchors (`plaza`, `bases`, `convocatoria`, `bolsa de empleo`) to pass the filter.

---

## 🗺️ Domain Insights: BOC (Boletín Oficial de Canarias)

### 1. XML RSS Feeds & Section Rules
The BOC provides section-specific RSS 2.0 feeds at `https://www.gobiernodecanarias.org/boc/feeds/`.
To scan local and regional jobs, the tool fetches three official feeds:
* **II.B (Oposiciones y concursos)**: Regional government jobs.
* **III (Otras Resoluciones)**: University job boards (ULPGC, ULL).
* **V (Otros anuncios)**: Mixed announcements (Ayuntamientos, Cabildos).

Because feed V contains unrelated entities, the parser extracts hierarchical tags from the `<description>` HTML content. It decodes HTML entities with `html.unescape()` and checks the header string inside the `<h5>` tag, which follows the pattern `Section - Subsection - Organism`:
* **II. Autoridades y Personal** is scanned only if the subsection is **Oposiciones y concursos**.
* **III. Otras Resoluciones** is scanned fully.
* **V. Anuncios** is scanned only if the subsection is **Administración Local**.

### 2. Standardized BOPage Interface
To unify parsing, the `BOCParser` converts RSS items into the common `BOPage` interface:
* `page_number` acts as a dummy index representing the sequential order of matching items.
* `text` is compiled by joining the parsed `<h3>` (resolution title) and `<p>` paragraphs.
* `detected_organism` is parsed from the last segment of the `<h5>` hierarchy.
* `source` is set to `"BOC"`.
* `url` is mapped directly from the `<link>` tag of each feed item for easy one-click access in the terminal output.

### 3. Smart Date fallbacks
Because RSS feeds cover multiple dates, if a default target date yields 0 matches, the `BOCFetcher.fetch_latest()` method scans all feeds, programmatically detects the most recent date present in the item list, and processes that date instead.

---

## 🗺️ Domain Insights: BOE (Boletín Oficial del Estado)

### 1. XML Open Data REST API & Required Headers
The BOE provides an official, high-quality daily sumario XML REST API:
```
https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}
```
* **Date format**: Strictly `YYYYMMDD` (e.g. `20260521`).
* **Headers**: The endpoint strictly requires the `Accept: application/xml` header. If missing, it returns a `400 Bad Request`.
* **Weekend/Holidays**: The BOE is not published on Sundays or national holidays, and returns `404 Not Found`.

### 2. Section II.B Parsing Hierarchy
We parse the XML using `xml.etree.ElementTree` and target only `<seccion codigo="2B">` (Oposiciones y concursos), which aggregates national-level, autonomous-community-level, local-government-level, and university-level job openings.
* **Organism mapping**: Extracted from `<departamento nombre="...">` attributes.
* **Epigraph/Sub-category extraction**: Items are often nested under `<epigrafe nombre="...">` tags. The parser uses a computed `parent_map` to retrieve the parent element and prefix the section path (e.g., `II.B. Oposiciones y concursos -> Personal funcionario. Oposiciones`).
* **Resolution links**: Extracted from `<url_html>` (with fallback to `<url_pdf>` if HTML representation is missing).

### 3. Standard Date Math Fallbacks
If the sumario API returns 404 for the current date, the fetcher calls `fetch_latest()`, which programmatically decrements a `datetime.date` object day-by-day (up to 7 days) via standard `timedelta` arithmetic. This naturally handles month boundaries and leap years without any manual date parsing logic.

### 4. Two-Tier Parsing Architecture & Concurrency
Relying solely on sumario titles was found to miss IT job opportunities masked behind generic administrative titles (e.g., *Libre Designación* or *Procesos selectivos*). We implemented:
* **Tier 1 Gatekeeper**: Quickly parses XML `<titulo>` strings. Uses case-insensitive regexes to immediately discard noise (e.g., Policía Local, Letrados, médicos) to save bandwidth, while scheduling all other Section II.B items (under mandatory triggers or golden fallback) for PDF scanning.
* **Tier 2 PDF deep-scan**: Downloads qualifying PDFs in parallel using a **`ThreadPoolExecutor`** capped at **5 concurrent workers** (ensuring polite server limits).
* **Robust Fallback**: If network or PDF parsing fails for any candidate, the worker gracefully falls back to XML title parsing, ensuring zero complete failures due to transient anomalies.

---

## 🗺️ Domain Insights: European Union Sources & Refinements

### 1. EPSO Ingestion (Hub Repository API & Dynamic Column Mapping)
* **API Ingest**: Target the official EU Data Portal Repository gateway:
  ```
  GET https://data.europa.eu/api/hub/repo/datasets/job-opportunities
  ```
* **Graph Distribution Schema**: The live API returns a JSON-LD `@graph` array rather than a simple CKAN package representation. The fetcher iterates through the `@graph` array, identifies items of type `dcat:Distribution`, and filters them for `CSV` format properties (`dct:format`) or URLs ending in `.csv` (extracting URLs from `dcat:downloadURL` or `dcat:accessURL` dictionaries).
* **Dynamic Column Mapping**: Live Open Data CSV columns change names and often contain trailing spaces (e.g. `Institution(s)    `, `Deadline `). The parser uses a robust, case-insensitive substring mapper to dynamically map original fields to required logical keys (`agency`, `title`, `location`, `contract`, `grade`, `deadline`, and `url`), ensuring absolute immunity to future columns adjustments.

### 2. EURES Anti-Scraping Bypass (XHR Response Interception)
* **Session & Anti-Bot Blocking**: EURES employs heavy Akamai bot-mitigation, CORS rules, and dynamically generated query `sessionId` parameters that cause standard POST fetches to yield 405 Method Not Allowed or 400 Bad Request.
* **XHR Interception Strategy**: Rather than fabricating manual POST requests, the fetcher runs headless Chromium, navigates directly to the EURES portal search URL (`https://europa.eu/eures/portal/jv-se/search?page=1&resultsPerPage=50&orderBy=BEST_MATCH`), and registers a response listener (`page.on("response")`). It listens for the page's natural background XHR query targeting `jv-search/search` and intercepts the clean 200 OK JSON text. This completely bypasses cookie/session management and anti-bot barriers since the browser natively manages them.

### 3. eu-LISA Multi-Strategy Table & List Crawling
* **Scraper Target**: Requests the live vacancies directory:
  ```
  https://www.eulisa.europa.eu/jobs/vacancies
  ```
* **Table & Link Selectors**: Implements Strategy A (parsing structural HTML table rows `<tr>` and cell dates `DD/MM/YYYY`) and Strategy B (extracting direct links to SharePoint e-recruitment paths or local vacancy details).
* **De-duplication**: To prevent duplicates, any Strategy B link originating inside a parsed table row `<tr>` is automatically bypassed.

### 4. ESCO IT Keyword Matcher & Spanish Exclusions
* **ESCO IT Regexes**: Uses 30 highly specific English IT keywords compiled with word boundaries (e.g. `\bDBA\b`, `\bSoftware Developer\b`) to scan EU vacancy text.
* **Direct Matching**: Dedicated EU portals contain only job vacancies (no mixed administrative regulations). If `is_eu` is detected, we bypass Spanish public contest anchors, guaranteeing direct matched announcements.
* **Spanish Boilerplate Exclusions**: Administrative submissions in Spanish bulletins often match `"informática"` due to submission boilerplate (e.g. *"Las solicitudes se presentarán mediante la aplicación informática..."*). We implemented a negative list of `boilerplate_exclusions` in [keywords.yaml](file:///c:/Users/muk04/Development/PyCharmProjects/job-finder/src/job_finder/keywords.yaml). The matching target paragraph has these phrases stripped *before* keyword scanning, completely eliminating false positives.

---

## 🗺️ Domain Insights: Gemini AI Validation Layer

### 1. Interface-Driven Architecture
To adhere strictly to Clean Architecture, the AI validation layer uses an interface-driven design:
* **`BaseAIValidator`** (defined in `src/job_finder/interfaces.py`) specifies the contract with the boolean property `enabled` and the abstract method `validate_batch(announcements)`.
* **`GeminiValidator`** (defined in `src/job_finder/gemini_validator.py`) is the concrete implementation. This separates the CLI execution logic in `main.py` from the specific LLM integration, allowing simple future swapping to other LLM providers (e.g. Claude, OpenAI, or a local model) without touching downstream filters or CLI arguments.

### 2. High-Performance Deduplication
To avoid unnecessary Google AI Studio API costs, the validator runs a deduplication step *before* initiating the HTTP request:
* Announcements are grouped by URL.
* A single representative announcement is selected for each unique URL.
* Verdicts returned by Gemini are mapped back to the full list: if a URL is marked `YES`, *all* matching candidate announcements sharing that URL are kept.

### 3. Graceful Fallback with Terminal Alerts
AI validation is designed as a non-breaking optional enhancement:
* If the `GEMINI_API_KEY` is missing (either in the environment or in the `.env` file loaded via `python-dotenv`), or if any HTTP error, network timeout, or JSON parsing error occurs, the system prints a prominent warning to `sys.stderr` (e.g., `⚠️ AI validation skipped: {reason}`).
* The full, unfiltered candidate list is returned to the execution thread, ensuring no search session crashes or fails due to remote API issues.
* Users can explicitly opt out of AI validation using the `--no-ai` CLI flag.

### 4. Low-Reasoning Prompt Strategy, Structured Outputs, and Context Inversion
To keep API latency and costs low, the validation layer is optimized for **Gemini Flash 3.5 (low reasoning)** using the official Google GenAI SDK:
* **API Specification**: Uses `client.models.generate_content(model="gemini-3.5-flash", ...)` under `google-genai>=1.0.0`.
* **Low Reasoning Mode**: Explicitly disables deep thinking by configuring `thinking_config=types.ThinkingConfig(thinking_level="low")` to force rapid, cost-effective evaluation. (Note: Avoid `thinking_budget=0` as it is deprecated and raises strict Pydantic extra-parameter rejections on modern SDKs).
* **Structured JSON Outputs**: Enforces deterministic, type-safe schema outputs by configuring `response_mime_type="application/json"` and mapping to a `JobOfferValidationBatch` Pydantic model, wrapping a list of `JobOfferValidationItem` matching input IDs (`id`, `is_tech_job`, `job_title`, `organism`, `confidence`, `reason`).
* **Context Inversion & Prompts Separation**: System and user template prompts are loaded externally from `src/job_finder/config_prompts.yaml`. The user template places the raw text payload at the top (`<context>`) and task instructions at the bottom (`<task>`), anchoring attention and reducing instruction-drift.
* **Rule-Based Bias (Recall Preference)**: The system prompt explicitly enforces recall bias: *"WHEN IN DOUBT, CLASSIFY AS TRUE. We prefer false positives over false negatives."*
* **Failsafe Default**: If the SDK fails to call, or if JSON parsing via Pydantic raises validation errors, the system defaults to keeping the announcement (`is_tech_job = True`) to prevent false negatives.

### 5. Free-Tier Quota & Rate Limit Optimization (429/503 Backoff & Chunked Parallel Scans)
To successfully operate under the Google AI Studio free tier limits:
* **Chunking**: Slices unique announcements into chunks of exactly 10 items. This reduces the number of API requests up to 10x, significantly avoiding rate-limit pressure.
* **ThreadPoolExecutor Concurrency**: Executes chunks concurrently using a `ThreadPoolExecutor` for high-throughput evaluation.
* **Exponential Backoff on 429/503 Errors**: Wraps each chunk call in a retry loop (up to 3 attempts). If an HTTP 429 (Too Many Requests) or HTTP 503 (Service Unavailable) is encountered, the validator sleeps for `60.0` seconds (for 429) or `10.0` seconds (for 503) and retries.
* **Granular Failsafe**: If validation fails all 3 attempts or encounters a non-retryable error, it defaults to keeping the candidate, ensuring transient errors do not disrupt the scan.

### 6. Parallel Fetching & Log Buffering
* **ThreadPoolExecutor**: `run_scan()` uses `ThreadPoolExecutor` to launch the fetches for all selected sources concurrently.
* **Atomic Log Buffering**: To prevent interleaved console output from multiple concurrent threads in CloudWatch or local terminals, stdout and stderr are dynamically wrapped in a custom `ThreadLocalStream` proxy class. Each scanner thread captures its output to a thread-local `io.StringIO` buffer, which is printed sequentially by the main thread after all fetches complete.


---

## 🗺️ Domain Insights: Findings Export Functionality

### 1. Markdown Overwrite Strategy
* The scan findings are saved at the end of the script execution to the file path specified in `--output` (defaulting to `findings.md`).
* It uses write mode (`"w"`), ensuring the file is overwritten on each run to reflect only the latest results.
* If no findings are found, a "No findings" markdown document is written.
* All write errors are caught and printed as stderr warnings, ensuring a failure to write to disk does not crash the CLI process.

---

## 🗺️ Domain Insights: Spanish Source Grouping

### 1. Spanish Source Grouping (`ES`)
* The CLI scanner supports the `--source ES` option which dynamically aggregates all Spanish job sources: `BOP`, `BOC`, `BOE`, and `SAGULPA` for online scans.

### 2. Sagulpa Date-Boundary & Locale Constraints
* **Closing Date Parsing**: Unlike official daily gazettes, Sagulpa listings remain active for weeks. The parser extracts the closing date from `Fecha finalización de presentación de candidaturas:`.
* **Zero OS-Locale Dependency**: Because Python's `datetime.strptime` month name parsing relies on OS-installed language packs (which lightweight Lambda containers lack), the parser bypasses OS-level locales. It maps Spanish month names (e.g. `junio`) to integers using a hardcoded `SPANISH_MONTHS` dictionary.
* **Target-Date Boundary**: When a `target_date` is specified (e.g. in Lambda execution), the parser collects all active listings where `target_date <= closing_date`, preventing missed vacancies when scans run days late.

---

## 🗺️ Domain Insights: AWS Lambda Stateless Architecture & Notifications

### 1. Unified Execution Architecture
* The orchestration entrypoint resides in [main.py](file:///c:/Users/muk04/Development/PyCharmProjects/job-finder/src/job_finder/main.py). It features the standard CLI main entrypoint (`def main()`) and a cloud entrypoint (`def lambda_handler(event, context)`).
* Both entrypoints delegate core scanning to `run_scan()`.
* **Important**: To run in AWS Lambda without needing `python-dotenv` packaged as a dependency, the import and call of `dotenv.load_dotenv()` are wrapped in a silent try-except `ImportError` block inside `main()`. This keeps standard local environment loading intact but prevents crash loops in the cloud.

### 2. Stateless Date-Filtering Constraints
* Because AWS Lambda is completely ephemeral and lacks access to a persistent disk or local database, the crawler avoids duplicating alerts by verifying publishing dates.
* **BOP/BOC/BOE Fallbacks**: When `is_lambda=True` is active, any fallback execution resulting from empty today bulletins (e.g. weekends) checks if the `latest_date` is strictly older than `resolved_date`. If so, the parser/scrape for that source is bypassed to prevent sending old/duplicated notifications.
* **Constant Ingestion Feeds**: Feeds pulling all active openings (EPSO, EURES, eu-LISA) are passed the resolved target date to filter out anything that wasn't published today. SAGULPA, as a municipal job board, is filtered using the closing date boundary instead (retaining jobs where execution date <= closing date).

### 3. Notification Dispatching (`notifier.py`)
* The dispatching logic is housed in [notifier.py](file:///c:/Users/muk04/Development/PyCharmProjects/job-finder/src/job_finder/notifier.py).
* It parses environment variables to decide which channels to alert: `DISCORD_WEBHOOK_URL` (Discord option), and both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (Telegram option).
* **Discord Chunks**: Discord webhook payloads allow a maximum of 10 embeds, *but* they also enforce a strict 6,000-character payload ceiling across all fields. Bundling up to 10 dense jobs easily violates this, causing silent HTTP 400 Bad Request rejections. To guarantee payload compliance, the dispatcher chunks messages safely into sets of **2 embeds** and sends them sequentially with a `time.sleep(0.5)` to avoid API rate limits.
* **Telegram HTML Formatting**: Telegram messages are parsed as HTML. It handles Unicode and HTML escaping natively, executing separate sequential POST requests to the `sendMessage` endpoint with a `time.sleep(0.5)` cooldown.

### 4. Ephemeral PDF Buffering (Memory Safety)
* **BOP PDF In-Memory Avoidance**: When downloading BOP gazettes online, the system bypasses direct in-memory PDF parsing to protect the Lambda container from memory allocation spikes and OOM exceptions.
* **Disk Buffering Flow**: The downloaded `BytesIO` buffer is dumped to `/tmp/bop_bulletin.pdf` on the container's ephemeral storage first. The parser reads from the disk buffer, which is immediately deleted via `try...finally` block (using `Path.unlink(missing_ok=True)`) to ensure the filesystem is cleaned up even if parsing exceptions are raised.

## 🗺️ Domain Insights: Aena Employment Portal

### 1. Java/SAP SSR Architecture & Self-Authenticating URLs
* The Aena employment portal is a legacy Java/SAP SSR web application which lists active job opportunities.
* It does not provide an API endpoint. Active announcements must be scraped from the list page via BeautifulSoup DOM parsing.
* Aena uses self-authenticating SAP Content Server URLs for PDF documents (`secKey`, `authId`, and expiration parameters) which bypass cookie/session tracking entirely. Thus, standard stateless `requests.get` requests with browser headers are sufficient to download bases PDFs.

### 2. Accent-Insensitive Date Matching & Robust Date boundary
* Spanish date strings contain accented characters (e.g. `Fecha fin inscripción:`). Due to potential encoding differences (e.g., ISO-8859-1 vs. UTF-8), parsing should use accent-insensitive, robust matching (e.g. searching for `"Fecha fin"` instead of the exact accented string) to prevent parsing failures.
* The date boundary filter is applied at the open-window level: if `target_date <= closing_date`, the job is kept.

### 3. Collision-free Ephemeral PDF Buffer
* To process jobs concurrently via `ThreadPoolExecutor` while respecting Lambda's read-only file system, downloaded PDFs must be stored to unique files in `/tmp` using the `get_temp_path(f"aena_temp_{uuid}.pdf")` pattern and deleted immediately in a `finally` block using `Path.unlink(missing_ok=True)`.

### 4. Targeted PDF Extraction & 503 Error Resilience
* **Selective Ingestion to Reduce Latency**: Aena job pages often contain dozens of irrelevant PDFs (administrative lists, syllabuses, etc.). To drastically reduce I/O overhead and memory consumption, the parser filters `<a>` tags by their inner text and `title` attributes. It selectively extracts only those documents containing target keywords (`base`, `bases`, `requisito`, `requisitos`), dropping the rest.
* **Graceful Degradation**: If no PDFs match the keywords, the candidate is cleanly skipped and a warning is logged without raising a breaking exception, keeping the concurrent pipeline intact.
* **Granular 503 Failsafes**: The Aena website frequently throws `503 Service Unavailable` errors. The `ThreadPoolExecutor` is protected by bulletproof nested exception handling:
  * If an individual PDF fails to download (503), the thread logs a warning, cleans up the temp file, and continues downloading the next PDF for that job.
  * If the detail page fails entirely, the outer `try...except` catches the error, generates a fallback `BOPage` (containing just the title and the list-level closing date), and returns it. This ensures the thread never crashes, and the scanner proceeds seamlessly to the next job.

### 5. Dynamic Console Buffering for Single vs. Multi Scans
* `ThreadLocalStream` is used to capture background thread `print()` statements and prevent overlapping text during parallel multi-source runs.
* **Single-Source Unbuffering**: When a single source is run (e.g. `--source AENA`), the `ThreadLocalStream` wrapper is bypassed in `main.py`. This ensures long-running tasks like AENA's 100+ PDF downloads can stream real-time progress (`⏳ Deep-scanning Aena job...`) directly to the console so the user knows the application is not frozen.

### 6. Fail-Fast List-Level Title Rejection
* **Preventing I/O Bottlenecks**: Aena and other legacy portal scans suffer massive performance overheads when downloading attachments for clearly irrelevant roles. To mitigate this, a list-level gatekeeper is integrated via `KeywordFilter.should_reject_title(title)`.
* **Rejection Categories**:
  - **Absolute Rejection**: Immediately skips the job if an absolute rejection pattern matches (e.g. `formativ[oa]s?` or `formativ\.` for student internships).
  - **Relative Rejection**: Skips the job if a relative rejection pattern matches (e.g. `mantenimiento` or `bomber[oa]s?`) **unless** a positive IT keyword is also present in the title (e.g., `"TÉCNICO MANTENIMIENTO SISTEMAS INFORMÁTICOS"` is kept because `"INFORMÁTICOS"` overrides `"mantenimiento"`).
* **Integration**: Call `should_reject_title` inside the list parser loop (`parse_list`) and immediately log a console warning (`⚠️ Title rejected by fast-filter: [Title]`) to skip detail extraction entirely.

### 7. List-Level Expiration Filter (Hard Expiration)
* **Historical Listings**: The Aena job list contains historical jobs that are already closed. To avoid processing expired job postings, a hard expiration filter is enforced at the list level (`parse_list`).
* **Date Parsing**: The `Fecha fin inscripción` date is extracted and parsed using `datetime.datetime.strptime(date_text, "%d/%m/%Y").date()`. If parsing fails, the system fails open (keeps the job) and logs a warning.
* **Expiration Logic**: If the target date is strictly after the job's closing date (i.e. `closing_date < target_date` or `closing_date < today`), the job is dropped immediately to save downstream detail processing overhead.

---

## 🏗️ Strict Deployment Architecture & Constraints

Every agent/assistant working on this repository must strictly adhere to the following rules for building, packaging, and deploying the AWS Lambda function:

1. **No Native Windows Zipping**: Never build the Lambda deployment package (`.zip`) using Windows native tools like `Compress-Archive` or a local Windows Python interpreter. Doing so strips POSIX file permissions (specifically `0o755` executable permissions for shared libraries) and results in `Permission denied` errors during AWS Lambda execution. Always perform zipping inside a Linux environment (like the SAM build container).
2. **Glibc Matching**: Never package dependencies using generic Debian or Ubuntu-based Docker images (such as `python:3.14-slim`). These environments may contain newer versions of `glibc` that are incompatible with the Amazon Linux target, causing dynamic linking runtime crashes. Only compile and package dependencies using the official AWS SAM build image: `public.ecr.aws/sam/build-python3.14`.
3. **Read-Only Filesystem**: AWS Lambda execution environments are ephemeral and read-only except for the `/tmp` directory. Any temporary file downloads (e.g. streaming PDFs) must be explicitly routed to write to and read from the `/tmp/` directory.
4. **Dependency Locking**: The `requirements.txt` file must enforce strict version locking using the `==` operator for stability. In addition, `cffi` must be explicitly defined in `requirements.txt` to prevent transient version or binary mismatches under different platforms.
5. **Gitignore Policy**: Ensure that local build targets (`dist_lambda/`) and validation results (`response.json`) are kept strictly out of git version control to prevent repository bloat and credential/artifact leaks (already configured in `.gitignore`).


---

## 🗺️ Domain Insights: HTML Exporter & CLI Output Routing

### 1. Decoupled HTML Exporter (`html_exporter.py`)
* **Standalone Self-Contained Document**: Generates a single HTML file with dark mode CSS injected directly into the `<style>` tag in the `<head>`. Zero external CSS dependencies or CDN links are used.
* **Modern Dark Mode Styling**: Features dark gray background theme (`#121214`), elevated card containers (`#1e1e24`), crisp typography, keyword chips (`#818cf8`), and accessible link accents (`#38bdf8`).
* **Zero Interactivity**: Designed strictly for static reading with vertical scrolling (linear reader layout). All content text is sanitized via `html.escape()`. Standard `<a>` tags link to official bulletins with `target="_blank" rel="noopener noreferrer"`.
* **File Handling**: Uses `"w"` mode with UTF-8 encoding to overwrite destination files predictably.

### 2. Dual CLI Export Control (`main.py`)
* Users can specify `--format html` or `--format markdown` (defaulting to `markdown`).
* Automatic Extension Override: If `--output` path ends in `.html` (e.g. `--output report.html`), the format dynamically defaults to HTML.
