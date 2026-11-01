# NOVA — Open, self-hostable AI agent

NOVA is a provider-neutral AI-agent foundation designed to run on a machine or host controlled by its owner. The project is open-source; external models and hosting retain their own licenses, terms, costs, and quotas.

> **Current state: Phase 3 foundation (v0.4.0).** Includes an Arabic-first web chat, SQLite conversation history and keyword search, bounded multi-step tool calling, owner authentication, an approval queue and console, Python plugins, and restricted workspace file tools. It is not yet a finished autonomous assistant: live voice/video, browser automation, robust plugin sandboxing, and verified production deployment remain future work.

## Features

- Provider-neutral inference through an OpenAI-compatible chat-completions endpoint.
- Browser chat at `/`; owner console at `/owner`; API docs at `/docs`.
- SQLite conversation persistence and basic keyword memory search.
- Owner-editable policy in `nova/policy.json`.
- Multi-round tool calling with configurable limits.
- Approval queue for sensitive tools; workspace writes require approval by default.
- Workspace list/read/write tools restricted to `NOVA_WORKSPACE_ROOT`.
- Owner-only endpoints protected by a bearer token.
- Docker Compose volumes separate persistent database and workspace data.

## Quick start

Python 3.11+:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set:
- `NOVA_BASE_URL`: base URL of a compatible inference provider (without the `/chat/completions` suffix).
- `NOVA_MODEL`: model identifier accepted by that provider.
- `NOVA_API_KEY`: provider key, if required.
- `NOVA_CHAT_TOKEN`: a long random secret for chat API access.
- `NOVA_OWNER_TOKEN`: a different long random secret for policy, memory, and approvals. Generate each independently with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Then start:

```bash
uvicorn nova.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. To review file-write approvals, open `http://127.0.0.1:8000/owner` and enter the owner token. In the chat page, enter the separate chat token in the access field. The token is kept in the browser tab's session storage.

## Docker

Copy `.env.example` to `.env`, configure the model and owner token, then run:

```bash
docker compose up --build
```

Docker Compose persists SQLite data in `nova-data` and user workspace files in `nova-workspace`.

## API

- `GET /health` — health check.
- `POST /v1/chat` — chat endpoint.
- `GET /v1/owner-policy` — active policy (owner bearer token required).
- `GET /v1/memory/search?q=...` — keyword memory search (owner token required).
- `GET /v1/approvals?status=pending` — list approval requests (owner token required).
- `POST /v1/approvals/{id}/decision` — approve or reject a request (owner token required).

## Workspace safety

NOVA's file tools are limited to `NOVA_WORKSPACE_ROOT`. Parent-directory traversal and symbolic links are rejected. Text reads and writes are capped at 128 KiB; directory listings are capped at 200 entries. The workspace is not a general-purpose filesystem browser. Writes are approval-gated by default.

This is application-level path restriction, not an operating-system sandbox. Keep the workspace separate from secrets and application files. Do not expose NOVA to untrusted users without additional authentication, TLS, network restrictions, and container/user isolation.

## Plugins

Python plugins in `nova/plugins/` run with the NOVA server process's OS permissions. Enable only code you wrote or reviewed. Approval delays a plugin's `run()` invocation but does not sandbox its import or execution. Strong process/container isolation is not implemented yet.

## Development and tests

```bash
pip install -r requirements-dev.txt
python -m compileall -q nova
pytest -q
```

GitHub Actions is configured to run compile checks and tests on pushes and pull requests to `main`. A successful run must be confirmed in the repository's Actions tab; the code changes alone do not prove the tests passed.

## Roadmap

1. Verify and harden the current runtime and approval workflow.
2. Add OS-level isolation for plugins and tool execution.
3. Add controlled browser automation with explicit approval for external side effects.
4. Improve memory retrieval and add import/export.
5. Add streaming responses, then voice input/output and live visual interaction where a compatible model/provider supports them.
6. Provide reproducible deployment and operational monitoring.

NOVA cannot provide unlimited free inference or compute. The owner chooses the model endpoint and remains subject to that provider's availability, limits, and terms.
