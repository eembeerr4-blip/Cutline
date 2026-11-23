"""Лёгкий запускатор для Cutline.exe: только стартует окно из .venv, код и модели внутрь не упакованы."""
import ctypes
import subprocess
import sys
from pathlib import Path

root = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
if not getattr(sys, "frozen", False):
    root = root.parent
py = root / ".venv" / "Scripts" / "pythonw.exe"
if not py.exists():
    ctypes.windll.user32.MessageBoxW(0, "Не найдено окружение .venv. Запусти Cutline.bat или пришли описание в чат.", "Cutline", 0x10)
    sys.exit(1)
subprocess.Popen([str(py), "-m", "clipper.launch"], cwd=str(root), env={**__import__("os").environ, "PYTHONUTF8": "1"},
                 creationflags=0x08000000)
