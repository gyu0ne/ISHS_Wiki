from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from hashlib import sha256

from ranking_test_support import _load_rankings_module, build_test_app, encoded, origin_headers, seed_popular
from flask import Flask, session


def test_ranking_schema_failure_keeps_app_routes_live_and_apis_unavailable(caplog):
    # Given: a database that rejects the rankings schema DDL.
    rankings = _load_rankings_module()
    app = Flask(__name__)

    @contextmanager
    def broken_connect():
        raise sqlite3.OperationalError("forced rankings schema failure")
        yield

    async def acl_check(title: str, tool: str) -> int:
        return 0

    async def render_page(title: str, body: str) -> str:
        return body

    @app.get("/__test/healthy")
    def healthy():
        return "ok"

    # When: rankings initializes during application startup.
    with caplog.at_level(logging.ERROR):
        rankings.init_rankings(
            app,
            connect=broken_connect,
            db_change=lambda sql: sql,
            acl_check=acl_check,
            get_display_name=lambda connection, user_id: user_id,
            render_page=render_page,
            contributor_refresh_seconds=None,
        )
    client = app.test_client()

    # Then: the application stays live, rankings reports an outage, and the concrete failure is logged.
    assert client.get("/__test/healthy").get_data(as_text=True) == "ok"
    assert client.get("/api/trending").status_code == 503
    assert client.get("/api/rankings/contributors").status_code == 503
    assert client.post("/api/ranking/view").status_code == 503
    assert "forced rankings schema failure" in caplog.text


def test_issue_ranking_ticket_reuses_the_document_connection(tmp_path):
    # Given: a valid member and the already-open document-route connection.
    test_app = build_test_app(tmp_path)
    rankings = _load_rankings_module()
    before = test_app.app.config["RANKING_CONNECT_CALLS"]

    # When: ticket issuance receives that connection.
    with test_app.connect() as connection, test_app.app.test_request_context("/w/Public%20Page"):
        session["id"] = "20261234"
        ticket = rankings.issue_ranking_ticket("Public Page", connection=connection)

    # Then: a usable ticket is issued without opening a nested rankings connection.
    assert ticket
    assert test_app.app.config["RANKING_CONNECT_CALLS"] == before


def test_trending_requires_a_registered_member(tmp_path):
    # Given: a guest browser.
    test_app = build_test_app(tmp_path)

    # When: the guest requests trending data.
    response = test_app.app.test_client().get("/api/trending")

    # Then: no ranking data is disclosed.
    assert response.status_code == 401
    assert response.get_json()["response"] == "error"


def test_trending_rechecks_current_acl_and_document_existence(tmp_path):
    # Given: cached candidates that became restricted or were deleted.
    test_app = build_test_app(tmp_path)
    seed_popular(test_app, "Public Page", ("a", "b", "c"))
    seed_popular(test_app, "Second Page", ("a", "b", "c"))
    seed_popular(test_app, "Private Page", ("a", "b", "c", "d"))
    seed_popular(test_app, "Deleted Later", ("a", "b", "c", "d", "e"))
    with sqlite3.connect(test_app.db_path) as connection:
        connection.execute("delete from data where title = 'Deleted Later'")
        connection.execute("insert into back values ('Second Page', 'Public Page', 'redirect', '')")
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests the current ranking.
    response = client.get("/api/trending")

    # Then: JSON and legacy HTML expose only the live, authorized document.
    payload = response.get_json()
    assert response.headers["Cache-Control"] == "private, no-store"
    assert [item["title"] for item in payload["items"]] == ["Second Page"]
    assert "Private Page" not in payload["data"]
    assert "Deleted Later" not in payload["data"]
    assert "Public Page" not in payload["data"]
    assert "Second Page" in payload["data"]
    assert isinstance(payload["generated_at"], int)
    assert payload["stale"] is False


def test_trending_limits_after_acl_filtering(tmp_path):
    # Given: one higher-scoring denied candidate and eleven eligible documents.
    test_app = build_test_app(tmp_path)
    seed_popular(test_app, "Private Page", tuple(f"private-{index}" for index in range(20)))
    with sqlite3.connect(test_app.db_path) as connection:
        connection.executemany(
            "insert into data values (?, 'body', '')",
            ((f"Article {index}",) for index in range(11)),
        )
    for index in range(11):
        seed_popular(test_app, f"Article {index}", (f"a-{index}", f"b-{index}", f"c-{index}"))
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests trending data.
    payload = client.get("/api/trending").get_json()

    # Then: ten eligible results remain after the denied candidate is removed.
    assert len(payload["items"]) == 10
    assert all(item["title"] != "Private Page" for item in payload["items"])


def test_view_ticket_accepts_once_after_five_seconds_and_store_deduplicates_devices(tmp_path):
    # Given: two sessions for the same member viewing a public canonical document.
    test_app = build_test_app(tmp_path)
    first = test_app.app.test_client()
    second = test_app.app.test_client()
    first.get("/__test/login/20261234")
    second.get("/__test/login/20261234")
    first_ticket = first.get("/__test/ticket/Public%20Page").get_json()["ticket"]
    second_ticket = second.get("/__test/ticket/Public%20Page").get_json()["ticket"]

    # When: five seconds elapse and both browser sessions qualify the view.
    test_app.clock.value += 5
    first_response = first.post("/api/ranking/view", json={"ticket": first_ticket}, headers=origin_headers())
    second_response = second.post("/api/ranking/view", json={"ticket": second_ticket}, headers=origin_headers())

    # Then: both requests are valid but the account/document store has one first anchor.
    assert first_response.get_json() == {"response": "ok", "counted": True}
    assert second_response.get_json() == {"response": "ok", "counted": False}
    with sqlite3.connect(test_app.db_path) as connection:
        stored_hash = connection.execute("select member_token_hash from realtime_popularity_views").fetchone()[0]
    assert stored_hash != sha256(b"20261234").hexdigest()


def test_view_ticket_rejects_too_early_tampered_expired_cross_session_and_cross_origin(tmp_path):
    # Given: a signed ticket for one member session.
    test_app = build_test_app(tmp_path)
    owner = test_app.app.test_client()
    other_session = test_app.app.test_client()
    owner.get("/__test/login/20261234")
    other_session.get("/__test/login/20261234")
    ticket = owner.get("/__test/ticket/Public%20Page").get_json()["ticket"]

    # When/Then: each boundary rejects the ticket without recording a view.
    assert owner.post("/api/ranking/view", json={"ticket": ticket}, headers=origin_headers()).status_code == 400
    test_app.clock.value += 5
    assert owner.post("/api/ranking/view", json={"ticket": ticket + "x"}, headers=origin_headers()).status_code == 400
    assert other_session.post("/api/ranking/view", json={"ticket": ticket}, headers=origin_headers()).status_code == 400
    assert owner.post(
        "/api/ranking/view", json={"ticket": ticket}, headers={"Origin": "https://evil.example"}
    ).status_code == 403
    assert owner.post(
        "/api/ranking/view", json={"ticket": ticket}, headers={"Origin": "http://["}
    ).status_code == 403
    test_app.clock.value += 1801
    assert owner.post("/api/ranking/view", json={"ticket": ticket}, headers=origin_headers()).status_code == 400


def test_view_ticket_rechecks_acl_deleted_document_and_requires_get_issuance(tmp_path):
    # Given: tickets issued before policy/data changes.
    test_app = build_test_app(tmp_path)
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")
    public_ticket = client.get("/__test/ticket/Public%20Page").get_json()["ticket"]
    private_ticket = client.get("/__test/ticket/Private%20Page").get_json()["ticket"]
    head_response = client.head("/__test/ticket/Public%20Page")
    test_app.clock.value += 5
    with sqlite3.connect(test_app.db_path) as connection:
        connection.execute("delete from data where title = 'Public Page'")

    # When/Then: deleted and denied pages never enter the store, and HEAD has no usable body ticket.
    assert client.post("/api/ranking/view", json={"ticket": public_ticket}, headers=origin_headers()).status_code == 404
    assert client.post("/api/ranking/view", json={"ticket": private_ticket}, headers=origin_headers()).status_code == 403
    assert head_response.data == b""


def test_view_ticket_rejects_after_session_cookie_state_is_removed(tmp_path):
    # Given: a ticket bound to an authenticated browser session.
    test_app = build_test_app(tmp_path)
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")
    ticket = client.get("/__test/ticket/Public%20Page").get_json()["ticket"]
    test_app.clock.value += 5
    with client.session_transaction() as browser_session:
        browser_session.clear()

    # When: the browser posts the old ticket without its original session state.
    response = client.post("/api/ranking/view", json={"ticket": ticket}, headers=origin_headers())

    # Then: the signed value alone cannot qualify the view.
    assert response.status_code == 400


def test_contributors_replays_mature_history_and_links_nicknames_to_accounts(tmp_path):
    # Given: mature public and restricted history with student-number member IDs.
    test_app = build_test_app(tmp_path)
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests contributor rankings.
    response = client.get("/api/rankings/contributors")

    # Then: nicknames remain labels and links use the canonical account document.
    payload = response.get_json()
    assert [item["name"] for item in payload["items"]] == ["별빛", "달빛"]
    assert [item["url"] for item in payload["items"]] == [
        "/w/user:20261234", "/w/user:20265678"
    ]
    assert all(set(item) == {"name", "url", "score"} for item in payload["items"])


def test_contributor_cache_keeps_default_all_and_user_view_policies(tmp_path):
    # Given: mature contributions on member-wide policies and one narrower policy.
    def seed_policies(db_path):
        with sqlite3.connect(db_path) as connection:
            for index, policy in enumerate(("", "all", "user", "admin"), 1):
                user_id = f"policy-member-{index}"
                title = f"Policy Page {index}"
                connection.executemany(
                    "insert into user_set values (?, ?, ?)",
                    (("pw", user_id, "hash"), ("user_name", user_id, f"공개{index}")),
                )
                body = chr(64 + index) * 1000
                connection.execute("insert into data values (?, ?, '')", (title, body))
                connection.execute("insert into acl values (?, ?, 'view')", (title, policy))
                connection.execute(
                    "insert into history values ('1', ?, ?, '2026-01-01 00:00:00', ?, '', '+1000', '', '')",
                    (title, body, user_id),
                )

    test_app = build_test_app(tmp_path, seed_extra=seed_policies)
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the background snapshot is read through the contributor API.
    payload = client.get("/api/rankings/contributors").get_json()

    # Then: normal/all/user remain and the narrower admin policy is absent.
    names = {item["name"] for item in payload["items"]}
    assert {"공개1", "공개2", "공개3"} <= names
    assert "공개4" not in names


def test_contributor_warm_cache_fails_closed_when_global_render_default_denies(tmp_path):
    # Given: a completed contributor snapshot whose global render policy changes to deny.
    test_app = build_test_app(tmp_path)
    test_app.app.config["DENY_GLOBAL_RENDER"] = True
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests the already-warm contributor cache.
    response = client.get("/api/rankings/contributors")

    # Then: one live default-policy check fails closed before cached items are exposed.
    assert response.status_code == 403
    assert "items" not in response.get_json()


def test_rankings_require_riro_reauthentication_for_target_generations(tmp_path):
    # Given: a registered current-generation member whose Riro verification was reset.
    test_app = build_test_app(tmp_path)
    with sqlite3.connect(test_app.db_path) as connection:
        connection.execute(
            "delete from user_set where id = '20261234' and name = 'riro_reauthed'"
        )
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member requests ranking data.
    response = client.get("/api/rankings/contributors")

    # Then: the existing generation-scoped verification policy denies the request.
    assert response.status_code == 401


def test_rankings_page_uses_real_ringo_template_and_accessible_table(tmp_path):
    # Given: an authenticated registered member.
    test_app = build_test_app(tmp_path)
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens the contributor ranking page.
    response = client.get("/rankings")

    # Then: the real skin renders the requested title and a simple table.
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "기여자 순위" in html
    assert "<table" in html
    assert "별빛" in html
    assert f'/w/{encoded("별빛")}' not in html


def test_rankings_page_redirects_guests_to_existing_login_flow(tmp_path):
    # Given: a guest browser.
    test_app = build_test_app(tmp_path)

    # When: the guest opens the human-facing rankings page.
    response = test_app.app.test_client().get("/rankings")

    # Then: the page follows the existing login flow while APIs retain JSON errors.
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_personal_rank_uses_account_identity_and_handles_unranked_members(tmp_path):
    def seed_members(db_path):
        with sqlite3.connect(db_path) as connection:
            connection.execute("update user_set set data = '같은 이름' where name = 'user_name'")
            connection.executemany(
                "insert into user_set values (?, 'new-member', ?)",
                (("pw", "hash"), ("user_name", "새 편집자")),
            )

    test_app = build_test_app(tmp_path, seed_extra=seed_members)
    client = test_app.app.test_client()
    for user_id, rank, score in (("20261234", 1, 11.56), ("20265678", 2, 9.63), ("new-member", None, None)):
        client.get(f"/__test/login/{user_id}")
        api_response = client.get("/api/rankings/contributors")
        page_response = client.get("/rankings")
        page = page_response.get_data(as_text=True)
        personal = page.split('aria-label="내 순위">', 1)[1].split("</section>", 1)[0]
        assert page.index('aria-label="내 순위"') > page.index("</table>")
        assert api_response.headers["Cache-Control"] == "private, no-store"
        assert page_response.headers["Cache-Control"] == "private, no-store"
        assert [item["url"] for item in api_response.get_json()["items"]] == [
            "/w/user:20261234", "/w/user:20265678"
        ]
        assert all(item["name"] == "같은 이름" for item in api_response.get_json()["items"])
        if rank is None:
            assert api_response.get_json()["me"] is None
            assert "아직 순위가 없습니다." in personal
        else:
            assert api_response.get_json()["me"] == {"rank": rank, "score": score}
            assert f"<strong>{rank}위</strong>" in personal
            assert f"{score:.2f}점" in personal


def test_rankings_page_refreshes_while_background_snapshot_is_loading(tmp_path):
    # Given: a ranking cache whose initial background replay has not completed.
    test_app = build_test_app(tmp_path)
    service = test_app.app.extensions["rankings"]
    with service.contributors.lock:
        service.contributors.state = "loading"
        service.contributors.items = ()
    client = test_app.app.test_client()
    client.get("/__test/login/20261234")

    # When: the member opens the page during the cold-cache window.
    response = client.get("/rankings")

    # Then: the real page schedules a retry and distinguishes loading from an empty ranking.
    assert response.headers["Refresh"] == "5"
    assert "불러오는 중입니다." in response.get_data(as_text=True)
