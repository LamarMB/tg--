"""Лист Э3 «Распределение питания 24 В» (как лист 4 образца).

Группа автоматов: шина от источника, под ней автоматы (1QFU1 …) с номиналом,
проводом, стрелками к потребителям (до двух) и подписью в пунктирной рамке.
Шина минусов: клеммник (XM1) с отводами вверх и вниз к потребителям.
Ссылки «лист.столбец» на стрелках подставляются сами, если потребитель есть
на других генерируемых листах (-A3:A9, -CPU:+24V …).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from reportlab.lib.colors import white

from ..pen import PAGE_H, Pen, wrap
from . import symbols as S
from .io_sheets import XRef, split_link


# ------------------------------------------------------------------ модель
@dataclass
class Breaker:
    tag: str                                   # -1QFU1
    rating: str = ""                           # DC 1A 'C'
    wire: list[str] = field(default_factory=list)
    targets: list[tuple[str, str]] = field(default_factory=list)   # [(связь, ссылка)]
    caption: str = ""                          # «Питание коммутатора»


@dataclass
class BreakerGroup:
    name: str                                  # имя группы (1, 2 …)
    source: str = ""                           # стрелка питания шины: -X0.3:1L+
    source_ref: str = ""
    source_wire: list[str] = field(default_factory=list)
    breakers: list[Breaker] = field(default_factory=list)


@dataclass
class MinusTap:
    clamp: str                                 # M1
    up: bool
    wire: list[str] = field(default_factory=list)
    link: str = ""
    ref: str = ""


@dataclass
class MinusBus:
    name: str                                  # XM1
    source: str = ""
    source_ref: str = ""
    source_wire: list[str] = field(default_factory=list)
    taps: list[MinusTap] = field(default_factory=list)


@dataclass
class Power24:
    groups: list[BreakerGroup] = field(default_factory=list)
    minus: list[MinusBus] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.groups or self.minus)


# ------------------------------------------------------------------ раскладка
STEP = 73.7                  # шаг автоматов
X_FIRST = 116.3
ROW_BUS = (196.3, 505.0)     # шины верхнего и нижнего ряда
SIDE_X0, SIDE_X1 = 770.0, 1150.0      # зона шины минусов справа
MINUS_BUS_Y = 419.5


@dataclass
class _Row:
    group: BreakerGroup
    breakers: list[Breaker]
    first: bool              # первый ряд группы (рисуем источник)
    last: bool


@dataclass
class _Sheet:
    rows: list[_Row] = field(default_factory=list)
    minus: MinusBus | None = None
    number: int = 0
    xs: dict = field(default_factory=dict)     # id(breaker) -> x


def layout(pw: Power24) -> list[_Sheet]:
    per_row_side = 9          # рядом с шиной минусов
    per_row_full = 13
    rows_all: list[_Row] = []
    for g in pw.groups:
        chunks = [g.breakers[i:i + per_row_side]
                  for i in range(0, max(len(g.breakers), 1), per_row_side)] if pw.minus \
            else [g.breakers[i:i + per_row_full]
                  for i in range(0, max(len(g.breakers), 1), per_row_full)]
        for k, ch in enumerate(chunks):
            rows_all.append(_Row(g, ch, k == 0, k == len(chunks) - 1))
    minus = list(pw.minus)
    sheets: list[_Sheet] = []
    while rows_all or minus:
        sh = _Sheet(rows=rows_all[:2], minus=minus.pop(0) if minus else None)
        rows_all = rows_all[2:]
        sheets.append(sh)
    for sh in sheets:
        for r, row in enumerate(sh.rows):
            for i, b in enumerate(row.breakers):
                sh.xs[id(b)] = X_FIRST + i * STEP
    return sheets


def register(sheets: list[_Sheet], first: int, xr: XRef) -> None:
    for i, sh in enumerate(sheets):
        sh.number = first + i
        for row in sh.rows:
            for b in row.breakers:
                x = sh.xs[id(b)]
                for pin in ("1", "2"):
                    xr.point(f"{b.tag}:{pin}", sh.number, x)
        if sh.minus:
            for tap, x in zip(sh.minus.taps, _tap_xs(sh)):
                xr.point(f"{sh.minus.name}:{tap.clamp}", sh.number, x)


def _tap_xs(sh: _Sheet) -> list[float]:
    m = sh.minus
    x0, x1 = (SIDE_X0, SIDE_X1) if sh.rows else (110.0, 1150.0)
    n = max(len(m.taps), 1)
    step = min(34.0, (x1 - x0 - 30) / n)
    return [x0 + 30 + i * step for i in range(n)]


# ------------------------------------------------------------------ рисование
def painter(sh: _Sheet, xr: XRef):
    def draw(p: Pen) -> None:
        for r, row in enumerate(sh.rows):
            _row(p, sh, row, ROW_BUS[r], xr)
        if sh.minus:
            _minus(p, sh, xr)
    return draw


def _breaker_symbol(p: Pen, x: float, y: float, tag: str, rating: str):
    """y — низ толстого отвода от шины (верх контакта)."""
    p.vline(x, y, y + 5.0, S.LW)
    p.line(x, y + 5.0, x - 6.3, y + 17.5, S.LW)                   # подвижный контакт
    # привод: стрелка расцепителя и «ступенька»
    p.line(x - 3.6, y + 11.8, x - 17.0, y + 4.8, S.LW)
    S._tri(p, [(x - 17.0, y + 4.8), (x - 11.5, y + 5.4), (x - 13.6, y + 9.0)])
    for a, b in (((x - 21.0, y + 11.0), (x - 17.5, y + 11.0)),
                 ((x - 17.5, y + 11.0), (x - 17.5, y + 16.0)),
                 ((x - 17.5, y + 16.0), (x - 12.5, y + 16.0)),
                 ((x - 12.5, y + 16.0), (x - 12.5, y + 13.0))):
        p.line(*a, *b, S.LW)
    p.text(x + 2.4, y - 7.0, "+", 5.5)
    p.text(x + 1.6, y + 1.2, "2", S.PIN)
    p.text(x + 1.6, y + 26.0, "1", S.PIN)
    p.text(x + 2.4, y + 32.0, "-", 5.5)
    p.text(x - 9.4, y + 29.3, tag, S.TAG, "right")
    if rating:
        p.text(x - 9.4, y + 39.6, rating, S.PIN, "right")


def _row(p: Pen, sh: _Sheet, row: _Row, bus_y: float, xr: XRef) -> None:
    xs = [sh.xs[id(b)] for b in row.breakers]
    if not xs:
        return
    feed_x = xs[0] - STEP / 2
    p.hline(feed_x, xs[-1], bus_y, S.LW_BUS)
    for i in range(len(xs) - 1):                       # подписи «шина»
        mx = (xs[i] + xs[i + 1]) / 2
        p.line(mx - 2.8, bus_y - 2.8, mx + 2.8, bus_y + 2.8, S.LW)
        p.text(mx + 3.0, bus_y - 4.0, "шина", 5.5)
    # источник
    g = row.group
    if row.first and g.source:
        # короткий подвод сверху: стрелка, над ней «откуда», справа провод
        link, ref = split_link(g.source, g.source_ref, xr)
        tip = bus_y - 28.0
        S._tri(p, [(feed_x - 2.8, tip - 7.8), (feed_x + 2.8, tip - 7.8), (feed_x, tip)])
        p.vline(feed_x, tip, bus_y, S.LW)
        p.text(feed_x - 3.0, tip - 11.0, link + (f" / {ref}" if ref else ""), 8.5)
        if g.source_wire and any(g.source_wire):
            S.wire_mark(p, feed_x, bus_y - 9.0, [w for w in g.source_wire if w][:1] +
                        [w for w in g.source_wire if w][1:])
    elif not row.first:
        p.text(feed_x, bus_y - 6.0, "…", 10.6, "center")
    for b, x in zip(row.breakers, xs):
        p.vline(x, bus_y, bus_y + 22.5, S.LW_BUS)
        _breaker_symbol(p, x, bus_y + 22.5, b.tag, b.rating)
        top = bus_y + 40.0
        tip = bus_y + 130.0
        p.vline(x, top, tip - 7.8, S.LW)
        if b.wire and any(b.wire):
            S.wire_mark(p, x, bus_y + 84.0, [w for w in b.wire if w])
        t1 = b.targets[0] if b.targets else ("", "")
        link, ref = split_link(t1[0], t1[1], xr)
        _arrow_down_to(p, x, tip, link, ref)
        if len(b.targets) > 1:                              # второй потребитель
            yb = bus_y + 90.0
            p.line(x, yb, x + 5.0, yb + 5.0, S.LW)
            p.hline(x + 5.0, x + 28.0, yb + 5.0, S.LW)
            p.vline(x + 28.0, yb + 5.0, bus_y + 111.0, S.LW)
            link2, ref2 = split_link(b.targets[1][0], b.targets[1][1], xr)
            _arrow_down_to(p, x + 28.0, bus_y + 119.0, link2, ref2)
        if b.caption:
            y0, y1 = bus_y + 178.0, bus_y + 250.0
            x0, x1 = x - STEP / 2, x + STEP / 2
            for a, c in (((x0, y0), (x1, y0)), ((x0, y1), (x1, y1)),
                         ((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))):
                p.line(*a, *c, S.LW, dash=([6, 4], 0))
            lines = wrap(b.caption, STEP - 6, 10.6)
            size = 10.6
            widest = max((S.text_width(w, size) for w in b.caption.split()), default=0)
            if widest > STEP - 6:
                size = size * (STEP - 6) / widest
                lines = wrap(b.caption, STEP - 6, size)
            base = (y0 + y1) / 2 - (len(lines) - 1) * size * 0.6 + size * 0.36
            for k, ln in enumerate(lines):
                p.text(x, base + k * size * 1.2, ln, size, "center")


def _arrow_down_to(p: Pen, x: float, tip: float, link: str, ref: str) -> None:
    S._tri(p, [(x - 2.8, tip - 7.8), (x + 2.8, tip - 7.8), (x, tip)])
    if link:
        p.text(x, tip + 15.0, link, 8.5, "center")
    if ref:
        p.text(x, tip + 24.5, ref, 8.5, "center")


def _minus(p: Pen, sh: _Sheet, xr: XRef) -> None:
    m = sh.minus
    xs = _tap_xs(sh)
    y = MINUS_BUS_Y if sh.rows else 420.0
    x_start = xs[0] - 22.0
    p.hline(x_start, xs[-1] + 8.0, y, S.LW_BUS)
    p.text(x_start - 6.0, y + 3.8, f"-{m.name.lstrip('-')}", S.TAG, "right")
    # источник
    if m.source:
        link, ref = split_link(m.source, m.source_ref, xr)
        p.vline(x_start, y - 150.0, y, S.LW)
        S.arrow_down(p, x_start, y - 138.0, link, ref, 8.5)
        if m.source_wire:
            S.wire_mark(p, x_start, y - 60.0, m.source_wire)
    step = xs[1] - xs[0] if len(xs) > 1 else 34.0
    levels = max(1, min(4, math.ceil(46.0 / step)))
    up_i = down_i = 0
    prev_clamp = None
    for tap, x in zip(m.taps, xs):
        # клемма (белый кружок на шине)
        p.c.saveState()
        p.c.setFillColor(white)
        p.c.setLineWidth(S.LW)
        p.c.circle(x, PAGE_H - y, 2.6, stroke=1, fill=1)
        p.c.restoreState()
        if tap.clamp != prev_clamp:
            p.text(x + 3.0, y + 12.0, tap.clamp, S.PIN)
            prev_clamp = tap.clamp
        link, ref = split_link(tap.link, tap.ref, xr)
        if tap.up:
            lvl = up_i % levels
            up_i += 1
            tip = y - 95.0 - lvl * 22.0
            p.vline(x, tip + 7.8, y - 2.6, S.LW)
            S._tri(p, [(x - 2.8, tip + 7.8), (x + 2.8, tip + 7.8), (x, tip)])
            if ref:
                p.text(x, tip - 4.0, ref, 8.5, "center")
            if link:
                p.text(x, tip - (13.5 if ref else 4.0), link, 8.5, "center")
            if tap.wire and any(tap.wire):
                S.wire_mark(p, x, y - 45.0, [w for w in tap.wire if w])
        else:
            lvl = down_i % levels
            down_i += 1
            tip = y + 90.0 + lvl * 22.0
            p.vline(x, y + 2.6, tip - 7.8, S.LW)
            S._tri(p, [(x - 2.8, tip - 7.8), (x + 2.8, tip - 7.8), (x, tip)])
            if link:
                p.text(x, tip + 11.0, link, 8.5, "center")
            if ref:
                p.text(x, tip + 20.5, ref, 8.5, "center")
            if tap.wire and any(tap.wire):
                S.wire_mark(p, x, y + 55.0, [w for w in tap.wire if w])
