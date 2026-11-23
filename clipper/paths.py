"""Пути проекта, config.json и безопасные имена файлов. Всё через pathlib."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "port": 8765,
    "profile": "x",
    "output_dir": "Готовые видео",
    "ffmpeg": "tools/ffmpeg/ffmpeg.exe",
    "node": "node",
    "ollama": "ollama",
    "whisper_model": "large-v3-turbo",
    "whisper_fallback": "small",
    "language": None,
    "min_free_vram_mb": 2500,
    "fonts_dir": "C:/Windows/Fonts",
    "download_retry_pauses": [5, 20, 60],
    "prefetch_video": True,
    "default_clip_tail_sec": 240,
}

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def load_config(root: Path = ROOT) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = root / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


def resolve(rel: str, root: Path = ROOT) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else root / p


def safe_name(text: str, limit: int = 60) -> str:
    """Имя файла/папки без запрещённых символов Windows."""
    s = _BAD_CHARS.sub(" ", text or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s[:limit].rstrip(" .")
    if not s or s.split(".")[0].upper() in _RESERVED:
        s = "клип " + s if s else "клип"
    return s


def data_dir(root: Path = ROOT) -> Path:
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir(root: Path = ROOT) -> Path:
    d = data_dir(root) / "проекты"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(root: Path = ROOT) -> Path:
    d = data_dir(root) / "кэш"
    d.mkdir(parents=True, exist_ok=True)
    return d
