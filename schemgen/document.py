"""Сборка PDF из модели."""
from __future__ import annotations

from .e3 import io_sheets
from .frame import draw_frame
from .model import Document
from .pen import Pen
from .sheets.spec import spec_pages
from .sheets.terminals import terminal_pages
from .sheets.title import title_page


def _code(pr, suffix: str) -> str:
    return f"{pr.code}.{suffix}" if suffix else pr.code


def _emit(pen: Pen, pr, code: str, name: str, pages, numbers=None,
          sheets_total=None) -> int:
    numbers = numbers or list(range(1, len(pages) + 1))
    for n, draw in zip(numbers, pages):
        draw_frame(pen, pr, code, n, sheets_total or len(pages), name, first=(n == 1))
        draw(pen)
        pen.new_page()
    return len(pages)


def render_pdf(doc: Document, path: str) -> int:
    """Рисует комплект в PDF. Возвращает число листов."""
    pr = doc.project
    pen = Pen(path)
    total = 0

    # Документ В4: титул + спецификация + клеммный план
    if doc.spec or doc.terminals:
        pages = [title_page(pr)]
        if doc.spec:
            pages += spec_pages(doc.spec)
        if doc.terminals:
            pages += terminal_pages(doc.terminals)
        total += _emit(pen, pr, _code(pr, pr.spec_doc_suffix), pr.spec_doc_name, pages)

    # Документ Э3: титул + листы входов/выходов ПЛК
    if doc.plc:
        first = int(pr.e3_first_io_sheet or 2)
        io_pages = io_sheets.layout(doc.plc)
        xr = io_sheets.register(io_pages, first_sheet=first)
        pages = [title_page(pr)] + [io_sheets.painter(pg, xr) for pg in io_pages]
        numbers = [1] + [pg.number for pg in io_pages]
        total += _emit(pen, pr, _code(pr, pr.e3_doc_suffix), pr.e3_doc_name, pages,
                       numbers, sheets_total=numbers[-1])

    pen.c.setTitle(f"{pr.code} {pr.line}".strip())
    pen.c.setAuthor(pr.contractor)
    pen.save()
    return total
