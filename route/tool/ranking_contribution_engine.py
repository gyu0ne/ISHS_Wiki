from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Set
from copy import deepcopy
from datetime import date, datetime
from unicodedata import normalize

from diff_match_patch import diff_match_patch

from .ranking_contribution_scores import ContributionBucket, ContributionScores, HistoryRevision
from .ranking_contribution_state import DocumentState, MATURITY, REMOVAL_GRACE, TokenState, as_kst, can_own
from .ranking_replay_checkpoint import decode_checkpoint, encode_checkpoint


class DocumentContributionEngine:
    """Mutable historical lineage for one document; current-body scoring uses a copy."""

    def __init__(self, title: str, credit_limit: int | None = None) -> None:
        self.title = title
        self.credit_limit = credit_limit
        self.documents: dict[str, DocumentState] = {}
        self.tokens: dict[int, TokenState] = {}
        self.deleted_spans: dict[str, list[tuple[str, tuple[int, ...]]]] = defaultdict(list)
        self.next_token_id = 0
        self.last_revision: int | None = None
        self.last_applied_at: datetime | None = None
        self.uncertain = False
        self.frozen = False
        self.differ = diff_match_patch()

    @property
    def text(self) -> str:
        return self.documents.get(self.title, DocumentState("", ())).text

    def freeze_credit(self) -> None:
        if self.credit_limit is None or self.frozen:
            return
        for _, placements in self.deleted_spans[self.title]:
            for token_id in placements:
                token = self.tokens[token_id]
                if token.active_count == 0:
                    token.author = None
        self.frozen = True

    def advance(self, revisions: Iterable[HistoryRevision], member_ids: Set[str], now: datetime) -> None:
        now_kst = as_kst(now)
        for revision in sorted(revisions, key=lambda item: int(item.id)):
            stored_at = as_kst(revision.date)
            if stored_at > now_kst:
                continue
            number = int(revision.id)
            if self.credit_limit is not None and number > self.credit_limit:
                self.freeze_credit()
            contiguous = number == 1 if self.last_revision is None else number == self.last_revision + 1
            self.last_revision = number
            if revision.type == "edit_request" and revision.leng == 0:
                self.uncertain = True
                continue
            at = max(stored_at, self.last_applied_at or stored_at)
            author = (
                revision.ip
                if (not self.uncertain and can_own(revision, member_ids, contiguous)
                    and (self.credit_limit is None or number <= self.credit_limit))
                else None
            )
            self.apply(self.title, normalize("NFC", revision.data), at, author,
                       stored_at.date() if author is not None else None,
                       revision.ip if revision.ip in member_ids else None,
                       allow_removal_grace=True)
            self.uncertain = False
            self.last_applied_at = at

    def scores(self, current_body: str, now: datetime, *, require_mature: bool = False) -> ContributionScores:
        if self.credit_limit is None and normalize("NFC", current_body) == self.text:
            return score_tokens(self.tokens.values(), as_kst(now), require_mature)
        working = deepcopy(self)
        working.freeze_credit()
        working.apply(self.title, normalize("NFC", current_body), as_kst(now), None, None, None,
                      allow_removal_grace=False)
        return score_tokens(working.tokens.values(), as_kst(now), require_mature)

    def dump_checkpoint(self) -> str:
        return encode_checkpoint(self)

    @classmethod
    def load_checkpoint(cls, payload: str) -> DocumentContributionEngine:
        return decode_checkpoint(payload, cls)

    def remove(
        self,
        placements: tuple[int, ...],
        at: datetime,
        remover: str | None,
        editor: str | None,
        editor_day: date | None,
        allow_grace: bool,
    ) -> None:
        for token_id in placements:
            token = self.tokens[token_id]
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
        self,
        title: str, text: str, author: str | None, owner_day: date | None, at: datetime
    ) -> tuple[int, ...]:
        placements: list[int] = []
        for character in text:
            token_id = self.next_token_id
            self.next_token_id += 1
            owner = author if not character.isspace() else None
            self.tokens[token_id] = TokenState(
                owner, owner_day if owner is not None else None, title, at
            )
            placements.append(token_id)
        return tuple(placements)

    def reuse(self, token_ids: tuple[int, ...], at: datetime) -> tuple[int, ...]:
        for token_id in token_ids:
            token = self.tokens[token_id]
            if token.active_count == 0:
                token.continuous_since = at
            token.removal_active = False
            token.active_count += 1
        return token_ids

    def restore(
        self,
        title: str, text: str, author: str | None, owner_day: date | None, at: datetime
    ) -> tuple[int, ...]:
        matches: list[tuple[int, int, int, tuple[int, ...]]] = []
        for priority, (deleted, token_ids) in enumerate(reversed(self.deleted_spans[title])):
            old_index = new_index = 0
            for operation, part in self.differ.diff_main(deleted, text):
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
                if target not in best and token_id not in used and self.tokens[token_id].active_count == 0:
                    best[target] = token_id
                    used.add(token_id)
        if not best:
            return self.create(title, text, author, owner_day, at)
        placements: list[int] = []
        for index, character in enumerate(text):
            token_id = best.get(index)
            placements.extend(
                self.create(title, character, author, owner_day, at)
                if token_id is None
                else self.reuse((token_id,), at)
            )
        return tuple(placements)

    def apply(
        self,
        title: str,
        new_text: str,
        at: datetime,
        author: str | None,
        owner_day: date | None,
        remover: str | None,
        *,
        allow_removal_grace: bool,
    ) -> None:
        old = self.documents.get(title, DocumentState("", ()))
        placements_list: list[int] = []
        old_index = 0
        for operation, text in self.differ.diff_main(old.text, new_text):
            if operation == 0:
                end = old_index + len(text)
                placements_list.extend(old.placements[old_index:end])
                old_index = end
            elif operation == -1:
                end = old_index + len(text)
                removed = old.placements[old_index:end]
                self.deleted_spans[title].append((text, removed))
                self.remove(
                    removed,
                    at,
                    remover,
                    author,
                    owner_day,
                    allow_removal_grace,
                )
                old_index = end
            else:
                placements_list.extend(self.restore(title, text, author, owner_day, at))
        placements = tuple(placements_list)
        self.documents[title] = DocumentState(new_text, placements)



def score_tokens(tokens: Iterable[TokenState], now_kst: datetime, require_mature: bool) -> ContributionScores:
    addition_buckets: dict[tuple[str, str, date], int] = defaultdict(int)
    removal_buckets: dict[tuple[str, str, date], int] = defaultdict(int)
    for token in tokens:
        retained = token.active_count > 0 and (
            not require_mature or token.matured or now_kst - token.continuous_since >= MATURITY
        )
        retained = retained or (
            require_mature
            and token.active_count == 0
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
            and (not require_mature or now_kst - removed_since >= MATURITY)
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
