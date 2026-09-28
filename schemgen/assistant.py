"""Разбор описания проекта свободным текстом через Claude API.

Модель получает текущий проект (JSON) и сообщение пользователя и через
инструмент save_project возвращает только изменённые разделы. Раздел,
который модель прислала, заменяет раздел проекта целиком; остальные
остаются как были.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """Ты — инженер-проектировщик АСУ ТП (шкафы управления, ГОСТ 2.702, 2.710).
Пользователь описывает проект шкафа свободным текстом (часто кратко, с жаргоном).
Твоя задача — перевести описание в структуру проекта и вызвать инструмент save_project.

ПРАВИЛА
1. Не выдумывай то, чего пользователь не говорил: артикулы, производителей, номера
   листов, фамилии. Оставляй такие поля пустыми и перечисли главное недостающее в
   questions (коротко, не больше 6 пунктов).
2. Очевидное достраивай сам: позиционные обозначения по ГОСТ (QF — автоматы, K —
   реле, SB — кнопки, HL — лампы/колонны, XT/X — клеммники, A — модули), маркировку
   проводов по образцу «A1-DI0», «CPU-Q0» (цвет WH/BK, сечение 0,5 для сигналов, если
   не сказано иное), № выводов модулей по порядку (A1…A8, B1…B8, COM — A9/B9).
3. Если в проекте уже есть данные, меняй только то, о чём просит пользователь, а в
   save_project присылай ТОЛЬКО изменённые разделы (project / spec / terminals / plc),
   каждый раздел — целиком в новом виде. Неизменённые разделы не присылай.
4. Спецификация (spec): одна строка — одна позиция; designation — обозначения через «;»
   (напр. «QF1;QF2») или диапазоном «1K1...1K4»; qty — число строкой.
5. Клеммы (terminals): блок = клеммник; строка = клемма или крышка. label — надпись
   клеммы (L, N, PE, 1, 2 …); section — сечение («2,5», «1,5»); у концевой крышки
   label пустой; tier: 0 — одноярусная, 1/2 — ярусы двухъярусной (для яруса 2 строка
   с пустыми part_no/type_no); bridge — одинаковый номер у клемм под одной перемычкой.
6. ПЛК (plc): модуль = kind "in" (входы) или "out" (выходы). Если у CPU есть и входы, и
   выходы — два модуля с одинаковым tag и разными key («CPU.DI», «CPU.DO»).
   element канала:
     входы:  "" — провод со стрелкой от link (клемма/устройство), "ттр" — НО контакт
             твердотельного реле 13+/14, "перекл" — перекидной контакт 11/14/12,
             "кнопка но", "кнопка нз", "общий" — COM модуля (стрелка к link);
     выходы: "" — провод стрелкой к link, "катушка" — катушка реле (param «=24V»),
             "лампа", "общий" — COM OUT, "питание" — +24V модуля.
   device — обозначение реле/кнопки («-1K1»). Контакты и катушки одного реле должны
   иметь одинаковое device — ссылки между ними программа ставит сама.
   feed/feed_wire — питание контактов модуля входов (стрелка слева), common/common_wire
   — общий провод катушек модуля выходов; npn=true, если выходы коммутируют минус.
   desc — назначение вывода, переносы строк можно ставить «\\n».
   Марку провода придумывай всегда: вход «<модуль>-DI<n>» (n с 0), выход
   «<модуль>-Q<n>», общий — по клемме («XM1-M3»). Ссылки на устройства в link, feed,
   common пиши с минусом: «-1XT1:1».
7. summary — 1–3 предложения по-русски: что понял и что изменил.
"""

def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


WIRE = {"type": "object", "description": "Провод: марка, цвет, сечение",
        "properties": {"mark": _str("марка провода, напр. CPU-DI0, A1-Q3, XM1-M4, 1QFU5-1"),
                       "color": _str("цвет: WH, BK, RD, BU, DK BU, GNYE ..."),
                       "section": _str("сечение, мм², напр. 0,5")}}

TOOL = {
    "name": "save_project",
    "description": "Сохранить изменённые разделы проекта шкафа.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": _str("1–3 предложения: что понял и что изменил"),
            "questions": {"type": "array", "items": {"type": "string"},
                          "description": "что уточнить у пользователя (до 6 пунктов)"},
            "project": {"type": "object", "properties": {
                "code": _str("шифр без суффикса документа, напр. ВКС.АСПУ.2196.СС1"),
                "system_name": _str("наименование системы на титуле, напр. "
                                    "«Автоматизированная система поштучного учета»; "
                                    "не название шкафа"),
                "contractor": _str("исполнитель, напр. ООО \"ВЕКАС\""),
                "customer": _str("заказчик"),
                "line": _str("линия/объект в основной надписи, напр. «Линия 4а»"),
                "product": _str("изделие, напр. «Шкаф управления ШУ1»"),
                "location": _str("место установки / обозначение шкафа, напр. +СС1"),
                "litera": _str("литера"), "mass": _str("масса"), "scale": _str("масштаб"),
                "e3_first_io_sheet": _str("номер первого листа ПЛК в схеме Э3 (по умолчанию 2)"),
                "people": {"type": "array", "items": {"type": "object", "properties": {
                    "role": {"type": "string", "enum": ["Разраб.", "Пров.", "Т.контр.",
                                                        "Нач.отд.", "Н.контр.", "Утв."]},
                    "name": _str("фамилия"), "date": _str("дата, напр. 03.26")}}}}},
            "spec": {"type": "array", "items": {"type": "object", "properties": {
                "designation": _str("позиционные обозначения: QF1;QF2 или 1K1...1K4"),
                "name": _str("наименование изделия"),
                "article": _str("артикул (только если назван пользователем)"),
                "qty": _str("количество"),
                "manufacturer": _str("производитель (только если назван)"),
                "note": _str("примечание")}}},
            "terminals": {"type": "array", "items": {"type": "object", "properties": {
                "name": _str("имя клеммника: X1, 1XT1 ..."),
                "rows": {"type": "array", "items": {"type": "object", "properties": {
                    "part_no": _str("номер изделия (код заказа): CWL.CP2.5, PXC.3214657"),
                    "type_no": _str("номер типа: CP2.5, CPG2.5, EPCX2.5, PTTBS 1,5"),
                    "section": _str("сечение клеммы, мм² (у крышек и пластин — пусто)"),
                    "marking": _str("маркировка клемм (обычно пусто)"),
                    "jumper": _str("перемычка (обычно пусто)"),
                    "cover": _str("крышка (обычно пусто)"),
                    "label": _str("надпись клеммы: L, N, PE, 1, 2; у крышки пусто"),
                    "tier": {"type": ["integer", "null"],
                             "description": "0 — одноярусная, 1/2 — ярус двухъярусной, "
                                            "null — крышка"},
                    "bridge": _str("номер группы перемычки")}}}}}},
            "plc": {"type": "array", "items": {"type": "object", "properties": {
                "key": _str("уникальное имя модуля: CPU.DI, CPU.DO, A1 ..."),
                "tag": _str("позиция на схеме без минуса: CPU, A1"),
                "type": _str("тип модуля: AM5210808TN, GL20-1600END"),
                "kind": {"type": "string", "enum": ["in", "out"]},
                "ref": _str("ссылка на лист, где модуль целиком, напр. /5.0"),
                "feed": _str("входы: откуда питание контактов, напр. -KBF1:24 / 7.3"),
                "feed_wire": WIRE,
                "feed_next": _str("входы: куда питание уходит дальше"),
                "common": _str("выходы: общий провод катушек, напр. -XM1:M5/4.8"),
                "common_wire": WIRE,
                "npn": {"type": "boolean", "description": "выходы коммутируют минус"},
                "channels": {"type": "array", "items": {"type": "object", "properties": {
                    "pin": _str("вывод модуля: A1…A8, B1…B8; COM входов — A9 (и B9), "
                                "COM OUT / +24V выходов — B9 / A9"),
                    "desc": _str("назначение, строки через \\n"),
                    "wire": WIRE,
                    "element": {"type": "string", "enum": [
                        "", "ттр", "перекл", "кнопка но", "кнопка нз", "катушка", "лампа",
                        "общий", "питание"]},
                    "device": _str("обозначение реле/кнопки/лампы: -1K1, -S1"),
                    "link": _str("откуда/куда провод: -1XT1:1, -U1:DC OK, -XM1:M3"),
                    "ref": _str("ссылка вручную: лист.столбец (12.1) или /16.3"),
                    "param": _str("надпись у катушки/лампы: =24V")}}}}}},
        },
        "required": ["summary"],
    },
}

SECTIONS = ("project", "spec", "terminals", "plc")


class AssistantError(Exception):
    pass


def ask(api_key: str, current: dict, message: str, model: str = DEFAULT_MODEL,
        url: str = API_URL, timeout: float = 600) -> dict:
    """Возвращает ответ инструмента save_project (dict)."""
    user = ("Текущий проект (JSON):\n" + json.dumps(current, ensure_ascii=False,
                                                    separators=(",", ":"))
            + "\n\nСообщение пользователя:\n" + message)
    body = {
        "model": model,
        "max_tokens": 32000,
        "system": SYSTEM,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": "save_project"},
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise AssistantError(f"Claude API ответил ошибкой {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise AssistantError(f"Нет связи с api.anthropic.com: {e.reason}. "
                             "Из России нужен VPN.") from e
    for block in res.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "save_project":
            return block.get("input") or {}
    if res.get("stop_reason") == "max_tokens":
        raise AssistantError("Описание слишком большое для одного сообщения — "
                             "пришлите его частями.")
    raise AssistantError("Модель не вернула проект, попробуйте переформулировать.")


def merge(current: dict, update: dict) -> dict:
    """Применяет присланные разделы к текущему проекту."""
    out = {k: current.get(k) for k in SECTIONS}
    if update.get("project"):
        pr = dict(out.get("project") or {})
        pr.update({k: v for k, v in update["project"].items() if v is not None})
        out["project"] = pr
    for k in ("spec", "terminals", "plc"):
        if update.get(k):  # пустой список = раздел не менялся
            out[k] = update[k]
    return out
