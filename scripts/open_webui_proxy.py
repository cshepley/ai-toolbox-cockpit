#!/usr/bin/env python3
"""Authenticated, model-independent OpenAI front door for Open WebUI."""

from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MODEL_ALIAS = "local-model"
MAX_BODY_BYTES = 16 * 1024 * 1024
POST_PATHS = frozenset({"/chat/completions", "/completions", "/responses", "/embeddings"})
LOG = logging.getLogger("open-webui-proxy")


class ProxyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def loaded_model(document: object) -> dict:
    """A model catalogue is not necessarily a loaded-model listing."""
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        raise ProxyError(502, "Model endpoint returned an invalid OpenAI model listing.")
    models = document["data"]
    if any(
        not isinstance(model, dict)
        or not isinstance(model.get("id"), str)
        or not model["id"].strip()
        for model in models
    ):
        raise ProxyError(502, "Model listing contains an invalid model ID.")
    explicit = [model for model in models if model.get("loaded") is True]
    candidates = explicit or [model for model in models if model.get("loaded") is not False]
    if not candidates:
        raise ProxyError(503, "No model is loaded. Start the backend on the fixed upstream endpoint.")
    if len(candidates) != 1:
        raise ProxyError(409, "Multiple models are available; the backend must identify one loaded model.")
    return candidates[0]


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], webui_url: str) -> None:
        super().__init__(address, ProxyHandler)
        self.webui_url = webui_url.rstrip("/")
        self.opener = build_opener(NoRedirects())


class ProxyHandler(BaseHTTPRequestHandler):
    server: ProxyServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        # Never log request headers, keys, prompts, or backend response bodies.
        LOG.info("%s %s", self.command, self.path.split("?", 1)[0])

    def _json(self, status: int, document: dict) -> None:
        self._response_started = True
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _request(self, path: str, authorization: str, body: bytes | None = None):
        headers = {"Authorization": authorization, "Content-Type": "application/json"}
        return self.server.opener.open(
            Request(self.server.webui_url + path, data=body, headers=headers),
            timeout=600 if body is not None else 15,
        )

    def _discover(self, authorization: str) -> dict:
        # Indexed discovery bypasses Open WebUI's aggregate model cache. Connection
        # zero is the one fixed upstream configured by the launcher.
        with self._request("/openai/models/0", authorization) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise ProxyError(502, "Model listing is too large.")
            try:
                return loaded_model(json.loads(raw))
            except (ValueError, UnicodeDecodeError) as error:
                raise ProxyError(502, "Model endpoint did not return JSON.") from error

    def _relay(self, response) -> None:
        self._response_started = True
        self.send_response(response.status)
        self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        # read1 does not wait to fill a 64 KiB buffer before releasing an SSE event.
        while chunk := response.read1(65536):
            self.wfile.write(chunk)
            self.wfile.flush()

    def _handle(self) -> None:
        self._response_started = False
        self.close_connection = True
        if self.command == "GET" and self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            self._json(401, {"error": {"message": "Use your existing Open WebUI bearer API key."}})
            return
        try:
            if self.command == "GET" and self.path == "/v1/models":
                model = self._discover(authorization)
                public_model = {
                    **model, "id": MODEL_ALIAS,
                    "object": model.get("object", "model"),
                    "created": model.get("created", 0),
                    "owned_by": model.get("owned_by", "local"),
                    "loaded_model": model["id"],
                }
                self._json(200, {"object": "list", "data": [public_model]})
                return
            path = self.path.removeprefix("/v1")
            if not self.path.startswith("/v1/") or path not in POST_PATHS or self.command != "POST":
                raise ProxyError(404, "Supported endpoints: models, chat/completions, completions, responses, embeddings.")
            if self.headers.get("Transfer-Encoding"):
                raise ProxyError(400, "Send a JSON request with Content-Length, not chunked transfer encoding.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ProxyError(400, "Invalid Content-Length.") from error
            if not 0 < length <= MAX_BODY_BYTES:
                raise ProxyError(413, "Request body must be between 1 byte and 16 MiB.")
            self.connection.settimeout(30)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ProxyError(400, "Incomplete request body.")
            try:
                document = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as error:
                raise ProxyError(400, "Request body must be JSON.") from error
            if not isinstance(document, dict):
                raise ProxyError(400, "Request body must be a JSON object.")
            if document.get("model") != MODEL_ALIAS:
                raise ProxyError(400, f"Set the client model to {MODEL_ALIAS}.")
            document["model"] = self._discover(authorization)["id"]
            try:
                response = self._request("/openai" + path, authorization, json.dumps(document).encode())
            except HTTPError as error:
                response = error
            with response:
                self._relay(response)
        except HTTPError as error:
            with error:
                self._relay(error)
        except ProxyError as error:
            LOG.warning("Request rejected: HTTP %s", error.status)
            self._json(error.status, {"error": {"message": str(error)}})
        except (URLError, TimeoutError, ConnectionError, OSError) as error:
            LOG.warning("Open WebUI connection failed: %s", type(error).__name__)
            if not self._response_started:
                self._json(502, {"error": {"message": "Open WebUI is unreachable or timed out."}})

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webui-url", default="http://127.0.0.1:8080")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    with ProxyServer((args.bind, args.port), args.webui_url) as server:
        LOG.info("OpenAI adapter listening on port %s; model alias %s", args.port, MODEL_ALIAS)
        server.serve_forever()


if __name__ == "__main__":
    main()
