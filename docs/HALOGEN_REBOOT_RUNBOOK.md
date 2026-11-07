# Reboot runbook: active model + Open WebUI proxy

Run this on the GPU host at **10.0.0.170**, using the same Linux user, container
engine, and state directory as before. The historical
[`halogen_chat.sh`](../scripts/halogen_chat.sh) name now manages both Open WebUI
and the model-independent OpenAI adapter.

## 1. Start the backend in terminal A

Start Cockpit and select the desired platform/backend/model.
Keep **Host = 127.0.0.1, Port = 8731** for every backend, including DS4.
Start Server Mode and leave terminal A open. Halogen requires Cockpit's host
relay; starting its isolated container alone does not recreate that relay.
Ctrl+C stops the selected backend.

Do not start both memory-heavy models together on a single 128 GB host.
Downloaded files being ready does not mean the inference server has loaded.

## 2. Start front ends in terminal B

```bash
scripts/halogen_chat.sh up
```

The launcher polls `/v1/models` until one loaded model is available, without
knowing its ID. It waits up to 15 minutes, then pulls/starts the two front-end
containers and verifies their JSON health endpoints. Neither the backend nor
its files are managed by this script.

```bash
scripts/halogen_chat.sh ready
scripts/halogen_chat.sh status
scripts/halogen_chat.sh logs
scripts/halogen_chat.sh urls
```

If no admin exists yet, use `ALLOW_SIGNUP=1` for first setup, create the admin,
then restart without that variable. Reuse the existing admin API key.
If the upstream itself requires authentication, supply its existing key through
`UPSTREAM_API_KEY`; that is not the client's Open WebUI key.

The existing WebUI account database and signing key are retained.
Saved admin connection settings are intentionally overridden by environment
configuration; review [persistence notes](HALOGEN_CHAT_UI.md#options-and-persistence)
if you use additional saved admin settings. Keep a previously tested image
pinned using `--image` if you do not want the rolling `main` image updated.

## 3. Verify the client path

- Browser: **http://10.0.0.170:8080**; sign in and select the discovered model.
- OpenAI-compatible client: **http://10.0.0.170:8081/v1**.
- Client model: **local-model**, not a Qwen/DeepSeek-specific ID.
- Client key: the **same existing Open WebUI administrator API key**.

Use the authenticated model-list and chat commands in
[client verification](HALOGEN_CHAT_UI.md#client-configuration-and-verification).
Confirm `loaded_model` matches the intended backend, then send a short request.
A healthy UI/adapter does not prove GPU inference works.

To switch models, stop terminal A's backend, start the next on the same 8731
port, and leave front ends and client configuration unchanged. Prefer a new
conversation. During loading requests may return 503; do not mask that failure
by changing the client model ID. Test a basic chat first, then one tool round trip.

## Shutdown and recovery

```bash
scripts/halogen_chat.sh down
```

Removes only the UI and adapter containers, retaining accounts and chats.
Stop the model separately with Ctrl+C. Both front ends use
`--restart unless-stopped`, but they cannot answer inference requests after
reboot until Cockpit's backend/relay is restarted.

| Symptom | Action |
| --- | --- |
| Cannot reach 8731 | Start the selected backend through Server Mode on the fixed port. |
| No models / 503 | Wait for loading; inspect backend startup logs. |
| Ambiguous models / 409 | Serve one model or use a backend listing with one explicit loaded model. |
| 401/403 | Reuse a valid admin WebUI key; check API-key enablement and `/openai` endpoint restrictions. |
| 404 immediately after switch | Wait a second for WebUI routing-cache expiry, then retry. |
| Backend rejects tools/Responses/vision | Use only capabilities supported by the current backend. |
| 8081 refused | Rerun `up`, inspect adapter logs, and check LAN firewall/bind settings. |
| API returns HTML | Wrong port/path; client API uses 8081/v1, browser uses 8080. |
| Accounts appear missing | Stop and verify user, engine, state root; do not create a new database. |

Do not expose plain-HTTP bearer keys outside a trusted LAN.
See [protocol scope and risks](HALOGEN_CHAT_UI.md).
