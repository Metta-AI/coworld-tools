#!/usr/bin/env python3
"""Serve docs/rules.html with auto-reload on file changes."""
import http.server
import os
import sys

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
RULES_HTML = os.path.join(DOCS_DIR, "rules.html")

INJECT_SCRIPT = b"""<script>
let _lastMod = 0;
setInterval(async () => {
  try {
    const r = await fetch('/__mtime');
    const t = await r.text();
    if (_lastMod && t !== String(_lastMod)) location.reload();
    _lastMod = t;
  } catch(e) {}
}, 1000);
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/__mtime":
            try:
                mt = str(int(os.path.getmtime(RULES_HTML)))
            except OSError:
                mt = "0"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(mt.encode())
            return

        # Serve files from docs/
        rel = self.path.lstrip("/")
        if rel == "" or rel == "rules.html":
            filepath = RULES_HTML
        else:
            filepath = os.path.join(DOCS_DIR, rel)

        filepath = os.path.normpath(filepath)
        if not filepath.startswith(os.path.normpath(DOCS_DIR)):
            self.send_response(403)
            self.end_headers()
            return

        if not os.path.isfile(filepath):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        # Determine content type
        ext = os.path.splitext(filepath)[1].lower()
        ct = {
            ".html": "text/html; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".css": "text/css",
            ".js": "application/javascript",
        }.get(ext, "application/octet-stream")

        with open(filepath, "rb") as f:
            data = f.read()

        # Inject auto-reload into HTML
        if ext == ".html":
            data = data.replace(b"</body>", INJECT_SCRIPT + b"\n</body>")

        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8801
    srv = http.server.HTTPServer(("", port), Handler)
    print(f"Serving {DOCS_DIR}/ at http://localhost:{port}")
    print(f"Watching {RULES_HTML} for changes.")
    print("Auto-reloads on file change. Ctrl+C to stop.")
    srv.serve_forever()
