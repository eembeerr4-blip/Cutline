"""Запуск ffmpeg: только списком аргументов (без shell), разбор свойств файла, звук для Whisper."""
import re
import shutil
import subprocess
from pathlib import Path

from .errors import ClipperError
from .paths import load_config, resolve

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_exe(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    local = resolve(cfg["ffmpeg"])
    if local.exists():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise ClipperError("ffmpeg не найден.", "Положи ffmpeg.exe в папку tools\\ffmpeg или запусти «Система» и пришли диагностику в чат.")


def run_ffmpeg(args: list, cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Запуск с кодом возврата без исключения; решает вызывающий (нужен откат NVENC)."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-loglevel", "error", *map(str, args)]
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as e:
        raise ClipperError("ffmpeg завис и был остановлен.", "Повтори шаг. Если снова так, пришли диагностику в чат.") from e


def tail(text: str, n: int = 8) -> str:
    return "\n".join((text or "").strip().splitlines()[-n:])


def probe(path: Path) -> dict:
    """Свойства файла из вывода `ffmpeg -i` (ffprobe отдельно не нужен)."""
    if not Path(path).exists():
        raise ClipperError(f"Файл не найден: {path}", "Проверь путь или перетащи файл заново.")
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", creationflags=_NO_WINDOW).stderr
    info = {"size_bytes": Path(path).stat().st_size, "duration": 0.0, "width": 0, "height": 0,
            "fps": 0.0, "vcodec": None, "acodec": None, "sample_rate": 0}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    v = re.search(r"Video: (\w+).*?,\s*(\d{2,5})x(\d{2,5})[\s,\[]", out)
    if v:
        info.update(vcodec=v[1], width=int(v[2]), height=int(v[3]))
        f = re.search(r"([\d.]+) fps", out[v.start():])
        info["fps"] = float(f[1]) if f else 0.0
    a = re.search(r"Audio: (\w+).*?(\d+) Hz", out)
    if a:
        info.update(acodec=a[1], sample_rate=int(a[2]))
    if info["duration"] <= 0 and not info["vcodec"] and not info["acodec"]:
        raise ClipperError(f"Файл не читается как видео или звук: {Path(path).name}",
                           "Проверь, что файл целый и открывается в плеере.", details=tail(out))
    return info


def decode_audio(path: Path, start: float | None = None, dur: float | None = None):
    """Моно 16 кГц float32 через ffmpeg (не через faster_whisper.decode_audio: он падает с av 19)."""
    import numpy as np
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if proc.returncode or not proc.stdout:
        raise ClipperError("Не удалось достать звук из файла.", "Проверь, что у файла есть звуковая дорожка.",
                           details=tail(proc.stderr.decode("utf-8", "replace")))
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def frame_png(path: Path, t: float) -> bytes:
    """Один кадр видео в момент t (PNG), для рамки crop."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(path),
           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if r.returncode or not r.stdout:
        raise ClipperError("Не удалось взять кадр.", "Выбери другое место в видео.", details=tail(r.stderr.decode("utf-8", "replace")))
    return r.stdout
