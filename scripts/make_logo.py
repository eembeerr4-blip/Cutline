"""Рисует логотип Cutline (синий «квадрат iOS», белый треугольник-плей, разрезанный диагональю) без сторонних библиотек.
Результат: assets/logo.png (256) и assets/logo.ico (16-256). Запуск: .venv\\Scripts\\python.exe scripts\\make_logo.py"""
import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SS = 4  # суперсэмплинг для гладких краёв


def png(rgba: list, size: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(v for px in rgba[y * size:(y + 1) * size] for v in px) for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def in_tri(x, y, a, b, c):
    def s(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    d1, d2, d3 = s((x, y), a, b), s((x, y), b, c), s((x, y), c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def sample(x, y):
    """Цвет точки (x, y) в 0..1: (r, g, b, a)."""
    u, v = (x - .5) * 2, (y - .5) * 2
    if abs(u) ** 5 + abs(v) ** 5 > 1:          # суперэллипс как значок iOS
        return (0, 0, 0, 0)
    t = y
    edge = abs(u) ** 5 + abs(v) ** 5
    if edge > .92:                                   # тонкая светлая кромка, чтобы тёмный значок не терялся на тёмной панели
        return (56, 61, 66, 255)
    bg = (int(21 + (0 - 21) * t), int(32 + (0 - 32) * t), int(43 + (0 - 43) * t), 255)   # от «Dim» к «Lights out» как в тёмной теме X
    tri = in_tri(x, y, (.37, .27), (.37, .73), (.74, .50))
    ax, ay, bx, by = .80, .14, .20, .86       # линия разреза
    d = abs((by - ay) * x - (bx - ax) * y + bx * ay - by * ax) / math.hypot(bx - ax, by - ay)
    if tri and d > .028:
        return (255, 255, 255, 255)
    if tri:
        return (29, 155, 240, 255)                   # разрез голубым, как фирменный цвет Твиттера
    return bg


def render(size: int) -> list:
    out = []
    for py in range(size):
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    r, g, b, a = sample((px + (sx + .5) / SS) / size, (py + (sy + .5) / SS) / size)
                    acc[0] += r * a; acc[1] += g * a; acc[2] += b * a; acc[3] += a
            n = SS * SS
            a = acc[3] / n
            out.append((0, 0, 0, 0) if acc[3] == 0 else (int(acc[0] / acc[3]), int(acc[1] / acc[3]), int(acc[2] / acc[3]), int(a)))
    return out


def main():
    (ROOT / "assets").mkdir(exist_ok=True)
    sizes = [256, 64, 48, 32, 24, 16]
    blobs = [(s, png(render(s), s)) for s in sizes]
    (ROOT / "assets" / "logo.png").write_bytes(blobs[0][1])
    head = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for s, b in blobs:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset + len(data))
        data += b
    (ROOT / "assets" / "logo.ico").write_bytes(head + entries + data)
    print("готово:", [s for s, _ in blobs])


main()
