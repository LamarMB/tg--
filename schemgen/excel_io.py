"""Чтение исходных данных из Excel и создание пустого шаблона.

Структура файла (листы):
  «Проект»        — параметр / значение (шифр, заказчик, линия ...)
  «Подписи»       — роль / фамилия / дата для основной надписи
  «Спецификация»  — строки спецификации элементов
  «Клеммы»        — строки клеммного плана (клеммник указывается в каждой строке)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .model import Document, Person, Project, SpecItem, TerminalBlock, TerminalRow


class TemplateError(Exception):
    """Ошибки заполнения шаблона — показываются пользователю как есть."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


# Параметр в Excel -> (атрибут Project, обязательный, значение по умолчанию)
PROJECT_FIELDS = [
    ("Шифр", "code", True, ""),
    ("Наименование системы", "system_name", False, ""),
    ("Исполнитель", "contractor", False, ""),
    ("Заказчик", "customer", False, ""),
    ("Линия", "line", False, ""),
    ("Изделие", "product", False, ""),
    ("Место установки", "location", False, ""),
    ("Суффикс спецификации", "spec_doc_suffix", False, "В4"),
    ("Название документа", "spec_doc_name", False, "Спецификация"),
    ("Суффикс схемы", "e3_doc_suffix", False, "Э3"),
    ("Название схемы", "e3_doc_name", False, "Схема электрическая принципиальная"),
    ("Первый лист ПЛК в схеме", "e3_first_io_sheet", False, "2"),
    ("Лист питания 24В в схеме", "e3_power24_sheet", False, ""),
    ("Литера", "litera", False, ""),
    ("Масса", "mass", False, ""),
    ("Масштаб", "scale", False, ""),
]
ROLES = ["Разраб.", "Пров.", "Т.контр.", "Нач.отд.", "Н.контр.", "Утв."]

SPEC_COLS = ["Обозначение", "Наименование", "Артикул", "Кол-во",
             "Производитель", "Примечание"]
TERM_COLS = ["Клеммник", "Номер изделия", "Номер типа", "Поперечное сечение",
             "Маркировка клемм", "Перемычка", "Крышка", "Метка", "Ярус",
             "Группа перемычки"]


# --------------------------------------------------------------------- чтение
def _s(v) -> str:
    """Значение ячейки -> строка так, как её ждут на чертеже."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "да" if v else ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%m.%y")
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{v:g}".replace(".", ",")
    return str(v).strip()


def _norm(s: str) -> str:
    return " ".join(str(s or "").replace("ё", "е").lower().split())


def _sheet(wb, name: str, required: bool, problems: list[str]):
    for ws in wb.worksheets:
        if _norm(ws.title) == _norm(name):
            return ws
    if required:
        problems.append(f"Нет листа «{name}».")
    return None


def _table(ws, columns: list[str], problems: list[str]):
    """Находит строку заголовков и отдаёт (номер строки, {колонка: значение})."""
    want = {_norm(c): c for c in columns}
    header_row, idx = None, {}
    for r in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 10)):
        found = {want[_norm(c.value)]: c.column - 1 for c in r
                 if c.value is not None and _norm(c.value) in want}
        if len(found) >= 2:
            header_row, idx = r[0].row, found
            break
    if header_row is None:
        problems.append(f"Лист «{ws.title}»: не найдена строка заголовков "
                        f"({', '.join(columns)}).")
        return
    missing = [c for c in columns if c not in idx]
    if missing:
        problems.append(f"Лист «{ws.title}»: нет колонок: {', '.join(missing)}.")
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        rec = {c: _s(row[i]) if i < len(row) else "" for c, i in idx.items()}
        for c in columns:
            rec.setdefault(c, "")
        if any(rec.values()):
            yield rec


def read_document(path: str | Path) -> Document:
    problems: list[str] = []
    try:
        wb = load_workbook(path, data_only=True, read_only=False)
    except Exception as e:  # битый/не тот файл
        raise TemplateError([f"Не удалось открыть Excel-файл: {e}"]) from e

    # Проект
    values: dict[str, str] = {}
    ws = _sheet(wb, "Проект", True, problems)
    if ws is not None:
        for row in ws.iter_rows(values_only=True):
            if row and row[0] is not None:
                values[_norm(str(row[0]).rstrip(' *'))] = _s(row[1] if len(row) > 1 else None)
    kwargs = {}
    for label, attr, required, default in PROJECT_FIELDS:
        v = values.get(_norm(label), "") or default
        if required and not v and ws is not None:
            problems.append(f"Лист «Проект»: не заполнен параметр «{label}».")
        kwargs[attr] = v
    project = Project(**kwargs)
    if not project.e3_first_io_sheet.isdigit() or int(project.e3_first_io_sheet) < 2:
        problems.append("Лист «Проект»: «Первый лист ПЛК в схеме» — целое число от 2.")
        project.e3_first_io_sheet = "2"

    # Подписи
    ws = _sheet(wb, "Подписи", False, problems)
    if ws is not None:
        for rec in _table(ws, ["Роль", "Фамилия", "Дата"], problems):
            role = rec["Роль"]
            match = next((r for r in ROLES if _norm(r) == _norm(role)), None)
            if not match:
                problems.append(f"Лист «Подписи»: неизвестная роль «{role}» "
                                f"(допустимо: {', '.join(ROLES)}).")
                continue
            project.people.append(Person(match, rec["Фамилия"], rec["Дата"]))

    # Спецификация
    spec: list[SpecItem] = []
    ws = _sheet(wb, "Спецификация", True, problems)
    if ws is not None:
        for rec in _table(ws, SPEC_COLS, problems):
            spec.append(SpecItem(rec["Обозначение"], rec["Наименование"],
                                 rec["Артикул"], rec["Кол-во"],
                                 rec["Производитель"], rec["Примечание"]))

    # Клеммы
    blocks: list[TerminalBlock] = []
    ws = _sheet(wb, "Клеммы", False, problems)
    if ws is not None:
        by_name: dict[str, TerminalBlock] = {}
        last_name = ""
        for n, rec in enumerate(_table(ws, TERM_COLS, problems), 1):
            name = rec["Клеммник"] or last_name
            if not name:
                problems.append(f"Лист «Клеммы», запись {n}: не указан клеммник.")
                continue
            last_name = name
            tier_s = rec["Ярус"]
            if tier_s in ("", None):
                tier = 0 if rec["Метка"] else None
            elif tier_s in ("0", "1", "2"):
                tier = int(tier_s)
            elif tier_s == "-":
                tier = None
            else:
                problems.append(f"Лист «Клеммы», клеммник {name}: ярус «{tier_s}» — "
                                f"допустимо 0, 1, 2 или пусто.")
                tier = 0
            blk = by_name.get(name)
            if blk is None:
                blk = by_name[name] = TerminalBlock(name)
                blocks.append(blk)
            blk.rows.append(TerminalRow(
                part_no=rec["Номер изделия"], type_no=rec["Номер типа"],
                section=rec["Поперечное сечение"], marking=rec["Маркировка клемм"],
                jumper=rec["Перемычка"], cover=rec["Крышка"], label=rec["Метка"],
                tier=tier, bridge=rec["Группа перемычки"]))

    # Схема Э3: модули ПЛК и каналы
    from .e3.excel import read_plc, read_power24
    plc = read_plc(wb, _sheet, _table, problems)
    p24 = read_power24(wb, _sheet, _table, problems)

    if not spec and not blocks and not plc and not p24 and not problems:
        problems.append("В файле нет ни строк спецификации, ни клемм, ни каналов ПЛК.")
    if problems:
        raise TemplateError(problems)
    return Document(project, spec, blocks, plc, p24)


# ---------------------------------------------------------------------- запись
_HEAD = Font(bold=True)
_FILL = PatternFill("solid", fgColor="DDEBF7")


def _header(ws, cols: list[str], widths: list[int]) -> None:
    ws.append(cols)
    for i, w in enumerate(widths, 1):
        cell = ws.cell(row=1, column=i)
        cell.font, cell.fill = _HEAD, _FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[cell.column_letter].width = w
    ws.freeze_panes = "A2"


def write_workbook(path: str | Path, doc: Document | None = None) -> None:
    """Пустой шаблон (doc=None) или заполненный файл с данными doc."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Проект"
    _header(ws, ["Параметр", "Значение"], [28, 70])
    for label, attr, required, default in PROJECT_FIELDS:
        v = getattr(doc.project, attr) if doc else default
        ws.append([label + (" *" if required else ""), v])
    ws2 = wb.create_sheet("Подписи")
    _header(ws2, ["Роль", "Фамилия", "Дата"], [14, 24, 10])
    people = {p.role: p for p in doc.project.people} if doc else {}
    for role in ROLES:
        p = people.get(role)
        ws2.append([role, p.name if p else "", p.date if p else ""])

    ws3 = wb.create_sheet("Спецификация")
    _header(ws3, SPEC_COLS, [28, 80, 22, 8, 20, 20])
    for it in (doc.spec if doc else []):
        ws3.append([it.designation, it.name, it.article, _num(it.qty),
                    it.manufacturer, it.note])
    for row in ws3.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    ws4 = wb.create_sheet("Клеммы")
    _header(ws4, TERM_COLS, [11, 18, 16, 11, 12, 11, 9, 9, 6, 10])
    dv = DataValidation(type="list", formula1='"0,1,2,-"', allow_blank=True)
    ws4.add_data_validation(dv)
    dv.add("I2:I2000")
    for blk in (doc.terminals if doc else []):
        for r in blk.rows:
            tier = "" if r.tier is None else r.tier
            ws4.append([blk.name, r.part_no, r.type_no, r.section, r.marking,
                        r.jumper, r.cover, r.label, tier, _num(r.bridge)])

    from .e3.excel import write_plc, write_power24
    write_plc(wb, doc.plc if doc else [], _header)
    write_power24(wb, doc.power24 if doc else None, _header)
    _help_sheet(wb.create_sheet("Инструкция"))
    wb.save(path)


def _num(s: str):
    try:
        return int(s)
    except (TypeError, ValueError):
        return s


def _help_sheet(ws) -> None:
    ws.column_dimensions["A"].width = 120
    lines = [
        "КАК ЗАПОЛНЯТЬ",
        "",
        "Лист «Проект»: заполните колонку «Значение». Обязателен только «Шифр» "
        "(напр. ВКС.АСПУ.2196.СС1). К шифру добавляется суффикс спецификации (В4).",
        "Лист «Подписи»: фамилии и даты для основной надписи титульного листа "
        "(дату можно писать текстом «03.26»).",
        "Лист «Спецификация»: одна строка — одна позиция. № п/п проставляется "
        "автоматически. Длинные наименования переносятся сами.",
        "Лист «Клеммы»: одна строка — одна строка клеммного плана, в том же "
        "порядке, как на чертеже.",
        "   Клеммник — имя (X0, 1XT1 ...). Можно указать только в первой строке "
        "клеммника, ниже оставить пустым.",
        "   Метка — надпись клеммы справа (L1, PE, 1 ...). Пусто — для крышек и "
        "концевых пластин.",
        "   Ярус — 0 (одноярусная, по умолчанию, если есть метка), 1 и 2 — "
        "верхний/нижний ярус двухъярусной клеммы, «-» — без риски.",
        "   Для второго яруса двухъярусной клеммы добавьте строку, где заполнены "
        "только Метка и Ярус=2.",
        "   Группа перемычки — одинаковый номер у клемм, соединённых перемычкой "
        "(внутри одного клеммника).",
        "   «Общее количество клемм» считается автоматически: клеммы с "
        "заполненным «Поперечным сечением».",
        "",
        "СХЕМА Э3 (листы входов/выходов ПЛК)",
        "Лист «Модули ПЛК»: одна строка — один модуль (CPU, A1 ...). Вид — «Входы» или «Выходы».",
        "   Ссылка — где модуль изображён целиком (напр. /5.0), выводится под обозначением.",
        "   Для входов: «Стрелка слева» — откуда приходит питание контактов реле и кнопок "
        "(напр. -KBF1:24 / 7.3), «Стрелка вправо» — куда питание уходит дальше; провод — "
        "марка/цвет/сечение этого провода.",
        "   Для выходов: «Стрелка слева» — общий провод катушек (напр. -XM1:M5/4.8); "
        "«Выходы NPN» = да, если модуль коммутирует минус (у катушки A2 — к выходу).",
        "Лист «Каналы ПЛК»: одна строка — один вывод модуля, в порядке слева направо.",
        "   Элемент (для входов): пусто — провод со стрелкой от «Связь»; ТТР — контакт "
        "твердотельного реле 13+/14; Перекл — перекидной контакт 11/14/12; Кнопка НО; "
        "Кнопка НЗ; Общий — COM модуля (стрелка вправо к «Связь»).",
        "   Элемент (для выходов): пусто — провод стрелкой вниз к «Связь»; Катушка; Лампа; "
        "Общий — COM OUT (стрелка вправо); Питание — +24V модуля (приходит справа).",
        "   Обозначение — позиционное обозначение реле/кнопки (-2K1). Ссылки между "
        "катушками и контактами проставляются автоматически.",
        "   Ссылка — вручную, если элемент на другом (не генерируемом) листе: у стрелки — "
        "лист.столбец цели (12.1), у контакта — где катушка (/16.3), у катушки — где контакт.",
        "   Параметр — надпись у катушки/лампы (=24V).",
        "   Вывод без провода и элемента (резерв) рисуется только с подписью.",
        "",
        "ПИТАНИЕ 24 В (лист «Питание 24В»): строки по группам.",
        "   Группа автоматов (напр. 1): строка «ввод» — откуда питание шины (Связь, провод); "
        "строки «автомат» — Обозначение (1QFU1), Номинал (DC 1A 'C'), провод, Связь/Ссылка — "
        "куда идёт (напр. -ES1:V+), Связь 2 — второй потребитель, Подпись — надпись в рамке.",
        "   Шина минусов (Группа = имя клеммника, напр. XM1): «ввод» и строки «отвод вверх» / "
        "«отвод вниз» — Обозначение = клемма (M1), провод, Связь (-ES1:V-).",
        "   Ссылки лист.столбец на стрелках можно не писать — если потребитель есть на "
        "листах ПЛК, ссылка подставится сама.",
        "   «Первый лист ПЛК в схеме» (лист «Проект»): если перед листами ПЛК в схеме "
        "должны идти другие листы (силовая часть и т.п.), укажите номер, с которого "
        "начинать — нумерация и ссылки будут с учётом этого.",
    ]
    for ln in lines:
        ws.append([ln])
    ws["A1"].font = _HEAD
