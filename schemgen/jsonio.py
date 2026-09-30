"""Модель <-> JSON (для состояния проекта в чате и для обмена с языковой моделью)."""
from __future__ import annotations

from dataclasses import asdict

from .e3.model import PlcChannel, PlcModule
from .model import Document, Person, Project, SpecItem, TerminalBlock, TerminalRow

ELEMENTS = ["", "ттр", "перекл", "кнопка но", "кнопка нз", "катушка", "лампа",
            "общий", "питание"]


def doc_to_dict(doc: Document) -> dict:
    pr = asdict(doc.project)
    return {
        "project": pr,
        "spec": [asdict(s) for s in doc.spec],
        "terminals": [{"name": b.name, "rows": [asdict(r) for r in b.rows]}
                      for b in doc.terminals],
        "plc": [_mod_to_dict(m) for m in doc.plc],
        "power24": _p24_to_dict(doc.power24),
        "feeders": [asdict(f) for f in doc.feeders or []],
        "mains": _mains_to_dict(doc.mains),
        "frozen": _frozen_to_list(doc.frozen),
        "network": _net_to_dict(doc.network),
    }


def _net_to_dict(net):
    if not net:
        return None
    return {"devices": [{"tag": d.tag, "name": d.name, "brand": d.brand, "row": d.row,
                         "ref": d.ref, "pe": d.pe, "modules": list(d.modules),
                         "ports": [asdict(p) for p in d.ports],
                         "power": [{"pin": w.pin, "link": w.link, "ref": w.ref,
                                    "wire": _wire_obj(w.wire)} for w in d.power]}
                        for d in net.devices],
            "links": [asdict(l) for l in net.links]}


def _dict_to_net(d):
    from .e3.network import NetDevice, NetLink, NetPort, NetPower, Network
    if not d:
        return None
    net = Network()
    for x in d.get("devices") or []:
        tag = _dash(x.get("tag"))
        if not tag:
            continue
        net.devices.append(NetDevice(
            tag, _s(x.get("name")), _s(x.get("brand")).lower(),
            "bottom" if _s(x.get("row")).lower() in ("bottom", "низ", "нижний") else "top",
            _s(x.get("ref")),
            [NetPort(_s(p.get("name")), _s(p.get("kind")).lower() or "rj45",
                     "bottom" if _s(p.get("side")).lower() in ("bottom", "низ", "снизу") else "top")
             for p in x.get("ports") or [] if _s(p.get("name"))],
            [NetPower(_s(w.get("pin")), _dash(w.get("link")), _s(w.get("ref")), _wire(w.get("wire")))
             for w in x.get("power") or [] if _s(w.get("pin"))],
            bool(x.get("pe")), [_s(m) for m in x.get("modules") or [] if _s(m)]))
    fields = NetLink.__dataclass_fields__
    for l in d.get("links") or []:
        net.links.append(NetLink(**{k: _s(v) for k, v in l.items() if k in fields}))
    return net if net else None


def _frozen_to_list(fr):
    from .template import to_list
    return to_list(fr)


def _mains_to_dict(m) -> dict | None:
    """Ввод 230 В. Устройства — одним списком (и питаемые от ветви: ветвь находит своё
    устройство по load_tag)."""
    if not m:
        return None

    def dev(d):
        return {"tag": d.tag, "title": d.title, "param": d.param,
                "pins": [{"name": p.name, "top": p.top, "link": p.link, "ref": p.ref,
                          "wire": _wire_obj(p.wire)} for p in d.pins]}
    devs = [dev(b.device) for b in m.branches if b.device] + [dev(d) for d in m.devices]
    return {
        "input_block": m.input_block, "input_labels": list(m.input_labels),
        "input_from": m.input_from, "input_cable": m.input_cable,
        "input_cable_type": m.input_cable_type,
        "qs": m.qs, "qs_rating": m.qs_rating, "qs_poles": m.qs_poles,
        "qs_outputs": [{"pole": o.pole, "link": o.link, "ref": o.ref,
                        "wire": _wire_obj(o.wire)} for o in m.qs_outputs],
        "n_bus": m.n_bus,
        "n_taps": [{"clamp": t.clamp, "link": t.link, "ref": t.ref, "wire": _wire_obj(t.wire)}
                   for t in m.n_taps],
        "branches": [{"tag": b.tag, "rating": b.rating, "wire": _wire_obj(b.wire),
                      "load": b.load,
                      "load_tag": b.load_tag or (b.device.tag if b.device else ""),
                      "load_param": b.load_param, "load_tag2": b.load_tag2,
                      "load_param2": b.load_param2, "n_link": b.n_link, "link": b.link,
                      "ref": b.ref} for b in m.branches],
        "devices": devs,
    }


def _dict_to_mains(d):
    from .e3.mains import Branch, Device, Mains, NTap, Pin, QsOutput
    if not d:
        return None
    m = Mains()
    m.input_block = _s(d.get("input_block")).lstrip("-") or m.input_block
    labels = [_s(x) for x in d.get("input_labels") or [] if _s(x)]
    if labels:
        m.input_labels = labels
    m.input_from = _s(d.get("input_from"))
    m.input_cable = _s(d.get("input_cable")).lstrip("-")
    m.input_cable_type = _s(d.get("input_cable_type"))
    m.qs = _s(d.get("qs")).lstrip("-") or m.qs
    m.qs_rating = _s(d.get("qs_rating"))
    try:
        m.qs_poles = max(1, min(6, int(d.get("qs_poles") or 4)))
    except (TypeError, ValueError):
        m.qs_poles = 4
    def qlink(v):
        v = _s(v)
        return v if v.lower() in ("шина", "n", "bus") else _dash(v)
    m.qs_outputs = [QsOutput(_s(o.get("pole")), qlink(o.get("link")), _s(o.get("ref")),
                             _wire(o.get("wire"))) for o in d.get("qs_outputs") or []
                    if _s(o.get("pole"))]
    m.n_bus = _s(d.get("n_bus")).lstrip("-") or m.n_bus
    m.n_taps = [NTap(_s(t.get("clamp")), _dash(t.get("link")), _s(t.get("ref")),
                     _wire(t.get("wire"))) for t in d.get("n_taps") or [] if _s(t.get("clamp"))]
    devices = {}
    for x in d.get("devices") or []:
        tag = _dash(x.get("tag"))
        if not tag:
            continue
        devices[tag.upper()] = Device(tag, _s(x.get("title")), _s(x.get("param")), [
            Pin(_s(p.get("name")), p.get("top") is not False, _dash(p.get("link")),
                _s(p.get("ref")), _wire(p.get("wire")))
            for p in x.get("pins") or [] if _s(p.get("name"))])
    for b in d.get("branches") or []:
        load = _s(b.get("load")).lower() or "стрелка"
        br = Branch(_dash(b.get("tag")), _s(b.get("rating")), _wire(b.get("wire")), load,
                    _dash(b.get("load_tag")), _s(b.get("load_param")),
                    _dash(b.get("load_tag2")), _s(b.get("load_param2")),
                    _dash(b.get("n_link")), _dash(b.get("link")), _s(b.get("ref")))
        if load.startswith("устр"):
            br.device = devices.pop(br.load_tag.upper(), None)
        m.branches.append(br)
    m.devices = list(devices.values())
    return m if m else None


def _p24_to_dict(pw) -> dict | None:
    if not pw:
        return None
    return {
        "groups": [{"name": g.name, "source": g.source, "source_ref": g.source_ref,
                    "source_wire": _wire_obj(g.source_wire),
                    "breakers": [{"tag": b.tag, "rating": b.rating, "wire": _wire_obj(b.wire),
                                  "targets": [{"link": l, "ref": r} for l, r in b.targets],
                                  "caption": b.caption} for b in g.breakers]}
                   for g in pw.groups],
        "minus": [{"name": m.name, "source": m.source, "source_ref": m.source_ref,
                   "source_wire": _wire_obj(m.source_wire),
                   "taps": [{"clamp": t.clamp, "up": t.up, "wire": _wire_obj(t.wire),
                             "link": t.link, "ref": t.ref} for t in m.taps]}
                  for m in pw.minus],
    }


def _dict_to_p24(d):
    from .e3.power24 import Breaker, BreakerGroup, MinusBus, MinusTap, Power24
    if not d:
        return None
    pw = Power24()
    for g in d.get("groups") or []:
        grp = BreakerGroup(_s(g.get("name")) or str(len(pw.groups) + 1), _dash(g.get("source")),
                           _s(g.get("source_ref")), _wire(g.get("source_wire")))
        for b in g.get("breakers") or []:
            tag = _dash(b.get("tag"))
            if not tag:
                continue
            grp.breakers.append(Breaker(tag, _s(b.get("rating")), _wire(b.get("wire")),
                                        [(_dash(t.get("link")), _s(t.get("ref")))
                                         for t in (b.get("targets") or [])[:2]],
                                        _s(b.get("caption"))))
        if grp.breakers:
            pw.groups.append(grp)
    for m in d.get("minus") or []:
        mb = MinusBus(_s(m.get("name")).lstrip("-") or "XM1", _dash(m.get("source")),
                      _s(m.get("source_ref")), _wire(m.get("source_wire")))
        for t in m.get("taps") or []:
            mb.taps.append(MinusTap(_s(t.get("clamp")), bool(t.get("up")), _wire(t.get("wire")),
                                    _dash(t.get("link")), _s(t.get("ref"))))
        if mb.taps:
            pw.minus.append(mb)
    return pw if pw else None


def _wire_obj(w: list[str]) -> dict:
    w = (list(w) + ["", "", ""])[:3]
    return {"mark": w[0], "color": w[1], "section": w[2]}


def _mod_to_dict(m: PlcModule) -> dict:
    d = asdict(m)
    d["feed_wire"], d["common_wire"] = _wire_obj(m.feed_wire), _wire_obj(m.common_wire)
    for c in d["channels"]:
        c.pop("module", None)
        c["wire"] = _wire_obj(c["wire"])
    return d


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _dash(s) -> str:
    """Ссылка на устройство — с минусом впереди (-1XT1:1), если не задано иначе."""
    s = _s(s)
    return "-" + s if s and s[0].isalnum() else s


def _wire(v) -> list[str]:
    if isinstance(v, dict):
        v = [v.get("mark"), v.get("color"), v.get("section")]
    v = list(v or [])[:3]
    return [_s(x) for x in v] + [""] * (3 - len(v))


def dict_to_doc(d: dict) -> Document:
    p = d.get("project") or {}
    fields = Project.__dataclass_fields__
    kw = {k: _s(p.get(k)) for k in fields if k != "people" and p.get(k) is not None}
    kw.setdefault("code", "")
    project = Project(**kw)
    project.people = [Person(_s(x.get("role")), _s(x.get("name")), _s(x.get("date")))
                      for x in p.get("people") or [] if x.get("role")]
    spec = [SpecItem(_s(x.get("designation")), _s(x.get("name")), _s(x.get("article")),
                     _s(x.get("qty")), _s(x.get("manufacturer")), _s(x.get("note")))
            for x in d.get("spec") or []]
    terms = []
    for b in d.get("terminals") or []:
        blk = TerminalBlock(_s(b.get("name")))
        for r in b.get("rows") or []:
            tier = r.get("tier")
            if tier in ("", None):
                tier = 0 if _s(r.get("label")) else None
            else:
                try:
                    tier = int(tier)
                except (TypeError, ValueError):
                    tier = 0
            blk.rows.append(TerminalRow(
                _s(r.get("part_no")), _s(r.get("type_no")), _s(r.get("section")),
                _s(r.get("marking")), _s(r.get("jumper")), _s(r.get("cover")),
                _s(r.get("label")), tier, _s(r.get("bridge"))))
        if blk.name:
            terms.append(blk)
    plc = []
    for m in d.get("plc") or []:
        kind = _s(m.get("kind")).lower()
        kind = "in" if kind.startswith(("in", "вх")) else "out"
        tag = _s(m.get("tag")).lstrip("-")
        mod = PlcModule(tag, _s(m.get("type")), kind, _s(m.get("ref")),
                        _dash(m.get("feed")), _wire(m.get("feed_wire")),
                        _dash(m.get("feed_next")),
                        _dash(m.get("common")), _wire(m.get("common_wire")),
                        bool(m.get("npn")), [], _s(m.get("key")) or tag)
        for c in m.get("channels") or []:
            el = _s(c.get("element")).lower()
            if el not in ELEMENTS:
                el = ""
            dev = _s(c.get("device"))
            if dev and not dev.startswith("-"):
                dev = "-" + dev
            mod.channels.append(PlcChannel(mod.key, _s(c.get("pin")), _s(c.get("desc")),
                                           _wire(c.get("wire")), el, dev, _dash(c.get("link")),
                                           _s(c.get("ref")), _s(c.get("param"))))
        if mod.tag and mod.channels:
            plc.append(mod)
    return Document(project, spec, terms, plc, _dict_to_p24(d.get("power24")),
                    _dict_to_feeders(d.get("feeders")), _dict_to_mains(d.get("mains")),
                    _frozen_from(d.get("frozen")), _dict_to_net(d.get("network")))


def _frozen_from(items):
    from .template import from_list
    return from_list(items)


def _dict_to_feeders(items):
    from .e3.power230 import Feeder
    out = []
    for f in items or []:
        tag = _dash(f.get("tag"))
        if not tag:
            continue
        kind = _s(f.get("kind")).lower()
        out.append(Feeder(
            tag, "ав" if kind in ("ав", "ab", "mcb") else "авдт", _s(f.get("rating")),
            _s(f.get("leak")), _s(f.get("section")) or "2,5", _dash(f.get("source")),
            _s(f.get("source_ref")), _dash(f.get("n_source")), _s(f.get("n_ref")),
            _s(f.get("terminal")).lstrip("-"), _s(f.get("cable")).lstrip("-"),
            _s(f.get("cable_type")), _s(f.get("cable_cores")), _s(f.get("zone")),
            [_s(x).lstrip("-") for x in f.get("sockets") or [] if _s(x)],
            _s(f.get("socket_rating")), [_s(x) for x in f.get("load_links") or []][:3],
            _s(f.get("load_ref")), _s(f.get("caption"))))
    return out


def check(doc: Document) -> list[str]:
    """Проверки, которые Excel-чтение делает при загрузке (для данных из модели)."""
    problems = []
    if not doc.project.code:
        problems.append("Не указан шифр проекта (напр. ВКС.АСПУ.2196.СС1).")
    for m in doc.plc:
        for c in m.channels:
            if c.element in ("ттр", "перекл", "кнопка но", "кнопка нз", "катушка", "лампа") \
                    and not c.device:
                problems.append(f"Модуль {m.tag}, вывод {c.pin}: у элемента нет обозначения.")
    return problems
