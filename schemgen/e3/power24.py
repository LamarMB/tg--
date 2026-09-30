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
    layout: dict = field(default_factory=dict)  # подгонка: {"xs": {"M1": x, "M1.j": отвод}}


@dataclass
class InClamp:
    """Клемма вводного клеммника (-X0.3 на листе 4 образца)."""
    name: str                                  # 1L+, 1M …
    source: str = ""                           # стрелка сверху: -UPS:Output DC 24V:+
    source_ref: str = ""
    source_wire: list[str] = field(default_factory=list)
    wire: list[str] = field(default_factory=list)       # провод вниз: 1L+ RD 1,5
    feed: str = ""                             # куда идёт: группа «1», шина «XM1», «XM1:M7»
    jumper: str = ""                           # пунктирная перемычка на клемму (1L+)
    x: float = 0.0                             # подгонка положения


@dataclass
class InputBlock:
    name: str                                  # X0.3
    clamps: list[InClamp] = field(default_factory=list)
    note: str = ""                             # поясняющий текст справа


@dataclass
class Power24:
    groups: list[BreakerGroup] = field(default_factory=list)
    minus: list[MinusBus] = field(default_factory=list)
    inputs: list[InputBlock] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.groups or self.minus)


# ------------------------------------------------------------------ раскладка
STEP = 73.7                  # шаг автоматов
X_FIRST = 116.3
ROW_BUS = (195.7, 516.0)     # шины верхнего и нижнего ряда
# ряды образца отличаются: второй ряд шире и автоматы ниже от шины
ROW_GEOM = (dict(x0=116.3, step=73.7, drop=22.7, wire=85.0, box=195.0),
            dict(x0=119.1, step=79.4, drop=25.5, wire=90.7, box=175.8))
SIDE_X0, SIDE_X1 = 765.4, 1150.0      # зона шины минусов справа
MINUS_BUS_Y = 414.0
# клемма шины минусов (как в образце): пара кружков a/b через 11.3; от «a» отводы
# прямо вверх/вниз, от «b» — с уступом вправо на JOG; следующая клемма через GAP
PAIR, JOG, GAP = 11.3, 17.0, 28.3


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
    inputs: list = field(default_factory=list)  # вводные клеммники (первый лист)


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
    if sheets:
        sheets[0].inputs = [b for b in pw.inputs if b.clamps]
    for sh in sheets:
        for r, row in enumerate(sh.rows):
            g = ROW_GEOM[min(r, 1)]
            for i, b in enumerate(row.breakers):
                sh.xs[id(b)] = g["x0"] + i * g["step"]
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


@dataclass
class _Slot:
    tap: MinusTap | None      # None — ввод шины (прямо вверх от первой клеммы)
    x: float                  # вертикаль отвода
    circle: float             # кружок на шине
    straight: bool            # от «a» прямо; иначе с уступом от «b»
    up: bool


@dataclass
class _Pair:
    clamp: str
    a: float
    b: float
    label: bool               # подписать клемму (первая пара клеммы)
    slots: list[_Slot] = field(default_factory=list)


@dataclass
class _FeedTap(MinusTap):
    """Отвод шины минусов, идущий проводом на вводной клеммник (без стрелки)."""
    feed: object = None


def _feeds(sh: _Sheet) -> dict[str, InClamp]:
    """Куда идут клеммы ввода: {«1»: клемма, «XM1»: …, «XM1:M7»: …}."""
    out = {}
    for b in sh.inputs:
        for c in b.clamps:
            if c.feed:
                out.setdefault(c.feed.strip().lstrip("-").upper(), c)
    return out


def _pairs(sh: _Sheet) -> list[_Pair]:
    m = sh.minus
    feeds = _feeds(sh)
    name = m.name.lstrip("-").upper()
    extra = {k.split(":", 1)[1]: c for k, c in feeds.items()
             if k.startswith(name + ":")}
    order: list[str] = []
    by: dict[str, list[MinusTap]] = {}
    for t in m.taps:
        if t.clamp not in by:
            order.append(t.clamp)
            by[t.clamp] = []
        by[t.clamp].append(t)
    # раскладка по парам: вверх/вниз — сначала прямой отвод, потом с уступом
    plan = []                                    # (clamp, [ups], [downs])
    for k, c in enumerate(order):
        ups = [t for t in by[c] if t.up]
        downs = [t for t in by[c] if not t.up]
        if c.upper() in extra:
            ups.append(_FeedTap(c, True, feed=extra[c.upper()]))
        if k == 0 and m.source:
            ups = [None] + ups
        n = max(1, math.ceil(len(ups) / 2), math.ceil(len(downs) / 2))
        for i in range(n):
            plan.append((c, i == 0, ups[2 * i:2 * i + 2], downs[2 * i:2 * i + 2]))
    if not plan and m.source:
        plan.append(("", True, [None], []))
    hints = (m.layout or {}).get("xs") or {}
    x0, x1 = (SIDE_X0, SIDE_X1) if sh.rows else (110.0, 1150.0)
    x0 = (m.layout or {}).get("x0", x0)
    # шаги по умолчанию; если не влезает — ужимаем
    need = sum(PAIR + JOG + GAP for _ in plan) - GAP
    k = min(1.0, max(0.45, (x1 - x0) / need)) if need > 0 else 1.0
    out, x = [], x0
    for c, first, ups, downs in plan:
        a = hints.get(c, x) if first else x
        jog = hints.get(f"{c}.j", (PAIR + JOG) * k) if first else (PAIR + JOG) * k
        pr = _Pair(c, a, a + PAIR * min(1.0, k / 0.8), first)
        for j, t in enumerate(ups):
            pr.slots.append(_Slot(t, a if j == 0 else a + jog, a if j == 0 else pr.b, j == 0, True))
        for j, t in enumerate(downs):
            pr.slots.append(_Slot(t, a if j == 0 else a + jog, a if j == 0 else pr.b, j == 0, False))
        out.append(pr)
        x = a + jog + GAP * k
    return out


def _tap_xs(sh: _Sheet) -> list[float]:
    """x отводов в порядке m.taps (для ссылок)."""
    pos = {id(s.tap): s.x for pr in _pairs(sh) for s in pr.slots if s.tap is not None}
    return [pos.get(id(t), SIDE_X0) for t in sh.minus.taps]


# ------------------------------------------------------------------ рисование
def painter(sh: _Sheet, xr: XRef):
    def draw(p: Pen) -> None:
        for r, row in enumerate(sh.rows):
            _row(p, sh, row, ROW_BUS[r], xr, ROW_GEOM[min(r, 1)])
        if sh.minus:
            _minus(p, sh, xr)
        for blk in sh.inputs:
            _inputs(p, sh, blk, xr)
    return draw


def _breaker_symbol(p: Pen, x: float, y: float, tag: str, rating: str,
                    pins=("2", "1"), dc: bool = True):
    """y — низ толстого отвода от шины (верх контакта). pins — выводы сверху/снизу,
    dc — подписи «+»/«-»."""
    p.vline(x, y, y + 5.7, S.LW)
    p.line(x - 7.1, y + 5.7, x, y + 18.4, S.LW)                  # подвижный контакт
    p.vline(x, y + 17.0, y + 22.7, S.LW)
    # привод: стрелка расцепителя и «ступенька» (координаты образца)
    p.line(x - 14.2, y + 4.1, x - 2.6, y + 10.4, S.LW)
    S._tri(p, [(x - 19.2, y + 1.4), (x - 14.9, y + 5.3), (x - 13.5, y + 2.9)])
    pts = [(-21.0, 4.6), (-16.0, 7.3), (-18.7, 12.2), (-13.7, 15.0), (-11.0, 10.0), (-4.4, 13.6)]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        p.line(x + ax, y + ay, x + bx, y + by, S.LW)
    if dc:
        p.text(x + 2.4, y - 7.0, "+", 5.5)
        p.text(x + 2.4, y + 32.0, "-", 5.5)
    p.text(x + 1.6, y + 1.2, pins[0], S.PIN)
    p.text(x + 1.6, y + 26.0, pins[1], S.PIN)
    p.text(x - 9.4, y + 29.3, tag, S.TAG, "right")
    if rating:
        p.text(x - 9.4, y + 39.6, rating, S.PIN, "right")


def _row(p: Pen, sh: _Sheet, row: _Row, bus_y: float, xr: XRef, geom: dict) -> None:
    xs = [sh.xs[id(b)] for b in row.breakers]
    if not xs:
        return
    step = geom["step"]
    feed_x = xs[0] - step / 2
    p.hline(feed_x, xs[-1], bus_y, S.LW_BUS)
    for i in range(len(xs) - 1):                       # подписи «шина»
        mx = (xs[i] + xs[i + 1]) / 2
        p.line(mx - 2.8, bus_y - 2.8, mx + 2.8, bus_y + 2.8, S.LW)
        p.text(mx + 3.0, bus_y - 4.0, "шина", 5.5)
    # источник
    g = row.group
    fed = row.first and g.name.strip().upper() in _feeds(sh)
    if row.first and g.source and not fed:
        # короткий подвод сверху: стрелка, над ней «откуда», справа провод
        link, ref = split_link(g.source, g.source_ref, xr)
        tip = bus_y - 28.0
        S._tri(p, [(feed_x - 2.8, tip - 7.8), (feed_x + 2.8, tip - 7.8), (feed_x, tip)])
        p.vline(feed_x, tip, bus_y, S.LW)
        p.text(feed_x - 3.0, tip - 11.0, link + (f" / {ref}" if ref else ""), 8.5)
        if g.source_wire and any(g.source_wire):
            S.wire_mark(p, feed_x, bus_y - 9.0, [w for w in g.source_wire if w][:1] +
                        [w for w in g.source_wire if w][1:])
    elif not row.first and not fed:
        p.text(feed_x, bus_y - 6.0, "…", 10.6, "center")
    for b, x in zip(row.breakers, xs):
        d = geom["drop"]
        p.vline(x, bus_y, bus_y + d, S.LW_BUS)
        _breaker_symbol(p, x, bus_y + d, b.tag, b.rating)
        top = bus_y + d + 17.0
        tip = bus_y + 130.0
        p.vline(x, top, tip - 7.8, S.LW)
        if b.wire and any(b.wire):
            S.wire_mark(p, x, bus_y + geom["wire"], [w for w in b.wire if w])
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
            y0 = bus_y + geom["box"]
            y1 = y0 + 73.7
            x0, x1 = x - step / 2, x + step / 2
            for a, c in (((x0, y0), (x1, y0)), ((x0, y1), (x1, y1)),
                         ((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))):
                p.line(*a, *c, S.LW, dash=([6, 4], 0))
            paras = [t.strip() for t in b.caption.replace("\\n", "\n").split("\n") if t.strip()]
            size = 10.6
            widest = max((S.text_width(w, size) for t in paras for w in t.split()), default=0)
            if widest > step - 6:
                size = size * (step - 6) / widest
            lines = [ln for t in paras for ln in wrap(t, step - 6, size)]
            base = (y0 + y1) / 2 - (len(lines) - 1) * size * 0.6 + size * 0.36
            for k, ln in enumerate(lines):
                p.text(x, base + k * size * 1.2, ln, size, "center")


def _arrow_down_to(p: Pen, x: float, tip: float, link: str, ref: str) -> None:
    S._tri(p, [(x - 2.8, tip - 7.8), (x + 2.8, tip - 7.8), (x, tip)])
    if link:
        p.text(x, tip + 15.0, link, 8.5, "center")
    if ref:
        p.text(x, tip + 24.5, ref, 8.5, "center")


def _circle(p: Pen, x: float, y: float, r: float = 2.15) -> None:
    p.c.saveState()
    p.c.setFillColor(white)
    p.c.setLineWidth(S.LW)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=1)
    p.c.restoreState()


def _minus(p: Pen, sh: _Sheet, xr: XRef) -> None:
    """Шина минусов по образцу (лист 4): клеммы парами кружков, отводы вверх —
    прямой (высокий) и с уступом (ниже), вниз — прямой (выше) и с уступом (ниже)."""
    m = sh.minus
    pairs = _pairs(sh)
    if not pairs:
        return
    y = MINUS_BUS_Y if sh.rows else 420.0
    r = 2.15
    fed = m.name.lstrip("-").upper() in _feeds(sh)
    p.text(pairs[0].a - 5.0, y - 3.5, f"-{m.name.lstrip('-')}", S.TAG, "right")
    for i, pr in enumerate(pairs):
        p.hline(pr.a + r, pr.b - r, y, S.LW)                      # перемычка клеммы
        if i + 1 < len(pairs):                                     # шина до следующей
            nx = pairs[i + 1].a
            p.hline(pr.b + r, nx - r, y, S.LW_BUS)
            sx = pr.b + 11.3 if nx - pr.b > 20 else (pr.b + nx) / 2
            p.line(sx - 2.8, y + 2.8, sx + 2.8, y - 2.8, S.LW)
            p.text(sx + 4.3, y - 3.6, "шина", 5.5)
        for cx in (pr.a, pr.b):
            _circle(p, cx, y, r)
        if pr.label and pr.clamp:
            p.text(pr.b + 4.0, y + 10.9, pr.clamp, S.PIN)
        for sl in pr.slots:
            _slot(p, sl, y, r, m, xr, fed)


def _slot(p: Pen, sl: _Slot, y: float, r: float, m: MinusBus, xr: XRef,
          fed: bool = False) -> None:
    x = sl.x
    sgn = -1 if sl.up else 1
    start = y + sgn * r
    if not sl.straight:                                  # уступ от «b»
        yj = y + sgn * 22.7
        p.vline(sl.circle, start, yj, S.LW)
        p.hline(sl.circle, x, yj, S.LW)
        start = yj
    if isinstance(sl.tap, _FeedTap):                     # провод рисует клеммник ввода
        return
    if sl.tap is None:                                   # ввод шины сверху
        if fed:
            return
        link, ref = split_link(m.source, m.source_ref, xr)
        top = y - 235.3
        p.vline(x, top, start, S.LW)
        S.arrow_down(p, x, top + 12.0, link, ref, 8.5)
        if m.source_wire and any(m.source_wire):
            S.wire_mark(p, x, y - 45.4, [w for w in m.source_wire if w])
        return
    tap = sl.tap
    link, ref = split_link(tap.link, tap.ref, xr)
    if sl.up:
        tip = y - (96.4 if sl.straight else 79.4)
        p.vline(x, tip + 7.8, start, S.LW)
        S._tri(p, [(x - 2.8, tip + 7.8), (x + 2.8, tip + 7.8), (x, tip)])
        if ref:
            p.text(x, tip - 2.1, ref, 8.5, "center")
            if link:
                p.text(x, tip - 12.3, link, 8.5, "center")
        elif link:
            p.text(x, tip - 2.1, link, 8.5, "center")
        if tap.wire and any(tap.wire):
            S.wire_mark(p, x, y - 45.4, [w for w in tap.wire if w])
    else:
        tip = y + (85.0 if sl.straight else 102.0)
        p.vline(x, start, tip - 7.8, S.LW)
        S._tri(p, [(x - 2.8, tip - 7.8), (x + 2.8, tip - 7.8), (x, tip)])
        if link:
            p.text(x, tip + 13.1, link, 8.5, "center")
        if ref:
            p.text(x, tip + 22.4, ref, 8.5, "center")
        if tap.wire and any(tap.wire):
            S.wire_mark(p, x, y + 56.7, [w for w in tap.wire if w])


# ------------------------------------------------------------------ вводной клеммник
IN_Y = 107.8                 # кружки клемм
IN_TIP = 54.0                # острие стрелок источников
LANE_R, LANE_L, LANE_STEP = 178.7, 175.9, 14.2


def _in_xs(blk: InputBlock) -> list[float]:
    xs, x, prev = [], 374.2, None
    for c in blk.clamps:
        if prev is not None:
            x += 36.8 if c.name == prev.name else (76.5 if c.jumper or prev.jumper else 59.6)
        x = c.x or x
        xs.append(x)
        prev = c
    return xs


def _inputs(p: Pen, sh: _Sheet, blk: InputBlock, xr: XRef) -> None:
    xs = _in_xs(blk)
    y, r = IN_Y, 2.15
    p.text(xs[0] - 7.8, y + 3.4, f"-{blk.name.lstrip('-')}", S.TAG, "right")
    # перемычки между соседними одноимёнными клеммами
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and blk.clamps[j + 1].name == blk.clamps[i].name:
            j += 1
        if j > i:
            p.hline(xs[i] - 5.7, xs[j] + 5.7, y, S.LW)
        i = j + 1
    for c, x in zip(blk.clamps, xs):
        p.vline(x, y - 5.6, y - r, S.LW)
        _circle(p, x, y, r)
        p.text(x + 3.9, y + 10.9, c.name, S.PIN)
        if c.source:
            link, ref = split_link(c.source, c.source_ref, xr)
            S._tri(p, [(x - 2.8, IN_TIP - 7.8), (x + 2.8, IN_TIP - 7.8), (x, IN_TIP)])
            p.vline(x, IN_TIP - 11.4, IN_TIP - 7.8, S.LW)
            p.vline(x, IN_TIP - 2.9, y - 5.6, S.LW)
            if ref:
                p.text(x, IN_TIP - 13.8, ref, S.PIN, "center")
            p.text(x, IN_TIP - (24.1 if ref else 13.8), link, S.PIN, "center")
            if c.source_wire and any(c.source_wire):
                S.wire_mark(p, x, 71.0, [w for w in c.source_wire if w])
    # пунктирные перемычки (переключение на другой источник)
    jumps = []
    for c, x in zip(blk.clamps, xs):
        if c.jumper:
            tgt = [xx for cc, xx in zip(blk.clamps, xs) if cc.name == c.jumper and cc is not c]
            if tgt:
                jumps.append((x, tgt[-1]))
    if jumps:
        xv0 = min(x for x, _ in jumps) - 25.6
        for k, (x, xt) in enumerate(jumps):
            yb, yt, xv = y + 14.2 + 11.3 * k, 82.3 + 11.4 * k, xv0 - 11.3 * k
            d = ([4.5, 3.0], 0)
            p.line(x, y + r, x, yb, S.LW_BUS, dash=d)
            p.line(x, yb, xv, yb, S.LW_BUS, dash=d)
            p.line(xv, yb, xv, yt, S.LW_BUS, dash=d)
            p.line(xv, yt, xt, yt, S.LW_BUS, dash=d)
            p.line(xt, yt, xt, y - 5.6, S.LW_BUS, dash=d)
    if blk.note:
        for k, ln in enumerate(blk.note.split("\n")):
            p.text(xs[-1] + 14.2, y + 17.6 + k * 9.2, ln.strip(), S.PIN)
    # провода вниз: к группам автоматов и к шине минусов
    feeds = []
    for c, x in zip(blk.clamps, xs):
        tgt = _in_target(sh, c.feed) if c.feed else None
        p.vline(x, y + r, y + 5.7, S.LW)
        if c.wire and any(c.wire):
            S.wire_mark(p, x, 144.6, [w for w in c.wire if w])
        if tgt is None:
            continue
        if tgt[0] == "row":        # верхний ряд под клеммой — прямо вниз, иначе в обход слева
            tgt = tgt[:4] + (tgt[4] == 0 and tgt[1] <= x <= tgt[5],)
        feeds.append((c, x, tgt))
    right = sorted([f for f in feeds if f[2][0] == "pt" and f[2][1] > f[1]], key=lambda f: f[1])
    left = sorted([f for f in feeds if f[2][0] == "row" and not f[2][4]], key=lambda f: -f[1])
    lane = {}
    for k, f in enumerate(right):
        lane[id(f[0])] = LANE_R - k * LANE_STEP
    for k, f in enumerate(left):
        lane[id(f[0])] = LANE_L - k * LANE_STEP
    for c, x, tgt in feeds:
        if tgt[0] == "row":
            _, x0, bus_y, xl, direct = tgt
            if direct:
                p.vline(x, y + 5.7, bus_y, S.LW)
                continue
            yl = lane[id(c)]
            p.vline(x, y + 5.7, yl, S.LW)
            p.hline(xl, x, yl, S.LW)
            p.vline(xl, yl, bus_y - 39.7, S.LW)
            p.hline(xl, x0, bus_y - 39.7, S.LW)
            p.vline(x0, bus_y - 39.7, bus_y, S.LW)
        else:
            _, tx, ty = tgt
            yl = lane.get(id(c), LANE_R)
            p.vline(x, y + 5.7, yl, S.LW)
            p.hline(min(x, tx), max(x, tx), yl, S.LW)
            p.vline(tx, yl, ty, S.LW)


def _in_target(sh: _Sheet, feed: str):
    """(«row», x шины, y шины, x обхода, напрямую) или («pt», x, y) на шине минусов."""
    key = feed.strip().lstrip("-").upper()
    for r, row in enumerate(sh.rows):
        if row.first and row.group.name.strip().upper() == key:
            xs = [sh.xs[id(b)] for b in row.breakers]
            if not xs:
                return None
            return ("row", xs[0], ROW_BUS[r], xs[0] - 53.9, r, xs[-1])
    if sh.minus:
        name = sh.minus.name.lstrip("-").upper()
        y = MINUS_BUS_Y if sh.rows else 420.0
        for pr in _pairs(sh):
            for sl in pr.slots:
                if key == name and sl.tap is None:
                    return ("pt", sl.x, y - 2.15)
                if isinstance(sl.tap, _FeedTap) and key == f"{name}:{sl.tap.clamp.upper()}":
                    return ("pt", sl.x, y - 22.7)
    return None
