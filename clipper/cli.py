"""Меню Cutline.bat (этап 0): клип без Claude Code. Все сообщения по-русски, каждая ошибка говорит, что делать."""
import argparse
import logging
import os
import re
import traceback

from . import pipeline as pl
from .clipboard import copy_text, paste_text
from .errors import ClipperError, explain
from .moment import by_numbers, find_quote, fmt, parse_range, phrases, snap
from .paths import data_dir, load_config
from .profiles import load_profile
from .project import list_projects
from .sysinfo import diagnostics, collect, render_report
from .textcheck import check_text

TIME_RE = re.compile(r"^\d+(:\d{1,2}){0,2}(\s*[-–—]\s*\d+(:\d{1,2}){0,2})?$")
MARK = {"OK": "[ОК]       ", "WARN": "[ВНИМАНИЕ] ", "FAIL": "[ОШИБКА]   "}


def setup_log() -> None:
    logging.basicConfig(filename=str(data_dir() / "лог.txt"), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")


def show(results: list) -> None:
    for lv, msg in results:
        print(f"  {MARK[lv]}{msg}")


def progress_printer():
    last = [-1]

    def cb(x: float) -> None:
        pct = int(x * 100) // 5 * 5
        if pct != last[0]:
            last[0] = pct
            print(f"  расшифровка: {pct}%", flush=True)
    return cb


def resolve_moment(phr: list, text: str, cfg: dict, interactive: bool) -> dict:
    """Время, диапазон или цитата → границы по целым фразам."""
    tail = cfg["default_clip_tail_sec"]
    if TIME_RE.match(text.strip()):
        a, b = parse_range(text)
        return snap(phr, a, b, tail)
    hits = find_quote(phr, text)
    if not hits:
        raise ClipperError("Цитату не нашёл.", "Вставь точную английскую фразу из видео или введи время, например 12:34.")
    pick = 0
    if interactive:
        for n, h in enumerate(hits, 1):
            print(f"  {n}) {fmt(h['start'])}  совпадение {h['score']}%\n     …{h['before'][-70:]} | {h['text'][:140]} | {h['after'][:70]}…")
        s = input("Какое место? (номер, Enter = 1, 0 = заново): ").strip()
        if s == "0":
            raise ClipperError("Отменено.", "Введи момент заново.")
        pick = int(s) - 1 if s.isdigit() and 1 <= int(s) <= len(hits) else 0
    return snap(phr, hits[pick]["start"], None, tail)


def clip_flow(proj, cfg: dict, p) -> None:
    print("\nШаг 1 из 4. Расшифровка (при первом запуске долго; видеопамять освобождается сама)…")
    tr = pl.ensure_transcript(proj, cfg, progress_printer())
    for w in tr.get("warnings", []):
        print(f"  [ВНИМАНИЕ] {w}")
    phr = phrases(tr["segments"])
    print(f"  готово: {len(phr)} фраз, модель {tr['model']} на {tr['device']}")
    while True:
        text = input("\nШаг 2 из 4. Момент: время (12:34 или 12:34-16:40) или цитата из видео по-английски: ").strip()
        try:
            m = resolve_moment(phr, text, cfg, True)
        except ClipperError as e:
            print(explain(e))
            continue
        dur = m["end"] - m["start"]
        print(f"  Отрезок {fmt(m['start'])}-{fmt(m['end'])}, длина {fmt(dur)}\n  Начало: {phr[m['first']]['text'][:100]}\n  Конец:  {phr[m['last']]['text'][:100]}")
        if not p.clip_len_sec[0] <= dur <= p.clip_len_sec[1]:
            print(f"  [ВНИМАНИЕ] длина вне окна {fmt(p.clip_len_sec[0])}-{fmt(p.clip_len_sec[1])}")
        if input("  Подходит? (Enter = да, любая буква = выбрать заново): ").strip() == "":
            break
    open_span = None
    o = input("Холодное начало (самый сильный кусок вперёд), время, например 20:10-20:25. Enter = без него: ").strip()
    if o:
        a, b = parse_range(o)
        s = snap(phr, a, b)
        open_span = (s["start"], s["end"])
    subs = input("Субтитры? (Enter = да, н = без): ").strip().lower() not in ("н", "n", "нет")
    print("\nШаг 3 из 4. Собираю ролик…")
    res = pl.build_clip(proj, p, m["start"], m["end"], open_span=open_span, subtitles=subs, cfg=cfg)
    show(res["checks"])
    for w in res["render"]["warnings"]:
        print(f"  [ВНИМАНИЕ] {w}")
    print(f"  Ролик: {res['video']}")
    copy_text(res["package_text"])
    print(f"\nШаг 4 из 4. Пакет для чата СКОПИРОВАН в буфер ({res['doubts']} слов стоит проверить на слух).")
    print("  Вставь его в чат с Claude, ответ скопируй и выбери в меню пункт 4 (проверка текста).")


def post_flow(proj) -> None:
    p = load_profile(load_config()["profile"])
    print("Скопируй ответ Claude в буфер обмена и нажми Enter…")
    input()
    text = paste_text()
    if not text.strip():
        raise ClipperError("Буфер обмена пуст.", "Скопируй ответ Claude целиком и повтори.")
    results, stats = check_text(p.text_check, text)
    show(results)
    if stats:
        print(f"  слов {stats['words']}, цитат {stats['quotes']}")
    if proj and input("Сохранить как post.md в папку проекта? (Enter = да, н = нет): ").strip().lower() not in ("н", "n"):
        print("  Сохранено:", pl.save_post(proj, text))
        os.startfile(proj.done_dir)  # noqa: S606 - открыть папку с готовым


def choose_project():
    items = list_projects()[:15]
    if not items:
        print("Проектов пока нет.")
        return None
    for n, pr in enumerate(items, 1):
        print(f"  {n}) {pr.dir.name}")
    s = input("Номер проекта (Enter = отмена): ").strip()
    return items[int(s) - 1] if s.isdigit() and 1 <= int(s) <= len(items) else None


def menu() -> int:
    cfg = load_config()
    p = load_profile(cfg["profile"])
    while True:
        print(f"\n=== РЕЗАК (профиль {p.title}) ===\n 1  Новый клип из ссылки\n 2  Новый клип из файла\n 3  Продолжить проект\n"
              " 4  Проверить текст поста (из буфера)\n 5  Система: всё ли работает\n 0  Выход")
        c = input("Выбери номер: ").strip()
        try:
            if c in ("1", "2"):
                src = input("Вставь ссылку: " if c == "1" else "Перетащи файл сюда и нажми Enter: ").strip()
                if src:
                    clip_flow(pl.new_project(src, cfg), cfg, p)
            elif c == "3":
                pr = choose_project()
                if pr:
                    clip_flow(pr, cfg, p)
            elif c == "4":
                post_flow(choose_project())
            elif c == "5":
                print(render_report(collect(cfg)))
                if input("Скопировать диагностику для чата? (Enter = да, н = нет): ").strip().lower() not in ("н", "n"):
                    copy_text(diagnostics(cfg))
                    print("  Скопировано.")
            elif c == "0":
                return 0
        except KeyboardInterrupt:
            print("\nПрервано.")
        except Exception as e:  # noqa: BLE001 - центральная обработка: человеку понятный текст, подробности в лог
            logging.error("menu action %s failed\n%s", c, traceback.format_exc())
            print("\n" + explain(e))
            if isinstance(e, ClipperError) and e.details:
                print("  Подробности:", e.details[-400:])


def main(argv: list) -> int:
    setup_log()
    ap = argparse.ArgumentParser(prog="clipper")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("clip", help="клип без вопросов: источник и момент в аргументах")
    c.add_argument("source")
    c.add_argument("--at", required=True, help="время, диапазон или цитата")
    c.add_argument("--open", dest="open_at")
    c.add_argument("--no-subs", action="store_true")
    c.add_argument("--profile")
    k = sub.add_parser("check-post")
    k.add_argument("file")
    sub.add_parser("doctor")
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        if args.cmd == "clip":
            p = load_profile(args.profile or cfg["profile"])
            proj = pl.new_project(args.source, cfg)
            tr = pl.ensure_transcript(proj, cfg, progress_printer())
            phr = phrases(tr["segments"])
            m = resolve_moment(phr, args.at, cfg, False)
            op = None
            if args.open_at:
                s = snap(phr, *parse_range(args.open_at))
                op = (s["start"], s["end"])
            res = pl.build_clip(proj, p, m["start"], m["end"], open_span=op, subtitles=not args.no_subs, cfg=cfg)
            print(f"Отрезок {fmt(m['start'])}-{fmt(m['end'])}\nРолик: {res['video']}\nПакет: {res['package']}")
            show(res["checks"])
            return 0 if res["verdict"] != "FAIL" else 2
        if args.cmd == "check-post":
            from pathlib import Path
            results, stats = check_text(load_profile(cfg["profile"]).text_check, Path(args.file).read_text(encoding="utf-8"))
            show(results)
            return 1 if any(lv == "FAIL" for lv, _ in results) else 0
        if args.cmd == "doctor":
            print(diagnostics(cfg))
            return 0
        return menu()
    except Exception as e:  # noqa: BLE001
        logging.error("failed\n%s", traceback.format_exc())
        print(explain(e))
        return 1
