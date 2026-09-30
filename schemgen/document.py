"""Сборка PDF из модели."""
from __future__ import annotations

from . import template
from .e3 import field as fieldsheets, io_sheets, mains, network, power24, power230
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
        if hasattr(draw, "pre"):                 # лист-шаблон: закрасить надписи образца
            draw.pre(pen)
            pen.templates.append((pen.page_no - 1, draw.template))
        draw_frame(pen, pr, code, n, sheets_total or len(pages), name, first=(n == 1))
        draw(pen)
        pen.new_page()
    return len(pages)


def render_pdf(doc: Document, path: str, marks=None, hits=None) -> int:
    """Рисует комплект в PDF. Возвращает число листов.

    marks — метки для черновика (см. Pen); hits — сюда складываются найденные
    метки: (страница PDF, вид, номер)."""
    pr = doc.project
    pen = Pen(path, marks)
    pen.templates = []                  # (индекс страницы, Frozen)
    frozen = template.active(doc, doc.frozen)
    total = 0

    # Документ В4: титул + спецификация + клеммный план
    if doc.spec or doc.terminals:
        pages = [title_page(pr)]
        if doc.spec:
            pages += spec_pages(doc.spec)
        if doc.terminals:
            pages += terminal_pages(doc.terminals)
        total += _emit(pen, pr, _code(pr, pr.spec_doc_suffix), pr.spec_doc_name, pages)

    # Документ Э3: титул + силовые листы + питание 24 В + листы ПЛК.
    # Сначала раскладываем все листы и регистрируем точки — потом рисуем,
    # чтобы ссылки между листами разных типов подставлялись сами.
    if doc.plc or doc.power24 or doc.feeders or doc.mains or doc.network or doc.fields \
            or frozen:
        xr = io_sheets.XRef()
        numbers, pages = [1], [title_page(pr)]
        nxt = 2

        def start(field_value) -> int:
            v = str(field_value or "").strip()
            return max(int(v), nxt) if v.isdigit() else nxt

        plan = []                                     # (номер, painter)
        m_sheets = mains.layout(doc.mains) if doc.mains else []
        if m_sheets:
            nums = mains.register(m_sheets, start(pr.e3_mains_sheet), xr)
            plan += [(n, mains.painter(sh, xr)) for n, sh in zip(nums, m_sheets)]
            nxt = nums[-1] + 1
        f_sheets = power230.layout(doc.feeders) if doc.feeders else []
        if f_sheets:
            nums = power230.register(f_sheets, start(pr.e3_feeders_sheet), xr)
            plan += [(n, power230.painter(sh, xr)) for n, sh in zip(nums, f_sheets)]
            nxt = nums[-1] + 1
        p24_sheets = power24.layout(doc.power24) if doc.power24 else []
        if p24_sheets:
            power24.register(p24_sheets, start(pr.e3_power24_sheet), xr)
            plan += [(sh.number, power24.painter(sh, xr)) for sh in p24_sheets]
            nxt = p24_sheets[-1].number + 1
        n_sheets = network.layout(doc.network) if doc.network else []
        if n_sheets:
            nums = network.register(n_sheets, start(pr.e3_network_sheet), xr)
            plan += [(n, network.painter(sh, xr)) for n, sh in zip(nums, n_sheets)]
            nxt = nums[-1] + 1
        io_pages = io_sheets.layout(doc.plc) if doc.plc else []
        if io_pages:
            io_sheets.register(io_pages, start(pr.e3_first_io_sheet), xr)
            plan += [(pg.number, io_sheets.painter(pg, xr)) for pg in io_pages]
            nxt = io_pages[-1].number + 1
        fl_sheets = fieldsheets.layout(doc.fields) if doc.fields else []
        if fl_sheets:
            nums = fieldsheets.register(fl_sheets, start(pr.e3_fields_sheet), xr)
            plan += [(n, fieldsheets.painter(sh, xr)) for n, sh in zip(nums, fl_sheets)]
        # листы-шаблоны образца заменяют сгенерированные с тем же номером
        by_num = dict(plan)
        for f in frozen:
            by_num[f.sheet] = template.painter(f)
        for n in sorted(by_num):
            numbers.append(n)
            pages.append(by_num[n])
        total += _emit(pen, pr, _code(pr, pr.e3_doc_suffix), pr.e3_doc_name, pages,
                       numbers, sheets_total=len(numbers))

    pen.c.setTitle(f"{pr.code} {pr.line}".strip())
    pen.c.setAuthor(pr.contractor)
    pen.save()
    template.underlay(path, pen.templates)
    if hits is not None:
        hits.extend(pen.hits)
    return total
