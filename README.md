# NOVA — Open, self-hostable AI agent

NOVA is a provider-neutral AI-agent foundation designed to run on a machine or host controlled by its owner. The project is open-source; external models and hosting retain their own licenses, terms, costs, and quotas.

> **Current state: Phase 3 foundation (v0.5.0 in progress).** Includes an Arabic-first web chat, SQLite conversation history and keyword search, bounded multi-step tool calling, owner authentication, an approval queue and console, and restricted workspace file tools. A restricted plugin worker is included for a small allowlist of declarative operations; arbitrary Python plugin execution is not enabled. It is not yet a finished autonomous assistant: live voice/video, browser automation and verified production deployment remain in progress.

## Features

- Provider-neutral inference through an OpenAI-compatible chat-completions endpoint.
- Browser chat at `/`; owner console at `/owner`; API docs at `/docs`.
- SQLite conversation persistence and basic keyword memory search.
- Owner-editable policy in `nova/policy.json`, with fail-closed type validation for tool lists and execution limits.
- Multi-round tool calling with a strict aggregate tool-call budget per user turn.
- Approval queue for sensitive tools; workspace writes require approval by default.
- A separate plugin-worker container runs allowlisted declarative operations with read-only plugin manifests, no Linux capabilities, no-new-privileges, resource limits, and a private network.
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
python scripts/setup_env.py
```

The setup script creates three independent random secrets and refuses to overwrite an existing `.env`. Edit `.env` and set:
- `NOVA_BASE_URL`: base URL of a compatible inference provider (without the `/chat/completions` suffix).
- `NOVA_MODEL`: model identifier accepted by that provider.
- `NOVA_API_KEY`: provider key, if required.
- `NOVA_CHAT_TOKEN`, `NOVA_OWNER_TOKEN`, and `NOVA_PLUGIN_WORKER_TOKEN` are generated automatically by the setup script. Keep them private and do not commit `.env`.

Then start:

```bash
uvicorn nova.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. To review file-write approvals, open `http://127.0.0.1:8000/owner` and enter the owner token. In the chat page, enter the separate chat token in the access field. The token is kept in the browser tab's session storage.

## Docker

Run `python scripts/setup_env.py`, configure the model in `.env`, then start Docker Compose. The setup script creates the required chat, owner, and worker secrets. Docker Compose refuses to start without the worker secret. The API container runs as non-root with a read-only root filesystem, and the host port is bound to `127.0.0.1` only by default. Then run:

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

The worker currently supports only the `text_stats` declarative operation; it does not import or execute arbitrary Python plugin code. Plugins remain disabled by default in `nova/policy.json`. To try the sample plugin, run Docker Compose, then add `text_stats` to `enabled_plugins`. The worker has no published host port and is attached only to an internal Docker network. Calls require a shared bearer secret. Its container is read-only, non-root, drops all capabilities, disables privilege escalation, and has CPU, memory, PID, and temporary-filesystem limits. The API container is also non-root and read-only, with a localhost-only published port and resource limits. This is defense in depth, not a substitute for host/container security updates or independent security review.

## Development and tests

```bash
pip install -r requirements-dev.txt
python -m compileall -q nova
python -m pytest -q
```

GitHub Actions is configured to run compile checks and tests on pushes and pull requests to `main`. A successful run must be confirmed in the repository's Actions tab; the code changes alone do not prove the tests passed.

## Roadmap

1. Verify authenticated plugin execution and full Docker startup in CI.
2. Add robust memory retrieval, conversation export, and retention controls.
3. Add streaming responses and interrupt/cancel support.
4. Add controlled browser automation with explicit approval for external side effects.
5. Integrate voice input/output and live visual interaction through compatible browser and model interfaces.
6. Provide remote deployment behind TLS, backup/restore, and operational monitoring.

NOVA cannot provide unlimited free inference or compute. The owner chooses the model endpoint and remains subject to that provider's availability, limits, and terms.
