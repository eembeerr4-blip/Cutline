"""Субтитры: слова → короткие строки по лимитам профиля → один ASS-файл (pysubs2)."""
import re
from pathlib import Path

SENT_END = (".", "?", "!")
GAP_TO_NEXT = 0.02


def apply_fixes(text: str, fixes: list | None) -> str:
    """Замена слова целиком (не внутри другого слова): «one» не трогает «anyone»."""
    for old, new in fixes or []:
        text = re.sub(r"(?<!\w)" + re.escape(old) + r"(?!\w)", lambda _m, n=new: n, text)
    return text


def censor_text(text: str, censor: dict | None) -> str:
    """Маскирует мат в субтитрах по словарю профиля (слово целиком, без учёта регистра, первая заглавная сохраняется)."""
    for bad, good in sorted((censor or {}).items(), key=lambda kv: -len(kv[0])):
        text = re.sub(r"(?<!\w)" + re.escape(bad) + r"(?!\w)",
                      lambda m, g=good: g[:1].upper() + g[1:] if m.group(0)[:1].isupper() else g, text, flags=re.I)
    return text


def _is_cap(tok: str) -> bool:
    t = tok.strip().lstrip("\"'“(")
    return len(t) > 0 and t[0].isupper() and not t.isupper() or t in ("I", "I'm", "I'll", "I'd", "I've")


def _key(t: str) -> str:
    return re.sub(r"[^\w']", "", t.lower().replace("\u2019", "'"))


def align_text(words: list, corrected: str) -> tuple[list, float]:
    """Подставляет в слова с таймингом исправленный Claude текст (знаки препинания, регистр, поправки слов), время остаётся от Whisper.
    Возвращает (слова, доля совпавших слов). При доле меньше 0.6 текст Claude не применяется: это, скорее всего, другой кусок."""
    import difflib
    toks = []
    for t in corrected.split():
        if _key(t):
            toks.append(t)
        elif toks:
            toks[-1] += t                      # одинокий знак (— или …) приклеиваем к предыдущему слову
    if not words or not toks:
        return words, 0.0
    sm = difflib.SequenceMatcher(a=[_key(w["w"]) for w in words], b=[_key(t) for t in toks], autojunk=False)
    ratio = sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal") / len(words)
    if ratio < 0.6:
        return words, ratio
    out = [dict(w) for w in words]
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k]["w"] = toks[j1 + k]
        elif tag == "replace":
            n_old, n_new = i2 - i1, j2 - j1
            if n_old == n_new:
                for k in range(n_old):
                    out[i1 + k]["w"] = toks[j1 + k]
            elif n_new < n_old:                 # Claude слил слова: лишние убираем, время остальных не трогаем
                for k in range(n_new):
                    out[i1 + k]["w"] = toks[j1 + k]
                for k in range(n_new, n_old):
                    out[i1 + k]["w"] = ""
            else:                               # Claude разбил слово: лишние токены добавляем к последнему слову блока
                for k in range(n_old - 1):
                    out[i1 + k]["w"] = toks[j1 + k]
                out[i2 - 1]["w"] = " ".join(toks[j1 + n_old - 1:j2])
        elif tag == "insert" and i1 > 0:
            out[i1 - 1]["w"] += " " + " ".join(toks[j1:j2])
    return [w for w in out if w["w"].strip()], ratio


def proper_names(all_words: list) -> list[str]:
    """Слова, которые во всей расшифровке НИ РАЗУ не встречаются с маленькой буквы (Austin, Kessler), это имена: их регистр не трогаем."""
    low, cap = set(), set()
    for w in all_words:
        t = re.sub(r"[^\w']", "", w["w"])
        if len(t) > 2:
            (cap if t[:1].isupper() and not t.isupper() else low).add(t.lower()) if t[:1].isupper() else low.add(t.lower())
    return sorted(cap - low)


def fix_case(words: list, names: list | None = None) -> list:
    """Whisper местами пишет каждое слово с заглавной («Man I It's Still Hard For Me»). Серию из 4+ слов с заглавной
    приводим к обычному регистру, кроме начала предложения, «I» и имён из названия/канала."""
    keep = {n.lower() for n in (names or [])}
    caps = [_is_cap(w["w"]) for w in words]
    i = 0
    while i < len(words):
        if not caps[i]:
            i += 1
            continue
        j = i
        while j < len(words) and caps[j]:
            j += 1
        if j - i >= 4:
            for k in range(i, j):
                tok = words[k]["w"].strip()
                prev = words[k - 1]["w"].strip() if k else ""
                if k == 0 or prev.endswith(SENT_END) or re.match(r"I($|')", tok) or re.sub(r"\W", "", tok).lower() in keep:
                    continue
                words[k]["w"] = words[k]["w"].lower()
        i = j
    return words


def map_words(all_words: list, spans: list, fixes: list | None = None) -> list[dict]:
    """Слова источника → слова на таймлинии готового ролика. spans = [(начало, конец)] в секундах источника, по порядку воспроизведения."""
    out, off = [], 0.0
    for a, b in spans:
        for w in all_words:
            if w["s"] >= a - 0.05 and w["e"] <= b + 0.1:
                text = apply_fixes(w["w"].strip(), fixes)
                if text:
                    out.append({"w": text, "s": off + max(0.0, w["s"] - a), "e": off + min(b - a, w["e"] - a)})
        off += b - a
    return out


def caption_groups(words: list, st: dict) -> list[dict]:
    """Группы слов: до max_words слов и max_chars символов, рвём на паузе и конце предложения, без наложения."""
    groups, cur = [], []

    def flush():
        if cur:
            groups.append({"text": " ".join(x["w"] for x in cur), "start": cur[0]["s"], "end": cur[-1]["e"]})
            cur.clear()

    for w in words:
        if cur:
            chars = len(" ".join(x["w"] for x in cur)) + 1 + len(w["w"])
            if (len(cur) >= st["max_words"] or chars > st["max_chars"]
                    or w["s"] - cur[-1]["e"] > st["pause_split_sec"] or cur[-1]["w"].endswith(SENT_END)):
                flush()
        cur.append(w)
    flush()
    for i, g in enumerate(groups):
        nxt = groups[i + 1]["start"] if i + 1 < len(groups) else float("inf")
        need = len(g["text"]) / st["max_cps"]
        end = max(g["end"] + 0.1, g["start"] + need)          # не быстрее max_cps, если есть куда растянуть
        if nxt - end < 0.6:                                      # короткую паузу закрываем, чтобы не мигало
            end = max(end, nxt - GAP_TO_NEXT)
        g["end"] = min(end, nxt - GAP_TO_NEXT, g["end"] + 1.5)
        g["end"] = max(g["end"], g["start"] + 0.15)
    for i in range(len(groups) - 1):                             # окончательная защита от наложения
        groups[i]["end"] = min(groups[i]["end"], groups[i + 1]["start"] - GAP_TO_NEXT)
    return [g for g in groups if g["end"] > g["start"]]


def violations(groups: list, st: dict) -> list[str]:
    """Проверка лимитов (для тестов и автопроверки)."""
    bad = []
    for i, g in enumerate(groups):
        if len(g["text"].split()) > st["max_words"]:
            bad.append(f"строка {i}: больше {st['max_words']} слов")
        if len(g["text"]) > st["max_chars"]:
            bad.append(f"строка {i}: длиннее {st['max_chars']} символов")
        if i and g["start"] < groups[i - 1]["end"]:
            bad.append(f"строка {i}: наложение на предыдущую")
    return bad


def build_ass(groups: list, st: dict, width: int, height: int, path: Path) -> Path:
    import pysubs2
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"], subs.info["PlayResY"] = str(width), str(height)
    subs.info["WrapStyle"], subs.info["ScaledBorderAndShadow"] = "2", "yes"
    subs.styles["Default"] = pysubs2.SSAStyle(
        fontname=st["font"], fontsize=st["size"], bold=bool(st["bold"]),
        primarycolor=pysubs2.Color(255, 255, 255), outlinecolor=pysubs2.Color(0, 0, 0),
        backcolor=pysubs2.Color(0, 0, 0, 255), borderstyle=1, outline=st["outline"], shadow=0,
        alignment=2, marginl=40, marginr=40, marginv=st["margin_v"])
    for g in groups:
        text = re.sub(r"(?<=\w) -(?=\w)", "-", g["text"]).replace("{", "(").replace("}", ")").replace("\n", " ")
        subs.events.append(pysubs2.SSAEvent(start=int(g["start"] * 1000), end=int(g["end"] * 1000), text=text, style="Default"))
    subs.save(str(path), encoding="utf-8")
    return path
