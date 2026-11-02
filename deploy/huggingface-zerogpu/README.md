---
title: NOVA Free GPU
emoji: 🧠
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
---

# NOVA — Free GPU test deployment

This is a lightweight, password-gated Hugging Face ZeroGPU demo for NOVA.

## Configure before sharing

In **Settings → Variables and secrets**, set:

- `NOVA_ACCESS_PASSWORD` — required private access password.
- `NOVA_SYSTEM_RULES` — your owner-defined system rules.
- `NOVA_MODEL` — optional; defaults to `Qwen/Qwen3-4B`.

Do not place secrets in source code or commit them to Git.

## Hardware and quotas

This Space targets Hugging Face ZeroGPU. Free accounts currently have a small daily GPU allowance (documented as 5 minutes per 24-hour quota window); this is a demo, not an always-on unlimited server. The model is loaded once when the Space starts, while generation calls request temporary GPU time.

## Scope

This free demo currently supports text chat only. It does not yet connect to NOVA's SQLite memory, owner approval queue, isolated plugin worker, camera/video, or live voice. Do not enter sensitive information: this is a public hosted Space protected by an application password, not a private production environment.

## License

Qwen3-4B weights are Apache-2.0. See the upstream model card: https://huggingface.co/Qwen/Qwen3-4B
