from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from .ranking_contribution_scores import ContributorEntry, Period
from .ranking_incremental import CheckpointConflict, read_revisions, refresh_scores, source_snapshot
from .ranking_checkpoint_store import ensure_schema as ensure_checkpoint_schema
from .ranking_monthly_awards import MonthlyHistory, ensure_schema, finalize_months
from .ranking_alltime_awards import ensure_alltime_schema, confirm_alltime_candidates


class ContributorCache:
    def __init__(
        self,
        connect: Callable,
        db_change: Callable[[str], str],
        get_display_name: Callable,
        clock: Callable[[], float],
        refresh_seconds: float | None,
    ) -> None:
        self.connect = connect
        self.db_change = db_change
        self.get_display_name = get_display_name
        self.clock = clock
        self.refresh_seconds = refresh_seconds
        self.lock = threading.Lock()
        self.items: tuple[dict[str, str | float], ...] = ()
        self.member_ranks: dict[str, dict[str, int | float]] = {}
        self.period_items: dict[Period, tuple[dict[str, str | float], ...]] = {
            "all": self.items
        }
        self.period_member_ranks: dict[Period, dict[str, dict[str, int | float]]] = {
            "all": self.member_ranks
        }
        self.documents: dict[Period, dict[str, tuple[dict[str, str | float], ...]]] = {
            "all": {}
        }
        self.document_contributor_items: dict[
            Period, dict[str, tuple[dict[str, str | float], ...]]
        ] = {"all": {}}
        self.document_contributor_ranks: dict[
            Period, dict[str, dict[str, dict[str, int | float]]]
        ] = {"all": {}}
        self.generated_at = 0
        self.state = "loading"
        self.ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def snapshot(
        self, member_id: str, period: Period = "all"
    ) -> tuple[tuple[dict[str, str | float], ...], int, str, dict[str, int | float] | None]:
        with self.lock:
            if period == "all":
                return self.items, self.generated_at, self.state, self.member_ranks.get(member_id)
            return (
                self.period_items.get(period, ()),
                self.generated_at,
                self.state,
                self.period_member_ranks.get(period, {}).get(member_id),
            )

    def document_snapshot(
        self, member_id: str, period: Period = "all"
    ) -> tuple[tuple[dict[str, str | float], ...], int, str]:
        with self.lock:
            return self.documents.get(period, {}).get(member_id, ()), self.generated_at, self.state

    def document_contributors_snapshot(
        self, title: str, member_id: str, period: Period = "all"
    ) -> tuple[
        tuple[dict[str, str | float], ...],
        int,
        str,
        dict[str, int | float] | None,
    ]:
        with self.lock:
            return (
                self.document_contributor_items.get(period, {}).get(title, ()),
                self.generated_at,
                self.state,
                self.document_contributor_ranks.get(period, {})
                .get(title, {})
                .get(member_id),
            )

    def _run(self) -> None:
        succeeded = False
        try:
            self._refresh()
            succeeded = True
        finally:
            with self.lock:
                if not succeeded:
                    self.state = "error"
            self.ready.set()
            if self.refresh_seconds is not None:
                timer = threading.Timer(self.refresh_seconds, self.start)
                timer.daemon = True
                timer.start()

    def _refresh(self) -> None:
        now_epoch = int(self.clock())
        for attempt in range(2):
            try:
                with self.connect() as connection:
                    ensure_schema(connection, self.db_change)
                    ensure_alltime_schema(connection, self.db_change)
                    ensure_checkpoint_schema(connection, self.db_change)
                    with source_snapshot(connection, self.db_change):
                        documents = self._documents(connection)
                        calculated = self._compute(connection, documents, now_epoch)
                break
            except CheckpointConflict:
                if attempt:
                    raise
        with self.lock:
            (self.period_items, self.period_member_ranks, self.documents,
             self.document_contributor_items, self.document_contributor_ranks) = calculated
            self.items = self.period_items["all"]
            self.member_ranks = self.period_member_ranks["all"]
            self.generated_at = now_epoch
            self.state = "ready"

    def _documents(self, connection) -> dict[str, str]:
        cursor = connection.cursor()
        cursor.execute(self.db_change("select title, data from data"))
        documents = cursor.fetchall()
        cursor.execute(self.db_change("select title, data from acl where type = 'view'"))
        policies = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.execute(self.db_change("select distinct link from back where type = 'redirect'"))
        redirects = {row[0] for row in cursor.fetchall()}
        return {
            title: body
            for title, body in documents
            if policies.get(title, "") in {"", "all", "user"} and title not in redirects
        }

    def _compute(
        self, connection, documents: dict[str, str], now_epoch: int
    ) -> tuple[
        dict[Period, tuple[dict[str, str | float], ...]],
        dict[Period, dict[str, dict[str, int | float]]],
        dict[Period, dict[str, tuple[dict[str, str | float], ...]]],
        dict[Period, dict[str, tuple[dict[str, str | float], ...]]],
        dict[Period, dict[str, dict[str, dict[str, int | float]]]],
    ]:
        cursor = connection.cursor()
        cursor.execute(self.db_change("select id from user_set where name = 'pw'"))
        members = {row[0] for row in cursor.fetchall()}
        cursor.close()
        now = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
        calculation = refresh_scores(connection, self.db_change, documents, members, now)
        scores = calculation.scores
        revisions = None

        def load_revisions():
            nonlocal revisions
            if revisions is None:
                revisions = tuple(row for row in read_revisions(connection, self.db_change)
                                  if row.title in documents)
            return revisions

        period_items: dict[Period, tuple[dict[str, str | float], ...]] = {}
        period_member_ranks: dict[Period, dict[str, dict[str, int | float]]] = {}
        document_scores: dict[Period, dict[str, tuple[dict[str, str | float], ...]]] = {}
        document_contributor_items: dict[
            Period, dict[str, tuple[dict[str, str | float], ...]]
        ] = {}
        document_contributor_ranks: dict[
            Period, dict[str, dict[str, dict[str, int | float]]]
        ] = {}
        identities: dict[str, tuple[str, str] | None] = {}

        def identity(user_id: str) -> tuple[str, str] | None:
            if user_id not in identities:
                name = self.get_display_name(connection, user_id).strip()
                identities[user_id] = (
                    None
                    if not name or (name == user_id and name.isdigit())
                    else (
                        name,
                        "/w/user:" + quote(user_id, safe="") if name == user_id else "",
                    )
                )
            return identities[user_id]

        finalize_months(connection, self.db_change, MonthlyHistory(
            (), frozenset(members),
            frozenset(
                user_id for user_id in members
                if identity(user_id) is not None
            ),
            now,
        ), first_revision_at=calculation.first_revision_at, load_revisions=load_revisions)

        alltime_entries: list[ContributorEntry] = []
        for named_scores in scores.periods():
            period = named_scores.period
            period_scores = named_scores.scores
            items: list[dict[str, str | float]] = []
            member_ranks: dict[str, dict[str, int | float]] = {}
            documents_by_member = {
                item.user_id: tuple(
                    {"title": row.title, "score": row.score}
                    for row in item.documents
                )
                for item in period_scores.documents
            }
            raw_document_contributors: dict[str, list[tuple[float, str]]] = defaultdict(list)
            for contributor in period_scores.documents:
                for row in contributor.documents:
                    raw_document_contributors[row.title].append((row.score, contributor.user_id))
            items_by_document: dict[str, tuple[dict[str, str | float], ...]] = {}
            ranks_by_document: dict[str, dict[str, dict[str, int | float]]] = {}
            for title, raw_contributors in raw_document_contributors.items():
                document_items: list[dict[str, str | float]] = []
                document_ranks: dict[str, dict[str, int | float]] = {}
                for raw_score, user_id in sorted(
                    raw_contributors, key=lambda item: (-item[0], item[1])
                ):
                    display = identity(user_id)
                    if display is None:
                        continue
                    name, url = display
                    score = round(raw_score, 2)
                    document_items.append({"name": name, "url": url, "score": score})
                    document_ranks[user_id] = {"rank": len(document_items), "score": score}
                items_by_document[title] = tuple(document_items)
                ranks_by_document[title] = document_ranks
            for entry in period_scores.contributors:
                display = identity(entry.user_id)
                if display is None:
                    continue
                if period == "all" and entry.score > 0:
                    alltime_entries.append(entry)
                name, url = display
                score = round(entry.score, 2)
                items.append({"name": name, "url": url, "score": score})
                member_ranks[entry.user_id] = {"rank": len(items), "score": score}
            period_items[period] = tuple(items)
            period_member_ranks[period] = member_ranks
            document_scores[period] = documents_by_member
            document_contributor_items[period] = items_by_document
            document_contributor_ranks[period] = ranks_by_document
        confirm_alltime_candidates(
            connection, self.db_change, tuple(alltime_entries), (), documents,
            members, now, load_revisions=load_revisions, revision_limits=calculation.revision_limits,
        )
        connection.commit()
        return (
            period_items,
            period_member_ranks,
            document_scores,
            document_contributor_items,
            document_contributor_ranks,
        )
