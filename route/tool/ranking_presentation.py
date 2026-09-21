from __future__ import annotations

import html
from collections.abc import Iterable, Mapping
from typing import Final


PAGE_SIZE: Final = 20


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


def pagination_html(page: int, total_pages: int) -> str:
    if total_pages == 1:
        return ""
    first = max(1, min(page - 2, total_pages - 4))
    links = [f'<a href="/rankings?page={page - 1}" rel="prev">이전</a>'] if page > 1 else []
    for number in range(first, min(total_pages, first + 4) + 1):
        current = ' aria-current="page"' if number == page else ""
        links.append(f'<a href="/rankings?page={number}"{current}>{number}</a>')
    if page < total_pages:
        links.append(f'<a href="/rankings?page={page + 1}" rel="next">다음</a>')
    return '<nav class="ringo_rank_pagination" aria-label="기여자 순위 페이지">' + "".join(links) + '</nav>'
