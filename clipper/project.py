"""Проект клипа: папка с state.json. Результат каждого шага на диске; шаг пропускается, если результат уже есть."""
import json
import os
from datetime import datetime
from pathlib import Path

from .errors import ClipperError
from .paths import projects_dir, safe_name


class Project:
    def __init__(self, folder: Path):
        self.dir = folder
        self.state_path = folder / "state.json"
        self.state: dict = {}
        if self.state_path.exists():
            try:
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ClipperError(f"Файл состояния проекта {folder.name} повреждён.",
                                   "Удали вручную state.json в папке проекта (остальное сохранится) и открой проект снова.") from e

    @classmethod
    def create(cls, title: str, root: Path | None = None) -> "Project":
        base = root or projects_dir()
        name = f"{datetime.now():%Y-%m-%d_%H%M}_{safe_name(title, 50)}"
        folder = base / name
        folder.mkdir(parents=True, exist_ok=False)
        for sub in ("источник", "готово"):
            (folder / sub).mkdir()
        proj = cls(folder)
        proj.state = {"created": datetime.now().isoformat(timespec="seconds"), "title": title}
        proj.save()
        return proj

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def set(self, **kw) -> None:
        self.state.update(kw)
        self.save()

    def get(self, key: str, default=None):
        return self.state.get(key, default)

    def has_file(self, key: str) -> bool:
        v = self.state.get(key)
        return bool(v) and Path(v).exists()

    @property
    def done_dir(self) -> Path:
        return self.dir / "готово"

    @property
    def source_dir(self) -> Path:
        return self.dir / "источник"


def list_projects(root: Path | None = None) -> list[Project]:
    base = root or projects_dir()
    out = []
    for d in sorted((x for x in base.iterdir() if (x / "state.json").exists()), reverse=True):
        try:
            out.append(Project(d))
        except ClipperError:
            continue
    return out
