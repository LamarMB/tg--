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

ГЛАВНОЕ ПРАВИЛО: пользователь пишет (часто списком), ЧТО будет в шкафу. По этому
списку нужна полноценная электрическая схема, как в образце шкафа 2196.
• Всё названное оборудование и сигналы должны попасть в проект.
• То, без чего названное не заработает, но пользователь не расписал, достраивай
  сам по типовому решению: распределение сигналов по выводам ПЛК, клеммники и клеммы
  для полевых устройств (1XT1, 1XT2 …), промежуточные реле для колонны/зуммера,
  автоматы питания 24 В по потребителям и шину минусов XM1, ввод 230 В (X0, QS1,
  шина N, автомат БП), марки проводов, ссылки.
• КАЖДОЕ такое своё решение, которое заказчик может захотеть иначе, внеси в confirm:
  key — обозначение элемента на схеме («-A1:B3» для вывода модуля, «-1QFU2»,
  «1XT1», «-K1»), text — коротко, что принял («датчик уровня — на A1:B3, питание
  от 1QFU2»). Однотипное объединяй в один пункт. Не больше 8 пунктов. Не повторяй
  одно и то же допущение в разных пунктах и не противоречь сам себе.
• Не добавляй оборудование, которого нет в списке и которое не нужно для работы
  названного (другие датчики, насосы, отбраковщики …).
• questions — только то, без чего схему нарисовать нельзя (не больше 5 пунктов).
  Про артикулы и производителей спрашивай ОДНИМ общим пунктом.
• Исполнитель (contractor), если не назван, — ООО "ВЕКАС".
• Ссылайся только на устройства, которые есть в этом проекте: обозначения из
  образца (KBF1, 1KK1, CPW …) не переноси, если их нет в списке.
• Типовое решение (как в образце 2196):
  – ПЛК: каждый названный модуль — отдельный модуль в plc с тем типом, что назван
    (CPU AM521-0808TN; A1 GL20-1600END входы; A2 GL20-0016ETP выходы; модули
    нумеруются A1, A2 … в порядке перечисления). Встроенные входы CPU — быстрые
    сигналы (энкодеры A/B) и сигналы БП/ИБП; остальные входы — на модули входов.
    Встроенные выходы CPU — колонна, зуммер через реле K1…; выходы к внешним
    устройствам (триггер камеры, останов, команды) — на модули выходов.
  – Триггер, команда, останов, подсветка, колонна, зуммер — это ВЫХОДЫ; датчики,
    кнопки, сигналы «готов/ошибка/факт» — ВХОДЫ.
  – 24 В: БП U1 от автомата 230 В; ИБП 24 В DC питается от выходов БП, батарея GB1
    — от ИБП; от ИБП — шина автоматов QFU по потребителям и шина минусов XM1.
• Если в тексте только реквизиты — заполни project и спроси, что будет в шкафу.

ПРАВИЛА
1. Никогда не придумывай артикулы, производителей, фамилии и даты — оставляй пустыми.
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
   spec — только изменённые строки (с их номером n из текущей спецификации) и новые
     строки (n = null); удалённые строки — номера в remove_spec_rows;
   terminals — только изменённые/новые клеммники, каждый целиком (все строки);
     удалённые клеммники перечисли в remove_terminal_blocks;
   plc — только изменённые/новые модули, каждый целиком (все каналы, как были, с
     правкой); удалённые модули перечисли в remove_plc_modules (по key).
   Неизменённое не присылай.
4. Спецификация (spec) описывает ВСЕ изделия шкафа: если в сообщении добавлено,
   удалено или изменено изделие любого листа (автомат, лампа, реле, БП, модуль …) —
   отрази это в spec, даже когда запрос обрабатывает только spec. Правка одного изделия из общей строки (напр. «1QFU6 на 6А» при
   строке «1QFU6;2QFU3;2QFU6 … 4А, 3 шт») — убери его обозначение из общей строки и
   уменьши её количество, а для него заведи отдельную строку. Остальные изделия
   общей строки не меняются. Если изделие удалено из схемы — убери его и из спецификации.
   Одна строка — одна позиция; designation — обозначения через «;»
   (напр. «QF1;QF2») или диапазоном «1K1...1K4»; qty — число строкой.
5. Клеммы (terminals): клеммник должен содержать ровно те клеммы, на которые
   ссылаются link/feed/common в других разделах («-1XT1:6» → клемма 6 в 1XT1) — номера
   бери оттуда, свои не придумывай; допущение по клеммам уже внесено в confirm
   разделом ПЛК — не дублируй его. Блок = клеммник; строка = клемма или крышка. label — надпись
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
   link: точка подключения («-1XT1:1», «-U1:DC OK»). Если пользователь её не назвал —
   для полевого устройства назначь клемму клеммника по порядку (и внеси в confirm);
   для внешнего шкафа/устройства пиши только его («+1KK1», «-UPS»). Не сочиняй имена
   сигналов вроде «:BOSCH1_RDY».
   Выход, который идёт на промежуточное реле / колонну через реле, — element
   «катушка» с device реле (-K1); реле только для сопряжения — тоже катушка.
   Если обозначение реле/кнопки/лампы не названо — назначь по порядку (K1, K2 …, S1,
   SB1, H1) и внеси в confirm.
   Марку провода придумывай всегда: вход «<модуль>-DI<n>» (n с 0), выход
   «<модуль>-Q<n>», общий — по клемме («XM1-M3»). Ссылки на устройства в link, feed,
   common пиши с минусом: «-1XT1:1».
6а. Питание 24 В (power24): группы автоматов на шине (groups) и шины минусов (minus).
   Автомат: tag «-1QFU1», rating «DC 1A 'C'», wire (марка «1QFU1-1», RD, 0,5), targets —
   куда идёт (до двух, «-A3:A9»), caption — назначение («Питание ПЛК»). Шина минусов:
   name «XM1», taps — отводы: clamp «M1», up (вверх/вниз), link «-ES1:V-».
   Вводной клеммник (inputs, name «X0.3»): клеммы с источником сверху и feed — какую
   группу / шину минусов клемма питает; пришли inputs целиком, если его меняешь.
   Правка: присылай изменённую группу / шину целиком (все автоматы / отводы). Чтобы
   убрать один автомат — пришли его группу целиком без него. remove_power24_groups —
   только для удаления группы или шины целиком. Ссылки «лист.столбец» не выдумывай — программа ставит их сама.
6б. Отходящие линии 230 В (feeders): линия = автомат (tag -QF1, kind авдт/ав, rating,
   leak), источник фазы (source -QS1:8) и нейтрали (n_source -XN:N1), клеммник, кабель,
   далее розетки (sockets) или стрелки к нагрузке (load_links: L, N, PE), caption.
   Правка: присылай изменённую линию целиком; удалённые — в remove_feeders.
   Линия на feeders — для потребителей ВНЕ шкафа (принтер, лазер, чиллер …) с
   клеммником и кабелем. Не дублируй то, что уже нарисовано ветвью на листе ввода.
6в. Ввод и питание 230 В (mains): клеммник ввода (input_block X0, input_labels), кабель
   ввода, выключатель-разъединитель (qs QS1, qs_rating 40A, qs_poles), выходы QS
   (qs_outputs: pole 2/4/6/8, link «шина» — общая шина автоматов ветвей, «N» — на шину
   нейтрали, иначе точка -QF1:1), шина нейтрали (n_bus XN, n_taps: clamp N1, link),
   ветви от шины (branches: автомат tag -SF1, rating 6A 'C', load — розетка / лампа /
   термостат (+ вентилятор в load_tag2/load_param2) / светильник / устройство /
   стрелка (link), load_tag, load_param, n_link — откуда N нагрузки, -XN:N2),
   устройства с выводами (devices: tag -U1/-UPS/-GB1, title, param, pins: name, top,
   link, wire). Устройство, питаемое от ветви (load «устройство»), имеет тот же tag,
   что load_tag ветви. Правка: присылай только изменённые поля и элементы — ветвь,
   устройство, выход QS, отвод N — каждый целиком; удалённые — в remove_mains_items
   (обозначение автомата/устройства, «QS:4» для выхода, «N:N3» для отвода).
   Ветви mains — только нагрузки внутри шкафа (розетка шкафа, вентилятор, свет, БП).
   Потребители вне шкафа — отходящие линии feeders: на листе ввода для них только
   стрелка к их автомату («стрелка», link -QF1:1) или выход QS.
6г. Сеть (network): устройства (devices: tag -ES2/-PC1/-CPU/-OP1, name — модель,
   brand moxa/inovance/ifc или пусто, row top/bottom — верхний/нижний ряд, ports: name
   (1, 2, LAN A, HDMI, USB3.0 1), kind rj45/lan/usb/usb2/hdmi, side top/bottom; power:
   pin V+/V-/+24V/0V, link -1QFU2:1, wire; pe; modules — «A1 GL20-1600END /8.0») и
   кабели (links: cable W001, cable_type «S/FTP, CAT6A», length «1 м», a «-ES2:1»,
   b — второй конец на листе «-PC1:LAN A», либо наружу: socket XETH1 (socket_kind
   RJ45 / USB A), zone +1KK1/+ZM, remote «+1KK1-XETH1:RJ45», remote_ref, remote_cable
   WET-1CM1, remote_cable_type, target -1PR1 + target_title «Принтер» + target_port P1).
   Правка: устройство или кабель целиком; удалённые — в remove_network_items (tag / кабель).
6д. Коробки и внешние шкафы (fields): список зон (n — номер зоны в текущем проекте,
   zone +1KK1/+ZM, groups). Группа = клеммник шкафа (block 1XT1) с полевым кабелем
   (cable WIO-1ENC1, cable_ref, cable_type, shield — экран на -XSH, pe, paired — реле на
   парах клемм, remote_device -CC_CPW — если удалённый конец — выводы устройства) и
   клеммами (terms: clamp, core — жила, remote — «+1KK1-XT1:L+» или вывод устройства,
   remote_ref, dir in — из поля в шкаф / out — из шкафа в поле, wire, element — пусто /
   «катушка» / «контакт» / «ттр» (на этой и следующей клемме), device -1K3, param,
   link — куда в шкафу (-CPU:A1, -2QFU1:1), caption — подпись внизу, bridge).
   Правка: присылай зону с n и изменённые группы целиком; удалённые группы —
   remove_field_groups «n:1XT3».
6е. Сигнальная колонна (column): tag -HL1, title, feed_wire, feed_next (-1K1:13+),
   lamps: pin 1…, color GN/YL/RD/BZ, kind лампа/зуммер, relay -K1 (катушка на выходе ПЛК),
   wire, при цепи через перекидной контакт другого реле — relay_wire, via -KBF1,
   via_pins «11/14/12»; common_pin 0, common_link -XM1:M3, common_wire.
   Правка: присылай колонну целиком.
7. Открытые пункты. Если в запросе перечислены открытые пункты (вопросы и допущения
   с номерами), сообщение пользователя может быть ответом на них («1 да», «3 — реле
   на 230 В», «всё ок»). Внеси изменения по ответу, номера закрытых пунктов верни в
   resolved («да», «ок», «согласен» — просто закрыть). Не повторяй закрытое в confirm.
8. summary — 1–3 предложения по-русски: только что именно изменено/добавлено.
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
            "confirm": {"type": "array", "description": "твои допущения на подтверждение",
                        "items": {"type": "object", "properties": {
                            "key": _str("обозначение на схеме: -A1:B3, -1QFU2, 1XT1, -K1"),
                            "text": _str("что принято, коротко")}}},
            "resolved": {"type": "array", "items": {"type": "integer"},
                         "description": "номера открытых пунктов, закрытых этим ответом"},
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
                "n": {"type": ["integer", "null"],
                      "description": "номер строки текущей спецификации, которую эта строка "
                                     "заменяет; для новой строки — null"},
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
                        "ref": _str("ссылка вручную")}}}}}},
                "inputs": {"type": "array",
                           "description": "вводной клеммник над автоматами (-X0.3)",
                           "items": {"type": "object", "properties": {
                    "name": _str("клеммник: X0.3"),
                    "note": _str("пояснение справа (необязательно)"),
                    "clamps": {"type": "array", "items": {"type": "object", "properties": {
                        "name": _str("клемма: 1L+, 1M"),
                        "source": _str("откуда питание сверху: -UPS:Output DC 24V:+"),
                        "source_ref": _str("ссылка вручную"),
                        "source_wire": WIRE,
                        "wire": WIRE,
                        "feed": _str("куда провод: группа «1», шина «XM1» или «XM1:M7»"),
                        "jumper": _str("пунктирная перемычка на клемму (запасной ввод): 1L+")
                    }}}}}}}},
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
            "mains": {"type": "object", "description": "Лист «Ввод и питание 230 В»",
                      "properties": {
                "input_block": _str("клеммник ввода: X0"),
                "input_labels": {"type": "array", "items": {"type": "string"},
                                 "description": "клеммы ввода: L1, L2, L3, N, PE"},
                "input_from": _str("откуда ввод: -ШР"),
                "input_cable": _str("кабель ввода: W1E-001"),
                "input_cable_type": _str("марка кабеля: FLEXICORE 130H-нг(A)-HF 5G2,5"),
                "qs": _str("выключатель-разъединитель: QS1"), "qs_rating": _str("40A"),
                "qs_poles": {"type": "integer", "description": "число полюсов QS"},
                "qs_outputs": {"type": "array", "items": {"type": "object", "properties": {
                    "pole": _str("вывод QS: 2, 4, 6, 8"),
                    "link": _str("«шина», «N» или точка: -QF1:1"),
                    "ref": _str("ссылка вручную"), "wire": WIRE}}},
                "n_bus": _str("шина нейтрали: XN"),
                "n_taps": {"type": "array", "items": {"type": "object", "properties": {
                    "clamp": _str("N1"), "link": _str("-QF1:N1"), "ref": _str("ссылка вручную"),
                    "wire": WIRE}}},
                "branches": {"type": "array", "items": {"type": "object", "properties": {
                    "tag": _str("автомат: -SF1 (пусто — без автомата)"),
                    "rating": _str("номинал АВТОМАТА ветви: 6A 'C' («SF1 на 10А» — сюда)"),
                    "wire": WIRE,
                    "load": {"type": "string", "enum": ["розетка", "лампа", "термостат",
                                                        "светильник", "устройство", "стрелка"]},
                    "load_tag": _str("-XS1, -H1, -TR1, -EA1, -U1"),
                    "load_param": _str("параметр НАГРУЗКИ (не автомата): номинал розетки "
                                       "16 A, лампа AC230V Белая, -10..+80°C, 5 Вт"),
                    "load_tag2": _str("вентилятор при термостате: -EC1"),
                    "load_param2": _str("100м3/ч, 230VAC"),
                    "n_link": _str("нейтраль нагрузки: -XN:N2"),
                    "link": _str("для стрелки: куда, -QF3:1"), "ref": _str("ссылка вручную")}}},
                "devices": {"type": "array", "items": {"type": "object", "properties": {
                    "tag": _str("-U1, -UPS, -GB1"), "title": _str("надпись в блоке"),
                    "param": _str("10 A"),
                    "pins": {"type": "array", "items": {"type": "object", "properties": {
                        "name": _str("вывод: L, N, V+, 11"),
                        "top": {"type": "boolean", "description": "вывод сверху блока"},
                        "link": _str("куда провод: -X0.3:1L+"), "ref": _str("ссылка вручную"),
                        "wire": WIRE}}}}}}}},
            "network": {"type": "object", "description": "Лист «Сеть»", "properties": {
                "devices": {"type": "array", "items": {"type": "object", "properties": {
                    "tag": _str("-ES2, -PC1, -CPU"), "name": _str("модель: EDS-208"),
                    "brand": _str("логотип: moxa / inovance / ifc / пусто"),
                    "row": {"type": "string", "enum": ["top", "bottom"]},
                    "ref": _str("ссылка на подробный лист: /6.1"),
                    "pe": {"type": "boolean"},
                    "modules": {"type": "array", "items": {"type": "string"},
                                "description": "модули рядом: «A1 GL20-1600END /8.0»"},
                    "ports": {"type": "array", "items": {"type": "object", "properties": {
                        "name": _str("1, LAN A, HDMI, USB3.0 1"),
                        "kind": {"type": "string", "enum": ["rj45", "lan", "usb", "usb2", "hdmi"]},
                        "side": {"type": "string", "enum": ["top", "bottom"]}}}},
                    "power": {"type": "array", "items": {"type": "object", "properties": {
                        "pin": _str("V+, V-, +24V, 0V"), "link": _str("-1QFU2:1"),
                        "ref": _str("ссылка вручную"), "wire": WIRE}}}}}},
                "links": {"type": "array", "items": {"type": "object", "properties": {
                    "cable": _str("W001"), "cable_type": _str("S/FTP, CAT6A"),
                    "length": _str("1 м"), "a": _str("-ES2:1"),
                    "b": _str("второй конец на листе: -PC1:LAN A"),
                    "socket": _str("панельный разъём: XETH1"), "socket_kind": _str("RJ45 / USB A"),
                    "zone": _str("+1KK1 / +ZM"), "remote": _str("+1KK1-XETH1:RJ45"),
                    "remote_ref": _str("+1KK1/3.1"), "remote_cable": _str("WET-1CM1"),
                    "remote_cable_type": _str("F/UTP CAT6"), "target": _str("-1PR1"),
                    "target_title": _str("Принтер"), "target_port": _str("P1"),
                    "note": _str("примечание")}}}}},
            "fields": {"type": "array", "description": "Листы коробок / внешних шкафов",
                       "items": {"type": "object", "properties": {
                "n": {"type": ["integer", "null"], "description": "номер зоны в текущем проекте"},
                "zone": _str("+1KK1 / +ZM"), "sheet": _str("номер листа (обычно пусто)"),
                "groups": {"type": "array", "items": {"type": "object", "properties": {
                    "block": _str("клеммник: 1XT1"), "cable": _str("WIO-1ENC1"),
                    "cable_ref": _str("+1KK1/2.0"), "cable_type": _str("FLEXICORE 135 CH 7G0,75"),
                    "shield": {"type": "boolean"}, "pe": {"type": "boolean"},
                    "paired": {"type": "boolean"}, "remote_device": _str("-CC_CPW"),
                    "terms": {"type": "array", "items": {"type": "object", "properties": {
                        "clamp": _str("L+, M, 1"), "core": _str("жила"),
                        "remote": _str("+1KK1-XT1:L+ или вывод устройства"),
                        "remote_ref": _str("+1KK1/2.0"),
                        "dir": {"type": "string", "enum": ["in", "out"]},
                        "wire": WIRE,
                        "element": {"type": "string", "enum": ["", "катушка", "контакт", "ттр"]},
                        "device": _str("-1K3"), "param": _str("=24В"),
                        "link": _str("-CPU:A1, -2QFU1:1"), "ref": _str("ссылка вручную"),
                        "caption": _str("подпись внизу, строки через \\n"),
                        "bridge": _str("перемычка")}}}}}}}}},
            "column": {"type": "object", "description": "Сигнальная колонна под выходами ПЛК",
                       "properties": {
                "tag": _str("-HL1"), "title": _str("Сигнальная колонна"), "feed_wire": WIRE,
                "feed_next": _str("-1K1:13+"), "feed_next_ref": _str("ссылка вручную"),
                "common_pin": _str("0"), "common_link": _str("-XM1:M3"),
                "common_ref": _str("ссылка вручную"), "common_wire": WIRE,
                "lamps": {"type": "array", "items": {"type": "object", "properties": {
                    "pin": _str("1"), "color": _str("GN / YL / RD / BZ"),
                    "kind": {"type": "string", "enum": ["лампа", "зуммер"]},
                    "relay": _str("-K1"), "wire": WIRE, "relay_wire": WIRE,
                    "via": _str("-KBF1"), "via_pins": _str("11/14/12"),
                    "via_ref": _str("ссылка вручную")}}}}},
            "remove_field_groups": {"type": "array", "items": {"type": "string"},
                                    "description": "«n:клеммник» — группы, которые удалить"},
            "remove_network_items": {"type": "array", "items": {"type": "string"},
                                     "description": "устройства (-ES2) или кабели (W001) удалить"},
            "remove_mains_items": {"type": "array", "items": {"type": "string"},
                                   "description": "что удалить с листа ввода: -SF2, -UPS, "
                                                  "QS:4, N:N3"},
            "remove_spec_rows": {"type": "array", "items": {"type": "integer"},
                                 "description": "номера (n) строк спецификации, которые удалить"},
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

SECTIONS = ("project", "spec", "terminals", "plc", "power24", "feeders", "mains", "network",
            "fields", "column")


class AssistantError(Exception):
    pass


# Разделы разбираются параллельно отдельными запросами: полный проект шкафа не
# помещается в один ответ модели.
GROUPS = [("project", "spec"), ("terminals",), ("plc",), ("power24", "feeders"),
          ("mains",), ("network",), ("fields",), ("column",)]   # см. STAGES — порядок разбора
GROUP_NAMES = {"project": "реквизиты проекта", "spec": "спецификация",
               "terminals": "клеммники", "plc": "модули ПЛК и каналы",
               "power24": "распределение питания 24 В (автоматы QFU, шина минусов)",
               "feeders": "отходящие линии 230 В (QF, клеммы, кабели, розетки)",
               "mains": "ввод и питание 230 В (X0, QS1, шина N, автоматы SF с нагрузками, "
                        "БП, ИБП, батарея)",
               "network": "сеть: коммутаторы, ПК, панель, кабели Ethernet/USB/HDMI, "
                          "панельные разъёмы",
               "fields": "коробки и внешние шкафы: полевые кабели, клеммники 1XT/2XT/3XT, "
                         "реле CPW",
               "column": "сигнальная колонна HL1 (лампы, зуммер, реле K1…)"}


def _tool_for(sections) -> dict:
    props = TOOL["input_schema"]["properties"]
    extra = {"spec": ["remove_spec_rows"], "terminals": ["remove_terminal_blocks"], "plc": ["remove_plc_modules"],
             "power24": ["remove_power24_groups"], "feeders": ["remove_feeders"],
             "mains": ["remove_mains_items"], "network": ["remove_network_items"],
             "fields": ["remove_field_groups"]}
    keep = ["summary", "questions", "confirm", "resolved", *sections, *[x for s in sections for x in extra.get(s, [])]]
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


def _call(api_key, current, message, sections, model, url, timeout,
          open_items=None) -> dict:
    names = ", ".join(GROUP_NAMES[s] for s in sections)
    ctx = {k: current.get(k) for k in ("project", *sections) if current.get(k)}
    if ctx.get("fields"):                     # номера зон — чтобы править поштучно
        ctx["fields"] = [{"n": i, **a} for i, a in enumerate(ctx["fields"], 1)]
    if ctx.get("spec"):                       # номера строк — чтобы править поштучно
        ctx["spec"] = [{"n": i, **row} for i, row in enumerate(ctx["spec"], 1)]
    ref = {k: current.get(k) for k in SECTIONS
           if k not in ctx and k not in ("project", "spec") and current.get(k)}
    user = "Текущий проект (JSON, разделы этого запроса):\n" \
        + json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
    if ref:
        user += ("\n\nДругие разделы проекта — только для согласованности обозначений, "
                 "клемм и ссылок (их не присылай и не меняй):\n"
                 + json.dumps(ref, ensure_ascii=False, separators=(",", ":")))
    if open_items:
        user += "\n\nОткрытые пункты на согласовании:\n" + "\n".join(
            f"{o['n']}. {('[' + o['key'] + '] ') if o.get('key') else ''}{o['text']}"
            for o in open_items)
    user += ("\n\nСообщение пользователя:\n" + message
             + f"\n\nВ ЭТОМ запросе обрабатывай только: {names}. Другие разделы "
               "разбираются отдельно — не упоминай их ни в summary, ни в questions, ни в "
               "confirm. Если в сообщении нет ничего для этих разделов — не присылай их, "
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
            allowed = {"summary", "questions", "confirm", "resolved", *sections}
            if "spec" in sections:
                allowed.add("remove_spec_rows")
            if "terminals" in sections:
                allowed.add("remove_terminal_blocks")
            if "plc" in sections:
                allowed.add("remove_plc_modules")
            if "power24" in sections:
                allowed.add("remove_power24_groups")
            if "feeders" in sections:
                allowed.add("remove_feeders")
            if "mains" in sections:
                allowed.add("remove_mains_items")
            if "network" in sections:
                allowed.add("remove_network_items")
            if "fields" in sections:
                allowed.add("remove_field_groups")
            return {k: v for k, v in out.items() if k in allowed}
    raise AssistantError("Модель не вернула проект, попробуйте переформулировать.")


# Порядок разбора: сначала ПЛК, потом питание (зная, что нужно запитать), потом
# клеммники и спецификация (зная всё остальное). Внутри этапа — параллельно.
STAGES = [[("plc",)], [("mains",), ("network",), ("fields",), ("column",)],
          [("power24", "feeders")],
          [("project", "spec"), ("terminals",)]]


def ask(api_key: str, current: dict, message: str, model: str = DEFAULT_MODEL,
        url: str = API_URL, timeout: float = 600, open_items=None) -> dict:
    """Разбирает сообщение; возвращает изменённые разделы + summary/questions/
    confirm (допущения на подтверждение)/resolved (закрытые открытые пункты)."""
    from concurrent.futures import ThreadPoolExecutor
    result: dict = {"summary": "", "questions": [], "confirm": [], "resolved": []}
    work = dict(current or {})
    for stage in STAGES:
        with ThreadPoolExecutor(len(stage)) as ex:
            futs = [ex.submit(_call, api_key, work, message, g, model, url, timeout,
                              open_items) for g in stage]
            parts = [f.result() for f in futs]      # первая ошибка пробрасывается
        for part in parts:
            if not any(v for k, v in part.items()
                       if k not in ("summary", "questions", "confirm", "resolved")):
                # группе нечего менять — её рассуждения не нужны, закрытые пункты — нужны
                result["resolved"] += [x for x in part.get("resolved") or []
                                       if isinstance(x, int)]
                continue
            for k, v in part.items():
                if k == "summary":
                    if v and v.strip():
                        result["summary"] = (result["summary"] + " " + v.strip()).strip()
                elif k == "questions":
                    result["questions"] += [q for q in v or [] if q
                                            and q not in result["questions"]]
                elif k == "confirm":
                    result["confirm"] += [c for c in v or [] if isinstance(c, dict)
                                          and str(c.get("text") or "").strip()]
                elif k == "resolved":
                    result["resolved"] += [x for x in v or [] if isinstance(x, int)]
                else:
                    result[k] = v
            work = merge(work, {k: v for k, v in part.items()
                                if k not in ("summary", "questions", "confirm", "resolved")})
    _guard_articles(result, current or {}, message)
    result["questions"] = result["questions"][:8]
    result["confirm"] = result["confirm"][:12]
    return result


def _guard_articles(result: dict, current: dict, message: str) -> None:
    """Артикул, которого нет ни в текущей спецификации, ни в сообщении, модель
    придумала «по аналогии» — убираем и спрашиваем."""
    known = {str(r.get("article") or "").strip().upper() for r in current.get("spec") or []}
    text = message.upper()
    for r in result.get("spec") or []:
        a = str(r.get("article") or "").strip()
        if a and a.upper() not in known and a.upper() not in text:
            r["article"] = ""
            q = f"Артикул для {r.get('designation') or r.get('name', '')[:40]} — назовите " \
                f"(«{a}» не подставил: его нет в проекте и в сообщении)."
            result["questions"].insert(0, q)


def _mkey(m: dict) -> str:
    return str(m.get("key") or m.get("tag") or "").strip().upper()


def merge(current: dict, update: dict) -> dict:
    """Применяет правку: project — по полям, spec — целиком, клеммники и модули
    ПЛК — поштучно (по имени / key), удаление — явными списками."""
    out = {k: current.get(k) for k in SECTIONS}
    if current.get("frozen"):
        out["frozen"] = current["frozen"]             # листы-шаблоны образца — как были
    if update.get("project"):
        pr = dict(out.get("project") or {})
        pr.update({k: v for k, v in update["project"].items() if v is not None})
        out["project"] = pr
    if update.get("spec") or update.get("remove_spec_rows"):
        out["spec"] = _merge_spec(list(out.get("spec") or []), update.get("spec") or [],
                                  update.get("remove_spec_rows") or [])
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
                if sec == "plc" and items[idx].get("layout") and not new.get("layout"):
                    new = {**new, "layout": items[idx]["layout"]}   # положение выводов — как было
                items[idx] = new
        out[sec] = items
    pw_new = update.get("power24") or {}
    rm = {str(x).strip().upper() for x in update.get("remove_power24_groups") or []}
    if pw_new or rm:
        pw = dict(out.get("power24") or {})
        if pw_new.get("inputs"):
            pw["inputs"] = pw_new["inputs"]
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
                    if items[idx].get("layout") and not new.get("layout"):
                        new = {**new, "layout": items[idx]["layout"]}   # подгонка под образец
                    items[idx] = new
            pw[part] = items
        # модель иногда кладёт в remove_power24_groups обозначение автомата — удаляем его
        for g in pw.get("groups") or []:
            g["breakers"] = [b for b in g.get("breakers") or []
                             if str(b.get("tag", "")).strip().lstrip("-").upper()
                             not in {x.lstrip("-") for x in rm}]
        out["power24"] = pw
    nw = update.get("network") or {}
    rmn = {_u(x) for x in update.get("remove_network_items") or []}
    if nw or rmn:
        net = dict(out.get("network") or {})
        for part, key in (("devices", lambda d: _u(d.get("tag"))),
                          ("links", lambda l: _u(l.get("cable")))):
            items = [x for x in net.get(part) or [] if key(x) not in rmn]
            for n in nw.get(part) or []:
                k = key(n)
                idx = next((i for i, x in enumerate(items) if key(x) == k), None)
                if idx is None:
                    items.append(n)
                else:
                    items[idx] = n
            net[part] = items
        out["network"] = net
    if update.get("column"):
        out["column"] = update["column"]
    fl = update.get("fields") or []
    rmf = {str(x).strip().upper() for x in update.get("remove_field_groups") or []}
    if fl or rmf:
        areas = [dict(a) for a in out.get("fields") or []]
        for i, a in enumerate(areas, 1):
            a["groups"] = [g for g in a.get("groups") or []
                           if f"{i}:{_u(g.get('block'))}" not in rmf]
        for a in fl:
            a = dict(a)
            try:
                n = int(a.pop("n", None) or 0)
            except (TypeError, ValueError):
                n = 0
            if 1 <= n <= len(areas):
                cur = areas[n - 1]
                groups = list(cur.get("groups") or [])
                for g in a.get("groups") or []:
                    k = _u(g.get("block"))
                    idx = next((j for j, x in enumerate(groups) if _u(x.get("block")) == k), None)
                    if idx is None:
                        groups.append(g)
                    else:
                        groups[idx] = g
                cur["groups"] = groups
                for key in ("zone", "sheet"):
                    if a.get(key):
                        cur[key] = a[key]
            else:
                areas.append(a)
        out["fields"] = [a for a in areas if a.get("groups")]
    mn = update.get("mains") or {}
    rm = {str(x).strip().lstrip("-").upper() for x in update.get("remove_mains_items") or []}
    if mn or rm:
        out["mains"] = _merge_mains(dict(out.get("mains") or {}), mn, rm)
    return out


def _merge_spec(cur: list, new: list, remove: list) -> list:
    """Строки с номером n заменяют строку n текущей спецификации, без номера —
    добавляются после последней строки с похожим обозначением (или в конец)."""
    def num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    def looks_full():
        """Модель прислала весь список заново (без номеров, с почти всеми строками)."""
        if remove or any(r.get("n") not in (None, "") for r in new):
            return False
        have = {str(r.get("designation", "")).strip().upper() for r in new}
        old_d = [str(r.get("designation", "")).strip().upper() for r in cur]
        return len(new) >= len(cur) and sum(d in have for d in old_d) >= 0.8 * len(old_d)
    if not cur or looks_full():
        # новый проект или модель прислала весь список заново
        return [{k: v for k, v in r.items() if k != "n"} for r in new]
    rows = [dict(r) for r in cur]
    slots: list = [[r] for r in rows]          # на месте строки i — одна или несколько
    rm = {num(x) for x in remove} - {None}
    tail = []
    for r in new:
        r = dict(r)
        n = num(r.pop("n", None))
        if n is not None and 1 <= n <= len(rows):
            if n in rm:
                rm.discard(n)
            if slots[n - 1] and slots[n - 1][0] is rows[n - 1]:
                slots[n - 1][0] = r
            else:
                slots[n - 1].append(r)
        else:
            tail.append(r)
    for n in rm:
        if 1 <= n <= len(rows):
            slots[n - 1] = [x for x in slots[n - 1] if x is not rows[n - 1]]
    out = [r for sl in slots for r in sl]
    for r in tail:                             # новую строку ставим рядом с «родственной»
        pref = str(r.get("designation", "")).split(";")[0].rstrip("0123456789.").upper()
        idx = max((i for i, x in enumerate(out) if pref and str(x.get("designation", ""))
                   .upper().startswith(pref)), default=None)
        if idx is None:
            out.append(r)
        else:
            out.insert(idx + 1, r)
    return out


def _u(v) -> str:
    return str(v or "").strip().lstrip("-").upper()


def _merge_mains(cur: dict, new: dict, rm: set) -> dict:
    """Ввод 230 В: простые поля — по одному, списки — поэлементно по ключу."""
    lists = {"qs_outputs": lambda o: "QS:" + _u(o.get("pole")),
             "n_taps": lambda t: "N:" + _u(t.get("clamp")),
             "branches": lambda b: _u(b.get("tag")) or "LOAD:" + _u(b.get("load_tag")),
             "devices": lambda d: _u(d.get("tag"))}
    for k, v in new.items():
        if k not in lists and v not in (None, "", []):
            cur[k] = v
    for part, key in lists.items():
        items = [x for x in cur.get(part) or [] if key(x) not in rm]
        for n in new.get(part) or []:
            k = key(n)
            idx = next((i for i, x in enumerate(items) if key(x) == k), None)
            if idx is None:
                items.append(n)
            else:
                items[idx] = n
        cur[part] = items
    # ветвь без автомата, удалённая по обозначению нагрузки
    cur["branches"] = [b for b in cur.get("branches") or [] if _u(b.get("load_tag")) not in rm
                       or _u(b.get("tag"))]
    return cur
