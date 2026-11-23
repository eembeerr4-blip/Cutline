"""Один заход в чат: Claude получает всю расшифровку с номерами фраз и правила, а в ответ даёт
границы клипа (START/END, по желанию OPEN) и сразу готовый пост. Код проверяет номера, длину, пересечения
и что цитаты из поста дословно звучат в выбранном куске. Понимает и «свободный» ответ: время вместо номеров,
английский пост среди пояснений."""
import re

from .errors import ClipperError
from .moment import by_numbers, fmt, parse_time, snap
from .package import strip_front_matter
from .textcheck import extract_quotes, normalize_post

HEAD = """ВАЖНО: твой ответ читает программа «Cutline», а не человек. Ответь СТРОГО по шаблону ниже:
без заголовков, пояснений, списков, ссылок и оценок до шаблона и после него.

=== ШАБЛОН ОТВЕТА ===
START: <номер первой фразы клипа из расшифровки, только число>
END: <номер последней фразы клипа, только число>
OPEN: <номер-номер> (эту строку можно не писать: самый сильный кусок для холодного начала, вне основного отрезка)
ПОСТ:
<готовый пост на английском по правилам ниже>
---
RU: <перевод поста на русский>
СУБТИТРЫ:
<вся речь твоего клипа по порядку, то есть сначала OPEN (если есть), потом START-END, слово в слово, только с правильными знаками препинания и заглавными буквами>

=== ОБРАЗЕЦ НАЧАЛА ОТВЕТА ===
START: 395
END: 418
ПОСТ:
Flea handed him the perfect line, and he passed on it.

=== ТРЕБОВАНИЯ ===
1. Выбери один отрезок длиной {lo}-{hi}: конфликт или поворот, цифры и детали. Начало и конец на целой фразе.
2. Номера бери из квадратных скобок в расшифровке ниже, например [395].
3. Пост только про этот отрезок. Прямые цитаты бери дословно из его фраз: программа сверит их с расшифровкой.
4. Хук ровно одно предложение без вопроса; финал один вопрос вида «A or B?»; 400-650 слов; 4 и больше прямых цитат.
5. Без длинного тире, эмодзи и ссылок.
6. СУБТИТРЫ: перепиши речь клипа из расшифровки, не добавляя и не убирая слов: расставь точки, запятые, вопросительные знаки и заглавные, исправь явные ослышки (имена бери из названия и описания видео). Мат оставь как есть: программа замаскирует его сама. Без таймкодов и номеров.
7. После блока СУБТИТРЫ ничего не добавляй.
"""

TAIL = "\n=== НАПОМИНАНИЕ ===\nОтветь строго по шаблону из начала: START, END, (OPEN), ПОСТ:, текст на английском, ---, RU: перевод, СУБТИТРЫ: речь клипа с пунктуацией. Ничего больше.\n"


def chat_package(phr: list, *, rules_md: str, title: str, channel: str, url: str, window: tuple) -> str:
    """Всё для одного запроса в чат: шаблон ответа (в начале), правила, сведения о видео, вся расшифровка с номерами."""
    lo, hi = fmt(window[0]), fmt(window[1])
    lines = "\n".join(f"[{p['i']}] {fmt(p['start'])} {p['text']}" for p in phr)
    return (HEAD.format(lo=lo, hi=hi)
            + f"\n=== ПРАВИЛА ТЕКСТА ===\n{strip_front_matter(rules_md)}\n\n"
            + f"=== ВИДЕО ===\nНазвание: {title}\nКанал: {channel}\nСсылка: {url or '(файл)'}\n\n"
            + f"=== РАСШИФРОВКА С НОМЕРАМИ ФРАЗ ===\n{lines}\n" + TAIL)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower().replace("’", "'"))).strip()


def _english(line: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", line)
    return len(line.split()) >= 2 and len(letters) >= 6 and sum(c.isascii() for c in letters) / len(letters) > .8


def english_block(text: str) -> str:
    """Самый длинный сплошной кусок английских строк (пустые строки внутри допускаются): это и есть пост."""
    best, cur = [], []
    for ln in text.splitlines():
        if _english(ln) or (cur and not ln.strip()):
            cur.append(ln)
        else:
            if sum(len(x) for x in cur) > sum(len(x) for x in best):
                best = cur
            cur = []
    if sum(len(x) for x in cur) > sum(len(x) for x in best):
        best = cur
    return "\n".join(best).strip()


SUBS_MARK = re.compile(r"^[ \t]*(СУБТИТРЫ|SUBTITLES|SUBS)[ \t]*:[ \t]*", re.I | re.M)


def cut_subs(text: str) -> tuple[str, str]:
    """Отделяет блок «СУБТИТРЫ:» (речь клипа с пунктуацией) от остального ответа."""
    m = SUBS_MARK.search(text)
    return (text[:m.start()], text[m.end():].strip()) if m else (text, "")


def split_post(text: str) -> str:
    """Пост из ответа: после строки «ПОСТ:»; иначе после строк START/END/OPEN; иначе самый длинный английский кусок (+ RU:, если есть)."""
    m = re.search(r"^\s*(ПОСТ|POST)\s*:", text, re.I | re.M)
    if m:
        return text[m.end():].strip()
    tags = list(re.finditer(r"^\s*(START|END|OPEN|QUOTE)\b.*$", text, re.I | re.M))
    if tags and _english(text[tags[-1].end():].strip().split("\n", 1)[0]):
        return text[tags[-1].end():].strip()
    en = english_block(text)
    ru = re.search(r"^\s*RU\s*:.*", text, re.I | re.M | re.S)
    return (en + ("\n---\n" + ru.group(0).strip() if ru else "")).strip()


TIME_RANGE = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]\s*(\d{1,2}:\d{2}(?::\d{2})?)")


def find_moment(text: str, phr: list) -> tuple[dict, str | None]:
    """Границы клипа: по номерам START/END, а если их нет, по первому диапазону времени (41:49–46:28)."""
    m_s = re.search(r"START\s*[:=]?\s*\[?(\d+)\]?", text, re.I)
    m_e = re.search(r"END\s*[:=]?\s*\[?(\d+)\]?", text, re.I)
    if m_s and m_e:
        return by_numbers(phr, int(m_s[1]), int(m_e[1])), None
    t = TIME_RANGE.search(text)
    if t:
        a, b = parse_time(t[1]), parse_time(t[2])
        if b > a:
            return snap(phr, a, b), f"В ответе нет номеров фраз: границы взяты по времени {t[1]}-{t[2]} и подогнаны к целым фразам. Проверь начало и конец."
    raise ClipperError("В ответе нет ни номеров фраз START/END, ни времени клипа.",
                       "Нажми «Скопировать всю расшифровку» ещё раз и вставь в чат целиком: в начале там шаблон ответа для программы.")


def parse_reply(text: str, phr: list, window: tuple) -> dict:
    """Возвращает {first,last,start,end,open,post,errors,warnings}. Ошибки по-русски, с подсказкой."""
    errors, warns = [], []
    text, subs_text = cut_subs(text)
    main, note = find_moment(text, phr)
    if note:
        warns.append(note)
    first, last = main["first"], main["last"]
    dur = main["end"] - main["start"]
    if not window[0] <= dur <= window[1]:
        warns.append(f"Длина клипа {fmt(dur)} вне окна {fmt(window[0])}-{fmt(window[1])}")
    open_span, open_idx = None, None
    m_o = re.search(r"OPEN\s*[:=]?\s*(\d+)\s*[-–—]\s*(\d+)", text, re.I)
    if m_o:
        o = by_numbers(phr, int(m_o[1]), int(m_o[2]))
        open_idx, open_span = (o["first"], o["last"]), (o["start"], o["end"])
        if not (o["last"] < main["first"] or o["first"] > main["last"]):
            errors.append("Холодное начало пересекается с основным отрезком: попроси Claude взять кусок вне него.")
    body = _norm(" ".join(p["text"] for p in phr[first:last + 1] + (phr[open_idx[0]:open_idx[1] + 1] if open_idx else [])))
    post = normalize_post(split_post(text))
    en = re.split(r"^\s*---\s*$", post, maxsplit=1, flags=re.M)[0]
    quotes = extract_quotes(en)
    missing = [q for q in quotes if _norm(q) not in body]
    for q in missing:
        warns.append(f"Цитаты нет дословно в выбранном куске: «{q[:70]}». Проверь на слух или убери из текста.")
    return {**main, "open": open_span, "open_idx": open_idx, "post": post, "subs_text": subs_text, "quotes": len(quotes),
            "quotes_ok": len(quotes) - len(missing), "errors": errors, "warnings": warns}


def link_request(*, rules_md: str, title: str, channel: str, url: str, window: tuple) -> str:
    """Короткий запрос для Claude (или другого ИИ), который сам открывает видео по ссылке: просит время клипа и пост."""
    lo, hi = fmt(window[0]), fmt(window[1])
    return ("ВАЖНО: твой ответ читает программа «Cutline». Ответь СТРОГО по шаблону, без пояснений до и после.\n\n"
            f"Открой видео по ссылке: {url}\nНазвание: {title}\nКанал: {channel}\n\n"
            f"Найди в нём один самый сильный отрезок длиной {lo}-{hi} (конфликт или поворот, цифры и детали, начало и конец на целой фразе) "
            "и напиши к нему пост для X по правилам ниже.\n\n"
            "=== ШАБЛОН ОТВЕТА ===\nВРЕМЯ: <начало>-<конец>, например 41:49-46:28\n"
            "ПОСТ:\n<готовый пост на английском>\n---\nRU: <перевод на русский>\n\n"
            f"=== ПРАВИЛА ТЕКСТА ===\n{strip_front_matter(rules_md)}\n\n"
            "Цитаты в посте бери дословно из речи в выбранном отрезке. Без длинного тире, эмодзи и ссылок. После перевода ничего не добавляй.\n")
