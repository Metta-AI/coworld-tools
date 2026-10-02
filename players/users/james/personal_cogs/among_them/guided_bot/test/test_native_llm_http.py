import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

requests = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append((self.path, dict(self.headers), body))
        response = json.dumps(
            {"content": [{"type": "text", "text": "NATIVE"}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    subprocess.run([sys.argv[1], f"http://127.0.0.1:{server.server_port}/"], check=True)
finally:
    server.shutdown()
    server.server_close()
    thread.join()
assert len(requests) == 1
path, headers, body = requests[0]
assert path == "/v1/messages"
assert body["model"] == "anthropic/claude-sonnet-4.6"
assert "anthropic_version" not in body
assert "Authorization" not in headers
