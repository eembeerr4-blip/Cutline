import tempfile
import unittest
from pathlib import Path

from clipper.publish import publish, publish_post


class PublishTests(unittest.TestCase):
    def test_publish_and_repeat(self):
        with tempfile.TemporaryDirectory() as t:
            clip = Path(t) / "clip.mp4"
            clip.write_bytes(b"v1")
            cfg = {"output_dir": str(Path(t) / "Готовые видео")}
            d = publish("2026-11-23_проект", clip, cfg)
            self.assertEqual(d.read_bytes(), b"v1")
            clip.unlink()
            clip.write_bytes(b"v2")                       # пересборка того же проекта
            d2 = publish("2026-11-23_проект", clip, cfg)
            self.assertEqual((d2, d2.read_bytes()), (d, b"v2"))
            md = publish_post(d2, "text")
            self.assertEqual((md.suffix, md.read_text(encoding="utf-8").strip()), (".md", "text"))


if __name__ == "__main__":
    unittest.main()
