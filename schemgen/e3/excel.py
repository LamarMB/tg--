"""Чтение/запись листов «Модули ПЛК» и «Каналы ПЛК»."""
from __future__ import annotations

from .model import INPUT_ELEMENTS, OUTPUT_ELEMENTS, PlcChannel, PlcModule

MOD_COLS = ["Модуль", "Позиция", "Тип", "Вид", "Ссылка", "Стрелка слева", "Стрелка вправо",
            "Марка провода", "Цвет", "Сечение", "Выходы NPN"]
CH_COLS = ["Модуль", "Вывод", "Назначение", "Марка провода", "Цвет", "Сечение",
           "Элемент", "Обозначение", "Связь", "Ссылка", "Параметр"]

_EL_ALIASES = {"": "", "ттр": "ттр", "но ттр": "ттр", "перекл": "перекл",
               "перекидной": "перекл", "кнопка но": "кнопка но", "кнопка нз": "кнопка нз",
               "катушка": "катушка", "реле": "катушка", "лампа": "лампа",
               "общий": "общий", "com": "общий", "питание": "питание", "+24v": "питание"}


def _tag(s: str) -> str:
    s = s.strip()
    return s if not s or s.startswith("-") else "-" + s


def read_plc(wb, find_sheet, table, problems) -> list[PlcModule]:
    ws_m = find_sheet(wb, "Модули ПЛК", False, problems)
    ws_c = find_sheet(wb, "Каналы ПЛК", False, problems)
    if ws_m is None and ws_c is None:
        return []
    mods: dict[str, PlcModule] = {}
    order: list[PlcModule] = []
    if ws_m is not None:
        for rec in table(ws_m, MOD_COLS, problems):
            name = rec["Модуль"].lstrip("-")
            if not name:
                continue
            kind = rec["Вид"].lower()
            if kind.startswith("вх"):
                kind = "in"
            elif kind.startswith("вых"):
                kind = "out"
            else:
                problems.append(f"Лист «Модули ПЛК», модуль {name}: Вид «{rec['Вид']}» — "
                                "нужно «Входы» или «Выходы».")
                continue
            wire = [rec["Марка провода"], rec["Цвет"], rec["Сечение"]]
            m = PlcModule((rec["Позиция"] or name).lstrip("-"), rec["Тип"], kind, rec["Ссылка"],
                          npn=rec["Выходы NPN"].lower() in ("да", "1", "npn", "yes"))
            if kind == "in":
                m.feed, m.feed_next, m.feed_wire = rec["Стрелка слева"], rec["Стрелка вправо"], wire
            else:
                m.common, m.common_wire = rec["Стрелка слева"], wire
            key = name.upper()
            if key in mods:
                problems.append(f"Лист «Модули ПЛК»: модуль {name} указан дважды.")
                continue
            m.key = name
            mods[key] = m
            order.append(m)
    if ws_c is not None:
        last = ""
        for n, rec in enumerate(table(ws_c, CH_COLS, problems), 1):
            name = (rec["Модуль"] or last).lstrip("-")
            last = name
            m = mods.get(name.upper())
            where = f"Лист «Каналы ПЛК», модуль {name}, вывод {rec['Вывод'] or '?'}"
            if m is None:
                problems.append(f"{where}: модуль не описан на листе «Модули ПЛК».")
                continue
            el = _EL_ALIASES.get(rec["Элемент"].strip().lower())
            if el is None:
                problems.append(f"{where}: неизвестный элемент «{rec['Элемент']}».")
                continue
            allowed = INPUT_ELEMENTS if m.kind == "in" else OUTPUT_ELEMENTS
            if el not in allowed:
                problems.append(f"{where}: элемент «{rec['Элемент']}» не подходит для "
                                f"{'входов' if m.kind == 'in' else 'выходов'}.")
                continue
            if el in ("ттр", "перекл", "кнопка но", "кнопка нз", "катушка", "лампа") \
                    and not rec["Обозначение"]:
                problems.append(f"{where}: для элемента «{rec['Элемент']}» нужно Обозначение.")
                continue
            m.channels.append(PlcChannel(
                module=name, pin=rec["Вывод"], desc=rec["Назначение"],
                wire=[rec["Марка провода"], rec["Цвет"], rec["Сечение"]], element=el,
                device=_tag(rec["Обозначение"]), link=rec["Связь"], ref=rec["Ссылка"],
                param=rec["Параметр"]))
    return [m for m in order if m.channels]


def write_plc(wb, modules: list[PlcModule], header) -> None:
    ws = wb.create_sheet("Модули ПЛК")
    header(ws, MOD_COLS, [9, 9, 18, 9, 8, 22, 22, 13, 8, 8, 10])
    for m in modules:
        wire = m.feed_wire if m.kind == "in" else m.common_wire
        wire = (wire + ["", "", ""])[:3]
        ws.append([m.key or m.tag, m.tag if m.key and m.key != m.tag else "", m.type, "Входы" if m.kind == "in" else "Выходы", m.ref,
                   m.feed if m.kind == "in" else m.common,
                   m.feed_next if m.kind == "in" else "", *wire,
                   "да" if m.npn else ""])
    ws2 = wb.create_sheet("Каналы ПЛК")
    header(ws2, CH_COLS, [8, 7, 34, 12, 7, 8, 11, 11, 18, 8, 9])
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", allow_blank=True, formula1='"ТТР,Перекл,Кнопка НО,'
                        'Кнопка НЗ,Катушка,Лампа,Общий,Питание"')
    ws2.add_data_validation(dv)
    dv.add("G2:G3000")
    names = {"ттр": "ТТР", "перекл": "Перекл", "кнопка но": "Кнопка НО",
             "кнопка нз": "Кнопка НЗ", "катушка": "Катушка", "лампа": "Лампа",
             "общий": "Общий", "питание": "Питание", "": ""}
    for m in modules:
        for c in m.channels:
            w = (c.wire + ["", "", ""])[:3]
            ws2.append([m.key or m.tag, c.pin, c.desc, *w, names[c.element], c.device, c.link,
                        c.ref, c.param])
