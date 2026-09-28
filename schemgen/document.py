"""Сборка PDF из модели."""
from __future__ import annotations

from .frame import draw_frame
from .model import Document
from .pen import Pen
from .sheets.spec import spec_pages
from .sheets.terminals import terminal_pages
from .sheets.title import title_page


def render_pdf(doc: Document, path: str) -> int:
    """Рисует комплект в PDF. Возвращает число листов."""
    pr = doc.project
    pen = Pen(path)
    total = 0

    # Документ В4: титул + спецификация + клеммный план
    code = f"{pr.code}.{pr.spec_doc_suffix}" if pr.spec_doc_suffix else pr.code
    pages = [title_page(pr)] + spec_pages(doc.spec)
    if doc.terminals:
        pages += terminal_pages(doc.terminals)
    for i, draw in enumerate(pages, 1):
        draw_frame(pen, pr, code, i, len(pages), pr.spec_doc_name, first=(i == 1))
        draw(pen)
        pen.new_page()
    total += len(pages)

    pen.c.setTitle(f"{code} {pr.spec_doc_name}")
    pen.c.setAuthor(pr.contractor)
    pen.save()
    return total
