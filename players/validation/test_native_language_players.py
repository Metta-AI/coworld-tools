import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = Path(__file__).resolve().parents[2]
calls = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls.append((self.path, dict(self.headers), data))
        text = json.dumps(
            {
                "schema_version": 1,
                "action": "wait",
                "reason": "native",
                "rationale": "native",
                "confidence": 0.8,
            }
        )
        response = json.dumps(
            {
                "id": "msg-native",
                "type": "message",
                "role": "assistant",
                "model": data["model"],
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ.update(
    COWORLD_LLM_ENDPOINT=f"http://127.0.0.1:{server.server_port}",
    COWORLD_LLM_MODEL="anthropic/claude-sonnet-4.6",
    CLAUDE_CODE_USE_BEDROCK="1",
    ANTHROPIC_API_KEY="wrong-key",
)
spec = importlib.util.spec_from_file_location(
    "suspectra", root / "players/players/crewrift/suspectra/llm_meeting.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    decision = mod.decide(
        {
            "constraints": {"valid_vote_targets": ["skip"]},
            "state": {"fallback_vote": "skip"},
        }
    )
    assert decision["reason"] == "native", decision
    sys.path.insert(0, str(root / "players/users/james/personal_cogs/persephone"))
    from agents.eurydice.llm_provider import (
        BedrockHaikuProvider,
        _invoke_bedrock_messages,
    )

    provider = BedrockHaikuProvider(model="retired-model")
    assert (
        json.loads(_invoke_bedrock_messages(provider, "rules", "state"))["reason"]
        == "native"
    )
finally:
    server.shutdown()
    server.server_close()
assert len(calls) == 2
for path, headers, data in calls:
    assert (
        path == "/v1/messages"
        and data["model"] == "anthropic/claude-sonnet-4.6"
        and "anthropic_version" not in data
    )
    assert "Authorization" not in headers
print("Two native copied player transports passed real HTTP")
