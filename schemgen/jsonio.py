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
    }


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
    return Document(project, spec, terms, plc)


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
