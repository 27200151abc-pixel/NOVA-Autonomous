from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN_DIR = Path(os.environ.get("NOVA_PLUGIN_DIR", "/plugins")).resolve()
MAX_REQUEST = 65536
MAX_OUTPUT = 65536
TIMEOUT_SECONDS = 5


class Handler(BaseHTTPRequestHandler):
    server_version = "NOVAPluginWorker/1"

    def log_message(self, format, *args):
        # Do not log plugin arguments or returned data.
        return

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/run":
            self._send(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_REQUEST:
                self._send(413, {"error": "request_too_large"})
                return
            payload = json.loads(self.rfile.read(length))
            name = payload.get("name")
            arguments = payload.get("arguments")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
                self._send(400, {"error": "invalid_plugin_name"})
                return
            if not isinstance(arguments, dict):
                self._send(400, {"error": "arguments_must_be_object"})
                return
            plugin_file = (PLUGIN_DIR / (name + ".py")).resolve()
            manifest_file = (PLUGIN_DIR / (name + ".json")).resolve()
            if PLUGIN_DIR not in plugin_file.parents or PLUGIN_DIR not in manifest_file.parents:
                self._send(400, {"error": "invalid_plugin_path"})
                return
            if not plugin_file.is_file() or not manifest_file.is_file():
                self._send(404, {"error": "plugin_not_found"})
                return
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("name") != name:
                self._send(400, {"error": "manifest_name_mismatch"})
                return
            completed = subprocess.run(
                [sys.executable, "-I", "/worker/runner.py", name],
                input=json.dumps(arguments, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                cwd="/tmp",
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
                check=False,
            )
            if completed.returncode != 0:
                self._send(422, {"error": "plugin_execution_failed"})
                return
            if len(completed.stdout.encode("utf-8")) > MAX_OUTPUT:
                self._send(413, {"error": "plugin_output_too_large"})
                return
            result = json.loads(completed.stdout)
            self._send(200, {"result": result})
        except subprocess.TimeoutExpired:
            self._send(408, {"error": "plugin_timeout"})
        except (ValueError, TypeError, OSError, json.JSONDecodeError):
            self._send(400, {"error": "invalid_plugin_request"})
        except Exception:
            self._send(500, {"error": "worker_error"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
