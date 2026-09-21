from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ranking_test_support import RankingTestApp, build_test_app, encoded

KST = timezone(timedelta(hours=9))


@pytest.fixture
def document_rank_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[RankingTestApp, str]:
    title = '설계/A & <B> "인용"'

    def seed(db_path: Path) -> None:
        with sqlite3.connect(db_path) as connection:
            connection.execute("insert into data values (?, 'body', '')", (title,))

    test_app = build_test_app(tmp_path, seed_extra=seed)
    test_app.clock.value = int(datetime(2026, 9, 22, tzinfo=KST).timestamp())
    cache = test_app.app.extensions["rankings"].contributors
    items = tuple(
        {"name": f"기여자 {rank}", "url": "", "score": float(101 - rank)}
        for rank in range(1, 26)
    )

    def document_contributors_snapshot(document: str, member_id: str, period: str = "all"):
        assert document == title
        selected = items if period != "all" else items[:2]
        own = {"rank": 24, "score": 77.0} if member_id == "20261234" else None
        return selected, test_app.clock.value, "ready", own

    monkeypatch.setattr(
        cache,
        "document_contributors_snapshot",
        document_contributors_snapshot,
        raising=False,
    )
    return test_app, title


@pytest.mark.parametrize("api", [False, True])
def test_document_contributor_routes_require_current_member(
    document_rank_app: tuple[RankingTestApp, str], api: bool,
) -> None:
    # Given: a guest requesting a public document's contributor ranking.
    test_app, title = document_rank_app
    prefix = "/api" if api else ""

    # When: the private ranking surface is requested without a session.
    response = test_app.app.test_client().get(f"{prefix}/rankings/document/{encoded(title)}")

    # Then: HTML follows the login flow and API returns the existing JSON boundary.
    if api:
        assert response.status_code == 401
        assert response.get_json() == {"response": "error"}
    else:
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"


def test_document_contributor_api_keeps_month_page_and_private_own_rank(
    document_rank_app: tuple[RankingTestApp, str],
) -> None:
    # Given: 25 cached contributors and a current member ranked 24th on one document.
    test_app, title = document_rank_app
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests page two for a past month with a supplied foreign account ID.
    response = client.get(
        f"/api/rankings/document/{encoded(title)}?period=2026-07&page=2&user_id=20265678"
    )

    # Then: document-global ranks and current-account rank are returned without account identifiers.
    payload = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert payload["title"] == title
    assert payload["period"] == "2026-07"
    assert (payload["page"], payload["page_size"], payload["total"], payload["total_pages"]) == (2, 20, 25, 2)
    assert [item["name"] for item in payload["items"]] == [f"기여자 {rank}" for rank in range(21, 26)]
    assert payload["me"] == {"rank": 24, "score": 77.0}
    wire = response.get_data(as_text=True)
    assert "20261234" not in wire
    assert "20265678" not in wire
    invalid = client.get(f"/api/rankings/document/{encoded(title)}?period=30d").get_json()
    assert (invalid["period"], invalid["total"]) == ("all", 2)


def test_document_contributor_routes_fail_closed_on_global_acl(
    document_rank_app: tuple[RankingTestApp, str],
) -> None:
    # Given: an authenticated member while the global render ACL denies access.
    test_app, title = document_rank_app
    test_app.app.config["DENY_GLOBAL_RENDER"] = True
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the document contributor API is requested.
    response = client.get(f"/api/rankings/document/{encoded(title)}")

    # Then: the route fails closed before exposing title or cached ranking metadata.
    assert response.status_code == 403
    assert response.get_json() == {"response": "error"}
    assert title not in response.get_data(as_text=True)


def test_document_contributor_page_escapes_title_and_preserves_encoded_month_links(
    document_rank_app: tuple[RankingTestApp, str],
) -> None:
    # Given: an authenticated member and an HTML-sensitive document title containing a slash.
    test_app, title = document_rank_app
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens page two of the document's July ranking.
    response = client.get(f"/rankings/document/{encoded(title)}?period=2026-07&page=2")

    # Then: title text is escaped and every native navigation link retains the encoded title and month.
    body = response.get_data(as_text=True)
    path = f"/rankings/document/{encoded(title)}"
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "문서 기여자" in body
    assert '설계/A &amp; &lt;B&gt; &quot;인용&quot;' in body
    assert title not in body
    assert f'<a class="ringo_rank_back" href="/w/{encoded(title)}">문서로 돌아가기</a>' in body
    assert f'href="{path}?period=2026-09&amp;page=1" aria-current="page">월별</a>' in body
    assert f'action="{path}"' in body
    assert 'type="month" name="period" value="2026-07" max="2026-09"' in body
    assert f'href="{path}?period=2026-07&amp;page=1" rel="prev">이전</a>' in body
    assert 'aria-label="문서 기여자 페이지"' in body
    assert '<strong>24위</strong>' in body
    assert '77.00점' in body
    assert 'data-rank="21"' in body
    assert 'data-rank="25"' in body


@pytest.mark.parametrize("change", ["deleted", "restricted", "redirect", "runtime_acl"])
@pytest.mark.parametrize("api", [False, True])
def test_document_contributor_routes_recheck_current_document_visibility(
    document_rank_app: tuple[RankingTestApp, str], change: str, api: bool,
) -> None:
    # Given: a warm ranking whose document becomes unavailable after cache generation.
    test_app, title = document_rank_app
    with sqlite3.connect(test_app.db_path) as connection:
        if change == "deleted":
            connection.execute("delete from data where title = ?", (title,))
        elif change == "restricted":
            connection.execute("insert into acl values (?, 'admin', 'view')", (title,))
        elif change == "redirect":
            connection.execute("insert into back values ('target', ?, 'redirect', '')", (title,))
        else:
            test_app.app.config["DENY_DOCUMENT_TITLE"] = title
    if change == "runtime_acl":
        dependencies = test_app.app.extensions["rankings"].dependencies
        original_acl = dependencies.acl_check

        async def deny_document(document: str, tool: str) -> int:
            return 1 if document == title else await original_acl(document, tool)

        object.__setattr__(dependencies, "acl_check", deny_document)
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")
    prefix = "/api" if api else ""

    # When: the member requests the stale document ranking.
    response = client.get(f"{prefix}/rankings/document/{encoded(title)}")

    # Then: a generic 404 reveals no document title or cached score metadata.
    assert response.status_code == 404
    wire = response.get_data(as_text=True)
    assert title not in wire
    assert "기여자 1" not in wire
    assert "100.0" not in wire


@pytest.mark.parametrize(
    ("state", "message", "refresh"),
    [("loading", "불러오는 중입니다.", "5"), ("error", "불러오지 못했습니다.", None)],
)
def test_document_contributor_page_has_private_readable_cache_states(
    document_rank_app: tuple[RankingTestApp, str], monkeypatch: pytest.MonkeyPatch,
    state: str, message: str, refresh: str | None,
) -> None:
    # Given: a visible document whose contributor cache is not ready.
    test_app, title = document_rank_app
    cache = test_app.app.extensions["rankings"].contributors
    monkeypatch.setattr(
        cache,
        "document_contributors_snapshot",
        lambda document, member_id, period="all": ((), test_app.clock.value, state, None),
        raising=False,
    )
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens the document contributor page.
    response = client.get(f"/rankings/document/{encoded(title)}?period=2026-09")

    # Then: the page is private, readable, and only loading schedules a refresh.
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert message in response.get_data(as_text=True)
    assert response.headers.get("Refresh") == refresh
