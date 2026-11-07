# Model-independent Open WebUI and OpenAI proxy

The historical launcher names remain compatible:
[`halogen_chat.sh`](../scripts/halogen_chat.sh) manages Open WebUI and the
[`OpenAI adapter`](../scripts/open_webui_proxy.py). Neither starts or stops a
model server. Halogen Qwen, DS4 DeepSeek, llama.cpp, and other backends can be
switched without changing the client's model ID.

## Fixed endpoints

```text
VS Code / OpenAI client
  http://10.0.0.170:8081/v1     model: local-model
       -> Open WebUI          http://127.0.0.1:8080/openai/...
       -> active backend      http://127.0.0.1:8731/v1
Browser UI                    http://10.0.0.170:8080
```

Run the launcher on the GPU host at `10.0.0.170`. All backends must use
**127.0.0.1:8731** when switching; configure DS4's port accordingly instead of
its usual 8000. Do not point Open WebUI back at the adapter: that creates a loop.
Halogen retains its isolated container and loopback host relay.

Open WebUI's native routes are **not** `http://HOST:8080/v1`.
The adapter supplies that conventional API base on port 8081.
It queries `/openai/models/0` for every model-list and inference request,
selects the one loaded model, replaces only the request's `model`, and forwards
through Open WebUI. It does not bypass WebUI to generate responses.

Connection-indexed discovery in Open WebUI 0.13.0 requires an **administrator
API key**. Reuse the existing Open WebUI key if it belongs to your administrator;
the adapter forwards the caller's bearer key unchanged. It generates/stores no
new client key. Missing, invalid, restricted, or non-admin keys are rejected by
the adapter or Open WebUI. If endpoint restrictions are enabled, allow the
`/openai` routes. A backend's own API key is separate from the WebUI client key.

## Start, switch, stop

Start one backend in Cockpit Server Mode, bound to `127.0.0.1:8731`. Then, in
another terminal on the same GPU host:

```bash
scripts/halogen_chat.sh preview
scripts/halogen_chat.sh up
scripts/halogen_chat.sh status
scripts/halogen_chat.sh logs
scripts/halogen_chat.sh urls
```

`up` and `restart` wait up to 900 seconds for a valid OpenAI model listing,
with no Qwen/DeepSeek model name required. `ready` performs just that check.
Multiple advertised models without a unique `loaded: true` indication fail
explicitly; the adapter never guesses which model to use. Empty lists or all
models marked unloaded return 503. A backend advertising one model without
a loaded-state field is treated as serving that model; this is discovery, not
an inference benchmark.

The launcher pulls the selected WebUI image, replaces its two named containers,
and verifies both JSON health endpoints. Accounts and chat data remain intact.
It keeps the existing `ai-toolbox-cockpit-halogen-chat` name for the UI and adds
`ai-toolbox-cockpit-openai-proxy` for the adapter. The adapter reuses the WebUI
image's Python interpreter and installs no packages.

To switch: stop the old backend with Ctrl+C, start the new backend on the
**same port**, and leave both front-end containers running. Use a new conversation
when changing models; old history may contain unsupported image/tool content.
The next request rediscovers the model. A switch between discovery and generation
may fail; retry after the new server finishes loading. WebUI's aggregate routing
cache is limited to one second; an immediate switch can require a retry.

```bash
scripts/halogen_chat.sh down
```

This stops/removes only the two front-end containers, never the model server,
model files, accounts, or chats.

## Client configuration and verification

In the client's existing OpenAI-compatible provider configuration, set:

| Setting | Value |
| --- | --- |
| API base URL | `http://10.0.0.170:8081/v1` |
| Model ID | `local-model` |
| API key | Existing Open WebUI administrator API key |
| API mode | Chat Completions initially; Responses only if the backend supports it |

Use the provider's actual settings schema; property names differ between VS Code
extensions. This is a one-time change from a Qwen-specific ID. No client setting
changes are required for later backend switches.

With the existing key already in your local `OPENWEBUI_API_KEY` environment:

```bash
curl --fail --show-error http://10.0.0.170:8081/v1/models \
  -H "Authorization: Bearer $OPENWEBUI_API_KEY"
curl --fail --show-error http://10.0.0.170:8081/v1/chat/completions \
  -H "Authorization: Bearer $OPENWEBUI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-model","messages":[{"role":"user","content":"Say hello."}],"stream":false}'
```

The model list always exposes `local-model`; its `loaded_model` field shows the
current upstream ID. Backend context/modality metadata is retained when supplied.
Generation responses retain the backend's model ID and
payload. Repeat after switching Qwen to DeepSeek: the alias stays fixed and
`loaded_model` changes.

## Tools and protocol scope

Supported routes: `GET /v1/models`, `POST /v1/chat/completions`,
`POST /v1/completions`, `POST /v1/responses`, and `POST /v1/embeddings`.
JSON fields such as `tools`, `tool_choice`, `parallel_tool_calls`, tool-result
history, structured-output parameters, reasoning options, and image content
are forwarded without alteration by the adapter, apart from `model`.
SSE is flushed as it arrives, including incremental tool-call arguments.
Open WebUI may normalize parameters according to its own provider handling.

Tool calls are returned to the **client**, which executes authorized tools and
sends their results back. This route does not run Open WebUI workspace tools,
RAG pipelines, or browser-side workflows on behalf of VS Code.
The adapter does not add capabilities absent from the backend; errors and HTTP
statuses are relayed rather than silently dropping unsupported options.
An embeddings request only works if the loaded backend supports that operation.

This is not a complete implementation of every OpenAI endpoint: multipart audio,
files, batches, stored Responses retrieval/deletion, and WebSockets are not
implemented. Client-side tool, vision, and reasoning capability declarations must
match the actual loaded backend; `/v1/models` cannot reliably advertise them.
For initial GPU validation, use one model and one request at a time.

## Options and persistence

| Option/environment | Purpose |
| --- | --- |
| `--engine` / `ENGINE` | Podman or Docker; wrapper defaults to Docker. |
| `--api-host` / `API_HOST` | Fixed upstream host; defaults to 127.0.0.1. |
| `--api-port` / `API_PORT` | Fixed upstream port; defaults to 8731. |
| `--ui-port` | Browser port, default 8080. |
| `--proxy-port` | Stable client port, default 8081; must differ from other ports. |
| `--bind` | Both front-end listeners; default 0.0.0.0. |
| `--wait-seconds` / `WAIT_SECONDS` | Model-readiness budget; 0 checks once. |
| `UPSTREAM_API_KEY` | Existing backend key, only if upstream requires one. |
| `--root` | State directory; keep the same directory across restarts. |
| `ALLOW_SIGNUP=1` | First setup only; wrapper otherwise disables signup. |
| `DRY_RUN=1` | Print command only; no network calls or containers. |
| `PYTHON` | Wrapper's Python interpreter override. |

Explicit options override environment defaults for both startup and readiness.
State stays under `${XDG_STATE_HOME:-~/.local/state}/ai-toolbox-cockpit`:
`open-webui-data` contains accounts/chats, and private `open-webui.env` contains
the retained signing key and any upstream key. The launcher keeps secrets out of
its generated command preview; use environment variables rather than `--api-key`
to avoid shell-history exposure. The WebUI client key remains in its existing
account database/client configuration.

**Configuration change:** the launcher sets `ENABLE_PERSISTENT_CONFIG=false`
to prevent saved WebUI connections from overriding the fixed upstream, enables
API keys and OpenAI passthrough, and disables Ollama. Admin configuration is
environment-controlled for this deployment; saved admin settings are not applied.
Accounts, existing API-key records, and chats are not deleted. If you depend on
other saved administrator settings, review their environment equivalents before
restarting. Pin `--image` to a tested complete image reference to avoid rolling
updates; the observed LAN UI version was 0.13.0.

## Exposure and limitations

Only front-end ports need LAN access. Keep the backend loopback-only; close
signup after first setup, restrict firewall access to trusted devices, and use
TLS or a trusted tailnet off-LAN. Plain HTTP exposes bearer keys and prompts to
network observers. The adapter is a small trusted-LAN convenience, not a
public-facing hardened API gateway.

Fake-HTTP tests verify model switching, authentication, JSON/tool payloads,
streaming before generation completes, and backend errors. They do not certify
GPU inference or tool quality. On the user's GPU host at 10.0.0.170,
authenticated discovery and a benign tool-call/result round trip were also
verified through the LAN adapter with the loaded Halogen Qwen model.
DeepSeek switching and vision still require separate GPU-host validation.
See [the reboot runbook](HALOGEN_REBOOT_RUNBOOK.md).
