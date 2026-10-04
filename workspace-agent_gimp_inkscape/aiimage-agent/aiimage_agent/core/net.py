"""HTTP mínimo sobre la librería estándar: JSON requests + streaming SSE.

Sin dependencias externas (ni `requests`) para que PyInstaller y Flatpak sean triviales.
"""

from __future__ import annotations

import gzip
import io
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

DEFAULT_TIMEOUT = 120.0
USER_AGENT = "AIImageAgent/1.0 (+inkscape; +gimp)"


class NetError(RuntimeError):
    """Error de red/HTTP con mensaje legible para la GUI."""

    def __init__(self, message: str, *, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _ssl_context(verify: bool = True) -> ssl.SSLContext:
    if verify:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _opener(timeout: float, verify: bool = True) -> urllib.request.OpenerDirector:
    handlers: List[urllib.request.BaseHandler] = [
        urllib.request.HTTPSHandler(context=_ssl_context(verify))
    ]
    # urllib respeta proxies del entorno por defecto; no añadimos ProxyHandler.
    return urllib.request.build_opener(*handlers)


def request(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Any] = None,
    timeout: float = DEFAULT_TIMEOUT,
    verify: bool = True,
    retries: int = 1,
) -> Dict[str, Any]:
    """Peticion HTTP que devuelve JSON (dict). Reintenta 1 vez en 429/5xx."""
    body: Optional[bytes] = None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    last: Optional[NetError] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            with _opener(timeout, verify).open(req, timeout=timeout) as resp:
                raw = _maybe_gunzip(resp.read(), resp.headers.get("Content-Encoding"))
            if not raw.strip():
                return {}
            data = json.loads(raw.decode("utf-8", "replace"))
            return data if isinstance(data, dict) else {"data": data}
        except urllib.error.HTTPError as exc:
            raw = _maybe_gunzip(exc.read() or b"", exc.headers.get("Content-Encoding") if exc.headers else None)
            detail = _error_detail(raw)
            err = NetError(
                f"HTTP {exc.code} en {url}\n{detail}",
                status=exc.code,
                body=raw.decode("utf-8", "replace")[:4000],
            )
            if exc.code in (408, 409, 425, 429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = err
                continue
            raise err from None
        except urllib.error.URLError as exc:
            raise NetError(
                f"No se pudo conectar a {url}\n"
                f"Motivo: {exc.reason}\n"
                "¿Está el servidor local encendido (Ollama / LM Studio / OmniRoute) "
                "y la URL base correcta?",
                status=0,
            ) from None
        except TimeoutError as exc:
            raise NetError(f"Timeout ({timeout:.0f}s) al llamar {url}") from exc
        except json.JSONDecodeError as exc:
            raise NetError(f"El proveedor devolvió JSON inválido: {exc}") from None
    assert last is not None
    raise last


def _maybe_gunzip(raw: bytes, encoding: Optional[str]) -> bytes:
    if not raw or (encoding or "").lower() not in ("gzip", "x-gzip"):
        return raw
    try:
        return gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    except OSError:
        return raw


def _error_detail(raw: bytes) -> str:
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", "replace")[:1500]
    if isinstance(obj, dict):
        err = obj.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)
        if err:
            return str(err)
        if obj.get("detail"):
            return str(obj["detail"])
    return json.dumps(obj)[:1500]


def stream_sse(
    url: str,
    *,
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Any] = None,
    timeout: float = DEFAULT_TIMEOUT,
    verify: bool = True,
    on_event: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
) -> Iterator[str]:
    """Itera trozos de texto desde una respuesta `text/event-stream`.

    `on_event` recibe cada JSON de un `data:` y puede devolver el texto a emitir
    (str) o None para no emitir nada.
    """
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "text/event-stream, application/json",
        **(headers or {}),
    }
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        resp = _opener(timeout, verify).open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raw = _maybe_gunzip(exc.read() or b"", exc.headers.get("Content-Encoding") if exc.headers else None)
        raise NetError(f"HTTP {exc.code} en {url}\n{_error_detail(raw)}", status=exc.code) from None
    except urllib.error.URLError as exc:
        raise NetError(
            f"No se pudo conectar a {url}\nMotivo: {exc.reason}\n"
            "Revisa la URL base y que el servicio local esté corriendo."
        ) from None

    with resp:
        encoding = resp.headers.get("Content-Encoding")
        reader = io.TextIOWrapper(resp, encoding="utf-8", errors="replace", newline="")
        if (encoding or "").lower() in ("gzip", "x-gzip"):  # pragma: no cover - poco común
            reader = io.TextIOWrapper(
                gzip.GzipFile(fileobj=resp), encoding="utf-8", errors="replace", newline=""
            )
        data_lines: List[str] = []
        for line in reader:
            line = line.rstrip("\r\n")
            if not line:
                for chunk in _flush(data_lines, on_event):
                    yield chunk
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        for chunk in _flush(data_lines, on_event):
            yield chunk


def _flush(data_lines: List[str], on_event: Optional[Callable[[Dict[str, Any]], Optional[str]]]) -> List[str]:
    out: List[str] = []
    for raw in data_lines:
        if raw.strip() in ("[DONE]", "done"):
            return out
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if on_event is None:
            text = obj.get("content") or obj.get("delta") or ""
            if isinstance(text, str) and text:
                out.append(text)
            continue
        res = on_event(obj)
        if res:
            out.append(res)
    return out


def stream_ndjson(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Any] = None,
    timeout: float = DEFAULT_TIMEOUT,
    verify: bool = True,
    on_obj: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
) -> Iterator[str]:
    """Streaming de respuestas "JSON por línea" (Ollama /api/chat, /api/generate)."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/x-ndjson, application/json", **(headers or {})}
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        resp = _opener(timeout, verify).open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raw = _maybe_gunzip(exc.read() or b"", exc.headers.get("Content-Encoding") if exc.headers else None)
        raise NetError(f"HTTP {exc.code} en {url}\n{_error_detail(raw)}", status=exc.code) from None
    except urllib.error.URLError as exc:
        raise NetError(
            f"No se pudo conectar a {url}\nMotivo: {exc.reason}\n"
            "Revisa la URL base y que el servicio local esté corriendo."
        ) from None
    with resp, io.TextIOWrapper(resp, encoding="utf-8", errors="replace") as reader:
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            text = on_obj(obj) if on_obj else (obj.get("message", {}).get("content") or obj.get("response") or "")
            if text:
                yield text
            if obj.get("done"):
                return


def url_join(base: str, path: str) -> str:
    """Une base + path sin duplicar barras (acepta bases con o sin /v1)."""
    base = (base or "").rstrip("/")
    if path.startswith("/"):
        return base + path
    return f"{base}/{path}"


def is_local(base_url: str) -> bool:
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local")
