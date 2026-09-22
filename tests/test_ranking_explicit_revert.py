import json
import zlib
from base64 import b64decode
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_contribution_engine import DocumentContributionEngine
from route.tool.ranking_contribution_scores import HistoryRevision
from route.tool.ranking_replay_checkpoint import InvalidCheckpoint
from route.tool.ranking_revision_snapshot import RevisionSnapshot


def history() -> list[HistoryRevision]:
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    return [
        HistoryRevision(str(number), 'Page', body, start + timedelta(days=number),
                        author, send, len(body), '', kind)
        for number, (body, author, kind, send) in enumerate([
            ('한글😀abc', 'alice', 'r1', ''),
            ('한글😀abcabc', 'bob', '', ''),
            ('한글😀', 'bob', '', ''),
            ('한글😀abcabc', 'bob', 'revert', '돌리기 (r2)'),
        ], 1)
    ]


@pytest.mark.parametrize('restart', [False, True])
def test_explicit_revert_preserves_exact_target_live_state_without_diff(restart: bool) -> None:
    revisions = history()
    now = revisions[-1].date + timedelta(days=2)
    engine = DocumentContributionEngine('Page')
    engine.advance(revisions[:3], {'alice', 'bob'}, now)
    expected = engine.revision_snapshots[2].placements()
    continuity = engine.tokens[0].continuous_since
    if restart:
        engine = engine.load_checkpoint(engine.dump_checkpoint())
    with patch.object(engine.differ, 'diff_main', side_effect=AssertionError('unexpected diff')):
        engine.advance(revisions[3:], {'alice', 'bob'}, now)
    assert engine.documents['Page'].placements == expected
    assert engine.tokens[0].continuous_since == continuity
    assert all(token.active_count == 1 for token in engine.tokens.values())
    assert all(not token.removal_active for token in engine.tokens.values())
    assert {entry.user_id: entry.retained_characters for entry in engine.scores(engine.text, now).contributors()} == {
        'alice': 6, 'bob': 3,
    }


def test_explicit_revert_cannot_revive_credit_frozen_after_deletion() -> None:
    revisions = history()
    now = revisions[-1].date + timedelta(days=2)
    engine = DocumentContributionEngine('Page', credit_limit=3)
    engine.advance(revisions[:3], {'alice', 'bob'}, now)
    engine = engine.load_checkpoint(engine.dump_checkpoint())
    engine.advance(revisions[3:], {'alice', 'bob'}, now)
    assert all(engine.tokens[token_id].author is None
               for token_id in engine.revision_snapshots[2].placements()[3:])
    assert {entry.user_id: entry.retained_characters for entry in engine.scores(engine.text, now).contributors()} == {
        'alice': 3,
    }


@pytest.mark.parametrize('change', [
    {'type': ''}, {'send': '(r2)'}, {'send': '돌리기 (r2) trailing'},
    {'send': '돌리기 (r0)'}, {'send': '돌리기 (r4)'}, {'send': '돌리기 (r99)'},
    {'data': 'different'},
])
def test_untrusted_or_mismatched_restore_target_uses_generic_diff(change: dict[str, str]) -> None:
    revisions = history()
    now = revisions[-1].date
    engine = DocumentContributionEngine('Page')
    engine.advance(revisions[:3], {'alice', 'bob'}, now)
    revision = replace(revisions[-1], **change)
    with patch.object(engine.differ, 'diff_main', wraps=engine.differ.diff_main) as compare:
        engine.advance([revision], {'alice', 'bob'}, now)
    assert compare.call_count > 0


def test_corrupt_live_snapshot_falls_back_before_mutating_tokens() -> None:
    revisions = history()
    now = revisions[-1].date
    engine = DocumentContributionEngine('Page')
    engine.advance(revisions[:3], {'alice', 'bob'}, now)
    snapshot = engine.revision_snapshots[2]
    engine.revision_snapshots[2] = RevisionSnapshot(snapshot.digest, snapshot.length, ((999, snapshot.length),))
    with patch.object(engine.differ, 'diff_main', wraps=engine.differ.diff_main) as compare:
        engine.advance(revisions[3:], {'alice', 'bob'}, now)
    assert compare.call_count > 0
    assert engine.text == revisions[-1].data


@pytest.mark.parametrize('corruption', [
    'version', 'duplicate_revision', 'negative_start', 'zero_count', 'missing_token',
    'overlap', 'wrong_length', 'wrong_digest', 'future_revision',
])
def test_checkpoint_rejects_corrupt_snapshot(corruption: str) -> None:
    revisions = history()
    engine = DocumentContributionEngine('Page')
    engine.advance(revisions[:3], {'alice', 'bob'}, revisions[-1].date)
    data = json.loads(zlib.decompress(b64decode(engine.dump_checkpoint()[5:])))
    if corruption == 'version':
        data[0] = 1
    elif corruption == 'duplicate_revision':
        data[11].append(data[11][0])
    elif corruption == 'negative_start':
        data[11][0][3] = [[-1, 6]]
    elif corruption == 'zero_count':
        data[11][0][3] = [[0, 0]]
    elif corruption == 'missing_token':
        data[11][0][3] = [[999, 6]]
    elif corruption == 'overlap':
        data[11][0][3] = [[0, 3], [0, 3]]
    elif corruption == 'wrong_length':
        data[11][0][2] = 5
    elif corruption == 'wrong_digest':
        data[11][0][1] = 'z' * 64
    else:
        data[11][0][0] = 99
    with pytest.raises(InvalidCheckpoint):
        engine.load_checkpoint(json.dumps(data))


def test_revision_snapshots_store_ranges_without_duplicating_text() -> None:
    revision = replace(history()[0], data='가' * 10000)
    engine = DocumentContributionEngine('Page')
    engine.advance([revision], {'alice'}, revision.date)
    payload = engine.dump_checkpoint()
    data = json.loads(zlib.decompress(b64decode(payload[5:])))
    assert data[11][0][3] == [[0, 10000]]
    resumed = engine.load_checkpoint(payload)
    assert resumed.revision_snapshots == engine.revision_snapshots
