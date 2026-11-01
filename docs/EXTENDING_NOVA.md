# Extending NOVA

NOVA separates its agent runtime from its tools and model provider.

## Owner policy

Edit `nova/policy.json` and restart NOVA (or make the change before the next request) to control registered tools:

- `enabled_tools`: registered tools the model may request.
- `approval_required`: tools that are queued and will execute only after an authenticated owner approves them.
- `max_tool_calls_per_turn`: owner-configurable cap per tool-call batch (1–50).
- `max_tool_rounds`: owner-configurable multi-step tool-planning rounds (1–10).

Owner endpoints require `Authorization: Bearer $NOVA_OWNER_TOKEN`. Set a long random `NOVA_OWNER_TOKEN`; without it, owner endpoints remain locked (HTTP 503). The active policy is readable at `GET /v1/owner-policy`. Unknown tool names are ignored until a corresponding implementation is registered in `TOOL_REGISTRY`.

## Add a tool

1. Add a JSON-schema function description to `TOOL_REGISTRY` in `nova/main.py`.
2. Implement its execution in `run_tool`.
3. Add its name to `enabled_tools` in `nova/policy.json`.
4. Add tests for valid input, invalid input, permission behavior, and side effects.
5. Document required credentials, data access, and risks.

Never put secrets in tool schemas or commit them to the repository. For network, filesystem, browser, or command-execution tools, use narrow scopes, timeouts, isolated processes/containers, and explicit owner approval for destructive or external side effects. A model's text is untrusted input; validate every tool argument in code.

## Model provider

Set `NOVA_BASE_URL`, `NOVA_MODEL`, and optionally `NOVA_API_KEY` to any compatible endpoint. The API key is optional for local endpoints. NOVA does not bundle a model or bypass provider restrictions.

## Important boundary

Owner-editable policy controls NOVA's own registered capabilities. It cannot change a model's license, a remote provider's terms, or the laws applying to the operator.
## Python plugins

Put a Python file in `nova/plugins/`. Define a `PLUGIN` manifest containing a unique `name`, `description`, and JSON Schema `parameters`, and a `run(arguments)` function. Add the plugin name to `enabled_plugins` in `nova/policy.json`. The sample `text_stats` plugin demonstrates the interface.

**Important:** enabling a Python plugin executes its code in the NOVA server process with the server's OS permissions. Only enable code you wrote or reviewed. Approval controls when `run()` is invoked; plugin import and tool-schema discovery still happen inside the server process. Isolate untrusted plugins in a restricted process/container before enabling them.

## Memory search

NOVA stores messages in SQLite. The agent can use the built-in `memory_search` tool, or you can call `GET /v1/memory/search?q=...`. This is basic keyword matching, not semantic/vector retrieval yet.

## Owner approval queue

Add a tool name to `approval_required` in `nova/policy.json`. When NOVA requests that tool, it stores a pending request and does not execute it. Authenticated owner endpoints:

- `GET /v1/approvals?status=pending` — list pending requests.
- `POST /v1/approvals/{id}/decision` with `{"decision":"approve"}` or `{"decision":"reject"}` — approve and execute once, or reject.

A request is atomically claimed before execution to prevent duplicate approvals. Approved execution re-checks that the tool is still enabled. Approval is not a sandbox: only approve actions and plugins you trust.


## Restricted workspace tools

Set `NOVA_WORKSPACE_ROOT` to the dedicated directory NOVA may access. The built-in `workspace_list`, `workspace_read`, and `workspace_write` tools do not intentionally access paths outside this root; parent traversal and symbolic links are rejected. Text file reads/writes are capped at 128 KiB and listings at 200 entries. Keep the workspace separate from application secrets and the SQLite database. `workspace_write` is included in `approval_required` by default. This is path-level application isolation, not an OS security sandbox; do not expose the service to untrusted users without container/user-level isolation.


## Phase 3 status

The API serves a standalone responsive Arabic-first chat interface at `/`. The frontend uses the persistent conversation ID returned by `/v1/chat` and renders model text as text nodes (not HTML). This is a basic non-streaming chat UI; voice/video, browser automation, and operating-system-level plugin isolation are not implemented yet.


## Chat API authentication

The chat endpoint requires a separate `NOVA_CHAT_TOKEN` bearer token. The web chat asks for this token and keeps it in tab-scoped session storage; the owner token is separate and grants access to policy, memory, and approval endpoints. Generate independent random values for both. Do not reuse either token across untrusted deployments.
