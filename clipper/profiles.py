"""Профили платформ: profiles\\<имя>.json. Ядро берёт всё (размер, fps, стиль, лимиты) отсюда.

Новая платформа = новый json-файл. Код менять не нужно.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from .errors import ClipperError
from .paths import ROOT

REQUIRED = ("name", "width", "height", "fps", "fit", "clip_len_sec", "loudness",
            "max_size_mb", "subtitles", "rules_file", "text_check")
FITS = ("pad", "blur", "crop")


@dataclass(frozen=True)
class Profile:
    name: str
    title: str
    width: int
    height: int
    fps: int
    fit: str
    clip_len_sec: tuple
    loudness: dict
    max_size_mb: float
    silence_max_sec: float
    fade_out_sec: float
    subtitles: dict
    rules_file: str
    text_check: str
    censor: dict


def parse_profile(data: dict, source: str = "профиль") -> Profile:
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ClipperError(f"В файле {source} не хватает полей: {', '.join(missing)}.",
                           "Открой файл в папке profiles и добавь эти поля по образцу x.json.")
    if data["fit"] not in FITS:
        raise ClipperError(f"В {source} режим вписывания «{data['fit']}» неизвестен.",
                           f"Допустимо: {', '.join(FITS)}.")
    lo, hi = data["clip_len_sec"]
    if not 0 < lo < hi:
        raise ClipperError(f"В {source} окно длины клипа задано неверно: {data['clip_len_sec']}.",
                           "Нужны два числа: от и до, в секундах.")
    return Profile(
        name=str(data["name"]), title=str(data.get("title", data["name"])),
        width=int(data["width"]), height=int(data["height"]), fps=int(data["fps"]),
        fit=data["fit"], clip_len_sec=(float(lo), float(hi)), loudness=dict(data["loudness"]),
        max_size_mb=float(data["max_size_mb"]), silence_max_sec=float(data.get("silence_max_sec", 3)),
        fade_out_sec=float(data.get("fade_out_sec", 0.4)), subtitles=dict(data["subtitles"]),
        rules_file=str(data["rules_file"]), text_check=str(data["text_check"]), censor=dict(data.get("censor", {})))


def load_profile(name: str, profiles_dir: Path | None = None) -> Profile:
    folder = profiles_dir or ROOT / "profiles"
    path = folder / f"{name}.json"
    if not path.exists():
        raise ClipperError(f"Профиль «{name}» не найден ({path.name}).",
                           "Выбери профиль из списка или проверь config.json (поле profile).")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ClipperError(f"Файл профиля {path.name} повреждён: {e}.",
                           "Верни его из резервной копии или исправь запятые и кавычки.") from e
    return parse_profile(data, path.name)


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    folder = profiles_dir or ROOT / "profiles"
    return sorted(p.stem for p in folder.glob("*.json"))
