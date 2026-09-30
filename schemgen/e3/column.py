"""Сигнальная колонна (HL1) под выходами ПЛК — нижняя часть листа 7 образца.

Питание контактов реле приходит с общего провода катушек (стрелка слева) и идёт
на шину контактов реле K1…; от контакта 14 каждого реле — на вход колонны.
Сегмент может идти через перекидной контакт другого реле («via», напр. -KBF1:
НЗ 12 — от своего реле, НО 14 — напрямую от питания). Внизу колонны — общий
вывод 0 с проводом на минус. Координаты сняты с образца (от линии питания y0).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.lib.colors import white

from ..pen import PAGE_H, Pen, text_width
from . import symbols as S
from .io_sheets import XRef, split_link


@dataclass
class ColLamp:
    pin: str                        # 1, 2 …
    color: str = ""                 # GN / YL / RD / BZ
    kind: str = "лампа"             # лампа / зуммер
    relay: str = ""                 # -K1 — реле, контакт которого включает сегмент
    wire: list[str] = field(default_factory=list)       # провод к колонне (HL1-1)
    relay_wire: list[str] = field(default_factory=list)  # провод от реле до «via» (K3-14)
    via: str = ""                   # -KBF1 — перекидной контакт в цепи
    via_pins: str = "11/14/12"      # общий / НО / НЗ
    via_ref: str = ""               # /2.6


@dataclass
class Column:
    tag: str = "-HL1"
    title: str = "Сигнальная колонна"
    feed_wire: list[str] = field(default_factory=list)   # 1QFU5-1 RD 0,5
    feed_next: str = ""             # -1K1:13+ — питание дальше (стрелка вправо)
    feed_next_ref: str = ""
    lamps: list[ColLamp] = field(default_factory=list)
    common_pin: str = "0"
    common_link: str = ""           # -XM1:M3
    common_ref: str = ""
    common_wire: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.lamps)


def relays(col: Column) -> set[str]:
    return {l.relay.upper() for l in col.lamps if l.relay}


def _xs(col: Column, x0: float) -> list[float]:
    """x контактов реле: шаг 45.4, перед сегментом через «via» — ещё 11.3."""
    xs, x = [], x0
    for i, l in enumerate(col.lamps):
        if i:
            x += 45.4 + (11.3 if l.via and not col.lamps[i - 1].via else 0.0)
        xs.append(x)
    return xs


def register(col: Column, sheet: int, x_first: float, xr: XRef) -> None:
    for l, x in zip(col.lamps, _xs(col, x_first + 53.8)):
        if l.relay:
            xr.contact(l.relay, "co", sheet, x)


def _circle(p: Pen, x, y, r=2.8):
    p.c.saveState()
    p.c.setLineWidth(S.LW)
    p.c.setFillColor(white)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=1)
    p.c.restoreState()


def draw(p: Pen, col: Column, x_first: float, y0: float, xr: XRef) -> None:
    """x_first — вертикаль общего провода катушек, y0 — линия питания (стрелка слева)."""
    x0 = x_first + 53.8
    xs = _xs(col, x0)
    Y = lambda d: y0 + d                                             # noqa: E731
    # питание: от общего провода вправо и вниз к шине контактов
    p.line(x_first, Y(-5.7), x_first + 5.7, Y(0), S.LW)
    p.hline(x_first, x0, Y(0), S.LW)
    p.vline(x0, Y(0), Y(102.0), S.LW)
    if col.feed_wire and any(col.feed_wire):
        S.wire_mark(p, x0, Y(62.3), [w for w in col.feed_wire if w])
    vias = [(l, x) for l, x in zip(col.lamps, xs) if l.via]
    if vias or col.feed_next:
        # ответвление влево и вниз — к контактам «via» и дальше стрелкой
        p.hline(x_first, x0 - 5.7, Y(79.3), S.LW)
        p.line(x0 - 5.7, Y(79.3), x0, Y(85.0), S.LW)
        p.vline(x_first, Y(79.3), Y(192.7), S.LW)
        right = (xs[-1] + 68.0) if col.feed_next else max(x - 11.4 for _, x in vias)
        p.hline(x_first, right, Y(192.7), S.LW)
        for _, x in vias:
            S.junction(p, x - 11.4, Y(192.7))
        if col.feed_next:
            S.arrow_right(p, right + 7.8, Y(192.7),
                          col.feed_next + (f" / {col.feed_next_ref}" if col.feed_next_ref else ""))
            if col.feed_wire and any(col.feed_wire):
                S.hwire_mark(p, right - 31.1, Y(192.7), [w for w in col.feed_wire if w])
    # шина контактов и контакты реле
    if len(xs) > 1:
        S.drop_bus(p, xs, Y(102.0))
        p.text(x0 + 24.1, Y(102.0) - 1.5, "", 5.5)
    for l, x in zip(col.lamps, xs):
        p.vline(x, Y(102.0) + 11.3, Y(124.7), S.LW)
        ref = xr.head_ref(l.relay) if l.relay else ""
        S.contact_changeover(p, x, Y(124.7), l.relay, ref)
    # от контактов вниз к колонне
    box_top, box_bot = Y(272.1), Y(351.5)
    pins = []
    for l, x in zip(col.lamps, xs):
        if l.via:
            xv = x - 11.4
            p.vline(x, Y(141.7), Y(212.6), S.LW)                     # к НЗ «via»
            ww = l.relay_wire or l.wire
            if ww and any(ww):
                S.wire_mark(p, x, Y(178.6), [w for w in ww if w])
            _via(p, xv, Y(206.9), l, xr)
            p.vline(xv, Y(229.6), box_top, S.LW)
            if l.wire and any(l.wire) and l.relay_wire:
                S.wire_mark(p, xv, Y(260.8), [w for w in l.wire if w])
            pins.append(xv)
        else:
            p.vline(x, Y(141.7), box_top, S.LW)
            if l.wire and any(l.wire):
                S.wire_mark(p, x, Y(178.6), [w for w in l.wire if w])
            pins.append(x)
    # колонна
    bx0, bx1 = pins[0] - 28.3, pins[-1] + 39.7
    p.rect(bx0, box_top, bx1, box_bot, 1.13)
    p.text(bx0 - 4.0, box_top + 8.7, col.tag if col.tag.startswith("-") else f"-{col.tag}",
           10.6, "right")
    if col.title:
        p.text(bx1, box_bot + 12.5, col.title, 7.7, "right")
    for l, x in zip(col.lamps, pins):
        p.vline(x, box_top, Y(280.6), S.LW)
        _circle(p, x, Y(283.4))
        p.text(x + 5.7, Y(286.8), l.pin, 7.7)
        p.vline(x, Y(286.2), Y(306.1), S.LW)
        if l.kind.startswith("зум") or l.color.upper() == "BZ":
            p.rect(x - 5.7, Y(306.1), x + 5.7, Y(317.4), 0.71)
            p.line(x + 5.7, Y(306.1), x + 22.8, Y(310.4), 0.71)
            p.line(x + 22.8, Y(306.1), x + 28.4, Y(317.4), 0.71)
            p.line(x + 5.7, Y(313.2), x + 28.4, Y(317.4), 0.71)
        else:
            p.c.saveState()
            p.c.setLineWidth(S.LW)
            p.c.circle(x, PAGE_H - Y(311.7), 5.7, stroke=1, fill=0)
            p.c.restoreState()
            p.line(x - 4.0, Y(307.8), x + 4.0, Y(315.7), S.LW)
            p.line(x - 4.0, Y(315.7), x + 4.0, Y(307.8), S.LW)
        p.text(x - 8.5, Y(314.5), l.color, 7.7, "right")
        p.vline(x, Y(317.4), Y(323.1), S.LW)
    # общий провод внизу колонны
    p.hline(pins[0], pins[-1], Y(328.8), S.LW)
    for x in pins:
        p.vline(x, Y(323.1), Y(328.8), S.LW)
    p.vline(pins[0], Y(328.8), Y(337.3), S.LW)
    _circle(p, pins[0], Y(340.1))
    p.text(pins[0] + 5.7, Y(343.3), col.common_pin, 7.7)
    p.vline(pins[0], Y(343.0), Y(399.7), S.LW)
    if col.common_wire and any(col.common_wire):
        S.wire_mark(p, pins[0], Y(382.6), [w for w in col.common_wire if w])
    if col.common_link:
        lk, rf = split_link(col.common_link, col.common_ref, xr)
        tip = pins[0] - 8.5
        p.hline(tip, pins[0], Y(399.7), S.LW)
        S.arrow_in_from_left(p, tip, Y(399.7), lk + (f" / {rf}" if rf else ""), 7.7)


def _via(p: Pen, xv, y, l: ColLamp, xr: XRef):
    """Перекидной контакт «via» вверх ногами: 14 и 12 сверху, общий 11 снизу."""
    a, no, nc = (l.via_pins.split("/") + ["11", "14", "12"])[:3]
    p.vline(xv, y - 14.2, y, S.LW)                       # к 14 (НО) — от линии питания
    p.vline(xv, y, y + 5.7, S.LW)
    p.line(xv, y + 17.0, xv + 8.5, y + 4.2, S.LW)         # нож
    p.hline(xv + 5.7, xv + 11.4, y + 5.7, S.LW)            # 12 (НЗ)
    p.vline(xv + 11.4, y, y + 5.7, S.LW)
    p.vline(xv, y + 17.0, y + 22.7, S.LW)
    p.text(xv + 1.2, y + 2.5, no, S.PIN)
    p.text(xv + 12.5, y + 2.5, nc, S.PIN)
    p.text(xv + 1.2, y + 26.5, a, S.PIN)
    tag = l.via if l.via.startswith("-") else f"-{l.via}"
    p.text(xv - 3.5, y + 16.5, tag, S.TAG, "right")
    ref = xr.head_ref(l.via) or l.via_ref
    if ref:
        p.text(xv - 3.5, y + 28.6, ref, S.PIN, "right")
