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
