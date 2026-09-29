"""Листы-шаблоны: страницы образца, которые берутся как есть.

Часть листов образца нарисована вручную (ввод, сеть, коробки, шкаф CPW…) — их
генератор повторить 1:1 не может. Такие листы базового проекта хранятся ссылкой
на страницу PDF-образца (assets/templates) и отпечатком данных раздела, из
которого лист строится. Пока данные раздела не менялись — в PDF идёт страница
образца (основная надпись и графа 26 перерисовываются под текущий проект). Как
только раздел поменяли правкой — лист рисует генератор.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .pen import ASSETS, Pen

log = logging.getLogger(__name__)
TEMPLATES = ASSETS / "templates"


@dataclass
class Frozen:
    sheet: int                 # номер листа в Э3
    page: int                  # номер страницы в PDF-образце (с 1)
    pdf: str                   # файл в assets/templates
    keys: list[str] = field(default_factory=list)   # разделы: mains, plc:CPU.DO …
    hash: str = ""             # отпечаток данных разделов на момент заморозки


def section_data(doc_dict: dict, key: str):
    """Часть проекта (dict), от которой зависит лист."""
    if key.startswith("plc:"):
        k = key[4:].upper()
        return [m for m in doc_dict.get("plc") or []
                if str(m.get("key") or m.get("tag") or "").upper() == k]
    return doc_dict.get(key)


def fingerprint(doc_dict: dict, keys: list[str]) -> str:
    data = [section_data(doc_dict, k) for k in keys]
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def active(doc, frozen: list[Frozen]) -> list[Frozen]:
    """Шаблонные листы, данные которых не менялись (и файл образца на месте)."""
    if not frozen:
        return []
    try:
        import pikepdf  # noqa: F401  — без него подложить образец нельзя
    except ImportError:
        log.warning("pikepdf не установлен — листы-шаблоны рисует генератор")
        return []
    from .jsonio import doc_to_dict
    d = doc_to_dict(doc)
    out = []
    for f in frozen:
        if not (TEMPLATES / f.pdf).is_file():
            continue
        if not f.keys or fingerprint(d, f.keys) == f.hash:
            out.append(f)
    return out


def painter(f: Frozen):
    """Страница-шаблон: своё содержимое пустое, образец подкладывается потом.
    pre() закрашивает основную надпись и графу 26 образца — их рисует рамка."""
    def draw(p: Pen) -> None:
        pass

    def pre(p: Pen) -> None:
        p.c.saveState()
        p.c.setFillColorRGB(1, 1, 1)
        p.rect(652.0, 779.0, 1176.4, 827.8, stroke=False, fill=True)   # осн. надпись
        p.rect(56.7, 14.3, 255.6, 54.5, stroke=False, fill=True)       # графа 26
        p.rect(0, 827.9, 1190.5, 841.9, stroke=False, fill=True)       # «Копировал/Формат»
        p.c.restoreState()
    draw.pre = pre
    draw.template = f
    return draw


def underlay(pdf_path: str, placements: list[tuple[int, Frozen]]) -> None:
    """Подложить страницы образца под страницы готового PDF (индексы с 0)."""
    if not placements:
        return
    try:
        import pikepdf
    except ImportError:
        log.warning("pikepdf не установлен — листы-шаблоны останутся пустыми")
        return
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as out:
        cache = {}
        for idx, f in placements:
            src = cache.get(f.pdf)
            if src is None:
                src = cache[f.pdf] = pikepdf.open(str(TEMPLATES / f.pdf))
            page = pikepdf.Page(out.pages[idx])
            page.add_underlay(pikepdf.Page(src.pages[f.page - 1]))
        out.save(pdf_path)
        for s in cache.values():
            s.close()


def to_list(frozen) -> list[dict]:
    return [asdict(f) for f in frozen or []]


def from_list(items) -> list[Frozen]:
    out = []
    for it in items or []:
        try:
            out.append(Frozen(int(it["sheet"]), int(it["page"]), str(it["pdf"]),
                              [str(k) for k in it.get("keys") or []], str(it.get("hash") or "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out
