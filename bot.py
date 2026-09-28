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
from schemgen import assistant
from schemgen.jsonio import check, dict_to_doc, doc_to_dict

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "examples" / "example_2196_SS1.xlsx"
STATE_DIR = ROOT / "data"          # текущий проект каждого чата (JSON)
log = logging.getLogger("bot")

HELP = (
    "Я делаю комплект документации в PDF: спецификацию и клеммный план (В4) и схему "
    "Э3 (листы входов/выходов ПЛК).\n\n"
    "Два способа:\n"
    "• Текстом. Опишите, что в проекте: шифр, заказчик, модули ПЛК и что на каких "
    "входах/выходах, реле, клеммники, спецификация. Можно по частям и потом "
    "поправлять: «добавь реле 1K5 на выход B5», «убери клеммник X3».\n"
    "• Excel. /template — пустой шаблон, /example — заполненный пример. "
    "Заполните и пришлите файлом.\n\n"
    "В ответ — PDF и Excel с тем, что я понял (его можно поправить и прислать обратно).\n"
    "/project — текущий проект в Excel, /new — начать новый проект."
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

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None):
        p = {"chat_id": chat_id, "text": text}
        if reply_to:
            p["reply_to_message_id"] = reply_to
        return self.call("sendMessage", p)


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
        self.claude_url = claude_url
        self.state_dir = state_dir
        self._locks: dict[int, threading.Lock] = {}
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

    def lock(self, chat: int) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(chat, threading.Lock())

    def handle(self, update: dict) -> None:
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
        elif cmd == "/new":
            self.save_state(chat, {})
            self.api.send_message(chat, "Начинаем новый проект. Опишите его текстом "
                                        "или пришлите Excel.")
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

    def on_text(self, chat: int, mid: int, text: str) -> None:
        if not self.claude_key:
            self.api.send_message(chat, "Понимание текста не настроено: в файл .env нужно "
                                        "добавить ANTHROPIC_API_KEY. Пока можно "
                                        "работать через Excel (/template).", mid)
            return
        self.api.send_message(chat, "Разбираю описание, это займёт до пары минут…", mid)
        self.api.call("sendChatAction", {"chat_id": chat, "action": "typing"})
        current = self.load_state(chat)
        try:
            update = assistant.ask(self.claude_key, current, text, self.claude_model,
                                   self.claude_url)
        except assistant.AssistantError as e:
            self.api.send_message(chat, str(e), mid)
            return
        merged = assistant.merge(current, update)
        document = dict_to_doc(merged)
        self.save_state(chat, doc_to_dict(document))
        lines = [update.get("summary", "").strip()]
        problems = check(document)
        questions = [q for q in update.get("questions") or [] if q]
        if questions:
            lines.append("Уточните:\n" + "\n".join(f"• {q}" for q in questions[:8]))
        if problems:
            lines.append("Не хватает для PDF:\n" + "\n".join(f"• {p}" for p in problems[:10]))
        if not (document.spec or document.terminals or document.plc):
            lines.append("Пока нечего рисовать — опишите оборудование подробнее.")
            self.api.send_message(chat, "\n\n".join(x for x in lines if x), mid)
            return
        if not document.project.code:
            document.project.code = "БЕЗ ШИФРА"
        self.api.send_message(chat, "\n\n".join(x for x in lines if x), mid)
        self.deliver(chat, mid, document, "")

    def on_document(self, chat: int, mid: int, doc: dict) -> None:
        name = doc.get("file_name") or "file"
        if not name.lower().endswith((".xlsx", ".xlsm")):
            self.api.send_message(chat, "Нужен файл Excel (.xlsx). "
                                        "Шаблон — командой /template.", mid)
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
            with tempfile.TemporaryDirectory() as d2:
                out = Path(d2) / "out.pdf"
                sheets = render_pdf(document, str(out))
                self.api.send_document(
                    chat, out, self._name(document, ".pdf"),
                    f"Готово: {sheets} листов; спецификация: {len(document.spec)} поз., "
                    f"клеммников: {len(document.terminals)}, модулей ПЛК: {len(document.plc)}.\n"
                    "Проект запомнил — дальше можно править текстом.", mid)

    def run(self) -> None:
        offset = 0
        me = self.api.call("getMe")
        log.info("Бот @%s запущен", me.get("username"))
        while True:
            try:
                updates = self.api.call("getUpdates", {"offset": offset, "timeout": 50})
            except Exception as e:
                log.warning("getUpdates: %s — повтор через 5 с", e)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                # каждый апдейт — в своём потоке, но сообщения одного чата по очереди
                threading.Thread(target=self._safe_handle, args=(u,), daemon=True).start()

    def _safe_handle(self, u: dict) -> None:
        chat = ((u.get("message") or u.get("edited_message") or {}).get("chat") or {}).get("id")
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
    if not claude_key and sys.stdin and sys.stdin.isatty() and not os.environ.get("ANTHROPIC_ASKED"):
        claude_key = input("Ключ Claude API (sk-ant-...) для понимания текста; "
                           "Enter — пропустить: ").strip()
        with open(ROOT / ".env", "a", encoding="utf-8") as f:
            f.write(f"ANTHROPIC_API_KEY={claude_key}\n" if claude_key else "ANTHROPIC_ASKED=1\n")
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
