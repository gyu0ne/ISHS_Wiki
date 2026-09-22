from datetime import datetime, timedelta, timezone

from route.tool import ranking_contributions
from route.tool.ranking_contribution_scores import HistoryRevision


def test_checkpoint_restores_original_credit_without_replaying_prior_revisions():
    # Given a document whose original text was deleted by another member.
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    revisions = [
        HistoryRevision(str(index), 'Page', text, start + timedelta(days=index),
                        author, '', len(text), '', '')
        for index, (text, author) in enumerate(
            [('original', 'alice'), ('', 'bob'), ('original!', 'bob')], 1
        )
    ]
    engine_type = getattr(ranking_contributions, 'DocumentContributionEngine', None)
    assert engine_type is not None, 'Contribution replay has no persistent checkpoint yet'
    engine = engine_type('Page')
    engine.advance(revisions[:2], {'alice', 'bob'}, start + timedelta(days=5))
    payload = engine.dump_checkpoint()
    # When a fresh engine resumes only the last revision.
    resumed = engine_type.load_checkpoint(payload)
    resumed.advance(revisions[2:], {'alice', 'bob'}, start + timedelta(days=5))
    # Then original ownership survives and current-body overlays never alter history.
    scores = resumed.scores('original!', start + timedelta(days=5))
    assert {entry.user_id: entry.retained_characters for entry in scores.contributors()} == {
        'alice': 8, 'bob': 1,
    }
    resumed.scores('', start + timedelta(days=5))
    assert resumed.scores('original!', start + timedelta(days=5)) == scores
    assert resumed.text == 'original!'


def test_checkpoint_preserves_hidden_gaps_requests_and_credit_freeze():
    # Given hidden, discontinuous, pending and backdated edits across the cutoff.
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        ('1', 'alpha beta', 0, 'alice', '', '', 10),
        ('2', 'beta', 2, 'bob', '', '', -5),
        ('3', 'request', 3, 'alice', '', 'edit_request', 0),
        ('5', 'beta gamma', 4, 'alice', 'O', '', 6),
        ('6', 'beta gamma delta', 1, 'bob', '', '', 6),
        ('7', 'alpha beta gamma delta', 6, 'alice', '', '', 6),
    ]
    revisions = [HistoryRevision(number, 'Page', text, start + timedelta(days=day),
                                 author, '', length, hidden, kind)
                 for number, text, day, author, hidden, kind, length in rows]
    now = start + timedelta(days=8)
    for credit_limit in (None, 2):
        for split in range(1, len(revisions)):
            for mature in (False, True):
                engine = ranking_contributions.DocumentContributionEngine('Page', credit_limit)
                engine.advance(revisions[:split], {'alice', 'bob'}, now)
                # When serialization separates the historical prefix from its tail.
                resumed = engine.load_checkpoint(engine.dump_checkpoint())
                resumed.advance(revisions[split:], {'alice', 'bob'}, now)
                # Then live and mature scoring match an uninterrupted replay.
                expected = ranking_contributions.compute_contribution_scores(
                    revisions, {'Page': rows[-1][1]}, {'alice', 'bob'}, now,
                    require_mature=mature,
                    credit_limits=None if credit_limit is None else {'Page': credit_limit},
                )
                assert resumed.scores(rows[-1][1], now, require_mature=mature) == expected


def test_checkpoint_rejects_invalid_token_references():
    # Given a checkpoint containing an impossible placement.
    import json
    import pytest
    from route.tool.ranking_replay_checkpoint import InvalidCheckpoint
    engine = ranking_contributions.DocumentContributionEngine('Page')
    payload = [2, 'Page', None, None, None, False, False, '', [], [], [], []]
    payload[7], payload[8] = 'x', [99]
    # When loading it, then the boundary rejects it before any scoring occurs.
    with pytest.raises(InvalidCheckpoint):
        engine.load_checkpoint(json.dumps(payload))


def test_compressed_checkpoint_remains_small_and_reads_legacy_json():
    import json
    import zlib
    from base64 import b64decode

    now = datetime(2026, 4, 3, tzinfo=timezone.utc)
    body = ('학교 문서 본문입니다. 내용이 길어지는 상황입니다.' + chr(10)) * 1000
    engine = ranking_contributions.DocumentContributionEngine('Page')
    engine.advance([HistoryRevision('1', 'Page', body, now - timedelta(days=2),
                                    'alice', '', len(body), '', '')], {'alice'}, now)
    compressed = engine.dump_checkpoint()
    legacy = zlib.decompress(b64decode(compressed[5:])).decode()
    assert json.loads(legacy)[0] == 2
    assert len(compressed.encode()) < len(legacy.encode()) / 10
    for payload in (compressed, legacy):
        resumed = engine.load_checkpoint(payload)
        assert resumed.text == body
        assert resumed.scores(body, now) == engine.scores(body, now)


def test_invalid_compression_is_rejected():
    import pytest
    from route.tool.ranking_replay_checkpoint import InvalidCheckpoint

    for payload in ('zlib:!', 'zlib:eA=='):
        with pytest.raises(InvalidCheckpoint):
            ranking_contributions.DocumentContributionEngine.load_checkpoint(payload)
