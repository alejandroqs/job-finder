# Local development workflow

Purpose: run the scanner locally and understand its side effects.

Read when: setting up the project, reproducing a parser result, using offline fixtures, or checking exports.

Source of truth: `pyproject.toml`, `requirements.txt`, `main.py`, and the test suite.

## Setup

Use Python 3.11 or newer. From PowerShell at the repository root:

```powershell
python -m pip install -e ".[dev]"
```

The runtime dependency list is in `pyproject.toml`; the deployment-oriented pinned list is in `requirements.txt`. Check [known-limitations.md](../known-limitations.md) before assuming the two lists are equivalent.

## Common commands

```powershell
python -m job_finder.main
python -m job_finder.main --source BOE --no-ai
python -m job_finder.main --date 2026-05-21 --source ES
python -m job_finder.main --file tests/fixtures/boe_sample.xml --output findings.md
python -m job_finder.main --file tests/fixtures/eulisa_careers.html --format html --output findings.html
python -m pytest tests/ -v --tb=short
```

Offline files are auto-detected by extension or signature. They avoid live fetching but still run the parser and keyword filter. The normal CLI overwrites its output file and exits `0` if findings exist or `1` if none exist.

## Side effects

Live commands contact official portals and optional AI services. If notification variables are configured, a local run with findings can send Discord or Telegram messages, including when `--no-ai` is used. Use offline fixtures and unset notification variables for isolated local checks.

The scanner may write temporary PDFs to the system temporary directory locally. It writes the requested findings file using UTF-8 and replaces an existing file.
