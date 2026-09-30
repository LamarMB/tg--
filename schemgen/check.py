"""Автопроверка проекта после разбора текста — как проектировщик сверяет чертёж.

Находит то, что модель чаще всего путает:
  • стрелка «куда/откуда» ведёт на устройство, которого нет ни на одном листе;
  • устройство со схемы отсутствует в спецификации;
  • два вывода одного устройства идут в одну и ту же точку (перепутаны пары +/-);
  • устройство нарисовано дважды (в сети — и как устройство, и как «цель» кабеля);
  • модуль ПЛК без каналов, ветвь 230 В без нагрузки и т.п.

Результат — список Issue(раздел, ключ для метки, текст). Ассистент отдаёт его модели
на исправление, оставшееся — ставит оранжевыми метками на подтверждение.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Issue:
    section: str          # раздел проекта, где исправлять (mains, plc, spec …)
    key: str              # обозначение для метки на листе (-H1, -GB1 …)
    text: str             # что не так (для пользователя)
    fix: str = ""         # как исправить (подсказка модели)

    def __str__(self) -> str:
        return self.text


def _u(s) -> str:
    return str(s or "").strip().lstrip("-").upper()


def _dev(link) -> str:
    """«-UPS:Battery» → «UPS»; «+1KK1-XETH1:RJ45» → «» (во внешней зоне — не проверяем)."""
    s = str(link or "").strip()
    if not s or s.startswith("+") or not s.startswith("-"):
        return ""
    return _u(s.split(":", 1)[0].split("/", 1)[0].strip())


_RANGE = re.compile(r"^(.*?)(\d+)\s*(?:\.\.\.|…|-|–)\s*-?\1(\d+)$")


def expand(designation: str) -> set[str]:
    """«K1...K4; 1XT1…1XT3, SB1» → {K1, K2, K3, K4, 1XT1, 1XT2, 1XT3, SB1}."""
    out: set[str] = set()
    for part in re.split(r"[;,]\s*|\s+", str(designation or "")):
        p = _u(part)
        if not p:
            continue
        m = _RANGE.match(p)
        if m and int(m.group(3)) - int(m.group(2)) < 200:
            for i in range(int(m.group(2)), int(m.group(3)) + 1):
                out.add(f"{m.group(1)}{i}")
        else:
            out.add(p)
    return out


BUILTIN = {"XPE", "XSH", "PE"}          # шины PE и экранов есть в каждом шкафу


def _drawn(d: dict, outside: set | None = None) -> dict[str, str]:
    """Обозначения, нарисованные на листах: {обозначение: раздел}. В outside
    складываются те, что стоят вне шкафа (в спецификацию шкафа не обязаны входить)."""
    got: dict[str, str] = {}
    outside = outside if outside is not None else set()

    def add(tag, sec, out=False):
        t = _u(tag)
        if t and t not in ("ШИНА", "N", "PE"):
            got.setdefault(t, sec)
            if out:
                outside.add(t)

    m = d.get("mains") or {}
    for k in ("input_block", "qs", "n_bus"):
        add(m.get(k), "mains")
    for b in m.get("branches") or []:
        for k in ("tag", "load_tag", "load_tag2"):
            add(b.get(k), "mains")
    for dv in m.get("devices") or []:
        add(dv.get("tag"), "mains")
    for f in d.get("feeders") or []:
        add(f.get("tag"), "feeders")
        add(f.get("terminal"), "feeders")
        for s in f.get("sockets") or []:
            add(s, "feeders", bool(f.get("zone")))
    pw = d.get("power24") or {}
    for g in pw.get("groups") or []:
        for b in g.get("breakers") or []:
            add(b.get("tag"), "power24")
    for mb in pw.get("minus") or []:
        add(mb.get("name"), "power24")
    for blk in pw.get("inputs") or []:
        add(blk.get("name"), "power24")
    for mod in d.get("plc") or []:
        add(mod.get("tag"), "plc")
        for c in mod.get("channels") or []:
            add(c.get("device"), "plc")
    net = d.get("network") or {}
    for dv in net.get("devices") or []:
        add(dv.get("tag"), "network")
    for ln in net.get("links") or []:
        add(ln.get("socket"), "network")
        add(ln.get("target"), "network", True)
    for area in d.get("fields") or []:
        for g in area.get("groups") or []:
            add(g.get("block"), "fields")
            add(g.get("remote_device"), "fields", True)
            for t in g.get("terms") or []:
                add(t.get("device"), "fields", True)
    col = d.get("column") or {}
    if col.get("lamps"):
        add(col.get("tag"), "column")
        for lp in col.get("lamps") or []:
            add(lp.get("relay"), "column")
            add(lp.get("via"), "column")
    for blk in d.get("terminals") or []:
        add(blk.get("name"), "terminals")
    return got


def _links(d: dict):
    """(раздел, чей вывод, ссылка) — все стрелки «куда/откуда» проекта."""
    m = d.get("mains") or {}
    for o in m.get("qs_outputs") or []:
        yield "mains", m.get("qs") or "QS", o.get("link")
    for t in m.get("n_taps") or []:
        yield "mains", m.get("n_bus") or "XN", t.get("link")
    for b in m.get("branches") or []:
        yield "mains", b.get("tag") or b.get("load_tag"), b.get("link")
        yield "mains", b.get("load_tag") or b.get("tag"), b.get("n_link")
    for dv in m.get("devices") or []:
        for p in dv.get("pins") or []:
            yield "mains", dv.get("tag"), p.get("link")
    for f in d.get("feeders") or []:
        yield "feeders", f.get("tag"), f.get("source")
        yield "feeders", f.get("tag"), f.get("n_source")
    pw = d.get("power24") or {}
    for g in pw.get("groups") or []:
        yield "power24", "", g.get("source")
        for b in g.get("breakers") or []:
            for t in b.get("targets") or []:
                yield "power24", b.get("tag"), t.get("link")
    for mb in pw.get("minus") or []:
        yield "power24", mb.get("name"), mb.get("source")
        for t in mb.get("taps") or []:
            yield "power24", mb.get("name"), t.get("link")
    for mod in d.get("plc") or []:
        yield "plc", mod.get("tag"), mod.get("feed")
        yield "plc", mod.get("tag"), mod.get("common")
        for c in mod.get("channels") or []:
            yield "plc", mod.get("tag"), c.get("link")
    net = d.get("network") or {}
    for ln in net.get("links") or []:
        yield "network", ln.get("cable"), ln.get("a")
        yield "network", ln.get("cable"), ln.get("b")
    for dv in net.get("devices") or []:
        for p in dv.get("power") or []:
            yield "network", dv.get("tag"), p.get("link")
    for area in d.get("fields") or []:
        for g in area.get("groups") or []:
            for t in g.get("terms") or []:
                yield "fields", g.get("block"), t.get("link")
    col = d.get("column") or {}
    if col.get("lamps"):
        yield "column", col.get("tag"), col.get("common_link")
        yield "column", col.get("tag"), col.get("feed_next")


# стрелки, которые по смыслу ведут за пределы проекта шкафа
_EXTERNAL = re.compile(r"^(ЩР|ШР|ВРУ|ЩС|ГРЩ|UPS:OUTPUT|OMS|СЕРВЕР)", re.I)


def check(d: dict) -> list[Issue]:
    issues: list[Issue] = []
    outside: set = set()
    drawn = _drawn(d, outside)
    for b in BUILTIN:
        drawn.setdefault(b, "")
    spec_tags: set[str] = set()
    for r in d.get("spec") or []:
        spec_tags |= expand(r.get("designation"))

    # 1. стрелки в никуда
    seen = set()
    for sec, owner, link in _links(d):
        dev = _dev(link)
        if not dev or dev in drawn or _EXTERNAL.match(dev):
            continue
        if (sec, dev) in seen:
            continue
        seen.add((sec, dev))
        who = f"от -{_u(owner)} " if owner else ""
        issues.append(Issue(sec, f"-{_u(owner)}" if owner else f"-{dev}",
                            f"Стрелка {who}ведёт на «{link}», но устройства -{dev} "
                            "нет ни на одном листе.",
                            "Нарисуй устройство в подходящем разделе (лампу/блок — "
                            "устройством ввода 230 В с выводами, клеммник — в terminals и "
                            "там, где он на схеме) или исправь ссылку."))

    # 2. устройства схемы — в спецификации
    if d.get("spec"):
        missing = sorted(t for t, sec in drawn.items()
                         if sec and t not in spec_tags and t not in outside)
        if missing:
            issues.append(Issue("spec", "", "Нет в спецификации (есть на схемах): "
                                + ", ".join(missing) + ".",
                                "Добавь строки спецификации с наименованием, типом и "
                                "количеством (артикул — только если он известен)."))

    # 3. два вывода устройства в одну точку
    def same_target(sec, tag, pins):
        by: dict[str, list[str]] = {}
        for name, link in pins:
            if link and str(link).startswith("-"):
                by.setdefault(_u(link), []).append(str(name))
        for link, names in by.items():
            if len(names) > 1:
                issues.append(Issue(sec, f"-{_u(tag)}",
                                    f"У -{_u(tag)} выводы {', '.join(names)} идут в одну точку "
                                    f"«-{link}».",
                                    "У каждого вывода своя точка подключения (L — к фазе, "
                                    "N — к нейтрали, PE — к -XPE, + к +, − к −)."))
    for dv in (d.get("mains") or {}).get("devices") or []:
        same_target("mains", dv.get("tag"), [(p.get("name"), p.get("link"))
                                              for p in dv.get("pins") or []])
    for dv in (d.get("network") or {}).get("devices") or []:
        same_target("network", dv.get("tag"), [(p.get("pin"), p.get("link"))
                                                for p in dv.get("power") or []])

    # 4. нарисовано дважды
    net = d.get("network") or {}
    net_devs = {_u(x.get("tag")) for x in net.get("devices") or []}
    for ln in net.get("links") or []:
        t = _u(ln.get("target"))
        if t and t in net_devs:
            issues.append(Issue("network", f"-{t}",
                                f"-{t} нарисован дважды: как устройство и как внешняя цель "
                                f"кабеля {ln.get('cable')}.",
                                "Подключи кабель к порту устройства (b), target оставь "
                                "пустым."))
    ports = {}
    for dv in net.get("devices") or []:
        for pt in dv.get("ports") or []:
            ports[(_u(dv.get("tag")), str(pt.get("name") or "").strip().upper())] = \
                str(pt.get("kind") or "").lower()
    for ln in net.get("links") or []:
        ct = str(ln.get("cable_type") or "").upper()
        want = "usb" if "USB" in ct else "hdmi" if "HDMI" in ct else \
            "rj45" if any(x in ct for x in ("CAT", "FTP", "UTP", "ETHERNET")) else ""
        for end in (ln.get("a"), ln.get("b")):
            if not end or ":" not in str(end):
                continue
            dev, pin = str(end).split(":", 1)
            kind = ports.get((_u(dev), pin.strip().upper()), "")
            base = "usb" if kind.startswith("usb") else kind
            if want and base and base != "lan" and want != base and \
                    not (want == "rj45" and base == "lan"):
                issues.append(Issue("network", f"-{_u(dev)}",
                                    f"Кабель {ln.get('cable')} ({ln.get('cable_type')}) "
                                    f"подключён к порту {end} типа {kind}.",
                                    "Тип кабеля и порта должны совпадать (Ethernet — RJ45, "
                                    "USB — USB, HDMI — HDMI): поправь порт или кабель."))
    mains_devs = [_u(x.get("tag")) for x in (d.get("mains") or {}).get("devices") or []]
    for t in {x for x in mains_devs if mains_devs.count(x) > 1}:
        issues.append(Issue("mains", f"-{t}", f"-{t} в разделе ввода 230 В описан дважды."))

    # 5. пустые модули ПЛК
    for mod in d.get("plc") or []:
        if not mod.get("channels"):
            issues.append(Issue("plc", f"-{_u(mod.get('tag'))}",
                                f"Модуль -{_u(mod.get('tag'))} без каналов."))
    return issues


def report(issues: list[Issue]) -> str:
    """Список для модели: что не так и как исправить."""
    return "\n".join(f"- [{i.section}] {i.text} {i.fix}".rstrip() for i in issues)
