from __future__ import annotations

import re
import secrets
from pathlib import Path


SECRET_KEYS = (
    "NOVA_CHAT_TOKEN",
    "NOVA_OWNER_TOKEN",
    "NOVA_PLUGIN_WORKER_TOKEN",
)


def create_env(template_path: Path, target_path: Path) -> None:
    if target_path.exists():
        raise FileExistsError(f"{target_path} already exists; refusing to overwrite secrets.")
    content = template_path.read_text(encoding="utf-8")
    for key in SECRET_KEYS:
        value = secrets.token_urlsafe(48)
        pattern = rf"(?m)^{re.escape(key)}=.*$"
        content, count = re.subn(pattern, f"{key}={value}", content, count=1)
        if count != 1:
            raise ValueError(f"Missing {key} setting in environment template.")
    target_path.write_text(content, encoding="utf-8")
    try:
        target_path.chmod(0o600)
    except OSError:
        # Windows and some mounted filesystems do not support POSIX modes.
        pass


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    create_env(root / ".env.example", target)
    print("Created .env with three independent random secrets.")
    print("Now add your model provider settings to .env before starting NOVA.")


if __name__ == "__main__":
    main()
