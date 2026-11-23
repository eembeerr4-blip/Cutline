"""Хранилище: размеры, корзина внутри приложения, возврат и окончательное удаление.

Ничего не удаляется без явного действия: «в корзину» только переносит файлы, окончательное удаление
требует отдельного подтверждения с размером. По умолчанию уходят исходники, готовый ролик, post.md и state.json остаются.
"""
import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from .errors import ClipperError
from .paths import data_dir


def dir_size(p: Path) -> int:
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _trash(root: Path) -> Path:
    d = root / "корзина"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _projects(root: Path) -> Path:
    d = root / "проекты"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state(folder: Path) -> dict:
    try:
        return json.loads((folder / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def source_paths(folder: Path, root: Path) -> list[Path]:
    """Тяжёлое, что можно убрать: папка источника проекта и загруженный файл (если лежит в data\\загрузки)."""
    out = [folder / "источник"] if dir_size(folder / "источник") > 0 else []
    uploads = (root / "загрузки").resolve()
    st = _state(folder)
    for key in ("video", "audio"):
        v = st.get(key)
        if v and Path(v).exists() and uploads in Path(v).resolve().parents:
            out.append(Path(v))
    return out


def move_to_trash(label: str, project: str, kind: str, paths: list[Path], root: Path) -> str | None:
    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    tid = f"{datetime.now():%Y%m%d-%H%M%S}_{label}"[:90]
    folder = _trash(root) / tid
    (folder / "files").mkdir(parents=True)
    moves = []
    for n, p in enumerate(paths):
        dest = folder / "files" / str(n)
        shutil.move(str(p), str(dest))
        moves.append({"orig": str(p), "stored": f"files/{n}", "dir": dest.is_dir()})
    (folder / "meta.json").write_text(json.dumps({"project": project, "kind": kind, "moved_at": time.time(), "moves": moves},
                                                 ensure_ascii=False), encoding="utf-8")
    return tid


def list_projects_info(root: Path | None = None) -> list[dict]:
    root = root or data_dir()
    out = []
    for d in sorted(_projects(root).iterdir(), reverse=True):
        if not (d / "state.json").exists():
            continue
        st = _state(d)
        out.append({"name": d.name, "title": st.get("title", d.name), "created": st.get("created", ""),
                    "size": dir_size(d), "source_size": sum(dir_size(p) for p in source_paths(d, root)),
                    "clip_size": dir_size(d / "готово"), "clip_size": dir_size(d / "готово"), "has_clip": bool(st.get("clip")), "has_post": bool(st.get("post"))})
    return out


def trash_sources(names: list[str], root: Path | None = None, whole: bool = False) -> list[str]:
    root = root or data_dir()
    ids = []
    for n in names:
        if Path(n).name != n or not (_projects(root) / n / "state.json").exists():
            raise ClipperError(f"Проект «{n}» не найден.", "Обнови список и выбери заново.")
        folder = _projects(root) / n
        if whole:
            tid = move_to_trash(n[:40], n, "all", [folder], root)
        else:
            tid = move_to_trash(n[:40] + "_исходники", n, "sources", source_paths(folder, root), root)
        if tid:
            ids.append(tid)
    return ids


def trash_older(days: int, root: Path | None = None) -> list[str]:
    root = root or data_dir()
    limit = datetime.now() - timedelta(days=days)
    names = []
    for p in list_projects_info(root):
        try:
            if p["source_size"] and datetime.fromisoformat(p["created"]) < limit:
                names.append(p["name"])
        except ValueError:
            continue
    return trash_sources(names, root)


def trash_cache(root: Path | None = None) -> list[str]:
    """Кэш скачанных видео и звука = исходники всех проектов и загруженные файлы. Расшифровки не трогаем."""
    root = root or data_dir()
    ids = trash_sources([p["name"] for p in list_projects_info(root) if p["source_size"]], root)
    loose = [f for f in (root / "загрузки").glob("*")] if (root / "загрузки").exists() else []
    tid = move_to_trash("загрузки", "", "uploads", loose, root)
    return ids + ([tid] if tid else [])


def list_trash(root: Path | None = None) -> list[dict]:
    root = root or data_dir()
    out = []
    for d in sorted(_trash(root).iterdir(), reverse=True):
        mp = d / "meta.json"
        if mp.exists():
            m = json.loads(mp.read_text(encoding="utf-8"))
            out.append({"id": d.name, "project": m["project"], "kind": m["kind"], "size": dir_size(d / "files"),
                        "moved": datetime.fromtimestamp(m["moved_at"]).isoformat(timespec="minutes")})
    return out


def restore(tid: str, root: Path | None = None) -> None:
    root = root or data_dir()
    folder = _trash(root) / tid
    if Path(tid).name != tid or not (folder / "meta.json").exists():
        raise ClipperError("Этого элемента в корзине нет.", "Обнови список корзины.")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    for m in meta["moves"]:
        if Path(m["orig"]).exists():
            raise ClipperError(f"На месте уже есть {Path(m['orig']).name}: вернуть нельзя без перезаписи.",
                               "Переименуй или перенеси существующее и повтори.")
    for m in meta["moves"]:
        Path(m["orig"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder / m["stored"]), m["orig"])
    shutil.rmtree(folder)


def _force(func, path, _exc):
    """Файл только для чтения мешает удалению на Windows: снимаем атрибут и пробуем ещё раз."""
    import os
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


def purge(ids: list[str], confirm_bytes: int, root: Path | None = None) -> int:
    """Окончательное удаление только из корзины. confirm_bytes должен совпасть с реальным размером (человек видел цифру)."""
    root = root or data_dir()
    folders = []
    for tid in ids:
        f = _trash(root) / tid
        if Path(tid).name != tid or not (f / "meta.json").exists():
            raise ClipperError("Этого элемента в корзине нет.", "Обнови список корзины.")
        folders.append(f)
    total = sum(dir_size(f / "files") for f in folders)
    if int(confirm_bytes) != total:
        raise ClipperError("Размер для подтверждения не совпал с реальным.", "Обнови список и подтверди удаление снова.")
    for f in folders:
        shutil.rmtree(f, onerror=_force)
    return total
