from __future__ import annotations

import json
from datetime import date, datetime
from typing import TYPE_CHECKING, TypeAlias

from .ranking_contribution_state import DocumentState, TokenState

if TYPE_CHECKING:
    from .ranking_contribution_engine import DocumentContributionEngine

Json: TypeAlias = str | int | bool | None | list['Json'] | dict[str, 'Json']


class InvalidCheckpoint(ValueError):
    """A persisted replay checkpoint has an unsupported or malformed shape."""


def _list(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise InvalidCheckpoint('Expected checkpoint array')
    return value


def _str(value: Json) -> str:
    if not isinstance(value, str):
        raise InvalidCheckpoint('Expected checkpoint string')
    return value


def _int(value: Json) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidCheckpoint('Expected checkpoint integer')
    return value


def _bool(value: Json) -> bool:
    if not isinstance(value, bool):
        raise InvalidCheckpoint('Expected checkpoint boolean')
    return value


def _optional_str(value: Json) -> str | None:
    return None if value is None else _str(value)


def _datetime(value: Json) -> datetime | None:
    return None if value is None else datetime.fromisoformat(_str(value))


def _date(value: Json) -> date | None:
    return None if value is None else date.fromisoformat(_str(value))


def encode_checkpoint(engine: DocumentContributionEngine) -> str:
    """Encode historical state only; positional token rows avoid repeated field names."""
    tokens = [
        [token.author, token.day.isoformat() if token.day else None,
         token.continuous_since.isoformat(), token.active_count, token.matured,
         token.grace_until.isoformat() if token.grace_until else None,
         token.removal_active, token.removal_author,
         token.removal_day.isoformat() if token.removal_day else None,
         token.removal_lineage,
         token.removed_since.isoformat() if token.removed_since else None]
        for token in engine.tokens.values()
    ]
    document = engine.documents.get(engine.title, DocumentState('', ()))
    payload = [1, engine.title, engine.credit_limit, engine.last_revision,
               engine.last_applied_at.isoformat() if engine.last_applied_at else None,
               engine.uncertain, engine.frozen, document.text, list(document.placements),
               [[text, list(placements)] for text, placements in engine.deleted_spans[engine.title]],
               tokens]
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def decode_checkpoint(payload: str, engine_type: type[DocumentContributionEngine]) -> DocumentContributionEngine:
    """Parse the versioned JSON checkpoint without executable deserialization."""
    data = _list(json.loads(payload))
    if len(data) != 11 or _int(data[0]) != 1:
        raise InvalidCheckpoint('Unsupported replay checkpoint version')
    engine = engine_type(_str(data[1]), None if data[2] is None else _int(data[2]))
    engine.last_revision = None if data[3] is None else _int(data[3])
    engine.last_applied_at = _datetime(data[4])
    engine.uncertain, engine.frozen = _bool(data[5]), _bool(data[6])
    placements = tuple(_int(item) for item in _list(data[8]))
    engine.documents[engine.title] = DocumentState(_str(data[7]), placements)
    for item in _list(data[9]):
        span = _list(item)
        if len(span) != 2:
            raise InvalidCheckpoint('Invalid deleted span')
        engine.deleted_spans[engine.title].append((_str(span[0]), tuple(_int(value) for value in _list(span[1]))))
    for index, item in enumerate(_list(data[10])):
        row = _list(item)
        if len(row) != 11:
            raise InvalidCheckpoint('Invalid token row')
        token = TokenState(_optional_str(row[0]), _date(row[1]), engine.title,
                           datetime.fromisoformat(_str(row[2])))
        token.active_count, token.matured = _int(row[3]), _bool(row[4])
        token.grace_until = _datetime(row[5])
        token.removal_active, token.removal_author = _bool(row[6]), _optional_str(row[7])
        token.removal_day, token.removal_lineage = _date(row[8]), _optional_str(row[9])
        token.removed_since = _datetime(row[10])
        engine.tokens[index] = token
    engine.next_token_id = len(engine.tokens)
    spans = [(engine.text, placements), *engine.deleted_spans[engine.title]]
    if any(len(text) != len(ids) or any(index < 0 or index >= engine.next_token_id for index in ids)
           for text, ids in spans):
        raise InvalidCheckpoint('Invalid token references')
    return engine
