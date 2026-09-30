"""Картинки листов для проверки правок: что поменялось между двумя версиями."""
from __future__ import annotations

import hashlib
import io
import tempfile
import threading
from pathlib import Path

from .document import render_pdf

_PDFIUM_LOCK = threading.Lock()      # pypdfium2 не потокобезопасен
MAX_FULL = 4                          # столько листов шлём картинками целиком


def _pages(doc, scale: float) -> list:
    import pypdfium2 as pdfium
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.pdf"
        render_pdf(doc, str(p))
        with _PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(str(p))
            try:
                return [pdf[i].render(scale=scale).to_pil().convert("RGB")
                        for i in range(len(pdf))]
            finally:
                pdf.close()


def _key(img) -> str:
    """Отпечаток листа без основной надписи и графы 26 (в них шифр, № листа):
    смена шифра не должна «менять» все листы."""
    from .pen import PAGE_H, PAGE_W
    kx, ky = img.width / PAGE_W, img.height / PAGE_H
    img = img.copy()
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.rectangle([652 * kx, 780 * ky, img.width, img.height], fill="white")   # осн. надпись
    d.rectangle([0, 0, 260 * kx, 58 * ky], fill="white")                    # графа 26
    small = img.resize((img.width // 4, img.height // 4)).convert("L")
    return hashlib.md5(small.tobytes()).hexdigest()


def changed_pages(old_doc, new_doc, scale: float = 1.4) -> list:
    """Листы новой версии, которых нет в старой (новые или изменённые).
    Если у листа есть «пара» в старой версии (тот же номер) — изменённые места
    обводятся красным."""
    new = _pages(new_doc, scale)
    if old_doc is None or not (old_doc.spec or old_doc.terminals or old_doc.plc
                               or old_doc.power24 or old_doc.feeders or old_doc.mains):
        return new
    old = _pages(old_doc, scale)
    old_keys = {_key(im) for im in old}
    out = []
    for i, im in enumerate(new):
        if _key(im) in old_keys:
            continue
        if i < len(old) and old[i].size == im.size:
            im = _highlight(old[i], im)
        out.append(im)
    return out


def _highlight(old, new, cell: int = 24):
    """Красные рамки вокруг областей, где листы отличаются."""
    from PIL import ImageChops, ImageDraw
    from .pen import PAGE_H, PAGE_W
    diff = ImageChops.difference(old.convert("L"), new.convert("L"))
    kx, ky = new.width / PAGE_W, new.height / PAGE_H
    d0 = ImageDraw.Draw(diff)       # основную надпись и графу 26 не подсвечиваем
    d0.rectangle([652 * kx, 780 * ky, new.width, new.height], fill=0)
    d0.rectangle([0, 0, 260 * kx, 58 * ky], fill=0)
    small = diff.point(lambda v: 255 if v > 40 else 0).resize(
        (max(1, new.width // cell), max(1, new.height // cell)))
    w, h = small.size
    px = small.load()
    hot = {(x, y) for y in range(h) for x in range(w) if px[x, y] > 0}
    if not hot:
        return new
    # объединяем соседние клетки в прямоугольники
    seen, boxes = set(), []
    for start in hot:
        if start in seen:
            continue
        stack, x0, y0, x1, y1 = [start], start[0], start[1], start[0], start[1]
        seen.add(start)
        while stack:
            x, y = stack.pop()
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    n = (x + dx, y + dy)
                    if n in hot and n not in seen:
                        seen.add(n)
                        stack.append(n)
        boxes.append((x0, y0, x1, y1))
    out = new.copy()
    dr = ImageDraw.Draw(out)
    for x0, y0, x1, y1 in boxes:
        dr.rectangle([x0 * cell - 6, y0 * cell - 6, (x1 + 1) * cell + 6, (y1 + 1) * cell + 6],
                     outline=(230, 0, 0), width=4)
    return out


def contact_sheet(images, cols: int = 3, width: int = 2400):
    """Обзорная картинка: листы мелко сеткой."""
    from PIL import Image
    w = width // cols
    thumbs = [im.resize((w, int(im.height * w / im.width))) for im in images]
    h = max(t.height for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), "white")
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * w, (i // cols) * h))
    return sheet


def to_png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def to_jpeg(img, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ------------------------------------------------------------ метки черновика
def _k(v) -> str:
    return str(v or "").strip()


def _by(items, key):
    return {key(x): x for x in items or [] if key(x)}


def changed_keys(old: dict, new: dict) -> list[str]:
    """Что поменялось между двумя версиями проекта (dict) — обозначения для синих
    меток в PDF: модули и выводы ПЛК, клеммники, автоматы, линии, устройства,
    строки спецификации. Для нового проекта — пусто (менять нечего отмечать)."""
    old, new = old or {}, new or {}
    if not any(old.get(k) for k in ("spec", "terminals", "plc", "power24", "feeders", "mains")):
        return []
    out: list[str] = []

    # ПЛК: изменённые выводы; новый модуль — целиком
    om = _by(old.get("plc"), lambda m: _k(m.get("key") or m.get("tag")))
    for key, m in _by(new.get("plc"), lambda m: _k(m.get("key") or m.get("tag"))).items():
        tag = _k(m.get("tag"))
        o = om.get(key)
        if o is None:
            out.append("-" + tag)
            continue
        if o == m:
            continue
        oc = _by(o.get("channels"), lambda c: _k(c.get("pin")))
        chans = [c for c in m.get("channels") or [] if oc.get(_k(c.get("pin"))) != c]
        if chans:
            out += [f"-{tag}:{_k(c.get('pin'))}" for c in chans]
        else:
            out.append("-" + tag)
    # клеммники
    ot = _by(old.get("terminals"), lambda b: _k(b.get("name")))
    out += [n for n, b in _by(new.get("terminals"), lambda b: _k(b.get("name"))).items()
            if ot.get(n) != b]
    # питание 24 В: автоматы и шины минусов
    op, np_ = old.get("power24") or {}, new.get("power24") or {}
    obr = {_k(b.get("tag")): b for g in op.get("groups") or [] for b in g.get("breakers") or []}
    for g in np_.get("groups") or []:
        out += [_k(b.get("tag")) for b in g.get("breakers") or [] if obr.get(_k(b.get("tag"))) != b]
    omn = _by(op.get("minus"), lambda m: _k(m.get("name")))
    out += [n for n, m in _by(np_.get("minus"), lambda m: _k(m.get("name"))).items()
            if omn.get(n) != m]
    # линии 230 В
    of = _by(old.get("feeders"), lambda f: _k(f.get("tag")))
    out += [t for t, f in _by(new.get("feeders"), lambda f: _k(f.get("tag"))).items()
            if of.get(t) != f]
    # ввод 230 В
    om2, nm = old.get("mains") or {}, new.get("mains") or {}
    obr2 = _by(om2.get("branches"), lambda b: _k(b.get("tag")) or _k(b.get("load_tag")))
    for b in nm.get("branches") or []:
        k = _k(b.get("tag")) or _k(b.get("load_tag"))
        if obr2.get(k) != b:
            out += [x for x in (_k(b.get("tag")), _k(b.get("load_tag"))) if x]
    od = _by(om2.get("devices"), lambda d: _k(d.get("tag")))
    out += [t for t, d in _by(nm.get("devices"), lambda d: _k(d.get("tag"))).items()
            if od.get(t) != d]
    simple = ("input_block", "input_cable", "qs", "qs_rating", "qs_poles", "qs_outputs",
              "n_bus", "n_taps")
    if nm and any(om2.get(k) != nm.get(k) for k in simple):
        out.append(_k(nm.get("qs")) or "QS1")
    # сеть: устройства и кабели
    on, nn = old.get("network") or {}, new.get("network") or {}
    odv = _by(on.get("devices"), lambda d: _k(d.get("tag")))
    out += [t for t, d in _by(nn.get("devices"), lambda d: _k(d.get("tag"))).items()
            if odv.get(t) != d]
    olk = _by(on.get("links"), lambda l: _k(l.get("cable")))
    out += ["-" + c.lstrip("-") for c, l in _by(nn.get("links"), lambda l: _k(l.get("cable"))).items()
            if olk.get(c) != l]
    # коробки / внешние шкафы: изменённые клеммники
    ofg = {(_k(a.get("zone")), _k(g.get("block"))): g for a in old.get("fields") or []
           for g in a.get("groups") or []}
    for a in new.get("fields") or []:
        for g in a.get("groups") or []:
            if ofg.get((_k(a.get("zone")), _k(g.get("block")))) != g:
                out.append("-" + _k(g.get("block")).lstrip("-"))
    # сигнальная колонна
    if (old.get("column") or None) != (new.get("column") or None) and new.get("column"):
        out.append(_k(new["column"].get("tag")) or "-HL1")
    # спецификация: новые/изменённые строки — их обозначения
    osp = [dict(r) for r in old.get("spec") or []]
    for r in new.get("spec") or []:
        if r not in osp:
            out += [x.strip() for x in _k(r.get("designation")).split(";") if x.strip()
                    and "..." not in x]
    seen, res = set(), []
    for x in out:
        if x and x.upper() not in seen:
            seen.add(x.upper())
            res.append(x)
    return res
