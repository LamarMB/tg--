"""Лист «Спецификация элементов»."""
from __future__ import annotations

from dataclasses import dataclass

from ..model import SpecItem
from ..pen import Pen, text_width, wrap

COLS = [79.4, 124.7, 317.5, 805.0, 850.4, 986.5, 1156.5]
HEADERS = ["№ п/п", "Обозначение", "Наименование", "Кол-во", "Производитель",
           "Примечание"]
HEAD_Y0, HEAD_Y1 = 82.3, 105.0
BOTTOM_LIMIT = 762.0      # ниже — основная надпись
SIZE = 8.5
LINE = 10.2

NAME_X, NAME_W = 323.1, 362.0          # текст наименования
ART_RIGHT, ART_W = 799.4, 105.0        # артикул прижат вправо
DES_W = COLS[2] - COLS[1] - 10
MFR_W = COLS[5] - COLS[4] - 10
NOTE_W = COLS[6] - COLS[5] - 10


@dataclass
class _Row:
    n: int
    item: SpecItem
    des: list[str]
    name: list[str]
    art: list[str]
    mfr: list[str]
    note: list[str]

    @property
    def height(self) -> float:
        k = max(len(self.des), len(self.name), len(self.art), len(self.mfr),
                len(self.note), 1)
        return 17.0 if k == 1 else 8.6 + LINE * k


def _wrap_des(s: str) -> list[str]:
    # Обозначения переносим по ';', как в образце
    parts = s.split(";")
    lines, cur = [], ""
    for i, part in enumerate(parts):
        piece = part + (";" if i < len(parts) - 1 else "")
        if cur and text_width(cur + piece, SIZE) > DES_W:
            lines.append(cur.rstrip(";"))
            cur = piece
        else:
            cur += piece
    lines.append(cur)
    out = []
    for ln in lines:
        out += wrap(ln, DES_W, SIZE)
    return out


def spec_pages(items: list[SpecItem]):
    rows = []
    for i, it in enumerate(items, 1):
        rows.append(_Row(i, it, _wrap_des(it.designation),
                         wrap(it.name, NAME_W, SIZE), wrap(it.article, ART_W, SIZE),
                         wrap(it.manufacturer, MFR_W, SIZE), wrap(it.note, NOTE_W, SIZE)))
    pages: list[list[_Row]] = []
    cur: list[_Row] = []
    y = HEAD_Y1
    for r in rows:
        if cur and y + r.height > BOTTOM_LIMIT:
            pages.append(cur)
            cur, y = [], HEAD_Y1
        cur.append(r)
        y += r.height
    if cur or not pages:
        pages.append(cur)
    return [_painter(pg) for pg in pages]


def _painter(rows: list[_Row]):
    def draw(p: Pen) -> None:
        p.text(612.0, 69.0, "Спецификация элементов", 25.5, "center")
        # шапка
        x0, x1 = COLS[0], COLS[-1]
        p.rect(x0, HEAD_Y0, x1, HEAD_Y1)
        for a, b, h, dx in zip(COLS, COLS[1:], HEADERS, (0, 5.5, 5.5, 0, 0, -5.7)):
            p.vline(a, HEAD_Y0, HEAD_Y1)
            p.text_in_box(a + 2 * dx, HEAD_Y0, b, HEAD_Y1, h, 10.6)
        y = HEAD_Y1
        for r in rows:
            y2 = y + r.height
            for a in COLS:
                p.vline(a, y, y2)
            p.hline(x0, x1, y2)
            base = y + 11.8
            p.text((COLS[0] + COLS[1]) / 2, base, str(r.n), SIZE, "center")
            for k, ln in enumerate(r.des):
                p.text(130.4, base + k * LINE, ln, SIZE, tag=True)
            for k, ln in enumerate(r.name):
                p.text(NAME_X, base + 1.0 + k * LINE, ln, SIZE)
            for k, ln in enumerate(r.art):
                p.text(ART_RIGHT, base + k * LINE, ln, SIZE, "right")
            p.text((COLS[3] + COLS[4]) / 2, base, r.item.qty, SIZE, "center",
                   max_width=COLS[4] - COLS[3] - 4)
            for k, ln in enumerate(r.mfr):
                p.text(856.1, base + k * LINE, ln, SIZE)
            for k, ln in enumerate(r.note):
                p.text(COLS[5] + 5.6, base + k * LINE, ln, SIZE)
            y = y2
    return draw
