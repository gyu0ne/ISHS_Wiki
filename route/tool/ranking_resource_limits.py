"""Finite replay work; exceeding a limit aborts publication, never invents credit."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

MAX_DOCUMENT_CHARS = 100_000
MAX_TOKENS = 200_000
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MAX_ENCODED_CHARS = 8 * 1024 * 1024
MAX_COLLECTION_ITEMS = 400_000
MAX_REVISIONS = 10_000


class RankingResourceLimit(ValueError):
    pass


@dataclass(slots=True)
class WorkBudget:
    calls: int = 0
    characters: int = 0
    work: int = 0
    max_calls: int = 25_000
    max_characters: int = 10_000_000
    max_work: int = 5_000_000_000

    def consume(self, characters: int, work: int) -> None:
        if (self.calls + 1 > self.max_calls
                or self.characters + characters > self.max_characters
                or self.work + work > self.max_work):
            raise RankingResourceLimit('Contribution replay work budget exceeded')
        self.calls += 1
        self.characters += characters
        self.work += work

    def __deepcopy__(self, memo):
        # Scoring overlays consume the same work budget as historical replay.
        return self


refresh_budget = ContextVar('ranking_refresh_budget', default=None)


@contextmanager
def ranking_work_budget():
    token = refresh_budget.set(WorkBudget(max_calls=100_000, max_characters=100_000_000,
                                        max_work=50_000_000_000))
    try:
        yield
    finally:
        refresh_budget.reset(token)
