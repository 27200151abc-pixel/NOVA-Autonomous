from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PLUGIN_DIR = Path("/plugins")
MAX_BODY = 16 * 1024
MAX_TEXT = 100_000


def execute(name: str, arguments: dict) -> dict:
    if not name.isidentifier():
        raise ValueError("Invalid plugin name")
    manifest_path = PLUGIN_DIR / f"{name}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("name") != name:
        raise ValueError("Plugin manifest name mismatch")

    # Explicit operation allowlist: no arbitrary plugin Python is imported.
    if manifest.get("operation") == "text_stats":
        value = arguments.get("text")
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise ValueError("text must be a string of at most 100000 characters")
        return {
            "characters": len(value),
            "words": len(value.split()),
            "lines": len(value.splitlines()) if value else 0,
        }
    raise ValueError("Unsupported plugin operation")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Invalid request")
            name = payload.get("name")
            arguments = payload.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("Invalid plugin request")
            result = execute(name, arguments)
            body = json.dumps({"result": result}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
        except Exception:
            body = json.dumps({"error": "plugin_execution_failed"}).encode("utf-8")
            self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
