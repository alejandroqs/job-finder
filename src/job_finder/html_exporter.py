import datetime
import html
import sys
from pathlib import Path
from typing import List

from job_finder.interfaces import ParsedAnnouncement


def generate_html_findings(announcements: List[ParsedAnnouncement]) -> str:
    """
    Generates a standalone, self-contained HTML document representing the job findings.

    Args:
        announcements: List of parsed job announcements.

    Returns:
        A formatted HTML string with inline CSS styling.
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_count = len(announcements)

    items_html_list: List[str] = []

    if not announcements:
        items_html_list.append(
            '  <div class="empty-state">\n'
            '    <p>No IT-related jobs found matching your filters in any source.</p>\n'
            '  </div>'
        )
    else:
        for ann in announcements:
            source_label = f"{ann.source} - Página" if ann.source == "BOP" else f"{ann.source} - Item"
            organism_escaped = html.escape(ann.organism.upper())
            source_label_escaped = html.escape(f"{source_label} {ann.page_number}")
            description_escaped = html.escape(ann.description.strip())

            # Format keywords as chips
            keyword_chips = "".join(
                f'<span class="chip">{html.escape(k)}</span>'
                for k in ann.matched_keywords
            )

            # URL element
            if ann.url:
                url_escaped = html.escape(ann.url)
                url_html = (
                    f'      <footer class="card-footer">\n'
                    f'        <a href="{url_escaped}" target="_blank" rel="noopener noreferrer" class="bulletin-link">\n'
                    f'          View Original Bulletin &rarr;\n'
                    f'        </a>\n'
                    f'      </footer>\n'
                )
            else:
                url_html = ""

            card_html = (
                f'    <article class="job-card">\n'
                f'      <header class="card-header">\n'
                f'        <div class="source-badge">{source_label_escaped}</div>\n'
                f'        <h2 class="organism-title">{organism_escaped}</h2>\n'
                f'      </header>\n'
                f'      <div class="card-body">\n'
                f'        <p class="description-text">{description_escaped}</p>\n'
                f'      </div>\n'
                f'      <div class="card-metadata">\n'
                f'        <div class="keywords-list">\n'
                f'          {keyword_chips}\n'
                f'        </div>\n'
                f'      </div>\n'
                f'{url_html}'
                f'    </article>'
            )
            items_html_list.append(card_html)

    cards_joined = "\n\n".join(items_html_list)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>IT Job Findings</title>
  <style>
    :root {{
      --bg-body: #18181b;       /* zinc-900 */
      --bg-card: #27272a;       /* zinc-800 */
      --border-color: #3f3f46;  /* zinc-700 */
      --text-main: #f4f4f5;     /* zinc-100 */
      --text-muted: #a1a1aa;    /* zinc-400 */
      --accent: #a78bfa;        /* violet-400 */
      --accent-hover: #c4b5fd;  /* violet-300 */
      --badge-bg: #3f3f46;      /* zinc-700 */
      --badge-text: #e4e4e7;    /* zinc-200 */
      --chip-bg: rgba(167, 139, 250, 0.1);
      --chip-border: rgba(167, 139, 250, 0.2);
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background-color: var(--bg-body);
      color: var(--text-main);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      padding: 4rem 1.5rem;
    }}

    .container {{
      max-width: 65ch;
      margin: 0 auto;
    }}

    .page-header {{
      margin-bottom: 4rem;
    }}

    .page-title {{
      font-size: 2.25rem;
      font-weight: 800;
      letter-spacing: -0.025em;
      color: var(--text-main);
      margin-bottom: 0.5rem;
    }}

    .page-meta {{
      font-size: 0.875rem;
      color: var(--text-muted);
      display: flex;
      gap: 1.5rem;
    }}

    .job-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 2.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}

    .job-card:hover {{
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
      transform: translateY(-2px);
    }}

    .card-header {{
      margin-bottom: 1.5rem;
    }}

    .source-badge {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--badge-text);
      background-color: var(--badge-bg);
      padding: 0.25rem 0.75rem;
      border-radius: 9999px;
      margin-bottom: 1rem;
    }}

    .organism-title {{
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--text-main);
      line-height: 1.3;
      letter-spacing: -0.015em;
    }}

    .card-body {{
      margin-bottom: 2rem;
    }}

    .description-text {{
      color: var(--text-muted);
      white-space: pre-wrap;
      font-size: 1rem;
    }}

    .card-metadata {{
      border-top: 1px solid var(--border-color);
      padding-top: 1.5rem;
      margin-bottom: 1.5rem;
    }}

    .keywords-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .chip {{
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--accent);
      background-color: var(--chip-bg);
      border: 1px solid var(--chip-border);
      padding: 0.25rem 0.875rem;
      border-radius: 9999px;
    }}

    .card-footer {{
      display: flex;
      justify-content: flex-start;
    }}

    .bulletin-link {{
      display: inline-flex;
      align-items: center;
      color: var(--accent);
      font-size: 0.9375rem;
      font-weight: 500;
      text-decoration: none;
      transition: color 0.2s ease;
    }}

    .bulletin-link:hover {{
      color: var(--accent-hover);
    }}

    .empty-state {{
      text-align: center;
      padding: 4rem 2rem;
      background-color: var(--bg-card);
      border: 1px dashed var(--border-color);
      border-radius: 12px;
      color: var(--text-muted);
    }}
  </style>
</head>
<body>
  <main class="container">
    <header class="page-header">
      <h1 class="page-title">IT Job Findings</h1>
      <div class="page-meta">
        <span>Scan Date: {now_str}</span>
        <span>Total Findings: {total_count}</span>
      </div>
    </header>

{cards_joined}
  </main>
</body>
</html>
"""


def save_html_findings(announcements: List[ParsedAnnouncement], output_path: Path) -> None:
    """
    Saves the scanning findings to a self-contained HTML file, overwriting existing content.

    Args:
        announcements: List of parsed job announcements.
        output_path: Path where the HTML file should be written.
    """
    try:
        html_content = generate_html_findings(announcements)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"💾 Findings successfully saved to {output_path}")
    except Exception as e:
        print(f"⚠️ Warning: Could not save findings to {output_path}: {e}", file=sys.stderr)
