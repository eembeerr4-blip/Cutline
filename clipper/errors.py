"""Единая ошибка приложения: что случилось и что нажать дальше (всё по-русски)."""


class ClipperError(Exception):
    """Ожидаемый сбой. `what` объясняет проблему, `hint` говорит, что делать дальше."""

    def __init__(self, what: str, hint: str = "", details: str = ""):
        super().__init__(what)
        self.what = what
        self.hint = hint
        self.details = details

    def __str__(self) -> str:
        return self.what + (f"\n  Что делать: {self.hint}" if self.hint else "")


def explain(exc: BaseException) -> str:
    """Человеческий текст любой ошибки (неожиданные тоже, без страшного traceback)."""
    if isinstance(exc, ClipperError):
        return str(exc)
    return (f"Неожиданная ошибка: {type(exc).__name__}: {exc}\n"
            "  Что делать: скопируй диагностику (меню «Система») и вставь в чат вместе с этим текстом.")
