"""Папка «Готовые видео»: сюда попадает готовый ролик (и post.md рядом), чтобы забирать одним кликом."""
import os
import shutil
from pathlib import Path

from .paths import ROOT, load_config, resolve


def output_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    d = resolve(cfg.get("output_dir", "Готовые видео"), ROOT)
    d.mkdir(parents=True, exist_ok=True)
    return d


def publish(project_name: str, clip: Path, cfg: dict | None = None) -> Path:
    """Кладёт ролик в «Готовые видео». Жёсткая ссылка не занимает места второй раз; не вышло: копия."""
    dest = output_dir(cfg) / (project_name[:110] + ".mp4")
    if dest.exists():
        dest.unlink()  # это наш собственный файл от прошлой сборки того же проекта
    try:
        os.link(clip, dest)
    except OSError:
        shutil.copy2(clip, dest)
    return dest


def publish_post(published: Path, text: str) -> Path:
    md = published.with_suffix(".md")
    md.write_text(text.strip() + "\n", encoding="utf-8")
    return md
