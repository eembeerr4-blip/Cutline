"""Пакет для чата: правила + видео + расшифровка клипа с таймкодами + сомнительные слова + формат ответа."""
import re
from pathlib import Path

from .moment import fmt
from .subs import apply_fixes
from .paths import ROOT

NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "twenty",
                "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion"}
COMMON = {"the", "and", "you", "for", "like", "but", "yeah", "um", "uh", "your", "very", "they", "them", "its", "it", "this", "that", "with",
          "have", "was", "are", "not", "all", "one", "just", "know", "right", "man", "because", "gonna", "what", "about", "then", "there",
          "can", "get", "got", "his", "her", "him", "she", "who", "how", "out", "see", "say", "said", "now", "well", "really", "kind", "sort"}
STOP_CAPS = {"The", "This", "That", "With", "From", "Full", "Episode", "Podcast", "Interview", "Show", "And", "For", "About"}


def hint_names(*texts: str) -> list[str]:
    """Имена и слова с большой буквы из названия, канала и описания: подсказка для Whisper и словарь для проверки.
    Обычные английские слова (They, Right, Season…) именами не считаются."""
    seen, out = set(), []
    for t in texts:
        for w in re.findall(r"\b[A-Z][a-zA-Z'’-]{2,}\b", t or ""):
            if w not in STOP_CAPS and w.lower() not in COMMON and w.lower() not in seen:
                seen.add(w.lower())
                out.append(w)
    return out


def doubtful_words(segments: list, a: float, b: float, names: list[str], threshold: float = 0.3, limit: int = 15) -> list[dict]:
    """Слова клипа, которые надо проверить на слух: низкая уверенность, имена из словаря, любые числа."""
    lower_names = {n.lower() for n in names}
    out = []
    for seg in segments:
        for w in seg.get("words", []):
            if w["s"] < a or w["e"] > b:
                continue
            tok = re.sub(r"[^\w'’-]", "", w["w"]).strip()
            if not tok:
                continue
            why = []
            if w.get("p", 1.0) < threshold and tok.lower() not in COMMON and len(tok) > 2:
                why.append("низкая уверенность")
            if tok.lower() in lower_names:
                why.append("имя из названия/канала")
            if re.search(r"\d", tok) or (tok.lower() in NUMBER_WORDS and tok.lower() not in COMMON):
                why.append("число")
            if why:
                out.append({"t": w["s"], "word": tok, "p": w.get("p", 1.0), "why": ", ".join(why)})
    out.sort(key=lambda d: (len(d["why"].split(",")) * -1, d["p"]))   # самые подозрительные первыми
    return sorted(out[:limit], key=lambda d: d["t"])


def clip_transcript(segments: list, a: float, b: float, fixes: list | None = None) -> str:
    lines = []
    for seg in segments:
        if seg["start"] >= a - 0.01 and seg["end"] <= b + 0.01:
            text = apply_fixes(seg["text"], fixes)
            lines.append(f"[{fmt(seg['start'])}] {text}")
    return "\n".join(lines)


def strip_front_matter(md: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", md, count=1, flags=re.S).strip()


ANSWER_FORMAT = """Ответь только текстом поста, без пояснений до и после.
1) Сначала текст поста на английском.
2) Потом отдельной строкой три дефиса: ---
3) Потом строка RU: и перевод на русский.
Требования: хук ровно одно предложение без вопроса; финал вопрос вида «A or B?»; 400-650 слов; не меньше 4 прямых цитат из клипа;
без длинного тире, эмодзи и ссылок. В самом конце, после перевода, коротко перечисли, что на слух проверить (имена, цифры)."""


def build_package(*, rules_file: str, url: str, title: str, channel: str, span: tuple, segments: list,
                  names: list[str], fixes: list | None = None, root: Path = ROOT) -> tuple[str, list[dict]]:
    a, b = span
    rules = strip_front_matter((root / rules_file).read_text(encoding="utf-8"))
    doubts = doubtful_words(segments, a, b, names)
    dl = "\n".join(f"- {fmt(d['t'])} «{d['word']}» ({d['why']}, уверенность {d['p']:.2f})" for d in doubts) or "- нет"
    text = (
        "Напиши пост для X по моему видео. Ниже правила, данные видео и нужный формат ответа.\n\n"
        f"=== ПРАВИЛА ===\n{rules}\n\n"
        f"=== ВИДЕО ===\nСсылка: {url or '(файл, ссылки нет)'}\nНазвание: {title}\nКанал: {channel}\n"
        f"Отрезок клипа: {fmt(a)}-{fmt(b)} (длина {fmt(b - a)})\n\n"
        f"=== РАСШИФРОВКА КЛИПА (таймкоды из исходного видео) ===\n{clip_transcript(segments, a, b, fixes)}\n\n"
        f"=== СОМНИТЕЛЬНЫЕ СЛОВА (расшифровка могла ошибиться, не цитируй их как есть) ===\n{dl}\n\n"
        f"=== ФОРМАТ ОТВЕТА ===\n{ANSWER_FORMAT}\n")
    return text, doubts
