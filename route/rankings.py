from __future__ import annotations

import html
import hmac
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Awaitable, Callable, Final
from urllib.parse import quote, urlsplit

from flask import Blueprint, Flask, current_app, jsonify, make_response, redirect, request, session
from itsdangerous import BadSignature, URLSafeSerializer

from .tool.ranking_contributor_cache import ContributorCache
from .tool.ranking_views import ensure_schema, get_popular, record_view


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


def _service() -> RankingService:
    return current_app.extensions["rankings"]


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


def issue_ranking_ticket(title: str) -> str:
    if request.method != "GET":
        return ""
    service = _service()
    dependencies = service.dependencies
    with dependencies.connect() as connection:
        member_id = _member_id(connection, dependencies)
        if not member_id or not _document_is_canonical(connection, title, dependencies):
            return ""
    nonce = session.get("_ranking_nonce")
    if not isinstance(nonce, str) or not nonce:
        nonce = secrets.token_urlsafe(24)
        session["_ranking_nonce"] = nonce
    return _serializer().dumps(
        {"member": member_id, "nonce": nonce, "title": title, "issued_at": int(dependencies.clock())}
    )


def wait_for_contributor_refresh(app: Flask, timeout: float = 5) -> bool:
    return app.extensions["rankings"].contributors.ready.wait(timeout)


def _member_token(member_id: str) -> str:
    secret = str(current_app.secret_key).encode()
    return hmac.new(secret, member_id.encode(), sha256).hexdigest()


def _contributor_name_html(item: dict[str, str | float]) -> str:
    name = html.escape(str(item["name"]))
    url = str(item["url"])
    return f'<a href="{html.escape(url, quote=True)}">{name}</a>' if url else name


@ranking_blueprint.get("/api/trending")
async def trending():
    service = _service()
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
    with service.dependencies.connect() as connection:
        member_id = _member_id(connection, service.dependencies)
        if not member_id:
            return _error(401)
    if await service.dependencies.acl_check("", "render") != 0:
        return _error(403)
    items, generated_at, state, my_rank = service.contributors.snapshot(member_id)
    response = jsonify(
        {"response": "ok", "items": items, "me": my_rank, "generated_at": generated_at, "stale": state != "ready"}
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ranking_blueprint.get("/rankings")
async def rankings_page():
    service = _service()
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
    rows = "".join(
        f'<tr class="ringo_ranked"><td><span class="ringo_rank_badge">{rank}</span></td><td class="ringo_contributor_name">{_contributor_name_html(item)}</td><td class="ringo_contributor_score">{item["score"]:.2f}</td></tr>'
        for rank, item in enumerate(items, 1)
    )
    personal = (
        f'<span class="ringo_my_rank_values"><strong>{my_rank["rank"]}위</strong><span>{my_rank["score"]:.2f}점</span></span>'
        if my_rank is not None else '<span>아직 순위가 없습니다.</span>'
    )
    body = (
        '<div class="opennamu_main"><table id="main_table_set" class="ringo_contributor_table"><thead><tr><th scope="col">순위</th><th scope="col">이름</th><th scope="col">점수</th></tr></thead><tbody>'
        + rows + '</tbody></table><section class="ringo_my_rank" aria-label="내 순위"><strong>내 순위</strong>'
        + personal + '</section></div>'
    )
    response = make_response(await service.dependencies.render_page("기여자 순위", body))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@ranking_blueprint.post("/api/ranking/view")
async def qualify_view():
    if not _same_origin():
        return _error(403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("ticket"), str):
        return _error(400)
    try:
        ticket = _serializer().loads(payload["ticket"])
    except BadSignature:
        return _error(400)
    service = _service()
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
    with connect() as connection:
        ensure_schema(connection, db_change)
    service = RankingService(dependencies, contributor_refresh_seconds)
    app.extensions["rankings"] = service
    app.register_blueprint(ranking_blueprint)
    service.contributors.start()
