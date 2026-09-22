from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import jsonify, make_response, redirect, request

from .tool.ranking_presentation import (
    PAGE_SIZE,
    contributor_page,
    contributor_page_html,
    document_page_html,
    ranking_period,
    ranking_state_html,
)

KST = timezone(timedelta(hours=9))


def _current_month(dependencies) -> str:
    return datetime.fromtimestamp(dependencies.clock(), tz=KST).strftime("%Y-%m")


async def _visible_documents(connection, items, dependencies):
    cursor = connection.cursor()
    cursor.execute(dependencies.db_change("select title from data"))
    existing = {row[0] for row in cursor.fetchall()}
    cursor.execute(dependencies.db_change("select title, data from acl where type = 'view'"))
    policies = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute(dependencies.db_change("select distinct link from back where type = 'redirect'"))
    redirects = {row[0] for row in cursor.fetchall()}
    visible = []
    for item in items:
        title = str(item["title"])
        if title not in existing or title in redirects or policies.get(title, "") not in {"", "all", "user"}:
            continue
        if await dependencies.acl_check(title, "render") != 0:
            continue
        visible.append({"title": title, "score": float(item["score"])})
    return tuple(visible)


def register_ranking_period_routes(blueprint, service_getter, member_id_getter, error, private_response) -> None:
    @blueprint.get("/api/rankings/contributors")
    async def contributors():
        service = service_getter()
        if service is None:
            return error(503)
        with service.dependencies.connect() as connection:
            member_id = member_id_getter(connection, service.dependencies)
            if not member_id:
                return error(401)
        if await service.dependencies.acl_check("", "render") != 0:
            return error(403)
        period = ranking_period(request.args.get("period", "all"))
        items, generated_at, state, my_rank = service.contributors.snapshot(member_id, period)
        page, total_pages, start = contributor_page(request.args.get("page", "1"), len(items))
        return private_response(
            jsonify(
                {
                    "response": "ok", "items": items[start : start + PAGE_SIZE], "me": my_rank,
                    "period": period, "generated_at": generated_at, "stale": state != "ready",
                    "page": page, "page_size": PAGE_SIZE, "total": len(items), "total_pages": total_pages,
                }
            )
        )

    @blueprint.get("/rankings")
    async def rankings_page():
        service = service_getter()
        if service is None:
            return error(503)
        with service.dependencies.connect() as connection:
            member_id = member_id_getter(connection, service.dependencies)
            if not member_id:
                return redirect("/login")
        if await service.dependencies.acl_check("", "render") != 0:
            return error(403)
        period = ranking_period(request.args.get("period", "all"))
        current_month = _current_month(service.dependencies)
        items, _, state, my_rank = service.contributors.snapshot(member_id, period)
        if state in {"loading", "error"}:
            message = "불러오는 중입니다." if state == "loading" else "불러오지 못했습니다."
            response = make_response(await service.dependencies.render_page("기여자 순위", ranking_state_html("/rankings", period, current_month, message)))
            if state == "loading":
                response.headers["Refresh"] = "5"
            return private_response(response)
        page, total_pages, start = contributor_page(request.args.get("page", "1"), len(items))
        body = contributor_page_html(items[start : start + PAGE_SIZE], start, my_rank, page, total_pages, period, current_month)
        return private_response(make_response(await service.dependencies.render_page("기여자 순위", body)))

    @blueprint.get("/api/rankings/me")
    async def my_contributions():
        service = service_getter()
        if service is None:
            return error(503)
        dependencies = service.dependencies
        with dependencies.connect() as connection:
            member_id = member_id_getter(connection, dependencies)
            if not member_id:
                return error(401)
            if await dependencies.acl_check("", "render") != 0:
                return error(403)
            period = ranking_period(request.args.get("period", "all"))
            items, generated_at, state = service.contributors.document_snapshot(member_id, period)
            visible = await _visible_documents(connection, items, dependencies)
        page, total_pages, start = contributor_page(request.args.get("page", "1"), len(visible))
        response_items = tuple(
            {
                "title": item["title"],
                "url": "/w/" + quote(str(item["title"]), safe=""),
                "score": round(float(item["score"]), 4),
            }
            for item in visible[start : start + PAGE_SIZE]
        )
        return private_response(
            jsonify(
                {
                    "response": "ok",
                    "items": response_items,
                    "period": period,
                    "generated_at": generated_at,
                    "stale": state != "ready",
                    "page": page,
                    "page_size": PAGE_SIZE,
                    "total": len(visible),
                    "total_pages": total_pages,
                    "total_score": round(sum(float(item["score"]) for item in visible), 4),
                }
            )
        )

    @blueprint.get("/rankings/me")
    async def my_contributions_page():
        service = service_getter()
        if service is None:
            return error(503)
        dependencies = service.dependencies
        with dependencies.connect() as connection:
            member_id = member_id_getter(connection, dependencies)
            if not member_id:
                return redirect("/login")
            if await dependencies.acl_check("", "render") != 0:
                return error(403)
            period = ranking_period(request.args.get("period", "all"))
            current_month = _current_month(dependencies)
            items, _, state = service.contributors.document_snapshot(member_id, period)
            visible = await _visible_documents(connection, items, dependencies)
        if state in {"loading", "error"}:
            message = "불러오는 중입니다." if state == "loading" else "불러오지 못했습니다."
            response = make_response(await dependencies.render_page("기여한 문서", ranking_state_html("/rankings/me", period, current_month, message)))
            if state == "loading":
                response.headers["Refresh"] = "5"
            return private_response(response)
        page, total_pages, start = contributor_page(request.args.get("page", "1"), len(visible))
        body = document_page_html(
            visible[start : start + PAGE_SIZE],
            sum(float(item["score"]) for item in visible),
            page,
            total_pages,
            period,
            current_month,
        )
        return private_response(make_response(await dependencies.render_page("기여한 문서", body)))
