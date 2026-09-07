# Source inventory

Purpose: map each job source to its fetcher, parser, input format, date handling, and detailed documentation.

Read when: choosing a source-specific investigation path or assessing the impact of a source change.

Source of truth: `main.py` and the fetcher/parser modules listed below.

| Source | Fetcher | Parser | Input | Family document | Tests |
| --- | --- | --- | --- | --- | --- |
| BOP | `bop_fetcher.py` | `bop_parser.py` | PDF | [Spanish gazettes](spanish-gazettes.md) | `test_bop_parser.py` |
| BOC | `boc_fetcher.py` | `boc_parser.py` | RSS/XML | [Spanish gazettes](spanish-gazettes.md) | `test_boc_parser.py` |
| BOE | `boe_fetcher.py` | `boe_parser.py` | XML, with optional PDF deep scan | [Spanish gazettes](spanish-gazettes.md) | `test_boe_parser.py` |
| Sagulpa | `sagulpa_fetcher.py` | `sagulpa_parser.py` | HTML list and details | [Corporate boards](corporate-boards.md) | `test_sagulpa_parser.py` |
| Aena | `aena_fetcher.py` | `aena_parser.py` | HTML list/details and PDFs | [Corporate boards](corporate-boards.md) | `test_aena_parser.py` |
| EPSO | `epso_fetcher.py` | `epso_parser.py` | JSON-LD repository metadata and CSV | [European sources](european-sources.md) | `test_eu_sources.py` |
| EURES | `eures_fetcher.py` | `eures_parser.py` | Browser-intercepted JSON | [European sources](european-sources.md) | `test_eu_sources.py` |
| eu-LISA | `eulisa_fetcher.py` | `eulisa_parser.py` | HTML table/list | [European sources](european-sources.md) | `test_eu_sources.py` |

The `ES` group in `main.py` contains BOP, BOC, BOE, Sagulpa, and Aena. The `EU` group contains EPSO, EURES, and eu-LISA. `ALL` contains all eight.
