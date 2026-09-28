"""Модель данных для схемы Э3: модули ПЛК и их каналы."""
from __future__ import annotations

from dataclasses import dataclass, field

# Типы элементов в колонке «Элемент»
CONTACT_SSR = "ттр"            # НО контакт твердотельного реле 13+/14
CONTACT_CO = "перекл"          # перекидной контакт 11/14/12
BUTTON_NO = "кнопка но"
BUTTON_NC = "кнопка нз"
COIL = "катушка"
LAMP = "лампа"
COMMON = "общий"               # COM модуля: провод уходит стрелкой вправо
SUPPLY = "питание"             # +24V модуля выходов: провод приходит справа

INPUT_ELEMENTS = {"", CONTACT_SSR, CONTACT_CO, BUTTON_NO, BUTTON_NC, COMMON}
OUTPUT_ELEMENTS = {"", COIL, LAMP, COMMON, SUPPLY}


@dataclass
class PlcChannel:
    module: str
    pin: str
    desc: str = ""
    wire: list[str] = field(default_factory=list)   # [марка, цвет, сечение]
    element: str = ""
    device: str = ""        # -2K1, -S1 ...
    link: str = ""          # куда/откуда провод: -1XT1:1
    ref: str = ""           # ссылка вручную (если не найдена автоматически)
    param: str = ""         # =24V и т.п.


@dataclass
class PlcModule:
    tag: str                 # CPU, A1 ...
    type: str                # AM5210808TN
    kind: str                # "in" / "out"
    ref: str = ""            # /5.0 — где изображён модуль целиком
    feed: str = ""           # вход: питание контактов, стрелка слева
    feed_wire: list[str] = field(default_factory=list)
    feed_next: str = ""      # вход: продолжение питания, стрелка вправо
    common: str = ""         # выход: общий провод катушек, стрелка слева
    common_wire: list[str] = field(default_factory=list)
    npn: bool = False        # выход: ключ по минусу (катушка A2 — к выходу)
    channels: list[PlcChannel] = field(default_factory=list)
    key: str = ""            # имя строки в Excel (если позиция повторяется: CPU.DI / CPU.DO)

    @property
    def title(self) -> str:
        return "digital inputs" if self.kind == "in" else "digital outputs"
