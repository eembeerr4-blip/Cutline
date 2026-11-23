"""Проверка текста поста по правилам платформы. Имя проверки берётся из профиля (text_check).

Новая платформа: добавь функцию и запиши её в CHECKS. Для платформы без проверки есть "none".
"""
import re

BANNED = ("watch till the end", "tell me below", "let me know", "comment below", "follow me", "retweet")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
def extract_quotes(text: str) -> list[str]:
    """\u041f\u0440\u044f\u043c\u044b\u0435 \u0446\u0438\u0442\u0430\u0442\u044b (12+ \u0437\u043d\u0430\u043a\u043e\u0432): \u043f\u0430\u0440\u043d\u044b\u0435 \u201c\u2026\u201d \u0438 "\u2026". \u041f\u043e\u044f\u0441\u043d\u0435\u043d\u0438\u044f \u043c\u0435\u0436\u0434\u0443 \u0446\u0438\u0442\u0430\u0442\u0430\u043c\u0438 (\u043d\u0430\u0447\u0438\u043d\u0430\u044e\u0442\u0441\u044f \u0441\u043e \u0437\u043d\u0430\u043a\u0430 \u043f\u0440\u0435\u043f\u0438\u043d\u0430\u043d\u0438\u044f) \u043d\u0435 \u0441\u0447\u0438\u0442\u0430\u044e\u0442\u0441\u044f."""
    found = re.findall(r"\u201c([^\u201c\u201d]{12,400})\u201d", text)
    plain = re.sub(r"\u201c[^\u201c\u201d]*\u201d", " ", text)
    for seg in plain.split('"')[1::2]:
        if 12 <= len(seg) <= 400 and not re.match(r"\s*[.,;:!?)\-]", seg):
            found.append(seg)
    return found


def normalize_post(text: str) -> str:
    """Если Claude забыл строку --- перед переводом, но перевод с «RU:» есть, разделитель добавляется сам."""
    if re.search(r"^[ \t]*---[ \t]*$", text, re.M):
        return text
    m = re.search(r"^[ \t]*RU[ \t]*:", text, re.M | re.I)
    return text[:m.start()].rstrip() + "\n\n---\n" + text[m.start():] if m else text


def split_post(text: str) -> tuple[str, str]:
    """Английская часть и русский перевод: делит строка из трёх дефисов (или «RU:», если дефисов нет)."""
    text = normalize_post(text)
    m = re.search(r"^[ \t]*---[ \t]*$", text, re.M)
    return (text[:m.start()], text[m.end():]) if m else (text, "")


def x_post(text: str) -> tuple[list[tuple[str, str]], dict]:
    res: list[tuple[str, str]] = []
    text = normalize_post(text)
    en, ru = split_post(text)
    en = en.strip()
    if not re.search(r"^[ \t]*---[ \t]*$", text, re.M):
        res.append(("FAIL", "Нет разделителя: после английского текста должна быть строка из трёх дефисов ---"))
    if not re.search(r"^\s*RU\s*:", ru, re.M | re.I):
        res.append(("FAIL", "Нет русского перевода: после --- нужна строка, начинающаяся с «RU:»"))
    paras = [x.strip() for x in re.split(r"\n\s*\n", en) if x.strip()]
    if not paras:
        return res + [("FAIL", "Английский текст пустой")], {}
    words = len(en.split())
    quotes = len(extract_quotes(en))
    if not 400 <= words <= 650:
        res.append(("WARN", f"Английский текст {words} слов, ориентир 400–650"))
    hook = paras[0]
    if "?" in hook:
        res.append(("FAIL", "Хук с вопросом: нужно одно утверждение без вопроса"))
    if len(re.findall(r"[.!?](\s|$)", hook)) != 1:
        res.append(("FAIL", "Хук должен быть ровно одним предложением"))
    if len(paras) > 1 and len(paras[1].split()) > 40:
        res.append(("WARN", "Второй абзац длинный: он должен быть коротким и держать напряжение"))
    last = paras[-1]
    if not last.endswith("?") or " or " not in last:
        res.append(("FAIL", "Финал: один вопрос вида «A or B?» (с or и знаком ?)"))
    low = text.lower()
    res += [("FAIL", f"Запрещённая фраза: {b}") for b in BANNED if b in low]
    if "\u2014" in text or "\u2013" in text:
        res.append(("FAIL", "Длинное тире в тексте: замени запятой, точкой или дефисом"))
    if EMOJI.search(text):
        res.append(("FAIL", "Эмодзи в тексте"))
    if "http" in low or "www." in low:
        res.append(("FAIL", "Ссылка в тексте"))
    if quotes < 4:
        res.append(("WARN", f"Мало прямых цитат ({quotes}), нужно 4 и больше"))
    if not any(lv == "FAIL" for lv, _ in res):
        res.insert(0, ("OK", "Обязательные правила соблюдены"))
    return res, {"words": words, "quotes": quotes}


def no_check(text: str) -> tuple[list[tuple[str, str]], dict]:
    return [("OK", "Для этой платформы проверка текста не задана")], {}


CHECKS = {"x_post": x_post, "none": no_check}


def check_text(name: str, text: str):
    from .errors import ClipperError
    if name not in CHECKS:
        raise ClipperError(f"Проверка текста «{name}» не найдена.", f"Допустимо: {', '.join(CHECKS)}. Поправь поле text_check в профиле.")
    return CHECKS[name](text)
