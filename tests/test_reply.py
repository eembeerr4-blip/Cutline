import unittest

from clipper.claude_reply import chat_package, parse_reply, split_post
from clipper.errors import ClipperError

PHR = [{"i": i, "start": i * 10.0, "end": i * 10.0 + 9, "text": f"Phrase number {i} about the money we paid.", "words": []} for i in range(60)]
REPLY = """START: 2
END: 20
ПОСТ:
He refused the bait in one sentence.

He said "phrase number 5 about the money we paid" and moved on.

He also said "this was never said by anyone".

Would you stay or leave?
---
RU: перевод"""


class ReplyTests(unittest.TestCase):
    def test_moment_and_post_in_one_reply(self):
        r = parse_reply(REPLY, PHR, (150, 330))
        self.assertEqual((r["first"], r["last"], r["errors"]), (2, 20, []))
        self.assertTrue(r["post"].startswith("He refused"))
        self.assertIn("RU:", r["post"])
        self.assertEqual((r["quotes"], r["quotes_ok"]), (2, 1))       # вторая цитата не из клипа: предупреждение
        self.assertTrue(any("never said" in w for w in r["warnings"]))

    def test_without_post_marker(self):
        self.assertTrue(split_post("START: 1\nEND: 3\nHook here.\n\nBody").startswith("Hook here"))

    def test_bad_numbers(self):
        with self.assertRaises(ClipperError):
            parse_reply("готовый текст без номеров", PHR, (150, 330))
        with self.assertRaises(ClipperError):
            parse_reply("START: 1\nEND: 999", PHR, (150, 330))

    def test_package_has_rules_transcript_and_format(self):
        t = chat_package(PHR, rules_md="---\nname: x\n---\nПРАВИЛО", title="T", channel="C", url="u", window=(150, 330))
        self.assertIn("ПРАВИЛО", t)
        self.assertIn("[59] ", t)
        self.assertIn("ПОСТ:", t)
        self.assertNotIn("name: x", t)


if __name__ == "__main__":
    unittest.main()


class FreeFormTests(unittest.TestCase):
    PHR = [{"i": i, "start": i * 10.0, "end": i * 10.0 + 9, "text": f"Phrase number {i} about the money we paid.", "words": []} for i in range(60)]

    def test_time_instead_of_numbers_and_english_among_russian(self):
        ans = ("1. Выбранный фрагмент\nМой выбор 0:20-4:50 — 4 минуты.\n\n2. Готовый пост для X\n"
               "He refused the bait in one sentence and moved on.\n\nHe said \"phrase number 5 about the money we paid\" today.\n\n"
               "Which is better, A or B?\n\n3. Что проверить на слух\nИмена.")
        r = parse_reply(ans, self.PHR, (150, 330))
        self.assertEqual((r["first"], r["last"]), (2, 29))
        self.assertTrue(any("по времени" in w for w in r["warnings"]))
        self.assertTrue(r["post"].startswith("He refused"))
        self.assertNotIn("Что проверить", r["post"])

    def test_link_request_template(self):
        from clipper.claude_reply import link_request
        t = link_request(rules_md="ПРАВИЛО", title="T", channel="C", url="https://y/1", window=(150, 330))
        self.assertIn("ВРЕМЯ:", t)
        self.assertIn("https://y/1", t)
        self.assertIn("ПРАВИЛО", t)

    def test_chat_package_template_is_first(self):
        t = chat_package(self.PHR, rules_md="X", title="T", channel="C", url="", window=(150, 330))
        self.assertTrue(t.startswith("ВАЖНО: твой ответ читает программа"))
        self.assertTrue(t.rstrip().endswith("Ничего больше."))


class QuoteTests(unittest.TestCase):
    def test_quotes_not_shifted_by_stray_quote(self):
        from clipper.textcheck import extract_quotes
        t = ('The “overpaid” talk was in the room. He says “I trust in my preparation” and later "I am not gonna let you score". '
             'Then a stray 7" mark. He admits he has a number in his head, "I do not care what you did" and ends.')
        q = extract_quotes(t)
        self.assertIn("I trust in my preparation", q)
        self.assertIn("I am not gonna let you score", q)
        self.assertFalse([x for x in q if x.lstrip().startswith((".", ","))])


class NormalizeTests(unittest.TestCase):
    def test_missing_separator_is_added(self):
        from clipper.textcheck import check_text, normalize_post
        en = "He passed on the bait in one line.\n\nShort second paragraph.\n\nHe said \"I do not care what they paid for\" and \"I will just win games\" and \"nobody is chasing stats\" and \"we just want to win\".\n\nWhich is better: A or B?"
        text = en + "\n\nRU: Он не повёлся.\n\nКакой вариант лучше: А или Б?"
        self.assertIn("\n---\n", normalize_post(text))
        res, st = check_text("x_post", text)
        self.assertFalse([m for lv, m in res if "разделител" in m or "перевод" in m])
        self.assertLess(st["words"], 60)              # английская часть отдельно, русская не считается
        self.assertFalse([m for lv, m in res if lv == "FAIL"], res)


class SubtitleTextTests(unittest.TestCase):
    def test_align_keeps_timing_and_takes_punctuation(self):
        from clipper.subs import align_text
        ws = [{"w": t, "s": i * .5, "e": i * .5 + .4} for i, t in enumerate("man i its still hard for me lucas scoring 40 points".split())]
        fixed, ratio = align_text(ws, "Man, I— it's still hard for me. Luka's scoring 40 points.")
        self.assertEqual(" ".join(w["w"] for w in fixed), "Man, I— it's still hard for me. Luka's scoring 40 points.")
        self.assertEqual([w["s"] for w in fixed], [w["s"] for w in ws])         # время от Whisper не тронуто

    def test_other_text_is_not_applied(self):
        from clipper.subs import align_text
        ws = [{"w": t, "s": i, "e": i + .5} for i, t in enumerate("alpha beta gamma delta epsilon".split())]
        out, ratio = align_text(ws, "Totally different text about something else entirely.")
        self.assertLess(ratio, .6)
        self.assertEqual([w["w"] for w in out], [w["w"] for w in ws])

    def test_subtitles_block_is_cut_from_post(self):
        reply = "START: 2\nEND: 20\nПОСТ:\nHook here.\n\nEnd or start?\n---\nRU: Перевод\nСУБТИТРЫ:\nPhrase number 2, about the money."
        r = parse_reply(reply, PHR, (150, 330))
        self.assertIn("Перевод", r["post"])
        self.assertNotIn("Phrase number 2", r["post"])
        self.assertTrue(r["subs_text"].startswith("Phrase number 2"))

