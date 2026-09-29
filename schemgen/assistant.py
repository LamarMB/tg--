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

ГЛАВНОЕ ПРАВИЛО: в проект попадает ТОЛЬКО то, что есть в тексте пользователя.
Никогда не придумывай оборудование, модули, каналы, реле, кнопки, лампы, клеммники,
клеммы и позиции спецификации, которых нет в тексте. Не подставляй «типовую» или
«примерную» схему. Если в сообщении только реквизиты — заполни только project,
остальные разделы не присылай и спроси в questions, какое оборудование в шкафу.
Лучше меньше, но точно.

ПРАВИЛА
1. Не выдумывай то, чего пользователь не говорил: артикулы, производителей, номера
   листов, фамилии. Оставляй такие поля пустыми и перечисли главное недостающее в
   questions (коротко, не больше 6 пунктов).
1б. Артикул и производитель у новой или изменённой позиции — ТОЛЬКО если пользователь их
   назвал в этом сообщении. Не подбирай и не «продолжай ряд» артикулов по аналогии
   (13350DEK, 13351DEK → 13353DEK — нельзя): оставь пустым и спроси в questions.
1а. Переноси ВСЕ перечисленные пользователем позиции, клеммы и каналы полностью и
   дословно (наименование, артикул, количество, производитель) — не сокращай, не
   объединяй и не пропускай, даже если их сотни.
2. Очевидное достраивай сам: позиционные обозначения по ГОСТ (QF — автоматы, K —
   реле, SB — кнопки, HL — лампы/колонны, XT/X — клеммники, A — модули), маркировку
   проводов по образцу «A1-DI0», «CPU-Q0» (цвет WH/BK, сечение 0,5 для сигналов, если
   не сказано иное), № выводов модулей по порядку (A1…A8, B1…B8, COM — A9/B9).
3. Если в проекте уже есть данные, меняй только то, о чём просит пользователь:
   project — только изменённые поля;
   power24 — только изменённые группы/шины минусов, каждая целиком;
   feeders — только изменённые/новые линии 230 В, каждая целиком;
   spec — если меняется, весь список целиком (все позиции, включая неизменённые);
   terminals — только изменённые/новые клеммники, каждый целиком (все строки);
     удалённые клеммники перечисли в remove_terminal_blocks;
   plc — только изменённые/новые модули, каждый целиком (все каналы, как были, с
     правкой); удалённые модули перечисли в remove_plc_modules (по key).
   Неизменённое не присылай.
4. Спецификация (spec): правка одного изделия из общей строки (напр. «1QFU6 на 6А» при
   строке «1QFU6;2QFU3;2QFU6 … 4А, 3 шт») — убери его обозначение из общей строки и
   уменьши её количество, а для него заведи отдельную строку. Остальные изделия
   общей строки не меняются. Если изделие удалено из схемы — убери его и из спецификации.
   Одна строка — одна позиция; designation — обозначения через «;»
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
   link: только реально названная точка подключения («-1XT1:1», «-U1:DC OK»). Если в
   тексте названо лишь устройство или коробка — пиши только его («+1KK1», «-UPS»),
   НЕ сочиняй имена клемм и сигналов вроде «:A», «:BOSCH1_RDY». Если ничего не
   названо — оставь пустым.
   Выход, который идёт на промежуточное реле / колонну через реле, — element
   «катушка» с device реле (-K1); реле только для сопряжения — тоже катушка.
   Если обозначение устройства в тексте не названо, не придумывай номер: оставь
   device пустым у простых стрелок, а для реле/кнопок спроси в questions.
   Марку провода придумывай всегда: вход «<модуль>-DI<n>» (n с 0), выход
   «<модуль>-Q<n>», общий — по клемме («XM1-M3»). Ссылки на устройства в link, feed,
   common пиши с минусом: «-1XT1:1».
6а. Питание 24 В (power24): группы автоматов на шине (groups) и шины минусов (minus).
   Автомат: tag «-1QFU1», rating «DC 1A 'C'», wire (марка «1QFU1-1», RD, 0,5), targets —
   куда идёт (до двух, «-A3:A9»), caption — назначение («Питание ПЛК»). Шина минусов:
   name «XM1», taps — отводы: clamp «M1», up (вверх/вниз), link «-ES1:V-».
   Правка: присылай изменённую группу / шину целиком (все автоматы / отводы). Чтобы
   убрать один автомат — пришли его группу целиком без него. remove_power24_groups —
   только для удаления группы или шины целиком. Ссылки «лист.столбец» не выдумывай — программа ставит их сама.
6б. Отходящие линии 230 В (feeders): линия = автомат (tag -QF1, kind авдт/ав, rating,
   leak), источник фазы (source -QS1:8) и нейтрали (n_source -XN:N1), клеммник, кабель,
   далее розетки (sockets) или стрелки к нагрузке (load_links: L, N, PE), caption.
   Правка: присылай изменённую линию целиком; удалённые — в remove_feeders.
7. summary — 1–3 предложения по-русски: только что именно изменено/добавлено.
   Не пиши о том, что не менялось, и не упоминай «разделы» и «запросы».
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
            "project": {"type": "object", "additionalProperties": False, "properties": {
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
            "power24": {"type": "object", "description": "Лист «Распределение питания 24 В»",
                        "properties": {
                "groups": {"type": "array", "description": "группы автоматов на общей шине",
                           "items": {"type": "object", "properties": {
                    "name": _str("имя группы: 1, 2 …"),
                    "source": _str("откуда питание шины: -X0.3:1L+"),
                    "source_ref": _str("ссылка вручную"),
                    "source_wire": WIRE,
                    "breakers": {"type": "array", "items": {"type": "object", "properties": {
                        "tag": _str("автомат: -1QFU1"),
                        "rating": _str("номинал: DC 1A 'C'"),
                        "wire": WIRE,
                        "targets": {"type": "array", "description": "потребители (до двух)",
                                    "items": {"type": "object", "properties": {
                                        "link": _str("-ES1:V+, -A3:A9, -1XT1:L+"),
                                        "ref": _str("ссылка вручную (лист.столбец)")}}},
                        "caption": _str("надпись в рамке: «Питание коммутатора»")}}}}}},
                "minus": {"type": "array", "description": "шины минусов (клеммник XM1 …)",
                          "items": {"type": "object", "properties": {
                    "name": _str("клеммник: XM1"),
                    "source": _str("откуда минус: -X0.3:1M"),
                    "source_ref": _str("ссылка вручную"),
                    "source_wire": WIRE,
                    "taps": {"type": "array", "items": {"type": "object", "properties": {
                        "clamp": _str("клемма: M1"),
                        "up": {"type": "boolean", "description": "отвод вверх (иначе вниз)"},
                        "wire": WIRE,
                        "link": _str("куда: -ES1:V-, -A1:A9"),
                        "ref": _str("ссылка вручную")}}}}}}}},
            "feeders": {"type": "array", "description": "Лист «Отходящие линии 230 В»",
                        "items": {"type": "object", "properties": {
                "tag": _str("автомат: -QF1"),
                "kind": {"type": "string", "enum": ["авдт", "ав"],
                         "description": "авдт — диф.автомат 1P+N, ав — автомат 1P"},
                "rating": _str("номинал: 20A 'C'"), "leak": _str("ток утечки: 30мА"),
                "section": _str("сечение проводов, мм²: 2,5"),
                "source": _str("откуда фаза: -QS1:8"), "source_ref": _str("ссылка вручную"),
                "n_source": _str("откуда нейтраль: -XN:N1"), "n_ref": _str("ссылка вручную"),
                "terminal": _str("клеммник L/N/PE: X1"), "cable": _str("кабель: W1LR1"),
                "cable_type": _str("марка кабеля: FLEXICORE 130H-нг(A)-HF"),
                "cable_cores": _str("жилы: 3G2,5"), "zone": _str("зона/место: +ZM"),
                "sockets": {"type": "array", "items": {"type": "string"},
                            "description": "розетки гирляндой: 1XS1, 1XS2 …"},
                "socket_rating": _str("номинал розеток: 16 A"),
                "load_links": {"type": "array", "items": {"type": "string"},
                               "description": "если не розетки: куда L, N, PE (стрелки)"},
                "load_ref": _str("ссылка нагрузки"),
                "caption": _str("подпись: «Питание лазера … (поток 1)»")}}},
            "remove_feeders": {"type": "array", "items": {"type": "string"},
                               "description": "обозначения линий (автоматов), которые удалить"},
            "remove_power24_groups": {"type": "array", "items": {"type": "string"},
                                      "description": "имена групп автоматов / шин минусов, "
                                                     "которые удалить"},
            "remove_terminal_blocks": {"type": "array", "items": {"type": "string"},
                                       "description": "имена клеммников, которые удалить"},
            "remove_plc_modules": {"type": "array", "items": {"type": "string"},
                                   "description": "key модулей ПЛК, которые удалить"},
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

SECTIONS = ("project", "spec", "terminals", "plc", "power24", "feeders")


class AssistantError(Exception):
    pass


# Разделы разбираются параллельно отдельными запросами: полный проект шкафа не
# помещается в один ответ модели.
GROUPS = [("project", "spec"), ("terminals",), ("plc",), ("power24", "feeders")]
GROUP_NAMES = {"project": "реквизиты проекта", "spec": "спецификация",
               "terminals": "клеммники", "plc": "модули ПЛК и каналы",
               "power24": "распределение питания 24 В (автоматы QFU, шина минусов)",
               "feeders": "отходящие линии 230 В (QF, клеммы, кабели, розетки)"}


def _tool_for(sections) -> dict:
    props = TOOL["input_schema"]["properties"]
    extra = {"terminals": ["remove_terminal_blocks"], "plc": ["remove_plc_modules"],
             "power24": ["remove_power24_groups"], "feeders": ["remove_feeders"]}
    keep = ["summary", "questions", *sections, *[x for s in sections for x in extra.get(s, [])]]
    return {"name": "save_project", "description": TOOL["description"],
            "input_schema": {"type": "object", "required": ["summary"],
                             "properties": {k: props[k] for k in keep}}}


def _unwrap(out: dict) -> dict:
    """Модель иногда вкладывает разделы внутрь project: {"project": {"project": …,
    "spec": […]}}. Поднимаем их на верхний уровень."""
    pr = out.get("project")
    if isinstance(pr, dict) and any(k in pr for k in SECTIONS + ("summary", "questions")):
        out = dict(out)
        inner = pr
        out["project"] = inner.get("project") if isinstance(inner.get("project"), dict) else {
            k: v for k, v in inner.items() if k not in SECTIONS + ("summary", "questions")}
        for k in ("spec", "terminals", "plc", "summary", "questions"):
            if k in inner and not out.get(k):
                out[k] = inner[k]
    return out


def _call(api_key, current, message, sections, model, url, timeout) -> dict:
    names = ", ".join(GROUP_NAMES[s] for s in sections)
    ctx = {k: current.get(k) for k in ("project", *sections) if current.get(k)}
    user = ("Текущий проект (JSON, только нужные разделы):\n"
            + json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
            + "\n\nСообщение пользователя:\n" + message
            + f"\n\nВ ЭТОМ запросе обрабатывай только: {names}. Другие разделы "
              "разбираются отдельно — не упоминай их ни в summary, ни в questions. "
              "Если в сообщении нет ничего для этих разделов — не присылай их, "
              "summary оставь пустым.")
    body = {
        "model": model,
        "max_tokens": 32000,
        "system": SYSTEM,
        "tools": [_tool_for(sections)],
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
    if res.get("stop_reason") == "max_tokens":
        raise AssistantError(f"Раздел «{names}» получился слишком большим для одного "
                             "ответа модели — пришлите описание этого раздела частями.")
    for block in res.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "save_project":
            out = _unwrap(block.get("input") or {})
            allowed = {"summary", "questions", *sections}
            if "terminals" in sections:
                allowed.add("remove_terminal_blocks")
            if "plc" in sections:
                allowed.add("remove_plc_modules")
            if "power24" in sections:
                allowed.add("remove_power24_groups")
            if "feeders" in sections:
                allowed.add("remove_feeders")
            return {k: v for k, v in out.items() if k in allowed}
    raise AssistantError("Модель не вернула проект, попробуйте переформулировать.")


def ask(api_key: str, current: dict, message: str, model: str = DEFAULT_MODEL,
        url: str = API_URL, timeout: float = 600) -> dict:
    """Разбирает сообщение; возвращает изменённые разделы + summary/questions."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(len(GROUPS)) as ex:
        futs = [ex.submit(_call, api_key, current, message, g, model, url, timeout)
                for g in GROUPS]
        parts = [f.result() for f in futs]      # первая ошибка пробрасывается
    result: dict = {"summary": "", "questions": []}
    for part in parts:
        for k, v in part.items():
            if k == "summary":
                if v and v.strip():
                    result["summary"] = (result["summary"] + " " + v.strip()).strip()
            elif k == "questions":
                result["questions"] += [q for q in v or [] if q and q not in result["questions"]]
            else:
                result[k] = v
    result["questions"] = result["questions"][:8]
    return result


def _mkey(m: dict) -> str:
    return str(m.get("key") or m.get("tag") or "").strip().upper()


def merge(current: dict, update: dict) -> dict:
    """Применяет правку: project — по полям, spec — целиком, клеммники и модули
    ПЛК — поштучно (по имени / key), удаление — явными списками."""
    out = {k: current.get(k) for k in SECTIONS}
    if update.get("project"):
        pr = dict(out.get("project") or {})
        pr.update({k: v for k, v in update["project"].items() if v is not None})
        out["project"] = pr
    if update.get("spec"):
        out["spec"] = update["spec"]
    for sec, key, rm in (("terminals", lambda b: str(b.get("name", "")).strip().upper(),
                          "remove_terminal_blocks"),
                         ("plc", _mkey, "remove_plc_modules"),
                         ("feeders", lambda f: str(f.get("tag", "")).strip().lstrip("-").upper(),
                          "remove_feeders")):
        items = list(out.get(sec) or [])
        remove = {str(x).strip().lstrip("-").upper() if sec == "feeders" else
                  str(x).strip().upper() for x in update.get(rm) or []}
        items = [x for x in items if key(x) not in remove]
        for new in update.get(sec) or []:
            k = key(new)
            idx = next((i for i, x in enumerate(items) if key(x) == k), None)
            if idx is None:
                items.append(new)
            else:
                items[idx] = new
        out[sec] = items
    pw_new = update.get("power24") or {}
    rm = {str(x).strip().upper() for x in update.get("remove_power24_groups") or []}
    if pw_new or rm:
        pw = dict(out.get("power24") or {})
        for part in ("groups", "minus"):
            items = [x for x in pw.get(part) or []
                     if str(x.get("name", "")).strip().upper() not in rm]
            for new in pw_new.get(part) or []:
                k = str(new.get("name", "")).strip().upper()
                idx = next((i for i, x in enumerate(items)
                            if str(x.get("name", "")).strip().upper() == k), None)
                if idx is None:
                    items.append(new)
                else:
                    items[idx] = new
            pw[part] = items
        # модель иногда кладёт в remove_power24_groups обозначение автомата — удаляем его
        for g in pw.get("groups") or []:
            g["breakers"] = [b for b in g.get("breakers") or []
                             if str(b.get("tag", "")).strip().lstrip("-").upper()
                             not in {x.lstrip("-") for x in rm}]
        out["power24"] = pw
    return out
