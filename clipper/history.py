"""История: поиск пересечений нового отрезка с прежними клипами того же видео."""
from .moment import fmt
from .project import list_projects

MIN_OVERLAP_SEC = 30.0


def overlaps(source_id: str, start: float, end: float, exclude: str = "", projects=None) -> list[dict]:
    """Прежние клипы того же видео, пересекающиеся с [start, end] больше чем на 30 секунд."""
    out = []
    for p in projects if projects is not None else list_projects():
        s = p.get("source") or {}
        m = p.get("moment")
        if p.dir.name == exclude or not m or s.get("id") != source_id or not p.get("clip"):
            continue
        common = min(end, m["end"]) - max(start, m["start"])
        if common > MIN_OVERLAP_SEC:
            out.append({"project": p.dir.name, "title": s.get("title", ""), "start": m["start"], "end": m["end"], "overlap": common,
                        "text": f"Уже есть клип {fmt(m['start'])}-{fmt(m['end'])} из этого видео: пересечение {fmt(common)}"})
    return out
