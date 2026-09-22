from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Set
from datetime import datetime

from .ranking_contribution_engine import DocumentContributionEngine
from .ranking_contribution_scores import ContributionBucket, ContributionScores, ContributorEntry, HistoryRevision


def compute_contribution_scores(
    revisions: Iterable[HistoryRevision],
    current_documents: Mapping[str, str],
    member_ids: Set[str],
    now: datetime,
    *,
    require_mature: bool = False,
    credit_limits: Mapping[str, int] | None = None,
) -> ContributionScores:
    """Replay document lineages independently, then aggregate their live contributions."""
    grouped: dict[str, list[HistoryRevision]] = defaultdict(list)
    for revision in revisions:
        grouped[revision.title].append(revision)
    buckets: list[ContributionBucket] = []
    for title in grouped.keys() | current_documents.keys():
        engine = DocumentContributionEngine(title, None if credit_limits is None else credit_limits.get(title, 0))
        engine.advance(grouped[title], member_ids, now)
        buckets.extend(engine.scores(current_documents.get(title, ""), now, require_mature=require_mature).buckets)
    return ContributionScores(tuple(sorted(buckets, key=lambda bucket: (bucket.user_id, bucket.title, bucket.day))))



def compute_contributors(
    revisions: Iterable[HistoryRevision],
    current_documents: Mapping[str, str],
    member_ids: Set[str],
    now: datetime,
) -> tuple[ContributorEntry, ...]:
    return compute_contribution_scores(
        revisions, current_documents, member_ids, now
    ).contributors()
