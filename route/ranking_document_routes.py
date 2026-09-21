from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import abort, jsonify, make_response, redirect, request

from .tool.ranking_presentation import (
    PAGE_SIZE,
    contributor_page,
    document_contributors_page_html,
    ranking_period,
)

KST = timezone(timedelta(hours=9))


def _current_month(dependencies) -> str:
    return datetime.fromtimestamp(dependencies.clock(), tz=KST).strftime("%Y-%m")


async def _document_is_public(connection, title: str, dependencies) -> bool:
    cursor = connection.cursor()
    cursor.execute(dependencies.db_change("select 1 from data where title = ? limit 1"), [title])
    if cursor.fetchone() is None:
        return False
    cursor.execute(
        dependencies.db_change("select data from acl where title = ? and type = 'view'"),
        [title],
    )
    policies = [row[0] for row in cursor.fetchall()]
    if policies and policies[-1] not in {"", "all", "user"}:
        return False
    cursor.execute(
        dependencies.db_change("select 1 from back where link = ? and type = 'redirect' limit 1"),
        [title],
    )
    return cursor.fetchone() is None and await dependencies.acl_check(title, "render") == 0


def register_document_ranking_routes(
    blueprint, service_getter, member_id_getter, error, private_response
) -> None:
    @blueprint.get("/api/rankings/document/<path:title>")
    async def document_contributors(title: str):
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
            if not await _document_is_public(connection, title, dependencies):
                return error(404)
            period = ranking_period(request.args.get("period", "all"))
            items, generated_at, state, my_rank = service.contributors.document_contributors_snapshot(
                title, member_id, period
            )
        page, total_pages, start = contributor_page(request.args.get("page", "1"), len(items))
        return private_response(
            jsonify(
                {
                    "response": "ok",
                    "title": title,
                    "items": items[start : start + PAGE_SIZE],
                    "me": my_rank,
                    "period": period,
                    "generated_at": generated_at,
                    "stale": state != "ready",
                    "page": page,
                    "page_size": PAGE_SIZE,
                    "total": len(items),
                    "total_pages": total_pages,
                }
            )
        )

    @blueprint.get("/rankings/document/<path:title>")
    async def document_contributors_page(title: str):
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
            if not await _document_is_public(connection, title, dependencies):
                abort(404)
            period = ranking_period(request.args.get("period", "all"))
            current_month = _current_month(dependencies)
            items, _, state, my_rank = service.contributors.document_contributors_snapshot(
                title, member_id, period
            )
        page, total_pages, start = contributor_page(request.args.get("page", "1"), len(items))
        message = ""
        if state == "loading":
            message = "불러오는 중입니다."
        elif state == "error":
            message = "불러오지 못했습니다."
        body = document_contributors_page_html(
            title,
            items[start : start + PAGE_SIZE],
            start,
            my_rank,
            page,
            total_pages,
            period,
            current_month,
            message,
        )
        response = make_response(await dependencies.render_page("문서 기여자", body))
        if state == "loading":
            response.headers["Refresh"] = "5"
        return private_response(response)
