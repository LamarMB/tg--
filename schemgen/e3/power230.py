"""Лист Э3 «Отходящие линии 230 В» (как лист 3 образца).

Линия: автомат (АВДТ 1P+N с дифзащитой или АВ 1P) от фазы (стрелка слева, напр.
-QS1:8) и нейтрали (стрелка вверх, напр. -XN:N1) -> клеммник L/N/PE -> кабель ->
розетки гирляндой или стрелки к нагрузке. Три линии на лист.
Марки проводов по правилу образца: QF1-1 / QF1-N1 до автомата, QF1-2 / QF1-N2 после.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.lib.colors import white

from ..pen import PAGE_H, Pen, wrap
from . import symbols as S
from .io_sheets import XRef, split_link
from .power24 import _breaker_symbol


@dataclass
class Feeder:
    tag: str                          # -QF1
    kind: str = "авдт"                # «авдт» или «ав»
    rating: str = ""                  # 20A 'C'
    leak: str = ""                    # 30мА
    section: str = "2,5"
    source: str = ""                  # -QS1:8
    source_ref: str = ""
    n_source: str = ""                # -XN:N1
    n_ref: str = ""
    terminal: str = ""                # X1
    cable: str = ""                   # W1LR1
    cable_type: str = ""              # FLEXICORE 130H-нг(A)-HF
    cable_cores: str = ""             # 3G2,5
    zone: str = ""                    # +ZM
    sockets: list[str] = field(default_factory=list)       # [-1XS1, …]
    socket_rating: str = ""           # 16 A
    load_links: list[str] = field(default_factory=list)    # [L, N, PE] стрелками
    load_ref: str = ""
    caption: str = ""


COL_W = 360.0
COL_X0 = 238.5            # провод L первой линии
PITCH = 22.7              # L / N / PE


def layout(feeders: list[Feeder]) -> list[list[Feeder]]:
    return [feeders[i:i + 3] for i in range(0, len(feeders), 3)]


def register(sheets: list[list[Feeder]], first: int, xr: XRef) -> list[int]:
    numbers = []
    for i, sh in enumerate(sheets):
        n = first + i
        numbers.append(n)
        for k, f in enumerate(sh):
            x = COL_X0 + k * COL_W
            for pin in ("1", "2", "N1", "N2"):
                xr.point(f"{f.tag}:{pin}", n, x)
            if f.terminal:
                for pin in ("L", "N", "PE"):
                    xr.point(f"{f.terminal}:{pin}", n, x)
    return numbers


def painter(sheet: list[Feeder], xr: XRef):
    def draw(p: Pen) -> None:
        zones = {f.zone for f in sheet if f.zone}
        if zones:
            y0, y1 = 415.0, 680.0
            x0, x1 = 88.0, 1150.0
            for a, b in (((x0, y0), (x1, y0)), ((x0, y1), (x1, y1)),
                         ((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))):
                p.line(*a, *b, S.LW, dash=([8, 4], 0))
            p.text(65.1, 429.0, ", ".join(sorted(zones)), S.TAG)
        for k, f in enumerate(sheet):
            _feeder(p, f, COL_X0 + k * COL_W, xr)
    return draw


def _wm(f: Feeder, suffix: str, color: str) -> list[str]:
    return [f"{f.tag.lstrip('-')}-{suffix}", color, f.section]


def _circle(p: Pen, x, y, r=2.9, fill_white=True):
    p.c.saveState()
    if fill_white:
        p.c.setFillColor(white)
    p.c.setLineWidth(S.LW)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=1)
    p.c.restoreState()


def _rcbo(p: Pen, xl: float, xn: float, y: float, f: Feeder) -> None:
    """АВДТ 1P+N: y — верх контактов (выводы 1 / N1)."""
    lw = S.LW
    for x in (xl, xn):
        p.line(x - 7.0, y + 4.0, x, y + 16.0, lw)             # подвижный контакт
        p.vline(x, y + 16.0, y + 22.0, lw)
    p.line(xl - 2.2, y - 2.2, xl + 2.2, y + 2.2, lw)          # «x» — автомат
    p.line(xl - 2.2, y + 2.2, xl + 2.2, y - 2.2, lw)
    # механическая связь, замок
    p.line(xl - 58.0, y + 8.0, xn + 45.0, y + 8.0, lw, dash=([5, 3], 0))
    p.rect(xl - 49.0, y + 3.0, xl - 41.0, y + 13.0, lw)
    p.vline(xl - 45.0, y + 1.0, y + 15.0, lw)
    p.hline(xl - 51.0, xl - 39.0, y + 8.0, lw)
    # расцепитель (стрелка к контакту L)
    p.line(xl - 13.0, y + 11.0, xl - 5.0, y + 6.5, lw)
    S._tri(p, [(xl - 13.0, y + 11.0), (xl - 9.8, y + 7.2), (xl - 8.6, y + 10.7)])
    # кнопка «тест» с резистором
    xt = xn + 22.0
    p.line(xt - 7.0, y + 4.0, xt, y + 16.0, lw)
    p.hline(xt - 11.0, xt - 7.0, y + 0.5, lw)
    p.vline(xt - 11.0, y + 0.5, y + 4.0, lw)
    p.vline(xt, y - 3.0, y + 0.5, lw)
    p.hline(xt - 11.0, xt, y - 3.0, lw)
    p.line(xt + 5.0, y + 4.0, xt + 12.0, y + 16.0, lw)
    p.vline(xt + 5.0, y + 16.0, y + 40.0, lw)
    p.rect(xt + 1.8, y + 20.0, xt + 8.2, y + 36.0, lw)
    p.hline(xl, xt, y + 18.5, lw)
    p.dot(xl, y + 18.5, 1.8)
    p.hline(xn, xt + 5.0, y + 40.0, lw)
    p.dot(xn, y + 40.0, 1.8)
    # дифф. трансформатор и реле
    p.rect(xl - 22.0, y + 22.0, xl - 17.0, y + 36.0, 0.1, fill=True)
    p.hline(xl - 22.0, xn + 5.0, y + 29.0, lw)
    p.rect(xl - 60.0, y + 24.5, xl - 38.0, y + 33.5, lw)
    p.text(xl - 49.0, y + 31.7, "-I>", 6.0, "center")
    p.vline(xl - 45.0, y + 13.0, y + 24.5, lw)
    p.text(xl - 2.0 + 3.6, y - 3.8, "1", S.PIN)
    p.text(xn + 1.3, y - 3.8, "N1", S.PIN)
    p.text(xl + 1.3, y + 50.9, "2", S.PIN)
    p.text(xn + 1.3, y + 50.9, "N2", S.PIN)
    p.text(xl - 70.0, y + 27.5, f.tag, S.TAG, "right")
    if f.rating:
        p.text(xl - 70.0, y + 37.5, f.rating, S.PIN, "right")
    if f.leak:
        p.text(xl - 70.0, y + 46.7, f.leak, S.PIN, "right")


def _feeder(p: Pen, f: Feeder, xl: float, xr: XRef) -> None:
    xn, xpe = xl + PITCH, xl + 2 * PITCH
    y_src, y_brk, y_term = 119.0, 207.0, 368.0
    rcbo = f.kind.lower().startswith("авдт") or f.kind.lower() == "rcbo"
    # фаза: стрелка слева
    link, ref = split_link(f.source, f.source_ref, xr)
    if link:
        S.arrow_in_from_left(p, xl - 28.0, y_src, link + (f" / {ref}" if ref else ""), 7.7)
        p.hline(xl - 28.0, xl, y_src, S.LW)
    p.vline(xl, y_src, y_brk, S.LW)
    S.wire_mark(p, xl, y_src + 25.0, _wm(f, "1", "BK"))
    y_after = y_brk + 22.0 if rcbo else y_brk + 40.0
    if rcbo:
        # нейтраль: стрелка вверх (приходит от шины N)
        nlink, nref = split_link(f.n_source, f.n_ref, xr)
        tip = y_src + 51.0
        S._tri(p, [(xn - 2.8, tip + 7.8), (xn + 2.8, tip + 7.8), (xn, tip)])
        p.vline(xn, tip + 7.8, y_brk, S.LW)
        if nlink:
            p.text(xn, tip - 13.5, nlink, S.PIN, "center")
        if nref:
            p.text(xn, tip - 4.0, nref, S.PIN, "center")
        S.wire_mark(p, xn, tip + 21.0, _wm(f, "N1", "BU"))
        _rcbo(p, xl, xn, y_brk, f)
    else:
        _breaker_symbol(p, xl, y_brk, f.tag, f.rating)
        if f.n_source:
            nlink, nref = split_link(f.n_source, f.n_ref, xr)
            tip = y_brk + 18.0
            S._tri(p, [(xn - 2.8, tip + 7.8), (xn + 2.8, tip + 7.8), (xn, tip)])
            p.text(xn, tip - 13.5, nlink, S.PIN, "center")
            if nref:
                p.text(xn, tip - 4.0, nref, S.PIN, "center")
    # после автомата — до клеммника
    p.vline(xl, y_after, y_term - 2.9, S.LW)
    S.wire_mark(p, xl, y_term - 42.0, _wm(f, "2", "BK"))
    p.vline(xn, y_after if rcbo else y_brk + 34.0, y_term - 2.9, S.LW)
    S.wire_mark(p, xn, y_term - 42.0, _wm(f, "N2", "BU") if rcbo else _wm(f, "N", "BU"))
    if f.terminal:
        for x, lab in ((xl, "L"), (xn, "N"), (xpe, "PE")):
            _circle(p, x, y_term)
            p.text(x + 3.6, y_term + 9.0, lab, S.PIN)
        p.text(xl - 11.0, y_term + 4.0, f"-{f.terminal.lstrip('-')}", S.TAG, "right")
    # от клеммника вниз
    y_cable = 515.0
    y_bot = 603.0
    for x in (xl, xn, xpe):
        p.vline(x, y_term + 2.9, y_bot if f.sockets else 640.0, S.LW)
    if f.cable or f.cable_cores:
        p.hline(xl - 14.0, xpe + 14.0, y_cable, S.LW)
        for x, lab in ((xl, "1"), (xn, "2"), (xpe, "GNYE")):
            p.text(x + 3.6, y_cable - 1.5, lab, 5.5)
        p.text(xl - 14.0, y_cable - 17.0, f"-{f.cable.lstrip('-')}" if f.cable else "",
               S.TAG, "right")
        p.text(xl - 14.0, y_cable - 4.3, f.cable_type, S.TAG, "right", max_width=150)
        p.text(xl - 14.0, y_cable + 8.5, f.cable_cores, S.TAG, "right")
    if f.sockets:
        _sockets(p, f, xl, y_bot)
    elif f.load_links:
        links = (f.load_links + ["", "", ""])[:3]
        for x, lk in zip((xl, xn, xpe), links):
            S._tri(p, [(x - 2.8, 640.0), (x + 2.8, 640.0), (x, 647.8)])
            if lk:
                p.text(x + 3.0, 692.0, lk, S.PIN, rotate=90)
                if f.load_ref:
                    p.text(x + 11.0, 692.0, f.load_ref, S.PIN, rotate=90)
    if f.caption:
        cx = xl + PITCH + (40.0 if f.sockets else 0.0)
        for i, ln in enumerate(wrap(f.caption, COL_W - 30, 10.6)):
            p.text(cx, 737.0 + i * 12.6, ln, 10.6, "center")


def _sockets(p: Pen, f: Feeder, xl: float, y_top: float) -> None:
    """Розетки гирляндой (как 1XS1…1XS3 образца): первая — от кабеля, следующие —
    перемычками от предыдущей (L, N, PE на разных уровнях)."""
    box_w, gap = 79.0, 34.0
    y_box0, y_box1 = 648.0, 668.0
    y_contact = y_box1 - 6.5
    levels = [y_box0 - 8.0, y_box0 - 17.0, y_box0 - 26.0]      # L, N, PE
    prev = None
    for i, tag in enumerate(f.sockets):
        bx = xl - 17.0 + i * (box_w + gap)
        p.rect(bx, y_box0, bx + box_w, y_box1, S.LW)
        pins = [bx + 17.0, bx + 17.0 + PITCH, bx + 17.0 + 2 * PITCH]
        for k, (x, lab) in enumerate(zip(pins, ("L", "N", "PE"))):
            p.c.setLineWidth(S.LW)
            p.c.arc(x - 3.0, PAGE_H - y_contact - 3.0, x + 3.0, PAGE_H - y_contact + 3.0,
                    0, 180)
            p.text(x + 1.5, y_box0 + 7.0, lab, S.PIN)
            start = y_top if prev is None else levels[k]
            p.vline(x, start, y_contact - 3.0, S.LW)
            if prev is not None:                    # перемычка от предыдущей розетки
                p.line(prev[k], levels[k] + 5.0, prev[k] + 5.0, levels[k], S.LW)
                p.hline(prev[k] + 5.0, x, levels[k], S.LW)
        p.hline(pins[2] - 4.0, pins[2] + 4.0, y_contact - 3.0, S.LW)   # PE — черта
        p.text(bx - 3.0, y_box0 + 11.0, f"-{tag.lstrip('-')}", S.TAG, "right")
        if f.socket_rating:
            p.text(bx - 3.0, y_box0 + 21.0, f.socket_rating, S.PIN, "right")
        prev = pins
