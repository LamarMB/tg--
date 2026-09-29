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
    if old_doc is None or not (old_doc.spec or old_doc.terminals or old_doc.plc):
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
