import stat
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.halogen_open_webui import (
    CONTAINER_NAME, DEFAULT_API_PORT, PROXY_CONTAINER_NAME, SetupError,
    build_proxy_cmd, build_remove_cmd, build_run_cmd, cockpit_api_endpoint,
    ensure_env_file, env_file_path, relay_reachable, save_upstream_key,
    volume_arg, wait_for_model,
)


def run_cmd(root: Path, **overrides) -> list[str]:
    defaults = dict(
        engine="podman", image="ghcr.io/open-webui/open-webui:main",
        api_host="127.0.0.1", api_port=DEFAULT_API_PORT, ui_port=8080,
        bind_address="0.0.0.0", data_dir=root / "data",
        env_file=ensure_env_file(root), relabel=True,
    )
    defaults.update(overrides)
    return build_run_cmd(**defaults)


class HalogenOpenWebUITests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def test_proxies_loopback_relay_without_rebinding_halogen(self) -> None:
        command = run_cmd(self.root)
        self.assertIn("--network=host", command)
        self.assertNotIn("-p", command)
        joined = " ".join(command)
        self.assertIn("OPENAI_API_BASE_URLS=http://127.0.0.1:8731/v1", joined)
        self.assertIn("HOST=0.0.0.0", joined)
        self.assertIn("PORT=8080", joined)
        self.assertIn("ENABLE_OLLAMA_API=false", joined)
        # Halogen itself is never reconfigured here; only its relay is consumed.
        self.assertNotIn("HALOGEN", joined)

    def test_signing_key_never_reaches_the_command_line(self) -> None:
        command = run_cmd(self.root)
        joined = " ".join(command)
        self.assertIn("--env-file", command)
        self.assertNotIn("WEBUI_SECRET_KEY", joined)
        key = env_file_path(self.root).read_text(encoding="utf-8").strip()
        self.assertTrue(key.startswith("WEBUI_SECRET_KEY="))
        self.assertNotIn(key.split("=", 1)[1], joined)

    def test_loopback_relay_host_may_be_narrowed(self) -> None:
        joined = " ".join(run_cmd(self.root, api_host="100.64.1.2", api_port=9000))
        self.assertIn("OPENAI_API_BASE_URLS=http://100.64.1.2:9000/v1", joined)

    def test_bind_may_be_restricted_to_one_interface(self) -> None:
        joined = " ".join(run_cmd(self.root, bind_address="192.168.1.20"))
        self.assertIn("HOST=192.168.1.20", joined)

    def test_engine_specific_replace_flag_only_for_podman(self) -> None:
        self.assertIn("--replace", run_cmd(self.root, engine="podman"))
        self.assertNotIn("--replace", run_cmd(self.root, engine="docker"))

    def test_restart_and_rm_are_never_combined(self) -> None:
        # Docker refuses --rm together with --restart, so the builder must pick one.
        for engine in ("podman", "docker"):
            command = run_cmd(self.root, engine=engine)
            self.assertIn("--restart", command)
            self.assertNotIn("--rm", command)

    def test_selinux_relabel_only_when_enabled(self) -> None:
        self.assertTrue(volume_arg(self.root, relabel=True).endswith(":z"))
        self.assertFalse(volume_arg(self.root, relabel=False).endswith(":z"))

    def test_signup_can_be_closed_after_first_admin(self) -> None:
        self.assertIn("ENABLE_SIGNUP=true", " ".join(run_cmd(self.root)))
        self.assertIn("ENABLE_SIGNUP=false", " ".join(run_cmd(self.root, enable_signup=False)))

    def test_api_key_passed_only_when_halogen_requires_one(self) -> None:
        self.assertIn("OPENAI_API_KEYS=unused", " ".join(run_cmd(self.root)))
        self.assertIn("OPENAI_API_KEYS=shhh", " ".join(run_cmd(self.root, api_key="shhh")))

    def test_rejects_wildcard_upstream_and_bad_ports(self) -> None:
        with self.assertRaises(SetupError):
            run_cmd(self.root, api_host="0.0.0.0")
        with self.assertRaises(SetupError):
            run_cmd(self.root, api_port=0)
        with self.assertRaises(SetupError):
            run_cmd(self.root, env_file=self.root / "missing.env")

    def test_env_file_is_created_once_with_private_mode(self) -> None:
        path = ensure_env_file(self.root)
        first = path.read_text(encoding="utf-8")
        self.assertEqual(first, ensure_env_file(self.root).read_text(encoding="utf-8"))
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertNotIn("open-webui-data", str(path))

    def test_relay_probe_reports_no_listener(self) -> None:
        self.assertFalse(relay_reachable("127.0.0.1", 1))

    def test_upstream_does_not_follow_backend_specific_saved_settings(self) -> None:
        self.assertEqual(cockpit_api_endpoint(), ("127.0.0.1", DEFAULT_API_PORT))

    def test_ipv6_upstream_has_brackets(self) -> None:
        self.assertIn("OPENAI_API_BASE_URLS=http://[::1]:8731/v1",
                      run_cmd(self.root, api_host="::1"))

    def test_model_readiness_does_not_require_a_model_name(self) -> None:
        for model in ("qwen", "deepseek", "another-engine"):
            response = io.BytesIO(json.dumps({"data": [{"id": model}]}).encode())
            with patch("scripts.halogen_open_webui.urlopen", return_value=response) as request:
                self.assertEqual(wait_for_model("127.0.0.1", 8731,
                                               api_key="existing", seconds=0), model)
                self.assertEqual(request.call_args.args[0].full_url,
                                 "http://127.0.0.1:8731/v1/models")
                self.assertEqual(request.call_args.args[0].get_header("Authorization"),
                                 "Bearer existing")

    def test_readiness_rejects_empty_ambiguous_and_malformed_listing(self) -> None:
        for listing in ({"data": []}, {"data": [{"id": "a"}, {"id": "b"}]}, {}):
            with patch("scripts.halogen_open_webui.urlopen",
                       return_value=io.BytesIO(json.dumps(listing).encode())):
                with self.assertRaises(SetupError):
                    wait_for_model("127.0.0.1", 8731, seconds=0)

    def test_upstream_secret_can_stay_in_private_env_file(self) -> None:
        path = ensure_env_file(self.root)
        original = path.read_text()
        save_upstream_key(path, "existing-upstream-key")
        self.assertIn(original.strip(), path.read_text())
        self.assertIn("OPENAI_API_KEYS=existing-upstream-key", path.read_text())
        command = run_cmd(self.root, api_key_in_env=True)
        self.assertNotIn("existing-upstream-key", " ".join(command))
        self.assertNotIn("OPENAI_API_KEYS=unused", command)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_proxy_container_reuses_webui_image_without_a_new_key(self) -> None:
        for engine in ("docker", "podman"):
            command = build_proxy_cmd(engine, "ghcr.io/open-webui/open-webui:main",
                                      ui_port=8080, proxy_port=8081,
                                      bind_address="10.0.0.170", ui_bind="0.0.0.0",
                                      relabel=False)
            self.assertIn(PROXY_CONTAINER_NAME, command)
            self.assertIn("--read-only", command)
            self.assertIn("--entrypoint", command)
            self.assertIn("http://127.0.0.1:8080", command)
            self.assertNotIn("--env-file", command)
            self.assertEqual("--replace" in command, engine == "podman")
            health = command[command.index("--health-cmd") + 1]
            self.assertIn("http://10.0.0.170:8081/health", health)
            self.assertNotIn(":8080/health", health)

    def test_database_settings_cannot_restore_stale_model_connection(self) -> None:
        command = run_cmd(self.root)
        self.assertIn("ENABLE_PERSISTENT_CONFIG=false", command)
        self.assertIn("ENABLE_API_KEYS=true", command)
        self.assertIn("ENABLE_OPENAI_API_PASSTHROUGH=true", command)
        self.assertIn("MODELS_CACHE_TTL=1", command)

    def test_wrapper_forwards_same_endpoint_to_readiness_and_start(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "scripts" / "halogen_chat.sh"
        for action in ("up", "restart", "ready", "down", "urls"):
            result = subprocess.run(
                ["bash", str(wrapper), action, "--api-port", "9123"],
                env={**os.environ, "DRY_RUN": "1", "API_PORT": "8731"},
                capture_output=True, text=True, check=True,
            )
            self.assertIn(f" {action} ", result.stdout)
            self.assertIn("--api-port 8731", result.stdout)
            self.assertTrue(result.stdout.strip().endswith("--api-port 9123"))
            self.assertNotIn("halogen-qwen", result.stdout)

    def test_down_targets_only_the_proxy_container(self) -> None:
        self.assertEqual(build_remove_cmd("podman"),
                         ["podman", "rm", "-f", CONTAINER_NAME])

    def test_data_directory_path_with_colon_is_refused(self) -> None:
        odd = self.root / "a:b"
        odd.mkdir()
        self.assertEqual(stat.S_ISDIR(odd.stat().st_mode), True)
        with self.assertRaises(SetupError):
            volume_arg(odd, relabel=False)
