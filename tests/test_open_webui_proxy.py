import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.open_webui_proxy import MODEL_ALIAS, ProxyError, ProxyServer, loaded_model

KEY = "test-existing-webui-key"
TOOL = {"type": "function", "function": {"name": "read_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}},
}}}
EVENT = b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_1","type":"function","function":{"name":"read_file","arguments":"{}"}}]}}]}\n\n'


class FakeBackend(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, status: int, document: object) -> None:
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, self.server.listing)

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, payload))
        if self.server.failure:
            self._send(422, {"error": {"message": "Backend does not support this feature."}})
        elif payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(EVENT)
            self.wfile.flush()
            self.server.release.wait(5)
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self._send(200, {"model": payload["model"], "choices": [{
                "message": {"role": "assistant", "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }]},
            }]})


class FakeWebUI(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _forward(self, path: str, body: bytes | None = None) -> None:
        self.server.authorizations.append(self.headers.get("Authorization"))
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            body = b'{"detail":"Invalid API key"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.server.paths.append(self.path)
        try:
            response = urlopen(Request(self.server.backend + path, data=body), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            self.send_response(response.status)
            self.send_header("Content-Type", response.headers["Content-Type"])
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()

    def do_GET(self) -> None:
        self._forward("/v1/models")

    def do_POST(self) -> None:
        self._forward(self.path.replace("/openai", "/v1", 1),
                      self.rfile.read(int(self.headers["Content-Length"])))


class OpenWebUIProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        self.backend.listing = {"data": [{"id": "halogen-qwen"}]}
        self.backend.requests = []
        self.backend.failure = False
        self.backend.release = threading.Event()
        self.webui = ThreadingHTTPServer(("127.0.0.1", 0), FakeWebUI)
        self.webui.backend = f"http://127.0.0.1:{self.backend.server_port}"
        self.webui.authorizations = []
        self.webui.paths = []
        self.proxy = ProxyServer(("127.0.0.1", 0),
                                 f"http://127.0.0.1:{self.webui.server_port}")
        for server in (self.backend, self.webui, self.proxy):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.addCleanup(self.backend.release.set)

    def request(self, path: str, document: object = None, key: str = KEY):
        body = json.dumps(document).encode() if document is not None else None
        request = Request(f"http://127.0.0.1:{self.proxy.server_port}" + path, data=body,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_model_switch_changes_routing_without_changing_client(self) -> None:
        for model in ("halogen-qwen", "deepseek-q2", "another-model"):
            self.backend.listing = {"data": [{"id": model}]}
            status, listing = self.request("/v1/models")
            self.assertEqual(status, 200)
            self.assertEqual(listing["data"][0]["id"], MODEL_ALIAS)
            self.assertEqual(listing["data"][0]["loaded_model"], model)
            status, result = self.request("/v1/chat/completions", {
                "model": MODEL_ALIAS, "messages": [{"role": "user", "content": "test"}],
                "tools": [TOOL], "tool_choice": "auto", "parallel_tool_calls": False,
                "response_format": {"type": "json_object"}, "reasoning_effort": "high",
            })
            self.assertEqual(status, 200)
            self.assertEqual(result["model"], model)
            forwarded = self.backend.requests[-1][1]
            self.assertEqual(forwarded["model"], model)
            self.assertEqual(forwarded["tools"], [TOOL])
            self.assertEqual(forwarded["tool_choice"], "auto")
            self.assertFalse(forwarded["parallel_tool_calls"])
            self.assertEqual(forwarded["reasoning_effort"], "high")
            self.assertEqual(forwarded["response_format"], {"type": "json_object"})
            self.assertEqual(result["choices"][0]["message"]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(self.webui.paths.count("/openai/models/0"), 6)
        self.assertEqual(set(self.webui.authorizations), {f"Bearer {KEY}"})

    def test_model_metadata_is_preserved_under_the_stable_alias(self) -> None:
        self.backend.listing = {"data": [{
            "id": "halogen-qwen", "context_length": 262144,
            "architecture": {"input_modalities": ["text", "image"]},
        }]}
        status, listing = self.request("/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(listing["data"][0]["context_length"], 262144)
        self.assertEqual(listing["data"][0]["architecture"]["input_modalities"], ["text", "image"])

    def test_stream_releases_tool_event_before_backend_finishes(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.proxy.server_port, timeout=3)
        self.addCleanup(connection.close)
        connection.request("POST", "/v1/chat/completions",
                           json.dumps({"model": MODEL_ALIAS, "stream": True, "tools": [TOOL]}),
                           {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline(), EVENT.splitlines(keepends=True)[0])
        self.assertFalse(self.backend.release.is_set())
        self.backend.release.set()
        self.assertEqual(response.read(), b"\ndata: [DONE]\n\n")

    def test_invalid_key_is_not_bypassed(self) -> None:
        status, _ = self.request("/v1/models", key="invalid")
        self.assertEqual(status, 401)
        self.assertEqual(self.backend.requests, [])

    def test_missing_key_is_rejected_before_discovery(self) -> None:
        with self.assertRaises(HTTPError) as failure:
            urlopen(f"http://127.0.0.1:{self.proxy.server_port}/v1/models", timeout=5)
        self.assertEqual(failure.exception.code, 401)
        failure.exception.close()
        self.assertEqual(self.webui.paths, [])

    def test_empty_or_ambiguous_listing_never_picks_arbitrary_model(self) -> None:
        for listing, expected in (
            ({"data": []}, 503), ({"data": [{"id": "a"}, {"id": "b"}]}, 409),
            ({"data": [{"id": "a", "loaded": False}]}, 503),
            ({"data": [{"id": ""}]}, 502),
        ):
            self.backend.listing = listing
            status, _ = self.request("/v1/models")
            self.assertEqual(status, expected)

    def test_responses_embeddings_and_completions_use_webui(self) -> None:
        for path in ("/responses", "/embeddings", "/completions"):
            status, _ = self.request("/v1" + path, {"model": MODEL_ALIAS, "input": "test"})
            self.assertEqual(status, 200)
            self.assertEqual(self.webui.paths[-1], "/openai" + path)

    def test_backend_errors_and_multimodal_tool_history_are_preserved(self) -> None:
        self.backend.failure = True
        messages = [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,test"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "file data"},
        ]
        status, body = self.request("/v1/chat/completions", {"model": MODEL_ALIAS, "messages": messages})
        self.assertEqual(status, 422)
        self.assertIn("Backend does not support", body["error"]["message"])
        self.assertEqual(self.backend.requests[-1][1]["messages"], messages)

    def test_wrong_alias_and_invalid_json_shape_fail_explicitly(self) -> None:
        for payload in ({"model": "qwen"}, [], "test"):
            status, _ = self.request("/v1/chat/completions", payload)
            self.assertEqual(status, 400)
        self.assertEqual(self.backend.requests, [])


class LoadedModelTests(unittest.TestCase):
    def test_selects_only_explicit_loaded_model(self) -> None:
        self.assertEqual(loaded_model({"data": [
            {"id": "catalogue"}, {"id": "active", "loaded": True},
        ]})["id"], "active")

    def test_invalid_listing_fails(self) -> None:
        for value in (None, [], {"data": None}, {"data": ["model"]}):
            with self.assertRaises(ProxyError):
                loaded_model(value)
