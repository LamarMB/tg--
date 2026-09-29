"""Проверки: python -m unittest -v  (из корня проекта)."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from openpyxl import load_workbook

import bot
from schemgen import TemplateError, read_document, render_pdf, write_workbook

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "example_2196_SS1.xlsx"


class Generate(unittest.TestCase):
    def test_example_reads(self):
        d = read_document(EXAMPLE)
        self.assertEqual(d.project.code, "ВКС.АСПУ.2196.СС1")
        self.assertEqual(len(d.spec), 74)
        counts = {b.name: b.terminal_count for b in d.terminals}
        # как в образце PDF
        self.assertEqual(counts["X0"], 6)
        self.assertEqual(counts["1XT1"], 3)
        self.assertEqual(counts["3XT1"], 27)
        self.assertEqual(counts["XM1"], 7)

    def test_render(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "o.pdf"
            n = render_pdf(read_document(EXAMPLE), str(out))
            self.assertGreater(n, 5)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    def test_empty_template_errors(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.xlsx"
            write_workbook(p)
            with self.assertRaises(TemplateError) as e:
                read_document(p)
            self.assertTrue(any("Шифр" in x for x in e.exception.problems))

    def test_bad_tier(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.xlsx"
            write_workbook(p, read_document(EXAMPLE))
            wb = load_workbook(p)
            wb["Клеммы"]["I2"] = "5"
            wb.save(p)
            with self.assertRaises(TemplateError) as e:
                read_document(p)
            self.assertIn("ярус", e.exception.problems[0])


class FakeTelegram(BaseHTTPRequestHandler):
    """Минимальный Bot API: getFile, скачивание файла, sendMessage, sendDocument."""
    sent = []
    file_bytes = b""
    claude_requests = []
    claude_reply = {}

    def log_message(self, *a):
        pass

    def _ok(self, result):
        body = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.file_bytes)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        method = self.path.rsplit("/", 1)[-1]
        if method == "getFile":
            return self._ok({"file_path": "documents/f.xlsx"})
        if self.path.endswith("/v1/messages"):
            req = json.loads(data)
            FakeTelegram.claude_requests.append(req)
            body = json.dumps({"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "name": "save_project",
                 "input": FakeTelegram.claude_reply}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        FakeTelegram.sent.append((method, data))
        self._ok({})


class BotFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bot = bot.Bot(bot.Api("TOKEN", base), claude_key="KEY",
                          claude_url=base + "/v1/messages", state_dir=Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        FakeTelegram.sent = []
        for f in Path(self.tmp.name).glob("*.json"):
            f.unlink()

    def msg(self, **kw):
        m = {"message_id": 1, "chat": {"id": 42}, "from": {"id": 7}}
        m.update(kw)
        return {"update_id": 1, "message": m}

    def test_excel_to_pdf(self):
        FakeTelegram.file_bytes = EXAMPLE.read_bytes()
        self.bot.handle(self.msg(document={"file_id": "x", "file_name": "a.xlsx",
                                           "file_size": 1000}))
        docs = [d for m, d in FakeTelegram.sent if m == "sendDocument"]
        self.assertEqual(len(docs), 1)
        self.assertIn(b"%PDF", docs[0])
        self.assertIn(".pdf", docs[0].decode("latin1"))

    def test_bad_excel_reports_errors(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.xlsx"
            write_workbook(p)
            FakeTelegram.file_bytes = p.read_bytes()
        self.bot.handle(self.msg(document={"file_id": "x", "file_name": "a.xlsx"}))
        texts = [json.loads(d)["text"] for m, d in FakeTelegram.sent if m == "sendMessage"]
        self.assertTrue(texts and "Шифр" in texts[0])

    def test_template_and_help(self):
        self.bot.handle(self.msg(text="/template"))
        self.bot.handle(self.msg(text="/start"))
        methods = [m for m, _ in FakeTelegram.sent]
        self.assertEqual(methods, ["sendDocument", "sendMessage"])

    def ok(self, data="ok"):
        return {"update_id": 2, "callback_query": {
            "id": "q", "from": {"id": 7}, "data": data,
            "message": {"message_id": 5, "chat": {"id": 42}}}}

    def test_text_preview_confirm_and_edit(self):
        FakeTelegram.claude_reply = {
            "summary": "Шкаф с ПЛК, 2 входа.",
            "questions": ["Артикул ПЛК?"],
            "project": {"code": "ВКС.ТЕСТ.1", "customer": "Заказчик"},
            "spec": [{"designation": "CPU", "name": "Контроллер", "qty": "1"}],
            "plc": [{"key": "CPU", "tag": "CPU", "type": "AM600", "kind": "in",
                     "channels": [
                         {"pin": "A1", "desc": "Датчик", "wire": ["CPU-DI0", "WH", "0,5"],
                          "link": "-XT1:1"},
                         {"pin": "A2", "desc": "Реле", "element": "ттр", "device": "K1"}]}]}
        self.bot.handle(self.msg(text="Шкаф ВКС.ТЕСТ.1, CPU AM600, на A1 датчик..."))
        methods = [m for m, _ in FakeTelegram.sent]
        # сначала картинки листов и вопрос с кнопками, PDF ещё нет
        self.assertTrue({"sendPhoto", "sendMediaGroup"} & set(methods))
        self.assertNotIn("sendDocument", methods)
        last = json.loads([d for m, d in FakeTelegram.sent if m == "sendMessage"][-1])
        self.assertIn("inline_keyboard", last["reply_markup"])
        self.assertIn("Артикул ПЛК?", last["text"])
        self.assertEqual(self.bot.load_state(42), {})           # ещё не применено
        # подтверждение
        FakeTelegram.sent = []
        self.bot.handle(self.ok())
        docs = [d for m, d in FakeTelegram.sent if m == "sendDocument"]
        self.assertEqual(len(docs), 2)                          # PDF + Excel
        self.assertIn(b"%PDF", docs[0])
        state = self.bot.load_state(42)
        self.assertEqual(state["plc"][0]["channels"][1]["device"], "-K1")
        # правка -> отмена: проект не меняется
        FakeTelegram.claude_reply = {"summary": "Добавил блок питания.",
                                     "spec": [{"designation": "CPU", "name": "Контроллер"},
                                              {"designation": "U1", "name": "БП 24В"}]}
        self.bot.handle(self.msg(text="добавь блок питания U1"))
        self.bot.handle(self.ok("undo"))
        self.assertEqual(len(self.bot.load_state(42)["spec"]), 1)
        # правка -> принять
        self.bot.handle(self.msg(text="добавь блок питания U1"))
        sent_ctx = FakeTelegram.claude_requests[-1]["messages"][0]["content"]
        self.assertIn("ВКС.ТЕСТ.1", sent_ctx)
        self.bot.handle(self.ok())
        state = self.bot.load_state(42)
        self.assertEqual(len(state["spec"]), 2)
        self.assertEqual(len(state["plc"]), 1)

    def test_base_template(self):
        self.bot.handle(self.msg(text="/base"))
        state = self.bot.load_state(42)
        self.assertEqual(state["project"]["code"], "ВКС.АСПУ.2196.СС1")
        self.assertEqual(len(state["spec"]), 74)

    def test_key_command(self):
        import os
        b = bot.Bot(self.bot.api, claude_url=self.bot.claude_url,
                    state_dir=self.bot.state_dir)
        FakeTelegram.claude_reply = {"summary": "ok"}
        old_root = bot.ROOT
        with tempfile.TemporaryDirectory() as t:
            bot.ROOT = Path(t)
            try:
                b.handle(self.msg(text="/key sk-ant-test123"))
                self.assertEqual(b.claude_key, "sk-ant-test123")
                self.assertIn("ANTHROPIC_API_KEY=sk-ant-test123",
                              (Path(t) / ".env").read_text(encoding="utf-8"))
                # второй раз чужой пользователь ключ не поменяет
                b.handle(self.msg(text="/key sk-ant-other"))
                self.assertEqual(b.claude_key, "sk-ant-test123")
            finally:
                bot.ROOT = old_root
                os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_not_allowed(self):
        b = bot.Bot(self.bot.api, allowed={1})
        b.handle(self.msg(text="/template"))
        self.assertEqual([m for m, _ in FakeTelegram.sent], ["sendMessage"])


if __name__ == "__main__":
    unittest.main()


class Schematic(unittest.TestCase):
    def test_plc_sheets_and_xrefs(self):
        from schemgen.e3 import io_sheets
        d = read_document(EXAMPLE)
        self.assertEqual([m.key for m in d.plc], ["CPU.DI", "CPU.DO", "A1", "A2", "A3", "A4"])
        pages = io_sheets.layout(d.plc)
        self.assertEqual(len(pages), 6)          # как листы 6–11 образца
        xr = io_sheets.register(pages, first_sheet=6)
        # кнопка -S1 на листе A2 ссылается на лампу -S1 листа выходов CPU (лист 7)
        self.assertTrue(xr.head_ref("-S1").startswith("/7."))
        # катушки 1K11 на листе 10, контактов на генерируемых листах нет
        self.assertTrue(xr.head_ref("1K11").startswith("/10."))

    def test_bad_element(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.xlsx"
            write_workbook(p, read_document(EXAMPLE))
            wb = load_workbook(p)
            wb["Каналы ПЛК"]["G2"] = "Трансформатор"
            wb.save(p)
            with self.assertRaises(TemplateError) as e:
                read_document(p)
            self.assertIn("неизвестный элемент", e.exception.problems[0])


class AssistantUnits(unittest.TestCase):
    def test_unwrap_nested_sections(self):
        from schemgen.assistant import _unwrap
        out = _unwrap({"project": {"project": {"code": "X"}, "spec": [{"name": "a"}],
                                   "summary": "ok"}})
        self.assertEqual(out["project"], {"code": "X"})
        self.assertEqual(out["spec"], [{"name": "a"}])
        self.assertEqual(out["summary"], "ok")

    def test_merge_per_module(self):
        from schemgen.assistant import merge
        cur = {"plc": [{"key": "A1", "channels": [1]}, {"key": "A2", "channels": [2]}],
               "terminals": [{"name": "X1", "rows": []}, {"name": "X2", "rows": []}],
               "spec": [{"name": "a"}]}
        out = merge(cur, {"plc": [{"key": "a2", "channels": [3]}, {"key": "A5"}],
                          "remove_terminal_blocks": ["X1"],
                          "terminals": [{"name": "X3", "rows": []}]})
        self.assertEqual([m["key"] for m in out["plc"]], ["A1", "a2", "A5"])
        self.assertEqual(out["plc"][1]["channels"], [3])
        self.assertEqual([b["name"] for b in out["terminals"]], ["X2", "X3"])
        self.assertEqual(out["spec"], [{"name": "a"}])


class Power24Sheet(unittest.TestCase):
    def test_example_power24_and_autorefs(self):
        from schemgen.e3 import io_sheets, power24
        d = read_document(EXAMPLE)
        self.assertEqual([len(g.breakers) for g in d.power24.groups], [9, 8])
        self.assertEqual(len(d.power24.minus[0].taps), 25)
        xr = io_sheets.XRef()
        sheets = power24.layout(d.power24)
        power24.register(sheets, 4, xr)
        io_sheets.register(io_sheets.layout(d.plc), 6, xr)
        self.assertEqual(xr.point_ref("-A3:A9").split(".")[0], "10")   # вывод модуля
        self.assertEqual(xr.point_ref("-1QFU4:1").split(".")[0], "4")  # автомат
        self.assertEqual(xr.point_ref("-XM1:M5").split(".")[0], "4")   # шина минусов

    def test_merge_power24_remove_breaker_by_tag(self):
        from schemgen.assistant import merge
        cur = {"power24": {"groups": [{"name": "2", "breakers": [{"tag": "-2QFU7"},
                                                                  {"tag": "-2QFU8"}]}]}}
        out = merge(cur, {"remove_power24_groups": ["2QFU8"]})
        self.assertEqual([b["tag"] for b in out["power24"]["groups"][0]["breakers"]], ["-2QFU7"])
