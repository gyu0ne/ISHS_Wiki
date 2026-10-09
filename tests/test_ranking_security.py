"""Regression scenarios for persisted ownership, resource limits and local keys."""

from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import tracemalloc
from unittest.mock import patch
import zlib

import pytest
from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool import ranking_checkpoint_store as store, ranking_replay_checkpoint as codec
from route.tool.ranking_checkpoint_auth import sign_checkpoint, verify_checkpoint
from route.tool.ranking_contribution_engine import DocumentContributionEngine
from route.tool.ranking_resource_limits import RankingResourceLimit, WorkBudget, ranking_work_budget, refresh_budget
from route.tool.ranking_text_diff import ContributionDiffer
from route.tool.security_key import read_security_key, session_key
from test_document_contributor_cache import build_cache
from test_ranking_incremental import restarted


def test_local_key_is_complete_shared_persistent_and_not_database_derived(tmp_path):
    target = tmp_path / 'security.key'
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: read_security_key(target), range(16)))
    assert all(key == keys[0] and len(key) == 32 for key in keys)
    assert list(tmp_path.iterdir()) == [target]
    with patch('route.tool.security_key.security_key', return_value=keys[0]):
        first = session_key('public-database-key')
    with patch('route.tool.security_key.security_key', return_value=b'x' * 32):
        assert session_key('public-database-key') != first
    target.write_bytes(b'broken')
    with pytest.raises(RuntimeError):
        read_security_key(target)


@pytest.mark.parametrize('mutation', ['owner', 'range', 'score', 'title', 'payload'])
def test_signed_checkpoint_detects_ownership_scores_and_row_swapping(mutation):
    engine = DocumentContributionEngine('Page')
    payload = engine.dump_checkpoint()
    metadata = sign_checkpoint('Page', '{"version":2,"buckets":[]}', payload)
    title = 'Page'
    if mutation in ('owner', 'range'):
        # A structurally valid change cannot be hidden behind the same text hash.
        raw = [2, 'Page', None, None, None, False, False, '', [], [], [], []]
        if mutation == 'owner':
            raw[10] = [['attacker', None, '2026-10-09T00:00:00+00:00', 0, False, None, False, None, None, None, None]]
        else:
            raw[11] = [[1, 'a' * 64, 0, []]]
        payload = 'zlib:' + b64encode(zlib.compress(json.dumps(raw).encode())).decode()
    elif mutation == 'score':
        raw = json.loads(metadata); raw['buckets'] = [['attacker', 'Page', '2026-10-09', 999, 0]]
        metadata = json.dumps(raw)
    elif mutation == 'title':
        title = 'Other'
    else:
        payload += 'AAAA'
    with pytest.raises(codec.InvalidCheckpoint):
        verify_checkpoint(title, metadata, payload)


def test_duplicate_metadata_keys_and_unsigned_state_are_rejected():
    signed = sign_checkpoint('Page', '{}', 'payload')
    assert isinstance(json.loads(signed), dict)
    assert verify_checkpoint('Page', signed, 'payload') == '{}'
    for value in ('{}', signed[:-1] + ',"auth_version":1}'):
        with pytest.raises(codec.InvalidCheckpoint):
            verify_checkpoint('Page', value, 'payload')


@pytest.mark.parametrize('kind', ['bomb', 'truncated', 'trailing', 'joined'])
def test_bounded_decoder_rejects_expansion_and_extra_streams(kind):
    packed = zlib.compress(b'x' * (1024 * 1024))
    if kind == 'truncated': packed = packed[:-1]
    if kind == 'trailing': packed += b'trailing'
    if kind == 'joined': packed += zlib.compress(b'another')
    payload = 'zlib:' + b64encode(packed).decode()
    tracemalloc.start()
    try:
        with patch.object(codec, 'MAX_CHECKPOINT_BYTES', 4096):
            with pytest.raises(codec.InvalidCheckpoint):
                DocumentContributionEngine.load_checkpoint(payload)
        assert tracemalloc.get_traced_memory()[1] < 256 * 1024
    finally:
        tracemalloc.stop()


def test_decoder_exact_expanded_boundary_and_legacy_limit():
    payload = json.dumps([2, 'Page', None, None, None, False, False, '', [], [], [], []])
    encoded = 'zlib:' + b64encode(zlib.compress(payload.encode())).decode()
    with patch.object(codec, 'MAX_CHECKPOINT_BYTES', len(payload.encode())):
        assert DocumentContributionEngine.load_checkpoint(encoded).text == ''
    with patch.object(codec, 'MAX_CHECKPOINT_BYTES', len(payload.encode()) - 1):
        for value in (payload, encoded):
            with pytest.raises(codec.InvalidCheckpoint):
                DocumentContributionEngine.load_checkpoint(value)


def test_invalid_collection_and_encoded_size_are_rejected():
    payload = [2, 'Page', None, None, None, False, False, '', [], [], [], []]
    payload[9] = [['', []]] * 3
    with patch.object(codec, 'MAX_REVISIONS', 2):
        with pytest.raises(codec.InvalidCheckpoint):
            DocumentContributionEngine.load_checkpoint(json.dumps(payload))
    with patch.object(codec, 'MAX_ENCODED_CHARS', 8):
        with pytest.raises(codec.InvalidCheckpoint):
            DocumentContributionEngine.load_checkpoint('zlib:' + 'A' * 10)


def test_oversized_and_cumulative_diff_never_enter_native_code():
    differ = ContributionDiffer()
    with patch('route.tool.ranking_text_diff.Indel.opcodes') as native:
        with pytest.raises(RankingResourceLimit): differ.diff_main('x' * 100001, '')
        native.assert_not_called()
    differ.budget = WorkBudget(max_calls=2)
    differ.diff_main('a', 'b'); differ.diff_main('a', 'b')
    with pytest.raises(RankingResourceLimit): differ.diff_main('a', 'b')
    with ranking_work_budget():
        refresh_budget.get().max_calls = 1
        ContributionDiffer().diff_main('a', 'b')
        with pytest.raises(RankingResourceLimit): ContributionDiffer().diff_main('a', 'b')


def test_large_small_edit_preserves_native_result_and_has_small_work_weight():
    from rapidfuzz.distance import Indel
    body = '학교 내용 ' * 6000
    changed = body[:10000] + '!' + body[10000:]
    differ = ContributionDiffer()
    result = differ.diff_main(body, changed)
    assert ''.join(part for operation, part in result if operation != -1) == changed
    assert differ.budget.work == 1


def test_diff_budget_is_lazy_and_cannot_be_reset_by_score_overlay_copy():
    import copy
    differ = ContributionDiffer()
    assert differ._budget is None
    differ.budget = WorkBudget(max_calls=1)
    overlay = copy.deepcopy(differ)
    assert overlay is differ
    overlay.diff_main('a', 'b')
    with pytest.raises(RankingResourceLimit):
        differ.diff_main('b', 'c')


def test_unsigned_legacy_metadata_rebuilds_once_with_same_rankings(tmp_path):
    import sqlite3
    cache = build_cache(tmp_path)
    expected = cache.snapshot('member-a')
    database = tmp_path / 'document-contributors.sqlite3'
    with sqlite3.connect(database) as connection:
        for title, metadata in connection.execute('select title, metadata from contributor_checkpoints').fetchall():
            raw = json.loads(metadata)
            raw.pop('_security')
            connection.execute('update contributor_checkpoints set metadata=? where title=?', (json.dumps(raw), title))
    cache = restarted(cache); cache._refresh()
    assert cache.snapshot('member-a') == expected
    with sqlite3.connect(database) as connection:
        assert all('_security' in json.loads(row[0]) for row in connection.execute('select metadata from contributor_checkpoints'))


def test_member_views_are_document_scoped_without_duplicate_counts(tmp_path):
    from ranking_test_support import build_test_app, origin_headers
    import sqlite3
    app = build_test_app(tmp_path)
    client = app.app.test_client()
    with client.session_transaction() as session:
        session['id'] = '20261234'
    first = client.get('/__test/ticket/Public%20Page').json['ticket']
    second = client.get('/__test/ticket/Second%20Page').json['ticket']
    app.clock.value += 5
    for ticket in (first, second):
        response = client.post('/api/ranking/view', json={'ticket': ticket}, headers=origin_headers())
        assert response.status_code == 200 and response.json['counted']
        assert not client.post('/api/ranking/view', json={'ticket': ticket}, headers=origin_headers()).json['counted']
    with sqlite3.connect(app.db_path) as connection:
        rows = connection.execute('select member_token_hash from realtime_popularity_views').fetchall()
    assert len(rows) == 2 and rows[0][0] != rows[1][0]
    assert client.post('/api/ranking/view', json={'ticket': 'x' * 40000}, headers=origin_headers()).status_code == 413


def test_budget_failure_does_not_publish_partial_or_fabricated_scores(tmp_path):
    cache = build_cache(tmp_path)
    expected = cache.snapshot('member-a')
    with patch.object(cache, '_compute', side_effect=RankingResourceLimit('fixture limit')):
        with pytest.raises(RankingResourceLimit): cache._refresh()
    assert cache.snapshot('member-a') == expected


def test_whole_set_memo_revalidates_changed_bytes_and_is_not_shared(tmp_path):
    import sqlite3
    from route.tool.ranking_checkpoint_auth import CheckpointVerification
    database = tmp_path / 'memo.db'
    with sqlite3.connect(database) as connection:
        connection.execute('create table history (title text, id text, data text)')
        store.ensure_schema(connection, str)
        store.publish(connection, str, store.snapshot(connection, str),
                      (store.CheckpointWrite('Page', '{"version":2}', 'payload'),), (), 'members')
        verification = CheckpointVerification()
        with patch.object(store, 'verify_checkpoint', wraps=store.verify_checkpoint) as verify:
            first = store.snapshot(connection, str, verification)
            assert verify.call_count == 1
            assert store.snapshot(connection, str, verification).checkpoints == first.checkpoints
            assert verify.call_count == 1
            store.snapshot(connection, str, CheckpointVerification())
            assert verify.call_count == 2
            original = connection.execute('select metadata from contributor_checkpoints').fetchone()[0]
            changed = original.replace('"version":2', '"version":3')
            connection.execute('update contributor_checkpoints set metadata=?', (changed,))
            assert store.snapshot(connection, str, verification).checkpoints == {'Page': ''}
            assert verify.call_count == 3 and verification.digest is None
            # Invalid bytes never become trusted merely by repeating them.
            assert store.snapshot(connection, str, verification).checkpoints == {'Page': ''}
            assert verify.call_count == 4 and verification.digest is None


def test_unchanged_checkpoint_publish_keeps_generation_and_writes_nothing(tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path / 'unchanged.db') as connection:
        connection.execute('create table history (title text, id text, data text)')
        store.ensure_schema(connection, str)
        initial = store.snapshot(connection, str)
        assert store.publish(connection, str, initial, (), (), 'members')
        unchanged = store.snapshot(connection, str)
        writes = connection.total_changes
        assert store.publish(connection, str, unchanged, (), (), 'members')
        assert connection.total_changes == writes
        assert store.snapshot(connection, str).generation == unchanged.generation
        assert not store.publish(connection, str, initial, (), (), 'members')


def test_checkpoint_snapshot_accepts_tuple_rows_returned_by_mysql(tmp_path):
    import sqlite3
    class TupleCursor:
        def __init__(self, cursor): self.cursor = cursor
        def execute(self, *args): return self.cursor.execute(*args)
        def fetchall(self): return tuple(self.cursor.fetchall())
        def close(self): self.cursor.close()
    class TupleConnection:
        def __init__(self, connection): self.connection = connection
        def cursor(self): return TupleCursor(self.connection.cursor())
    with sqlite3.connect(tmp_path / 'tuple-rows.db') as connection:
        connection.execute('create table history (title text, id text, data text)')
        store.ensure_schema(connection, str)
        store.publish(connection, str, store.snapshot(connection, str),
                      (store.CheckpointWrite('Page', '{"version":2}', 'payload'),), (), 'members')
        from route.tool.ranking_checkpoint_auth import CheckpointVerification
        verification = CheckpointVerification()
        wrapped = TupleConnection(connection)
        assert store.snapshot(wrapped, str, verification).checkpoints == {'Page': '{"version":2}'}
        assert store.snapshot(wrapped, str, verification).checkpoints == {'Page': '{"version":2}'}


def test_ranking_startup_prunes_expired_views_without_new_visit(tmp_path):
    import sqlite3
    from ranking_test_support import build_test_app
    from route.tool.ranking_views import record_view
    app = build_test_app(tmp_path)
    with sqlite3.connect(app.db_path) as connection:
        record_view(connection, 'Public Page', 'Public Page', 'legacy-token', app.clock.value - 90000, str)
        assert connection.execute('select count(*) from realtime_popularity_views').fetchone()[0] == 1
    # Initialization of the real blueprint uses its existing connection and
    # daily worker; no HTTP view needs to arrive to remove expired rows.
    from route.rankings import init_rankings
    service = app.app.extensions['rankings']
    dependencies = service.dependencies
    init_rankings(app.app, connect=dependencies.connect, db_change=dependencies.db_change,
                  acl_check=dependencies.acl_check, get_display_name=dependencies.get_display_name,
                  render_page=dependencies.render_page, member_is_eligible=dependencies.member_is_eligible,
                  clock=dependencies.clock, contributor_refresh_seconds=None)
    with sqlite3.connect(app.db_path) as connection:
        assert connection.execute('select count(*) from realtime_popularity_views').fetchone()[0] == 0
