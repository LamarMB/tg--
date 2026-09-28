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
        FakeTelegram.sent.append((method, data))
        self._ok({})


class BotFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.bot = bot.Bot(bot.Api("TOKEN", base))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeTelegram.sent = []

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

    def test_not_allowed(self):
        b = bot.Bot(self.bot.api, allowed={1})
        b.handle(self.msg(text="/template"))
        self.assertEqual([m for m, _ in FakeTelegram.sent], ["sendMessage"])


if __name__ == "__main__":
    unittest.main()
