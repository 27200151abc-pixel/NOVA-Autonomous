import pytest

from nova.main import safe_calculate


def test_basic_arithmetic():
    assert safe_calculate("2 + 3 * 4") == 14
    assert safe_calculate("(10 - 4) / 2") == 3


def test_unary_arithmetic():
    assert safe_calculate("-5 + +2") == -3


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo unsafe')",
    "open('/etc/passwd')",
    "x + 1",
    "2 ** 99",
])
def test_rejects_unsafe_or_excessive_expressions(expression):
    with pytest.raises((ValueError, TypeError, SyntaxError)):
        safe_calculate(expression)



def test_owner_policy_can_disable_tools(tmp_path, monkeypatch):
    import json
    from nova import main

    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({
        "enabled_tools": ["calculator"],
        "approval_required": [],
        "max_tool_calls_per_turn": 7
    }), encoding="utf-8")
    monkeypatch.setattr(main.settings, "nova_policy_path", str(policy_file))
    policy = main.load_policy()
    assert policy["enabled_tools"] == ["calculator"]
    assert policy["max_tool_calls_per_turn"] == 7
    with pytest.raises(PermissionError):
        main.run_tool("current_datetime", {})

def test_memory_search_finds_previous_messages(tmp_path, monkeypatch):
    from nova import main

    monkeypatch.setattr(main.settings, "nova_database_path", str(tmp_path / "memory.sqlite3"))
    main.remember("conversation-a", "user", "NOVA should remember this project")
    results = main.search_memory("remember this")
    assert len(results) == 1
    assert results[0]["conversation_id"] == "conversation-a"


def test_enabled_plugin_is_loaded_and_executable(tmp_path, monkeypatch):
    import json
    from nova import main

    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "sample.py").write_text(
        "PLUGIN = {'name': 'sample', 'description': 'sample', "
        "'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}\n"
        "def run(arguments): return {'ok': True}\n",
        encoding="utf-8",
    )
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "enabled_tools": [],
        "enabled_plugins": ["sample"],
        "approval_required": [],
        "max_tool_calls_per_turn": 3
    }), encoding="utf-8")
    monkeypatch.setattr(main.settings, "nova_policy_path", str(policy))
    monkeypatch.setattr(main.settings, "nova_plugins_dir", str(plugins))
    assert "sample" in main.load_plugins()
    assert main.run_tool("sample", {}) == '{"ok": true}'


def test_owner_endpoints_require_token(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from nova import main

    monkeypatch.setattr(main.settings, "nova_owner_token", "test-secret")
    with pytest.raises(HTTPException) as error:
        main.require_owner("Bearer wrong")
    assert error.value.status_code == 401
    assert main.require_owner("Bearer test-secret") is None


def test_approval_queue_executes_only_after_owner_approval(tmp_path, monkeypatch):
    import json
    import sqlite3
    from nova import main

    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({
        "enabled_tools": ["calculator"],
        "enabled_plugins": [],
        "approval_required": ["calculator"],
        "max_tool_calls_per_turn": 2,
        "max_tool_rounds": 2
    }), encoding="utf-8")
    monkeypatch.setattr(main.settings, "nova_policy_path", str(policy_file))
    monkeypatch.setattr(main.settings, "nova_plugins_dir", str(tmp_path / "no-plugins"))
    monkeypatch.setattr(main.settings, "nova_database_path", str(tmp_path / "approvals.sqlite3"))

    pending = json.loads(main.run_tool("calculator", {"expression": "6 * 7"}))
    assert pending["status"] == "pending_owner_approval"
    with sqlite3.connect(main.settings.nova_database_path) as conn:
        row = conn.execute("SELECT status FROM approvals WHERE id=?", (pending["approval_id"],)).fetchone()
    assert row[0] == "pending"

    result = main.decide_approval(pending["approval_id"], main.ApprovalDecision(decision="approve"))
    assert result["status"] == "approved"
    assert result["result"] == "42"
    with sqlite3.connect(main.settings.nova_database_path) as conn:
        row = conn.execute("SELECT status FROM approvals WHERE id=?", (pending["approval_id"],)).fetchone()
    assert row[0] == "approved"


def test_workspace_tools_restrict_paths_and_read_write(tmp_path, monkeypatch):
    from nova import main

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(main.settings, "nova_workspace_root", str(workspace))

    assert main.workspace_read("note.txt")["content"] == "hello"
    assert main.workspace_list(".")["entries"][0]["name"] == "note.txt"
    with pytest.raises(ValueError):
        main.workspace_read("../outside.txt")
    with pytest.raises(ValueError):
        main.workspace_write("../outside.txt", "no")
    assert main.workspace_write("new.txt", "NOVA")["bytes_written"] == 4
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "NOVA"


def test_workspace_write_is_approval_gated_by_default(tmp_path, monkeypatch):
    import json
    from nova import main

    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({
        "enabled_tools": ["workspace_write"],
        "enabled_plugins": [],
        "approval_required": ["workspace_write"],
        "max_tool_calls_per_turn": 2,
        "max_tool_rounds": 2
    }), encoding="utf-8")
    monkeypatch.setattr(main.settings, "nova_policy_path", str(policy_file))
    monkeypatch.setattr(main.settings, "nova_plugins_dir", str(tmp_path / "no-plugins"))
    monkeypatch.setattr(main.settings, "nova_database_path", str(tmp_path / "approvals.sqlite3"))

    pending = json.loads(main.run_tool("workspace_write", {"path": "x.txt", "content": "test"}))
    assert pending["status"] == "pending_owner_approval"
    assert not (tmp_path / "x.txt").exists()


def test_root_serves_chat_ui():
    from fastapi.testclient import TestClient
    from nova.main import app

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "NOVA" in response.text
    assert 'id="chat-form"' in response.text


def test_workspace_blocks_symbolic_links(tmp_path, monkeypatch):
    from nova import main

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "shortcut.txt"
    link.symlink_to(outside)
    monkeypatch.setattr(main.settings, "nova_workspace_root", str(workspace))

    with pytest.raises(ValueError):
        main.workspace_read("shortcut.txt")
    with pytest.raises(ValueError):
        main.workspace_write("shortcut.txt", "overwrite")
    assert outside.read_text(encoding="utf-8") == "secret"


def test_owner_route_serves_console():
    from fastapi.testclient import TestClient
    from nova.main import app

    response = TestClient(app).get("/owner")
    assert response.status_code == 200
    assert "NOVA_OWNER_TOKEN" in response.text
    assert "approval" in response.text.lower()


def test_chat_api_requires_separate_token(monkeypatch):
    from fastapi import HTTPException
    from nova import main

    monkeypatch.setattr(main.settings, "nova_chat_token", "chat-secret")
    with pytest.raises(HTTPException) as error:
        main.require_chat("Bearer owner-secret")
    assert error.value.status_code == 401
    assert main.require_chat("Bearer chat-secret") is None


def test_tool_call_budget_is_total_across_rounds(monkeypatch):
    import asyncio
    from nova import main

    monkeypatch.setattr(main.settings, "nova_base_url", "https://model.invalid/v1")
    monkeypatch.setattr(main.settings, "nova_model", "test-model")
    monkeypatch.setattr(main, "load_policy", lambda: {
        "enabled_tools": ["calculator"],
        "enabled_plugins": [],
        "approval_required": [],
        "max_tool_calls_per_turn": 2,
        "max_tool_rounds": 5,
    })
    executed = []

    class FakeResponse:
        def __init__(self, message):
            self.message = message

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": self.message}]}

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = [
                FakeResponse({"role": "assistant", "tool_calls": [
                    {"id": "call-1", "function": {"name": "calculator", "arguments": '{"expression":"1+1"}'}},
                    {"id": "call-2", "function": {"name": "calculator", "arguments": '{"expression":"2+2"}'}},
                ]}),
                FakeResponse({"role": "assistant", "tool_calls": [
                    {"id": "call-3", "function": {"name": "calculator", "arguments": '{"expression":"3+3"}'}},
                ]}),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return self.responses.pop(0)

    original_run_tool = main.run_tool

    def record_tool(name, arguments):
        executed.append(arguments["expression"])
        return str(original_run_tool(name, arguments))

    monkeypatch.setattr(main, "run_tool", record_tool)
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)

    reply = asyncio.run(main.ask_model([{"role": "user", "content": "calculate"}]))
    assert len(executed) == 2
    assert reply == "NOVA reached the maximum tool-call budget for this turn. Send a follow-up to continue."


def test_database_parent_is_created_and_history_limit_is_bounded(tmp_path, monkeypatch):
    from nova import main

    database = tmp_path / "missing" / "nested" / "nova.sqlite3"
    monkeypatch.setattr(main.settings, "nova_database_path", str(database))
    monkeypatch.setattr(main.settings, "nova_max_history_messages", 0)
    main.remember("conversation-b", "user", "first")
    main.remember("conversation-b", "assistant", "second")

    assert database.exists()
    assert main.history("conversation-b") == [{"role": "assistant", "content": "second"}]
