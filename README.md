# NOVA — Open, self-hostable AI agent

NOVA is an independent, provider-agnostic agent foundation. The project is designed to run locally or on a user-controlled host, with optional remote model inference through any OpenAI-compatible endpoint.

> **Status:** Phase 1 foundation. This is an early working scaffold, not yet a fully autonomous agent. Free hosting and free inference are quota-limited; no service is represented as unlimited.

## Principles
- Open-source NOVA code (MIT); third-party models and services retain their own licenses and terms.
- Provider-neutral model adapter: configure `NOVA_BASE_URL`, `NOVA_API_KEY`, and `NOVA_MODEL`.
- Local SQLite conversation history.
- Explicit allow-list of tools; no arbitrary shell execution or hidden background actions.
- High-impact actions require a future approval gate before execution.

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

## Roadmap
1. **Foundation:** independent API, configuration, health checks, SQLite memory, provider adapter.
2. Tool execution with strict schemas, per-tool permissions, and human approval.
3. Web/browser automation in a sandbox with domain and action policies.
4. Retrieval memory, task planning, retries, observability, and evaluation tests.
5. Optional web UI and deployment recipes.

## Security
Never commit `.env`, API keys, personal data, or database files. Do not expose the API publicly without authentication, rate limiting, TLS, and network restrictions. NOVA does not execute arbitrary code.

## License
NOVA-authored code is MIT licensed. See [LICENSE](LICENSE).