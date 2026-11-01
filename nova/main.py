from __future__ import annotations

import ast
import json
import operator
import sqlite3
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


TOOLS = [
    {"type": "function", "function": {"name": "calculator", "description": "Evaluate a basic arithmetic expression safely.",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "current_datetime", "description": "Get the current UTC date and time.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
]


def run_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "calculator":
        return str(safe_calculate(str(arguments.get("expression", ""))))
    if name == "current_datetime":
        return datetime.now(timezone.utc).isoformat()
    raise ValueError(f"Tool not allowed: {name}")


async def ask_model(messages: list[dict[str, str]]) -> str:
    if not (settings.nova_base_url and settings.nova_model):
        raise HTTPException(status_code=503, detail="No model configured. Set NOVA_BASE_URL and NOVA_MODEL in .env.")
    url = settings.nova_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.nova_api_key:
        headers["Authorization"] = f"Bearer {settings.nova_api_key}"
    payload: dict[str, Any] = {"model": settings.nova_model, "messages": messages, "tools": TOOLS, "tool_choice": "auto"}
    try:
        async with httpx.AsyncClient(timeout=settings.nova_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        message = data["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if calls:
            # Preserve the provider's tool-call envelope so the follow-up request is valid.
            messages.append({"role": "assistant", **message})
            for call in calls[:4]:
                fn = call["function"]
                try:
                    result = run_tool(fn["name"], json.loads(fn.get("arguments") or "{}"))
                except Exception as exc:
                    result = f"Tool error: {exc}"
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            async with httpx.AsyncClient(timeout=settings.nova_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json={
                    "model": settings.nova_model, "messages": messages, "tools": TOOLS, "tool_choice": "auto"
                })
                response.raise_for_status()
                data = response.json()
        return str(data["choices"][0]["message"].get("content") or "The model returned an empty response.")
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Model request failed: {type(exc).__name__}: {exc}") from exc


@app.get("/health")
def health() -> dict[str, Any]:
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "service": "NOVA", "version": "0.1.0",
            "model_configured": bool(settings.nova_base_url and settings.nova_model)}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    conversation_id = request.conversation_id or str(uuid.uuid4())
    remember(conversation_id, "user", request.message)
    messages = [{"role": "system", "content": "You are NOVA, a helpful and honest assistant. Be clear about uncertainty. Use only the provided tools; never claim to have performed actions you did not perform."}]
    messages.extend(history(conversation_id))
    reply = await ask_model(messages)
    remember(conversation_id, "assistant", reply)
    return ChatResponse(conversation_id=conversation_id, reply=reply, model=settings.nova_model)
