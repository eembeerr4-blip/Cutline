"""Скачивание через yt-dlp: сведения, звук, видео отрезка, повторы с паузами. Cookies браузера не читаются."""
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from .errors import ClipperError
from .ffmpeg import _NO_WINDOW, ffmpeg_exe, tail
from .paths import load_config

VIDEO_FORMAT = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b"
AUDIO_FORMAT = "ba[ext=m4a]/ba/b"


def is_url(text: str) -> bool:
    return bool(re.match(r"https?://", text.strip(), re.I))


def kind(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if re.search(r"(^|//|\.)(x|twitter)\.com/", u):
        return "x"
    return "other"


def file_key(path: Path) -> str:
    """Стабильный ID файла для кэша: размер + хэш первого и последнего мегабайта."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(1 << 20))
        f.seek(max(0, size - (1 << 20)))
        h.update(f.read(1 << 20))
    return "file-" + h.hexdigest()[:16]


def _cmd(args: list, cfg: dict) -> list:
    return [sys.executable, "-I", "-m", "yt_dlp", "--ffmpeg-location", ffmpeg_exe(cfg), "--js-runtimes", cfg.get("node", "node"),
            "--no-playlist", "--no-progress", "-q", "--no-warnings", *map(str, args)]


def _once(args: list, cfg: dict, timeout: float) -> str:
    try:
        r = subprocess.run(_cmd(args, cfg), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as e:
        raise ClipperError("Загрузка зависла и была остановлена.", "Повтори. Если снова так, перетащи файл с видео.") from e
    if r.returncode:
        raise ClipperError("Скачать не получилось.", "", details=tail(r.stderr, 6))
    return r.stdout


def run_with_retries(args: list, cfg: dict | None = None, timeout: float = 3600, sleep=time.sleep) -> str:
    cfg = cfg or load_config()
    pauses = list(cfg["download_retry_pauses"])
    last = None
    for attempt in range(len(pauses) + 1):
        try:
            return _once(args, cfg, timeout)
        except ClipperError as e:
            last = e
            if attempt < len(pauses):
                print(f"  загрузка не удалась, повтор через {pauses[attempt]} с…")
                sleep(pauses[attempt])
    low = (last.details or "").lower()
    hint = ("Для этой ссылки нужен вход в аккаунт. Скачай видео другим способом и перетащи файл." if re.search(r"sign in|log in|login|private|cookies", low)
            else "Проверь ссылку и интернет. Если не помогает, нажми «Обновить загрузчик» или перетащи файл с видео.")
    raise ClipperError("Не удалось скачать по ссылке после повторов.", hint, details=last.details)


def info(url: str, cfg: dict | None = None) -> dict:
    out = run_with_retries(["--dump-single-json", "--skip-download", url], cfg, timeout=180)
    d = json.loads(out)
    return {"id": d.get("id"), "title": d.get("title") or "", "channel": d.get("channel") or d.get("uploader") or "",
            "description": (d.get("description") or "")[:2000], "duration": d.get("duration") or 0,
            "heatmap": d.get("heatmap"), "url": d.get("webpage_url") or url, "kind": kind(url)}


def _find(folder: Path, stem: str) -> Path:
    hits = sorted(p for p in folder.glob(stem + ".*") if p.suffix not in (".part", ".ytdl", ".json"))
    if not hits:
        raise ClipperError("Загрузка закончилась, но файла нет.", "Повтори шаг или перетащи файл с видео.")
    return hits[0]


def fetch_audio(url: str, folder: Path, cfg: dict | None = None) -> Path:
    run_with_retries(["-f", AUDIO_FORMAT, "-o", folder / "audio.%(ext)s", url], cfg)
    return _find(folder, "audio")


def fetch_full(url: str, folder: Path, cfg: dict | None = None) -> Path:
    run_with_retries(["-f", VIDEO_FORMAT, "--merge-output-format", "mp4", "-o", folder / "video.%(ext)s", url], cfg)
    return _find(folder, "video")


def fetch_section(url: str, folder: Path, start: float, end: float, cfg: dict | None = None) -> tuple[Path, float]:
    """Видео отрезка. Возвращает (файл, сдвиг): время в файле = время в источнике - сдвиг. Не вышло: качаем целиком."""
    a = max(0, int(start))
    try:
        run_with_retries(["-f", VIDEO_FORMAT, "--merge-output-format", "mp4", "--download-sections", f"*{a}-{int(end) + 1}",
                          "--force-keyframes-at-cuts", "-o", folder / "section.%(ext)s", url], cfg)
        return _find(folder, "section"), float(a)
    except ClipperError:
        print("  отрезок не скачался, качаю видео целиком…")
        return fetch_full(url, folder, cfg), 0.0


def ytdlp_age_days() -> int | None:
    try:
        from yt_dlp.version import __version__
        y, m, d = (int(x) for x in __version__.split(".")[:3])
        return (date.today() - date(y, m, d)).days
    except (ImportError, ValueError):
        return None
