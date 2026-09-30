"""Лист Э3 «Ввод и питание 230 В» (содержание листа 2 образца, типовая раскладка).

Слева — ввод: клеммник ввода (X0) с кабелем, выключатель-разъединитель (QS1)
и его выходы, шина нейтрали (XN) с отводами.
Сверху справа — шина фазы от QS1 и ветви «автомат + нагрузка»: розетка, лампа,
термостат + вентилятор, светильник, устройство с выводами (БП), стрелка на другой лист.
Снизу справа — самостоятельные устройства с выводами (ИБП, батарея).
Связи между частями — стрелками со ссылками «лист.столбец» (ставятся сами).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.lib.colors import white

from ..pen import PAGE_H, Pen, wrap
from . import symbols as S
from .io_sheets import XRef, split_link
from .power24 import _breaker_symbol


# ------------------------------------------------------------------ модель
@dataclass
class Pin:
    name: str                          # L, N, V+, 11 …
    top: bool = True                   # вывод сверху блока (иначе снизу)
    link: str = ""                     # куда провод: -X0.3:1L+
    ref: str = ""
    wire: list[str] = field(default_factory=list)


@dataclass
class Device:
    tag: str                           # -U1, -UPS
    title: str = ""                    # CP DC UPS 24V 20A/10A
    param: str = ""                    # 10 A
    pins: list[Pin] = field(default_factory=list)


@dataclass
class Branch:
    """Ветвь от шины фазы: автомат (может не быть) и нагрузка."""
    tag: str = ""                      # -SF1 (пусто — без автомата)
    rating: str = ""                   # 6A 'C'
    wire: list[str] = field(default_factory=list)   # провод после автомата
    load: str = "стрелка"              # розетка / лампа / термостат / светильник / устройство / стрелка
    load_tag: str = ""                 # -XS1 / -H1 / -TR1 / -EA1
    load_param: str = ""               # 16 A / AC230V Белая / -10..+80°C / 5 Вт
    load_tag2: str = ""                # для термостата: вентилятор -EC1
    load_param2: str = ""              # 100м3/ч, 230VAC
    n_link: str = ""                   # нейтраль нагрузки: -XN:N2
    link: str = ""                     # для «стрелки»: куда идёт (-QF3:1)
    ref: str = ""
    device: Device | None = None       # для «устройства»


@dataclass
class QsOutput:
    pole: str                          # 2, 4, 6, 8
    link: str = ""                     # «шина» / «N» / -QF1:1
    ref: str = ""
    wire: list[str] = field(default_factory=list)


@dataclass
class NTap:
    clamp: str                         # N1
    link: str = ""
    ref: str = ""
    wire: list[str] = field(default_factory=list)


@dataclass
class Mains:
    input_block: str = "X0"
    input_labels: list[str] = field(default_factory=lambda: ["L1", "L2", "L3", "N", "PE"])
    input_from: str = ""               # откуда ввод (-ШР)
    input_cable: str = ""              # W1E-001
    input_cable_type: str = ""         # FLEXICORE 130H-нг(A)-HF 5G2,5
    qs: str = "QS1"
    qs_rating: str = ""
    qs_poles: int = 4
    qs_outputs: list[QsOutput] = field(default_factory=list)
    n_bus: str = "XN"
    n_taps: list[NTap] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    devices: list[Device] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.qs_outputs or self.branches or self.devices or self.n_taps)


# ------------------------------------------------------------------ раскладка
BUS_Y = 105.0
BR_X0, BR_STEP = 420.0, 108.0
BR_X1 = 1120.0                  # правее — следующий лист
QS_X = [150.0, 185.0, 220.0, 255.0, 290.0, 325.0]
QS_Y = 575.0                    # середина контактов QS
X0_Y = 700.0
XN_Y = 430.0
DEV_Y0 = 525.0                  # верх блоков устройств
DEV_X0, DEV_X1 = 400.0, 1160.0


@dataclass
class _Sheet:
    mains: Mains
    branches: list[Branch]
    devices: list[Device]
    first: bool
    number: int = 0


def _br_step(b: Branch) -> float:
    if b.device and b.load.startswith("устр"):
        return max(BR_STEP, _dev_width(b.device) + 10.0)
    kind = b.load.lower()
    if kind.startswith("стрел"):
        return 80.0 if b.tag else 60.0            # только стрелка — узко
    if kind.startswith("ламп") and not b.tag:
        return 70.0
    return BR_STEP


def _branch_xs(branches: list[Branch]) -> list[float]:
    xs, x = [], BR_X0
    for b in branches:
        xs.append(x)
        x += _br_step(b)
    return xs


def _pack_branches(branches: list[Branch]) -> list[list[Branch]]:
    out, cur, x = [], [], BR_X0
    for b in branches:
        narrow = not b.tag and b.load.lower().startswith("стрел")
        if cur and x > (1160.0 if narrow else BR_X1 + 10.0):   # не влезает до рамки
            out.append(cur)
            cur, x = [], BR_X0
        cur.append(b)
        x += _br_step(b)
    if cur:
        out.append(cur)
    return out


def layout(m: Mains) -> list[_Sheet]:
    sheets = []
    # продолжение шины на другой лист (стрелка без автомата) — всегда последним
    tail = [b for b in m.branches if not b.tag and b.load.startswith("стрел")]
    brs = _pack_branches([b for b in m.branches if b not in tail] + tail) or [[]]
    devs = _pack_devices(m.devices)
    n = max(len(brs), len(devs) or 1)
    for i in range(n):
        sheets.append(_Sheet(m, brs[i] if i < len(brs) else [],
                             devs[i] if i < len(devs) else [], i == 0))
    return sheets


def _is_lamp(d: Device) -> bool:
    """Одиночная сигнальная лампа (-H1 «Сеть»): рисуем символом, а не блоком."""
    t = d.tag.lstrip("-").upper()
    return (t.startswith("H") or "ЛАМП" in d.title.upper()) and len(d.pins) <= 2


def _dev_width(d: Device) -> float:
    if _is_lamp(d):
        return 60.0
    top = sum(1 for p in d.pins if p.top)
    bot = len(d.pins) - top
    return max(120.0, 34.0 * max(top, bot, 1) + 40.0)


def _pack_devices(devs: list[Device]) -> list[list[Device]]:
    out, cur, w = [], [], 0.0
    for d in devs:
        dw = _dev_width(d) + 40.0
        if cur and w + dw - 40.0 > DEV_X1 - DEV_X0:
            out.append(cur)
            cur, w = [], 0.0
        cur.append(d)
        w += dw
    if cur:
        out.append(cur)
    return out


def _dev_positions(sh: _Sheet) -> list[float]:
    xs, x = [], DEV_X0
    for d in sh.devices:
        xs.append(x)
        x += _dev_width(d) + 40.0
    return xs


def register(sheets: list[_Sheet], first: int, xr: XRef) -> list[int]:
    nums = []
    for i, sh in enumerate(sheets):
        sh.number = first + i
        nums.append(sh.number)
        m = sh.mains
        if sh.first:
            for k in range(m.qs_poles):
                x = QS_X[k]
                for pin in (str(2 * k + 1), str(2 * k + 2)):
                    xr.point(f"{m.qs}:{pin}", sh.number, x)
            for j, t in enumerate(m.n_taps):
                xr.point(f"{m.n_bus}:{t.clamp}", sh.number, 130.0 + j * 38.0)
            for j, lab in enumerate(m.input_labels):
                xr.point(f"{m.input_block}:{lab}", sh.number, QS_X[min(j, len(QS_X) - 1)])
        for b, x in zip(sh.branches, _branch_xs(sh.branches)):
            if b.tag:
                xr.point(f"{b.tag}:1", sh.number, x)
                xr.point(f"{b.tag}:2", sh.number, x)
            if b.device:
                for p in b.device.pins:
                    xr.point(f"{b.device.tag}:{p.name}", sh.number, x)
        for d, x in zip(sh.devices, _dev_positions(sh)):
            for k, p in enumerate(d.pins):
                xr.point(f"{d.tag}:{p.name}", sh.number, x + 30.0 + 34.0 * k)
    return nums


# ------------------------------------------------------------------ рисование
def painter(sh: _Sheet, xr: XRef):
    def draw(p: Pen) -> None:
        if sh.first:
            _input(p, sh.mains, xr)
        _branches(p, sh, xr)
        for d, x in zip(sh.devices, _dev_positions(sh)):
            _device(p, d, x, DEV_Y0, xr)
    return draw


def _circ(p: Pen, x, y, r=2.9):
    p.c.saveState()
    p.c.setFillColor(white)
    p.c.setLineWidth(S.LW)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=1)
    p.c.restoreState()


def _lbl_arrow_up(p: Pen, x, tip, link, ref):
    S._tri(p, [(x - 2.8, tip + 7.8), (x + 2.8, tip + 7.8), (x, tip)])
    if ref:
        p.text(x, tip - 4.0, ref, S.PIN, "center")
    if link:
        p.text(x, tip - (13.5 if ref else 4.0), link, S.PIN, "center")


def _lbl_arrow_down(p: Pen, x, tip, link, ref):
    S._tri(p, [(x - 2.8, tip - 7.8), (x + 2.8, tip - 7.8), (x, tip)])
    if link:
        p.text(x, tip + 11.0, link, S.PIN, "center")
    if ref:
        p.text(x, tip + 20.5, ref, S.PIN, "center")


def _ground(p: Pen, x, y):
    p.hline(x - 6.0, x + 6.0, y, S.LW)
    p.hline(x - 4.0, x + 4.0, y + 2.5, S.LW)
    p.hline(x - 2.0, x + 2.0, y + 5.0, S.LW)


def _input(p: Pen, m: Mains, xr: XRef) -> None:
    labels = m.input_labels
    n_pole = m.qs_poles
    # --- клеммник ввода
    xs_in = QS_X[:len(labels)]
    for x, lab in zip(xs_in, labels):
        _circ(p, x, X0_Y)
        p.text(x + 3.6, X0_Y + 10.0, lab, S.PIN)
    p.text(xs_in[0] - 12.0, X0_Y + 4.0, f"-{m.input_block.lstrip('-')}", S.TAG, "right")
    # кабель ввода
    if m.input_cable or m.input_cable_type:
        yc = X0_Y + 40.0
        p.hline(xs_in[0] - 14.0, xs_in[-1] + 14.0, yc, S.LW)
        for x in xs_in:
            p.vline(x, X0_Y + 2.9, yc + 20.0, S.LW)
        if m.input_cable:
            p.text(xs_in[0] - 16.0, yc + 4.0, f"-{m.input_cable.lstrip('-')}", S.TAG, "right")
        p.text(xs_in[0], yc + 32.0, m.input_cable_type, S.PIN, max_width=xs_in[-1] - xs_in[0] + 60)
    if m.input_from:
        p.text(xs_in[0], X0_Y + 86.0, f"от {m.input_from}", S.PIN)
    # PE — на шину заземления
    if "PE" in labels:
        x = xs_in[labels.index("PE")]
        p.vline(x, X0_Y - 2.9, X0_Y - 30.0, S.LW)
        _ground(p, x, X0_Y - 30.0)
        p.text(x + 5.0, X0_Y - 33.0, "-XPE", S.PIN)
    # --- QS: полюса (снизу вход 1,3,5,7 — сверху выход 2,4,6,8)
    for k in range(n_pole):
        x = QS_X[k]
        if k < len(labels) and labels[k] != "PE":
            p.vline(x, QS_Y + 14.0, X0_Y - 2.9, S.LW)
            S.wire_mark(p, x, X0_Y - 40.0, [f"{m.input_block}-{labels[k]}", "OG", "2,5"])
        p.line(x, QS_Y + 14.0, x - 7.0, QS_Y - 2.0, S.LW)          # разомкнутый контакт
        p.vline(x, QS_Y - 14.0, QS_Y - 6.0, S.LW)
        p.hline(x - 2.5, x + 2.5, QS_Y - 6.0, S.LW)
        p.text(x + 2.0, QS_Y + 22.0, str(2 * k + 1), S.PIN)
        p.text(x + 2.0, QS_Y - 16.0, str(2 * k + 2), S.PIN)
    p.line(QS_X[0] - 25.0, QS_Y + 6.0, QS_X[n_pole - 1] - 3.0, QS_Y + 6.0, S.LW,
           dash=([5, 3], 0))
    p.text(QS_X[0] - 28.0, QS_Y + 3.0, f"-{m.qs.lstrip('-')}", S.TAG, "right")
    if m.qs_rating:
        p.text(QS_X[0] - 28.0, QS_Y + 14.0, m.qs_rating, S.PIN, "right")
    # --- выходы QS
    outs = {o.pole: o for o in m.qs_outputs}
    for k in range(n_pole):
        x = QS_X[k]
        o = outs.get(str(2 * k + 2))
        if not o:
            continue
        if o.link.lower() in ("шина", "bus"):
            p.vline(x, BUS_Y, QS_Y - 14.0, S.LW)
            p.hline(x, BR_X0 - 50.0, BUS_Y, S.LW)
        elif o.link.upper().startswith(("N", f"-{m.n_bus.upper()}", m.n_bus.upper())) \
                and ":" not in o.link:
            p.vline(x, XN_Y, QS_Y - 14.0, S.LW)
        else:
            tip = XN_Y + 60.0 + (k % 2) * 25.0
            p.vline(x, tip + 7.8, QS_Y - 14.0, S.LW)
            _lbl_arrow_up(p, x, tip, *split_link(o.link, o.ref, xr))
        if o.wire and any(o.wire):
            S.wire_mark(p, x, QS_Y - 40.0, [w for w in o.wire if w])
    # --- шина нейтрали XN
    if m.n_taps:
        xs = [130.0 + j * 38.0 for j in range(len(m.n_taps))]
        p.hline(xs[0] - 10.0, xs[-1] + 10.0, XN_Y, S.LW)
        p.text(xs[0] - 14.0, XN_Y + 4.0, f"-{m.n_bus.lstrip('-')}", S.TAG, "right")
        for j, (t, x) in enumerate(zip(m.n_taps, xs)):
            _circ(p, x, XN_Y)
            p.text(x + 3.0, XN_Y + 12.0, t.clamp, S.PIN)
            tip = XN_Y - 120.0 - (j % 2) * 30.0
            p.vline(x, tip + 7.8, XN_Y - 2.9, S.LW)
            _lbl_arrow_up(p, x, tip, *split_link(t.link, t.ref, xr))
            if t.wire and any(t.wire):
                S.wire_mark(p, x, XN_Y - 45.0, [w for w in t.wire if w])


def _branches(p: Pen, sh: _Sheet, xr: XRef) -> None:
    if not sh.branches:
        return
    xs = _branch_xs(sh.branches)
    p.hline(BR_X0 - 50.0, xs[-1], BUS_Y, S.LW_BUS)
    if not sh.first:
        p.text(BR_X0 - 54.0, BUS_Y + 3.5, "…", 10.6, "right")
    for i in range(len(xs) - 1):
        mx = (xs[i] + xs[i + 1]) / 2
        p.line(mx - 2.8, BUS_Y - 2.8, mx + 2.8, BUS_Y + 2.8, S.LW)
        p.text(mx + 3.0, BUS_Y - 4.0, "шина", 5.5)
    for b, x in zip(sh.branches, xs):
        y = BUS_Y
        if b.tag:
            p.vline(x, y, y + 15.0, S.LW_BUS)
            _breaker_symbol(p, x, y + 15.0, b.tag, b.rating, ("1", "2"), dc=False)
            y += 55.0
        if b.wire and any(b.wire):
            S.wire_mark(p, x, y + 25.0, [w for w in b.wire if w])
        _load(p, b, x, y + 50.0, xr)


def _n_arrow_up(p: Pen, x, y_from, link, xr):
    if not link:
        return
    tip = y_from - 42.0
    p.vline(x, tip + 7.8, y_from, S.LW)
    lk, rf = split_link(link, "", xr)
    _lbl_arrow_up(p, x, tip, lk, rf)


def _load(p: Pen, b: Branch, x: float, y: float, xr: XRef) -> None:
    kind = b.load.lower()
    xn = x + 22.7
    if kind.startswith("розет"):
        p.vline(x, y - 50.0, y, S.LW)
        p.rect(x - 10.0, y, x + 55.0, y + 26.0, S.LW)
        for xx, lab in ((x, "L"), (xn, "N"), (x + 45.4, "PE")):
            p.c.setLineWidth(S.LW)
            p.c.arc(xx - 3.0, PAGE_H - (y + 20.0) - 3.0, xx + 3.0, PAGE_H - (y + 20.0) + 3.0,
                    0, 180)
            p.vline(xx, y, y + 17.0, S.LW)
            p.text(xx + 1.5, y + 9.0, lab, S.PIN)
        p.text(x - 13.0, y + 11.0, b.load_tag, S.TAG, "right")
        p.text(x - 13.0, y + 22.0, b.load_param, S.PIN, "right")
        _n_arrow_up(p, xn, y, b.n_link, xr)
        p.vline(x + 45.4, y - 20.0, y, S.LW, )
        _ground(p, x + 45.4, y - 20.0)
    elif kind.startswith("ламп"):
        p.vline(x, y - 50.0, y + 5.0, S.LW)
        S.lamp(p, x, y + 5.0, b.load_tag, b.load_param)
        p.vline(x, y + 16.5, y + 60.0, S.LW)
        lk, rf = split_link(b.n_link, "", xr)
        _lbl_arrow_down(p, x, y + 68.0, lk, rf)
    elif kind.startswith("термостат"):
        p.vline(x, y - 50.0, y, S.LW)
        p.rect(x - 22.0, y, x + 22.0, y + 70.0, S.LW)
        for yy, lab in ((y + 12.0, "1"), (y + 58.0, "2")):
            _circ(p, x, yy, 2.5)
            p.text(x + 4.0, yy + 3.0, lab, S.PIN)
        p.line(x, y + 26.0, x + 8.0, y + 44.0, S.LW)                  # контакт NO
        p.text(x + 26.0, y + 12.0, b.load_tag, S.TAG)
        p.text(x + 26.0, y + 23.0, b.load_param, S.PIN)
        # вентилятор
        ym = y + 150.0
        p.vline(x, y + 60.5, ym - 16.0, S.LW)
        p.c.setLineWidth(S.LW)
        p.c.circle(x + 11.0, PAGE_H - ym, 16.0, stroke=1, fill=0)
        p.text(x + 11.0, ym + 3.0, "M", S.TAG, "center")
        p.text(x + 11.0, ym + 12.0, "1~", S.PIN, "center")
        p.text(x - 9.0, ym + 3.0, b.load_tag2, S.TAG, "right")
        p.text(x - 9.0, ym + 14.0, b.load_param2, S.PIN, "right", max_width=90)
        p.vline(xn, ym - 60.0, ym - 12.0, S.LW)
        lk, rf = split_link(b.n_link, "", xr)
        _lbl_arrow_up(p, xn, ym - 70.0, lk, rf)
    elif kind.startswith("светил"):
        p.vline(x, y - 50.0, y, S.LW)
        p.rect(x - 12.0, y, x + 35.0, y + 34.0, S.LW)
        for xx, lab in ((x, "L"), (xn, "N")):
            _circ(p, xx, y + 6.0, 2.3)
            p.text(xx + 3.0, y + 3.0, lab, 5.5)
        p.line(x + 3.0, y + 26.0, x + 20.0, y + 26.0, S.LW)
        p.line(x + 11.5, y + 14.0, x + 11.5, y + 26.0, S.LW)
        p.text(x - 15.0, y + 11.0, b.load_tag, S.TAG, "right")
        p.text(x - 15.0, y + 22.0, b.load_param, S.PIN, "right")
        _n_arrow_up(p, xn, y, b.n_link, xr)
    elif kind.startswith("устр") and b.device:
        p.vline(x, y - 50.0, y + 30.0, S.LW)
        _device(p, b.device, x - 30.0, y + 30.0, xr, feed_pin_x=x)
    else:                                                        # стрелка
        p.vline(x, y - 50.0, y + 30.0, S.LW)
        _lbl_arrow_down(p, x, y + 38.0, *split_link(b.link, b.ref, xr))


def _device(p: Pen, d: Device, x0: float, y0: float, xr: XRef,
            feed_pin_x: float | None = None) -> None:
    """Блок устройства с выводами сверху и снизу; у свободных выводов — провода-стрелки."""
    if _is_lamp(d):
        _lamp_device(p, d, x0, y0, xr)
        return
    top = [pn for pn in d.pins if pn.top]
    bot = [pn for pn in d.pins if not pn.top]
    w = _dev_width(d)
    h = 110.0
    p.rect(x0, y0, x0 + w, y0 + h, 1.13)
    p.text(x0 - 4.0, y0 + 10.0, d.tag, S.TAG, "right")
    if d.param:
        p.text(x0 - 4.0, y0 + 22.0, d.param, S.PIN, "right")
    for ln_i, ln in enumerate(wrap(d.title, w - 20, 8.5)[:3]):
        p.text(x0 + w / 2, y0 + h / 2 + 3.0 + ln_i * 10.5, ln, 8.5, "center")
    for k, pn in enumerate(top):
        x = x0 + 30.0 + 34.0 * k
        _circ(p, x, y0 + 12.0)
        p.text(x + 4.0, y0 + 26.0, pn.name, S.PIN)
        if feed_pin_x is not None and k == 0:
            continue                                  # первый вывод питается от ветви
        lk, rf = split_link(pn.link, pn.ref, xr)
        if lk or (pn.wire and any(pn.wire)):
            tip = y0 - 45.0 - (k % 2) * 18.0
            p.vline(x, tip + 7.8, y0 + 9.1, S.LW)
            _lbl_arrow_up(p, x, tip, lk, rf)
            if pn.wire and any(pn.wire):
                S.wire_mark(p, x, y0 - 22.0, [w for w in pn.wire if w])
    for k, pn in enumerate(bot):
        x = x0 + 30.0 + 34.0 * k
        _circ(p, x, y0 + h - 12.0)
        p.text(x + 4.0, y0 + h - 18.0, pn.name, S.PIN)
        lk, rf = split_link(pn.link, pn.ref, xr)
        if lk or (pn.wire and any(pn.wire)):
            tip = y0 + h + 50.0 + (k % 2) * 18.0
            p.vline(x, y0 + h - 9.1, tip - 7.8, S.LW)
            _lbl_arrow_down(p, x, tip, lk, rf)
            if pn.wire and any(pn.wire):
                S.wire_mark(p, x, y0 + h + 22.0, [w for w in pn.wire if w])


def _lamp_device(p: Pen, d: Device, x0: float, y0: float, xr: XRef) -> None:
    """Лампа: вывод x2 сверху, x1 снизу, провода — стрелками со ссылками."""
    x, yl = x0 + 40.0, y0 + 40.0
    S.lamp(p, x, yl, d.tag if d.tag.startswith("-") else f"-{d.tag}",
           d.param or d.title)
    pins = list(d.pins) + [Pin("")] * (2 - len(d.pins))
    # верхний вывод — «x2»/«X2»/второй, нижний — «x1»/первый
    up = next((pn for pn in pins if pn.name.upper() == "X2"), pins[1])
    down = next((pn for pn in pins if pn is not up), pins[0])
    for pn, sign in ((up, -1), (down, 1)):
        lk, rf = split_link(pn.link, pn.ref, xr)
        if not (lk or (pn.wire and any(pn.wire))):
            continue
        if sign < 0:
            tip = yl - 45.0
            p.vline(x, tip + 7.8, yl, S.LW)
            _lbl_arrow_up(p, x, tip, lk, rf)
            if pn.wire and any(pn.wire):
                S.wire_mark(p, x, yl - 20.0, [w for w in pn.wire if w])
        else:
            tip = yl + 11.4 + 45.0
            p.vline(x, yl + 11.4, tip - 7.8, S.LW)
            _lbl_arrow_down(p, x, tip, lk, rf)
            if pn.wire and any(pn.wire):
                S.wire_mark(p, x, yl + 30.0, [w for w in pn.wire if w])
