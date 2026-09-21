from __future__ import annotations

import re
from pathlib import Path

import pytest
from ranking_test_support import RankingTestApp, build_test_app


@pytest.fixture
def paged_app(tmp_path: Path) -> RankingTestApp:
    test_app = build_test_app(tmp_path)
    cache = test_app.app.extensions["rankings"].contributors
    with cache.lock:
        cache.items = tuple(
            {"name": f"편집자 {rank}", "url": "", "score": float(101 - rank)}
            for rank in range(1, 46)
        )
        cache.member_ranks = {"20261234": {"rank": 43, "score": 58.0}}
    return test_app


@pytest.mark.parametrize(
    ("query", "page", "first", "last"),
    [("", 1, 1, 20), ("2", 2, 21, 40), ("3", 3, 41, 45),
     ("0", 1, 1, 20), ("-2", 1, 1, 20), ("bad", 1, 1, 20),
     ("1.5", 1, 1, 20), ("999999999999999999999", 3, 41, 45)],
)
def test_contributor_api_pages_snapshot_without_changing_personal_rank(
    paged_app: RankingTestApp, query: str, page: int, first: int, last: int,
) -> None:
    # Given: 45 cached contributors and a current member ranked outside the first two pages.
    client = paged_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests a page, including malformed and out-of-range inputs.
    response = client.get(f"/api/rankings/contributors?page={query}")

    # Then: the slice and metadata agree while the member retains their global rank.
    payload = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert {key: payload[key] for key in ("page", "page_size", "total", "total_pages")} == {
        "page": page, "page_size": 20, "total": 45, "total_pages": 3,
    }
    assert [item["name"] for item in payload["items"]] == [f"편집자 {rank}" for rank in range(first, last + 1)]
    assert payload["me"] == {"rank": 43, "score": 58.0}
    assert payload["generated_at"] == paged_app.clock.value
    assert payload["stale"] is False
    assert "20261234" not in response.get_data(as_text=True)


@pytest.mark.parametrize(("query", "page", "first", "last"), [
    ("1", 1, 1, 20), ("2", 2, 21, 40), ("3", 3, 41, 45),
    ("bad", 1, 1, 20), ("0", 1, 1, 20), ("999", 3, 41, 45),
])
def test_rankings_page_keeps_global_row_numbers_and_native_navigation(
    paged_app: RankingTestApp, query: str, page: int, first: int, last: int,
) -> None:
    # Given: an authenticated member whose cached global rank is 43.
    client = paged_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens the server-rendered contributor page.
    response = client.get(f"/rankings?page={query}")

    # Then: row ranks remain global and pagination follows the unchanged personal summary.
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert re.findall(r'<tr class="ringo_ranked" data-rank="(\d+)"', body) == [
        str(rank) for rank in range(first, last + 1)
    ]
    assert re.findall(r'<span class="ringo_rank_badge">(\d+)</span>', body) == [
        str(rank) for rank in range(first, last + 1)
    ]
    assert '<strong>43위</strong>' in body
    assert body.index('aria-label="내 순위"') < body.index('<nav class="ringo_rank_pagination"')
    navigation = body.split('<nav class="ringo_rank_pagination"', 1)[1].split('</nav>', 1)[0]
    assert 'aria-label="기여자 순위 페이지"' in navigation
    assert f'aria-current="page">{page}</' in navigation
    assert (f'href="/rankings?page={page - 1}"' in navigation) == (page > 1)
    assert (f'href="/rankings?page={page + 1}"' in navigation) == (page < 3)


@pytest.mark.parametrize("endpoint", ["/rankings", "/api/rankings/contributors"])
def test_empty_contributor_snapshot_has_one_page_without_controls(
    paged_app: RankingTestApp, endpoint: str,
) -> None:
    # Given: a ready empty snapshot and a logged-in unranked member.
    cache = paged_app.app.extensions["rankings"].contributors
    with cache.lock:
        cache.items = ()
        cache.member_ranks = {}
    client = paged_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests a page beyond the empty result.
    response = client.get(endpoint + "?page=100")

    # Then: the API normalizes to one empty page and HTML has no pagination controls.
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    if response.is_json:
        payload = response.get_json()
        assert (payload["page"], payload["total_pages"], payload["total"], payload["page_size"]) == (1, 1, 0, 20)
        assert payload["items"] == []
        assert payload["me"] is None
    else:
        assert '<nav class="ringo_rank_pagination"' not in response.get_data(as_text=True)


def test_paginated_names_remain_escaped(paged_app: RankingTestApp) -> None:
    # Given: an HTML-sensitive nickname and user URL in the last cached row.
    cache = paged_app.app.extensions["rankings"].contributors
    with cache.lock:
        cache.items = (*cache.items[:-1], {"name": '<b>"별&빛"</b>', "url": '/w/user:one?x="&y=2', "score": 1.0})
    client = paged_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens the page containing that row.
    body = client.get("/rankings?page=3").get_data(as_text=True)

    # Then: name and URL text remain escaped in the generated table.
    assert '&lt;b&gt;&quot;별&amp;빛&quot;&lt;/b&gt;' in body
    assert 'href="/w/user:one?x=&quot;&amp;y=2"' in body
    assert '<b>"별&빛"</b>' not in body


@pytest.mark.parametrize(("page", "numbers"), [(1, [1, 2, 3, 4, 5]), (4, [2, 3, 4, 5, 6]), (8, [4, 5, 6, 7, 8])])
def test_many_pages_show_at_most_five_nearby_numbers(
    paged_app: RankingTestApp, page: int, numbers: list[int],
) -> None:
    # Given: eight pages of cached contributors.
    cache = paged_app.app.extensions["rankings"].contributors
    with cache.lock:
        cache.items = cache.items * 3 + cache.items[:10]
    client = paged_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens a beginning, middle, or final page.
    body = client.get(f"/rankings?page={page}").get_data(as_text=True)

    # Then: the navigation window contains exactly five nearby numeric choices.
    navigation = body.split('<nav class="ringo_rank_pagination"', 1)[1].split('</nav>', 1)[0]
    assert [int(number) for number in re.findall(r'>(\d+)</(?:a|span)>', navigation)] == numbers
