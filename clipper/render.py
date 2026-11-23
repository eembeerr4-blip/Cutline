"""Сборка ролика одним проходом ffmpeg: резка с перекодированием, вписывание, субтитры, громкость, затухание."""
import tempfile
from pathlib import Path

from .errors import ClipperError
from .ffmpeg import probe, run_ffmpeg, tail
from .paths import load_config
from .profiles import Profile
from .subs import align_text, apply_fixes, build_ass, caption_groups, censor_text, fix_case, map_words, proper_names

MICRO_FADE = 0.04


def fit_chain(p: Profile, i: int, crop: str | None) -> str:
    """Фильтры одного куска: [i:v] → [v{i}] по режиму вписывания профиля."""
    W, H, F = p.width, p.height, p.fps
    pre = ""
    if crop:
        x, y, w, h = crop.split(":")
        pre = f"crop={w}:{h}:{x}:{y},"
    if p.fit == "pad":
        return f"[{i}:v]{pre}scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={F}[v{i}]"
    if p.fit == "crop":
        return f"[{i}:v]{pre}scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps={F}[v{i}]"
    return (f"[{i}:v]{pre}split=2[b{i}][f{i}];[b{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:5[bg{i}];"
            f"[f{i}]scale={W}:{H}:force_original_aspect_ratio=decrease[fg{i}];[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={F}[v{i}]")


def build_graph(p: Profile, durs: list, crop: str | None, ass_name: str | None, fonts_dir: str, scale_to: str | None = None) -> str:
    parts, joined = [], ""
    for i, d in enumerate(durs):
        parts.append(fit_chain(p, i, crop))
        fin = 0.15 if i == 0 else MICRO_FADE   # мягкий старт звука у ролика, микрофейд на стыках
        parts.append(f"[{i}:a]aresample=48000,afade=t=in:st=0:d={fin},afade=t=out:st={max(d - MICRO_FADE, 0):.3f}:d={MICRO_FADE}[a{i}]")
        joined += f"[v{i}][a{i}]"
    total = sum(durs)
    fo = min(p.fade_out_sec, total / 4)
    parts.append(f"{joined}concat=n={len(durs)}:v=1:a=1[vc][ac]")
    vtail = []
    if ass_name:
        fd = fonts_dir.replace(":", "\\:")
        vtail.append(f"subtitles=filename='{ass_name}':fontsdir='{fd}'")
    if scale_to:   # предпросмотр: после субтитров уменьшаем кадр
        vtail.append(f"scale={scale_to}")
    vtail += [f"fade=t=out:st={total - fo:.3f}:d={fo:.3f}", "format=yuv420p"]
    parts.append("[vc]" + ",".join(vtail) + "[vout]")
    ln = p.loudness
    parts.append(f"[ac]loudnorm=I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']},aresample=48000,afade=t=out:st={total - fo:.3f}:d={fo:.3f}[aout]")
    return ";".join(parts)


def encoder_args(kind: str, preview: bool = False) -> list:
    if preview:   # быстро и некрасиво: только посмотреть монтаж
        return (["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "34", "-b:v", "0"] if kind == "nvenc"
                else ["-c:v", "libx264", "-crf", "34", "-preset", "ultrafast"])
    if kind == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-profile:v", "high"]
    return ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-profile:v", "high"]


def render(video: Path, out: Path, p: Profile, spans: list, *, offset: float = 0.0, words: list | None = None,
           fixes: list | None = None, crop: str | None = None, subtitles: bool = True, names: list | None = None, corrected: str | None = None, preview: bool = False, cfg: dict | None = None) -> dict:
    """spans = [(начало, конец)] в секундах ИСХОДНИКА по порядку воспроизведения (холодное начало первым).
    offset: сколько секунд исходника обрезано в начале файла video (скачан кусок). words: слова расшифровки."""
    cfg = cfg or load_config()
    if not spans:
        raise ClipperError("Не задан отрезок для ролика.", "Сначала выбери момент.")
    info = probe(video)
    if not info["acodec"]:
        raise ClipperError("В видео нет звука.", "Нужен файл со звуковой дорожкой.")
    local = [(a - offset, b - offset) for a, b in spans]
    if any(a < -0.01 or b > info["duration"] + 0.5 for a, b in local):
        raise ClipperError("Выбранный отрезок выходит за пределы видеофайла.",
                           "Скачай видео целиком или выбери момент внутри скачанного куска.")
    durs = [b - a for a, b in local]
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings, used = [], "nvenc"
    with tempfile.TemporaryDirectory(prefix="cutline_") as tmp:
        work = Path(tmp)
        ass_name, ncap = None, 0
        if subtitles and words:
            mapped = map_words(words, spans)
            aligned = False
            if corrected:
                mapped, ratio = align_text(mapped, corrected)
                aligned = ratio >= 0.6
                if not aligned:
                    warnings.append(f"Субтитры от Claude не применены: совпало только {ratio:.0%} слов клипа (вставлен другой кусок?).")
            if not aligned:
                mapped = fix_case(mapped, list(names or []) + proper_names(words))
            for w in mapped:
                w["w"] = apply_fixes(w["w"], fixes)
            if aligned:
                warnings.insert(0, "Субтитры: знаки препинания и регистр взяты из ответа Claude.")
            for w in mapped:
                w["w"] = censor_text(w["w"], p.censor)
            groups = caption_groups(mapped, p.subtitles)
            ncap = len(groups)
            if groups:
                build_ass(groups, p.subtitles, p.width, p.height, work / "subs.ass")
                ass_name = "subs.ass"
        graph = build_graph(p, durs, crop, ass_name, cfg["fonts_dir"], "854:480" if preview else None)
        args = []
        for (a, _), d in zip(local, durs):
            args += ["-ss", f"{max(a, 0):.3f}", "-t", f"{d:.3f}", "-i", str(video)]
        base = args + ["-filter_complex", graph, "-map", "[vout]", "-map", "[aout]"]
        tail_args = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(out)]
        r = run_ffmpeg(base + encoder_args("nvenc", preview) + tail_args, cwd=work)
        if r.returncode:
            warnings.append("Видеокарта не смогла кодировать (NVENC), собрано процессором: дольше, но результат тот же.")
            used = "libx264"
            r = run_ffmpeg(base + encoder_args("libx264", preview) + tail_args, cwd=work)
        if r.returncode:
            raise ClipperError("Не удалось собрать ролик.", "Нажми «Система», скопируй диагностику и пришли в чат вместе с этим текстом.",
                               details=tail(r.stderr))
    return {"out": str(out), "encoder": used, "captions": ncap, "duration": sum(durs), "warnings": warnings}
