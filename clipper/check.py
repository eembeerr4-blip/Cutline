"""Автопроверка готового ролика по профилю. Результат: список (уровень, сообщение), уровни OK / WARN / FAIL."""
import re
import subprocess
from pathlib import Path

from .ffmpeg import _NO_WINDOW, ffmpeg_exe, probe
from .profiles import Profile


def _measure(path: Path) -> str:
    """Один проход: громкость (ebur128) и тишина (silencedetect). Вывод ffmpeg из stderr."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path), "-vn",
           "-af", "ebur128=peak=true,silencedetect=noise=-40dB:d=1", "-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=_NO_WINDOW).stderr


def fmt_len(sec: float) -> str:
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def check_video(path: Path, p: Profile) -> list[tuple[str, str]]:
    res: list[tuple[str, str]] = []
    if not Path(path).exists():
        return [("FAIL", f"Нет файла {path}. Собери ролик заново.")]
    i = probe(path)
    mb = i["size_bytes"] / 1e6
    res.append(("OK" if (i["width"], i["height"]) == (p.width, p.height) else "FAIL",
                f"Кадр {i['width']}x{i['height']} (нужно {p.width}x{p.height})"))
    res.append(("OK" if abs(i["fps"] - p.fps) < 0.2 else "FAIL", f"Частота кадров {i['fps']:g} (нужно {p.fps})"))
    res.append(("OK" if i["vcodec"] == "h264" else "FAIL", f"Видео {i['vcodec']} (нужен h264)"))
    res.append(("OK" if i["acodec"] == "aac" else "FAIL", f"Звук {i['acodec']} (нужен aac)"))
    res.append(("OK" if mb <= p.max_size_mb else "FAIL", f"Размер {mb:.0f} МБ (лимит {p.max_size_mb:.0f} МБ)"))
    lo, hi = p.clip_len_sec
    res.append(("OK" if lo <= i["duration"] <= hi else "WARN",
                f"Длина {fmt_len(i['duration'])} (ориентир {fmt_len(lo)}–{fmt_len(hi)})"))
    out = _measure(Path(path))
    m = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", out)
    if m:
        lufs = float(m[1])
        tol = p.loudness.get("tolerance", 2.5)
        res.append(("OK" if abs(lufs - p.loudness["I"]) <= tol else "WARN",
                    f"Громкость {lufs:.1f} LUFS (цель {p.loudness['I']}±{tol})"))
    else:
        res.append(("WARN", "Громкость измерить не удалось."))
    long_sil = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", out) if float(x) >= p.silence_max_sec]
    res.append(("OK" if not long_sil else "WARN",
                "Тишины дольше %g с нет" % p.silence_max_sec if not long_sil
                else f"Есть тишина дольше {p.silence_max_sec:g} с ({len(long_sil)} раз, до {max(long_sil):.1f} с)"))
    return res


def worst(results: list) -> str:
    levels = {lv for lv, _ in results}
    return "FAIL" if "FAIL" in levels else "WARN" if "WARN" in levels else "OK"
