"""Момент: фразы, время и диапазоны, привязка границ к целым фразам, нечёткий поиск цитаты."""
import re

from .errors import ClipperError

SENT_END = (".", "?", "!")


def phrases(segments: list, max_len: float = 15.0, min_len: float = 2.0) -> list[dict]:
    """Фразы из слов: фраза копит слова и заканчивается на конце предложения, паузе, конце сегмента Whisper
    или запятой после 12 с, но никогда не длиннее max_len. Короче min_len не режем (кроме самого конца)."""
    out, cur = [], []

    def flush():
        if cur:
            out.append(_make(cur))
            cur.clear()

    for seg in segments:
        words = seg.get("words") or []
        if not words:                      # сегмент без слов: целиком одна фраза
            flush()
            out.append(dict(seg))
            continue
        for k, w in enumerate(words):
            if cur and w["e"] - cur[0]["s"] > max_len:
                flush()                    # следующее слово сделало бы фразу слишком длинной
            cur.append(w)
            dur = w["e"] - cur[0]["s"]
            tok = w["w"].strip()
            gap = words[k + 1]["s"] - w["e"] if k + 1 < len(words) else 0.0
            if dur >= min_len and (tok.endswith(SENT_END) or gap > 0.8 or (dur >= 12 and tok.endswith(","))):
                flush()
        if cur and cur[-1]["e"] - cur[0]["s"] >= min_len:
            flush()                        # конец сегмента Whisper: естественная граница
    flush()
    for i, p in enumerate(out):
        p["i"] = i
    return out


def _make(words: list) -> dict:
    return {"start": words[0]["s"], "end": words[-1]["e"],
            "text": "".join(w["w"] for w in words).strip(), "words": list(words)}


FILLER_END = {"like", "and", "but", "so", "the", "a", "an", "to", "of", "um", "uh", "or", "because", "that", "with", "for", "i", "he", "she",
              "they", "we", "you", "it", "is", "was", "are", "my", "your", "his", "her", "in", "on", "at", "as", "if", "then", "just", "kind", "sort"}


def refine_bounds(words: list, start: float, end: float, tol: float = 10.0) -> tuple[float, float, list[str]]:
    """Подгоняет начало и конец клипа к границам мысли (в пределах tol секунд). Конец предложения (. ? !) важнее паузы;
    пауза не считается границей, если перед ней слово-паразит или обрывок («like», «and», «the»…). Возвращает (начало, конец, пояснения)."""
    def tok(k):
        return re.sub(r"[^\w']", "", words[k]["w"]).lower()

    cost, ends = {}, []
    for k, w in enumerate(words):
        if w["w"].strip().endswith(SENT_END):
            ends.append(k); cost[k] = 0.0
        elif k + 1 < len(words) and words[k + 1]["s"] - w["e"] >= 0.5 and tok(k) not in FILLER_END:
            ends.append(k); cost[k] = 3.0          # пауза: хуже, чем конец предложения
    starts = [0] + [k + 1 for k in ends if k + 1 < len(words) and tok(k + 1) not in ("and", "but", "so")]
    notes, new_s, new_e = [], start, end

    def pick(idx, t, key, extra):
        best = min(idx, key=lambda j: abs(key(words[j]) - t) + extra(j), default=None)
        return best if best is not None and abs(key(words[best]) - t) <= tol else None

    k = pick(starts, start, lambda w: w["s"], lambda j: cost.get(j - 1, 0.0))
    if k is not None and abs(words[k]["s"] - start) > 0.05:
        new_s = words[k]["s"]; notes.append(f"Начало подогнано к началу мысли ({new_s - start:+.1f} с)")
    k = pick(ends, end, lambda w: w["e"], lambda j: cost[j])
    if k is not None and abs(words[k]["e"] - end) > 0.05:
        new_e = words[k]["e"]; notes.append(f"Конец подогнан к концу мысли ({new_e - end:+.1f} с)")
    if new_e - new_s < 20:
        return start, end, []
    last = max((k for k, w in enumerate(words) if w["e"] <= new_e + 0.01), default=None)
    if last is not None and tok(last) in FILLER_END and not words[last]["w"].strip().endswith(SENT_END):
        notes.append(f"Клип заканчивается на слове «{tok(last)}», посреди мысли: в речи тут нет ни пауз, ни точек. Проверь конец "
                     "(блок «Подправить границы клипа вручную») или попроси Claude взять конец другой фразой.")
    return new_s, new_e, notes


def parse_time(text: str) -> float:
    """'12:34' → 754, '1:02:03' → 3723, '754' → 754."""
    t = text.strip()
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", t):
        raise ClipperError(f"Не понимаю время «{text}».", "Пиши в виде 12:34 или 1:02:03.")
    parts = [float(x) for x in t.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def parse_range(text: str) -> tuple[float, float | None]:
    parts = [p for p in re.split(r"\s*[-–—]\s*", text.strip()) if p]
    if not parts or len(parts) > 2:
        raise ClipperError(f"Не понимаю диапазон «{text}».", "Пиши 12:34-16:40 или только начало 12:34.")
    a = parse_time(parts[0])
    b = parse_time(parts[1]) if len(parts) == 2 else None
    if b is not None and b <= a:
        raise ClipperError("Конец раньше начала.", "Проверь два времени.")
    return a, b


def fmt(sec: float) -> str:
    s = int(round(sec))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _at(phr: list, t: float) -> int:
    """Индекс фразы, содержащей момент t, иначе ближайшей следующей (или последней)."""
    for p in phr:
        if t < p["end"]:
            return p["i"]
    return phr[-1]["i"]


def snap(phr: list, start: float, end: float | None = None, tail: float = 240.0) -> dict:
    """Границы по целым фразам. Без конца: конец = начало + tail по концу фразы."""
    if not phr:
        raise ClipperError("В расшифровке нет фраз.", "Проверь, что в видео есть речь, и повтори расшифровку.")
    a = _at(phr, start)
    want_end = end if end is not None else phr[a]["start"] + tail
    b = max(_at(phr, min(want_end, phr[-1]["end"] - 0.01)), a)
    return {"first": a, "last": b, "start": phr[a]["start"], "end": phr[b]["end"]}


def by_numbers(phr: list, first: int, last: int) -> dict:
    """Границы по номерам фраз (ответ Claude)."""
    n = len(phr)
    if not (0 <= first < n and 0 <= last < n):
        raise ClipperError(f"Номера фраз {first}–{last} вне диапазона 0–{n - 1}.", "Проверь номера в ответе Claude.")
    if last < first:
        raise ClipperError("Последняя фраза раньше первой.", "Проверь номера в ответе Claude.")
    return {"first": first, "last": last, "start": phr[first]["start"], "end": phr[last]["end"]}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def find_quote(phr: list, query: str, top: int = 5, min_gap: float = 20.0) -> list[dict]:
    """Топ мест, где встречается цитата (нечётко). Каждое место с контекстом из соседних фраз."""
    from rapidfuzz import fuzz
    q = _norm(query)
    if len(q) < 4:
        raise ClipperError("Цитата слишком короткая.", "Вставь хотя бы одну целую фразу из видео, по-английски.")
    cands = []
    for i in range(len(phr)):
        for k in (1, 2, 3):
            if i + k > len(phr):
                break
            window = _norm(" ".join(p["text"] for p in phr[i:i + k]))
            score = fuzz.partial_ratio(q, window) if len(window) >= len(q) else fuzz.ratio(q, window)
            cands.append((score - 3 * (k - 1), i, i + k - 1))  # штраф: предпочитаем окно покороче
    cands.sort(key=lambda c: (-c[0], c[1]))
    picked = []
    for score, a, b in cands:
        if score < 55 or len(picked) >= top:
            break
        if all(abs(phr[a]["start"] - phr[x["first"]]["start"]) >= min_gap for x in picked):
            before = phr[a - 1]["text"] if a > 0 else ""
            after = phr[b + 1]["text"] if b + 1 < len(phr) else ""
            picked.append({"first": a, "last": b, "score": round(score), "start": phr[a]["start"],
                           "text": " ".join(p["text"] for p in phr[a:b + 1]), "before": before, "after": after})
    return picked
