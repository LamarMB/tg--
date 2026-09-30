"""Модель данных проекта: то, что читается из Excel и рисуется в PDF."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Person:
    """Строка подписи в основной надписи (Разраб., Пров. и т.д.)."""
    role: str
    name: str = ""
    date: str = ""


@dataclass
class Project:
    code: str                      # Шифр, напр. ВКС.АСПУ.2196.СС1
    system_name: str = ""          # Автоматизированная система поштучного учета
    contractor: str = ""           # Исполнитель
    customer: str = ""             # Заказчик
    line: str = ""                 # Линия 4а
    product: str = ""              # Шкаф управления ШУ1
    location: str = ""             # +СС1
    spec_doc_suffix: str = "В4"
    spec_doc_name: str = "Спецификация"
    e3_doc_suffix: str = "Э3"
    e3_doc_name: str = "Схема электрическая принципиальная"
    e3_first_io_sheet: str = "2"   # с какого номера листа начинаются листы ПЛК
    e3_power24_sheet: str = ""     # номер листа «Питание 24 В» (пусто — следующий по порядку)
    e3_feeders_sheet: str = ""     # номер листа «Отходящие линии 230 В»
    e3_mains_sheet: str = ""       # номер листа «Ввод и питание 230 В»
    e3_network_sheet: str = ""     # номер листа «Сеть»
    e3_fields_sheet: str = ""      # первый лист «Коробки / внешние шкафы»
    litera: str = ""
    mass: str = ""
    scale: str = ""
    people: list[Person] = field(default_factory=list)


@dataclass
class SpecItem:
    designation: str
    name: str
    article: str = ""
    qty: str = ""
    manufacturer: str = ""
    note: str = ""


@dataclass
class TerminalRow:
    """Одна строка клеммного плана.

    tier: 0 — одноярусная клемма, 1 / 2 — верхний / нижний ярус двухъярусной;
          None — строка без метки (концевая крышка, пластина).
    bridge: номер группы перемычки внутри клеммника (строки с одинаковым
            номером соединяются перемычкой на рисунке справа).
    """
    part_no: str = ""
    type_no: str = ""
    section: str = ""
    marking: str = ""
    jumper: str = ""
    cover: str = ""
    label: str = ""
    tier: int | None = None
    bridge: str = ""


@dataclass
class TerminalBlock:
    name: str
    rows: list[TerminalRow] = field(default_factory=list)

    @property
    def terminal_count(self) -> int:
        # Как в образце: считаются клеммы, у которых указано сечение
        # (крышки и концевые пластины не считаются).
        return sum(1 for r in self.rows if r.section.strip())


@dataclass
class Document:
    project: Project
    spec: list[SpecItem] = field(default_factory=list)
    terminals: list[TerminalBlock] = field(default_factory=list)
    plc: list = field(default_factory=list)       # list[e3.model.PlcModule]
    power24: object = None                        # e3.power24.Power24
    feeders: list = field(default_factory=list)   # list[e3.power230.Feeder]
    mains: object = None                          # e3.mains.Mains
    frozen: list = field(default_factory=list)    # template.Frozen — листы из образца
    network: object = None                        # e3.network.Network
    fields: list = field(default_factory=list)    # list[e3.field.FieldArea]
    column: object = None                         # e3.column.Column — сигнальная колонна
