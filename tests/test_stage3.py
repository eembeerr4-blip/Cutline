import unittest
from pathlib import Path

from clipper.history import overlaps


class Stub:
    def __init__(self, name, sid, start, end, clip=True):
        self.dir = Path(name)
        self._d = {"source": {"id": sid, "title": name}, "moment": {"start": start, "end": end}, "clip": "x" if clip else None}

    def get(self, k, default=None):
        return self._d.get(k, default)


class Tests(unittest.TestCase):
    def test_duplicate_overlap(self):
        old = [Stub("a", "yt1", 100, 300), Stub("b", "other", 100, 300), Stub("c", "yt1", 1000, 1200), Stub("d", "yt1", 100, 300, clip=False)]
        hit = overlaps("yt1", 250, 500, projects=old)           # пересечение 50 с: ловится
        self.assertEqual([h["project"] for h in hit], ["a"])
        self.assertEqual(overlaps("yt1", 280, 500, projects=old), [])  # 20 с: не ловится
        self.assertEqual(overlaps("yt1", 250, 500, exclude="a", projects=old), [])


if __name__ == "__main__":
    unittest.main()
