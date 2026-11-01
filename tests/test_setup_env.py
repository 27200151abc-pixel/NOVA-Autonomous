from pathlib import Path

import pytest

from scripts.setup_env import SECRET_KEYS, create_env


def test_setup_generates_distinct_secrets_and_preserves_other_settings(tmp_path):
    template = tmp_path / ".env.example"
    target = tmp_path / ".env"
    template.write_text(
        "NOVA_BASE_URL=https://example.invalid/v1\n"
        "NOVA_CHAT_TOKEN=\n"
        "NOVA_OWNER_TOKEN=\n"
        "NOVA_PLUGIN_WORKER_TOKEN=\n",
        encoding="utf-8",
    )

    create_env(template, target)
    content = target.read_text(encoding="utf-8")
    values = {}
    for key in SECRET_KEYS:
        line = next(line for line in content.splitlines() if line.startswith(key + "="))
        values[key] = line.split("=", 1)[1]

    assert all(len(value) >= 60 for value in values.values())
    assert len(set(values.values())) == len(SECRET_KEYS)
    assert "NOVA_BASE_URL=https://example.invalid/v1" in content


def test_setup_refuses_to_overwrite_existing_env(tmp_path):
    template = tmp_path / ".env.example"
    target = tmp_path / ".env"
    template.write_text("NOVA_CHAT_TOKEN=\nNOVA_OWNER_TOKEN=\nNOVA_PLUGIN_WORKER_TOKEN=\n")
    target.write_text("KEEP_ME=secret\n")

    with pytest.raises(FileExistsError):
        create_env(template, target)

    assert target.read_text(encoding="utf-8") == "KEEP_ME=secret\n"
