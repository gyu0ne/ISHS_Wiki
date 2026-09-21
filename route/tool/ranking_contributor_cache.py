from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from .ranking_contribution_scores import Period
from .ranking_contributions import HistoryRevision, compute_contribution_scores


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
        with self.connect() as connection:
            documents = self._documents(connection)
            period_items, period_member_ranks, document_scores = self._compute(
                connection, documents, now_epoch
            )
        with self.lock:
            self.items = period_items["all"]
            self.member_ranks = period_member_ranks["all"]
            self.period_items = period_items
            self.period_member_ranks = period_member_ranks
            self.documents = document_scores
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
    ]:
        cursor = connection.cursor()
        cursor.execute(self.db_change("select id from user_set where name = 'pw'"))
        members = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            self.db_change(
                "select id, title, data, date, ip, send, leng, hide, type from history order by date, title, id"
            )
        )
        revisions = tuple(
            HistoryRevision(
                id=row[0], title=row[1], data=row[2], date=datetime.fromisoformat(row[3]),
                ip=row[4], send=row[5], leng=int(str(row[6]).replace("+", "") or 0),
                hide=row[7], type=row[8],
            )
            for row in cursor.fetchall()
            if row[1] in documents
        )
        scores = compute_contribution_scores(
            revisions, documents, members, datetime.fromtimestamp(now_epoch, tz=timezone.utc)
        )
        period_items: dict[Period, tuple[dict[str, str | float], ...]] = {}
        period_member_ranks: dict[Period, dict[str, dict[str, int | float]]] = {}
        document_scores: dict[Period, dict[str, tuple[dict[str, str | float], ...]]] = {}
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
            for entry in period_scores.contributors:
                name = self.get_display_name(connection, entry.user_id).strip()
                if not name or (name == entry.user_id and name.isdigit()):
                    continue
                url = "/w/user:" + quote(entry.user_id, safe="") if name == entry.user_id else ""
                score = round(entry.score, 2)
                items.append({"name": name, "url": url, "score": score})
                member_ranks[entry.user_id] = {"rank": len(items), "score": score}
            period_items[period] = tuple(items)
            period_member_ranks[period] = member_ranks
            document_scores[period] = documents_by_member
        return period_items, period_member_ranks, document_scores
