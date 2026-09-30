"""Условные графические обозначения для схемы Э3 (размеры сняты с образца).

Все функции рисуют относительно x провода; y — абсолютные (от верха листа).
"""
from __future__ import annotations

from ..pen import Pen, text_width

LW = 0.71          # тонкая линия (провод)
LW_BUS = 1.42      # шина / утолщение
SMALL = 5.5        # маркировка провода
PIN = 7.7          # номера выводов, подписи
TAG = 10.6         # позиционное обозначение


def wire(p: Pen, x, y0, y1):
    if y1 > y0:
        p.vline(x, y0, y1, LW)


def wire_mark(p: Pen, x, y, lines: list[str]):
    """Засечка на проводе и маркировка (марка / цвет / сечение) справа."""
    p.line(x - 2.8, y - 2.8, x + 2.8, y + 2.8, LW)
    lines = [s for s in lines if s]
    top = y - 19.4 - (len(lines) - 3) * 6.7 if lines else y
    for i, s in enumerate(lines):
        p.text(x + 4.3, top + i * 6.7 + 4.6, s, SMALL)


def hwire_mark(p: Pen, x, y, lines: list[str]):
    """Засечка на горизонтальном проводе, подпись над ней."""
    p.line(x - 2.8, y + 2.8, x + 2.8, y - 2.8, LW)
    lines = [s for s in lines if s]
    for i, s in enumerate(lines):
        p.text(x + 4.3, y - 1.4 - (len(lines) - 1 - i) * 6.7, s, SMALL)


def _tri(p: Pen, pts):
    from ..pen import PAGE_H
    c = p.c
    path = c.beginPath()
    path.moveTo(pts[0][0], PAGE_H - pts[0][1])
    for x, y in pts[1:]:
        path.lineTo(x, PAGE_H - y)
    path.close()
    c.drawPath(path, stroke=0, fill=1)


def arrow_down(p: Pen, x, y_tip, label: str, ref: str, size=PIN):
    """Стрелка «приходит сверху» (к проводу): подпись и ссылка над ней."""
    _tri(p, [(x - 2.8, y_tip - 7.8), (x + 2.8, y_tip - 7.8), (x, y_tip)])
    p.vline(x, y_tip - 11.3, y_tip - 7.8, LW)
    base = y_tip - 11.3 - 4.0
    if ref:
        p.text(x, base, ref, size, "center")
        base -= size * 1.2
    p.text(x, base, label, size, "center")


def arrow_down_out(p: Pen, x, y_top, label: str, ref: str):
    """Провод уходит вниз стрелкой; подпись под стрелкой."""
    _tri(p, [(x - 2.8, y_top), (x + 2.8, y_top), (x, y_top + 7.8)])
    p.text(x, y_top + 21.0, label, PIN, "center")
    if ref:
        p.text(x, y_top + 30.2, ref, PIN, "center")


def link_text(text: str) -> str:
    """«-XM1:M5/4.8» → «-XM1:M5 / 4.8» (как в образце)."""
    import re
    t = str(text or "")
    return re.sub(r"(?<=\S)\s*/\s*(?=\S)", " / ", t) if not t.startswith("/") else t


def arrow_right(p: Pen, x_tip, y, text: str):
    """Стрелка вправо (провод уходит), текст справа от острия."""
    text = link_text(text)
    _tri(p, [(x_tip - 7.8, y - 2.8), (x_tip - 7.8, y + 2.8), (x_tip, y)])
    p.text(x_tip + 2.9, y + 2.8, text, PIN)


def arrow_in_from_left(p: Pen, x_tip, y, text: str, size=8.5):
    """Стрелка слева (провод приходит): текст — слева от стрелки."""
    text = link_text(text)
    _tri(p, [(x_tip - 7.8, y - 2.8), (x_tip - 7.8, y + 2.8), (x_tip, y)])
    p.hline(x_tip - 11.3, x_tip - 7.8, y, LW)
    p.text(x_tip - 12.5, y + 3.0, text, size, "right")


def arrow_in_from_right(p: Pen, x_tip, y, text: str):
    """Стрелка справа, острием влево (провод приходит справа)."""
    text = link_text(text)
    _tri(p, [(x_tip + 7.8, y - 2.8), (x_tip + 7.8, y + 2.8), (x_tip, y)])
    p.hline(x_tip + 7.8, x_tip + 11.3, y, LW)
    p.text(x_tip + 13.0, y + 2.8, text, PIN)


def pin_bottom(p: Pen, x, y_box):
    """Вывод модуля на верхней кромке блока (провод приходит сверху).

    y_box — линия верхней кромки блока; символ под ней."""
    p.c.setLineWidth(LW)
    _arc_up(p, x, y_box + 11.3)                          # полукруг
    p.rect(x - 1.4, y_box + 14.2, x + 1.4, y_box + 18.4, stroke=False, fill=True)
    p.vline(x, y_box + 18.4, y_box + 19.9, LW)
    _circle(p, x, y_box + 22.7, 2.85)


def pin_top(p: Pen, x, y_box_bottom):
    """Вывод на нижней кромке блока выходов (провод уходит вниз)."""
    _circle(p, x, y_box_bottom - 22.7, 2.85)
    p.vline(x, y_box_bottom - 19.9, y_box_bottom - 18.4, LW)
    p.rect(x - 1.4, y_box_bottom - 18.4, x + 1.4, y_box_bottom - 14.2,
           stroke=False, fill=True)
    _arc_down(p, x, y_box_bottom - 14.2)


def _circle(p: Pen, x, y, r):
    from ..pen import PAGE_H
    p.c.setLineWidth(LW)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=0)


def _arc_up(p: Pen, x, y):
    """Дуга-«колпачок» выпуклостью вверх, нижняя точка на y+2.8."""
    from ..pen import PAGE_H
    p.c.setLineWidth(LW)
    p.c.arc(x - 2.85, PAGE_H - (y + 2.8) - 2.85, x + 2.85, PAGE_H - (y + 2.8) + 2.85,
            0, 180)


def _arc_down(p: Pen, x, y):
    from ..pen import PAGE_H
    p.c.setLineWidth(LW)
    p.c.arc(x - 2.85, PAGE_H - y - 2.85, x + 2.85, PAGE_H - y + 2.85, 180, 180)


def tag(p: Pen, x_right, y_top, name: str, ref: str = "", size=TAG, ref_dy=12.2):
    p.text(x_right, y_top + size * 0.85, name, size, "right")
    if ref:
        p.text(x_right, y_top + size * 0.85 + ref_dy, ref, PIN, "right")


# --- контакты (провод идёт сверху вниз, y0 — верх символа) -----------------
def contact_ssr(p: Pen, x, y0, name, ref):
    """НО контакт твердотельного реле (13+ / 14), высота 11.3. x — провод,
    сам контакт левее провода (как в образце)."""
    b = x - 5.7
    p.vline(b, y0 + 1.4, y0 + 9.9, LW)
    p.line(x, y0, b, y0 + 4.2, LW)
    p.line(b, y0 + 7.1, x, y0 + 11.3, LW)
    _tri(p, [(b + 1.7, y0 + 0.1), (b + 3.1, y0 + 2.9), (b + 4.8, y0 + 2.4)])
    p.hline(b - 2.8, b, y0 + 5.7, LW)
    p.text(x + 1.4, y0 - 3.5, "13+", PIN)
    p.text(x + 1.4, y0 + 22.7, "14", PIN)
    tag(p, x - 14.2, y0 + 0.7, name, ref, ref_dy=10.0)


def contact_changeover(p: Pen, x, y0, name, ref):
    """Перекидной контакт 11 / 14 / 12."""
    p.line(x, y0, x + 8.5, y0 + 12.8, LW)
    p.hline(x + 5.7, x + 11.4, y0 + 11.3, LW)
    p.vline(x + 11.4, y0 + 11.3, y0 + 17.0, LW)
    p.text(x + 1.4, y0 - 2.4, "11", PIN)
    p.text(x + 1.4, y0 + 21.5, "14", PIN)
    p.text(x + 12.0, y0 + 21.5, "12", PIN)
    tag(p, x - 7.1, y0 - 0.1, name, ref, ref_dy=7.1)


def button(p: Pen, x, y0, name, ref, nc: bool):
    """Кнопка НО (13/14) или НЗ (11/12) с толкателем (геометрия образца).
    x — провод, y0 — верх контакта."""
    p.vline(x, y0 - 4.2, y0 + 1.5, LW)
    if nc:
        p.line(x, y0 + 12.8, x + 4.2, y0, LW)
        p.hline(x, x + 5.7, y0 + 1.5, LW)
        dashes = [(-19.8, -18.4), (-15.6, -13.5), (-10.6, -8.5), (-5.7, -3.5), (0.0, 1.8)]
        zig = -13.5
    else:
        p.line(x, y0 + 12.8, x - 7.1, y0, LW)
        dashes = [(-19.8, -17.7), (-14.9, -12.8), (-9.9, -7.8), (-5.0, -3.2)]
        zig = -12.8
    ya = y0 + 7.1
    for a, b in dashes:                                   # пунктир толкателя
        p.hline(x + a, x + b, ya, LW)
    p.line(x + zig, ya, x + zig + 1.5, ya + 2.2, LW)       # «зубец» кнопки
    p.line(x + zig + 1.5, ya + 2.2, x + zig + 2.9, ya, LW)
    bx = x - 19.8                                         # скоба привода
    p.vline(bx, y0 + 4.3, y0 + 10.0, LW)
    p.hline(bx, bx + 2.8, y0 + 4.3, LW)
    p.hline(bx - 2.9, bx, y0 + 10.0, LW)
    a, b = ("11", "12") if nc else ("13", "14")
    p.text(x + 1.4, y0 - 1.8, a, PIN)
    p.text(x + 1.4, y0 + 22.2, b, PIN)
    p.text(x - 25.7, y0 + 11.3, name, TAG, "right")
    if ref:
        p.text(x - 7.7, y0 + 31.9, ref, PIN, "right")


def coil(p: Pen, x, y0, name, param, top_pin="A1", bottom_pin="A2"):
    """Катушка реле: прямоугольник 22.7 x 11.4, y0 — верх."""
    p.rect(x - 11.3, y0, x + 11.4, y0 + 11.4, LW)
    p.text(x + 1.7, y0 - 1.9, top_pin, PIN)
    p.text(x + 1.7, y0 + 19.9, bottom_pin, PIN)
    p.text(x - 16.2, y0 + 9.3, name, TAG, "right")
    for i, ln in enumerate(str(param or "").split("\n")):
        if ln:
            p.text(x - 16.2, y0 + 20.5 + 9.2 * i, ln, PIN, "right")


def lamp(p: Pen, x, y0, name, param):
    """Сигнальная лампа (круг с крестом), выводы x2 сверху, x1 снизу."""
    from ..pen import PAGE_H
    r = 5.0
    cy = y0 + 5.7
    p.c.setLineWidth(LW)
    p.c.circle(x, PAGE_H - cy, r, stroke=1, fill=0)
    d = r * 0.707
    p.line(x - d, cy - d, x + d, cy + d, LW)
    p.line(x - d, cy + d, x + d, cy - d, LW)
    p.text(x + 1.7, y0 - 1.9, "x2", PIN)
    p.text(x + 1.7, y0 + 19.0, "x1", PIN)
    p.text(x - 9.0, y0 + 9.3, name, TAG, "right")
    if param:
        p.text(x - 9.0, y0 + 20.5, param, PIN, "right")


def mirror(p: Pen, x, y, contacts: list[tuple[str, str]]):
    """«Зеркало» контактов под катушкой: [(тип, ссылка)], тип 'co' или 'no'."""
    for i, (kind, ref) in enumerate(contacts):
        yy = y + i * 18.0
        x0 = x - (26.7 if kind == "no" else 21.0)
        if kind == "no":
            p.text(x0, yy + 2.8, "13+", PIN)
            p.line(x0 + 15.5, yy, x0 + 20.0, yy, LW)
            p.line(x0 + 20.0, yy, x0 + 26.0, yy - 3.0, LW)
            p.line(x0 + 25.0, yy - 3.0, x0 + 30.0, yy - 3.0, LW)
            p.text(x0 + 31.5, yy + 2.8, "14" + (f" {ref}" if ref else ""), PIN)
        else:
            p.text(x0, yy + 2.8, "14", PIN)
            p.line(x0 + 11.2, yy, x0 + 15.1, yy, LW)
            p.line(x0 + 14.0, yy + 5.9, x0 + 23.0, yy, LW)
            p.line(x0 + 23.0, yy, x0 + 26.9, yy, LW)
            p.text(x0 + 29.9, yy + 2.8, "11" + (f" {ref}" if ref else ""), PIN)
            p.text(x0, yy + 10.8, "12", PIN)
            p.line(x0 + 11.2, yy + 7.9, x0 + 15.1, yy + 7.9, LW)
            p.line(x0 + 15.1, yy + 3.9, x0 + 15.1, yy + 7.9, LW)


def junction(p: Pen, x, y):
    """Отвод от горизонтали вниз (значок EPLAN): косая черта в углу."""
    p.line(x, y + 5.6, x + 5.6, y, LW)


def drop_bus(p: Pen, xs: list[float], y: float, up: bool = False):
    """Шина с отводами как в образце: у первого отвода тонкий скос «/», у остальных —
    толстый «\\»; «шина» на первом участке. up=True — отводы приходят сверху
    (катушки), иначе уходят вниз (контакты реле)."""
    xs = sorted(xs)
    p.hline(xs[0] + 5.7, xs[-1], y, LW_BUS)
    for i, x in enumerate(xs):
        w = LW if i == 0 else LW_BUS
        if up:                                    # катушки: скос вправо у всех, кроме последней
            if i < len(xs) - 1:
                p.line(x, y - 5.7, x + 5.7, y, w)
            p.vline(x, y - 11.3, y, LW_BUS)
        elif i == 0:                              # контакты: у первого «/», у остальных «\\»
            p.line(x, y + 5.7, x + 5.7, y, LW)
            p.vline(x, y, y + 11.3, LW_BUS)
        else:
            p.line(x - 5.7, y, x, y + 5.7, LW_BUS)
            p.vline(x, y + 5.7, y + 11.3, LW_BUS)
    for x in (xs[:-1] if up else xs[:1]):          # у катушек «шина» на каждом участке
        lx = x + 22.7
        p.line(lx - 2.8, y - 2.8, lx + 2.8, y + 2.8, LW)
        p.text(lx + 4.2, y - 1.5, "шина", SMALL)


def bus(p: Pen, x0, x1, y, label_x=None):
    """Шина (толстая линия) с подписью «шина»."""
    p.hline(x0, x1, y, LW_BUS)
    if label_x is not None:
        p.line(label_x - 2.8, y - 2.8, label_x + 2.8, y + 2.8, LW)
        p.text(label_x + 4.3, y - 4.3, "шина", SMALL)


def desc_lines(text: str, width: float, size=PIN) -> tuple[list[str], float]:
    """Перенос подписи; если слово не влезает в ширину — уменьшаем кегль."""
    from ..pen import wrap
    words = str(text).split()
    widest = max((text_width(w, size) for w in words), default=0)
    if widest > width:
        size = max(5.0, size * width / widest)
    return wrap(text, width, size), size


def centered_lines(p: Pen, x, y_top, text: str, width: float, size=PIN, step=9.2):
    """Подпись по центру. Строка-место («+1KK1-XT2:2») — ниже, с отступом, как в образце."""
    lines, size = desc_lines(text, width, size)
    y = y_top + size * 0.85
    for i, ln in enumerate(lines):
        if i:
            y += 21.9 if ln.startswith("+") and not lines[i - 1].startswith("+") else step
        p.text(x, y, ln, size, "center")


def fits(s: str, w: float, size: float) -> bool:
    return text_width(s, size) <= w
