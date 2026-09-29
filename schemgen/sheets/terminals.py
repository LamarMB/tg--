"""Лист «Клеммный план».

Каждый клеммник — таблица слева и «изображение» клеммника справа:
метки клемм, риски ярусов и перемычки. Клеммник может переходить на
следующий лист — тогда шапка повторяется, а итоговая строка идёт в конце.
"""
from __future__ import annotations

from ..model import TerminalBlock, TerminalRow
from ..pen import Pen

COLS = [70.9, 201.3, 354.3, 473.4, 609.4, 756.9, 900.0]
HEADERS = ["Номер изделия", "Номер типа", "Поперечное сечение",
           "Маркировка клемм", "Перемычка", "Крышка"]
STRIP_X0, STRIP_X1 = 978.0, 1148.0          # полоса с метками клемм
LABEL_CX = (STRIP_X0 + STRIP_X1) / 2
TIER_X = {0: 989.3, 1: 995.0, 2: 1000.6}     # риска / перемычка по ярусу

HEAD_DX = [0, 0, 0, 5.5, 5.6, 7.7]           # сдвиг заголовков как в образце
TOP = 71.0
ROW_H = 22.68
FOOT_H = 14.2
GAP = 11.3
BOTTOM_LIMIT = 775.0          # низ последней строки (как в образце)


def terminal_pages(blocks: list[TerminalBlock]):
    """Раскладка по листам: список страниц, страница — список фрагментов."""
    pages: list[list[tuple]] = []
    cur: list[tuple] = []
    y = TOP
    for blk in blocks:
        rows = blk.rows or [TerminalRow()]
        i = 0
        while i < len(rows):
            # сколько строк влезет с шапкой; последней нужна ещё итоговая строка
            avail = BOTTOM_LIMIT - y - ROW_H
            n = 0
            while i + n < len(rows):
                # у последней строки блока под ней ещё итог и отступ (так разбит образец)
                need = (n + 1) * ROW_H + (FOOT_H + GAP if i + n == len(rows) - 1 else 0)
                if need > avail:
                    break
                n += 1
            if n == 0:
                if not cur:          # даже на пустом листе не влезает — ставим 1 строку
                    n = 1
                else:
                    pages.append(cur)
                    cur, y = [], TOP
                    continue
            last = i + n == len(rows)
            cur.append((blk, rows, i, i + n, last, y))
            y += ROW_H * (n + 1) + (FOOT_H + GAP if last else 0)
            i += n
            if not last:
                pages.append(cur)
                cur, y = [], TOP
    if cur or not pages:
        pages.append(cur)
    return [_painter(pg) for pg in pages]


def _painter(frags):
    def draw(p: Pen) -> None:
        p.text(564.0, 54.8, "Клеммный план", 25.5, "center")
        for blk, rows, a, b, last, y in frags:
            _fragment(p, blk, rows, a, b, last, y)
    return draw


def _fragment(p: Pen, blk: TerminalBlock, rows, a: int, b: int, last: bool,
              y: float) -> None:
    x0, x1 = COLS[0], COLS[-1]
    # шапка таблицы
    p.rect(x0, y, x1, y + ROW_H, lw=0.71)
    for c0, c1, h, dx in zip(COLS, COLS[1:], HEADERS, HEAD_DX):
        p.vline(c0, y, y + ROW_H, 0.37)
        p.text_in_box(c0 + 2 * dx, y, c1, y + ROW_H, h, 10.6)
    # заголовок клеммника справа
    p.rect(1029.0, y, 1081.4, y + 2.8, stroke=False, fill=True)
    p.rect(1029.0, y + 19.8, 1082.8, y + ROW_H, stroke=False, fill=True)
    p.rect(980.8, y + 2.8, 1122.5, y + 19.8, lw=0.37)
    p.text_in_box(980.8, y + 2.8, 1122.5, y + 19.8, blk.name, 12.8, tag=True)

    yr = y + ROW_H
    part = rows[a:b]
    centers: dict[str, list[tuple[float, float]]] = {}
    for k, r in enumerate(part):
        ya, yb = yr + k * ROW_H, yr + (k + 1) * ROW_H
        for c in COLS:
            p.vline(c, ya, yb, 0.37)
        p.hline(x0, x1, yb, 0.37)
        base = (ya + yb) / 2 + 3.8
        p.text(COLS[0] + 2.8, base, r.part_no, 10.6, max_width=COLS[1] - COLS[0] - 5)
        p.text(COLS[1] + 11.3, base, r.type_no, 10.6, max_width=COLS[2] - COLS[1] - 14)
        for ci, val in ((2, r.section), (3, r.marking), (4, r.jumper), (5, r.cover)):
            p.text_in_box(COLS[ci], ya, COLS[ci + 1], yb, val, 10.6)
        # полоса меток
        p.vline(STRIP_X0, ya, yb)
        p.vline(STRIP_X1, ya, yb)
        p.hline(STRIP_X0, STRIP_X1, ya)
        p.hline(STRIP_X0, STRIP_X1, yb)
        cy = (ya + yb) / 2
        if r.tier is not None:
            tx = TIER_X.get(r.tier, TIER_X[0])
            p.vline(tx, cy - 1.4, cy + 1.4, 1.42)
            if r.bridge:
                centers.setdefault(r.bridge, []).append((tx, cy))
        p.text(LABEL_CX, cy + 3.8, r.label, 10.6, "center",
               max_width=STRIP_X1 - LABEL_CX - 20)
    # перемычки: точки на соединяемых клеммах и линия между крайними
    y_end = yr + len(part) * ROW_H
    for key, pts in centers.items():
        bx = pts[0][0]
        for _, cy in pts:
            p.dot(bx, cy)
        # перемычка продолжается с предыдущего / на следующий лист
        top, bottom = pts[0][1], pts[-1][1]
        if any(r.bridge == key for r in rows[:a]):
            top = yr
        if any(r.bridge == key for r in rows[b:]):
            bottom = y_end
        if bottom > top:
            p.vline(bx, top, bottom, 1.42)

    if last:
        yf = yr + len(part) * ROW_H
        p.rect(x0, yf, 1148.1, yf + FOOT_H, lw=0.51)
        p.rect(1029.0, yf, 1082.8, yf + FOOT_H, stroke=False, fill=True)
        p.text((x0 + x1) / 2, yf + FOOT_H / 2 + 3.8,
               f"Общее количество клемм в клеммнике: {blk.terminal_count} шт.",
               10.6, "center", italic=True)

