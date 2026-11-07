#!/usr/bin/env python3
"""Expose a fixed local model API through Open WebUI and a stable OpenAI alias.

Command builders are pure so they can be tested without touching containers.
Run ``up`` only on the GPU host, with the selected server already started in
Cockpit's Server Mode.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__:
    from .open_webui_proxy import ProxyError, loaded_model
else:
    from open_webui_proxy import ProxyError, loaded_model

CONTAINER_NAME = "ai-toolbox-cockpit-halogen-chat"
DEFAULT_IMAGE = "ghcr.io/open-webui/open-webui:main"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8731
DEFAULT_UI_PORT = 8080
DEFAULT_PROXY_PORT = 8081
PROXY_CONTAINER_NAME = "ai-toolbox-cockpit-openai-proxy"


class SetupError(RuntimeError):
    """A host prerequisite is missing or a value is invalid."""


def detect_engine(explicit: str = "") -> str:
    """Pick the container engine, honouring an explicit choice."""
    if explicit:
        if explicit not in {"podman", "docker"}:
            raise SetupError("Engine must be podman or docker.")
        if not shutil.which(explicit):
            raise SetupError(f"{explicit} is not installed or not on PATH.")
        return explicit
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            return candidate
    raise SetupError("Neither podman nor docker is on PATH.")


def selinux_enabled() -> bool:
    """True when an SELinux filesystem is mounted, so bind mounts need relabelling."""
    return Path("/sys/fs/selinux/enforce").exists()


def cockpit_api_endpoint() -> tuple[str, int]:
    """Keep the upstream fixed when the active backend or model changes."""
    return DEFAULT_API_HOST, DEFAULT_API_PORT


def api_url(host: str, port: int) -> str:
    return f"http://{'[' + host + ']' if ':' in host else host}:{port}/v1"


def wait_for_model(host: str, port: int, *, api_key: str = "", seconds: int = 900) -> str:
    """Require one advertised loaded model, never a predetermined model name."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            with urlopen(Request(api_url(host, port) + "/models", headers=headers), timeout=10) as response:
                model = loaded_model(json.load(response))
            print(f"Loaded model: {model['id']}", flush=True)
            return str(model["id"])
        except HTTPError as error:
            if error.code in {401, 403}:
                raise SetupError("Upstream authentication failed; supply its existing API key.") from error
            problem = f"upstream returned HTTP {error.code}"
        except ProxyError as error:
            if error.status != 503:
                raise SetupError(str(error)) from error
            problem = str(error)
        except (ValueError, URLError, TimeoutError, OSError) as error:
            problem = f"upstream unavailable or invalid model listing ({type(error).__name__})"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SetupError(f"Model not ready at {api_url(host, port)}: {problem}")
        print(f"Waiting for a loaded model: {problem}", flush=True)
        time.sleep(min(10, remaining))


def env_file_path(root: Path) -> Path:
    return root / "open-webui.env"


def ensure_env_file(root: Path) -> Path:
    """Persist a signing key on the host so logins survive container replacement."""
    path = env_file_path(root)
    try:
        existing = path.read_text(encoding="utf-8")
        if "WEBUI_SECRET_KEY=" in existing:
            path.chmod(0o600)
            return path
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"WEBUI_SECRET_KEY={secrets.token_urlsafe(32)}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def save_upstream_key(path: Path, api_key: str) -> None:
    if "\n" in api_key or "\r" in api_key:
        raise SetupError("Upstream API key cannot contain newlines.")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if not line.startswith("OPENAI_API_KEYS=")]
    path.write_text("\n".join([*lines, f"OPENAI_API_KEYS={api_key or 'unused'}"]) + "\n",
                    encoding="utf-8")
    path.chmod(0o600)


def data_directory(root: Path) -> Path:
    path = root / "open-webui-data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def volume_arg(directory: Path, *, relabel: bool) -> str:
    """Build the bind mount. Open WebUI stores its database under /app/backend/data."""
    text = str(directory.resolve())
    if ":" in text:
        raise SetupError("The Open WebUI data directory path cannot contain ':'.")
    suffix = ":z" if relabel else ""
    return f"{text}:/app/backend/data{suffix}"


def build_run_cmd(
    *,
    engine: str,
    image: str,
    api_host: str,
    api_port: int,
    ui_port: int,
    bind_address: str,
    data_dir: Path,
    env_file: Path,
    relabel: bool,
    api_key: str = "",
    enable_signup: bool = True,
    api_key_in_env: bool = False,
) -> list[str]:
    """Build a detached run command that proxies the fixed model endpoint.

    The signing key lives in ``env_file`` (mode 600) rather than the command line,
    so it stays out of process listings, previews, and shell history.
    """
    if engine not in {"podman", "docker"}:
        raise SetupError("Engine must be podman or docker.")
    if not 1 <= api_port <= 65535 or not 1 <= ui_port <= 65535:
        raise SetupError("Ports must be between 1 and 65535.")
    if not env_file.is_file():
        raise SetupError("Create the signing key env file before launching.")
    if api_host in {"0.0.0.0", "::"}:
        raise SetupError("The API host must be an address, not a wildcard.")
    environment = {
        # --network=host below: uvicorn binds the host stack, so HOST controls LAN exposure.
        "HOST": bind_address,
        "PORT": str(ui_port),
        "ENABLE_OPENAI_API": "true",
        "OPENAI_API_BASE_URLS": api_url(api_host, api_port),
        # Halogen needs no key unless HALOGEN_API_KEY is set; the field cannot be empty.
        "OPENAI_API_KEYS": api_key or "unused",
        "ENABLE_OLLAMA_API": "false",
        "ENABLE_API_KEYS": "true",
        "ENABLE_OPENAI_API_PASSTHROUGH": "true",
        "MODELS_CACHE_TTL": "1",
        # Existing database connection settings must not override this fixed URL.
        "ENABLE_PERSISTENT_CONFIG": "false",
        "ENABLE_SIGNUP": "true" if enable_signup else "false",
        "DEFAULT_USER_ROLE": "pending",
        "ANONYMIZED_TELEMETRY": "false",
        "SCARF_NO_ANALYTICS": "true",
        "DO_NOT_TRACK": "true",
    }
    if api_key_in_env:
        del environment["OPENAI_API_KEYS"]
    # No --rm: Docker rejects it alongside --restart, and keeping the stopped
    # container preserves its logs for `logs` after a crash. `down` removes it.
    command = [
        engine, "run", "-d",
        "--name", CONTAINER_NAME,
        # Host network is required: it lets the proxy reach Cockpit's loopback relay
        # and publishes Open WebUI on the LAN without a port mapping.
        "--network=host",
        "--env-file", str(env_file),
        "--volume", volume_arg(data_dir, relabel=relabel),
        "--restart", "unless-stopped",
    ]
    if engine == "podman":
        command.append("--replace")
    for key, value in environment.items():
        command.extend(["-e", f"{key}={value}"])
    return [*command, image]


def build_proxy_cmd(
    engine: str, image: str, *, ui_port: int, proxy_port: int,
    bind_address: str, ui_bind: str, relabel: bool,
) -> list[str]:
    if engine not in {"podman", "docker"}:
        raise SetupError("Engine must be podman or docker.")
    if not 1 <= proxy_port <= 65535 or proxy_port == ui_port:
        raise SetupError("Adapter port must be valid and different from the UI port.")
    script = Path(__file__).with_name("open_webui_proxy.py").resolve()
    mount = f"{script}:/opt/open_webui_proxy.py:ro" + (",z" if relabel else "")
    webui_host = "127.0.0.1" if ui_bind in {"0.0.0.0", "::"} else ui_bind
    health_host = "127.0.0.1" if bind_address in {"0.0.0.0", "::"} else bind_address
    health_command = shlex.join([
        "python3", "-c",
        "import json,urllib.request; "
        f"r=urllib.request.urlopen('http://{health_host}:{proxy_port}/health',timeout=3); "
        "assert json.load(r)['status']=='ok'",
    ])
    command = [
        engine, "run", "-d", "--name", PROXY_CONTAINER_NAME, "--network=host",
        "--restart", "unless-stopped", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--volume", mount, "--entrypoint", "python3",
        "--health-cmd", health_command, "--health-interval=30s",
        "--health-timeout=5s", "--health-start-period=10s",
    ]
    if engine == "podman":
        command.append("--replace")
    return [*command, image, "/opt/open_webui_proxy.py",
            "--webui-url", f"http://{webui_host}:{ui_port}",
            "--bind", bind_address, "--port", str(proxy_port)]


def build_logs_cmd(engine: str, *, tail: int) -> list[str]:
    return [engine, "logs", "--tail", str(tail), CONTAINER_NAME]


def build_remove_cmd(engine: str) -> list[str]:
    return [engine, "rm", "-f", CONTAINER_NAME]


def build_inspect_cmd(engine: str) -> list[str]:
    return [engine, "inspect", "--format", "{{.State.Status}} {{.Name}}", CONTAINER_NAME]


def relay_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    """True when Cockpit's Halogen API relay is already accepting connections."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(timeout)
            return probe.connect_ex((host, port)) == 0
    except OSError:
        return False


def lan_addresses() -> list[str]:
    """Best-effort host addresses that other LAN devices can reach."""
    found: list[str] = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return found


def print_preview(command: list[str], *, env_file: Path) -> None:
    print(shlex.join(command))
    print(f"\nSigning key: {env_file} (mode 600, passed with --env-file, never printed)")


def ensure_stoppable(engine: str) -> None:
    """Podman gets --replace; Docker needs the previous proxy container removed first.

    Only ever targets this script's own container name, never a Halogen server.
    """
    if engine == "podman":
        return
    subprocess.call(build_remove_cmd(engine), stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("preview", "up", "restart", "ready", "down", "status", "logs", "urls"),
                        nargs="?", default="preview")
    parser.add_argument("--engine", default="", choices=("", "podman", "docker"))
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--api-host", default=DEFAULT_API_HOST, help="Fixed model API host.")
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT, help="Fixed model API port.")
    parser.add_argument("--ui-port", type=int, default=DEFAULT_UI_PORT)
    parser.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT)
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--bind", default="0.0.0.0",
                        help="Open WebUI bind address. 0.0.0.0 exposes the chat UI to the LAN.")
    parser.add_argument("--api-key", default=os.environ.get("UPSTREAM_API_KEY", ""),
                        help="Upstream key, not the Open WebUI client key; prefer UPSTREAM_API_KEY.")
    parser.add_argument("--no-signup", action="store_true",
                        help="Disable self-registration after the first admin account exists.")
    parser.add_argument("--tail", type=int, default=60)
    parser.add_argument("--root", default="", help="State directory. Defaults under XDG_STATE_HOME.")
    args = parser.parse_args()
    if args.wait_seconds < 0:
        raise SetupError("Wait seconds must be non-negative.")
    if not 1 <= args.api_port <= 65535 or args.api_host in {"0.0.0.0", "::"}:
        raise SetupError("Use a concrete upstream host and a valid port.")
    if len({args.api_port, args.ui_port, args.proxy_port}) != 3:
        raise SetupError("Upstream, UI, and adapter ports must be different.")

    api_host, api_port = args.api_host, args.api_port
    root = Path(args.root).expanduser() if args.root else (
        Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser() / "ai-toolbox-cockpit")
    existing_env = env_file_path(root)
    if not args.api_key and existing_env.is_file():
        args.api_key = next(
            (line.split("=", 1)[1] for line in existing_env.read_text(encoding="utf-8").splitlines()
             if line.startswith("OPENAI_API_KEYS=")),
            "",
        )

    if args.action == "urls":
        print(f"local:   http://127.0.0.1:{args.ui_port}")
        for address in lan_addresses():
            print(f"LAN:     http://{address}:{args.ui_port}")
        print(f"upstream {api_url(api_host, api_port)}")
        print(f"client:  http://10.0.0.170:{args.proxy_port}/v1  model: local-model")
        return 0

    if args.action == "ready":
        wait_for_model(api_host, api_port, api_key=args.api_key, seconds=args.wait_seconds)
        return 0
    engine = detect_engine(args.engine)
    if args.action == "down":
        return remove_containers(engine)

    if args.action == "status":
        codes = [subprocess.call([engine, "inspect", "--format", "{{.State.Status}} {{.Name}}", name])
                 for name in (CONTAINER_NAME, PROXY_CONTAINER_NAME)]
        return max(codes)

    if args.action == "logs":
        codes = [subprocess.call([engine, "logs", "--tail", str(args.tail), name])
                 for name in (CONTAINER_NAME, PROXY_CONTAINER_NAME)]
        return max(codes)

    env_file = ensure_env_file(root)
    save_upstream_key(env_file, args.api_key)
    command = build_run_cmd(
        engine=engine, image=args.image, api_host=api_host, api_port=api_port,
        ui_port=args.ui_port, bind_address=args.bind,
        data_dir=data_directory(root), env_file=env_file, relabel=selinux_enabled(),
        enable_signup=not args.no_signup, api_key_in_env=True,
    )
    proxy_command = build_proxy_cmd(
        engine, args.image, ui_port=args.ui_port, proxy_port=args.proxy_port,
        bind_address=args.bind, ui_bind=args.bind, relabel=selinux_enabled(),
    )
    if args.action == "preview":
        print_preview(command, env_file=env_file)
        print_preview(proxy_command, env_file=env_file)
        print("\nNothing started. Review the command, then run:")
        print("  python scripts/halogen_open_webui.py up")
        return 0

    wait_for_model(api_host, api_port, api_key=args.api_key, seconds=args.wait_seconds)
    print(f"Pulling {args.image} ...")
    if subprocess.call([engine, "pull", args.image]):
        raise SetupError("Could not pull the Open WebUI image.")
    if remove_containers(engine):
        raise SetupError("Could not remove the previous UI/adapter containers.")
    code = subprocess.call(command)
    if code == 0:
        webui_host = "127.0.0.1" if args.bind in {"0.0.0.0", "::"} else args.bind
        try:
            wait_for_health(f"http://{webui_host}:{args.ui_port}/health")
            code = subprocess.call(proxy_command)
            if code == 0:
                wait_for_health(f"http://{webui_host}:{args.proxy_port}/health")
        except SetupError:
            remove_containers(engine)
            raise
        if code:
            remove_containers(engine)
    if code == 0:
        print("\nOpen WebUI and the OpenAI adapter passed their health checks.")
        print(f"  local:   http://127.0.0.1:{args.ui_port}")
        if args.bind in {"0.0.0.0", "::"}:
            for address in lan_addresses():
                print(f"  LAN:     http://{address}:{args.ui_port}")
        print(f"  upstream http://{api_host}:{api_port}/v1")
        print(f"  client   http://10.0.0.170:{args.proxy_port}/v1  model: local-model")
        print("Use the existing Open WebUI API key as the client bearer key.")
        print("\nThe first account created becomes admin. To close registration after that:")
        print("  scripts/halogen_chat.sh restart")
        print("Chat works only while a backend runs on the fixed upstream endpoint.")
    return code


def remove_containers(engine: str) -> int:
    """Remove only this launcher's containers; stopped/missing containers are safe."""
    for name in (PROXY_CONTAINER_NAME, CONTAINER_NAME):
        result = subprocess.run(
            [engine, "container", "ls", "-a", "--format", "{{.Names}}"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise SetupError("Cannot list containers; check container engine access.")
        if name in result.stdout.splitlines():
            code = subprocess.call([engine, "rm", "-f", name])
            if code:
                return code
    return 0


def wait_for_health(url: str, seconds: int = 120) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urlopen(url, timeout=5) as response:
                document = json.load(response)
            status = document.get("status") if isinstance(document, dict) else None
            if status is True or status == "ok":
                return
            problem = "response is not a healthy JSON status"
        except (URLError, ValueError, TimeoutError, OSError) as error:
            problem = type(error).__name__
        if time.monotonic() >= deadline:
            raise SetupError(f"Service failed its JSON health check: {url} ({problem})")
        time.sleep(1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
