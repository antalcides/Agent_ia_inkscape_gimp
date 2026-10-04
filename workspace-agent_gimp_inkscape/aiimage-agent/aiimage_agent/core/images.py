"""Lectura de dimensiones/formato de imágenes con solo la librería estándar.

Se usa para (a) informar al modelo del tamaño real de un bitmap adjunto,
(b) previsualizar sin depender de Pillow y (c) validar exportaciones.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional, Tuple

MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"BM": "bmp",
    b"II*\x00": "tiff",
    b"MM\x00*": "tiff",
    b"RIFF": "webp",
    b"\x00\x00\x01\x00": "ico",
}


def sniff(path: str | Path) -> str:
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return ""
    for magic, name in MAGIC.items():
        if head.startswith(magic):
            if name == "webp":
                try:
                    with open(path, "rb") as fh2:
                        return "webp" if fh2.read(16)[8:12] == b"WEBP" else ""
                except OSError:
                    return ""
            return name
    head_l = head.lower()
    if head_l.startswith(b"<?xml") or b"<svg" in _read(path, 4096).lower():
        return "svg"
    return ""


def _read(path: str | Path, n: int) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def image_size(path: str | Path) -> Optional[Tuple[int, int]]:
    """(ancho, alto) en píxeles, o None si no se puede determinar."""
    p = Path(path)
    kind = sniff(p)
    if kind == "png":
        raw = _read(p, 33)
        if len(raw) >= 33 and raw[12:16] == b"IHDR":
            w, h = struct.unpack(">II", raw[16:24])
            return (int(w), int(h)) if w and h else None
        return None
    if kind == "gif":
        raw = _read(p, 10)
        if len(raw) >= 10:
            return struct.unpack("<HH", raw[6:10])
        return None
    if kind == "bmp":
        raw = _read(p, 26)
        if len(raw) >= 26:
            w, h = struct.unpack("<ii", raw[18:26])
            return (abs(int(w)), abs(int(h)))
        return None
    if kind == "ico":
        raw = _read(p, 22)
        if len(raw) >= 22:
            w, h = struct.unpack("<BB", raw[6:8])
            return (w or 256, h or 256)
        return None
    if kind == "jpeg":
        return _jpeg_size(p)
    if kind == "tiff":
        raw = _read(p, 8)
        if len(raw) < 8:
            return None
        little = raw[:2] == b"II"
        off = struct.unpack("<I" if little else ">I", raw[4:8])[0]
        hdr = _read_at(p, off, 2 + 12 * 24)
        if len(hdr) < 2:
            return None
        fmt = "<" if little else ">"
        n = struct.unpack(fmt + "H", hdr[:2])[0]
        out: dict[int, int] = {}
        for i in range(min(n, 24)):
            e = hdr[2 + i * 12 : 14 + i * 12]
            if len(e) < 12:
                break
            tag, typ = struct.unpack(fmt + "HH", e[:4])
            if tag in (256, 257) and typ == 3:
                out[tag] = struct.unpack(fmt + "H", e[8:10])[0]
            elif tag in (256, 257) and typ == 4:
                out[tag] = struct.unpack(fmt + "I", e[8:12])[0]
        if 256 in out and 257 in out:
            return (int(out[256]), int(out[257]))
        return None
    if kind == "webp":
        raw = _read(p, 30)
        if len(raw) < 30:
            return None
        fourcc = raw[12:16]
        if fourcc == b"VP8X":
            w = 1 + int.from_bytes(raw[24:27], "little")
            h = 1 + int.from_bytes(raw[27:30], "little")
            return (w, h)
        if fourcc == b"VP8L":
            bits = struct.unpack("<I", raw[21:25])[0]
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if fourcc == b"VP8 ":
            return (int.from_bytes(raw[26:28], "little") & 0x3FFF,
                    int.from_bytes(raw[28:30], "little") & 0x3FFF)
    return None


def _jpeg_size(p: Path) -> Optional[Tuple[int, int]]:
    try:
        with open(p, "rb") as fh:
            if fh.read(2) != b"\xff\xd8":
                return None
            while True:
                marker = fh.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                code = marker[1]
                if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                    continue
                seg = fh.read(2)
                if len(seg) < 2:
                    return None
                length = struct.unpack(">H", seg)[0]
                if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                    data = fh.read(length - 2)
                    if len(data) >= 5:
                        h, w = struct.unpack(">HH", data[1:5])
                        return (int(w), int(h))
                    return None
                fh.seek(length - 2, 1)
                if code == 0xDA:  # start of scan: ya no hay metadatos de tamaño
                    return None
    except (OSError, struct.error):
        return None


def _read_at(p: Path, offset: int, n: int) -> bytes:
    try:
        with open(p, "rb") as fh:
            fh.seek(offset)
            return fh.read(n)
    except OSError:
        return b""


def write_png(path: str | Path, width: int, height: int,
              color: Tuple[int, int, int, int] = (210, 210, 215, 255)) -> Path:
    """Escribe un PNG RGBA real (gradiente a cuadros) con zlib: sirve para stubs y pruebas."""
    width, height = max(int(width), 2), max(int(height), 2)
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            shade = 1.0 if (x // 8 + y // 8) % 2 == 0 else 0.75
            rgba = tuple(max(0, min(255, int(c * shade))) for c in color)
            row += struct.pack("4B", *rgba)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return p


def describe(path: str | Path) -> str:
    """Descripción compacta para logs/prompts: 'foto.png [jpeg 1920×1080, 480 KB]'."""
    p = Path(path)
    kind = sniff(p) or "?"
    size = image_size(p)
    try:
        kb = p.stat().st_size // 1024
    except OSError:
        kb = 0
    dims = f"{size[0]}×{size[1]} px, " if size else ""
    return f"{p.name} [{kind} {dims}{kb} KB]"
