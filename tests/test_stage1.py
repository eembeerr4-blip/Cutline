import unittest

from fastapi.testclient import TestClient

from clipper.claude_reply import parse_reply
from clipper.errors import ClipperError
from clipper.server import create_app

PHR = [{"i": i, "start": i * 10.0, "end": i * 10.0 + 9, "text": f"Phrase number {i} about money.", "words": []} for i in range(60)]


class ReplyTests(unittest.TestCase):
    def test_ok_with_quote(self):
        r = parse_reply('START: 2\nEND: 20\nQUOTE: "phrase number 5 about money"', PHR, (150, 330))
        self.assertEqual((r["first"], r["last"], r["errors"]), (2, 20, []))

    def test_bad_quote_and_overlap(self):
        r = parse_reply('START: 2\nEND: 20\nOPEN: 10-12\nQUOTE: "never said"', PHR, (150, 330))
        self.assertEqual(len(r["errors"]), 1)          # пересечение холодного начала; цитаты теперь проверяются в посте (предупреждения)

    def test_missing_numbers_and_range(self):
        with self.assertRaises(ClipperError):
            parse_reply("не знаю", PHR, (150, 330))
        with self.assertRaises(ClipperError):
            parse_reply("START: 1\nEND: 999", PHR, (150, 330))


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(create_app("tok", 8765), base_url="http://127.0.0.1:8765")
        self.h = {"host": "127.0.0.1:8765"}

    def test_token_origin_host(self):
        self.assertEqual(self.c.get("/api/ping", headers=self.h).status_code, 403)
        self.assertEqual(self.c.get("/api/ping", headers={**self.h, "x-token": "tok"}).status_code, 200)
        self.assertEqual(self.c.get("/api/ping", headers={**self.h, "x-token": "tok", "origin": "http://evil.com"}).status_code, 403)
        self.assertEqual(self.c.get("/api/ping", headers={"host": "evil.com", "x-token": "tok"}).status_code, 403)
        self.assertEqual(self.c.delete("/api/projects", headers={**self.h, "origin": "http://evil.com"}).status_code, 403)

    def test_path_traversal(self):
        r = self.c.get("/api/project/..%2F..", headers={**self.h, "x-token": "tok"})
        self.assertIn(r.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
