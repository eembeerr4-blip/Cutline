"""Буфер обмена Windows через clip.exe (UTF-16, чтобы кириллица не ломалась)."""
import subprocess

from .errors import ClipperError


def copy_text(text: str) -> None:
    """Через Set-Clipboard: UTF-8 по stdin, без BOM (clip.exe добавляет невидимый символ в начало)."""
    cmd = ["powershell", "-NoProfile", "-Command",
           "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); Set-Clipboard -Value ([Console]::In.ReadToEnd())"]
    try:
        r = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ClipperError("Не удалось скопировать в буфер обмена.", "Открой файл с пакетом из папки проекта и скопируй вручную.") from e
    if r.returncode:
        raise ClipperError("Буфер обмена не принял текст.", "Открой файл с пакетом из папки проекта и скопируй вручную.")


def paste_text() -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                       capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.decode("utf-8", "replace").strip("\r\n")
