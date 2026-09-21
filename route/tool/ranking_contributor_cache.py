from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from .ranking_contributions import HistoryRevision, compute_contributors


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
        self.generated_at = 0
        self.state = "loading"
        self.ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def snapshot(self) -> tuple[tuple[dict[str, str | float], ...], int, str]:
        with self.lock:
            return self.items, self.generated_at, self.state

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
            items = self._compute(connection, documents, now_epoch)
        with self.lock:
            self.items = items
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
    ) -> tuple[dict[str, str | float], ...]:
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
        entries = compute_contributors(
            revisions, documents, members, datetime.fromtimestamp(now_epoch, tz=timezone.utc)
        )
        items: list[dict[str, str | float]] = []
        for entry in entries:
            name = self.get_display_name(connection, entry.user_id).strip()
            if not name or (name == entry.user_id and name.isdigit()):
                continue
            url = "/w/user:" + quote(entry.user_id, safe="") if name == entry.user_id else ""
            items.append({"name": name, "url": url, "score": round(entry.score, 2)})
        return tuple(items)
