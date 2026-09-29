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


# ------------------------------------------------------------ Питание 24 В
P24_COLS = ["Группа", "Тип", "Обозначение", "Номинал", "Марка провода", "Цвет",
            "Сечение", "Связь", "Ссылка", "Связь 2", "Ссылка 2", "Подпись"]
P24_TYPES = {"ввод": "ввод", "источник": "ввод", "автомат": "автомат", "qf": "автомат",
             "отвод вверх": "вверх", "вверх": "вверх", "отвод вниз": "вниз", "вниз": "вниз"}


def read_power24(wb, find_sheet, table, problems):
    from .power24 import Breaker, BreakerGroup, MinusBus, MinusTap, Power24
    ws = find_sheet(wb, "Питание 24В", False, problems) or \
        find_sheet(wb, "Питание 24 В", False, problems)
    if ws is None:
        return None
    rows, last = [], ""
    for rec in table(ws, P24_COLS, problems):
        grp = rec["Группа"] or last
        last = grp
        kind = P24_TYPES.get(rec["Тип"].strip().lower())
        if not grp or kind is None:
            problems.append(f"Лист «Питание 24В», группа {grp or '?'}: тип «{rec['Тип']}» — "
                            "нужно: ввод, автомат, отвод вверх, отвод вниз.")
            continue
        rows.append((grp, kind, rec))
    pw = Power24()
    groups: dict[str, object] = {}
    for grp, kind, rec in rows:
        is_minus = any(g == grp and k in ("вверх", "вниз") for g, k, _ in rows)
        obj = groups.get(grp)
        if obj is None:
            obj = MinusBus(grp.lstrip("-")) if is_minus else BreakerGroup(grp)
            groups[grp] = obj
            (pw.minus if is_minus else pw.groups).append(obj)
        wire = [rec["Марка провода"], rec["Цвет"], rec["Сечение"]]
        if kind == "ввод":
            obj.source, obj.source_ref, obj.source_wire = rec["Связь"], rec["Ссылка"], wire
        elif kind == "автомат":
            if is_minus:
                problems.append(f"Лист «Питание 24В», группа {grp}: автоматы и отводы "
                                "минуса в одной группе.")
                continue
            tag = rec["Обозначение"]
            tag = tag if tag.startswith("-") or not tag else "-" + tag
            targets = [(rec["Связь"], rec["Ссылка"])]
            if rec["Связь 2"]:
                targets.append((rec["Связь 2"], rec["Ссылка 2"]))
            obj.breakers.append(Breaker(tag, rec["Номинал"], wire, targets, rec["Подпись"]))
        else:
            obj.taps.append(MinusTap(rec["Обозначение"], kind == "вверх", wire,
                                     rec["Связь"], rec["Ссылка"]))
    return pw if pw else None


def write_power24(wb, pw, header) -> None:
    ws = wb.create_sheet("Питание 24В")
    header(ws, P24_COLS, [8, 11, 12, 12, 12, 8, 8, 20, 8, 16, 8, 24])
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", allow_blank=True,
                        formula1='"ввод,автомат,отвод вверх,отвод вниз"')
    ws.add_data_validation(dv)
    dv.add("B2:B2000")
    if not pw:
        return
    for g in pw.groups:
        if g.source:
            ws.append([g.name, "ввод", "", "", *(g.source_wire + ["", "", ""])[:3],
                       g.source, g.source_ref, "", "", ""])
        for b in g.breakers:
            t = b.targets + [("", "")] * (2 - len(b.targets))
            ws.append([g.name, "автомат", b.tag, b.rating, *(b.wire + ["", "", ""])[:3],
                       t[0][0], t[0][1], t[1][0], t[1][1], b.caption])
    for m in pw.minus:
        if m.source:
            ws.append([m.name, "ввод", "", "", *(m.source_wire + ["", "", ""])[:3],
                       m.source, m.source_ref, "", "", ""])
        for t in m.taps:
            ws.append([m.name, "отвод вверх" if t.up else "отвод вниз", t.clamp, "",
                       *(t.wire + ["", "", ""])[:3], t.link, t.ref, "", "", ""])


# ------------------------------------------------------------ Линии 230 В
F_COLS = ["Автомат", "Тип", "Номинал", "Утечка", "Сечение", "Питание L", "Ссылка L",
          "Питание N", "Ссылка N", "Клеммник", "Кабель", "Марка кабеля", "Жилы", "Зона",
          "Розетки", "Номинал розеток", "Нагрузка L", "Нагрузка N", "Нагрузка PE",
          "Ссылка нагрузки", "Подпись"]


def read_feeders(wb, find_sheet, table, problems):
    from .power230 import Feeder
    ws = find_sheet(wb, "Линии 230В", False, problems) or \
        find_sheet(wb, "Линии 230 В", False, problems)
    if ws is None:
        return []
    out = []
    for rec in table(ws, F_COLS, problems):
        tag = rec["Автомат"]
        if not tag:
            problems.append("Лист «Линии 230В»: строка без обозначения автомата.")
            continue
        kind = rec["Тип"].strip().lower() or "авдт"
        if kind not in ("авдт", "ав"):
            problems.append(f"Лист «Линии 230В», {tag}: тип «{rec['Тип']}» — нужно АВДТ или АВ.")
            continue
        socks = [x.strip() for x in rec["Розетки"].replace(",", ";").split(";") if x.strip()]
        loads = [rec["Нагрузка L"], rec["Нагрузка N"], rec["Нагрузка PE"]]
        out.append(Feeder(tag if tag.startswith("-") else "-" + tag, kind, rec["Номинал"],
                          rec["Утечка"], rec["Сечение"] or "2,5", rec["Питание L"],
                          rec["Ссылка L"], rec["Питание N"], rec["Ссылка N"],
                          rec["Клеммник"], rec["Кабель"], rec["Марка кабеля"], rec["Жилы"],
                          rec["Зона"], socks, rec["Номинал розеток"],
                          loads if any(loads) else [], rec["Ссылка нагрузки"], rec["Подпись"]))
    return out


def write_feeders(wb, feeders, header) -> None:
    ws = wb.create_sheet("Линии 230В")
    header(ws, F_COLS, [9, 7, 9, 8, 8, 12, 8, 12, 8, 9, 9, 24, 8, 7, 18, 9, 14, 14, 14, 10, 30])
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", allow_blank=True, formula1='"АВДТ,АВ"')
    ws.add_data_validation(dv)
    dv.add("B2:B500")
    for f in feeders or []:
        loads = (f.load_links + ["", "", ""])[:3]
        ws.append([f.tag, "АВДТ" if f.kind == "авдт" else "АВ", f.rating, f.leak, f.section,
                   f.source, f.source_ref, f.n_source, f.n_ref, f.terminal, f.cable,
                   f.cable_type, f.cable_cores, f.zone, ";".join(f.sockets), f.socket_rating,
                   *loads, f.load_ref, f.caption])
