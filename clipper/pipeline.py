"""Шаги конвейера: источник → расшифровка → ролик → проверка → пакет. Результат каждого шага пишется в state.json."""
import json
import shutil
from pathlib import Path

from . import download as dl
from .check import check_video, worst
from .errors import ClipperError
from .ffmpeg import probe
from .moment import fmt, phrases, refine_bounds
from .package import build_package, hint_names
from .paths import load_config, resolve, safe_name
from .profiles import Profile
from .project import Project
from .publish import publish, publish_post
from .render import render
from .transcribe import transcribe


def new_project(source: str, cfg: dict | None = None, log=print) -> Project:
    """Ссылка или файл → проект с источником. YouTube: пока только звук; остальное качается целиком."""
    cfg = cfg or load_config()
    source = source.strip().strip('"')
    if dl.is_url(source):
        log("Читаю сведения о видео…")
        meta = dl.info(source, cfg)
        proj = Project.create(meta["title"] or meta["id"] or "видео")
        proj.set(source=meta)
        if meta["kind"] == "youtube":
            log("Скачиваю звук…")
            proj.set(audio=str(dl.fetch_audio(meta["url"], proj.source_dir, cfg)), video=None, video_offset=0.0)
        else:
            log("Скачиваю видео целиком…")
            proj.set(video=str(dl.fetch_full(meta["url"], proj.source_dir, cfg)), audio=None, video_offset=0.0, video_full=True)
        return proj
    path = Path(source)
    if not path.is_file():
        raise ClipperError(f"Не нашёл файл или ссылку: {source}", "Вставь ссылку целиком (https://…) или перетащи файл в окно.")
    i = probe(path)
    meta = {"id": dl.file_key(path), "title": path.stem, "channel": "", "description": "", "duration": i["duration"],
            "heatmap": None, "url": "", "kind": "file"}
    proj = Project.create(path.stem)
    proj.set(source=meta, audio=None, video=str(path), video_offset=0.0, video_full=True)
    return proj


def ensure_transcript(proj: Project, cfg: dict | None = None, progress=None) -> dict:
    cfg = cfg or load_config()
    if proj.has_file("transcript"):
        return json.loads(Path(proj.get("transcript")).read_text(encoding="utf-8"))
    src = proj.get("source")
    media = proj.get("audio") or proj.get("video")
    hint = " ".join(hint_names(src["title"], src["channel"], src["description"]))
    result = transcribe(Path(media), src["id"], hint, progress, cfg)
    path = proj.dir / "расшифровка.json"
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    proj.set(transcript=str(path))
    return result


_PREFETCH: dict = {}


def start_prefetch(proj: Project, cfg: dict | None = None) -> None:
    """YouTube: сразу после звука качаем видео целиком в фоне (в 4 потока), пока идут расшифровка и чат с Claude.
    К сборке файл уже лежит на диске. Состояние проекта поток не трогает: файл подхватывает ensure_video."""
    import shutil
    import threading
    cfg = cfg or load_config()
    src = proj.get("source") or {}
    if not cfg.get("prefetch_video", True) or src.get("kind") != "youtube" or proj.has_file("video"):
        return
    if (proj.source_dir / "video.mp4").exists() or _PREFETCH.get(str(proj.dir), threading.Thread()).is_alive():
        return
    if shutil.disk_usage(proj.dir).free < 6 * 1024 ** 3:
        return                                   # мало места: останется докачка отрезка, как раньше

    def run():
        try:
            dl.fetch_full(src["url"], proj.source_dir, cfg)
        except Exception:  # noqa: BLE001 - фон не должен ничего ломать: при неудаче сборка скачает отрезок сама
            pass
    t = threading.Thread(target=run, daemon=True, name="prefetch")
    _PREFETCH[str(proj.dir)] = t
    t.start()


def _adopt_prefetch(proj: Project) -> bool:
    """Ждёт фоновую загрузку (если идёт) и подхватывает готовый video.mp4, если он целый."""
    t = _PREFETCH.get(str(proj.dir))
    if t is not None and t.is_alive():
        t.join()
    f = proj.source_dir / "video.mp4"
    src = proj.get("source") or {}
    if not f.exists():
        return False
    try:
        i = probe(f)
    except ClipperError:
        return False
    if not i["vcodec"] or not i["acodec"] or i["duration"] < (src.get("duration") or 0) - 5:
        return False
    proj.set(video=str(f), video_offset=0.0, video_len=i["duration"], video_full=True)
    return True


def ensure_video(proj: Project, a: float, b: float, cfg: dict | None = None, pad: float = 60.0) -> None:
    """Для YouTube докачивает видео отрезка ±pad секунд, если его ещё нет или отрезок не помещается."""
    cfg = cfg or load_config()
    if proj.has_file("video"):
        off = proj.get("video_offset", 0.0)
        if proj.get("video_full") or (a >= off and b <= off + proj.get("video_len", 0.0)):
            return
    src = proj.get("source")
    if not src or not src.get("url"):
        raise ClipperError("Нет видеофайла для этого проекта.", "Начни проект заново из файла.")
    if _adopt_prefetch(proj):
        return
    file, off = dl.fetch_section(src["url"], proj.source_dir, a - pad, b + pad, cfg)
    i = probe(file)
    full = off == 0.0 and i["duration"] >= (src.get("duration") or 0) - 2
    proj.set(video=str(file), video_offset=off, video_len=i["duration"], video_full=full)


def all_words(transcript: dict) -> list:
    return [w for s in transcript["segments"] for w in s["words"]]


def build_clip(proj: Project, p: Profile, a: float, b: float, *, open_span: tuple | None = None, subtitles: bool = True,
               fixes: list | None = None, crop: str | None = None, cfg: dict | None = None) -> dict:
    """Собирает ролик, проверяет, пишет пакет для чата. Возвращает итог для показа."""
    cfg = cfg or load_config()
    tr = ensure_transcript(proj, cfg)
    src = proj.get("source")
    names = hint_names(src["title"], src["channel"], src["description"])
    a, b, notes = refine_bounds(all_words(tr), a, b)          # клип начинается и заканчивается на целом предложении
    ensure_video(proj, min(a, open_span[0]) if open_span else a, max(b, open_span[1]) if open_span else b, cfg)
    spans = ([open_span] if open_span else []) + [(a, b)]
    out = proj.done_dir / f"{safe_name(src['title'], 70)}.mp4"
    r = render(Path(proj.get("video")), out, p, spans, offset=proj.get("video_offset", 0.0), words=all_words(tr),
               fixes=fixes, crop=crop, subtitles=subtitles, names=names, corrected=proj.get("subs_text"), cfg=cfg)
    r["warnings"] = notes + r["warnings"]
    checks = check_video(out, p)
    published = publish(proj.dir.name, out, cfg)
    text, doubts = build_package(rules_file=p.rules_file, url=src.get("url", ""), title=src["title"], channel=src["channel"],
                                 span=(a, b), segments=tr["segments"], names=names, fixes=fixes)
    pkg = proj.done_dir / "пакет_для_чата.txt"
    pkg.write_text(text, encoding="utf-8")
    result = {"video": str(out), "published": str(published), "package": str(pkg), "package_text": text, "checks": checks, "verdict": worst(checks),
              "doubts": len(doubts), "render": r}
    proj.set(moment={"start": a, "end": b, "open": open_span, "subtitles": subtitles, "crop": crop}, fixes=fixes or [], clip=str(out), published=str(published), package=str(pkg),
             checks=checks, verdict=result["verdict"])
    return result


def build_preview(proj: Project, p: Profile, a: float, b: float, *, open_span: tuple | None = None, subtitles: bool = True,
                  fixes: list | None = None, crop: str | None = None, cfg: dict | None = None) -> dict:
    """Быстрый предпросмотр (маленький кадр, без проверок, без «Готовых видео»): посмотреть монтаж до финальной сборки."""
    cfg = cfg or load_config()
    tr = ensure_transcript(proj, cfg)
    src = proj.get("source")
    names = hint_names(src["title"], src["channel"], src["description"])
    a, b, notes = refine_bounds(all_words(tr), a, b)
    ensure_video(proj, min(a, open_span[0]) if open_span else a, max(b, open_span[1]) if open_span else b, cfg)
    spans = ([open_span] if open_span else []) + [(a, b)]
    out = (proj.dir / "предпросмотр.mp4").resolve()
    r = render(Path(proj.get("video")), out, p, spans, offset=proj.get("video_offset", 0.0), words=all_words(tr), fixes=fixes, crop=crop,
               subtitles=subtitles, names=names, corrected=proj.get("subs_text"), preview=True, cfg=cfg)
    proj.set(preview=str(out))
    return {"notes": notes + r["warnings"], "duration": r["duration"], "start": a, "end": b}


def save_post(proj: Project, text: str) -> Path:
    path = proj.done_dir / "post.md"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    proj.set(post=str(path))
    if proj.get("published") and Path(proj.get("published")).exists():
        publish_post(Path(proj.get("published")), text)
    return path


def import_profile_rules(p: Profile) -> Path:
    path = resolve(p.rules_file)
    if not path.exists():
        raise ClipperError(f"Файл правил текста не найден: {p.rules_file}", "Верни файл в папку rules или поправь rules_file в профиле.")
    return path
