from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from itertools import groupby
from typing import TYPE_CHECKING
from unicodedata import normalize

from .ranking_contribution_scores import HistoryRevision
from .ranking_contribution_state import DocumentState

if TYPE_CHECKING:
    from .ranking_contribution_engine import DocumentContributionEngine


@dataclass(frozen=True, slots=True)
class RevisionSnapshot:
    digest: str
    length: int
    ranges: tuple[tuple[int, int], ...]

    @classmethod
    def capture(cls, document: DocumentState) -> RevisionSnapshot:
        ranges: list[tuple[int, int]] = []
        for token_id in document.placements:
            if ranges and ranges[-1][0] + ranges[-1][1] == token_id:
                start, length = ranges[-1]
                ranges[-1] = (start, length + 1)
            else:
                ranges.append((token_id, 1))
        return cls(sha256(document.text.encode()).hexdigest(), len(document.text), tuple(ranges))

    def placements(self) -> tuple[int, ...]:
        return tuple(token_id for start, length in self.ranges for token_id in range(start, start + length))


def restore_revision(engine: DocumentContributionEngine, revision: HistoryRevision, at: datetime) -> bool:
    """Use a route-authored target marker only when its body and live lineage agree."""
    if revision.type != 'revert':
        return False
    marker = re.search(r' \(r([1-9][0-9]*)\)\Z', revision.send)
    if marker is None or int(marker[1]) >= int(revision.id):
        return False
    snapshot = engine.revision_snapshots.get(int(marker[1]))
    body = normalize('NFC', revision.data)
    if snapshot is None or snapshot.length != len(body) or snapshot.digest != sha256(body.encode()).hexdigest():
        return False
    placements = snapshot.placements()
    target = set(placements)
    old = engine.documents.get(engine.title, DocumentState('', ()))
    current = set(old.placements)
    if (len(target) != len(body) or len(current) != len(old.placements)
            or any(token_id not in engine.tokens
                   or engine.tokens[token_id].active_count != int(token_id in current)
                   for token_id in target | current)):
        return False
    for removed, positions in groupby(enumerate(old.placements), key=lambda item: item[1] not in target):
        if removed:
            indices = [index for index, _ in positions]
            start, end = indices[0], indices[-1] + 1
            token_ids = old.placements[start:end]
            engine.deleted_spans[engine.title].append((old.text[start:end], token_ids))
            engine.remove(token_ids, at, revision.ip, None, None, True)
    engine.reuse(tuple(token_id for token_id in placements if token_id not in current), at)
    engine.documents[engine.title] = DocumentState(body, placements)
    return True
