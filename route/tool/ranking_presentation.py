from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from typing import Final
from urllib.parse import quote

from .ranking_contribution_scores import Period

PAGE_SIZE: Final = 20


def ranking_period(raw_period: str) -> Period:
    return raw_period if re.fullmatch(r"(?!0000)[0-9]{4}-(?:0[1-9]|1[0-2])", raw_period) else "all"


def period_navigation_html(path: str, period: Period, current_month: str) -> str:
    all_current = ' aria-current="page"' if period == "all" else ""
    month_current = ' aria-current="page"' if period != "all" else ""
    navigation = (
        '<nav class="ringo_rank_period" aria-label="집계 기간">'
        f'<a href="{path}?period=all&amp;page=1"{all_current}>전체</a>'
        f'<a href="{path}?period={current_month}&amp;page=1"{month_current}>월별</a></nav>'
    )
    if period == "all":
        return navigation
    return (
        navigation
        + f'<form class="ringo_rank_month" method="get" action="{path}">'
        '<label for="ringo_rank_month_input">조회 월</label>'
        f'<input id="ringo_rank_month_input" type="month" name="period" value="{period}" '
        f'max="{current_month}" required aria-label="조회 월"><button type="submit">보기</button></form>'
    )


def contributor_rows_html(items: Iterable[Mapping[str, str | float]], start: int) -> str:
    rows: list[str] = []
    for rank, item in enumerate(items, start + 1):
        name = html.escape(str(item["name"]))
        url = html.escape(str(item["url"]), quote=True)
        label = f'<a href="{url}">{name}</a>' if url else name
        rows.append(
            f'<tr class="ringo_ranked" data-rank="{rank}"><td><span class="ringo_rank_badge">{rank}</span></td><td class="ringo_contributor_name">{label}</td><td class="ringo_contributor_score">{item["score"]:.2f}</td></tr>'
        )
    return "".join(rows)


def contributor_page(raw_page: str, total: int) -> tuple[int, int, int]:
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        requested_page = int(raw_page)
    except ValueError:
        requested_page = 1
    page = min(max(1, requested_page), total_pages)
    return page, total_pages, (page - 1) * PAGE_SIZE


def pagination_html(
    page: int,
    total_pages: int,
    *,
    path: str = "/rankings",
    period: Period = "all",
    aria_label: str | None = None,
) -> str:
    if total_pages == 1:
        return ""
    first = max(1, min(page - 2, total_pages - 4))
    period_query = f"period={period}&amp;" if period != "all" else ""
    links = [f'<a href="{path}?{period_query}page={page - 1}" rel="prev">이전</a>'] if page > 1 else []
    for number in range(first, min(total_pages, first + 4) + 1):
        current = ' aria-current="page"' if number == page else ""
        links.append(f'<a href="{path}?{period_query}page={number}"{current}>{number}</a>')
    if page < total_pages:
        links.append(f'<a href="{path}?{period_query}page={page + 1}" rel="next">다음</a>')
    label = aria_label or ("내 기여 내역 페이지" if path == "/rankings/me" else "기여자 순위 페이지")
    return f'<nav class="ringo_rank_pagination" aria-label="{label}">' + "".join(links) + "</nav>"


def document_rows_html(items: Iterable[Mapping[str, str | float]]) -> str:
    return "".join(
        '<tr><td><a href="/w/'
        + quote(str(item["title"]), safe="")
        + '">'
        + html.escape(str(item["title"]))
        + '</a></td><td class="ringo_contributor_score">'
        + f"{float(item['score']):.4f}"
        + "</td></tr>"
        for item in items
    )


def contributor_page_html(
    items: Iterable[Mapping[str, str | float]],
    start: int,
    my_rank: Mapping[str, int | float] | None,
    page: int,
    total_pages: int,
    period: Period,
    current_month: str,
) -> str:
    page_items = tuple(items)
    rows = (
        contributor_rows_html(page_items, start)
        if page_items
        else '<tr><td colspan="3" class="ringo_ranking_empty">집계된 기여가 없습니다.</td></tr>'
    )
    personal = (
        f'<span class="ringo_my_rank_values"><strong>{my_rank["rank"]}위</strong><span>{float(my_rank["score"]):.2f}점</span></span>' if my_rank is not None else "<span>아직 순위가 없습니다.</span>"
    )
    return (
        '<div class="opennamu_main">' + period_navigation_html("/rankings", period, current_month) + '<table id="main_table_set" class="ringo_contributor_table"><thead><tr>'
        '<th scope="col">순위</th><th scope="col">이름</th><th scope="col">점수</th>'
        "</tr></thead><tbody>" + rows + '</tbody></table><section class="ringo_my_rank" aria-label="내 순위">'
        '<div class="ringo_my_rank_title"><strong>내 순위</strong>'
        f'<a class="ringo_my_contributions" href="/rankings/me?period={period}">내 기여 내역</a></div>' + personal + "</section>" + pagination_html(page, total_pages, period=period) + "</div>"
    )


def document_page_html(
    items: tuple[Mapping[str, str | float], ...],
    total_score: float,
    page: int,
    total_pages: int,
    period: Period,
    current_month: str,
) -> str:
    content = (
        '<p class="ringo_ranking_empty">기여한 공개 문서가 없습니다.</p>'
        if not items
        else (
            f'<p class="ringo_contribution_summary"><strong>합계</strong> {total_score:.2f}점</p>'
            '<table class="ringo_document_table"><thead><tr><th scope="col">문서</th>'
            '<th scope="col">기여 점수</th></tr></thead><tbody>' + document_rows_html(items) + "</tbody></table>"
        )
    )
    return (
        '<div class="opennamu_main"><a class="ringo_rank_back" '
        f'href="/rankings?period={period}">기여자 순위</a>'
        + period_navigation_html("/rankings/me", period, current_month)
        + content
        + pagination_html(page, total_pages, path="/rankings/me", period=period)
        + "</div>"
    )


def ranking_state_html(path: str, period: Period, current_month: str, message: str) -> str:
    back = f'<a class="ringo_rank_back" href="/rankings?period={period}">기여자 순위</a>' if path == "/rankings/me" else ""
    return '<div class="opennamu_main">' + back + period_navigation_html(path, period, current_month) + f'<p class="ringo_ranking_empty">{html.escape(message)}</p></div>'


def document_contributors_page_html(
    title: str,
    items: Iterable[Mapping[str, str | float]],
    start: int,
    my_rank: Mapping[str, int | float] | None,
    page: int,
    total_pages: int,
    period: Period,
    current_month: str,
    message: str = "",
) -> str:
    encoded_title = quote(title, safe="")
    path = "/rankings/document/" + encoded_title
    page_items = tuple(items)
    rows = (
        contributor_rows_html(page_items, start)
        if page_items
        else '<tr><td colspan="3" class="ringo_ranking_empty">집계된 기여가 없습니다.</td></tr>'
    )
    personal = (
        f'<span class="ringo_my_rank_values"><strong>{my_rank["rank"]}위</strong>'
        f'<span>{float(my_rank["score"]):.2f}점</span></span>'
        if my_rank is not None
        else "<span>아직 순위가 없습니다.</span>"
    )
    content = (
        f'<p class="ringo_ranking_empty">{html.escape(message)}</p>'
        if message
        else (
            '<table id="main_table_set" class="ringo_contributor_table"><thead><tr>'
            '<th scope="col">순위</th><th scope="col">이름</th><th scope="col">점수</th>'
            "</tr></thead><tbody>"
            + rows
            + '</tbody></table><section class="ringo_my_rank" aria-label="이 문서 내 순위">'
            '<div class="ringo_my_rank_title"><strong>이 문서 내 순위</strong></div>'
            + personal
            + "</section>"
            + pagination_html(
                page,
                total_pages,
                path=path,
                period=period,
                aria_label="문서 기여자 페이지",
            )
        )
    )
    return (
        '<div class="opennamu_main">'
        f'<a class="ringo_rank_back" href="/w/{encoded_title}">문서로 돌아가기</a>'
        f'<h2>문서 기여자: <a href="/w/{encoded_title}">{html.escape(title)}</a></h2>'
        + period_navigation_html(path, period, current_month)
        + content
        + "</div>"
    )
