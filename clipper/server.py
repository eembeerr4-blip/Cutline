"""Локальный сервер окна: только 127.0.0.1, токен сессии, проверка Host и Origin на каждый запрос к API."""
import json
import logging
import os
import secrets
import subprocess
import sys
import time
import webbrowser
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import pipeline as pl
from .claude_reply import chat_package, link_request, parse_reply
from .clipboard import copy_text
from . import history, storage
from .errors import ClipperError, explain
from .ffmpeg import frame_png, probe
from .jobs import JobRunner
from .moment import find_quote, fmt, parse_range, phrases, snap
from .publish import output_dir
from .package import doubtful_words, hint_names
from .paths import ROOT, data_dir, load_config, projects_dir
from .profiles import load_profile
from .project import Project, list_projects
from .sysinfo import collect, diagnostics
from .textcheck import check_text, normalize_post

STATIC = ROOT / "clipper" / "static"
TIME_CHARS = set("0123456789:-–— .")


def create_app(token: str, port: int) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    cfg = load_config()
    runner = JobRunner()
    state = {"last_ping": 0.0}
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in hosts}

    def proj(name: str) -> Project:
        if Path(name).name != name or not (projects_dir() / name / "state.json").exists():
            raise ClipperError("Проект не найден.", "Выбери проект из списка на вкладке «История».")
        return Project(projects_dir() / name)

    def tr_phr(p: Project) -> tuple[dict, list]:
        tr = pl.ensure_transcript(p, cfg)
        return tr, phrases(tr["segments"])

    def summary(p: Project) -> dict:
        s = p.get("source") or {}
        return {"name": p.dir.name, "title": s.get("title", ""), "channel": s.get("channel", ""), "kind": s.get("kind"),
                "duration": s.get("duration"), "has_transcript": p.has_file("transcript"), "moment": p.get("moment"),
                "clip": bool(p.get("clip")), "verdict": p.get("verdict"), "checks": p.get("checks"), "post": bool(p.get("post")), "heatmap": s.get("heatmap"), "fixes": p.get("fixes", []), "post_draft": p.get("post_draft"), "published": p.get("published"),
                "created": p.get("created")}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host", "") not in hosts:
            return JSONResponse({"what": "Чужой адрес запроса.", "hint": "Открой Cutline только через его окно."}, status_code=403)
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            tok = request.headers.get("x-token") or request.query_params.get("t") or ""
            if (origin and origin not in origins) or not secrets.compare_digest(tok, token):
                return JSONResponse({"what": "Запрос отклонён: нет доступа.", "hint": "Закрой окно и запусти Cutline заново."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ClipperError)
    async def on_clipper(_, e: ClipperError):
        return JSONResponse({"what": e.what, "hint": e.hint, "details": e.details[-500:]}, status_code=400)

    @app.exception_handler(Exception)
    async def on_any(_, e: Exception):
        logging.error("api error\n%s", traceback.format_exc())
        return JSONResponse({"what": explain(e), "hint": "Скопируй диагностику на вкладке «Система» и пришли в чат."}, status_code=500)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)

    @app.get("/api/ping")
    def ping():
        state["last_ping"] = time.time()
        p = load_profile(cfg["profile"])
        return {"ok": True, "profile": p.title, "window": list(p.clip_len_sec), "subs_default": cfg.get("subtitles_default", True)}

    @app.post("/api/bye")
    def bye():
        state["bye"] = time.time()
        return {"ok": True}

    @app.post("/api/window")
    async def window_state(req: Request):
        b = await req.json()
        keep = {k: int(b[k]) for k in ("x", "y", "w", "h") if k in b} | {"max": bool(b.get("max"))}
        (data_dir() / "окно.json").write_text(json.dumps(keep), encoding="utf-8")
        return {"ok": True}

    @app.get("/api/job/{jid}")
    def job(jid: str):
        j = runner.jobs.get(jid)
        if not j:
            raise ClipperError("Задача не найдена.", "Повтори действие.")
        return j.view()

    @app.post("/api/new")
    async def new(req: Request):
        source = (await req.json()).get("source", "").strip()
        if not source:
            raise ClipperError("Источник пустой.", "Вставь ссылку или выбери файл.")

        def work(j):
            p = pl.new_project(source, cfg, j.log)
            j.log("Расшифровка…")
            pl.start_prefetch(p, cfg)   # видео качается в фоне, пока идут расшифровка и чат с Claude
            pl.ensure_transcript(p, cfg, lambda x: setattr(j, "progress", x))
            return summary(p)
        return runner.start("Источник и расшифровка", work).view()

    @app.post("/api/pick_file")
    def pick_file():
        code = ("import tkinter as t, tkinter.filedialog as f; r=t.Tk(); r.withdraw(); r.attributes('-topmost',True);"
                "print(f.askopenfilename(title='Выбери видео', filetypes=[('Видео и звук','*.mp4 *.mkv *.mov *.webm *.avi *.m4a *.mp3 *.wav'),('Все файлы','*.*')]))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"}).stdout.strip()
        return {"path": out}

    @app.post("/api/upload")
    async def upload(req: Request, name: str = "video.mp4"):
        folder = data_dir() / "загрузки"
        folder.mkdir(exist_ok=True)
        dest = folder / f"{int(time.time())}_{Path(name).name}"
        with dest.open("wb") as f:
            async for chunk in req.stream():
                f.write(chunk)
        return {"path": str(dest)}

    @app.get("/api/projects")
    def projects():
        return [summary(p) for p in list_projects()]

    @app.get("/api/project/{name}")
    def one(name: str):
        return summary(proj(name))

    @app.get("/api/project/{name}/phrases")
    def get_phrases(name: str):
        _, phr = tr_phr(proj(name))
        return [{"i": x["i"], "start": x["start"], "end": x["end"], "text": x["text"]} for x in phr]

    @app.post("/api/project/{name}/moment")
    async def moment(name: str, req: Request):
        text = (await req.json()).get("text", "").strip()
        _, phr = tr_phr(proj(name))
        tail = cfg["default_clip_tail_sec"]
        if text and set(text) <= TIME_CHARS:
            a, b = parse_range(text)
            return {"kind": "time", "hits": [snap(phr, a, b, tail)]}
        hits = find_quote(phr, text)
        if not hits:
            raise ClipperError("Цитату не нашёл.", "Вставь точную английскую фразу из видео или введи время, например 12:34.")
        return {"kind": "quote", "hits": [{**snap(phr, h["start"], None, tail), "score": h["score"], "text": h["text"],
                                           "before": h["before"], "after": h["after"]} for h in hits]}

    @app.get("/api/project/{name}/for_claude")
    def for_claude(name: str):
        p = proj(name)
        _, phr = tr_phr(p)
        prof = load_profile(cfg["profile"])
        s = p.get("source")
        rules = pl.import_profile_rules(prof).read_text(encoding="utf-8")
        return {"text": chat_package(phr, rules_md=rules, title=s["title"], channel=s["channel"], url=s.get("url", ""),
                                     window=prof.clip_len_sec)}

    @app.get("/api/project/{name}/link_request")
    def link_req(name: str):
        p = proj(name)
        prof = load_profile(cfg["profile"])
        s = p.get("source")
        if not s.get("url"):
            raise ClipperError("У этого проекта нет ссылки: он начат из файла.", "Используй «Скопировать всю расшифровку»: она работает и без ссылки.")
        rules = pl.import_profile_rules(prof).read_text(encoding="utf-8")
        return {"text": link_request(rules_md=rules, title=s["title"], channel=s["channel"], url=s["url"], window=prof.clip_len_sec)}

    @app.post("/api/project/{name}/claude_reply")
    async def claude_reply(name: str, req: Request):
        text = (await req.json()).get("text", "")
        p = proj(name)
        _, phr = tr_phr(p)
        prof = load_profile(cfg["profile"])
        r = parse_reply(text, phr, prof.clip_len_sec)
        r["post_checks"] = check_text(prof.text_check, r["post"])[0] if r["post"] else []
        if r["post"]:
            p.set(post_draft=r["post"])   # текст подставится на шаге «Текст»
        p.set(subs_text=r["subs_text"] or None)   # пунктуация субтитров от Claude (если прислал)
        return r

    @app.post("/api/project/{name}/build")
    async def build(name: str, req: Request):
        body = await req.json()
        p = proj(name)
        prof = load_profile(cfg["profile"])
        a, b = float(body["start"]), float(body["end"])
        op = tuple(body["open"]) if body.get("open") else None

        def work(j):
            j.log("Собираю ролик (видео отрезка, субтитры, громкость)…")
            r = pl.build_clip(p, prof, a, b, open_span=op, subtitles=bool(body.get("subtitles", True)),
                              fixes=[tuple(f) for f in body.get("fixes", [])], crop=body.get("crop") or None, cfg=cfg)
            dupes = [d["text"] for d in history.overlaps(p.get("source")["id"], a, b, exclude=p.dir.name)]
            return {k: r[k] for k in ("checks", "verdict", "doubts", "published")} | {"warnings": r["render"]["warnings"] + dupes, "package": r["package_text"]}
        return runner.start("Сборка ролика", work).view()

    @app.post("/api/project/{name}/preview")
    async def preview(name: str, req: Request):
        body = await req.json()
        p = proj(name)
        prof = load_profile(cfg["profile"])
        a, b = float(body["start"]), float(body["end"])
        op = tuple(body["open"]) if body.get("open") else None

        def work(j):
            j.log("Собираю предпросмотр (быстро, в низком качестве)…")
            return pl.build_preview(p, prof, a, b, open_span=op, subtitles=bool(body.get("subtitles", True)),
                                    fixes=[tuple(f) for f in body.get("fixes", [])], crop=body.get("crop") or None, cfg=cfg)
        return runner.start("Предпросмотр", work).view()

    @app.get("/api/project/{name}/preview_video")
    def preview_video(name: str):
        p = proj(name)
        if not (p.get("preview") and Path(p.get("preview")).exists()):
            raise ClipperError("Предпросмотра ещё нет.", "Нажми «Предпросмотр» на шаге «Монтаж».")
        return FileResponse(p.get("preview"), media_type="video/mp4")

    @app.get("/api/project/{name}/video")
    def video(name: str):
        p = proj(name)
        if not p.has_file("clip"):
            raise ClipperError("Ролика ещё нет.", "Сначала собери ролик на шаге 3.")
        return FileResponse(p.get("clip"), media_type="video/mp4")

    @app.get("/api/project/{name}/package")
    def package(name: str):
        p = proj(name)
        if not p.has_file("package"):
            raise ClipperError("Пакет ещё не собран.", "Сначала собери ролик на шаге 3.")
        return {"text": Path(p.get("package")).read_text(encoding="utf-8")}

    @app.post("/api/project/{name}/post")
    async def post(name: str, req: Request):
        body = await req.json()
        p = proj(name)
        prof = load_profile(cfg["profile"])
        text = normalize_post(body.get("text", ""))
        results, stats = check_text(prof.text_check, text)
        saved = False
        if body.get("save") and not any(lv == "FAIL" for lv, _ in results):
            pl.save_post(p, text)
            saved = True
        return {"results": results, "stats": stats, "saved": saved, "text": text}

    @app.post("/api/project/{name}/open_folder")
    def open_folder(name: str):
        p = proj(name)
        pub = p.get("published")
        if pub and Path(pub).exists():   # открыть папку «Готовые видео» с выделенным файлом
            subprocess.Popen(f'explorer.exe /select,"{pub}"')
        else:
            os.startfile(p.done_dir)  # noqa: S606
        return {"ok": True, "path": pub or str(p.done_dir)}

    @app.post("/api/open_output")
    def open_output():
        d = output_dir(cfg)
        os.startfile(d)  # noqa: S606
        return {"ok": True, "path": str(d)}

    @app.post("/api/copy")
    async def copy(req: Request):
        copy_text((await req.json()).get("text", ""))
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings():
        return {"output_dir": str(output_dir(cfg)), "whisper_model": cfg["whisper_model"], "subtitles_default": cfg.get("subtitles_default", True)}

    @app.post("/api/settings")
    async def set_settings(req: Request):
        b = await req.json()
        new = {}
        if b.get("output_dir"):
            d = Path(b["output_dir"])
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ClipperError("Не могу создать эту папку.", "Выбери существующий диск и папку, например D:\\Готовые видео.") from e
            new["output_dir"] = str(d)
        if b.get("whisper_model") in ("large-v3-turbo", "medium", "small"):
            new["whisper_model"] = b["whisper_model"]
        new["subtitles_default"] = bool(b.get("subtitles_default", True))
        path = ROOT / "config.json"
        cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        cur.update(new)
        path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        cfg.update(new)
        return get_settings()

    @app.get("/api/system")
    def system():
        return [{"status": s, "name": n, "detail": d} for s, n, d in collect(cfg)]

    @app.get("/api/diagnostics")
    def diag():
        return {"text": diagnostics(cfg)}

    @app.post("/api/project/{name}/prepare")
    async def prepare(name: str, req: Request):
        body = await req.json()
        p = proj(name)
        a, b = float(body["start"]), float(body["end"])

        def work(j):
            j.log("Готовлю видео для монтажа…")
            pl.ensure_video(p, min(a, body.get("open_start", a)), max(b, body.get("open_end", b)), cfg)
            i = probe(Path(p.get("video")))
            return {"offset": p.get("video_offset", 0.0), "duration": i["duration"], "width": i["width"], "height": i["height"]}
        return runner.start("Видео для монтажа", work).view()

    @app.get("/api/project/{name}/source")
    def source(name: str):
        p = proj(name)
        if not p.has_file("video"):
            raise ClipperError("Видеофайла для монтажа ещё нет.", "Нажми «Дальше: монтаж» на шаге 2.")
        return FileResponse(p.get("video"))

    @app.get("/api/project/{name}/frame")
    def frame(name: str, at: float):
        p = proj(name)
        if not p.has_file("video"):
            raise ClipperError("Видеофайла для кадра ещё нет.", "Нажми «Дальше: монтаж» на шаге 2.")
        return Response(frame_png(Path(p.get("video")), at - p.get("video_offset", 0.0)), media_type="image/png")

    @app.post("/api/project/{name}/doubts")
    async def doubts(name: str, req: Request):
        body = await req.json()
        p = proj(name)
        tr, _ = tr_phr(p)
        s = p.get("source")
        names = hint_names(s["title"], s["channel"], s["description"])
        spans = [(float(body["start"]), float(body["end"]))] + ([tuple(body["open"])] if body.get("open") else [])
        out = [d for a, b in spans for d in doubtful_words(tr["segments"], a, b, names)]
        return sorted(out, key=lambda d: d["t"])[:120]

    @app.get("/api/storage")
    def storage_info():
        d = data_dir()
        import shutil
        return {"projects": storage.list_projects_info(d), "trash": storage.list_trash(d), "total": storage.dir_size(d),
                "free": shutil.disk_usage(d).free}

    def _trash(fn):
        ids = fn()
        return {"moved": len(ids)}

    @app.post("/api/storage/trash")
    async def storage_trash(req: Request):
        body = await req.json()
        return _trash(lambda: storage.trash_sources(body.get("names", []), data_dir(), bool(body.get("whole"))))

    @app.post("/api/storage/older")
    async def storage_older(req: Request):
        days = int((await req.json()).get("days", 30))
        return _trash(lambda: storage.trash_older(days, data_dir()))

    @app.post("/api/storage/cache")
    def storage_cache():
        return _trash(lambda: storage.trash_cache(data_dir()))

    @app.post("/api/storage/restore")
    async def storage_restore(req: Request):
        storage.restore((await req.json())["id"], data_dir())
        return {"ok": True}

    @app.post("/api/storage/purge")
    async def storage_purge(req: Request):
        body = await req.json()
        return {"freed": storage.purge(body.get("ids", []), int(body.get("confirm_bytes", -1)), data_dir())}

    @app.post("/api/project/{name}/dupes")
    async def dupes(name: str, req: Request):
        body = await req.json()
        p = proj(name)
        return history.overlaps(p.get("source")["id"], float(body["start"]), float(body["end"]), exclude=p.dir.name)

    @app.post("/api/update_downloader")
    def update_downloader():
        def work(j):
            j.log("Обновляю yt-dlp…")
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
            if r.returncode:
                raise ClipperError("Загрузчик не обновился.", "Проверь интернет и повтори.", details=r.stderr[-400:])
            return {"text": (r.stdout.strip().splitlines() or ["готово"])[-1]}
        return runner.start("Обновление загрузчика", work).view()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.state.last_ping = state
    return app
