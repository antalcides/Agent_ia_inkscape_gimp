"""Servidor HTTP que simula los 7 proveedores, para pruebas sin red ni API keys.

Registra cada petición (path, headers, body) en `MockLLM.requests` para poder
verificar que el payload/headers de cada formato son los correctos.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

PLAN_OK = {
    "summary": "Prueba: crea un logo y lo exporta.",
    "notes": ["paso 1 svg", "paso 2 gimp"],
    "explanation": "Listo.",
    "steps": [
        {"app": "inkscape", "kind": "svg", "purpose": "crear logo",
         "output": "logo.svg",
         "code": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                 "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"200\" height=\"200\" viewBox=\"0 0 200 200\">"
                 "<rect width=\"200\" height=\"200\" fill=\"#123456\"/><circle cx=\"100\" cy=\"100\" r=\"60\" fill=\"#fff\"/></svg>"},
        {"app": "gimp", "kind": "script-fu", "purpose": "convertir a png 400x400",
         "input": "logo.svg", "output": "logo.png",
         "code": "(define (ai-run)\n  (let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"{INPUT}\" \"{INPUT}\"))))\n"
                 "  (gimp-image-scale image 400 400)\n  (file-png-save RUN-NONINTERACTIVE image (car (gimp-image-get-active-drawable image)) "
                 "\"{OUTPUT}\" \"logo.png\" 0 9 1 1 1 1 1)\n  (gimp-displays-flush)))\n(ai-run)\n"},
    ],
}


class MockLLM:
    """Contenedor compartido de estado para el handler."""

    host = "127.0.0.1"
    port = 0
    requests: List[Dict[str, Any]] = []
    plan: Dict[str, Any] = PLAN_OK
    raw_response: Optional[str] = None      # si está, se devuelve tal cual
    split = ("El ", "plan ", "sigue", " aquí ", "=> ")
    server: Optional[ThreadingHTTPServer] = None
    thread: Optional[threading.Thread] = None
    fail_status: int = 0                     # >0 → el handler responde ese error

    @classmethod
    def response_text(cls) -> str:
        if cls.raw_response is not None:
            return cls.raw_response
        return "```json\n" + json.dumps(cls.plan, ensure_ascii=False) + "\n```"

    @classmethod
    def start(cls) -> str:
        cls.requests = []
        handler = _make_handler()
        cls.server = ThreadingHTTPServer((cls.host, 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        return f"http://{cls.host}:{cls.port}"

    @classmethod
    def stop(cls) -> None:
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()
        if cls.thread:
            cls.thread.join(timeout=5)

    @classmethod
    def last(cls, pattern: str = "") -> Dict[str, Any]:
        for r in reversed(cls.requests):
            if not pattern or re.search(pattern, r["path"]):
                return r
        raise AssertionError(f"no hay petición registrada que case con {pattern!r}; paths={[r['path'] for r in cls.requests]}")


def _make_handler() -> type:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # ---------- utilidades ----------
        def log_message(self, fmt: str, *args: Any) -> None:  # silencioso
            return

        def _body(self) -> Dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {"__raw__": raw.decode("utf-8", "replace")}

        def _record(self, body: Dict[str, Any]) -> Dict[str, Any]:
            rec = {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            }
            MockLLM.requests.append(rec)
            return rec

        def _send_sse(self, chunks: List[str], event_name: str = "") -> None:
            payload = b""
            for i, c in enumerate(chunks):
                obj = self._sse_obj(c, i)
                line = f"data: {json.dumps(obj)}\n\n".encode()
                if event_name:
                    line = f"event: {event_name}\n".encode() + line
                payload += line
            payload += b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _sse_obj(self, text: str, i: int) -> Dict[str, Any]:
            path = self.path
            if "/api/chat" in path:
                return {"message": {"role": "assistant", "content": text}, "done": False}
            if "messages" in path and "completions" not in path:  # anthropic
                return {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": text}}
            if "enerateContent" in path:  # gemini
                return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}
            return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None if i else "stop"}]}

        def _send_json(self, obj: Any, status: int = 200) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        # ---------- verbos ----------
        def do_GET(self) -> None:  # noqa: N802
            self._record({})
            if MockLLM.fail_status:
                self._send_json({"error": {"message": "fallo simulado"}}, MockLLM.fail_status)
                return
            p = self.path
            if p.startswith("/v1beta/models"):
                self._send_json({"models": [{"name": "models/gemini-2.5-flash",
                                             "displayName": "Gemini 2.5 Flash"},
                                            {"name": "models/gemini-2.5-pro", "displayName": "Gemini 2.5 Pro"}]})
            elif p.startswith("/v1/models") and "x-api-key" in dict((k.lower(), v) for k, v in self.headers.items()):
                self._send_json({"data": [{"id": "claude-sonnet-4.5", "display_name": "Claude Sonnet 4.5"}]})
            elif "/models" in p:
                self._send_json({"data": [{"id": "gpt-4.1-mini"}, {"id": "gpt-4o"}]})
            elif p.startswith("/api/tags"):
                self._send_json({"models": [{"name": "qwen2.5-coder:7b", "size": 4_700_000_000,
                                             "details": {"family": "qwen2"}},
                                            {"name": "llama3.1:8b", "size": 4_900_000_000}]})
            else:
                self._send_json({"data": []})

        def do_POST(self) -> None:  # noqa: N802
            body = self._body()
            self._record(body)
            if MockLLM.fail_status:
                self._send_json({"error": {"message": "fallo simulado"}}, MockLLM.fail_status)
                return
            text = MockLLM.response_text()
            if self.path.startswith("/api/chat"):
                # Ollama: NDJSON
                payload = b""
                for piece in _pieces(text):
                    payload += (json.dumps({"message": {"role": "assistant", "content": piece}, "done": False}) + "\n").encode()
                payload += json.dumps({"done": True, "total_duration": 123}).encode() + b"\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path.startswith("/v1/chat/completions") or self.path.startswith("/api/v1/chat/completions"):
                if not body.get("stream"):
                    self._send_json({"choices": [{"message": {"role": "assistant", "content": text}}],
                                     "usage": {"total_tokens": 42}})
                    return
                self._send_sse(_pieces(text))
                return
            if self.path.startswith("/v1/messages"):
                if not body.get("stream"):
                    self._send_json({"content": [{"type": "text", "text": text}], "id": "msg_mock"})
                    return
                self._send_sse(_pieces(text), event_name="content_block_delta")
                return
            if "enerateContent" in self.path:
                if "treamGenerateContent" in self.path:
                    self._send_sse(_pieces(text))
                    return
                self._send_json({"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]})
                return
            self._send_json({"choices": [{"message": {"content": text}}]})

    return Handler


def _pieces(text: str) -> List[str]:
    """Parte el texto en trozos de streaming (incluye un preámbulo de prosa para probar el parser)."""
    pre = MockLLM.split
    head = "".join(pre)
    out = [head + text[:40]]
    for i in range(40, len(text), 90):
        out.append(text[i : i + 90])
    return out
