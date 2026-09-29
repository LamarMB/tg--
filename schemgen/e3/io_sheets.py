"""Листы Э3 «входы / выходы модулей ПЛК» с автоматическими перекрёстными ссылками.

Раскладка идёт в два прохода:
  1) расставляем все каналы по листам и координатам, регистрируем, где стоят
     катушки, лампы и контакты (лист + столбец координатной линейки);
  2) рисуем, подставляя ссылки: у контакта — где его катушка («/16.3»),
     под катушкой — «зеркало» с местами всех её контактов.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..frame import X0, X1
from ..pen import Pen
from . import symbols as S
from .model import (BUTTON_NC, BUTTON_NO, COIL, COMMON, CONTACT_CO, CONTACT_SSR,
                    LAMP, SUPPLY, PlcChannel, PlcModule)

COL_W = (X1 - X0) / 10


def column(x: float) -> int:
    return max(0, min(9, int((x - X0) // COL_W)))


def _norm_tag(t: str) -> str:
    return t.strip().lstrip("-").upper()


def _norm_point(t: str) -> str:
    """«-A3:A9 / 10.9» -> «A3:A9»"""
    t = str(t or "").split("/")[0]
    return re.sub(r"\s+", "", t).lstrip("-").upper()


def split_link(link: str, ref: str, xr: "XRef") -> tuple[str, str]:
    """Стрелка: текст ссылки и «лист.столбец» (вручную или автоматически)."""
    link = str(link or "").strip()
    if "/" in link and not ref:                  # «-1QFU4:1 / 4.2»
        link, ref = (x.strip() for x in link.split("/", 1))
    return link, (ref.strip() or xr.point_ref(link))


# ----------------------------------------------------------------- реестр
@dataclass
class XRef:
    """Где стоят элементы: tag -> [(вид, лист, столбец)]."""
    heads: dict[str, tuple[int, int]] = field(default_factory=dict)       # катушка/лампа
    contacts: dict[str, list[tuple[str, int, int]]] = field(default_factory=dict)
    points: dict[str, tuple[int, int]] = field(default_factory=dict)      # «A3:A9» -> место

    def point(self, key: str, sheet: int, x: float):
        self.points.setdefault(_norm_point(key), (sheet, column(x)))

    def point_ref(self, link: str) -> str:
        """Ссылка «лист.столбец» для стрелки на точку (-A3:A9, -1QFU4:1, -XM1:M5)."""
        loc = self.points.get(_norm_point(link))
        return f"{loc[0]}.{loc[1]}" if loc else ""

    def head(self, t, sheet, x):
        self.heads.setdefault(_norm_tag(t), (sheet, column(x)))

    def contact(self, t, kind, sheet, x):
        self.contacts.setdefault(_norm_tag(t), []).append((kind, sheet, column(x)))

    def head_ref(self, t) -> str:
        loc = self.heads.get(_norm_tag(t))
        return f"/{loc[0]}.{loc[1]}" if loc else ""

    def mirror(self, t) -> list[tuple[str, str]]:
        return [(k, f"/{s}.{c}") for k, s, c in self.contacts.get(_norm_tag(t), [])]


# ----------------------------------------------------------------- раскладка
@dataclass
class _Pos:
    ch: PlcChannel
    x: float


@dataclass
class _Block:
    module: PlcModule
    regular: list[_Pos]
    special: list[_Pos]           # COM / +24V справа
    top: float                    # верх блока модуля
    x0: float = 0.0
    x1: float = 0.0


@dataclass
class _Page:
    kind: str                     # "in" / "out"
    blocks: list[_Block]
    number: int = 0


def _letter(pin: str) -> str:
    m = re.match(r"[A-Za-zА-Яа-я]+", pin)
    return m.group(0).upper() if m else ""


def _place(chs: list[PlcChannel], start: float, max_step: float, right: float,
           group_gap: float) -> list[_Pos]:
    """Равномерно раскладывает выводы, с доп. зазором между группами (A/B)."""
    n = len(chs)
    if n == 0:
        return []
    groups = sum(1 for i in range(1, n) if _letter(chs[i].pin) != _letter(chs[i - 1].pin))
    step = max_step if n == 1 else min(max_step, (right - start - groups * group_gap) / (n - 1))
    out, x = [], start
    for i, ch in enumerate(chs):
        if i and _letter(ch.pin) != _letter(chs[i - 1].pin):
            x += group_gap
        out.append(_Pos(ch, x))
        x += step
    return out


IN_TOP = 581.2            # верх блока модуля входов
OUT_TOPS = (82.3, 445.1)  # верх блоков выходов (две половины листа)
MAX_IN = 18               # обычных выводов на лист входов


def layout(modules: list[PlcModule]) -> list[_Page]:
    pages: list[_Page] = []
    out_blocks: list[_Block] = []

    def flush_out():
        nonlocal out_blocks
        for i in range(0, len(out_blocks), 2):
            pair = out_blocks[i:i + 2]
            for k, b in enumerate(pair):
                b.top = OUT_TOPS[k]
            pages.append(_Page("out", pair))
        out_blocks = []

    for m in modules:
        reg = [c for c in m.channels if c.element not in (COMMON, SUPPLY)]
        spec = [c for c in m.channels if c.element in (COMMON, SUPPLY)]
        if m.kind == "in":
            flush_out()
            chunks = [reg[i:i + MAX_IN] for i in range(0, max(len(reg), 1), MAX_IN)]
            for j, chunk in enumerate(chunks):
                regular = _place(chunk, 136.1, 56.7, 998.0, 11.3)
                last = regular[-1].x if regular else 136.1
                special = [_Pos(c, last + 68.0 + 34.0 * i) for i, c in
                           enumerate(spec if j == len(chunks) - 1 else [])]
                b = _Block(m, regular, special, IN_TOP)
                xs = [p.x for p in regular + special] or [136.1]
                b.x0, b.x1 = min(xs) - 45.4, max(max(xs) + 25.5, b.x0 + 200)
                pages.append(_Page("in", [b]))
        else:
            # выходы: группы по букве вывода (A…, B…), по два блока на лист
            groups: list[list[PlcChannel]] = []
            for c in reg:
                if groups and _letter(groups[-1][0].pin) == _letter(c.pin) and len(groups[-1]) < 10:
                    groups[-1].append(c)
                else:
                    groups.append([c])
            for c in spec:  # спец. выводы — в блок со своей буквой, иначе в последний
                g = next((g for g in groups if _letter(g[0].pin) == _letter(c.pin)), None)
                if g is None:
                    if not groups:
                        groups.append([])
                    g = groups[-1]
                g.append(c)
            for g in groups:
                r = [c for c in g if c.element not in (COMMON, SUPPLY)]
                s = [c for c in g if c.element in (COMMON, SUPPLY)]
                regular = _place(r, 181.4, 90.7, 900.0, 0.0)
                special = [_Pos(c, 1054.4 - 34.0 * (len(s) - 1 - i)) for i, c in enumerate(s)]
                b = _Block(m, regular, special, 0.0, 136.1, 1099.8)
                out_blocks.append(b)
    flush_out()
    return pages


# ----------------------------------------------------------------- ссылки
def register(pages: list[_Page], first_sheet: int, xr: XRef | None = None) -> XRef:
    xr = xr or XRef()
    for i, pg in enumerate(pages):
        pg.number = first_sheet + i
        for b in pg.blocks:
            for pos in b.regular + b.special:
                xr.point(f"{b.module.tag}:{pos.ch.pin}", pg.number, pos.x)
            for pos in b.regular:
                ch = pos.ch
                if not ch.device:
                    continue
                if ch.element in (COIL, LAMP):
                    xr.head(ch.device, pg.number, pos.x)
                elif ch.element in (CONTACT_SSR,):
                    xr.contact(ch.device, "no", pg.number, pos.x)
                elif ch.element in (CONTACT_CO,):
                    xr.contact(ch.device, "co", pg.number, pos.x)
                elif ch.element in (BUTTON_NO, BUTTON_NC):
                    xr.contact(ch.device, "btn", pg.number, pos.x)
    return xr


# ----------------------------------------------------------------- рисование
def painter(pg: _Page, xr: XRef):
    def draw(p: Pen) -> None:
        for b in pg.blocks:
            if pg.kind == "in":
                _draw_in(p, b, xr)
            else:
                _draw_out(p, b, xr)
    return draw


def _wire_lines(ch: PlcChannel) -> list[str]:
    return [w for w in ch.wire if w]


def _draw_in(p: Pen, b: _Block, xr: XRef) -> None:
    m, top = b.module, b.top
    bottom = top + 170.1
    p.rect(b.x0, top, b.x1, bottom, lw=1.42)
    r1, r2 = top + 124.7, top + 147.4
    p.line(b.x0, r1, b.x1, r1, 0.71, dash=([4, 3], 0))
    p.line(b.x0, r2, b.x1, r2, 0.71, dash=([4, 3], 0))
    cx = (b.x0 + b.x1) / 2
    p.text(cx, r1 + 15.5, m.type, 10.6, "center")
    p.text(cx, r2 + 15.5, m.title, 10.6, "center")
    S.tag(p, b.x0 - 4.2, top + 3.6, f"-{m.tag}", m.ref)

    pin_y = top + 11.4            # где провод входит в символ вывода
    mark_y = top - 34.0
    bus_y, feed_y = 456.5, 365.8
    relay_x, button_x = [], []

    for pos in b.regular + b.special:
        ch, x = pos.ch, pos.x
        S.pin_bottom(p, x, top)
        p.text(x, top + 36.1, ch.pin, S.PIN, "center")
        step = 56.7 if pos in b.regular else 34.0
        S.centered_lines(p, x, top + 45.3, ch.desc, step - 4)
        wired = bool(_wire_lines(ch) or ch.element or ch.link)
        if not wired:
            continue
        el = ch.element
        if el == COMMON:
            i = b.special.index(pos)
            yy = 490.5 + 22.7 * i
            S.wire(p, x, yy, pin_y)
            tip = b.special[-1].x + 17.0
            p.hline(x, tip - 7.8, yy, S.LW)
            lk, rf = split_link(ch.link, ch.ref, xr)
            S.arrow_right(p, tip, yy, lk + (f"/{rf.lstrip('/')}" if rf else ""))
        elif el in (CONTACT_SSR, CONTACT_CO):
            relay_x.append(x)
            p.vline(x, bus_y, bus_y + 11.3, S.LW_BUS)
            p.vline(x, bus_y + 11.3, 473.5, S.LW)
            ref = xr.head_ref(ch.device) or ch.ref
            if el == CONTACT_SSR:
                S.contact_ssr(p, x, 473.5, ch.device, ref)
                S.wire(p, x, 484.8, pin_y)
            else:
                S.contact_changeover(p, x, 473.5, ch.device, ref)
                S.wire(p, x, 484.8, pin_y)
        elif el in (BUTTON_NO, BUTTON_NC):
            button_x.append(x)
            S.wire(p, x, feed_y, 399.8)
            ref = xr.head_ref(ch.device) or ch.ref
            S.button(p, x, 403.0, ch.device, ref, el == BUTTON_NC)
            S.wire(p, x, 416.8, pin_y)
            if m.feed_wire:
                S.wire_mark(p, x, 388.5, m.feed_wire)
        else:
            S.wire(p, x, 473.5, pin_y)
            S.arrow_down(p, x, 473.5, *split_link(ch.link, ch.ref, xr), 8.5)
        if _wire_lines(ch):
            S.wire_mark(p, x, mark_y, _wire_lines(ch))

    # питание контактов: стрелка слева, горизонталь, спуск к шине
    if relay_x or button_x:
        drops = sorted(relay_x[:1] + button_x)
        first = drops[0]
        tip = first - 17.0
        right = max(drops)
        if m.feed_next:
            right = max(right, (max(relay_x) if relay_x else right)) + 40.0
        if m.feed:
            S.arrow_in_from_left(p, tip, feed_y, m.feed)
        p.hline(tip, right if m.feed_next else max(drops), feed_y, S.LW)
        if m.feed_next:
            S.arrow_right(p, right + 7.8, feed_y, m.feed_next)
        if relay_x:
            x = relay_x[0]
            p.vline(x, feed_y, bus_y, S.LW)
            if m.feed_wire:
                S.wire_mark(p, x, 388.5, m.feed_wire)
            if len(relay_x) > 1:
                S.bus(p, x, max(relay_x), bus_y, x + 11.3)


def _desc_rows(b: _Block, width_reg: float, width_spec: float) -> int:
    n = 0
    for pos in b.regular + b.special:
        w = width_reg if pos in b.regular else width_spec
        n = max(n, len(S.desc_lines(pos.ch.desc, w)[0]))
    return n


def _draw_out(p: Pen, b: _Block, xr: XRef) -> None:
    m, top = b.module, b.top
    rows = _desc_rows(b, 86.0, 60.0)
    bottom = top + 136.1 + max(0, rows - 3) * 11.4
    p.rect(b.x0, top, b.x1, bottom, lw=1.13)
    r1, r2 = top + 22.7, top + 45.4
    p.line(b.x0, r1, b.x1, r1, 0.71, dash=([4, 3], 0))
    p.line(b.x0, r2, b.x1, r2, 0.71, dash=([4, 3], 0))
    cx = (b.x0 + b.x1) / 2
    p.text(cx, top + 16.0, m.title, 10.6, "center")
    p.text(cx, r1 + 15.8, m.type, 10.6, "center")
    S.tag(p, b.x0 - 10.1, top - 1.8, f"-{m.tag}", m.ref)

    wire_top = bottom - 11.4
    mark_y = bottom + 45.3
    coil_y = bottom + 73.7
    bus_y = bottom + 113.4
    ret_y = bottom + 147.4
    heads: list[float] = []

    for pos in b.regular + b.special:
        ch, x = pos.ch, pos.x
        S.pin_top(p, x, bottom)
        p.text(x, bottom - 29.7, ch.pin, S.PIN, "center")
        S.centered_lines(p, x, top + 68.2, ch.desc, 86.0 if pos in b.regular else 60.0)
        el = ch.element
        wired = bool(_wire_lines(ch) or el or ch.link)
        if not wired:
            continue
        if el in (SUPPLY, COMMON):
            yy = bottom + 56.6
            S.wire(p, x, wire_top, yy)
            tip = x + 26.0
            p.hline(x, tip if el == SUPPLY else tip - 7.8, yy, S.LW)
            lk, rf = split_link(ch.link, ch.ref, xr)
            text = lk + (f"/{rf.lstrip('/')}" if rf else "")
            if el == SUPPLY:
                S.arrow_in_from_right(p, tip, yy, text)
            else:
                S.arrow_right(p, tip, yy, text)
        elif el in (COIL, LAMP):
            heads.append(x)
            S.wire(p, x, wire_top, coil_y)
            top_pin, bot_pin = ("A2", "A1") if m.npn else ("A1", "A2")
            if el == COIL:
                S.coil(p, x, coil_y, ch.device, ch.param or "=24V", top_pin, bot_pin)
                y_after = coil_y + 11.4
            else:
                S.lamp(p, x, coil_y, ch.device, ch.param)
                y_after = coil_y + 11.4
            p.vline(x, y_after, y_after + 5.6, S.LW)
            p.vline(x, y_after + 5.6, bus_y, S.LW_BUS)
            mir = xr.mirror(ch.device)
            if el == COIL:
                if not mir:
                    mir = [("co", ch.ref)]
                S.mirror(p, x, ret_y + 13.0, [(k if k != "btn" else "no", r) for k, r in mir])
        else:
            y_tip = bottom + 88.6
            S.wire(p, x, wire_top, y_tip)
            S.arrow_down_out(p, x, y_tip, *split_link(ch.link, ch.ref, xr))
        if _wire_lines(ch):
            S.wire_mark(p, x, mark_y, _wire_lines(ch))

    if heads:
        first = heads[0]
        if len(heads) > 1:
            S.bus(p, first, max(heads), bus_y, first + 22.7)
        # общий провод катушек: от шины вниз и влево к стрелке
        p.vline(first, bus_y, ret_y, S.LW)
        tip = b.x0 + 5.6
        p.hline(tip, first, ret_y, S.LW)
        if m.common_wire:
            S.hwire_mark(p, tip + 14.0, ret_y, m.common_wire)
        if m.common:
            S.arrow_in_from_left(p, tip, ret_y, m.common)
