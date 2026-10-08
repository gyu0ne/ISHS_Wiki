"""Native Unicode alignment with finite operand and cumulative replay budgets."""

from typing import assert_never

from rapidfuzz.distance import Indel, Prefix, Postfix
from .ranking_resource_limits import MAX_DOCUMENT_CHARS, RankingResourceLimit, WorkBudget, refresh_budget


class ContributionDiffer:
    __slots__ = ('_budget', '__dict__')

    def __init__(self):
        self._budget = None

    @property
    def budget(self):
        if self._budget is None:
            self._budget = WorkBudget()
        return self._budget

    @budget.setter
    def budget(self, value):
        self._budget = value

    def __deepcopy__(self, memo):
        # Alignment is stateless; history and score overlays share one budget.
        return self

    def diff_main(self, old: str, new: str) -> list[tuple[int, str]]:
        if max(len(old), len(new)) > MAX_DOCUMENT_CHARS:
            raise RankingResourceLimit('Contribution document exceeds 100000 characters')
        prefix = Prefix.similarity(old, new)
        suffix = min(Postfix.similarity(old, new), len(old) - prefix, len(new) - prefix)
        work = max(1, (len(old) - prefix - suffix) * (len(new) - prefix - suffix))
        if work > 2_500_000_000:
            raise RankingResourceLimit('Contribution comparison exceeds native work limit')
        characters = len(old) + len(new)
        self.budget.consume(characters, work)
        shared = refresh_budget.get()
        if shared is not None:
            shared.consume(characters, work)
        parts: list[tuple[int, str]] = []
        for operation in Indel.opcodes(old, new):
            match operation.tag:
                case 'equal':
                    parts.append((0, old[operation.src_start:operation.src_end]))
                case 'delete' | 'insert' | 'replace':
                    if operation.src_end > operation.src_start:
                        parts.append((-1, old[operation.src_start:operation.src_end]))
                    if operation.dest_end > operation.dest_start:
                        parts.append((1, new[operation.dest_start:operation.dest_end]))
                case unreachable:
                    assert_never(unreachable)
        return parts
