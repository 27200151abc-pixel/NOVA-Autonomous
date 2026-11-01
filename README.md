# NOVA — Open, self-hostable AI agent

NOVA is an independent, provider-agnostic agent foundation. The project is designed to run locally or on a user-controlled host, with optional remote model inference through any OpenAI-compatible endpoint.

> **Status:** Phase 3 foundation. Includes a standalone chat UI, owner-authenticated approval queue, restricted workspace file tools, SQLite memory, and bounded multi-step tool execution. This remains an early agent runtime, not a finished autonomous assistant. Includes owner-enabled Python plugins, SQLite conversation memory search, and bounded multi-step tool execution. It is still an early agent runtime, not a finished autonomous system. Free hosting and free inference are quota-limited; no service is represented as unlimited.

## Current release\n\nNOVA 0.4.0 exposes a browser chat at `/`, health at `/health`, API docs at `/docs`, and owner-only policy/memory/approval endpoints. File tools are confined to a dedicated workspace directory; writes require owner approval by default. A compatible model endpoint is still required for chat inference.\n\n## Principles
- Open-source NOVA code (MIT); third-party models and services retain their own licenses and terms.
- Provider-neutral model adapter: configure `NOVA_BASE_URL`, `NOVA_API_KEY`, and `NOVA_MODEL`.
- Local SQLite conversation history with keyword search.
- Owner-editable tool policy in `nova/policy.json`, including enabled tools/plugins and planning depth.
- Python plugin folder at `nova/plugins/` for owner-reviewed extensions.
- Bounded multi-step tool calling (configurable rounds and calls per round).
- Provider-neutral model connection.

## Quick start (Python 3.11+)
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and configure a compatible model endpoint.
uvicorn nova.main:app --reload
```

OpenAPI docs: http://127.0.0.1:8000/docs

## API
- `GET /health` — health check.
- `POST /v1/chat` — send a message and receive a response.
  ```json
  {"message":"Hello NOVA","conversation_id":"optional-id"}
  ```

If no model endpoint is configured, `/v1/chat` returns HTTP 503 with a clear configuration message. The health endpoint still works.

## Configuration
See [`.env.example`](.env.example). Use a provider you trust and check its privacy, pricing, retention, and usage limits. For local inference, point `NOVA_BASE_URL` to a compatible local server; the machine must have enough resources.

## Owner control
Edit `nova/policy.json` to configure `enabled_tools`, `enabled_plugins`, `approval_required`, `max_tool_calls_per_turn`, and `max_tool_rounds`. Read the active configuration at `GET /v1/owner-policy`. Search stored messages with `GET /v1/memory/search?q=...`. See [Extending NOVA](docs/EXTENDING_NOVA.md) to add capabilities.

## Roadmap
1. **Foundation:** independent API, SQLite memory, provider adapter, and editable policy.
2. Isolated plugin runner and interactive owner approval queue.
3. Sandboxed browser and filesystem tools with configurable scopes.
4. Semantic/vector memory, task planning improvements, retries, observability, and evaluation tests.
5. Optional web UI, voice/image interface, and deployment recipes.

## Security
Never commit `.env`, API keys, personal data, or database files. Do not expose the API publicly without authentication, rate limiting, TLS, and network restrictions. NOVA does not execute arbitrary code.

## License
NOVA-authored code is MIT licensed. See [LICENSE](LICENSE).

## Workspace file tools

NOVA can list and read UTF-8 text files, and write files, inside `NOVA_WORKSPACE_ROOT` only. Reads and writes are limited to 128 KiB; directory listings are capped at 200 entries. Parent-directory traversal and symbolic links are rejected. `workspace_write` is approval-gated by default. The workspace is mounted separately in Docker Compose at `/workspace`.

## Owner authentication and approvals

Set a long, private `NOVA_OWNER_TOKEN` in `.env`. Without this token, owner-only endpoints stay locked. Send it as `Authorization: Bearer <token>` when calling:

- `GET /v1/owner-policy` — read the active policy.
- `GET /v1/memory/search?q=...` — search stored messages.
- `GET /v1/approvals?status=pending` — list pending tool requests.
- `POST /v1/approvals/{id}/decision` with `{"decision":"approve"}` or `{"decision":"reject"}` — approve or reject a queued request.

Tools listed in `approval_required` are queued instead of executed. Approval executes the tool once after rechecking that it remains enabled. Keep the token secret and do not expose the owner endpoints publicly without TLS and additional deployment protections.

**Plugin safety:** Python plugins still execute inside the NOVA server process. Approval delays the plugin's `run()` call but is not a sandbox; enable only reviewed code. Process/container isolation remains future work.
