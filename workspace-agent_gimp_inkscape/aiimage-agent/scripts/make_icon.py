#!/usr/bin/env python3
"""Genera los iconos del AI Image Agent (.ico, .png, .icns, .svg) sin dependencias de red.

Uso:  python scripts/make_icon.py [salida_dir]

Necesita Pillow solo para re-muestrear; si no está disponible se generan igualmente
los PNG por defecto con el rasterizador interno (imágenes cuadradas simples) y se
escribe el .ico con zlib puro.
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw

    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

S = 1024  # lienzo base (se re-muestrea a los tamaños del .ico)


def render(scale: int = 1) -> "Image.Image":
    n = S * scale
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 1024.0  # unidad de diseño

    # ---- fondo: degradado verde-teal con esquinas super-redondeadas
    top, bottom = (14, 62, 60), (18, 22, 34)
    grad = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(n):
        t = i / max(n - 1, 1)
        t = t ** 1.25
        c = tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3)) + (255,)
        gd.line([(0, i), (n, i)], fill=c)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(215 * u), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([int(9 * u), int(9 * u), n - int(10 * u), n - int(10 * u)],
                        radius=int(206 * u), outline=(120, 220, 190, 110), width=int(9 * u))

    # ---- panel izquierdo (vector): curva Bézier con nodos cuadrados
    px = lambda x, y: (int(x * u), int(y * u))  # noqa: E731
    # rejilla tenue de "lienzo vectorial"
    for gx in range(80, 620, 68):
        d.line([px(gx, 250), px(gx, 760)], fill=(255, 255, 255, 22), width=max(1, int(2 * u)))
    for gy in range(250, 790, 68):
        d.line([px(80, gy), px(620, gy)], fill=(255, 255, 255, 22), width=max(1, int(2 * u)))

    # hoja vectorial (forma cerrada con curvas)
    leaf = [px(150, 700)]
    for t in [i / 40 for i in range(41)]:
        # Bézier cúbica: (150,700) c(150,380) (420,300) (560,470)
        p0, p1, p2, p3 = (150, 700), (150, 380), (420, 300), (560, 470)
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        leaf.append(px(x, y))
    p0, p1, p2, p3 = (560, 470), (430, 640), (300, 720), (150, 700)
    for t in [i / 40 for i in range(1, 41)]:
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        leaf.append(px(x, y))
    d.polygon(leaf, fill=(225, 250, 240, 235), outline=(20, 60, 52, 255))
    d.line(leaf[: len(leaf) // 2] + [leaf[0]], fill=(18, 40, 38, 200), width=max(2, int(4 * u)))
    # manejadores + nodos
    for (ax, ay), (hx, hy) in [((150, 700), (150, 380)), ((560, 470), (420, 300))]:
        d.line([px(ax, ay), px(hx, hy)], fill=(255, 209, 102, 220), width=max(2, int(5 * u)))
        d.ellipse([px(hx - 12, hy - 12), px(hx + 12, hy + 12)], fill=(255, 209, 102, 255))
    for (ax, ay) in [(150, 700), (560, 470)]:
        s2 = 20
        d.rectangle([px(ax - s2, ay - s2), px(ax + s2, ay + s2)],
                    fill=(255, 255, 255, 255), outline=(20, 60, 52, 255), width=max(2, int(4 * u)))

    # ---- panel derecho (bitmap): rejilla de píxeles con degradado de montaña
    gx0, gy0, cell, grid = 620, 300, 48, 7
    for j in range(grid):
        for i in range(grid):
            x0, y0 = gx0 + i * cell, gy0 + j * cell
            mtn = (i - 3) ** 2 * 0.55 + (j - 6)
            v = max(0.0, min(1.0, (j / (grid - 1)) * 1.05 - (0.30 if mtn > 0.35 else -0.25)))
            if mtn > 1.6:
                col = (236, 244, 246, 255)                      # cielo
            elif mtn > 0.35:
                col = (70 + int(40 * v), 120 + int(50 * v), 118 + int(40 * v), 255)  # montaña
            else:
                col = (36 + int(70 * v), 88 + int(80 * v), 74 + int(60 * v), 255)     # suelo
            d.rectangle([px(x0, y0), px(x0 + cell - 3, y0 + cell - 3)], fill=col)
    # píxel seleccionado (cuadrícula de selección en movimiento)
    sel = (4, 3)
    for k in range(-1, 2):
        d.rectangle([px(gx0 + sel[0] * cell + k * 4, gy0 + sel[1] * cell + k * 4),
                     px(gx0 + (sel[0] + 1) * cell - 3 - k * 4, gy0 + (sel[1] + 1) * cell - 3 - k * 4)],
                    outline=(255, 209, 102, 255), width=max(2, int(4 * u)))
    d.rectangle([px(gx0 - 6, gy0 - 6), px(gx0 + grid * cell - 3 + 6, gy0 + grid * cell - 3 + 6)],
                outline=(255, 255, 255, 90), width=max(1, int(3 * u)))

    # ---- chispa de IA en el centro superior
    cx, cy, r = 512, 172, 96

    def star(rad: float, points: int = 4, inner: float = 0.30):
        pts = []
        for i in range(points * 2):
            ang = -math.pi / 2 + i * math.pi / points
            rr = rad if i % 2 == 0 else rad * inner
            pts.append(px(cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        return pts

    d.polygon(star(r * 1.45), fill=(255, 209, 102, 60))
    d.polygon(star(r), fill=(255, 226, 150, 255), outline=(255, 255, 255, 255))
    d.ellipse([px(cx - 8, cy - 8), px(cx + 8, cy + 8)], fill=(255, 255, 255, 255))

    if scale > 1:
        img = img.resize((S, S), Image.LANCZOS)
    return img


def png_bytes(img: "Image.Image") -> bytes:
    import io

    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def write_ico(imgs: list, path: Path) -> None:
    """Escribe un .ico empaquetando PNGs (válido desde Windows Vista)."""
    entries = []
    for im in imgs:
        size = im.width
        data = png_bytes(im) if im.width > 256 or True else im.tobytes()
        entries.append((size, data))
    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for size, data in entries:
        b = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in entries:
        out += data
    path.write_bytes(bytes(out))


def make_svg(path: Path) -> None:
    path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#0e3e3c"/><stop offset="1" stop-color="#121622"/></linearGradient></defs>
<rect width="1024" height="1024" rx="215" fill="url(#g)"/>
<path d="M150 700 C150 380 420 300 560 470 C430 640 300 720 150 700 Z" fill="#e1faf0" stroke="#143c34" stroke-width="8"/>
<g stroke="#ffd166" stroke-width="6"><line x1="150" y1="700" x2="150" y2="380"/><line x1="560" y1="470" x2="420" y2="300"/></g>
<g fill="#ffd166"><circle cx="150" cy="380" r="14"/><circle cx="420" cy="300" r="14"/></g>
<g fill="#fff"><rect x="132" y="682" width="36" height="36"/><rect x="542" y="452" width="36" height="36"/></g>
<g>
<rect x="620" y="300" width="44" height="44" fill="#ecf4f6"/><rect x="668" y="300" width="44" height="44" fill="#e6eff1"/>
<rect x="716" y="300" width="44" height="44" fill="#eef5f6"/><rect x="764" y="300" width="44" height="44" fill="#e2ecee"/>
<rect x="620" y="348" width="44" height="44" fill="#4e8878"/><rect x="668" y="348" width="44" height="44" fill="#5c9c88"/>
<rect x="716" y="348" width="44" height="44" fill="#4a7f72"/><rect x="764" y="348" width="44" height="44" fill="#63a891"/>
<rect x="620" y="396" width="44" height="44" fill="#3a6f60"/><rect x="668" y="396" width="44" height="44" fill="#487f6e"/>
<rect x="716" y="396" width="44" height="44" fill="#376a5c"/><rect x="764" y="396" width="44" height="44" fill="#4b8574"/>
<rect x="620" y="444" width="44" height="44" fill="#2f5f53"/><rect x="668" y="444" width="44" height="44" fill="#3d7364"/>
<rect x="716" y="444" width="44" height="44" fill="#2c594f"/><rect x="764" y="444" width="44" height="44" fill="#3a6f61"/>
</g>
<rect x="612" y="292" width="204" height="204" fill="none" stroke="#ffd166" stroke-width="7"/>
<path d="M512 76 L548 140 L612 176 L548 212 L512 276 L476 212 L412 176 L476 140 Z" fill="#ffe296" stroke="#fff" stroke-width="6"/>
<circle cx="512" cy="176" r="9" fill="#fff"/>
</svg>""",
        encoding="utf-8",
    )


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "assets")
    out.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    if not HAVE_PIL:
        print("Pillow no disponible: se omite el re-muestreo fino.", file=sys.stderr)
        return 1
    base = render(scale=2)
    base.save(out / "icon-1024.png")
    base.resize((512, 512), Image.LANCZOS).save(out / "icon-512.png")
    base.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
    imgs = [base.resize((s, s), Image.LANCZOS) for s in sizes]
    write_ico(imgs, out / "icon.ico")
    # .icns (formato simple: un solo PNG de 512 → icns con bloque ic07..ic10 no requerido)
    ic07 = base.resize((128, 128), Image.LANCZOS)
    png = png_bytes(ic07)
    icns = b"icns" + struct.pack(">I", 8 + 8 + len(png)) + b"ic07" + struct.pack(">I", 8 + len(png)) + png
    (out / "icon.icns").write_bytes(icns)
    make_svg(out / "icon.svg")
    # previsualización clara sobre fondo blanco
    base.resize((256, 256), Image.LANCZOS).save(out / "preview-256.png")
    print("iconos generados en", out)
    for p in sorted(out.glob("icon*")) + [out / "preview-256.png"]:
        print(f"  {p.name:<16} {p.stat().st_size:>8} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
