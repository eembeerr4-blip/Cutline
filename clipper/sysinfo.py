"""Проверка системы: что установлено и работает. Вывод для меню и для «Скопировать диагностику»."""
import shutil
import subprocess
from pathlib import Path

from .download import ytdlp_age_days
from .ffmpeg import _NO_WINDOW, ffmpeg_exe
from .paths import ROOT, data_dir, load_config
from .profiles import list_profiles
from .transcribe import free_vram_mb

LOG_PATH_NAME = "лог.txt"


def _run(cmd: list, timeout: float = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_NO_WINDOW)
        return (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect(cfg: dict | None = None) -> list[tuple[str, str, str]]:
    """Список (статус, что проверяли, детали). Статус: OK / WARN / FAIL."""
    cfg = cfg or load_config()
    rows = []
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"], 10)
    rows.append(("OK" if gpu else "FAIL", "Видеокарта", gpu or "nvidia-smi не отвечает: расшифровка будет на процессоре (медленно)"))
    free = free_vram_mb()
    if free is not None:
        rows.append(("OK" if free >= cfg["min_free_vram_mb"] else "WARN", "Свободная видеопамять",
                     f"{free} МБ (нужно {cfg['min_free_vram_mb']}; перед расшифровкой Ollama выгружается сама)"))
    cuda_ok = all((ROOT / ".venv" / "Lib" / "site-packages" / "nvidia" / s / "bin").exists() for s in ("cublas", "cudnn"))
    rows.append(("OK" if cuda_ok else "FAIL", "CUDA-библиотеки (cuBLAS, cuDNN)", "найдены в .venv" if cuda_ok else "нет в .venv: пересобери окружение из wheels"))
    try:
        ff = ffmpeg_exe(cfg)
        ver = _run([ff, "-version"]).splitlines()[0]
        filters = _run([ff, "-hide_banner", "-filters"])
        enc = _run([ff, "-hide_banner", "-encoders"])
        feats = {"субтитры (libass)": " subtitles " in filters, "loudnorm": " loudnorm " in filters, "NVENC": "h264_nvenc" in enc}
        bad = [k for k, v in feats.items() if not v]
        rows.append(("OK" if not bad else "FAIL", "ffmpeg", f"{ver[:60]}; нет: {', '.join(bad)}" if bad else f"{ver[:60]}; субтитры, loudnorm, NVENC на месте"))
    except Exception as e:  # noqa: BLE001
        rows.append(("FAIL", "ffmpeg", str(e)))
    node = _run([cfg.get("node", "node"), "-v"])
    rows.append(("OK" if node.startswith("v") else "WARN", "Node.js (нужен загрузчику YouTube)", node or "не найден"))
    age = ytdlp_age_days()
    if age is None:
        rows.append(("FAIL", "yt-dlp", "не установлен"))
    else:
        rows.append(("OK" if age <= 14 else "WARN", "yt-dlp (загрузчик)", f"версии {age} дн." + ("" if age <= 14 else ": старше 14 дней, нажми «Обновить загрузчик»")))
    models = ROOT / "models"
    have = sorted(p.name.split("faster-whisper-")[-1] for p in models.glob("models--*"))
    rows.append(("OK" if cfg["whisper_model"] in have else "WARN", "Модель расшифровки", f"{cfg['whisper_model']}; в models: {', '.join(have) or 'пусто'}"))
    ollama = _run([cfg.get("ollama", "ollama"), "ps"], 10)
    rows.append(("OK", "Ollama", "модели в памяти: " + (", ".join(x.split()[0] for x in ollama.splitlines()[1:] if x.split()) or "нет")
                 if ollama else "не отвечает (для Cutline не обязателен)"))
    free_gb = shutil.disk_usage(data_dir()).free / 1e9
    rows.append(("OK" if free_gb > 20 else "WARN", "Свободное место на диске", f"{free_gb:.0f} ГБ"))
    rows.append(("OK", "Профили платформ", ", ".join(list_profiles()) or "нет"))
    return rows


def render_report(rows: list) -> str:
    mark = {"OK": "[ОК]     ", "WARN": "[ВНИМАНИЕ]", "FAIL": "[ОШИБКА] "}
    return "\n".join(f"{mark[s]} {name}: {detail}" for s, name, detail in rows)


def log_tail(n: int = 50) -> str:
    p = data_dir() / LOG_PATH_NAME
    if not p.exists():
        return "(лог пуст)"
    return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])


def diagnostics(cfg: dict | None = None) -> str:
    return render_report(collect(cfg)) + "\n\n--- последние 50 строк лога ---\n" + log_tail(50)
