from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from math import expm1, log1p


Period = str


@dataclass(frozen=True, slots=True)
class HistoryRevision:
    id: str
    title: str
    data: str
    date: datetime
    ip: str
    send: str
    leng: int
    hide: str
    type: str


@dataclass(frozen=True, slots=True)
class ContributorEntry:
    user_id: str
    score: float
    retained_characters: int
    active_days: int


@dataclass(frozen=True, slots=True)
class ContributionBucket:
    user_id: str
    title: str
    day: date
    additions: int
    removals: int

    @property
    def quantity(self) -> int:
        return max(self.additions, self.removals)


@dataclass(frozen=True, slots=True)
class DocumentScore:
    title: str
    score: float


@dataclass(frozen=True, slots=True)
class ContributorDocuments:
    user_id: str
    documents: tuple[DocumentScore, ...]


@dataclass(frozen=True, slots=True)
class PeriodScores:
    contributors: tuple[ContributorEntry, ...]
    documents: tuple[ContributorDocuments, ...]


@dataclass(frozen=True, slots=True)
class NamedPeriodScores:
    period: Period
    scores: PeriodScores


def _bucket_score(quantity: int) -> float:
    return -50 * expm1(-log1p(quantity / 1000) / 3)


@dataclass(frozen=True, slots=True)
class ContributionScores:
    buckets: tuple[ContributionBucket, ...]

    def _aggregate(self, buckets: Iterable[ContributionBucket]) -> PeriodScores:
        quantities: dict[str, list[int]] = defaultdict(list)
        retained: dict[str, int] = defaultdict(int)
        active_days: dict[str, set[date]] = defaultdict(set)
        document_scores: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for bucket in buckets:
            quantities[bucket.user_id].append(bucket.quantity)
            retained[bucket.user_id] += bucket.additions
            active_days[bucket.user_id].add(bucket.day)
            document_scores[bucket.user_id][bucket.title] += _bucket_score(bucket.quantity)
        entries = (
            ContributorEntry(
                user_id=user_id,
                score=sum(_bucket_score(quantity) for quantity in user_quantities),
                retained_characters=retained[user_id],
                active_days=len(active_days[user_id]),
            )
            for user_id, user_quantities in quantities.items()
        )
        documents = (
            ContributorDocuments(
                user_id,
                tuple(
                    DocumentScore(title, score)
                    for title, score in sorted(
                        scores.items(), key=lambda item: (-item[1], item[0])
                    )
                ),
            )
            for user_id, scores in document_scores.items()
        )
        return PeriodScores(
            tuple(sorted(entries, key=lambda entry: (-entry.score, entry.user_id))),
            tuple(sorted(documents, key=lambda item: item.user_id)),
        )

    def period(self, period: Period = "all") -> PeriodScores:
        if period == "all":
            return self._aggregate(self.buckets)
        return self._aggregate(
            bucket for bucket in self.buckets if bucket.day.strftime("%Y-%m") == period
        )

    def periods(self) -> tuple[NamedPeriodScores, ...]:
        month_buckets: dict[str, list[ContributionBucket]] = defaultdict(list)
        for bucket in self.buckets:
            month_buckets[bucket.day.strftime("%Y-%m")].append(bucket)
        return (
            NamedPeriodScores("all", self._aggregate(self.buckets)),
            *(
                NamedPeriodScores(month, self._aggregate(month_buckets[month]))
                for month in sorted(month_buckets)
            ),
        )

    def contributors(self, period: Period = "all") -> tuple[ContributorEntry, ...]:
        return self.period(period).contributors

    def documents(
        self, user_id: str, period: Period = "all"
    ) -> tuple[DocumentScore, ...]:
        return next(
            (
                item.documents
                for item in self.period(period).documents
                if item.user_id == user_id
            ),
            (),
        )
