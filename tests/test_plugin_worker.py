import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin-worker"))
import server


def test_text_stats_plugin_counts_text(tmp_path, monkeypatch):
    (tmp_path / "text_stats.json").write_text(json.dumps({
        "name": "text_stats",
        "operation": "text_stats"
    }), encoding="utf-8")
    monkeypatch.setattr(server, "PLUGIN_DIR", tmp_path)

    assert server.execute("text_stats", {"text": "a b\nc"}) == {
        "characters": 5,
        "words": 3,
        "lines": 2
    }


def test_worker_rejects_unknown_operations(tmp_path, monkeypatch):
    (tmp_path / "unknown.json").write_text(json.dumps({
        "name": "unknown",
        "operation": "arbitrary_python"
    }), encoding="utf-8")
    monkeypatch.setattr(server, "PLUGIN_DIR", tmp_path)

    try:
        server.execute("unknown", {})
    except ValueError as error:
        assert "Unsupported plugin operation" in str(error)
    else:
        raise AssertionError("Unknown operations must be rejected")


def test_worker_enforces_text_size_limit(tmp_path, monkeypatch):
    (tmp_path / "text_stats.json").write_text(json.dumps({
        "name": "text_stats",
        "operation": "text_stats"
    }), encoding="utf-8")
    monkeypatch.setattr(server, "PLUGIN_DIR", tmp_path)

    try:
        server.execute("text_stats", {"text": "x" * (server.MAX_TEXT + 1)})
    except ValueError:
        pass
    else:
        raise AssertionError("Oversized text must be rejected")



def test_worker_requires_shared_secret():
    assert server.is_authorized("Bearer correct-secret", "correct-secret")
    assert not server.is_authorized("Bearer wrong-secret", "correct-secret")
    assert not server.is_authorized(None, "correct-secret")
    assert not server.is_authorized("Bearer anything", "")


def test_text_stats_rejects_unexpected_arguments(tmp_path, monkeypatch):
    (tmp_path / "text_stats.json").write_text(json.dumps({
        "name": "text_stats",
        "operation": "text_stats"
    }), encoding="utf-8")
    monkeypatch.setattr(server, "PLUGIN_DIR", tmp_path)

    try:
        server.execute("text_stats", {"text": "hello", "extra": "no"})
    except ValueError as error:
        assert "only the text argument" in str(error)
    else:
        raise AssertionError("Unexpected plugin arguments must be rejected")
