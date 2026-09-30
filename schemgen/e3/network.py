"""Лист Э3 «Сеть»: коммутаторы, ПК, ПЛК, панели, кабели Ethernet/USB/HDMI.

Устройства — прямоугольники с портами; кабели — толстые линии с подписью
(обозначение, марка, длина). Порт, ведущий наружу, поднимается через панельный
разъём (XETH…) в зону (+1KK1, +ZM) к удалённому концу — стрелке или устройству
(принтер, сервер). Порты, соединённые между собой, разводятся ортогонально по
горизонтальным «дорожкам» между рядами. Стиль и размеры — по листу 5 образца.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.lib.colors import white

from ..pen import ASSETS, PAGE_H, Pen, text_width, wrap
from . import symbols as S
from .io_sheets import XRef, split_link

LOGOS = ASSETS / "logos"
LW_NET = 1.42


# ------------------------------------------------------------------ модель
@dataclass
class NetPort:
    name: str                       # 1, LAN A, USB3.0, HDMI, P1
    kind: str = "rj45"              # rj45 / lan / usb / usb2 / hdmi
    side: str = "top"               # top / bottom — где порт на устройстве


@dataclass
class NetPower:
    pin: str                        # V+, V-, +24V, 0V, +, -
    link: str = ""                  # -1QFU2:1
    ref: str = ""
    wire: list[str] = field(default_factory=list)


@dataclass
class NetDevice:
    tag: str                        # -ES2
    name: str = ""                  # EDS-208
    brand: str = ""                 # moxa / inovance / ifc / weidmuller
    row: str = "top"                # top / bottom
    ref: str = ""                   # /6.1 — где изображён подробно
    ports: list[NetPort] = field(default_factory=list)
    power: list[NetPower] = field(default_factory=list)
    pe: bool = False                # вывод PE на шину -XPE
    modules: list[str] = field(default_factory=list)   # «A1 GL20-1600END /8.0» — модули ПЛК


@dataclass
class NetLink:
    cable: str = ""                 # W001
    cable_type: str = ""            # S/FTP, CAT6A
    length: str = ""                # 1 м
    a: str = ""                     # -ES2:1
    b: str = ""                     # -PC1:LAN A (второе устройство на листе)
    socket: str = ""                # XETH1 / XUSB1 — панельный разъём на шкафу
    socket_kind: str = "RJ45"       # RJ45 / USB A
    zone: str = ""                  # +1KK1 / +ZM — где удалённый конец
    remote: str = ""                # +1KK1-XETH1:RJ45 — стрелка к удалённому концу
    remote_ref: str = ""            # +1KK1/3.1
    remote_cable: str = ""          # WET-1CM1 — кабель от разъёма до удалённого конца
    remote_cable_type: str = ""     # F/UTP CAT6
    target: str = ""                # -1PR1 — удалённое устройство (вместо стрелки)
    target_title: str = ""          # Принтер
    target_port: str = ""           # P1 / USB
    note: str = ""                  # «*входит в поставку монитора»


@dataclass
class Network:
    devices: list[NetDevice] = field(default_factory=list)
    links: list[NetLink] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.devices or self.links)


def _norm(t: str) -> str:
    return str(t or "").strip().lstrip("-").upper()


def split_end(end: str) -> tuple[str, str]:
    """«-ES2:1» → («ES2», «1»)."""
    s = str(end or "").strip()
    if ":" not in s:
        return _norm(s), ""
    a, b = s.split(":", 1)
    return _norm(a), b.strip()


# ------------------------------------------------------------------ раскладка
TOP_Y0, TOP_Y1 = 394.1, 510.3        # верхний ряд устройств
BOT_Y0, BOT_Y1 = 617.0, 740.0        # нижний ряд
PORT_STEP = 63.2                     # шаг портов RJ45
X_LEFT, X_RIGHT = 110.6, 1115.0
X_EXT = 1140.0                       # вертикали кабелей снизу наружу
SOCKET_Y = 290.0                     # панельные разъёмы
ZONE_Y0, ZONE_Y1 = 73.7, 262.0       # зоны (+1KK1, +ZM)


@dataclass
class _Dev:
    d: NetDevice
    x0: float
    x1: float
    y0: float
    y1: float
    ports: dict                      # имя порта -> (x, y якоря, сторона)


def _dev_width(d: NetDevice) -> float:
    top = [p for p in d.ports if p.side == "top"]
    bot = [p for p in d.ports if p.side != "top"]
    n = max(len(top), len(bot), 1)
    left = 40.0 + 25.0 * len(d.power) if d.power else 90.0
    w = left + n * PORT_STEP + 20.0
    if d.modules:
        w += 26.0 * len(d.modules) + 10.0
    return max(w, 190.0)


def _place_row(devs: list[NetDevice], y0: float, y1: float) -> list[_Dev]:
    if not devs:
        return []
    widths = [_dev_width(d) for d in devs]
    gap = 40.0
    total = sum(widths) + gap * (len(devs) - 1)
    scale = min(1.0, (X_RIGHT - X_LEFT - gap * (len(devs) - 1)) / max(sum(widths), 1))
    x = X_LEFT
    out = []
    for d, w in zip(devs, widths):
        w *= scale
        pd = _Dev(d, x, x + w, y0, y1, {})
        top = [p for p in d.ports if p.side == "top"]
        bot = [p for p in d.ports if p.side != "top"]
        left = x + ((40.0 + 25.0 * len(d.power)) if d.power else 90.0) * scale
        mods = (26.0 * len(d.modules) + 10.0) * scale if d.modules else 0.0
        step = min(PORT_STEP, (w - (left - x) - 20.0 - mods) / max(len(top), len(bot), 1))
        for i, p in enumerate(top):
            pd.ports[p.name.upper()] = (left + step * (i + 0.5), y0 + 22.7, "top", p)
        for i, p in enumerate(bot):
            pd.ports[p.name.upper()] = (left + step * (i + 0.5), y1 - 22.7, "bottom", p)
        out.append(pd)
        x += w + gap
    if total < X_RIGHT - X_LEFT:
        pass
    return out


@dataclass
class _Sheet:
    net: Network
    number: int = 0


def layout(net: Network) -> list[_Sheet]:
    return [_Sheet(net)] if net else []


def _sided(net: Network) -> Network:
    """Стороны портов по смыслу соединений (модель часто ставит их как попало):
    кабель наружу от верхнего ряда — порт сверху; между рядами — навстречу друг другу;
    два устройства нижнего ряда — оба порта сверху (под рядом места нет)."""
    from dataclasses import replace
    row = {_norm(d.tag): d.row for d in net.devices}
    want: dict = {}
    for l in net.links:
        ta, pa = split_end(l.a)
        tb, pb = split_end(l.b) if l.b else ("", "")
        ra, rb = row.get(ta), row.get(tb)
        if ra is None:
            continue
        if rb is None:                                   # наружу
            if ra == "top":
                want[(ta, pa.upper())] = "top"
        elif ra == rb == "bottom":
            want[(ta, pa.upper())] = want[(tb, pb.upper())] = "top"
        elif ra != rb:
            want[(ta, pa.upper())] = "bottom" if ra == "top" else "top"
            want[(tb, pb.upper())] = "bottom" if rb == "top" else "top"
    if not want:
        return net
    devs = []
    for d in net.devices:
        t = _norm(d.tag)
        ports = [replace(pt, side=want.get((t, pt.name.upper()), pt.side)) for pt in d.ports]
        devs.append(replace(d, ports=ports))
    return replace(net, devices=devs)


def register(sheets: list[_Sheet], first: int, xr: XRef) -> list[int]:
    nums = []
    for i, sh in enumerate(sheets):
        sh.number = first + i
        nums.append(sh.number)
        net = _sided(sh.net)
        devs = _place_row([d for d in net.devices if d.row == "top"], TOP_Y0, TOP_Y1) + \
            _place_row([d for d in net.devices if d.row != "top"], BOT_Y0, BOT_Y1)
        for pd in devs:
            xr.point(pd.d.tag, sh.number, (pd.x0 + pd.x1) / 2)
            for name, (x, _, _, _) in pd.ports.items():
                xr.point(f"{pd.d.tag}:{name}", sh.number, x)
    return nums


# ------------------------------------------------------------------ рисование
def painter(sh: _Sheet, xr: XRef):
    def draw(p: Pen) -> None:
        net = _sided(sh.net)
        devs = _place_row([d for d in net.devices if d.row == "top"], TOP_Y0, TOP_Y1) + \
            _place_row([d for d in net.devices if d.row != "top"], BOT_Y0, BOT_Y1)
        by_tag = {_norm(pd.d.tag): pd for pd in devs}
        for pd in devs:
            _device(p, pd, xr)
        _links(p, net.links, by_tag, xr)
    return draw


def _dashed_rect(p: Pen, x0, y0, x1, y1, lw=0.71, dash=(4.5, 3.0)):
    p.c.saveState()
    p.c.setDash(*[list(dash), 0])
    p.rect(x0, y0, x1, y1, lw)
    p.c.restoreState()


def _dash_dot_rect(p: Pen, x0, y0, x1, y1):
    _dashed_rect(p, x0, y0, x1, y1, 0.71, (9.0, 2.5, 1.5, 2.5))


def _circle(p: Pen, x, y, r=2.8, fill=True):
    p.c.saveState()
    p.c.setLineWidth(S.LW)
    if fill:
        p.c.setFillColor(white)
    p.c.circle(x, PAGE_H - y, r, stroke=1, fill=1 if fill else 0)
    p.c.restoreState()


def _logo(p: Pen, brand: str, x0, y_top, w):
    for ext in ("png", "jpg"):
        f = LOGOS / f"{brand.lower()}.{ext}"
        if f.is_file():
            w, h = {"moxa": (62.0, 16.3), "inovance": (34.0, 34.0), "ifc": (27.0, 27.0),
                    "weidmuller": (68.0, 13.8)}.get(brand.lower(), (w, w * 0.4))
            p.image(f, x0, y_top, x0 + w, y_top + h)
            return


# RJ45 порта устройства (черная рамка с «ключом»), координаты от центра кружка
_RJ45_BLACK = [(-15.2, -11.7, -12.7, -5.3), (-14.0, -11.7, -7.6, -9.1), (7.7, -11.7, 15.4, -9.2),
               (12.8, -11.7, 15.4, -5.3), (-15.2, -5.3, -10.9, -0.2), (11.1, -5.3, 15.4, -0.2),
               (-15.2, -0.2, -11.9, 7.5), (12.1, -0.2, 15.4, 7.4), (-15.2, 7.0, -7.5, 10.0),
               (7.8, 6.9, 15.4, 10.0), (-15.2, 10.0, -3.7, 13.8), (3.9, 10.0, 15.4, 13.8),
               (-6.3, 12.5, 6.5, 13.8)]
_RJ45_PINS = [-7.6, -6.3, -5.0, -2.5, 0.1, 2.6, 5.2, 7.7]


def _rj45_port(p: Pen, x, y, flip: bool = False):
    """Порт RJ45 на устройстве; (x, y) — кружок, куда приходит кабель.
    flip — зеркально по вертикали (кабель уходит вниз)."""
    k = -1 if flip else 1
    p.rect(x - 19.0, y - 15.6 if not flip else y - 17.6, x + 19.3, y + 17.6 if not flip else y + 15.6,
           0.37)
    p.c.saveState()
    p.c.setFillColorRGB(0, 0, 0)
    for a, b, c, d in _RJ45_BLACK:
        ya, yb = sorted((y + k * b, y + k * d))
        p.rect(x + a, ya, x + c, yb, stroke=False, fill=True)
    p.c.restoreState()
    for dx in _RJ45_PINS:
        p.vline(x + dx, y + k * -11.7, y + k * -6.6, 0.37)
    _circle(p, x, y, 2.8)
    p.text(x, y + (9.5 if not flip else -5.6), "RJ45", 5.5, "center")


def _small_port(p: Pen, x, y_icon, kind: str):
    """Небольшие значки портов ПК/панели: usb, usb2, hdmi, lan."""
    if kind in ("usb", "usb2"):
        p.rect(x - 14.0, y_icon, x + 14.0, y_icon + 14.0, 0.37)
        p.rect(x - 12.3, y_icon + 1.7, x + 12.3, y_icon + 12.3, 0.37)
        p.rect(x - 9.5, y_icon + 5.5, x + 9.5, y_icon + 8.5, 0.37)
    elif kind == "hdmi":
        p.rect(x - 18.0, y_icon, x + 18.0, y_icon + 13.0, 0.37)
        p.rect(x - 15.5, y_icon + 2.5, x + 15.5, y_icon + 8.5, 0.37)
        p.line(x - 15.5, y_icon + 8.5, x - 12.5, y_icon + 10.5, 0.37)
        p.line(x + 15.5, y_icon + 8.5, x + 12.5, y_icon + 10.5, 0.37)
        p.hline(x - 12.5, x + 12.5, y_icon + 10.5, 0.37)
    else:                                                       # lan: контур RJ45
        p.rect(x - 14.0, y_icon, x + 14.0, y_icon + 22.0, 0.5)
        pts = [(-10, 18), (-10, 8), (-6, 8), (-6, 5), (-3, 5), (-3, 2), (3, 2), (3, 5), (6, 5),
               (6, 8), (10, 8), (10, 18), (-10, 18)]
        for (a, b), (c, d) in zip(pts, pts[1:]):
            p.line(x + a, y_icon + b, x + c, y_icon + d, 0.5)


def _device(p: Pen, pd: _Dev, xr: XRef):
    d = pd.d
    p.rect(pd.x0, pd.y0, pd.x1, pd.y1, 1.42)
    S.tag(p, pd.x0 - 6.0, pd.y0 - 4.0, d.tag if d.tag.startswith("-") else f"-{d.tag}", d.ref)
    # название и логотип
    has_power = bool(d.power)
    nx = pd.x0 + 10.0
    ny = pd.y0 + (56.0 if (has_power or any(p_.side == "top" for p_ in d.ports)) else 30.0)
    p.text(nx, ny, d.name, 10.6)
    if d.brand:
        _logo(p, d.brand, nx - 2, ny + 6.0, 62.0)
    # питание: выводы в левом верхнем углу, провода — стрелками слева
    for i, pw in enumerate(d.power):
        x = pd.x0 + 25.0 + 25.0 * i
        y = pd.y0 + 12.0
        _circle(p, x, y, 2.8)
        p.text(x, y + 11.0, pw.pin, 7.7, "center")
        if pw.link:
            ya = pd.y0 - 36.0 - 12.0 * (len(d.power) - 1 - i)
            p.vline(x, ya, y - 2.8, S.LW)
            tip = pd.x0 - 8.0
            p.hline(tip, x, ya, S.LW)
            lk, rf = split_link(pw.link, pw.ref, xr)
            S.arrow_in_from_left(p, tip, ya, lk + (f" / {rf}" if rf else ""), 7.7)
            if pw.wire and any(pw.wire):
                S.wire_mark(p, x, pd.y0 - 16.0, [w for w in pw.wire if w])
    if d.pe:
        x = pd.x0 + 18.0
        y = pd.y1 - 12.0
        _circle(p, x, y, 2.8)
        p.text(x, y - 6.0, "PE", 7.7, "center")
        p.c.saveState()
        p.c.setDash([3, 2], 0)
        p.vline(x, y + 2.8, pd.y1 + 32.0, S.LW)
        p.hline(x - 25.0, x, pd.y1 + 32.0, S.LW)
        p.vline(x - 25.0, pd.y1 + 14.0, pd.y1 + 32.0, S.LW)
        p.c.restoreState()
        S.wire_mark(p, x, pd.y1 + 22.0, ["GNYE", "1,5"])
        _ground(p, x - 25.0, pd.y1 + 14.0)
    # порты
    for name, (x, y, side, port) in pd.ports.items():
        if port.kind == "rj45":
            _rj45_port(p, x, y, flip=(side != "top"))
            p.text(x, y + (25.0 if side == "top" else -21.0), port.name, 7.7, "center")
        else:
            iy = y + 8.0 if side == "top" else y - 30.0
            _small_port(p, x, iy, port.kind)
            _circle(p, x, y, 2.3)
            lab = port.name
            p.text(x + (4.0 if side == "top" else 4.0), y + (-5.0 if side == "top" else 9.0),
                   lab, 5.5)
    # модули ПЛК справа (узкие вертикальные прямоугольники)
    if d.modules:
        mx = pd.x1 - 26.0 * len(d.modules) - 4.0
        for i, mtxt in enumerate(d.modules):
            parts = mtxt.split()
            tag = parts[0] if parts else ""
            typ = parts[1] if len(parts) > 1 else ""
            ref = " ".join(parts[2:]) if len(parts) > 2 else ""
            x0 = mx + 26.0 * i
            p.rect(x0, pd.y0 + 3.0, x0 + 22.0, pd.y1, 1.13)
            p.text(x0 + 11.0, pd.y0 - 14.0, f"-{tag.lstrip('-')}", 10.6, "center")
            if ref:
                p.text(x0 + 11.0, pd.y0 - 3.0, ref, 7.7, "center")
            p.text(x0 + 15.0, pd.y1 - 12.0, typ, 10.6, rotate=90)


def _ground(p: Pen, x, y):
    """Заземление -XPE: кружок на пунктирной шине и знак земли."""
    _circle(p, x, y, 2.8)
    p.text(x, y - 6.0, "-XPE", 7.7, "center")
    p.line(x + 2.0, y + 2.0, x + 9.0, y + 9.0, S.LW)
    p.c.saveState()
    p.c.setLineWidth(S.LW)
    p.c.circle(x + 12.0, PAGE_H - (y + 12.0), 5.5, stroke=1, fill=0)
    p.c.restoreState()
    for i, w in enumerate((4.0, 2.8, 1.4)):
        p.hline(x + 12.0 - w, x + 12.0 + w, y + 11.0 + 2.0 * i, S.LW)


def _cable_label(p: Pen, x, y, l: NetLink):
    """Подпись кабеля слева от линии и поперечная черта (как в образце)."""
    if not (l.cable or l.cable_type or l.length):
        return
    tag = f"-{l.cable.lstrip('-')}" if l.cable else ""
    p.text(x - 4.0, y - 22.0, tag, 10.6, "right")
    p.text(x - 4.0, y - 11.0, l.cable_type, 7.7, "right", max_width=50.0)
    p.text(x - 4.0, y - 1.5, l.length, 7.7, "right")
    p.hline(x - 25.0, x + 25.0, y + 3.5, 0.71)
    if l.note:
        lines = [w for part in l.note.split("\n") for w in wrap(part, 48.0, 6.5)][:3]
        for i, ln in enumerate(lines):
            p.text(x - 4.0, y + 12.0 + 8.0 * i, ln, 6.5, "right", max_width=48.0)


def _socket(p: Pen, x, y, name: str, kind: str, note: str = ""):
    """Панельный разъём на шкафу: пунктирная рамка, гнездо, подпись повёрнута."""
    _dashed_rect(p, x - 17.8, y - 20.0, x + 14.2, y + 18.0)
    # гнездо: полуокружность и штекер
    p.c.saveState()
    p.c.setLineWidth(S.LW)
    p.c.arc(x - 5.0, PAGE_H - (y - 2.0) - 5.0, x + 5.0, PAGE_H - (y - 2.0) + 5.0, 0, 180)
    p.c.restoreState()
    p.rect(x - 2.8, y - 1.0, x + 2.8, y + 11.0, stroke=False, fill=True)
    p.text(x - 21.0, y + 18.0, f"-{name.lstrip('-')}", 10.6, rotate=90)
    p.text(x - 8.0, y + 12.0, kind, 7.7, rotate=90)
    if note:
        p.text(x + 23.0, y + 18.0, note, 7.7, rotate=90)


def _links(p: Pen, links: list[NetLink], by_tag: dict, xr: XRef):
    lanes = {"mid": 548.0}
    lane_used = {"mid": 0, "low": 0, "over": 0}
    zones: dict[str, list[float]] = {}
    sockets: list = []
    ext_used = [0]
    for l in links:
        ta, pa = split_end(l.a)
        dev = by_tag.get(ta)
        if not dev:
            continue
        port = dev.ports.get(pa.upper())
        if not port:
            continue
        x, y, side, _ = port
        tb, pb = split_end(l.b)
        other = by_tag.get(tb) if tb else None
        if other and other.ports.get(pb.upper()):
            x2, y2, side2, _ = other.ports[pb.upper()]
            # маршрут: от порта наружу до дорожки, по горизонтали, к второму порту
            if side == "top" and side2 == "top" and dev.d.row == other.d.row:
                # оба порта сверху, один ряд — над устройствами
                ly = min(dev.y0, other.y0) - 22.0 - 12.0 * lane_used["over"]
                lane_used["over"] += 1
            elif side == "bottom" and side2 == "bottom":
                ly = min(max(dev.y1, other.y1) + 30.0 + 12.0 * lane_used["low"], 800.0)
                lane_used["low"] += 1
            else:
                ly = lanes["mid"] + 12.0 * lane_used["mid"]
                lane_used["mid"] += 1
            ya = y + (-16.0 if side == "top" else 17.6)
            yb = y2 + (-16.0 if side2 == "top" else 17.6)
            p.vline(x, min(ya, ly), max(ya, ly), LW_NET)
            p.hline(min(x, x2), max(x, x2), ly, LW_NET)
            p.vline(x2, min(yb, ly), max(yb, ly), LW_NET)
            _cable_label(p, x, (ya + ly) / 2 + 10.0 if side == "bottom" else ly - 20.0, l)
            continue
        # наружу: вверх к разъёму на шкафу и дальше в зону
        top_end = SOCKET_Y + 11.0 if l.socket else ZONE_Y1 - 30.0
        if side != "top":
            # порт снизу: вниз под ряд, вправо к свободной вертикали, вверх к разъёму
            ly = min(dev.y1 + 25.0 + 12.0 * lane_used["low"], 800.0)
            lane_used["low"] += 1
            xe = X_EXT - 14.0 * ext_used[0]
            ext_used[0] += 1
            p.vline(x, y + 17.6, ly, LW_NET)
            p.hline(x, xe, ly, LW_NET)
            p.vline(xe, top_end, ly, LW_NET)
            x = xe
        else:
            p.vline(x, top_end, y - 15.6 + 4.0, LW_NET)
        _cable_label(p, x, 348.0, l)
        if l.socket:
            sockets.append((x, l.socket, l.socket_kind or "RJ45",
                            "" if (l.zone or l.target or l.remote) else "Панельный разъем"))
        if l.zone:
            zones.setdefault(l.zone, []).append(x)
        if l.target or l.remote or l.remote_cable:
            y_top = 152.0 if not l.target else 120.0 + 9.2 * max(0, len((l.target_title or "").split("\n")) - 1)
            p.vline(x, y_top, SOCKET_Y - 20.0, LW_NET)
            if l.remote_cable or l.remote_cable_type:
                p.text(x - 4.0, 248.0, f"-{l.remote_cable.lstrip('-')}", 10.6, rotate=90)
                p.text(x + 10.0, 248.0, l.remote_cable_type, 7.7, rotate=90)
            if l.target:
                _target(p, x, l)
            else:
                S._tri(p, [(x - 2.8, 152.0 + 7.8), (x + 2.8, 152.0 + 7.8), (x, 152.0)])
                lk, rf = split_link(l.remote, l.remote_ref, xr)
                p.text(x - 4.0, 145.0, lk, 7.7, rotate=90)
                if rf:
                    p.text(x + 5.0, 145.0, rf, 7.7, rotate=90)
    # панельные разъёмы: пояснение «Панельный разъем» — только если справа есть место
    xs_all = sorted(x for x, *_ in sockets)
    for x, name, kind, note in sockets:
        right = [o for o in xs_all if o > x + 0.1]
        if note and right and right[0] - x < 62.0:
            note = ""
        _socket(p, x, SOCKET_Y, name, kind, note)
    # зоны: пунктирная рамка вокруг удалённых концов, соседние не перекрываются
    order = sorted(zones.items(), key=lambda kv: min(kv[1]))
    bounds = []
    for i, (zone, xs) in enumerate(order):
        x0, x1 = min(xs) - 45.0, max(xs) + 30.0
        if bounds:
            x0 = max(x0, bounds[-1][2] + 8.0)
        if i + 1 < len(order):
            x1 = min(x1, min(order[i + 1][1]) - 45.0 - 4.0)
        bounds.append((zone, x0, x1))
    for zone, x0, x1 in bounds:
        _dash_dot_rect(p, x0, ZONE_Y0, x1, ZONE_Y1)
        p.text(x0 + 2.0, ZONE_Y0 - 6.0, zone, 10.6)


def _target(p: Pen, x, l: NetLink):
    """Удалённое устройство (принтер, сервер, сканер): пунктирная рамка с портом."""
    lines = l.target_title.split("\n") if l.target_title else []
    dy = 9.2 * max(0, len(lines) - 1)
    _dashed_rect(p, x - 20.0, 106.0 + dy, x + 20.0, 132.0 + dy)
    _circle(p, x, 116.0 + dy, 2.8)
    p.rect(x - 2.2, 118.8 + dy, x + 2.2, 124.0 + dy, stroke=False, fill=True)
    p.text(x + 6.0, 119.0 + dy, l.target_port or "P1", 7.7)
    top = 99.0
    p.text(x, top - 11.0, f"-{l.target.lstrip('-')}", 10.6, "center")
    for i, ln in enumerate(lines):
        p.text(x, top + 9.2 * i, ln, 7.7, "center")
