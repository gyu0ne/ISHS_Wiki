from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ranking_test_support import RankingTestApp, build_test_app, encoded


@pytest.fixture
def period_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RankingTestApp:
    test_app = build_test_app(tmp_path)
    test_app.clock.value = int(datetime(2026, 9, 22, tzinfo=timezone(timedelta(hours=9))).timestamp())
    cache = test_app.app.extensions["rankings"].contributors
    contributor_items = tuple({"name": f"편집자 {rank}", "url": "", "score": float(101 - rank)} for rank in range(1, 26))

    def snapshot(member_id: str, period: str = "all"):
        items = contributor_items if period != "all" else contributor_items[:2]
        return items, test_app.clock.value, "ready", {"rank": 25, "score": 76.0}

    monkeypatch.setattr(cache, "snapshot", snapshot)
    return test_app


def test_contributor_routes_normalize_period_and_preserve_it_in_native_links(
    period_app: RankingTestApp,
) -> None:
    # Given: distinct all-time and September contributor snapshots.
    client = period_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests page two of September.
    api_response = client.get("/api/rankings/contributors?period=2026-09&page=2")
    page_response = client.get("/rankings?period=2026-09&page=2")

    # Then: both surfaces keep the period, reset period switches to page one, and expose self detail.
    payload = api_response.get_json()
    body = page_response.get_data(as_text=True)
    assert (payload["period"], payload["page"], payload["total"]) == ("2026-09", 2, 25)
    assert [item["name"] for item in payload["items"]] == [f"편집자 {rank}" for rank in range(21, 26)]
    assert '<nav class="ringo_rank_period" aria-label="집계 기간">' in body
    assert 'href="/rankings?period=all&amp;page=1">전체</a>' in body
    assert 'href="/rankings?period=2026-09&amp;page=1" aria-current="page">월별</a>' in body
    assert 'href="/rankings?period=2026-09&amp;page=1" rel="prev">이전</a>' in body
    assert 'class="ringo_my_contributions" href="/rankings/me?period=2026-09"' in body
    assert '<form class="ringo_rank_month" method="get" action="/rankings">' in body
    assert 'type="month" name="period" value="2026-09" max="2026-09" required aria-label="조회 월"' in body
    for value in ("30d", "0000-01", "٢٠٢٦-09", "2026-13"):
        invalid = client.get("/api/rankings/contributors", query_string={"period": value}).get_json()
        assert (invalid["period"], invalid["total"]) == ("all", 2)
    all_time = client.get("/rankings?period=30d").get_data(as_text=True)
    assert 'aria-current="page">전체</a>' in all_time
    assert '<form class="ringo_rank_month"' not in all_time


def test_past_month_keeps_selected_month_while_month_tab_targets_current_month(
    period_app: RankingTestApp,
) -> None:
    # Given: the current KST month is September 2026 and an older monthly snapshot exists.
    client = period_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens page two for July 2026.
    response = client.get("/rankings?period=2026-07&page=2")

    # Then: the form and pager preserve July while the month tab remains a current-month shortcut.
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'href="/rankings?period=2026-09&amp;page=1" aria-current="page">월별</a>' in body
    assert 'type="month" name="period" value="2026-07" max="2026-09" required aria-label="조회 월"' in body
    assert 'href="/rankings?period=2026-07&amp;page=1" rel="prev">이전</a>' in body


def test_self_document_api_filters_live_visibility_before_pagination_and_keeps_raw_total(
    period_app: RankingTestApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a warm self snapshot containing a restricted page, a deleted page, and a redirect alias.
    cache = period_app.app.extensions["rankings"].contributors
    special_title = '공개 <문서> & "인용"'
    with sqlite3.connect(period_app.db_path) as connection:
        connection.execute("insert into data values (?, 'body', '')", (special_title,))
        connection.execute("delete from data where title = 'Deleted Later'")
        connection.execute("insert into back values ('target', 'Second Page', 'redirect', '')")

    def document_snapshot(member_id: str, period: str = "all"):
        assert member_id == "20261234"
        assert period == "2026-09"
        return (
            (
                {"title": "Private Page", "score": 99.0},
                {"title": "Deleted Later", "score": 88.0},
                {"title": "Second Page", "score": 77.0},
                {"title": special_title, "score": 2.005},
                {"title": "Public Page", "score": 1.005},
            ),
            period_app.clock.value,
            "ready",
        )

    monkeypatch.setattr(cache, "document_snapshot", document_snapshot, raising=False)
    client = period_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the current member requests only their recent document contributions.
    response = client.get("/api/rankings/me?period=2026-09&page=1&user_id=20265678")

    # Then: filtering precedes totals/pagination and private account identifiers never leave the server.
    payload = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert payload["period"] == "2026-09"
    assert payload["total"] == 2
    assert payload["total_pages"] == 1
    assert payload["total_score"] == pytest.approx(3.01)
    assert payload["items"] == [
        {"title": special_title, "url": f"/w/{encoded(special_title)}", "score": 2.005},
        {"title": "Public Page", "url": "/w/Public%20Page", "score": 1.005},
    ]
    wire = response.get_data(as_text=True)
    assert "Private Page" not in wire
    assert "Deleted Later" not in wire
    assert "Second Page" not in wire
    assert "20261234" not in wire
    assert "20265678" not in wire


def test_self_document_page_escapes_titles_and_has_period_scoped_navigation(
    period_app: RankingTestApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one visible contribution whose title contains HTML-sensitive characters.
    cache = period_app.app.extensions["rankings"].contributors
    title = '공개 <문서> & "인용"'
    with sqlite3.connect(period_app.db_path) as connection:
        connection.execute("insert into data values (?, 'body', '')", (title,))
    monkeypatch.setattr(
        cache,
        "document_snapshot",
        lambda member_id, period="all": (
            ({"title": title, "score": 12.345},),
            period_app.clock.value,
            "ready",
        ),
        raising=False,
    )
    client = period_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens their September contribution page.
    response = client.get("/rankings/me?period=2026-09")

    # Then: semantic navigation and escaped document output retain the selected period.
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert '<a class="ringo_rank_back" href="/rankings?period=2026-09">기여자 순위</a>' in body
    assert '<table class="ringo_document_table">' in body
    assert f'href="/w/{encoded(title)}"' in body
    assert "공개 &lt;문서&gt; &amp; &quot;인용&quot;" in body
    assert title not in body
    assert '<nav class="ringo_rank_period" aria-label="집계 기간">' in body
    assert 'href="/rankings/me?period=2026-09&amp;page=1" aria-current="page">월별</a>' in body
    assert '<form class="ringo_rank_month" method="get" action="/rankings/me">' in body


@pytest.mark.parametrize("endpoint", ["/rankings/me", "/api/rankings/me"])
def test_self_document_routes_require_the_current_authenticated_member(
    period_app: RankingTestApp,
    endpoint: str,
) -> None:
    # Given: a guest with no eligible account session.
    client = period_app.app.test_client()

    # When: the guest requests the private self-only surface.
    response = client.get(endpoint)

    # Then: HTML follows login flow while the API returns its existing JSON boundary.
    if endpoint.startswith("/api/"):
        assert response.status_code == 401
        assert response.get_json() == {"response": "error"}
    else:
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"


@pytest.mark.parametrize(
    ("state", "message", "refresh"),
    [("loading", "불러오는 중입니다.", "5"), ("error", "불러오지 못했습니다.", None)],
)
def test_self_document_page_has_readable_cache_states(
    period_app: RankingTestApp,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    message: str,
    refresh: str | None,
) -> None:
    # Given: the self contribution cache is not ready.
    cache = period_app.app.extensions["rankings"].contributors
    monkeypatch.setattr(
        cache,
        "document_snapshot",
        lambda member_id, period="all": ((), period_app.clock.value, state),
        raising=False,
    )
    client = period_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens the self detail page.
    response = client.get("/rankings/me?period=2026-09")

    # Then: the private page renders a readable state with an optional bounded refresh.
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert message in response.get_data(as_text=True)
    assert response.headers.get("Refresh") == refresh


def test_self_document_empty_state_and_global_acl_are_private_and_readable(
    period_app: RankingTestApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an authenticated member with an empty ready snapshot.
    cache = period_app.app.extensions["rankings"].contributors
    monkeypatch.setattr(
        cache,
        "document_snapshot",
        lambda member_id, period="all": ((), period_app.clock.value, "ready"),
        raising=False,
    )
    monkeypatch.setattr(
        cache,
        "snapshot",
        lambda member_id, period="all": ((), period_app.clock.value, "ready", None),
    )
    client = period_app.app.test_client()
    client.get("/__test/login/20261234")

    # When/Then: empty HTML is readable and a later global ACL denial fails closed.
    empty = client.get("/rankings/me")
    assert empty.status_code == 200
    assert '<p class="ringo_ranking_empty">기여한 공개 문서가 없습니다.</p>' in empty.get_data(as_text=True)
    contributors = client.get("/rankings")
    assert '<td colspan="3" class="ringo_ranking_empty">집계된 기여가 없습니다.</td>' in contributors.get_data(as_text=True)
    period_app.app.config["DENY_GLOBAL_RENDER"] = True
    denied = client.get("/api/rankings/me")
    assert denied.status_code == 403
    assert "items" not in denied.get_json()
