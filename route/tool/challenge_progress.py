from __future__ import annotations

import html
import sqlite3
from time import time
from typing import Protocol

import flask
from pymysql import MySQLError

from .func import acl_check, db_change, get_lang, get_time, ip_or_user
from .ranking_challenges import RANKING_CHALLENGES, RankingChallenge, earned_ranking_challenges
from .ranking_monthly_awards import Cursor


class ChallengeCursor(Cursor, Protocol):
    rowcount: int


class ChallengeConnection(Protocol):
    def cursor(self) -> ChallengeCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


def ensure_challenge_indexes(connection: ChallengeConnection) -> None:
    cursor = connection.cursor()
    try:
        mysql = db_change("?") == "%s"
        for table, column in (("history", "ip"), ("topic", "ip"), ("user_set", "id")):
            name = f"challenge_{table}_member_idx"
            if mysql:
                cursor.execute(f"SHOW INDEX FROM {table} WHERE Key_name = %s", [name])
                if cursor.fetchall():
                    continue
                try:
                    cursor.execute(f"CREATE INDEX {name} ON {table} ({column}(128))")
                except MySQLError as error:
                    if not error.args or error.args[0] != 1061:
                        raise
            else:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})")
    finally:
        cursor.close()


async def refresh_challenges(
    connection: ChallengeConnection, member_id: str, *, automatic: bool = False,
) -> tuple[RankingChallenge, ...]:
    if ip_or_user(member_id) == 1:
        return ()
    last_member, last_refresh = flask.session.get("challenge_refresh", ("", 0))
    if automatic and last_member == member_id and 0 <= time() - last_refresh < 60:
        return ()
    refreshed: dict[str, tuple[RankingChallenge, ...]] = flask.g.setdefault("challenge_progress", {})
    if member_id in refreshed:
        return refreshed[member_id]

    is_admin = await acl_check(tool="all_admin_auth", ip=member_id) == 0
    mysql = db_change("?") == "%s"
    cursor = connection.cursor()
    transaction_started = False
    try:
        # Read-only refreshes avoid the writer queue; changes are reread after locking.
        for write_locked in (False, True):
            if write_locked:
                if automatic and not mysql:
                    cursor.execute("PRAGMA busy_timeout")
                    busy_timeout = int(cursor.fetchall()[0][0])
                    try:
                        cursor.execute("PRAGMA busy_timeout = 0")
                        cursor.execute("BEGIN IMMEDIATE")
                    except sqlite3.OperationalError as error:
                        if error.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                            raise
                        flask.current_app.logger.warning(
                            "challenge_refresh_skipped reason=sqlite_busy attempted_at=%s last_success_at=%s",
                            time(), last_refresh if last_member == member_id else None,
                        )
                        refreshed[member_id] = ()
                        return ()
                    finally:
                        cursor.execute(f"PRAGMA busy_timeout = {busy_timeout}")
                else:
                    cursor.execute("START TRANSACTION" if mysql else "BEGIN IMMEDIATE")
                transaction_started = True
            cursor.execute(db_change("select name, data from user_set where id = ?")
                           + (" FOR UPDATE" if mysql and write_locked else ""), [member_id])
            stored = dict(cursor.fetchall())
            rankings = ()
            if "rankings" in flask.current_app.extensions:
                try:
                    rankings = earned_ranking_challenges(connection, member_id, db_change)
                except sqlite3.OperationalError as error:
                    if "no such table" not in str(error).lower():
                        raise
                    rankings = tuple(challenge for challenge in RANKING_CHALLENGES
                                     if "challenge_" + challenge.key in stored)
                except MySQLError as error:
                    if not error.args or error.args[0] != 1146:
                        raise
                    rankings = tuple(challenge for challenge in RANKING_CHALLENGES
                                     if "challenge_" + challenge.key in stored)
            experience = sum(challenge.experience for challenge in rankings)
            earned = [challenge.key for challenge in rankings]
            for table, category in (("history", "contribute"), ("topic", "discussion")):
                cursor.execute(db_change(f"select count(*) from {table} where ip = ?"), [member_id])
                count = int(cursor.fetchall()[0][0])
                experience += 5 * count
                for threshold, ordinal, reward in ((1, "first", 500), (10, "tenth", 1000),
                                                   (100, "hundredth", 3000), (1000, "thousandth", 10000)):
                    if count >= threshold:
                        earned.append(f"{ordinal}_{category}")
                        experience += reward
            if "challenge_admin" in stored or is_admin:
                earned.append("admin")
                experience += 10000

            level = 0
            while experience >= 500 + level * 50:
                experience -= 500 + level * 50
                level += 1
            values = (("level", str(level)), ("experience", str(experience)))
            if not write_locked:
                if (any("challenge_" + key not in stored for key in earned)
                        or any(stored.get(name) != value for name, value in values)):
                    continue
                break

            for key in earned:
                name = "challenge_" + key
                if name in stored:
                    continue
                cursor.execute(db_change(
                    "insert into user_set (name, id, data) select ?, ?, '1' "
                    "where not exists (select 1 from user_set where name = ? and id = ?)"
                ), [name, member_id, name, member_id])
                if cursor.rowcount == 1:
                    label = html.escape(get_lang(connection, "challenge_achieved"))
                    title = html.escape(get_lang(connection, "challenge_title_" + key))
                    message = 'tool:system | <a href="/challenge">' + label + ': ' + title + '</a>'
                    cursor.execute(db_change(
                        "insert into user_notice (id, name, data, date, readme) values (?, ?, ?, ?, '')"
                    ), [name, member_id, message, get_time()])

            for name, value in values:
                if stored.get(name) == value:
                    continue
                if name in stored:
                    cursor.execute(db_change("update user_set set data = ? where id = ? and name = ?"),
                                   [value, member_id, name])
                else:
                    cursor.execute(db_change("insert into user_set (name, id, data) values (?, ?, ?)"),
                                   [name, member_id, value])
            connection.commit()
            transaction_started = False
            break
    finally:
        if transaction_started:
            connection.rollback()
        cursor.close()
    refreshed[member_id] = rankings
    flask.session["challenge_refresh"] = (member_id, time())
    return rankings
