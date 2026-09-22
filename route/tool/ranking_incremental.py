"""Persist document replay checkpoints while keeping current-body overlays separate."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Set
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256

from . import ranking_checkpoint_store as store
from .ranking_contribution_engine import DocumentContributionEngine
from .ranking_contribution_scores import ContributionBucket, ContributionScores, HistoryRevision
from .ranking_contribution_state import as_kst
from .ranking_monthly_awards import Connection
from .ranking_replay_checkpoint import InvalidCheckpoint


class CheckpointConflict(RuntimeError):
    """Another refresh committed while this refresh was calculating."""


@contextmanager
def source_snapshot(connection: store.CheckpointConnection,
                    sql: Callable[[str], str]) -> Iterator[None]:
    cursor = connection.cursor()
    try:
        if sql("?") == "%s":
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        else:
            cursor.execute("BEGIN")
        yield
    finally:
        connection.rollback()
        cursor.close()


@dataclass(frozen=True, slots=True)
class RankingCalculation:
    scores: ContributionScores
    first_revision_at: datetime | None
    revision_limits: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class DocumentCheckpoint:
    body_hash: str
    last_id: int
    first_at: datetime | None
    future_at: datetime | None
    credit_limit: int
    buckets: tuple[ContributionBucket, ...]

    def encode(self) -> str:
        return json.dumps({
            "version": 1,
            "body_hash": self.body_hash, "last_id": self.last_id,
            "first_at": self.first_at.isoformat() if self.first_at else None,
            "future_at": self.future_at.isoformat() if self.future_at else None,
            "credit_limit": self.credit_limit,
            "buckets": [(row.user_id, row.title, row.day.isoformat(), row.additions, row.removals)
                        for row in self.buckets],
        }, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def decode(cls, payload: str) -> DocumentCheckpoint:
        value = json.loads(payload)
        if value["version"] != 1:
            raise InvalidCheckpoint("Unsupported contribution metadata version")
        return cls(
            value["body_hash"], int(value["last_id"]),
            datetime.fromisoformat(value["first_at"]) if value["first_at"] else None,
            datetime.fromisoformat(value["future_at"]) if value["future_at"] else None,
            int(value["credit_limit"]),
            tuple(ContributionBucket(user, title, date.fromisoformat(day), int(added), int(removed))
                  for user, title, day, added, removed in value["buckets"]),
        )


@dataclass(frozen=True, slots=True)
class ReplayInput:
    title: str
    body: str
    previous: DocumentCheckpoint | None
    engine: DocumentContributionEngine
    revisions: tuple[HistoryRevision, ...]


def read_revisions(connection: Connection, sql: Callable[[str], str],
                   selection: tuple[str, tuple[str | int, ...]] = ("", ())) -> tuple[HistoryRevision, ...]:
    clause, parameters = selection
    cursor = connection.cursor()
    try:
        cursor.execute(sql("SELECT id, title, data, date, ip, send, leng, hide, type FROM history "
                           + clause + " ORDER BY date, title, id"), parameters)
        return tuple(HistoryRevision(
            row[0], row[1], row[2], datetime.fromisoformat(row[3]), row[4], row[5],
            int(str(row[6]).replace("+", "") or 0), row[7], row[8],
        ) for row in cursor.fetchall())
    finally:
        cursor.close()


def _prepare(connection: store.CheckpointConnection, sql: Callable[[str], str],
             snapshot: store.Snapshot, documents: Mapping[str, str],
             member_hash: str, now: datetime) -> tuple[dict[str, DocumentCheckpoint], list[ReplayInput]]:
    checkpoints: dict[str, DocumentCheckpoint] = {}
    for title, value in snapshot.checkpoints.items():
        if title in documents:
            try:
                checkpoints[title] = DocumentCheckpoint.decode(value)
            except (ValueError, KeyError, TypeError, IndexError):
                continue
    changes: dict[str, list[store.HistoryChange]] = {}
    for event in snapshot.events:
        changes.setdefault(event.title, []).append(event)
    pending: list[ReplayInput] = []
    for title, body in documents.items():
        previous = checkpoints.get(title)
        events = changes.get(title, [])
        rebuild = (previous is None or snapshot.member_hash != member_hash
                   or previous.future_at is not None and previous.future_at <= now
                   or any(event.kind == "rebuild" or int(event.revision_id) <= previous.last_id
                          for event in events))
        changed = rebuild or bool(events)
        if not changed and previous.body_hash == sha256(body.encode()).hexdigest():
            continue
        rows: tuple[HistoryRevision, ...] = ()
        engine = DocumentContributionEngine(title)
        if rebuild:
            rows = read_revisions(connection, sql, ("WHERE title = ?", (title,)))
            previous = None
        else:
            payload = store.load_checkpoint(connection, sql, title)
            if payload is None:
                raise CheckpointConflict(title)
            try:
                engine = DocumentContributionEngine.load_checkpoint(payload)
            except (ValueError, KeyError, TypeError, IndexError):
                rows = read_revisions(connection, sql, ("WHERE title = ?", (title,)))
                previous = None
            if changed and previous is not None:
                numeric = "SIGNED" if sql("?") == "%s" else "INTEGER"
                rows = read_revisions(connection, sql, (
                    "WHERE title = ? AND CAST(id AS " + numeric + ") > ?", (title, previous.last_id),
                ))
        pending.append(ReplayInput(title, body, previous, engine, rows))
    return checkpoints, pending


def _advance(item: ReplayInput, members: Set[str], now: datetime) -> tuple[DocumentCheckpoint, str]:
    engine = item.engine
    engine.advance(item.revisions, members, now)
    previous = item.previous
    elapsed = [as_kst(row.date) for row in item.revisions if as_kst(row.date) <= now]
    future = [as_kst(row.date) for row in item.revisions if as_kst(row.date) > now]
    if previous is not None:
        if previous.first_at is not None:
            elapsed.append(previous.first_at)
        if previous.future_at is not None:
            future.append(previous.future_at)
    limit = previous.credit_limit if previous else 0
    blocked = previous is not None and previous.future_at is not None
    for revision in sorted(item.revisions, key=lambda row: int(row.id)):
        blocked = blocked or as_kst(revision.date) > now
        if not blocked:
            limit = int(revision.id)
    checkpoint = DocumentCheckpoint(
        sha256(item.body.encode()).hexdigest(),
        max((int(row.id) for row in item.revisions), default=previous.last_id if previous else 0),
        min(elapsed) if elapsed else None, min(future) if future else None, limit,
        engine.scores(item.body, now).buckets,
    )
    return checkpoint, engine.dump_checkpoint()


def refresh_scores(connection: store.CheckpointConnection, sql: Callable[[str], str],
                   documents: Mapping[str, str], members: Set[str], now: datetime) -> RankingCalculation:
    """Read under the caller's snapshot transaction, then publish after replay without a write lock."""
    member_hash = sha256(json.dumps(sorted(members), ensure_ascii=False).encode()).hexdigest()
    snapshot = store.snapshot(connection, sql)
    checkpoints, pending = _prepare(connection, sql, snapshot, documents, member_hash, as_kst(now))
    connection.commit()
    updates: list[store.CheckpointWrite] = []
    for item in pending:
        checkpoint, payload = _advance(item, members, as_kst(now))
        checkpoints[item.title] = checkpoint
        updates.append(store.CheckpointWrite(item.title, checkpoint.encode(), payload))
    removals = tuple(title for title in snapshot.checkpoints if title not in documents)
    if not store.publish(connection, sql, snapshot, updates, removals, member_hash):
        raise CheckpointConflict
    dates = [item.first_at for item in checkpoints.values() if item.first_at is not None]
    buckets = tuple(sorted((bucket for item in checkpoints.values() for bucket in item.buckets),
                           key=lambda row: (row.user_id, row.title, row.day)))
    return RankingCalculation(ContributionScores(buckets), min(dates) if dates else None,
                              {title: item.credit_limit for title, item in checkpoints.items()})
