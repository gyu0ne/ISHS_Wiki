from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Set
from datetime import date, datetime
from heapq import heappop, heappush
from unicodedata import normalize

from diff_match_patch import diff_match_patch

from .ranking_contribution_scores import (
    ContributionBucket,
    ContributionScores,
    ContributorEntry,
    HistoryRevision,
)
from .ranking_contribution_state import DocumentState, MATURITY, REMOVAL_GRACE, TokenState, as_kst, can_own


def compute_contribution_scores(
    revisions: Iterable[HistoryRevision],
    current_documents: Mapping[str, str],
    member_ids: Set[str],
    now: datetime,
) -> ContributionScores:
    now_kst = as_kst(now)
    documents: dict[str, DocumentState] = {}
    tokens: dict[int, TokenState] = {}
    deleted_spans: dict[str, list[tuple[str, tuple[int, ...]]]] = defaultdict(list)
    last_revision: dict[str, int | None] = {}
    next_token_id = 0
    differ = diff_match_patch()

    def remove(
        placements: tuple[int, ...],
        at: datetime,
        remover: str | None,
        editor: str | None,
        editor_day: date | None,
        allow_grace: bool,
    ) -> None:
        for token_id in placements:
            token = tokens[token_id]
            token.matured = token.matured or at - token.continuous_since >= MATURITY
            token.active_count -= 1
            if token.active_count != 0:
                continue
            token.removed_since = at
            token.removal_active = False
            if editor is not None:
                if token.removal_author is not None:
                    token.removal_active = True
                elif token.author is not None and token.author != editor:
                    token.removal_active = True
                    token.removal_author = editor
                    token.removal_day = editor_day
                    token.removal_lineage = token.lineage
            if allow_grace and token.author is not None and token.matured and remover != token.author:
                expiry = at + REMOVAL_GRACE
                if token.grace_until is None or expiry > token.grace_until:
                    token.grace_until = expiry
            else:
                token.grace_until = None

    def create(
        title: str, text: str, author: str | None, owner_day: date | None, at: datetime
    ) -> tuple[int, ...]:
        nonlocal next_token_id
        placements: list[int] = []
        for character in text:
            token_id = next_token_id
            next_token_id += 1
            owner = author if not character.isspace() else None
            tokens[token_id] = TokenState(
                owner, owner_day if owner is not None else None, title, at
            )
            placements.append(token_id)
        return tuple(placements)

    def reuse(token_ids: tuple[int, ...], at: datetime) -> tuple[int, ...]:
        for token_id in token_ids:
            token = tokens[token_id]
            if token.active_count == 0:
                token.continuous_since = at
            token.removal_active = False
            token.active_count += 1
        return token_ids

    def restore(
        title: str, text: str, author: str | None, owner_day: date | None, at: datetime
    ) -> tuple[int, ...]:
        matches: list[tuple[int, int, int, tuple[int, ...]]] = []
        for priority, (deleted, token_ids) in enumerate(reversed(deleted_spans[title])):
            old_index = new_index = 0
            for operation, part in differ.diff_main(deleted, text):
                size = len(part)
                if operation == 0:
                    matches.append((-size, priority, new_index, token_ids[old_index : old_index + size]))
                old_index += size if operation != 1 else 0
                new_index += size if operation != -1 else 0
        best: dict[int, int] = {}
        used: set[int] = set()
        for _, _, new_index, token_ids in sorted(matches):
            for offset, token_id in enumerate(token_ids):
                target = new_index + offset
                if target not in best and token_id not in used and tokens[token_id].active_count == 0:
                    best[target] = token_id
                    used.add(token_id)
        if not best:
            return create(title, text, author, owner_day, at)
        placements: list[int] = []
        for index, character in enumerate(text):
            token_id = best.get(index)
            placements.extend(
                create(title, character, author, owner_day, at)
                if token_id is None
                else reuse((token_id,), at)
            )
        return tuple(placements)

    def apply(
        title: str,
        new_text: str,
        at: datetime,
        author: str | None,
        owner_day: date | None,
        remover: str | None,
        *,
        allow_removal_grace: bool,
    ) -> None:
        old = documents.get(title, DocumentState("", ()))
        placements_list: list[int] = []
        old_index = 0
        for operation, text in differ.diff_main(old.text, new_text):
            if operation == 0:
                end = old_index + len(text)
                placements_list.extend(old.placements[old_index:end])
                old_index = end
            elif operation == -1:
                end = old_index + len(text)
                removed = old.placements[old_index:end]
                deleted_spans[title].append((text, removed))
                remove(
                    removed,
                    at,
                    remover,
                    author,
                    owner_day,
                    allow_removal_grace,
                )
                old_index = end
            else:
                placements_list.extend(restore(title, text, author, owner_day, at))
        placements = tuple(placements_list)
        documents[title] = DocumentState(new_text, placements)

    grouped: dict[str, list[tuple[int, HistoryRevision]]] = defaultdict(list)
    for index, revision in enumerate(revisions):
        grouped[revision.title].append((index, revision))
    for group in grouped.values():
        group.sort(key=lambda item: (int(item[1].id), item[0]))
    queue: list[tuple[datetime, int, str, int]] = []
    for title, group in grouped.items():
        index, revision = group[0]
        heappush(queue, (as_kst(revision.date), index, title, 0))
    ordered: list[HistoryRevision] = []
    while queue:
        _, _, title, position = heappop(queue)
        group = grouped[title]
        ordered.append(group[position][1])
        next_position = position + 1
        if next_position < len(group):
            index, revision = group[next_position]
            heappush(queue, (as_kst(revision.date), index, title, next_position))

    uncertain: set[str] = set()
    last_applied_at: dict[str, datetime] = {}
    for revision in ordered:
        stored_at = as_kst(revision.date)
        if stored_at > now_kst:
            continue
        number = int(revision.id)
        previous = last_revision.get(revision.title)
        contiguous = number == 1 if previous is None else number == previous + 1
        last_revision[revision.title] = number
        if revision.type == "edit_request" and revision.leng == 0:
            uncertain.add(revision.title)
            continue
        at = max(stored_at, last_applied_at.get(revision.title, stored_at))
        author = (
            revision.ip
            if revision.title not in uncertain and can_own(revision, member_ids, contiguous)
            else None
        )
        apply(revision.title, normalize("NFC", revision.data), at, author,
              stored_at.date() if author is not None else None,
              revision.ip if revision.ip in member_ids else None,
              allow_removal_grace=True)
        uncertain.discard(revision.title)
        last_applied_at[revision.title] = at

    for title in documents.keys() | current_documents.keys():
        apply(title, normalize("NFC", current_documents.get(title, "")), now_kst,
              None, None, None, allow_removal_grace=False)

    addition_buckets: dict[tuple[str, str, date], int] = defaultdict(int)
    removal_buckets: dict[tuple[str, str, date], int] = defaultdict(int)
    for token in tokens.values():
        retained = token.active_count > 0 and (
            token.matured or now_kst - token.continuous_since >= MATURITY
        )
        retained = retained or (
            token.active_count == 0
            and token.grace_until is not None
            and now_kst < token.grace_until
        )
        if retained and token.author is not None and token.day is not None:
            addition_buckets[(token.author, token.lineage, token.day)] += 1
        removal_author = token.removal_author
        removal_day = token.removal_day
        removal_lineage = token.removal_lineage
        removed_since = token.removed_since
        if (
            token.active_count == 0
            and token.removal_active
            and removal_author is not None
            and removal_day is not None
            and removal_lineage is not None
            and removed_since is not None
            and now_kst - removed_since >= MATURITY
        ):
            removal_buckets[(removal_author, removal_lineage, removal_day)] += 1

    buckets = (
        ContributionBucket(
            user_id,
            lineage,
            day,
            addition_buckets[(user_id, lineage, day)],
            removal_buckets[(user_id, lineage, day)],
        )
        for user_id, lineage, day in addition_buckets.keys() | removal_buckets.keys()
    )
    return ContributionScores(
        tuple(sorted(buckets, key=lambda bucket: (bucket.user_id, bucket.title, bucket.day)))
    )


def compute_contributors(
    revisions: Iterable[HistoryRevision],
    current_documents: Mapping[str, str],
    member_ids: Set[str],
    now: datetime,
) -> tuple[ContributorEntry, ...]:
    return compute_contribution_scores(
        revisions, current_documents, member_ids, now
    ).contributors()
