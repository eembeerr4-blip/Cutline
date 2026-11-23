"""Расшифровка через faster-whisper: GPU, выгрузка Ollama, откат на small/CPU, кэш по ID видео."""
import json
import os
import subprocess
import time
from pathlib import Path

from .errors import ClipperError
from .ffmpeg import decode_audio
from .paths import ROOT, cache_dir, load_config

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_dll_ready = False


def setup_cuda_dlls() -> None:
    """cuBLAS/cuDNN из venv: и в PATH (CTranslate2 грузит их обычным LoadLibrary), и через add_dll_directory."""
    global _dll_ready
    if _dll_ready:
        return
    base = ROOT / ".venv" / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn"):
        d = base / sub / "bin"
        if d.exists():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    _dll_ready = True


def _run(cmd: list, timeout: float = 20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=_NO_WINDOW)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def free_vram_mb() -> int | None:
    """Свободная видеопамять первой видеокарты или None, если nvidia-smi недоступен."""
    out = _run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], 10)
    try:
        return int(out.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def unload_ollama(cfg: dict) -> list[str]:
    """`ollama stop` для всех загруженных моделей (Ollama и Router не трогаем, только выгружаем из памяти)."""
    exe = cfg.get("ollama", "ollama")
    lines = _run([exe, "ps"], 10).strip().splitlines()[1:]
    names = [ln.split()[0] for ln in lines if ln.split()]
    for n in names:
        _run([exe, "stop", n], 20)
    if names:
        time.sleep(2)
    return names


def prepare_device(cfg: dict) -> tuple[str, list[str]]:
    """Решает, где считать: 'cuda' или 'cpu'. Возвращает (устройство, предупреждения)."""
    warns = []
    unloaded = unload_ollama(cfg)
    free = free_vram_mb()
    if free is None:
        return "cpu", ["Видеокарта не найдена (nvidia-smi недоступен): расшифровка пойдёт на процессоре, это медленно."]
    if free < cfg["min_free_vram_mb"]:
        warns.append(f"Свободно {free} МБ видеопамяти, нужно {cfg['min_free_vram_mb']}"
                     + (f" (выгрузка {', '.join(unloaded)} не помогла)" if unloaded else "")
                     + ". Расшифровка пойдёт на процессоре, это медленно.")
        return "cpu", warns
    return "cuda", warns


def load_model(name: str, device: str, models_dir: Path):
    """Модель из models\\, потом из общего кэша Hugging Face, потом скачивание в models\\."""
    from faster_whisper import WhisperModel
    compute = "float16" if device == "cuda" else "int8"
    for kwargs in ({"download_root": str(models_dir), "local_files_only": True}, {"local_files_only": True}, {"download_root": str(models_dir)}):
        try:
            return WhisperModel(name, device=device, compute_type=compute, **kwargs)
        except Exception as e:  # noqa: BLE001 - пробуем следующий источник модели
            last = e
    raise ClipperError(f"Модель {name} не загрузилась.", "Проверь интернет для первой загрузки или пришли диагностику в чат.", details=str(last))


def _collect(model, audio, hint, language, duration, progress) -> tuple[list, str]:
    segs, info = model.transcribe(
        audio, language=language, word_timestamps=True, vad_filter=True,
        condition_on_previous_text=False, hotwords=hint or None)
    out = []
    for s in segs:
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                    "words": [{"w": w.word, "s": round(w.start, 2), "e": round(w.end, 2), "p": round(w.probability, 3)}
                              for w in (s.words or [])]})
        if progress and duration:
            progress(min(1.0, s.end / duration))
    return out, info.language


def transcribe(video: Path, key: str, hint: str = "", progress=None, cfg: dict | None = None) -> dict:
    """Кэшированная расшифровка. `key` = ID видео или хэш файла. Возвращает словарь со списком segments."""
    cfg = cfg or load_config()
    cache = cache_dir() / "транскрипты"
    cache.mkdir(parents=True, exist_ok=True)
    for name in (cfg["whisper_model"], cfg["whisper_fallback"]):
        hit = cache / f"{key}.{name}.json"
        if hit.exists():
            return json.loads(hit.read_text(encoding="utf-8"))
    setup_cuda_dlls()
    audio = decode_audio(video)
    duration = len(audio) / 16000
    device, warns = prepare_device(cfg)
    plan = [(cfg["whisper_model"], device)] if device == "cuda" else []
    plan.append((cfg["whisper_fallback"], "cpu"))
    result, last = None, None
    for name, dev in plan:
        try:
            t0 = time.time()
            model = load_model(name, dev, ROOT / "models")
            segs, lang = _collect(model, audio, hint[:240], cfg.get("language"), duration, progress)
            result = {"model": name, "device": dev, "language": lang, "duration": round(duration, 1),
                      "seconds_spent": round(time.time() - t0, 1), "warnings": warns, "segments": segs}
            break
        except Exception as e:  # noqa: BLE001 - CUDA/память: падаем на запасной вариант
            last = e
            warns.append(f"{name} на {dev} не сработала ({type(e).__name__}); пробую запасной вариант.")
            unload_ollama(cfg)
    if result is None:
        raise ClipperError("Расшифровка не удалась ни на видеокарте, ни на процессоре.",
                           "Закрой тяжёлые программы и повтори. Если снова так, пришли диагностику в чат.", details=str(last))
    if result["model"] != cfg["whisper_model"]:
        result["warnings"].append(f"Использована запасная модель {result['model']} ({result['device']}): имена и числа проверяй внимательнее.")
    tmp = cache / f"{key}.{result['model']}.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache / f"{key}.{result['model']}.json")
    return result
