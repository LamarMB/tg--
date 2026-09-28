"""Рамка листа А3 и основные надписи (ГОСТ 2.104, формы 1 и 2а).

Размеры сняты с образца (ВКС.АСПУ.2196.СС1), единицы — пункты.
"""
from __future__ import annotations

from .model import Project
from .pen import ASSETS, Pen, text_width

# Внутренняя рамка
X0, X1 = 56.7, 1176.4     # 20 мм слева, 5 мм справа
Y0, Y1 = 14.3, 827.8      # 5 мм сверху и снизу

# Основная надпись: левая граница и колонки граф «Изм/Лист/№ докум/Подп/Дата»
TB_X = 652.0
TB_COLS = [652.0, 671.8, 700.2, 765.4, 807.9, 836.2]
TB_NAME_X1 = 1034.7       # правая граница поля наименования (форма 1)

LOGO = ASSETS / "logo.png"


def draw_frame(pen: Pen, project: Project, doc_code: str, sheet: int,
               sheets_total: int, doc_name: str, first: bool) -> None:
    _outer(pen)
    _ruler(pen)
    _side_column(pen)
    _top_left_box(pen, doc_code)
    if first:
        _form1(pen, project, doc_code, sheets_total, doc_name)
    else:
        _form2a(pen, doc_code, sheet)


def _outer(p: Pen) -> None:
    # Линии по краю листа (как в образце) и внутренняя рамка
    p.line(0, 0.1, 0, 842.0)
    p.line(1190.5, 0.1, 1190.5, 842.0)
    p.hline(0, 1190.5, 842.0)
    p.hline(0, 1190.5, 0.1)
    p.rect(X0, Y0, X1, Y1)


def _ruler(p: Pen) -> None:
    """Координатная линейка 0…9 над рамкой."""
    step = (X1 - X0) / 10
    for i in range(10):
        a = X0 + i * step
        if i:
            p.vline(a, 0.1, Y0)
        p.text(a + step / 2, 12.2, str(i), 10.6, "center")


def _side_column(p: Pen) -> None:
    """Боковая графа слева (Инв. № подл., Подп. и дата ...)."""
    xa, xb, xc = 22.7, 36.9, X0
    marks = [416.8, 516.0, 586.9, 657.7, 757.0, 827.8]
    titles = ["Подп. и дата", "Инв. № дубл.", "Взам. инв. №", "Подп. и дата",
              "Инв. № подл."]
    p.vline(xa, marks[0], marks[-1])
    p.vline(xb, marks[0], marks[-1])
    for y in marks:
        p.hline(xa, xc, y)
    size = 9.2
    for (y0, y1), t in zip(zip(marks, marks[1:]), titles):
        w = text_width(t, size)
        p.text((xa + xb) / 2 + size * 0.36, (y0 + y1) / 2 + w / 2, t, size,
               rotate=90)


def _top_left_box(p: Pen, doc_code: str) -> None:
    """Графа 26: обозначение документа, повёрнутое на 180°."""
    x0, y0, x1, y1 = X0, Y0, 255.1, 54.0
    p.rect(x0, y0, x1, y1)
    size = 12.8
    p.text((x0 + x1) / 2, (y0 + y1) / 2 - size * 0.36, doc_code, size,
           "center", rotate=180, max_width=x1 - x0 - 8)


def _left_grid(p: Pen, y_top: float, rows: int, list_col_rows: int | None = None) -> None:
    """Сетка граф изменений (7/10/23/15/10 мм) из rows строк по 5 мм.

    list_col_rows: сколько верхних строк делит граница «Изм.»/«Лист»
    (в форме 1 ниже неё идут объединённые ячейки «Разраб.», «Пров.» ...)."""
    h = 14.17
    y_bottom = y_top + rows * h
    for x in TB_COLS:
        yb = y_bottom
        if x == TB_COLS[1] and list_col_rows is not None:
            yb = y_top + list_col_rows * h
        p.vline(x, y_top, yb)
    for i in range(1, rows):
        p.hline(TB_COLS[0], TB_COLS[-1], y_top + i * h)


def _form2a(p: Pen, doc_code: str, sheet: int) -> None:
    y0, y1 = 785.3, Y1
    p.hline(TB_X, X1, y0)
    _left_grid(p, y0, 3)
    labels = [("Изм.", 654.5), ("Лист", 677.9), ("№ докум.", 716.2),
              ("Подп.", 774.0), ("Дата", 813.8)]
    for t, x in labels:
        p.text(x, 822.5, t, 8.5)
    # поле обозначения
    p.text_in_box(836.2, y0, 1148.0, y1, doc_code, 17.0)
    # графа «Лист»
    p.vline(1148.0, y0, y1)
    p.hline(1148.0, X1, 805.1)
    p.text_in_box(1148.0, y0, X1, 805.1, "Лист", 10.6)
    p.text_in_box(1148.0, 805.1, X1, y1, str(sheet), 10.6)
    _below_frame(p, 891.5, 1074.8)


def _form1(p: Pen, pr: Project, doc_code: str, sheets_total: int,
           doc_name: str) -> None:
    y0 = 671.9
    h = 14.17
    rows = [y0 + i * h for i in range(12)]  # 671.9 … 827.8
    p.hline(TB_X, X1, y0)
    _left_grid(p, y0, 11, list_col_rows=5)
    # колонки «Изм»/«Лист» не делятся ниже строки подписей
    labels = [("Изм.", 650.9), ("Лист", 674.5), ("№ докум.", 708.9),
              ("Подп.", 772.6), ("Дата", 810.3)]
    for t, x in labels:
        p.text(x, 740.0, t, 10.6)
    # Строки подписей: Разраб., Пров., Т.контр., Нач.отд., Н.контр., Утв.
    people = {x.role: x for x in pr.people}
    roles = ["Разраб.", "Пров.", "Т.контр.", "Нач.отд.", "Н.контр.", "Утв."]
    for i, role in enumerate(roles):
        yb = rows[6 + i]
        p.text(654.8, yb - 3.0, role, 10.6, max_width=44)
        person = people.get(role)
        if person:
            p.text(703.0, yb - 3.0, person.name, 10.6, max_width=60)
            p.text(808.8, yb - 3.0, person.date, 10.6, max_width=26)

    # Поле обозначения документа
    p.vline(836.2, y0, Y1)
    p.hline(836.2, X1, rows[3])
    p.text_in_box(836.2, y0, X1, rows[3], doc_code, 17.0)

    # Поле наименования: линия / изделие / название документа, ниже — место
    p.vline(TB_NAME_X1, rows[3], Y1)
    p.hline(836.2, X1, rows[8])
    p.text((836.2 + TB_NAME_X1) / 2, 736.0, pr.line, 14.9, "center",
           max_width=190)
    p.text((836.2 + TB_NAME_X1) / 2, 763.5, pr.product, 10.6, "center",
           max_width=190)
    p.text((836.2 + TB_NAME_X1) / 2, 783.0, doc_name, 10.6, "center",
           max_width=190)
    p.text_in_box(836.2, rows[8], TB_NAME_X1, Y1, pr.location, 14.9)

    # Лит. / Масса / Масштаб
    xl = [TB_NAME_X1, 1048.8, 1063.0, 1077.2, 1125.3, X1]
    p.hline(TB_NAME_X1, X1, rows[4])
    p.hline(TB_NAME_X1, X1, rows[7])
    for x in xl[1:4]:
        p.vline(x, rows[4], rows[7])
    p.vline(1077.2, rows[3], rows[7])
    p.vline(1125.3, rows[3], rows[7])
    p.text_in_box(TB_NAME_X1, rows[3], 1077.2, rows[4], "Лит.", 10.6)
    p.text_in_box(1077.2, rows[3], 1125.3, rows[4], "Масса", 10.6)
    p.text_in_box(1125.3, rows[3], X1, rows[4], "Масштаб", 10.6)
    for i, ch in enumerate((pr.litera or "")[:3]):
        p.text_in_box(xl[i], rows[4], xl[i + 1], rows[7], ch, 10.6)
    p.text_in_box(1077.2, rows[4], 1125.3, rows[7], pr.mass, 10.6)
    p.text_in_box(1125.3, rows[4], X1, rows[7], pr.scale, 10.6)

    # Лист / Листов
    p.vline(1091.3, rows[7], rows[8])
    p.text(1038.9, 782.0, "Лист", 10.6)
    p.text(1071.4, 782.0, "1", 10.6)
    p.text(1095.6, 782.0, "Листов", 10.6)
    p.text(1150.6, 782.0, str(sheets_total), 10.6)

    # Логотип организации
    if LOGO.is_file():
        p.image(LOGO, 1060.0, 792.0, 1151.0, 821.0)
    _below_frame(p, 864.6, 1055.9)


def _below_frame(p: Pen, x_copy: float, x_fmt: float) -> None:
    p.text(x_copy, 839.2, "Копировал", 10.6)
    p.text(x_fmt, 839.2, "Формат А3", 10.6)
