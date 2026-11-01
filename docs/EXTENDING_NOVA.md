# Extending NOVA

NOVA separates its agent runtime from its tools and model provider.

## Owner policy

Edit `nova/policy.json` and restart NOVA (or make the change before the next request) to control registered tools:

- `enabled_tools`: registered tools the model may request.
- `approval_required`: tools that must not run until an owner-approval workflow is implemented and satisfied. In this scaffold they are safely refused.
- `max_tool_calls_per_turn`: owner-configurable cap for one model turn (1–50).

The active policy is readable at `GET /v1/owner-policy`. Unknown tool names are ignored until a corresponding implementation is registered in `TOOL_REGISTRY`.

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