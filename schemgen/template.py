"""Листы-шаблоны: страницы образца, которые берутся как есть.

Часть листов образца нарисована вручную (ввод, сеть, коробки, шкаф CPW…) — их
генератор повторить 1:1 не может. Такие листы базового проекта хранятся ссылкой
на страницу PDF-образца (assets/templates) и отпечатком данных раздела, из
которого лист строится. Пока данные раздела не менялись — в PDF идёт страница
образца (основная надпись и графа 26 перерисовываются под текущий проект). Как
только раздел поменяли правкой:
  • если поменялись только надписи (номинал, обозначение, связь, маркировка провода…) —
    лист остаётся страницей образца, а изменённые надписи закрашиваются и пишутся
    заново на том же месте («заплатки»). Для этого рядом с PDF образца лежит снимок
    данных разделов и слов страниц (<pdf>.data.json, см. build_snapshot);
  • если поменялся состав (добавили/убрали автомат, клемму…) — лист рисует генератор.
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
    patches: list = field(default_factory=list, repr=False, compare=False)  # заплатки надписей


def section_data(doc_dict: dict, key: str):
    """Часть проекта (dict), от которой зависит лист."""
    if key.startswith("fields:"):
        items = doc_dict.get("fields") or []
        i = int(key[7:]) if key[7:].isdigit() else -1
        return items[i] if 0 <= i < len(items) else None
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
            f.patches = []
            out.append(f)
            continue
        try:
            patches = _patches(f, d)
        except Exception:  # noqa: BLE001 — заплатки не критичны: рисует генератор
            log.exception("заплатки листа %s", f.sheet)
            patches = None
        if patches:
            f.patches = patches
            out.append(f)
    return out


def painter(f: Frozen):
    """Страница-шаблон: своё содержимое пустое, образец подкладывается потом.
    pre() закрашивает основную надпись и графу 26 образца — их рисует рамка."""
    def draw(p: Pen) -> None:
        for pt in f.patches:
            _paint_patch(p, pt)

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


# ------------------------------------------------------------------ заплатки надписей
@dataclass
class Patch:
    box: tuple                 # (x0, top, x1, bottom) — закрасить (старая надпись)
    x: float                   # точка привязки новой надписи
    base: float                # базовая линия
    size: float
    text: str                  # новая надпись («» — только закрасить)
    align: str = "left"


def _snap_path(pdf: str) -> Path:
    return TEMPLATES / (Path(pdf).stem + ".data.json")


_SNAP_CACHE: dict = {}


def _snapshot(pdf: str) -> dict:
    path = _snap_path(pdf)
    if not path.is_file():
        return {}
    key = (str(path), path.stat().st_mtime)
    if key not in _SNAP_CACHE:
        _SNAP_CACHE.clear()
        _SNAP_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _SNAP_CACHE[key]


def build_snapshot(doc, frozen: list[Frozen]) -> list[str]:
    """Сохранить снимок данных и слов страниц образца (нужен pdfplumber — только
    при подготовке образца). Возвращает записанные файлы."""
    import pdfplumber
    from .jsonio import doc_to_dict
    d = doc_to_dict(doc)
    by_pdf: dict[str, list[Frozen]] = {}
    for f in frozen:
        by_pdf.setdefault(f.pdf, []).append(f)
    written = []
    for pdf, items in by_pdf.items():
        out = {"sheets": {}, "pages": {}}
        with pdfplumber.open(str(TEMPLATES / pdf)) as src:
            for f in items:
                out["sheets"][str(f.sheet)] = {
                    "keys": f.keys, "hash": fingerprint(d, f.keys),
                    "data": [section_data(d, k) for k in f.keys]}
                pg = src.pages[f.page - 1]
                words = pg.extract_words(extra_attrs=["size", "upright"], x_tolerance=1.5)
                out["pages"][str(f.page)] = [
                    [round(w["x0"], 2), round(w["top"], 2), round(w["x1"], 2),
                     round(w["bottom"], 2), round(w["size"], 2), w["text"]]
                    for w in words if w["upright"]]
        path = _snap_path(pdf)
        path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        written.append(str(path))
    return written


_ANCHOR_KEYS = ("tag", "name", "clamp", "pin", "cable", "mark", "block", "link", "source")


def _diff(old, new, path, parents, out) -> bool:
    """Собирает изменённые строки (старое, новое, цепочка родителей). False — если
    поменялся состав (длины списков, ключи, не строковые значения)."""
    if isinstance(old, dict) and isinstance(new, dict):
        for k in set(old) | set(new):
            if k in ("layout", "x", "xs"):
                continue
            if not _diff(old.get(k, ""), new.get(k, ""), path + [k], parents + [old], out):
                return False
        return True
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            return False
        return all(_diff(a, b, path + [i], parents, out) for i, (a, b) in enumerate(zip(old, new)))
    if old is None:
        old = ""
    if new is None:
        new = ""
    if isinstance(old, str) and isinstance(new, str):
        if old.strip() != new.strip():
            out.append((old, new, path, parents))
        return True
    return old == new


def _lines(words: list) -> list[list]:
    """Слова страницы по строкам (одинаковый верх и кегль), слева направо."""
    rows: list[list] = []
    for w in sorted(words, key=lambda w: (round(w[1]), w[0])):
        for r in rows:
            if abs(r[0][1] - w[1]) < 1.2 and abs(r[0][4] - w[4]) < 0.3:
                r.append(w)
                break
        else:
            rows.append([w])
    for r in rows:
        r.sort(key=lambda w: w[0])
    return rows


def _find(rows: list[list], phrase: str) -> list[tuple]:
    """Места фразы на странице: (x0, top, x1, bottom, size)."""
    toks = phrase.split()
    if not toks:
        return []
    out = []
    for r in rows:
        for i in range(len(r) - len(toks) + 1):
            seq = r[i:i + len(toks)]
            if [w[5] for w in seq] != toks:
                continue
            if any(b[0] - a[2] > a[4] * 0.9 for a, b in zip(seq, seq[1:])):
                continue
            out.append((seq[0][0], seq[0][1], seq[-1][2], seq[-1][3], seq[0][4]))
    return out


def _isolated(rows: list[list], toks: list[str]) -> list[tuple]:
    """Как _find, но фраза занимает свою строку целиком (соседних слов вплотную нет)."""
    out = []
    for r in rows:
        for i in range(len(r) - len(toks) + 1):
            seq = r[i:i + len(toks)]
            if [w[5] for w in seq] != toks:
                continue
            gap = seq[0][4] * 0.9
            if any(b[0] - a[2] > gap for a, b in zip(seq, seq[1:])):
                continue
            if i > 0 and seq[0][0] - r[i - 1][2] < gap:
                continue
            if i + len(toks) < len(r) and r[i + len(toks)][0] - seq[-1][2] < gap:
                continue
            out.append((seq[0][0], seq[0][1], seq[-1][2], seq[-1][3], seq[0][4]))
    return out


def _find_block(rows: list[list], phrase: str) -> list[list[tuple]]:
    """Места надписи: в одну строку или столбиком в несколько строк (подписи в рамках)."""
    toks = phrase.split()
    found = [[loc] for loc in _find(rows, phrase)]
    if found or len(toks) < 2:
        return found

    def below(loc, rest):
        res = []
        for k in range(len(rest), 0, -1):
            for nl in _isolated(rows, rest[:k]):
                dy = nl[1] - loc[1]
                if not (0.8 * loc[4] < dy < 1.7 * loc[4]) or abs(nl[4] - loc[4]) > 0.3:
                    continue
                if nl[2] < loc[0] - 2 or nl[0] > loc[2] + 2:          # не под ней
                    continue
                if k == len(rest):
                    res.append([nl])
                else:
                    res += [[nl] + tail for tail in below(nl, rest[k:])]
        return res

    for k in range(len(toks) - 1, 0, -1):
        for first in _isolated(rows, toks[:k]):
            found += [[first] + tail for tail in below(first, toks[k:])]
    return found


def _dist(a, b) -> float:
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _anchors(parents: list, rows, changed: set) -> list[tuple]:
    """Места «опорных» надписей того же объекта (обозначение, имя…), редких на листе."""
    for obj in reversed(parents):
        if not isinstance(obj, dict):
            continue
        found = []
        vals = [obj.get(k) for k in _ANCHOR_KEYS] + list(obj.values())
        for v in vals:
            if isinstance(v, dict):                      # провод: марка
                v = v.get("mark")
            if not isinstance(v, str) or not v.strip() or v in changed:
                continue
            for ln in v.split("\n"):
                locs = _find(rows, ln.strip())
                if 0 < len(locs) <= 2:
                    found += locs
        if found:
            return found
    return []


def _patches(f: Frozen, d: dict):
    """Заплатки для листа-шаблона или None (нужен генератор)."""
    snap = _snapshot(f.pdf)
    sh = (snap.get("sheets") or {}).get(str(f.sheet))
    words = (snap.get("pages") or {}).get(str(f.page))
    if not sh or words is None or sh.get("hash") != f.hash or sh.get("keys") != f.keys:
        return None
    changes: list = []
    new = [section_data(d, k) for k in f.keys]
    if not _diff(sh["data"], new, [], [], changes) or not changes:
        return None
    rows = _lines(words)
    olds = {c[0] for c in changes}
    out: list[Patch] = []
    used: set = set()
    for old, new_v, path, parents in changes:
        o_lines = [x.strip() for x in old.split("\n") if x.strip()]
        n_lines = [x.strip() for x in new_v.split("\n") if x.strip()]
        if not o_lines:
            return None                                  # надписи не было — ставить некуда
        if len(o_lines) > 1 and len(n_lines) == len(o_lines):
            pairs = list(zip(o_lines, n_lines))         # построчно
        else:
            pairs = [(" ".join(o_lines), "\n".join(n_lines))]
        anchors = None
        for ol, nl in pairs:
            blocks = [b for b in _find_block(rows, ol) if not any(l in used for l in b)]
            if not blocks and not ol.startswith("-"):    # обозначения рисуются с минусом
                blocks = [b for b in _find_block(rows, "-" + ol) if not any(l in used for l in b)]
                if nl and not nl.startswith("-"):
                    nl = "-" + nl
            if not blocks:
                return None
            if len(blocks) > 1:
                if anchors is None:
                    anchors = _anchors(parents, rows, olds)
                if not anchors:
                    return None
                def score(b):
                    return min(_dist(l, a) for l in b for a in anchors)
                blocks.sort(key=score)
                best = score(blocks[0])
                if best > 160 or score(blocks[1]) - best < 1.0:
                    return None                          # не понять, какая из одинаковых
            else:
                anchors = anchors if anchors is not None else _anchors(parents, rows, olds)
                if anchors and min(_dist(l, a) for l in blocks[0] for a in anchors) > 300:
                    return None                          # единственная, но далеко от объекта
            blk = blocks[0]
            used.update(blk)
            out += _block_patches(blk, nl, _align(blk, anchors, path, rows))
    return out


def _block_patches(blk: list[tuple], new: str, align: str) -> list[Patch]:
    from .pen import text_width, wrap
    size = blk[0][4]
    pitch = (blk[1][1] - blk[0][1]) if len(blk) > 1 else size * 1.2
    if "\n" in new:
        lines = [x.strip() for x in new.split("\n")]
    elif len(blk) > 1:
        width = max(l[2] - l[0] for l in blk) + 2.0
        lines = wrap(new, max(width, max((text_width(w, size) for w in new.split()),
                                         default=0)), size) if new else []
    else:
        lines = [new] if new else []
    out = []
    for i in range(max(len(blk), len(lines))):
        ref = blk[min(i, len(blk) - 1)]
        box = ref if i < len(blk) else (ref[0], ref[1], ref[0], ref[1])
        x = {"left": ref[0], "right": ref[2], "center": (ref[0] + ref[2]) / 2}[align]
        if i >= len(blk) and len(blk) > 1:
            x = {"left": blk[0][0], "right": blk[0][2]}.get(align, x)
        base = blk[0][3] - 0.24 * size + i * pitch
        out.append(Patch(box, x, base, size, lines[i] if i < len(lines) else "", align))
    return out


def _segments(row: list, gap_k: float = 0.9) -> list[tuple]:
    """Куски строки (слова вплотную) — (x0, top, x1, bottom, size)."""
    out, cur = [], [row[0]]
    for w in row[1:]:
        if w[0] - cur[-1][2] > cur[-1][4] * gap_k:
            out.append(cur)
            cur = [w]
        else:
            cur.append(w)
    out.append(cur)
    return [(c[0][0], c[0][1], c[-1][2], c[-1][3], c[0][4]) for c in out]


def _edge_align(lines: list[tuple]) -> str | None:
    """Как выровнены строки: по какому краю (или центру) разброс меньше всего."""
    if len(lines) < 2:
        return None
    spread = {
        "right": [l[2] for l in lines],
        "left": [l[0] for l in lines],
        "center": [(l[0] + l[2]) / 2 for l in lines],
    }
    best = min(spread, key=lambda k: max(spread[k]) - min(spread[k]))
    v = spread[best]
    return best if max(v) - min(v) < 1.5 else None


def _align(blk, anchors, path, rows=None) -> str:
    if len(blk) > 1:                                     # столбик: как выровнены строки
        return _edge_align(blk) or "left"
    loc = blk[0]
    # соседние строки того же блока надписей (сверху/снизу, внахлёст по x)
    for r in rows or []:
        dy = r[0][1] - loc[1]
        if 0.5 < abs(dy) < 1.8 * loc[4]:
            for seg in _segments(r):
                if seg[2] < loc[0] - 1 or seg[0] > loc[2] + 1:
                    continue
                al = _edge_align([loc, seg])
                if al:
                    return al
    for a in anchors or []:
        if a == loc:
            continue
        if abs(a[2] - loc[2]) < 1.5:
            return "right"
        if abs((a[0] + a[2]) / 2 - (loc[0] + loc[2]) / 2) < 1.5:
            return "center"
        if abs(a[0] - loc[0]) < 1.5:
            return "left"
    field_name = next((k for k in reversed(path) if isinstance(k, str)), "")
    if field_name in ("link", "ref", "source", "source_ref", "target", "remote_ref"):
        return "center"
    return "left"


def _paint_patch(p: Pen, pt: Patch) -> None:
    x0, top, x1, bottom = pt.box[:4]
    if x1 > x0:
        p.c.saveState()
        p.c.setFillColorRGB(1, 1, 1)
        p.rect(x0 - 0.6, top - 0.3, x1 + 0.6, bottom + 0.3, stroke=False, fill=True)
        p.c.restoreState()
    if pt.text:
        p.text(pt.x, pt.base, pt.text, pt.size, pt.align)


def to_list(frozen) -> list[dict]:
    out = []
    for f in frozen or []:
        d = asdict(f)
        d.pop("patches", None)
        out.append(d)
    return out


def from_list(items) -> list[Frozen]:
    out = []
    for it in items or []:
        try:
            out.append(Frozen(int(it["sheet"]), int(it["page"]), str(it["pdf"]),
                              [str(k) for k in it.get("keys") or []], str(it.get("hash") or "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out
