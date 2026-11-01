from __future__ import annotations

import ast
import json
import operator
import sqlite3
import secrets
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
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
    nova_owner_token: str = ""
    nova_chat_token: str = ""
    nova_workspace_root: str = "./workspace"


settings = Settings()
app = FastAPI(title="NOVA API", version="0.4.0", description="Provider-neutral, self-hostable AI agent foundation")
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


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


@contextmanager
def db():
    conn = sqlite3.connect(settings.nova_database_path, timeout=15)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, arguments TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','executing','approved','rejected','failed')),
            result TEXT, created_at TEXT NOT NULL, decided_at TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at)")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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


def workspace_path(relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute() or any(part in {"..", ""} for part in raw.parts):
        if str(relative_path) not in {"", "."}:
            raise ValueError("Workspace paths must be relative and cannot traverse parent directories.")
    root = Path(settings.nova_workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / raw).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes the NOVA workspace.")
    current = root
    for part in raw.parts:
        if part in {"", "."}:
            continue
        current = current / part
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in the NOVA workspace.")
    return candidate


def workspace_list(relative_path: str = ".") -> dict[str, Any]:
    directory = workspace_path(relative_path)
    if not directory.exists() or not directory.is_dir():
        raise ValueError("Workspace directory does not exist.")
    entries = []
    for item in sorted(directory.iterdir(), key=lambda p: p.name.lower())[:200]:
        if item.is_symlink():
            kind = "symlink_blocked"
        elif item.is_dir():
            kind = "directory"
        elif item.is_file():
            kind = "file"
        else:
            kind = "other"
        entries.append({"name": item.name, "type": kind, "size": item.stat().st_size if kind == "file" else None})
    return {"path": relative_path or ".", "entries": entries, "truncated": len(list(directory.iterdir())) > 200}


def workspace_read(relative_path: str) -> dict[str, Any]:
    target = workspace_path(relative_path)
    if not target.exists() or not target.is_file() or target.is_symlink():
        raise ValueError("Workspace file does not exist or is not a regular file.")
    if target.stat().st_size > 131072:
        raise ValueError("File exceeds the 128 KiB read limit.")
    return {"path": relative_path, "content": target.read_text(encoding="utf-8")}


def workspace_write(relative_path: str, content: str) -> dict[str, Any]:
    target = workspace_path(relative_path)
    if target == Path(settings.nova_workspace_root).resolve():
        raise ValueError("A file path is required.")
    if len(content.encode("utf-8")) > 131072:
        raise ValueError("Content exceeds the 128 KiB write limit.")
    if not target.parent.exists() or not target.parent.is_dir():
        raise ValueError("Parent directory must already exist inside the workspace.")
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise ValueError("Target must be a regular file, not a directory or symbolic link.")
    target.write_text(content, encoding="utf-8")
    return {"path": relative_path, "bytes_written": len(content.encode("utf-8"))}


TOOL_REGISTRY = {
    "calculator": {"type": "function", "function": {"name": "calculator", "description": "Evaluate a basic arithmetic expression safely.",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False}}},
    "current_datetime": {"type": "function", "function": {"name": "current_datetime", "description": "Get the current UTC date and time.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    "memory_search": {"type": "function", "function": {"name": "memory_search", "description": "Search previous NOVA conversation messages.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"], "additionalProperties": False}}},
    "workspace_list": {"type": "function", "function": {"name": "workspace_list", "description": "List files and folders inside NOVA's restricted workspace.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False}}},
    "workspace_read": {"type": "function", "function": {"name": "workspace_read", "description": "Read a UTF-8 text file inside NOVA's restricted workspace (128 KiB limit).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}}},
    "workspace_write": {"type": "function", "function": {"name": "workspace_write", "description": "Write a UTF-8 text file inside NOVA's restricted workspace. This action always requires owner approval.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}}},
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
        if path.name.startswith("_") or path.stem not in policy["enabled_plugins"]:
            continue
        spec = importlib.util.spec_from_file_location(f"nova_owner_plugin_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = getattr(module, "PLUGIN", {})
        name = manifest.get("name")
        if name == path.stem and callable(getattr(module, "run", None)):
            loaded[name] = module
    return loaded


def active_tool_specs() -> list[dict[str, Any]]:
    policy = load_policy()
    specs = [TOOL_REGISTRY[name] for name in policy["enabled_tools"]]
    for name, module in load_plugins().items():
        manifest = module.PLUGIN
        specs.append({"type": "function", "function": {"name": name, "description": manifest.get("description", name), "parameters": manifest.get("parameters", {"type": "object", "properties": {}, "additionalProperties": False})}})
    return specs


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    policy = load_policy()
    plugins = load_plugins()
    available = set(policy["enabled_tools"]) | set(plugins)
    if name not in available:
        raise PermissionError(f"Tool disabled or not registered: {name}")
    if name == "calculator":
        return str(safe_calculate(str(arguments.get("expression", ""))))
    if name == "current_datetime":
        return datetime.now(timezone.utc).isoformat()
    if name == "memory_search":
        return json.dumps(search_memory(str(arguments.get("query", "")), int(arguments.get("limit", 8))), ensure_ascii=False)
    if name == "workspace_list":
        return json.dumps(workspace_list(str(arguments.get("path", "."))), ensure_ascii=False)
    if name == "workspace_read":
        return json.dumps(workspace_read(str(arguments.get("path", ""))), ensure_ascii=False)
    if name == "workspace_write":
        return json.dumps(workspace_write(str(arguments.get("path", "")), str(arguments.get("content", ""))), ensure_ascii=False)
    if name in plugins:
        return json.dumps(plugins[name].run(arguments), ensure_ascii=False, default=str)
    raise ValueError(f"Tool is not registered: {name}")


def run_tool(name: str, arguments: dict[str, Any]) -> str:
    policy = load_policy()
    available = set(policy["enabled_tools"]) | set(load_plugins())
    if name not in available:
        raise PermissionError(f"Tool disabled or not registered: {name}")
    if name in policy["approval_required"]:
        approval_id = str(uuid.uuid4())
        with db() as conn:
            conn.execute(
                "INSERT INTO approvals(id, tool_name, arguments, status, created_at) VALUES(?,?,?,?,?)",
                (approval_id, name, json.dumps(arguments, ensure_ascii=False), "pending", datetime.now(timezone.utc).isoformat()),
            )
        return json.dumps({"status": "pending_owner_approval", "approval_id": approval_id, "tool": name}, ensure_ascii=False)
    return execute_tool(name, arguments)


def require_chat(authorization: str | None = Header(default=None)) -> None:
    if not settings.nova_chat_token:
        raise HTTPException(status_code=503, detail="Chat access is locked. Configure NOVA_CHAT_TOKEN.")
    expected = "Bearer " + settings.nova_chat_token
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Valid chat bearer token required.")


def require_owner(authorization: str | None = Header(default=None)) -> None:
    if not settings.nova_owner_token:
        raise HTTPException(status_code=503, detail="Owner endpoints are locked. Configure NOVA_OWNER_TOKEN.")
    expected = "Bearer " + settings.nova_owner_token
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Valid owner bearer token required.")


async def ask_model(messages: list[dict[str, Any]]) -> str:
    if not (settings.nova_base_url and settings.nova_model):
        raise HTTPException(status_code=503, detail="No model configured. Set NOVA_BASE_URL and NOVA_MODEL in .env.")
    url = settings.nova_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.nova_api_key:
        headers["Authorization"] = f"Bearer {settings.nova_api_key}"
    try:
        async with httpx.AsyncClient(timeout=settings.nova_timeout_seconds) as client:
            policy = load_policy()
            total_tool_calls = 0
            for _round in range(policy["max_tool_rounds"]):
                payload = {"model": settings.nova_model, "messages": messages, "tools": active_tool_specs(), "tool_choice": "auto"}
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                if not calls:
                    return str(message.get("content") or "The model returned an empty response.")
                remaining_calls = policy["max_tool_calls_per_turn"] - total_tool_calls
                if remaining_calls <= 0:
                    return "NOVA reached the maximum tool-call budget for this turn. Send a follow-up to continue."
                allowed_calls = calls[:remaining_calls]
                total_tool_calls += len(allowed_calls)
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

@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/owner", include_in_schema=False)
def owner_console() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "owner.html")


@app.get("/health")
def health() -> dict[str, Any]:
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "service": "NOVA", "version": "0.4.0",
            "model_configured": bool(settings.nova_base_url and settings.nova_model)}


@app.get("/v1/owner-policy")
def owner_policy(_: None = Depends(require_owner)) -> dict[str, Any]:
    """Read the active owner-editable policy; editing the JSON file changes behavior."""
    return load_policy()


@app.get("/v1/memory/search")
def memory_search_endpoint(q: str, limit: int = 8, _: None = Depends(require_owner)) -> dict[str, Any]:
    return {"query": q, "results": search_memory(q, limit)}


@app.get("/v1/approvals")
def list_approvals(status: str = "pending", _: None = Depends(require_owner)) -> dict[str, Any]:
    if status not in {"pending", "executing", "approved", "rejected", "failed", "all"}:
        raise HTTPException(status_code=400, detail="Invalid approval status.")
    with db() as conn:
        if status == "all":
            rows = conn.execute("SELECT id, tool_name, arguments, status, result, created_at, decided_at FROM approvals ORDER BY created_at DESC LIMIT 100").fetchall()
        else:
            rows = conn.execute("SELECT id, tool_name, arguments, status, result, created_at, decided_at FROM approvals WHERE status=? ORDER BY created_at DESC LIMIT 100", (status,)).fetchall()
    keys = ("id", "tool_name", "arguments", "status", "result", "created_at", "decided_at")
    return {"approvals": [dict(zip(keys, row)) for row in rows]}


@app.post("/v1/approvals/{approval_id}/decision")
def decide_approval(approval_id: str, decision: ApprovalDecision, _: None = Depends(require_owner)) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT tool_name, arguments, status FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Approval request not found.")
        tool_name, raw_arguments, status = row
        if status != "pending":
            raise HTTPException(status_code=409, detail=f"Approval is already {status}.")
        if decision.decision == "reject":
            changed = conn.execute(
                "UPDATE approvals SET status='rejected', result=?, decided_at=? WHERE id=? AND status='pending'",
                ("Rejected by owner.", datetime.now(timezone.utc).isoformat(), approval_id),
            ).rowcount
            if changed != 1:
                raise HTTPException(status_code=409, detail="Approval is already being processed.")
            return {"id": approval_id, "status": "rejected"}
        changed = conn.execute("UPDATE approvals SET status='executing', decided_at=? WHERE id=? AND status='pending'",
                               (datetime.now(timezone.utc).isoformat(), approval_id)).rowcount
        if changed != 1:
            raise HTTPException(status_code=409, detail="Approval is already being processed.")
    try:
        result = execute_tool(tool_name, json.loads(raw_arguments))
        final_status = "approved"
    except Exception as exc:
        result = f"Execution failed: {type(exc).__name__}: {exc}"
        final_status = "failed"
    with db() as conn:
        conn.execute("UPDATE approvals SET status=?, result=? WHERE id=? AND status='executing'",
                     (final_status, result, approval_id))
    return {"id": approval_id, "status": final_status, "result": result}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _: None = Depends(require_chat)) -> ChatResponse:
    conversation_id = request.conversation_id or str(uuid.uuid4())
    remember(conversation_id, "user", request.message)
    messages = [{"role": "system", "content": "You are NOVA, a helpful and honest assistant. For complex requests, break the task into manageable steps, use available tools when they materially help, inspect tool results, and continue until the task is complete or the configured tool-round limit is reached. Search conversation memory when earlier context is relevant. Be clear about uncertainty and never claim actions you did not perform. Do not reveal private internal reasoning; provide concise conclusions and useful progress summaries."}]
    messages.extend(history(conversation_id))
    reply = await ask_model(messages)
    remember(conversation_id, "assistant", reply)
    return ChatResponse(conversation_id=conversation_id, reply=reply, model=settings.nova_model)
