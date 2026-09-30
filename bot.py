"""Telegram-бот: принимает заполненный Excel-шаблон и возвращает PDF.

Работает на стандартной библиотеке Python (без сторонних Telegram-пакетов),
через long polling — ни белый IP, ни домен не нужны.

Настройки (переменные окружения или файл .env рядом с bot.py):
  BOT_TOKEN      — токен от @BotFather (обязательно)
  ALLOWED_USERS  — через запятую id пользователей, которым разрешён бот
                   (пусто — разрешено всем)
  TELEGRAM_API   — адрес Bot API (по умолчанию https://api.telegram.org)
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from schemgen import TemplateError, read_document, render_pdf, write_workbook
from schemgen import assistant, preview
from schemgen.jsonio import check, dict_to_doc, doc_to_dict

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "examples" / "example_2196_SS1.xlsx"
STATE_DIR = ROOT / "data"          # текущий проект каждого чата (JSON)
log = logging.getLogger("bot")

HELP = (
    "Я рисую электрическую схему шкафа (Э3) со спецификацией и клеммным планом (В4) в PDF.\n\n"
    "Напишите списком, что будет в шкафу: ПЛК и модули, датчики и сигналы, кнопки, "
    "лампы, колонна, питание 24 В и 230 В, розетки … Можно коротко — недостающее "
    "(выводы, клеммы, автоматы, провода) я дострою сам.\n\n"
    "В ответ пришлю ЧЕРНОВИК PDF: оранжевым с номером — мои допущения и вопросы, "
    "синим — что изменилось. Отвечайте текстом, можно по номерам («1 да, 3 — на "
    "B5»), — пришлю новый черновик. ✅ Принять — чистый PDF и Excel, ↩️ Отменить — "
    "откатить черновик.\n\n"
    "Ещё: /new — новый пустой проект, /base — проект из базового шаблона, "
    "/savebase — сделать текущий базовым, /project — текущий проект в Excel, "
    "/template и /example — Excel-шаблон и пример, /key sk-ant-… — ключ Claude API."
)


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def set_env_value(path: Path, name: str, value: str) -> None:
    """Записать/заменить NAME=value в файле .env."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    lines = [ln for ln in lines if not ln.strip().startswith(name + "=")]
    lines.append(f"{name}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[name] = value


class Api:
    def __init__(self, token: str, base: str):
        self.base = f"{base.rstrip('/')}/bot{token}"
        self.file_base = f"{base.rstrip('/')}/file/bot{token}"

    def call(self, method: str, params: dict | None = None, timeout: float = 70):
        data = json.dumps(params or {}).encode()
        req = urllib.request.Request(f"{self.base}/{method}", data=data,
                                     headers={"Content-Type": "application/json"})
        return self._send(req, timeout)

    def _send(self, req, timeout):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            res = json.loads(e.read() or b"{}")
        if not res.get("ok"):
            raise RuntimeError(f"Telegram API: {res.get('description', res)}")
        return res["result"]

    def download(self, file_id: str) -> bytes:
        info = self.call("getFile", {"file_id": file_id})
        with urllib.request.urlopen(f"{self.file_base}/{info['file_path']}",
                                    timeout=120) as r:
            return r.read()

    def send_document(self, chat_id: int, path: Path, filename: str,
                      caption: str = "", reply_to: int | None = None):
        boundary = uuid.uuid4().hex
        fields = {"chat_id": str(chat_id), "caption": caption}
        if reply_to:
            fields["reply_to_message_id"] = str(reply_to)
        body = bytearray()
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{k}"\r\n\r\n{v}\r\n').encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="document"; filename="{_ascii_name(filename)}"; '
                 f"filename*=UTF-8''{urllib.request.quote(filename)}\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode()
        body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.base}/sendDocument", data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return self._send(req, 120)

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None,
                     keyboard: list | None = None):
        p = {"chat_id": chat_id, "text": text[:4096]}
        if reply_to:
            p["reply_to_message_id"] = reply_to
        if keyboard:
            p["reply_markup"] = {"inline_keyboard": keyboard}
        return self.call("sendMessage", p)

    def _multipart(self, method: str, fields: dict, files: dict):
        """files: {поле: (имя_файла, bytes)}"""
        boundary = uuid.uuid4().hex
        body = bytearray()
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{k}"\r\n\r\n{v}\r\n').encode()
        for k, (fname, data) in files.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{k}"; filename="{fname}"\r\n'
                     "Content-Type: application/octet-stream\r\n\r\n").encode()
            body += data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.base}/{method}", data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return self._send(req, 120)

    def send_photos(self, chat_id: int, images: list[bytes], caption: str = ""):
        """1 картинка — sendPhoto, 2–10 — альбом."""
        if len(images) == 1:
            return self._multipart("sendPhoto", {"chat_id": chat_id, "caption": caption[:1000]},
                                   {"photo": ("page.jpg", images[0])})
        media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(images))]
        if caption:
            media[0]["caption"] = caption[:1000]
        return self._multipart("sendMediaGroup",
                               {"chat_id": chat_id, "media": json.dumps(media)},
                               {f"p{i}": (f"p{i}.jpg", b) for i, b in enumerate(images)})


def _ascii_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "document"


class Bot:
    def __init__(self, api: Api, allowed: set[int] | None = None,
                 claude_key: str = "", claude_model: str = assistant.DEFAULT_MODEL,
                 claude_url: str = assistant.API_URL, state_dir: Path = STATE_DIR):
        self.api = api
        self.allowed = allowed
        self.claude_key = claude_key
        self.claude_model = claude_model
        self.claude_model_big = os.environ.get("CLAUDE_MODEL_BIG", assistant.BIG_MODEL)
        self.claude_url = claude_url
        self.state_dir = state_dir
        self._locks: dict[int, threading.Lock] = {}
        self._pending: dict[int, dict] = {}
        self._locks_guard = threading.Lock()

    # --- состояние проекта чата -------------------------------------------
    def _state_path(self, chat: int) -> Path:
        return self.state_dir / f"{chat}.json"

    def load_state(self, chat: int) -> dict:
        p = self._state_path(chat)
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {}

    def save_state(self, chat: int, data: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path(chat).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                          encoding="utf-8")

    def _pending_path(self, chat: int) -> Path:
        return self.state_dir / f"{chat}.pending.json"

    def load_pending(self, chat: int) -> dict | None:
        p = self._pending_path(chat)
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return None

    def save_pending(self, chat: int, data: dict | None) -> None:
        p = self._pending_path(chat)
        if data is None:
            p.unlink(missing_ok=True)
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def load_base(self) -> dict:
        """Базовый проект: data/base.json, иначе — пример 2196."""
        p = self.state_dir / "base.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return doc_to_dict(read_document(EXAMPLE))

    def lock(self, chat: int) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(chat, threading.Lock())

    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            self.on_callback(update["callback_query"])
            return
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat = msg["chat"]["id"]
        user = (msg.get("from") or {}).get("id")
        mid = msg.get("message_id")
        if self.allowed and user not in self.allowed:
            self.api.send_message(chat, f"Нет доступа. Ваш id: {user} — "
                                        "попросите администратора добавить его.")
            return
        text = (msg.get("text") or "").strip()
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd in ("/start", "/help"):
            self.api.send_message(chat, HELP)
        elif cmd == "/template":
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "шаблон.xlsx"
                write_workbook(p)
                self.api.send_document(chat, p, "шаблон.xlsx",
                                       "Пустой шаблон. Заполните и пришлите мне.")
        elif cmd == "/example":
            self.api.send_document(chat, EXAMPLE, "пример_2196_СС1.xlsx",
                                   "Пример заполнения (по шкафу ВКС.АСПУ.2196.СС1).")
        elif cmd == "/key":
            self.on_key(chat, mid, user, text)
        elif cmd == "/new":
            self.save_state(chat, {})
            self.save_pending(chat, None)
            self.api.send_message(chat, "Начинаем новый пустой проект. Опишите его текстом "
                                        "или пришлите Excel. Начать с базового шаблона — /base.")
        elif cmd == "/base":
            base = self.load_base()
            self.save_state(chat, base)
            self.save_pending(chat, None)
            d = dict_to_doc(base)
            self.api.send_message(
                chat, f"Новый проект создан из базового шаблона ({d.project.code}): "
                      f"{len(d.spec)} поз. спецификации, {len(d.terminals)} клеммников, "
                      f"{len(d.plc)} модулей ПЛК.\nТеперь пишите, что поменять: «шифр "
                      "ВКС.АСПУ.2300.СС1», «вход A5 модуля A1 — датчик уровня», «убери "
                      "выход B3 модуля A4» … Каждую правку пришлю черновиком PDF с метками.")
        elif cmd == "/savebase":
            state = self.load_state(chat)
            if not state:
                self.api.send_message(chat, "Проекта нет — нечего сохранять.")
                return
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / "base.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            self.api.send_message(chat, "Текущий проект сохранён как базовый шаблон. "
                                        "Новый проект из него — /base.")
        elif cmd == "/project":
            state = self.load_state(chat)
            if not state:
                self.api.send_message(chat, "Проекта пока нет — опишите его или пришлите Excel.")
                return
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "project.xlsx"
                write_workbook(p, dict_to_doc(state))
                self.api.send_document(chat, p, self._name(dict_to_doc(state), ".xlsx"),
                                       "Текущий проект.")
        elif "document" in msg:
            self.on_document(chat, mid, msg["document"])
        elif text and not cmd:
            self.on_text(chat, mid, text)
        elif msg.get("voice") or msg.get("audio"):
            self.api.send_message(chat, "Голосовые пока не понимаю — напишите текстом.", mid)
        else:
            self.api.send_message(chat, "Не знаю такой команды. /help — справка.")

    @staticmethod
    def _name(document, ext: str) -> str:
        pr = document.project
        base = f"{pr.code}" if pr.code else "проект"
        return _safe_filename(base) + ext

    def deliver(self, chat: int, mid: int, document, caption: str) -> None:
        """Рисует PDF, отправляет PDF и Excel."""
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.pdf"
            sheets = render_pdf(document, str(out))
            xlsx = Path(d) / "project.xlsx"
            write_workbook(xlsx, document)
            stats = (f"{sheets} листов; спецификация: {len(document.spec)} поз., "
                     f"клеммников: {len(document.terminals)}, модулей ПЛК: {len(document.plc)}.")
            self.api.send_document(chat, out, self._name(document, ".pdf"),
                                   (caption + "\n" + stats).strip()[:1000], mid)
            self.api.send_document(chat, xlsx, self._name(document, ".xlsx"),
                                   "Исходные данные — можно поправить и прислать обратно.")

    def on_key(self, chat: int, mid: int, user: int, text: str) -> None:
        """/key sk-ant-... — сохранить ключ Claude API в .env.

        Менять уже заданный ключ может только пользователь из ALLOWED_USERS."""
        parts = text.split(maxsplit=1)
        key = parts[1].strip() if len(parts) > 1 else ""
        if self.claude_key and not (self.allowed and user in self.allowed):
            self.api.send_message(chat, "Ключ уже задан. Поменять его может только "
                                        "пользователь из ALLOWED_USERS в .env.", mid)
            return
        if not key.startswith("sk-ant-"):
            self.api.send_message(chat, "Пришлите так: /key sk-ant-...", mid)
            return
        try:
            assistant.ask(key, {}, "проверка связи: шифр ТЕСТ", self.claude_model,
                          self.claude_url, timeout=120, check_fix=False)
        except assistant.AssistantError as e:
            self.api.send_message(chat, f"Ключ не подошёл: {e}", mid)
            return
        set_env_value(ROOT / ".env", "ANTHROPIC_API_KEY", key)
        self.claude_key = key
        try:
            self.api.call("deleteMessage", {"chat_id": chat, "message_id": mid})
        except Exception:
            pass
        self.api.send_message(chat, "Ключ Claude API сохранён (сообщение с ним удалил). "
                                    "Теперь можно описывать проект текстом.")

    def _model_for(self, current: dict, text: str) -> str:
        """Новый проект или большое описание — сильная модель; мелкие правки — обычная."""
        empty = not any(current.get(k) for k in ("plc", "mains", "power24", "network",
                                                   "fields", "feeders"))
        if empty or len(text) > 1500:
            return self.claude_model_big or self.claude_model
        return self.claude_model

    def on_text(self, chat: int, mid: int, text: str) -> None:
        if not self.claude_key:
            self.api.send_message(chat, "Понимание текста не настроено. Пришлите ключ "
                                        "Claude API командой: /key sk-ant-...\n"
                                        "Пока можно работать через Excel (/template).", mid)
            return
        pending = self.load_pending(chat)
        saved = self.load_state(chat)
        current = {k: v for k, v in (pending or saved).items() if k != "_open"}
        open_items = (pending or {}).get("_open") or []
        big = self._model_for(current, text) != self.claude_model
        self.api.send_message(chat, "Принял, разбираю и проверяю — это займёт "
                              + ("3–6 минут…" if big else "1–3 минуты…"), mid)
        self.api.call("sendChatAction", {"chat_id": chat, "action": "typing"})
        try:
            update = assistant.ask(self.claude_key, current, text,
                                   self._model_for(current, text), self.claude_url,
                                   open_items=open_items)
        except assistant.AssistantError as e:
            self.api.send_message(chat, str(e), mid)
            return
        merged = update.pop("_merged", None) or assistant.merge(current, update)
        document = dict_to_doc(merged)
        # открытые пункты: старые без закрытых + новые допущения и вопросы
        closed = set(update.get("resolved") or [])
        items = [o for o in open_items if o.get("n") not in closed]
        items += [{"key": str(c.get("key") or "").strip(), "text": str(c["text"]).strip(),
                   "kind": "confirm"} for c in update.get("confirm") or []]
        items += [{"key": "", "text": q, "kind": "question"}
                  for q in update.get("questions") or [] if q]
        seen, uniq = set(), []
        for o in items:
            sig = (o["key"].upper(), o["text"].lower())
            if sig not in seen:
                seen.add(sig)
                uniq.append(o)
        uniq.sort(key=lambda o: o["kind"] != "confirm")   # сначала допущения, потом вопросы
        for i, o in enumerate(uniq, 1):
            o["n"] = i
        if not any((document.spec, document.terminals, document.plc, document.power24,
                    document.feeders, document.mains)):
            self.save_state(chat, doc_to_dict(document))   # только реквизиты — сразу
            lines = [update.get("summary", "").strip(), "Пока нечего рисовать — "
                     "напишите списком, что будет в шкафу."]
            if uniq:
                lines.append("\n".join(f"{o['n']}. {o['text']}" for o in uniq))
            self.api.send_message(chat, "\n\n".join(x for x in lines if x), mid)
            return
        if not document.project.code:
            document.project.code = "БЕЗ ШИФРА"
        # синим — отличия от прошлого черновика (или от принятого проекта)
        self.propose(chat, mid, current, document, uniq, update.get("summary", "").strip(),
                     closed_count=len(closed & {o.get("n") for o in open_items}))

    # --- черновик на согласование ---------------------------------------------
    KEYBOARD = [[{"text": "✅ Принять", "callback_data": "ok"},
                 {"text": "↩️ Отменить", "callback_data": "undo"}]]

    def propose(self, chat: int, mid: int, saved: dict, document, items: list,
                summary: str, closed_count: int = 0) -> None:
        """Черновик PDF с метками (оранжевые — на подтверждение, синие — изменения)
        и список пунктов; ждём ответ текстом или кнопку."""
        data = doc_to_dict(document)
        data["_open"] = items
        self.save_pending(chat, data)
        marks = [(o["key"], "confirm", o["n"]) for o in items if o.get("key")]
        try:
            marks += [(k, "changed", "") for k in preview.changed_keys(saved, data)]
        except Exception:
            log.error("Не удалось сравнить версии:\n%s", traceback.format_exc())
        hits: list = []
        pages_of: dict[str, set] = {}
        changed_pages: set = set()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "draft.pdf"
            try:
                sheets = render_pdf(document, str(out), marks, hits)
            except Exception:
                log.error("Черновик не нарисовался:\n%s", traceback.format_exc())
                self.api.send_message(chat, "Не смог нарисовать черновик — ошибка в "
                                            "программе, данные сохранил. Попробуйте "
                                            "переформулировать.", mid)
                return
            for page, kind, label in hits:
                if kind == "confirm":
                    pages_of.setdefault(label, set()).add(page)
                else:
                    changed_pages.add(page)
            cap = f"ЧЕРНОВИК, {sheets} листов."
            if changed_pages:
                cap += " Изменения (синие рамки) на стр. " + \
                    ", ".join(map(str, sorted(changed_pages))) + "."
            self.api.send_document(chat, out, self._name(document, "_черновик.pdf"),
                                   cap[:1000], mid)
        lines = []
        if summary:
            lines.append(summary)
        elif not closed_count:
            lines.append("Изменений нет.")
        if closed_count:
            lines.append(f"Закрыл пунктов: {closed_count}.")
        conf = [o for o in items if o["kind"] == "confirm"]
        ques = [o for o in items if o["kind"] != "confirm"]

        def row(o):
            pg = pages_of.get(str(o["n"]))
            where = f" (стр. {', '.join(map(str, sorted(pg)))})" if pg else ""
            return f"{o['n']}. {o['text']}{where}"
        if conf:
            lines.append("Подтвердите (оранжевые метки в PDF):\n" + "\n".join(map(row, conf)))
        if ques:
            lines.append("Вопросы:\n" + "\n".join(map(row, ques)))
        problems = check(document)
        if problems:
            lines.append("Не хватает:\n" + "\n".join(f"• {p}" for p in problems[:8]))
        lines.append("Ответьте текстом — можно по номерам («1 да, 2 — на B5») или "
                     "любой правкой. ✅ — принять, ↩️ — отменить черновик."
                     if items else "Если всё верно — ✅. Правки пишите текстом.")
        text = "\n\n".join(lines)
        if len(text) > 4000:
            text = text[:3990] + "…"
        self.api.send_message(chat, text, None, keyboard=self.KEYBOARD)

    def on_callback(self, cq: dict) -> None:
        chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
        user = (cq.get("from") or {}).get("id")
        try:
            self.api.call("answerCallbackQuery", {"callback_query_id": cq.get("id")})
        except Exception:
            pass
        if not chat or (self.allowed and user not in self.allowed):
            return
        try:  # убрать кнопки с сообщения
            self.api.call("editMessageReplyMarkup", {
                "chat_id": chat, "message_id": cq["message"]["message_id"],
                "reply_markup": {"inline_keyboard": []}})
        except Exception:
            pass
        pending = self.load_pending(chat)
        if pending is None:
            self.api.send_message(chat, "Нечего подтверждать — изменений на проверке нет.")
            return
        if cq.get("data") == "ok":
            left = len(pending.pop("_open", None) or [])
            self.save_state(chat, pending)
            self.save_pending(chat, None)
            note = "Принято." + (f" Неотвеченных пунктов осталось {left} — они приняты "
                                 "как в черновике." if left else "")
            self.deliver(chat, None, dict_to_doc(pending), note)
        else:
            self.save_pending(chat, None)
            self.api.send_message(chat, "Черновик отменил, проект остался как был "
                                        "до него.")

    def on_document(self, chat: int, mid: int, doc: dict) -> None:
        name = doc.get("file_name") or "file"
        if name.lower().endswith((".txt", ".md")):
            raw = self.api.download(doc["file_id"])
            for enc in ("utf-8-sig", "cp1251"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            self.on_text(chat, mid, text)
            return
        if not name.lower().endswith((".xlsx", ".xlsm")):
            self.api.send_message(chat, "Пришлите Excel (.xlsx) или описание текстом / "
                                        "файлом .txt. Шаблон Excel — /template.", mid)
            return
        if doc.get("file_size", 0) > 20 * 1024 * 1024:
            self.api.send_message(chat, "Файл больше 20 МБ — Telegram не даст "
                                        "боту его скачать.", mid)
            return
        self.api.call("sendChatAction", {"chat_id": chat, "action": "upload_document"})
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "input.xlsx"
            src.write_bytes(self.api.download(doc["file_id"]))
            try:
                document = read_document(src)
            except TemplateError as e:
                problems = "\n".join(f"• {x}" for x in e.problems[:30])
                more = len(e.problems) - 30
                if more > 0:
                    problems += f"\n… и ещё {more}"
                self.api.send_message(chat, "В файле есть ошибки, PDF не создан:\n"
                                            + problems, mid)
                return
            self.save_state(chat, doc_to_dict(document))
            self.save_pending(chat, None)
            with tempfile.TemporaryDirectory() as d2:
                out = Path(d2) / "out.pdf"
                sheets = render_pdf(document, str(out))
                self.api.send_document(
                    chat, out, self._name(document, ".pdf"),
                    f"Готово: {sheets} листов; спецификация: {len(document.spec)} поз., "
                    f"клеммников: {len(document.terminals)}, модулей ПЛК: {len(document.plc)}.\n"
                    "Проект запомнил — дальше можно править текстом.", mid)

    RESTART_CODE = 3   # run_bot.bat перезапускает бота с этим кодом выхода

    @staticmethod
    def _code_stamp() -> float:
        files = [ROOT / "bot.py", ROOT / "requirements.txt", *(ROOT / "schemgen").rglob("*.py")]
        return max((f.stat().st_mtime for f in files if f.is_file()), default=0.0)

    def run(self) -> None:
        offset = 0
        me = self.api.call("getMe")
        log.info("Бот @%s запущен", me.get("username"))
        stamp = self._code_stamp()
        self._active = 0
        while True:
            # обновились файлы бота — перезапуск, когда ничего не обрабатывается
            if self._code_stamp() != stamp and self._active == 0 and not self._pending:
                log.info("Файлы бота обновлены — перезапускаюсь")
                if offset:
                    try:  # подтвердить полученные апдейты, чтобы не обработать их дважды
                        self.api.call("getUpdates", {"offset": offset, "timeout": 0})
                    except Exception:
                        pass
                sys.exit(self.RESTART_CODE)
            try:
                updates = self.api.call("getUpdates", {"offset": offset, "timeout": 25})
            except Exception as e:
                log.warning("getUpdates: %s — повтор через 5 с", e)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                # каждый апдейт — в своём потоке, но сообщения одного чата по очереди
                self._active += 1
                threading.Thread(target=self._safe_handle, args=(u,), daemon=True).start()

    TEXT_QUIET = 4.0   # сек тишины, после которых собранный текст уходит в разбор

    def _buffer_text(self, u: dict) -> bool:
        """Обычный текст копим: Telegram делит длинное сообщение на части по 4096
        символов. Разбираем, когда части перестали приходить."""
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        if not text or text.startswith("/") or "chat" not in msg:
            return False
        user = (msg.get("from") or {}).get("id")
        if self.allowed and user not in self.allowed:
            return False
        chat = msg["chat"]["id"]
        with self._locks_guard:
            buf = self._pending.get(chat)
            if buf is None:
                buf = self._pending[chat] = {"parts": [], "mid": msg.get("message_id"),
                                             "last": 0.0}
                threading.Thread(target=self._flush_later, args=(chat,), daemon=True).start()
            buf["parts"].append(text)
            buf["last"] = time.monotonic()
        return True

    def _flush_later(self, chat: int) -> None:
        while True:
            time.sleep(0.5)
            with self._locks_guard:
                buf = self._pending.get(chat)
                if buf and time.monotonic() - buf["last"] >= self.TEXT_QUIET:
                    self._pending.pop(chat)
                    break
        text = "\n".join(buf["parts"])
        self._active = getattr(self, "_active", 0) + 1
        try:
            self._flush_text(chat, buf, text)
        finally:
            self._active -= 1

    def _flush_text(self, chat: int, buf: dict, text: str) -> None:
        with self.lock(chat):
            try:
                self.on_text(chat, buf["mid"], text)
            except Exception:
                log.error("Ошибка обработки:\n%s", traceback.format_exc())
                self.api.send_message(chat, "Внутренняя ошибка при обработке, "
                                            "см. журнал бота.")

    def _safe_handle(self, u: dict) -> None:
        """Счётчик _active увеличивает run() до запуска потока."""
        try:
            self._safe_handle_inner(u)
        finally:
            self._active -= 1

    def _safe_handle_inner(self, u: dict) -> None:
        if self._buffer_text(u):
            return
        msg = u.get("message") or u.get("edited_message") or \
            (u.get("callback_query") or {}).get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        with self.lock(chat or 0):
            try:
                self.handle(u)
            except Exception:
                log.error("Ошибка обработки:\n%s", traceback.format_exc())
                if chat:
                    try:
                        self.api.send_message(chat, "Внутренняя ошибка при "
                                                    "обработке, см. журнал бота.")
                    except Exception:
                        pass


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    load_env(ROOT / ".env")
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token and sys.stdin and sys.stdin.isatty():
        # Первый запуск: спрашиваем токен и сохраняем его в .env
        token = input("Вставьте токен бота от @BotFather и нажмите Enter: ").strip()
        if token:
            with open(ROOT / ".env", "a", encoding="utf-8") as f:
                f.write(f"BOT_TOKEN={token}\n")
            print("Токен сохранён в .env")
    if not token:
        print("Не задан BOT_TOKEN (в .env или переменной окружения).", file=sys.stderr)
        return 1
    allowed = {int(x) for x in re.findall(r"-?\d+", os.environ.get("ALLOWED_USERS", ""))}
    api = Api(token, os.environ.get("TELEGRAM_API", "https://api.telegram.org"))
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not claude_key:
        log.info("ANTHROPIC_API_KEY не задан — работаю только с Excel")
    try:
        Bot(api, allowed or None, claude_key,
            os.environ.get("CLAUDE_MODEL", assistant.DEFAULT_MODEL)).run()
    except RuntimeError as e:
        print(f"Не удалось подключиться к Telegram: {e}\n"
              "Проверьте токен в файле .env (строка BOT_TOKEN=...).", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Нет связи с api.telegram.org: {e.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
