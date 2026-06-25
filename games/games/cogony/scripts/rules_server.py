#!/usr/bin/env python3
"""Live-reloading markdown rules server.

Serves RULES.md as styled HTML with auto-reload on file changes.
Usage: python scripts/rules_server.py [--port 8800]
"""

import http.server
import os
import sys
import time

RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "RULES.md")

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Cogony Rules</title>
<style>
  :root { --bg: #1a1a2e; --fg: #e0e0e0; --accent: #00d4ff; --table-bg: #16213e; --border: #0f3460; --code-bg: #0d1117; }
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--fg); max-width: 900px; margin: 0 auto; padding: 20px 40px; line-height: 1.6; }
  h1 { color: var(--accent); border-bottom: 2px solid var(--accent); padding-bottom: 8px; }
  h2 { color: #e94560; margin-top: 2em; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
  h3 { color: #f5a623; }
  table { border-collapse: collapse; width: 100%%; margin: 12px 0; }
  th { background: var(--border); color: var(--accent); padding: 8px 12px; text-align: left; border: 1px solid #2a4a7f; }
  td { background: var(--table-bg); padding: 8px 12px; border: 1px solid #2a4a7f; }
  code { background: var(--code-bg); color: #7ee787; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
  pre { background: var(--code-bg); padding: 16px; border-radius: 6px; overflow-x: auto; border: 1px solid var(--border); }
  pre code { padding: 0; background: none; }
  a { color: var(--accent); }
  hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
  strong { color: #f0f0f0; }
  ul, ol { padding-left: 24px; }
  li { margin: 4px 0; }
  blockquote { border-left: 3px solid var(--accent); margin: 12px 0; padding: 8px 16px; background: rgba(0,212,255,0.05); }
  .timestamp { color: #666; font-size: 0.8em; text-align: right; }
</style>
<script>
  // Auto-reload: poll every 2 seconds
  let lastMod = 0;
  setInterval(async () => {
    try {
      const r = await fetch('/mtime');
      const t = await r.text();
      if (lastMod && t !== String(lastMod)) location.reload();
      lastMod = t;
    } catch(e) {}
  }, 2000);
</script>
</head>
<body>
%s
<p class="timestamp">Last updated: %s</p>
</body>
</html>"""


def render_md(path):
    """Render markdown to HTML using a simple approach."""
    import re

    with open(path) as f:
        md = f.read()

    # Convert markdown to HTML (basic but functional)
    lines = md.split("\n")
    html_parts = []
    in_code = False
    in_table = False
    table_header_done = False

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            if in_code:
                html_parts.append("</code></pre>")
                in_code = False
            else:
                html_parts.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            html_parts.append(line.replace("<", "&lt;").replace(">", "&gt;"))
            continue

        # Tables
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("- :") for c in cells):
                continue  # separator row
            if not in_table:
                html_parts.append("<table>")
                in_table = True
                table_header_done = False
            if not table_header_done:
                html_parts.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
                table_header_done = True
            else:
                html_parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        elif in_table:
            html_parts.append("</table>")
            in_table = False
            table_header_done = False

        # Headers
        if line.startswith("### "):
            html_parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("---"):
            html_parts.append("<hr>")
        elif line.startswith("* "):
            html_parts.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            html_parts.append("")
        else:
            # Inline formatting
            formatted = line
            formatted = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', formatted)
            formatted = re.sub(r'`(.+?)`', r'<code>\1</code>', formatted)
            html_parts.append(f"<p>{formatted}</p>")

    if in_table:
        html_parts.append("</table>")

    return "\n".join(html_parts)


class RulesHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/mtime":
            mtime = str(int(os.path.getmtime(RULES_PATH)))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(mtime.encode())
        else:
            body = render_md(RULES_PATH)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            html = HTML_TEMPLATE % (body, ts)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # quiet


if __name__ == "__main__":
    port = 8800
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    server = http.server.HTTPServer(("", port), RulesHandler)
    print(f"Rules server at http://localhost:{port}")
    print(f"Watching {os.path.abspath(RULES_PATH)}")
    print("Auto-reloads on file changes. Ctrl+C to stop.")
    server.serve_forever()
