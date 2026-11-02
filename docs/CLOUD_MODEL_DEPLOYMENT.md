# NOVA cloud + self-hosted model deployment

## Selected architecture

- **Agent/API:** existing NOVA FastAPI service.
- **Inference:** self-hosted vLLM OpenAI-compatible server.
- **Primary model:** `Qwen/Qwen3.6-35B-A3B-FP8` (Apache-2.0 model weights).
- **Control plane:** NOVA's owner-editable `nova/policy.json`, approval queue, chat/owner tokens, and isolated plugin worker.
- **Persistence:** existing Docker volumes for SQLite memory and workspace, plus a separate model-cache volume.

This keeps the model runtime separate from NOVA's policy and tool-execution layer. Replacing the model does not require changing the agent's policy code. The selected Qwen3.6 checkpoint is natively multimodal (text + image), but NOVA's current chat API still accepts text-only messages; image uploads and live camera/video need a separate API/UI implementation.

## GPU host requirements

This profile is for a cloud VM that you control and that has:
- Linux + Docker Engine + Docker Compose plugin.
- NVIDIA GPU and compatible NVIDIA Container Toolkit.
- Enough GPU memory for the selected 35B-A3B checkpoint and its configured context. Exact requirements depend on precision, vLLM version, concurrency, and context length. Do not assume a small free GPU instance can load it.
- Persistent disk for the downloaded model cache and NOVA's database/workspace.

**This is not a free always-on cloud deployment.** Free notebook/temporary GPU services sleep, expire, or impose quotas. Hugging Face ZeroGPU is a quota-limited Gradio execution service, not a permanent private vLLM server for this Docker Compose stack.

## Start the stack

1. Provision a GPU VM and install Docker, Compose, and NVIDIA Container Toolkit.
2. Clone this repository onto that VM.
3. Run `python scripts/setup_env.py`.
4. Keep the generated chat, owner, and plugin-worker secrets private. Do not commit `.env`.
5. Start the stack with:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up --build -d
```

The override points NOVA to the private `model` service at `http://model:8000/v1`. The model service has no published host port; only the NOVA API is published according to the base Compose file.

## Model choice

The default is `Qwen/Qwen3-30B-A3B`: 35B total parameters with about 3B activated per token, multilingual support, reasoning modes, and tool-use support. Its Hugging Face model card lists Apache-2.0. The official Qwen3.6 model card lists Apache-2.0, native image input, and vLLM >=0.19.0 support. vLLM provides an OpenAI-compatible endpoint.

If the selected GPU cannot load this checkpoint, use a smaller smaller Qwen checkpoint supported by your chosen inference engine by changing the model argument and `NOVA_MODEL` consistently. A smaller model is a capacity fallback, not an equivalent quality replacement.

## Security / owner control

- Edit `nova/policy.json` to decide which tools and plugins are enabled and which require owner approval.
- Keep the model endpoint on the private Compose network. Do not publish port 8000.
- Keep the NOVA API behind HTTPS, strong authentication, and a firewall. The base Compose file binds its host port to loopback; put a TLS reverse proxy in front of it on the same host before remote use.
- Never expose the owner token or chat token in frontend source, logs, screenshots, or public repositories.
- Model weights being open does not remove legal obligations, host-provider rules, or the need to protect systems and third parties. The owner controls NOVA's application policy, not every behavior learned by the model.

## Verification status

This profile is a deployment configuration committed to the repository. It has **not** been launched against a real GPU host in this repository's CI. Verify GPU visibility, model loading, health checks, authenticated chat, and restart/persistence on the selected host before calling it deployed.
