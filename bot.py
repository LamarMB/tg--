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
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from schemgen import TemplateError, read_document, render_pdf, write_workbook

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "examples" / "example_2196_SS1.xlsx"
log = logging.getLogger("bot")

HELP = (
    "Я делаю комплект документации (титульный лист, спецификация элементов, "
    "клеммный план) в PDF по Excel-файлу.\n\n"
    "1. /template — пустой шаблон Excel\n"
    "2. /example — заполненный пример (шкаф ВКС.АСПУ.2196.СС1)\n"
    "3. Заполните шаблон и пришлите его мне файлом (.xlsx) — в ответ придёт PDF.\n\n"
    "Как заполнять — на листе «Инструкция» внутри шаблона."
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
    def __init__(self, api: Api, allowed: set[int] | None = None):
        self.api = api
        self.allowed = allowed

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
        elif "document" in msg:
            self.on_document(chat, mid, msg["document"])
        else:
            self.api.send_message(chat, "Пришлите заполненный Excel-файл (.xlsx) "
                                        "или наберите /help.")

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
            pr = document.project
            out_name = _safe_filename(f"{pr.code}.{pr.spec_doc_suffix}".strip(".")) + ".pdf"
            out = Path(d) / "out.pdf"
            sheets = render_pdf(document, str(out))
            self.api.send_document(
                chat, out, out_name,
                f"Готово: {sheets} листов, позиций спецификации: {len(document.spec)}, "
                f"клеммников: {len(document.terminals)}.", mid)

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
                try:
                    self.handle(u)
                except Exception:
                    log.error("Ошибка обработки:\n%s", traceback.format_exc())
                    chat = ((u.get("message") or {}).get("chat") or {}).get("id")
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
    try:
        Bot(api, allowed or None).run()
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
