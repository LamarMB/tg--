"""Тонкая обёртка над reportlab.

Все координаты — в пунктах (1 мм = 2.8346 pt), ось Y направлена ВНИЗ от
верхнего края листа, как в чертеже. Так проще переносить размеры из образца.
"""
from __future__ import annotations

import os
from pathlib import Path

from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

MM = 72 / 25.4
PAGE_W, PAGE_H = landscape(A3)  # 1190.55 x 841.89

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

FONT = "Main"
_font_ready = False

# Tahoma — шрифт образца. Если он есть в системе (Windows), берём его,
# иначе — DejaVu Sans Condensed из assets (близок по ширине).
_FONT_CANDIDATES = [
    os.environ.get("SCHEMGEN_FONT", ""),
    r"C:\Windows\Fonts\tahoma.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/tahoma.ttf",
    "/Library/Fonts/Tahoma.ttf",
    str(ASSETS / "fonts" / "DejaVuSansCondensed.ttf"),
]


def ensure_font() -> None:
    global _font_ready
    if _font_ready:
        return
    for path in _FONT_CANDIDATES:
        if path and Path(path).is_file():
            pdfmetrics.registerFont(TTFont(FONT, path))
            _font_ready = True
            return
    raise RuntimeError("Не найден ни один TTF-шрифт с кириллицей")


def text_width(s: str, size: float) -> float:
    ensure_font()
    return pdfmetrics.stringWidth(s, FONT, size)


def wrap(text: str, width: float, size: float) -> list[str]:
    """Перенос по словам; слишком длинное слово режется по '-', ';', '/'."""
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            cand = w if not cur else f"{cur} {w}"
            if text_width(cand, size) <= width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            # слово само не влезает — режем по разделителям/символам
            while text_width(w, size) > width:
                cut = _split_long(w, width, size)
                lines.append(w[:cut])
                w = w[cut:]
            cur = w
        lines.append(cur)
    while len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return lines


def _split_long(w: str, width: float, size: float) -> int:
    """Сколько символов слова влезает в строку (с предпочтением разделителя)."""
    fit, last_sep = 1, 0
    for i in range(1, len(w)):
        if text_width(w[:i], size) > width:
            break
        fit = i
        if w[i - 1] in "-;/,":
            last_sep = i
    return last_sep or fit


class Pen:
    def __init__(self, path: str):
        ensure_font()
        self.c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
        self.c.setLineCap(0)

    # --- геометрия ---------------------------------------------------------
    def line(self, x0, y0, x1, y1, lw=0.99, dash=None):
        c = self.c
        c.setLineWidth(lw)
        c.setDash(*(dash or ([], 0)))
        c.line(x0, PAGE_H - y0, x1, PAGE_H - y1)
        if dash:
            c.setDash([], 0)

    def hline(self, x0, x1, y, lw=0.99):
        self.line(x0, y, x1, y, lw)

    def vline(self, x, y0, y1, lw=0.99):
        self.line(x, y0, x, y1, lw)

    def rect(self, x0, y0, x1, y1, lw=0.99, fill=False, stroke=True):
        self.c.setLineWidth(lw)
        self.c.rect(x0, PAGE_H - y1, x1 - x0, y1 - y0,
                    stroke=1 if stroke else 0, fill=1 if fill else 0)

    def dot(self, x, y, r=3.5):
        self.c.circle(x, PAGE_H - y, r, stroke=0, fill=1)

    def image(self, path, x0, y0, x1, y1):
        self.c.drawImage(str(path), x0, PAGE_H - y1, x1 - x0, y1 - y0,
                         mask="auto", preserveAspectRatio=True, anchor="c")

    # --- текст -------------------------------------------------------------
    def text(self, x, baseline, s, size=10.6, align="left", italic=False,
             rotate=0, max_width=None):
        """Строка текста. baseline — Y базовой линии (от верха листа).

        max_width: если текст шире — кегль уменьшается, чтобы влез.
        """
        s = "" if s is None else str(s)
        if not s:
            return
        if max_width:
            w = text_width(s, size)
            if w > max_width:
                size = size * max_width / w
        c = self.c
        c.saveState()
        c.translate(x, PAGE_H - baseline)
        if rotate:
            c.rotate(rotate)
        if italic:
            c.transform(1, 0, 0.21, 1, 0, 0)  # наклон ~12°
        c.setFont(FONT, size)
        if align == "center":
            c.drawCentredString(0, 0, s)
        elif align == "right":
            c.drawRightString(0, 0, s)
        else:
            c.drawString(0, 0, s)
        c.restoreState()

    def text_in_box(self, x0, y0, x1, y1, s, size=10.6, align="center",
                    pad=2.5, italic=False):
        """Текст, отцентрированный по вертикали в прямоугольнике."""
        base = (y0 + y1) / 2 + size * 0.36
        width = x1 - x0 - 2 * pad
        if align == "center":
            self.text((x0 + x1) / 2, base, s, size, "center", italic, max_width=width)
        elif align == "right":
            self.text(x1 - pad, base, s, size, "right", italic, max_width=width)
        else:
            self.text(x0 + pad, base, s, size, "left", italic, max_width=width)

    def vtext(self, x, y_bottom, s, size):
        """Вертикальный текст снизу вверх (боковая графа)."""
        self.text(x, y_bottom, s, size, rotate=90)

    def new_page(self):
        self.c.showPage()

    def save(self):
        self.c.save()
