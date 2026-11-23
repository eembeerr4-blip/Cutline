import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from clipper import storage
from clipper.errors import ClipperError


def make(root: Path, name: str, days_old: int = 0):
    d = root / "проекты" / name
    (d / "источник").mkdir(parents=True)
    (d / "готово").mkdir()
    (d / "источник" / "video.mp4").write_bytes(b"x" * 1000)
    (d / "готово" / "clip.mp4").write_bytes(b"y" * 500)
    created = (datetime.now() - timedelta(days=days_old)).isoformat()
    (d / "state.json").write_text(json.dumps({"title": name, "created": created, "clip": "x"}), encoding="utf-8")
    return d


class StorageTests(unittest.TestCase):
    def test_trash_restore_purge(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = make(root, "a")
            info = storage.list_projects_info(root)[0]
            self.assertEqual(info["source_size"], 1000)
            storage.trash_sources(["a"], root)
            self.assertFalse((d / "источник").exists())
            self.assertTrue((d / "готово" / "clip.mp4").exists())          # готовый ролик остался
            tr = storage.list_trash(root)
            self.assertEqual(tr[0]["size"], 1000)
            storage.restore(tr[0]["id"], root)
            self.assertTrue((d / "источник" / "video.mp4").exists())
            storage.trash_sources(["a"], root)
            tid = storage.list_trash(root)[0]["id"]
            with self.assertRaises(ClipperError):
                storage.purge([tid], 1, root)                                # неверный размер: ничего не удалено
            self.assertEqual(len(storage.list_trash(root)), 1)
            self.assertEqual(storage.purge([tid], 1000, root), 1000)
            self.assertEqual(storage.list_trash(root), [])

    def test_older_and_whole_and_cache(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make(root, "old", 40)
            make(root, "new", 1)
            self.assertEqual(len(storage.trash_older(30, root)), 1)
            self.assertTrue((root / "проекты" / "new" / "источник").exists())
            storage.trash_cache(root)
            self.assertFalse((root / "проекты" / "new" / "источник").exists())
            storage.trash_sources(["new"], root, whole=True)
            self.assertFalse((root / "проекты" / "new").exists())

    def test_bad_name(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ClipperError):
                storage.trash_sources(["../x"], Path(t))


if __name__ == "__main__":
    unittest.main()
