from __future__ import annotations

import html
import hmac
import secrets
import sqlite3
import time
from contextlib import nullcontext
from dataclasses import dataclass
from hashlib import sha256
from typing import Awaitable, Callable, Final
from urllib.parse import quote, urlsplit

from flask import Blueprint, Flask, current_app, jsonify, make_response, redirect, request, session
from itsdangerous import BadSignature, URLSafeSerializer
from pymysql import MySQLError

from .tool.ranking_contributor_cache import ContributorCache
from .tool.ranking_presentation import PAGE_SIZE, contributor_page, contributor_rows_html, pagination_html
from .tool.ranking_views import Connection, ensure_schema, get_popular, record_view


TICKET_SALT: Final = "ranking-view-v1"
TICKET_MIN_AGE: Final = 5
TICKET_MAX_AGE: Final = 1800
CACHE_SECONDS: Final = 300


@dataclass(frozen=True, slots=True)
class RankingDependencies:
    connect: Callable
    db_change: Callable[[str], str]
    acl_check: Callable[[str, str], Awaitable[int]]
    get_display_name: Callable
    member_is_eligible: Callable
    render_page: Callable[[str, str], Awaitable]
    clock: Callable[[], float]


class RankingService:
    def __init__(self, dependencies: RankingDependencies, refresh_seconds: float | None) -> None:
        self.dependencies = dependencies
        self.contributors = ContributorCache(
            dependencies.connect, dependencies.db_change, dependencies.get_display_name,
            dependencies.clock, refresh_seconds,
        )


ranking_blueprint = Blueprint("rankings", __name__)


def _service() -> RankingService | None:
    return current_app.extensions.get("rankings")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.secret_key, salt=TICKET_SALT)


def _member_id(connection, dependencies: RankingDependencies) -> str:
    user_id = session.get("id", "")
    if not isinstance(user_id, str) or not user_id:
        return ""
    cursor = connection.cursor()
    cursor.execute(
        dependencies.db_change("select 1 from user_set where id = ? and name = 'pw' limit 1"),
        [user_id],
    )
    return user_id if cursor.fetchone() and dependencies.member_is_eligible(connection, user_id) else ""


def _document_is_canonical(connection, title: str, dependencies: RankingDependencies) -> bool:
    cursor = connection.cursor()
    cursor.execute(dependencies.db_change("select 1 from data where title = ? limit 1"), [title])
    if cursor.fetchone() is None:
        return False
    cursor.execute(
        dependencies.db_change("select 1 from back where link = ? and type = 'redirect' limit 1"),
        [title],
    )
    return cursor.fetchone() is None


def _same_origin() -> bool:
    supplied = request.headers.get("Origin", "")
    if not supplied:
        return False
    try:
        origin = urlsplit(supplied)
    except ValueError:
        return False
    expected = urlsplit(request.host_url)
    return (origin.scheme, origin.netloc) == (expected.scheme, expected.netloc)


def _error(status: int):
    return jsonify({"response": "error"}), status


def issue_ranking_ticket(title: str, connection: Connection | None = None) -> str:
    if request.method != "GET":
        return ""
    service = _service()
    if service is None:
        return ""
    dependencies = service.dependencies
    with (dependencies.connect() if connection is None else nullcontext(connection)) as ranking_connection:
        member_id = _member_id(ranking_connection, dependencies)
        if not member_id or not _document_is_canonical(ranking_connection, title, dependencies):
            return ""
    nonce = session.get("_ranking_nonce")
    if not isinstance(nonce, str) or not nonce:
        nonce = secrets.token_urlsafe(24)
        session["_ranking_nonce"] = nonce
    return _serializer().dumps(
        {"member": member_id, "nonce": nonce, "title": title, "issued_at": int(dependencies.clock())}
    )


def wait_for_contributor_refresh(app: Flask, timeout: float = 5) -> bool:
    service = app.extensions.get("rankings")
    return service.contributors.ready.wait(timeout) if service is not None else False


def _member_token(member_id: str) -> str:
    secret = str(current_app.secret_key).encode()
    return hmac.new(secret, member_id.encode(), sha256).hexdigest()


@ranking_blueprint.get("/api/trending")
async def trending():
    service = _service()
    if service is None:
        return _error(503)
    dependencies = service.dependencies
    now_epoch = int(dependencies.clock())
    with dependencies.connect() as connection:
        if not _member_id(connection, dependencies):
            return _error(401)
        cursor = connection.cursor()
        cursor.execute(
            dependencies.db_change(
                "select link from back where title = '틀:인곽위키/공식문서' and type = 'include'"
            )
        )
        excluded = {"인곽위키:대문", *(row[0] for row in cursor.fetchall())}
        items = []
        for candidate in get_popular(connection, now_epoch, dependencies.db_change):
            if candidate.title in excluded:
                continue
            if not _document_is_canonical(connection, candidate.title, dependencies):
                continue
            if await dependencies.acl_check(candidate.title, "render") != 0:
                continue
            items.append(
                {"title": candidate.title, "url": "/w/" + quote(candidate.title, safe=""), "score": round(candidate.score, 2)}
            )
            if len(items) == 10:
                break
    rows = "".join(
        f'<li><span>{rank}</span> <a href="{item["url"]}">{html.escape(str(item["title"]))}</a></li>'
        for rank, item in enumerate(items, 1)
    )
    return jsonify(
        {"response": "ok", "items": items, "data": f'<ul class="opennamu_trending_sidebar">{rows}</ul>', "generated_at": now_epoch, "stale": False}
    )


@ranking_blueprint.get("/api/rankings/contributors")
async def contributors():
    service = _service()
    if service is None:
        return _error(503)
    with service.dependencies.connect() as connection:
        member_id = _member_id(connection, service.dependencies)
        if not member_id:
            return _error(401)
    if await service.dependencies.acl_check("", "render") != 0:
        return _error(403)
    items, generated_at, state, my_rank = service.contributors.snapshot(member_id)
    page, total_pages, start = contributor_page(request.args.get("page", "1"), len(items))
    response = jsonify(
        {
            "response": "ok", "items": items[start:start + PAGE_SIZE], "me": my_rank,
            "generated_at": generated_at, "stale": state != "ready", "page": page,
            "page_size": PAGE_SIZE, "total": len(items), "total_pages": total_pages,
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ranking_blueprint.get("/rankings")
async def rankings_page():
    service = _service()
    if service is None:
        return _error(503)
    with service.dependencies.connect() as connection:
        member_id = _member_id(connection, service.dependencies)
        if not member_id:
            return redirect("/login")
    if await service.dependencies.acl_check("", "render") != 0:
        return _error(403)
    items, _, state, my_rank = service.contributors.snapshot(member_id)
    if state == "loading":
        response = make_response(await service.dependencies.render_page("기여자 순위", "<p>불러오는 중입니다.</p>"))
        response.headers["Refresh"] = "5"
        return response
    if state == "error":
        return await service.dependencies.render_page("기여자 순위", "<p>불러오지 못했습니다.</p>")
    page, total_pages, start = contributor_page(request.args.get("page", "1"), len(items))
    rows = contributor_rows_html(items[start:start + PAGE_SIZE], start)
    personal = (
        f'<span class="ringo_my_rank_values"><strong>{my_rank["rank"]}위</strong><span>{my_rank["score"]:.2f}점</span></span>'
        if my_rank is not None else '<span>아직 순위가 없습니다.</span>'
    )
    body = (
        '<div class="opennamu_main"><table id="main_table_set" class="ringo_contributor_table"><thead><tr><th scope="col">순위</th><th scope="col">이름</th><th scope="col">점수</th></tr></thead><tbody>'
        + rows + '</tbody></table><section class="ringo_my_rank" aria-label="내 순위"><strong>내 순위</strong>'
        + personal + '</section>' + pagination_html(page, total_pages) + '</div>'
    )
    response = make_response(await service.dependencies.render_page("기여자 순위", body))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ranking_blueprint.post("/api/ranking/view")
async def qualify_view():
    service = _service()
    if service is None:
        return _error(503)
    if not _same_origin():
        return _error(403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("ticket"), str):
        return _error(400)
    try:
        ticket = _serializer().loads(payload["ticket"])
    except BadSignature:
        return _error(400)
    dependencies = service.dependencies
    now_epoch = int(dependencies.clock())
    if not isinstance(ticket, dict) or set(ticket) != {"member", "nonce", "title", "issued_at"}:
        return _error(400)
    age = now_epoch - ticket["issued_at"] if isinstance(ticket["issued_at"], int) else -1
    if age < TICKET_MIN_AGE or age > TICKET_MAX_AGE:
        return _error(400)
    if ticket["nonce"] != session.get("_ranking_nonce"):
        return _error(400)
    with dependencies.connect() as connection:
        member_id = _member_id(connection, dependencies)
        if not member_id or ticket["member"] != member_id:
            return _error(401)
        title = ticket["title"]
        if not isinstance(title, str) or not _document_is_canonical(connection, title, dependencies):
            return _error(404)
        if await dependencies.acl_check(title, "render") != 0:
            return _error(403)
        counted = record_view(connection, title, title, _member_token(member_id), now_epoch, dependencies.db_change)
    return jsonify({"response": "ok", "counted": counted})


def init_rankings(
    app: Flask,
    *,
    connect: Callable,
    db_change: Callable[[str], str],
    acl_check: Callable[[str, str], Awaitable[int]],
    get_display_name: Callable,
    render_page: Callable[[str, str], Awaitable],
    member_is_eligible: Callable = lambda connection, user_id: True,
    clock: Callable[[], float] = time.time,
    contributor_refresh_seconds: float | None = CACHE_SECONDS,
) -> None:
    dependencies = RankingDependencies(
        connect, db_change, acl_check, get_display_name, member_is_eligible, render_page, clock
    )
    if ranking_blueprint.name not in app.blueprints:
        app.register_blueprint(ranking_blueprint)
    try:
        with connect() as connection:
            ensure_schema(connection, db_change)
    except (sqlite3.DatabaseError, MySQLError):
        app.logger.exception("ranking schema initialization failed; rankings disabled")
        return
    service = RankingService(dependencies, contributor_refresh_seconds)
    app.extensions["rankings"] = service
    service.contributors.start()
