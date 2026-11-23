"""Запуск Cutline: сервер на 127.0.0.1 + собственное окно приложения (pywebview, компонент WebView2 из Windows).
Браузер не запускается. Если окно создать нельзя, запасной вариант: окно Chrome/Edge в режиме --app."""
import ctypes
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .paths import ROOT, data_dir, load_config
from .server import create_app

BROWSERS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
IDLE_EXIT_SEC = 180   # запасной вариант (окно в браузере): выходим, если окно пропало
BYE_GRACE_SEC = 6
APP_ID = "Cutline.App"
ICON = ROOT / "assets" / "logo.ico"


def free_port(start: int) -> int:
    """Порт из config.json; если он ещё занят закрывающейся копией, ждём до 8 секунд."""
    for _ in range(16):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", start)) != 0:
                return start
        time.sleep(0.5)
    for port in range(start + 1, start + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Нет свободного порта рядом с настроенным.")


def saved_geometry() -> dict | None:
    try:
        pos = json.loads((data_dir() / "окно.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return pos if pos.get("w", 0) >= 700 and pos.get("h", 0) >= 450 else None


def save_geometry(**kw) -> None:
    try:
        path = data_dir() / "окно.json"
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cur = {}
        cur.update(kw)
        path.write_text(json.dumps(cur), encoding="utf-8")
    except OSError:
        pass


HWNDS: list = []   # окно Cutline (найдено после запуска)


class _WP(ctypes.Structure):   # WINDOWPLACEMENT: обычный (не развёрнутый) прямоугольник окна + развёрнуто ли
    from ctypes import wintypes as _w
    _fields_ = [("length", _w.UINT), ("flags", _w.UINT), ("showCmd", _w.UINT), ("ptMin", _w.POINT), ("ptMax", _w.POINT), ("rc", _w.RECT)]


def snapshot(*_args) -> None:
    """Записывает полное положение окна у Windows: место, размер, развёрнуто ли. Свёрнутое в панель задач не записываем."""
    if not HWNDS:
        return
    wp = _WP()
    wp.length = ctypes.sizeof(_WP)
    if not ctypes.windll.user32.GetWindowPlacement(HWNDS[0], ctypes.byref(wp)) or wp.showCmd == 2:
        return
    r = wp.rc
    save_geometry(x=r.left, y=r.top, w=r.right - r.left, h=r.bottom - r.top, max=wp.showCmd == 3)


def set_window_icon(title: str) -> None:
    """Значок окна и панели задач средствами Windows (WM_SETICON), без .NET: так он ставится из любого потока."""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    u32.LoadImageW.restype = wintypes.HANDLE
    u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    pid, found = os.getpid(), HWNDS

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        buf = ctypes.create_unicode_buffer(64)
        u32.GetWindowTextW(hwnd, buf, 64)
        if owner.value == pid and buf.value == title:
            found.append(hwnd)
        return True

    for _ in range(50):   # окно появляется не сразу
        u32.EnumWindows(each, 0)
        if found:
            break
        time.sleep(0.1)
    if not found:
        logging.warning("окно для значка не найдено")
        return
    for size, kind in ((16, 0), (48, 1)):   # ICON_SMALL=0 (заголовок), ICON_BIG=1 (панель задач, Alt+Tab)
        h = u32.LoadImageW(None, str(ICON), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            for hwnd in found:
                u32.SendMessageW(hwnd, 0x80, kind, h)   # WM_SETICON


def run_native(url: str) -> bool:
    """Собственное окно приложения. False, если pywebview или WebView2 недоступны (тогда запасной вариант)."""
    try:
        import webview
    except ImportError:
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)   # своя группа и значок на панели задач
    except Exception:  # noqa: BLE001
        pass
    geo = saved_geometry()
    kw = {"min_size": (900, 600), "background_color": "#000000"}
    if geo:   # обычный размер помним всегда: кнопка «свернуть в окно» вернёт именно его
        kw.update(x=geo["x"], y=geo["y"], width=geo["w"], height=geo["h"], maximized=bool(geo.get("max")))
    else:
        kw.update(width=1280, height=860, maximized=True)   # самый первый запуск: на весь экран
    win = webview.create_window("Cutline", url, **kw)
    for ev in (win.events.moved, win.events.resized, win.events.maximized, win.events.restored, win.events.closing):
        ev += snapshot

    def after_start():
        set_window_icon("Cutline")
        snapshot()

    try:
        webview.start(after_start, gui="edgechromium", storage_path=str(data_dir() / "окно-webview"))
    except Exception:  # noqa: BLE001
        logging.exception("окно приложения не запустилось")
        return False
    return True


def find_browser() -> str | None:
    local = os.environ.get("LOCALAPPDATA", "")
    extra = [str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe")]
    return next((p for p in list(BROWSERS[:2]) + extra + list(BROWSERS[2:]) if Path(p).exists()), None) or shutil.which("chrome") or shutil.which("msedge")


def run_in_browser(url: str, app) -> None:
    """Запасной вариант: окно браузера без вкладок. Закрывается вместе с окном (сигнал bye или тишина)."""
    exe = find_browser()
    if not exe:
        webbrowser.open(url)
    else:
        geo = saved_geometry()
        args = [exe, f"--app={url}", f"--user-data-dir={data_dir() / 'окно'}", "--no-first-run", "--no-default-browser-check"]
        args += ([f"--window-position={geo['x']},{geo['y']}", f"--window-size={geo['w']},{geo['h']}"] if geo and not geo.get("max") else ["--start-maximized"])
        subprocess.Popen(args)
    started, st = time.time(), app.state.last_ping
    while True:
        time.sleep(1)
        now = time.time()
        if st.get("bye") and now - st["bye"] > BYE_GRACE_SEC and st["last_ping"] < st["bye"]:
            break
        if now - (st["last_ping"] or started) > IDLE_EXIT_SEC:
            break


def main() -> None:
    for name in ("stdout", "stderr"):  # pythonw: потоков нет
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    logging.basicConfig(filename=str(data_dir() / "лог.txt"), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    port = free_port(cfg["port"])
    app = create_app(secrets.token_urlsafe(24), port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)
    if cfg.get("preload_model", True):
        from .transcribe import warm_up
        threading.Thread(target=warm_up, args=(cfg,), daemon=True, name="warm").start()
    url = f"http://127.0.0.1:{port}/"
    if not run_native(url):
        run_in_browser(url, app)
    server.should_exit = True
    os._exit(0)   # окно закрыто: сервер и модель выгружаются, видеопамять и порт свободны


if __name__ == "__main__":
    main()
