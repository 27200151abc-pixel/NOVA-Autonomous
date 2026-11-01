from __future__ import annotations

import ast
import json
import operator
import sqlite3
import importlib.util
from pathlib import Path
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    nova_base_url: str = ""
    nova_api_key: str = ""
    nova_model: str = ""
    nova_timeout_seconds: float = 60
    nova_database_path: str = "./nova_memory.sqlite3"
    nova_max_history_messages: int = 20
    nova_cors_origins: str = "http://localhost:5173"
    nova_policy_path: str = "./nova/policy.json"
    nova_plugins_dir: str = "./nova/plugins"


settings = Settings()
app = FastAPI(title="NOVA API", version="0.1.0", description="Provider-neutral, self-hostable AI agent foundation")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.nova_cors_origins.split(",") if x.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    conversation_id: str | None = Field(default=None, max_length=100)


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    model: str


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.nova_database_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user','assistant')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id)")
    return conn


def remember(conversation_id: str, role: str, content: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES(?,?,?,?)",
            (conversation_id, role, content, datetime.now(timezone.utc).isoformat()),
        )


def history(conversation_id: str) -> list[dict[str, str]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, settings.nova_max_history_messages),
        ).fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]

def search_memory(query: str, limit: int = 8) -> list[dict[str, str]]:
    terms = [term.strip() for term in query.split() if term.strip()]
    if not terms:
        return []
    limit = max(1, min(int(limit), 25))
    where = " AND ".join(["content LIKE ?" for _ in terms])
    with db() as conn:
        rows = conn.execute(
            f"SELECT conversation_id, role, content FROM messages WHERE {where} ORDER BY id DESC LIMIT ?",
            [f"%{term}%" for term in terms] + [limit],
        ).fetchall()
    return [{"conversation_id": row[0], "role": row[1], "content": row[2]} for row in rows]


# Deliberately restricted arithmetic evaluator: no names, calls, attributes, or code execution.
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_calculate(expression: str) -> float | int:
    if len(expression) > 120:
        raise ValueError("Expression is too long")
    node = ast.parse(expression, mode="eval").body

    def visit(n: ast.AST) -> float | int:
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BINOPS:
            left, right = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Pow) and abs(right) > 8:
                raise ValueError("Exponent is too large")
            result = _BINOPS[type(n.op)](left, right)
            if abs(result) > 10**15:
                raise ValueError("Result is too large")
            return result
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARY:
            return _UNARY[type(n.op)](visit(n.operand))
        raise ValueError("Only basic arithmetic is allowed")

    return visit(node)


TOOL_REGISTRY = {
    "calculator": {"type": "function", "function": {"name": "calculator", "description": "Evaluate a basic arithmetic expression safely.",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False}}},
    "current_datetime": {"type": "function", "function": {"name": "current_datetime", "description": "Get the current UTC date and time.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    "memory_search": {"type": "function", "function": {"name": "memory_search", "description": "Search previous NOVA conversation messages.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"], "additionalProperties": False}}},
}


def load_policy() -> dict[str, Any]:
    defaults = {"enabled_tools": list(TOOL_REGISTRY), "enabled_plugins": [], "approval_required": [], "max_tool_calls_per_turn": 4, "max_tool_rounds": 5}
    try:
        with open(settings.nova_policy_path, "r", encoding="utf-8") as policy_file:
            configured = json.load(policy_file)
        if not isinstance(configured, dict):
            raise ValueError("Policy root must be a JSON object")
        defaults.update(configured)
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Invalid NOVA policy file: {exc}") from exc
    defaults["enabled_tools"] = [name for name in defaults.get("enabled_tools", []) if name in TOOL_REGISTRY]
    defaults["enabled_plugins"] = [str(name) for name in defaults.get("enabled_plugins", [])]
    defaults["approval_required"] = [str(name) for name in defaults.get("approval_required", [])]
    defaults["max_tool_calls_per_turn"] = max(1, min(int(defaults.get("max_tool_calls_per_turn", 4)), 50))
    defaults["max_tool_rounds"] = max(1, min(int(defaults.get("max_tool_rounds", 5)), 10))
    return defaults


def load_plugins() -> dict[str, Any]:
    policy = load_policy()
    plugin_dir = Path(settings.nova_plugins_dir)
    loaded: dict[str, Any] = {}
    for path in sorted(plugin_dir.glob("*.py")) if plugin_dir.exists() else []:
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"nova_owner_plugin_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = getattr(module, "PLUGIN", {})
        name = manifest.get("name")
        if name in policy["enabled_plugins"] and callable(getattr(module, "run", None)):
            loaded[name] = module
    return loaded


def active_tool_specs() -> list[dict[str, Any]]:
    policy = load_policy()
    specs = [TOOL_REGISTRY[name] for name in policy["enabled_tools"]]
    for name, module in load_plugins().items():
        manifest = module.PLUGIN
        specs.append({"type": "function", "function": {"name": name, "description": manifest.get("description", name), "parameters": manifest.get("parameters", {"type": "object", "properties": {}, "additionalProperties": False})}})
    return specs


def run_tool(name: str, arguments: dict[str, Any]) -> str:
    policy = load_policy()
    plugins = load_plugins()
    available = set(policy["enabled_tools"]) | set(plugins)
    if name not in available:
        raise PermissionError(f"Tool disabled or not registered: {name}")
    if name in policy["approval_required"]:
        raise PermissionError(f"Owner approval required before running: {name}")
    if name == "calculator":
        return str(safe_calculate(str(arguments.get("expression", ""))))
    if name == "current_datetime":
        return datetime.now(timezone.utc).isoformat()
    if name == "memory_search":
        return json.dumps(search_memory(str(arguments.get("query", "")), int(arguments.get("limit", 8))), ensure_ascii=False)
    if name in plugins:
        return json.dumps(plugins[name].run(arguments), ensure_ascii=False, default=str)
    raise ValueError(f"Tool is not registered: {name}")


async def ask_model(messages: list[dict[str, Any]]) -> str:
    if not (settings.nova_base_url and settings.nova_model):
        raise HTTPException(status_code=503, detail="No model configured. Set NOVA_BASE_URL and NOVA_MODEL in .env.")
    url = settings.nova_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.nova_api_key:
        headers["Authorization"] = f"Bearer {settings.nova_api_key}"
    try:
        async with httpx.AsyncClient(timeout=settings.nova_timeout_seconds) as client:
            for _round in range(load_policy()["max_tool_rounds"]):
                payload = {"model": settings.nova_model, "messages": messages, "tools": active_tool_specs(), "tool_choice": "auto"}
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                if not calls:
                    return str(message.get("content") or "The model returned an empty response.")
                allowed_calls = calls[:load_policy()["max_tool_calls_per_turn"]]
                messages.append({"role": "assistant", **{**message, "tool_calls": allowed_calls}})
                for call in allowed_calls:
                    fn = call["function"]
                    try:
                        arguments = json.loads(fn.get("arguments") or "{}")
                        if not isinstance(arguments, dict):
                            raise ValueError("Tool arguments must be a JSON object")
                        result = run_tool(fn["name"], arguments)
                    except Exception as exc:
                        result = f"Tool error: {type(exc).__name__}: {exc}"
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        return "NOVA reached the maximum tool-planning rounds. Send a follow-up to continue."
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Model request failed: {type(exc).__name__}: {exc}") from exc

@app.get("/health")
def health() -> dict[str, Any]:
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "service": "NOVA", "version": "0.2.0",
            "model_configured": bool(settings.nova_base_url and settings.nova_model)}


@app.get("/v1/owner-policy")
def owner_policy() -> dict[str, Any]:
    """Read the active owner-editable policy; editing the JSON file changes behavior."""
    return load_policy()


@app.get("/v1/memory/search")
def memory_search_endpoint(q: str, limit: int = 8) -> dict[str, Any]:
    return {"query": q, "results": search_memory(q, limit)}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    conversation_id = request.conversation_id or str(uuid.uuid4())
    remember(conversation_id, "user", request.message)
    messages = [{"role": "system", "content": "You are NOVA, a helpful and honest assistant. Be clear about uncertainty. Use only the provided tools; never claim to have performed actions you did not perform."}]
    messages.extend(history(conversation_id))
    reply = await ask_model(messages)
    remember(conversation_id, "assistant", reply)
    return ChatResponse(conversation_id=conversation_id, reply=reply, model=settings.nova_model)
