"""Листы Э3 «Коробки / внешние шкафы» (листы 12–16 образца).

Лист — зона (+1KK1, +ZM) с удалённым концом сверху, полевые кабели, клеммники
шкафа (двухъярусные, клеммы чередуются по ярусам) и то, что подключено снизу:
стрелки к ПЛК / источникам питания или реле (катушка / контакт на паре клемм).
Размеры — по листам 12 и 15 образца.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.lib.colors import white

from ..pen import PAGE_H, Pen, text_width
from . import symbols as S
from .io_sheets import XRef, split_link


# ------------------------------------------------------------------ модель
@dataclass
class FieldTerm:
    clamp: str                          # L+, M, 1, 2 …
    core: str = ""                      # жила кабеля
    remote: str = ""                    # +1KK1-XT1:L+ (стрелка вверх/вниз) или вывод устройства (8, 0V)
    remote_ref: str = ""                # +1KK1/2.0
    dir: str = "in"                     # in — сигнал из поля в шкаф; out — из шкафа в поле
    wire: list[str] = field(default_factory=list)
    element: str = ""                   # "" стрелка / катушка / контакт / ттр-контакт (на паре клемм)
    device: str = ""                    # -1K3
    param: str = ""                     # =24В, ТТР
    link: str = ""                      # -CPU:A1 / -2QFU1:1
    ref: str = ""
    caption: str = ""                   # подпись внизу (строки через \n)
    bridge: str = ""                    # перемычка по ярусу (одинаковый номер)


@dataclass
class FieldGroup:
    block: str                          # клеммник 1XT1
    cable: str = ""                     # WIO-1ENC1
    cable_ref: str = ""                 # +1KK1/2.0
    cable_type: str = ""                # FLEXICORE 135 CH нг(A)-HF 7G0,75
    shield: bool = False                # экран → -XSH
    pe: bool = False                    # клемма PE в конце
    paired: bool = False                # клеммы парами (реле на паре), как 1XT3 / 3XT1
    remote_device: str = ""             # -CC_CPW: удалённый конец — выводы устройства
    terms: list[FieldTerm] = field(default_factory=list)


@dataclass
class FieldArea:
    zone: str                           # +1KK1 / +ZM
    groups: list[FieldGroup] = field(default_factory=list)
    sheet: str = ""                     # номер листа (пусто — следующий по порядку)


# ------------------------------------------------------------------ раскладка
X_START = 159.0
STEP, PAIR = 34.0, 79.4
GROUP_GAP = 68.2
X_MAX = 1160.0
ZONE_Y0, ZONE_Y1 = 88.0, 311.0
@dataclass
class _Style:
    tier: tuple                 # y ярусов клемм
    mark: float                 # засечки маркировки
    coil: float                 # верх катушки
    loop: float                 # петля от второй клеммы пары
    mir_dx: float               # «зеркало» контактов под катушкой
    mir_dy: float
    cap_y: float = 683.0         # низ подписей
    cap_dx: float = 4.4


_BOX = _Style((377.3, 389.3), 445.5, 473.5, 523.0, 8.8, 8.7, 683.0, 4.4)   # коробки (лист 12)
_CPW = _Style((377.3, 396.5), 433.8, 461.0, 523.0, -0.8, 20.1, 694.5, 10.3)  # шкаф CPW (лист 15)
TIER = _BOX.tier
CAPTION_Y = 683.0


def _term_x(g: FieldGroup, x0: float, i: int) -> float:
    if g.paired:
        return x0 + (i // 2) * PAIR + (i % 2) * STEP
    return x0 + i * STEP


def _group_width(g: FieldGroup) -> float:
    n = len(g.terms)
    w = _term_x(g, 0.0, max(n - 1, 0))
    if g.pe or g.shield:
        w += 22.6
    return w


@dataclass
class _Sheet:
    area: FieldArea
    groups: list[tuple[FieldGroup, float]]     # группа и x первой клеммы
    number: int = 0


def layout(areas: list[FieldArea]) -> list[_Sheet]:
    sheets = []
    for a in areas:
        cur, x = [], X_START
        for g in a.groups:
            w = _group_width(g)
            if cur and x + w > X_MAX:
                sheets.append(_Sheet(a, cur))
                cur, x = [], X_START
            if cur and g.paired and not g.remote_device:
                x += 12.0                    # перед клеммником с реле — чуть шире (как в образце)
            cur.append((g, x))
            x += w + GROUP_GAP
        if cur:
            sheets.append(_Sheet(a, cur))
    return sheets


def register(sheets: list[_Sheet], first: int, xr: XRef) -> list[int]:
    nums = []
    nxt = first
    for sh in sheets:
        want = str(sh.area.sheet or "").strip()
        sh.number = max(int(want), nxt) if want.isdigit() and sh is _first_of(sheets, sh) else nxt
        nxt = sh.number + 1
        nums.append(sh.number)
        for g, x0 in sh.groups:
            for k, t in enumerate(g.terms):
                x = _term_x(g, x0, k)
                xr.point(f"{g.block}:{t.clamp}", sh.number, x)
                if t.device and t.element:
                    el = t.element.lower()
                    if el.startswith("кат"):
                        xr.head(t.device, sh.number, x)
                    elif el.startswith("ттр"):
                        xr.contact(t.device, "no", sh.number, x)
                    elif el.startswith("конт"):
                        xr.contact(t.device, "co", sh.number, x)
    return nums


def _first_of(sheets, sh) -> "_Sheet":
    return next(x for x in sheets if x.area is sh.area)


# ------------------------------------------------------------------ рисование
def painter(sh: _Sheet, xr: XRef):
    def draw(p: Pen) -> None:
        _zone(p, sh)
        for g, x0 in sh.groups:
            _group(p, g, x0, xr)
    return draw


def _dash_dot_rect(p: Pen, x0, y0, x1, y1):
    p.c.saveState()
    p.c.setDash([9.0, 2.5, 1.5, 2.5], 0)
    p.rect(x0, y0, x1, y1, 0.71)
    p.c.restoreState()


def _dashed(p: Pen, draw):
    p.c.saveState()
    p.c.setDash([4.5, 3.0], 0)
    draw()
    p.c.restoreState()


def _circle(p: Pen, x, y, r=2.8):
    p.c.saveState()
    p.c.setLineWidth(S.LW)
    p.c.setFillColor(white)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=1)
    p.c.restoreState()


def _zone(p: Pen, sh: _Sheet):
    x_last = max(x0 + _group_width(g) for g, x0 in sh.groups)
    cpw = any(g.remote_device for g, _ in sh.groups)
    x0 = 87.0 if not cpw else 90.0
    x1 = max(x_last + 30.0, 1150.0)
    y0, y1 = (ZONE_Y0, ZONE_Y1) if not cpw else (83.0, 305.0)
    _dash_dot_rect(p, x0, y0, min(x1, 1165.0), y1)
    p.text(x0 + (0.0 if not cpw else 9.8), y0 - (9.0 if not cpw else 9.0), sh.area.zone, 10.6)


def _group(p: Pen, g: FieldGroup, x0: float, xr: XRef):
    st = _CPW if g.remote_device else _BOX
    xs = [_term_x(g, x0, i) for i in range(len(g.terms))]
    if not xs:
        return
    x_end = xs[-1] + 22.6
    # --- удалённый конец
    if g.remote_device:
        rx0, rx1 = xs[0] - 34.0, xs[-1] + 34.0
        _dashed(p, lambda: p.rect(rx0, 116.0, rx1, 160.0, 0.71))
        p.text(xs[0] - 24.3, 106.5, f"-{g.remote_device.lstrip('-')}", 10.6)
    for x, t in zip(xs, g.terms):
        if g.remote_device:
            if t.remote:
                _circle(p, x, 136.0)
                p.text(x, 133.2, t.remote, 7.7, "center")
                p.vline(x, 138.8, st.tier[xs.index(x) % 2] - 2.8, S.LW)
        elif t.remote:
            up = t.dir == "out"
            tip = 156.0 if up else 167.4
            if up:
                S._tri(p, [(x - 2.8, tip + 7.8), (x + 2.8, tip + 7.8), (x, tip)])
            else:
                S._tri(p, [(x - 2.8, tip - 7.8), (x + 2.8, tip - 7.8), (x, tip)])
            y_line_top = tip + (7.8 if up else 0.0)
            tier_y = st.tier[xs.index(x) % 2]
            p.vline(x, y_line_top, tier_y - 2.8, S.LW)
            lk, rf = split_link(t.remote, t.remote_ref, xr)
            p.text(x - 3.0, 153.2, lk, 7.7, rotate=90)
            if rf:
                p.text(x + 6.4, 146.0, rf, 7.7, rotate=90)
        else:
            tier_y = st.tier[xs.index(x) % 2]
    # --- кабель
    if g.cable or g.cable_type:
        cx0, cx1 = xs[0] - 12.0, x_end + 4.0
        if g.shield:
            _dashed(p, lambda: (p.hline(cx0, cx1, 221.2, 0.71), p.hline(cx0, cx1, 238.2, 0.71)))
            for xx, a0, a1 in ((cx0, 90, 270), (cx1, 270, 450)):
                p.c.saveState()
                p.c.setLineWidth(0.71)
                p.c.arc(xx - 4.25, PAGE_H - 238.2, xx + 4.25, PAGE_H - 221.2, a0, 180)
                p.c.restoreState()
            p.text(x_end + 2.0, 228.3, "SH", 5.5)
            # экран на шину -XSH
            p.vline(x_end, 229.7, 347.0, S.LW)
            _dashed(p, lambda: p.hline(x_end - 9.0, x_end + 9.0, 349.8, S.LW))
            _circle(p, x_end, 349.8, 2.8)
            p.text(x_end + 2.9, 364.8, "-XSH", 7.7)
        else:
            p.hline(cx0, xs[-1] + 60.0, 237.0, 0.71)
        for x, t in zip(xs, g.terms):
            if t.core:
                p.text(x + 4.0, 228.3 if g.shield else 239.6, t.core, 5.5)
        base = xs[0] - 38.0
        top = 185.6 if g.shield else 205.0            # подписи кабеля выровнены по верху
        for dx, txt, size in ((0.0, f"-{g.cable.lstrip('-')}", 10.6),
                              (10.0, g.cable_ref, 7.7), (19.0, g.cable_type, 7.7)):
            if txt:
                p.text(base + dx, top + text_width(txt, size), txt, size, rotate=90)
    # --- клеммник: два яруса, клеммы чередуются
    p.text(xs[0] - 9.0, st.tier[0] + 4.2, f"-{g.block.lstrip('-')}", 10.6, "right")
    if len(xs) > 1:
        p.text(xs[1] - (6.5 if g.remote_device else 2.0), st.tier[1] + (1.8 if g.remote_device else 5.7),
               f"-{g.block.lstrip('-')}", 10.6, "right")
    bridges: dict[str, list[tuple[float, float]]] = {}
    def ty(i):                       # нижний ярус; клеммы с перемычкой — ещё ниже
        if i % 2 == 0:
            return st.tier[0]
        return 396.5 if g.terms[i].bridge else 389.3
    for i, (x, t) in enumerate(zip(xs, g.terms)):
        y = ty(i)
        _circle(p, x, y)
        p.text(x + 3.7, y + (4.2 if i % 2 == 0 else 0.8), t.clamp, 7.7)
        if t.bridge:
            bridges.setdefault(t.bridge, []).append((x, y))
    for pts in bridges.values():
        if len(pts) > 1:
            y = pts[0][1]
            p.hline(pts[0][0] + 2.8, pts[-1][0] - 2.8, y, S.LW)
            for x, _ in pts[1:-1]:
                p.dot(x, y, 1.6)
    if g.pe:
        _circle(p, x_end, st.tier[1] - 3.0)
        p.text(x_end + 3.8, st.tier[1] + 5.6, "PE", 7.7)
    # --- снизу: провод, маркировка, стрелка / реле
    i = 0
    while i < len(g.terms):
        t, x = g.terms[i], xs[i]
        y = ty(i)
        el = t.element.lower()
        nxt = (g.terms[i + 1], xs[i + 1]) if i + 1 < len(g.terms) else None
        if el and nxt:
            _relay(p, t, x, y, nxt[0], nxt[1], ty(i + 1), xr, st)
            i += 2
            continue
        if t.wire and any(t.wire):
            S.wire_mark(p, x, st.mark, [w for w in t.wire if w])
        lk, rf = split_link(t.link, t.ref, xr)
        power = any(k in lk.upper() for k in ("QFU", "XM", "QF", "L+"))
        if t.dir == "out" and lk and not power:             # выход ПЛК → клемма (стрелка вверх)
            p.vline(x, y + 2.8, 540.8, S.LW)
            S._tri(p, [(x - 2.8, 540.8), (x + 2.8, 540.8), (x, 533.0)])
            p.text(x, 554.0, lk, 7.7, "center")
            if rf:
                p.text(x, 563.2, rf, 7.7, "center")
        elif t.dir == "out" and lk:                         # питание из шкафа → клемма
            tip = 457.5
            p.vline(x, y + 2.8, tip, S.LW)
            S._tri(p, [(x - 2.8, tip + 7.8), (x + 2.8, tip + 7.8), (x, tip)])
            p.text(x, 487.0, lk, 7.7, "center")
            if rf:
                p.text(x, 496.2, rf, 7.7, "center")
        elif lk:                                            # клемма → ПЛК
            p.vline(x, y + 2.8, 533.0, S.LW)
            S.arrow_down_out(p, x, 533.0, lk, rf)
        elif t.wire and any(t.wire):
            p.vline(x, y + 2.8, st.mark + 8.0, S.LW)
        _caption(p, x, t.caption, st)
        i += 1


def _relay(p: Pen, a: FieldTerm, xa, ya, b: FieldTerm, xb, yb, xr: XRef, st: _Style = _BOX):
    """Реле на паре клемм: катушка (A1/A2) или контакт (11/14, 13+/14) на первой клемме,
    вторая клемма возвращается снизу петлёй."""
    el = a.element.lower()
    for t, x in ((a, xa), (b, xb)):
        if t.wire and any(t.wire):
            S.wire_mark(p, x, st.mark, [w for w in t.wire if w])
    if el.startswith("кат"):
        p.vline(xa, ya + 2.8, st.coil, S.LW)
        S.coil(p, xa, st.coil, a.device, a.param or "=24V")
        p.vline(xa, st.coil + 11.4, st.loop, S.LW)
        mir = xr.mirror(a.device)
        if mir:
            S.mirror(p, xa + st.mir_dx, st.loop + st.mir_dy, [(k if k != "btn" else "no", r) for k, r in mir])
    else:
        ref = xr.head_ref(a.device) or a.ref
        p.vline(xa, ya + 2.8, st.coil, S.LW)
        if el.startswith("ттр"):
            S.contact_ssr(p, xa, st.coil, a.device, ref)
            p.vline(xa, st.coil + 11.3, st.loop, S.LW)
        else:
            S.contact_changeover(p, xa, st.coil, a.device, ref)
            p.vline(xa, st.coil + 17.0, st.loop, S.LW)
    p.hline(xa, xb, st.loop, S.LW)
    p.vline(xb, yb + 2.8, st.loop, S.LW)
    _caption(p, xa, a.caption, st)
    _caption(p, xb, b.caption, st)


def _caption(p: Pen, x, text: str, st: "_Style" = None):
    if not text:
        return
    st = st or _BOX
    for k, ln in enumerate(str(text).split("\n")):
        p.text(x + st.cap_dx + 11.0 * k, st.cap_y, ln, 10.6, rotate=90)
