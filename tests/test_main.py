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
