from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Final

from .ranking_contribution_scores import HistoryRevision


KST: Final = timezone(timedelta(hours=9))
MATURITY: Final = timedelta(hours=24)
REMOVAL_GRACE: Final = timedelta(hours=24)


def as_kst(value: datetime) -> datetime:
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def can_own(revision: HistoryRevision, members: Set[str], contiguous: bool) -> bool:
    return (
        contiguous
        and revision.ip in members
        and revision.hide != "O"
        and "회원가입" not in revision.send
        and not revision.title.lower().startswith(("user:", "file:"))
        and (
            revision.type in {"", "r1", "direct", "delete"}
            or revision.type == "edit_request" and revision.leng != 0
        )
    )


@dataclass(frozen=True, slots=True)
class DocumentState:
    text: str
    placements: tuple[int, ...]


class TokenState:
    __slots__ = (
        "active_count",
        "author",
        "continuous_since",
        "day",
        "grace_until",
        "lineage",
        "matured",
        "removal_active",
        "removal_author",
        "removal_day",
        "removal_lineage",
        "removed_since",
    )

    active_count: int
    author: str | None
    continuous_since: datetime
    day: date | None
    grace_until: datetime | None
    lineage: str
    matured: bool
    removal_active: bool
    removal_author: str | None
    removal_day: date | None
    removal_lineage: str | None
    removed_since: datetime | None

    def __init__(
        self, author: str | None, day: date | None, lineage: str, since: datetime
    ) -> None:
        self.active_count = 1
        self.author = author
        self.continuous_since = since
        self.day = day
        self.grace_until = None
        self.lineage = lineage
        self.matured = False
        self.removal_active = False
        self.removal_author = None
        self.removal_day = None
        self.removal_lineage = None
        self.removed_since = None
