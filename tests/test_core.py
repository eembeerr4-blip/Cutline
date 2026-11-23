import json
import tempfile
import unittest
from pathlib import Path

from clipper.errors import ClipperError
from clipper.moment import find_quote, parse_range, phrases, snap
from clipper.profiles import load_profile, list_profiles, parse_profile
from clipper.render import build_graph
from clipper.subs import apply_fixes, caption_groups, map_words, violations
from clipper.textcheck import check_text

ST = load_profile("x").subtitles


def words(text, t0=0.0, step=0.4):
    return [{"w": " " + w, "s": t0 + i * step, "e": t0 + i * step + 0.3, "p": 0.9} for i, w in enumerate(text.split())]


class Tests(unittest.TestCase):
    def test_second_profile_needs_no_code(self):
        base = json.loads((Path("profiles") / "x.json").read_text(encoding="utf-8"))
        base.update(name="demo", width=1080, height=1920, fit="blur", text_check="none")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "demo.json").write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(list_profiles(Path(d)), ["demo"])
            p = load_profile("demo", Path(d))
            g = build_graph(p, [10.0], None, None, "C:/Windows/Fonts")
            self.assertIn("1080:1920", g)
            self.assertIn("boxblur", g)
            self.assertEqual(check_text(p.text_check, "x")[0][0][0], "OK")

    def test_bad_profile(self):
        with self.assertRaises(ClipperError):
            parse_profile({"name": "x"})

    def test_captions_limits(self):
        ws = words("this is a long sentence about money and contracts that goes on and on without any stop at all " * 3)
        g = caption_groups(ws, ST)
        self.assertEqual(violations(g, ST), [])

    def test_map_words_offsets(self):
        ws = words("hello world", 100.0)
        m = map_words(ws, [(99.0, 102.0)])
        self.assertAlmostEqual(m[0]["s"], 1.0)

    def test_snap_whole_phrases(self):
        text = "this is phrase number {} about money and contracts today."
        segs = [{"start": i * 10.0, "end": i * 10.0 + 9, "text": text.format(i), "words": words(text.format(i), i * 10.0, 0.9)} for i in range(40)]
        phr = phrases(segs)
        self.assertEqual(len(phr), 40)                       # одна фраза на предложение
        s = snap(phr, 25.0, 100.0)
        self.assertEqual((s["start"], s["end"]), (phr[2]["start"], phr[10]["end"]))   # границы ровно по целым фразам
        s = snap(phr, 50.0)
        self.assertEqual(s["start"], phr[5]["start"])
        self.assertGreaterEqual(s["end"] - s["start"], 239)

    def test_long_unpunctuated_segment_not_split_into_words(self):
        seg = {"start": 0.0, "end": 30.0, "text": "", "words": words("word " * 60, 0.0, 0.5)}   # 30 с без точек
        phr = phrases([seg])
        self.assertTrue(all(len(p["words"]) > 5 for p in phr))
        self.assertTrue(all(p["end"] - p["start"] <= 15.01 for p in phr))

    def test_quote(self):
        segs = [{"start": i * 10.0, "end": i * 10.0 + 9, "text": t, "words": []} for i, t in
                enumerate(["Nobody told me about taxes.", "I lost four million dollars in one year.", "Then I quit."])]
        hit = find_quote(phrases(segs), "lost 4 million dollars in a year")
        self.assertEqual(hit[0]["first"], 1)

    def test_fix_whole_word_only(self):
        self.assertEqual(apply_fixes("Anyone or one, someone.", [("one", "X")]), "Anyone or X, someone.")

    def test_range(self):
        self.assertEqual(parse_range("1:02-2:03"), (62.0, 123.0))
        with self.assertRaises(ClipperError):
            parse_range("abc")

    def test_post_check(self):
        good = ("He lost everything in one night.\n\nShort tension line.\n\n" + ("He said \"I never saw it coming at all\" and more words. " * 100)
                + "\n\nMy takeaway is simple.\n\nWould you stay or leave?\n\n---\nRU:\nПеревод")
        res, _ = check_text("x_post", good)
        self.assertFalse([m for lv, m in res if lv == "FAIL"], res)
        bad = "Why did he leave?\n\nText \u2014 dash.\n\nEnd.\n"
        self.assertTrue([m for lv, m in check_text("x_post", bad)[0] if lv == "FAIL"])


if __name__ == "__main__":
    unittest.main()


class ComparisonFixesTests(unittest.TestCase):
    def test_censor_whole_words_and_case(self):
        from clipper.subs import censor_text
        c = {"motherfucker": "motherf*****", "fuck": "f***"}
        self.assertEqual(censor_text("Fuck that motherfucker, fucking", c), "F*** that motherf*****, fucking")

    def test_title_case_run_fixed_but_names_and_I_kept(self):
        from clipper.subs import fix_case
        ws = [{"w": " " + t, "s": i, "e": i + .5} for i, t in enumerate("Man I It's Still Hard For Kessler To Understand".split())]
        out = " ".join(w["w"].strip() for w in fix_case(ws, ["Kessler"]))
        self.assertEqual(out, "Man I it's still hard for Kessler to understand")

    def test_refine_bounds_to_sentences(self):
        from clipper.moment import refine_bounds
        txt = "Alpha beta gamma. Delta epsilon zeta eta theta iota. Kappa lambda mu nu xi omicron pi rho. Sigma tau upsilon phi chi psi omega. " * 3
        ws, t = [], 0.0
        for tok in txt.split():
            ws.append({"w": " " + tok, "s": t, "e": t + 0.9}); t += 1.0
        s, e, notes = refine_bounds(ws, 4.0, 40.0, tol=4)          # старт внутри предложения, конец посреди предложения
        self.assertEqual(ws[[w["s"] for w in ws].index(s) - 1]["w"].strip()[-1], ".")
        self.assertTrue(next(w for w in ws if w["e"] == e)["w"].strip().endswith("."))
        self.assertTrue(notes)

    def test_hyphen_space_removed(self):
        import re
        self.assertEqual(re.sub(r"(?<=\w) -(?=\w)", "-", "self -belief and a - dash"), "self-belief and a - dash")


class PreviewTests(unittest.TestCase):
    def test_preview_graph_downscales_after_subtitles(self):
        p = load_profile("x")
        g = build_graph(p, [10.0], None, "subs.ass", "C:/Windows/Fonts", "854:480")
        self.assertLess(g.index("subtitles="), g.index("scale=854:480"))
        self.assertNotIn("854:480", build_graph(p, [10.0], None, None, "C:/Windows/Fonts"))
