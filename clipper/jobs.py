"""Фоновые задачи (скачать, расшифровать, собрать): статус, журнал и прогресс для окна."""
import logging
import threading
import traceback
import uuid

from .errors import ClipperError, explain


class Job:
    def __init__(self, title: str):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.status = "running"
        self.log_lines: list[str] = []
        self.progress = 0.0
        self.result = None
        self.error: dict | None = None

    def log(self, msg: str) -> None:
        self.log_lines.append(msg)

    def view(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status, "log": self.log_lines[-12:],
                "progress": self.progress, "result": self.result, "error": self.error}


class JobRunner:
    """Одна задача за раз: видеокарта и диск общие."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def busy(self) -> bool:
        return any(j.status == "running" for j in self.jobs.values())

    def start(self, title: str, fn) -> Job:
        with self._lock:
            if self.busy():
                raise ClipperError("Уже идёт другая задача.", "Дождись окончания текущей.")
            job = Job(title)
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, fn), daemon=True).start()
        return job

    @staticmethod
    def _run(job: Job, fn) -> None:
        try:
            job.result = fn(job)
            job.progress = 1.0
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - центральная обработка, подробности в лог
            logging.error("job %s failed\n%s", job.title, traceback.format_exc())
            ce = e if isinstance(e, ClipperError) else None
            job.error = {"what": ce.what if ce else explain(e), "hint": ce.hint if ce else "", "details": (ce.details if ce else "")[-500:]}
            job.status = "error"
