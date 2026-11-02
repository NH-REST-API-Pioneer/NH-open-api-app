"""약속 위반 시험용 — 전략 인스턴스에 target 이 없다."""
from dataclasses import dataclass

TICK = 0.1
TICK_VALUE = 1000
TITLE = "target 없음"
NAME = "nt"


@dataclass(frozen=True)
class Params:
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"
    hold_min: int = 120


class NoTarget:
    def __init__(self, p):
        self.p = p
        self.day = None

    def on_minute(self, m):
        return []

    def end_of_day(self):
        return []

    def on_entry(self, *a):
        pass

    def on_exit(self, *a):
        pass


STRATEGY = NoTarget
