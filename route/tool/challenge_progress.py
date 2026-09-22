from __future__ import annotations

import html
from typing import Protocol

import flask

from .func import acl_check, db_change, get_lang, get_time, ip_or_user
from .ranking_challenges import RankingChallenge, earned_ranking_challenges
from .ranking_monthly_awards import Cursor


class ChallengeCursor(Cursor, Protocol):
    rowcount: int


class ChallengeConnection(Protocol):
    def cursor(self) -> ChallengeCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


async def refresh_challenges(connection: ChallengeConnection, member_id: str) -> tuple[RankingChallenge, ...]:
    if ip_or_user(member_id) == 1:
        return ()
    refreshed: dict[str, tuple[RankingChallenge, ...]] = flask.g.setdefault("challenge_progress", {})
    if member_id in refreshed:
        return refreshed[member_id]

    rankings = (earned_ranking_challenges(connection, member_id, db_change)
                if "rankings" in flask.current_app.extensions else ())
    is_admin = await acl_check(tool="all_admin_auth", ip=member_id) == 0
    mysql = db_change("?") == "%s"
    cursor = connection.cursor()
    committed = False
    try:
        cursor.execute("START TRANSACTION" if mysql else "BEGIN IMMEDIATE")
        cursor.execute(db_change("select name, data from user_set where id = ?")
                       + (" FOR UPDATE" if mysql else ""), [member_id])
        stored = dict(cursor.fetchall())
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

        level = 0
        while experience >= 500 + level * 50:
            experience -= 500 + level * 50
            level += 1
        for name, value in (("level", str(level)), ("experience", str(experience))):
            if stored.get(name) == value:
                continue
            if name in stored:
                cursor.execute(db_change("update user_set set data = ? where id = ? and name = ?"),
                               [value, member_id, name])
            else:
                cursor.execute(db_change("insert into user_set (name, id, data) values (?, ?, ?)"),
                               [name, member_id, value])
        connection.commit()
        committed = True
    finally:
        if not committed:
            connection.rollback()
        cursor.close()
    refreshed[member_id] = rankings
    return rankings
