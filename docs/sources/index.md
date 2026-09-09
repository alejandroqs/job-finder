# Source inventory

Purpose: map each job source to its fetcher, parser, input format, date handling, and detailed documentation.

Read when: choosing a source-specific investigation path or assessing the impact of a source change.

Source of truth: [`main.py`](../../src/job_finder/main.py) and the fetcher/parser modules listed below.

| Source | Fetcher | Parser | Input | Date treatment | Family document | Tests |
| --- | --- | --- | --- | --- | --- | --- |
| BOP | [`bop_fetcher.py`](../../src/job_finder/bop_fetcher.py) | [`bop_parser.py`](../../src/job_finder/bop_parser.py) | PDF | Requested bulletin date; latest fallback when unavailable | [Spanish gazettes](spanish-gazettes.md) | [`test_bop_parser.py`](../../tests/test_bop_parser.py) |
| BOC | [`boc_fetcher.py`](../../src/job_finder/boc_fetcher.py) | [`boc_parser.py`](../../src/job_finder/boc_parser.py) | RSS/XML | Feed items equal the target date; latest-date fallback | [Spanish gazettes](spanish-gazettes.md) | [`test_boc_parser.py`](../../tests/test_boc_parser.py) |
| BOE | [`boe_fetcher.py`](../../src/job_finder/boe_fetcher.py) | [`boe_parser.py`](../../src/job_finder/boe_parser.py) | XML, with optional PDF deep scan | Sumario target date; backward fallback for unavailable issues | [Spanish gazettes](spanish-gazettes.md) | [`test_boe_parser.py`](../../tests/test_boe_parser.py) |
| Sagulpa | [`sagulpa_fetcher.py`](../../src/job_finder/sagulpa_fetcher.py) | [`sagulpa_parser.py`](../../src/job_finder/sagulpa_parser.py) | HTML list and details | Keeps listings whose closing date is on or after the target date | [Corporate boards](corporate-boards.md) | [`test_sagulpa_parser.py`](../../tests/test_sagulpa_parser.py) |
| Guaguas Municipales | [`guaguas_fetcher.py`](../../src/job_finder/guaguas_fetcher.py) | [`guaguas_parser.py`](../../src/job_finder/guaguas_parser.py) | HTML employment list | Keeps cards whose inclusive Convocatoria interval contains the target or current date | [Corporate boards](corporate-boards.md) | [`test_guaguas_parser.py`](../../tests/test_guaguas_parser.py), [`test_guaguas_fetcher.py`](../../tests/test_guaguas_fetcher.py), [`test_guaguas_integration.py`](../../tests/test_guaguas_integration.py) |
| Aena | [`aena_fetcher.py`](../../src/job_finder/aena_fetcher.py) | [`aena_parser.py`](../../src/job_finder/aena_parser.py) | HTML list/details and PDFs | Drops listings closed before the target or current date | [Corporate boards](corporate-boards.md) | [`test_aena_parser.py`](../../tests/test_aena_parser.py) |
| EPSO | [`epso_fetcher.py`](../../src/job_finder/epso_fetcher.py) | [`epso_parser.py`](../../src/job_finder/epso_parser.py) | JSON-LD repository metadata and CSV | Drops deadlines earlier than the target date | [European sources](european-sources.md) | [`test_eu_sources.py`](../../tests/test_eu_sources.py) |
| EURES | [`eures_fetcher.py`](../../src/job_finder/eures_fetcher.py) | [`eures_parser.py`](../../src/job_finder/eures_parser.py) | Browser-intercepted JSON | `target_date` is accepted but currently not applied | [European sources](european-sources.md) | [`test_eu_sources.py`](../../tests/test_eu_sources.py) |
| eu-LISA | [`eulisa_fetcher.py`](../../src/job_finder/eulisa_fetcher.py) | [`eulisa_parser.py`](../../src/job_finder/eulisa_parser.py) | HTML table/list | Drops deadlines earlier than the target date | [European sources](european-sources.md) | [`test_eu_sources.py`](../../tests/test_eu_sources.py) |

The `ES` group in `main.py` contains BOP, BOC, BOE, Sagulpa, Guaguas Municipales, and Aena. The `EU` group contains EPSO, EURES, and eu-LISA. `ALL` contains all nine sources.
