from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_contribution_engine import DocumentContributionEngine
from route.tool.ranking_contribution_scores import HistoryRevision


def restored_engine() -> DocumentContributionEngine:
    engine = DocumentContributionEngine('Page')
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [HistoryRevision(str(index), 'Page', text, start + timedelta(days=index),
                            author, '', len(text), '', '')
            for index, (text, author) in enumerate([
                ('original', 'alice'), ('', 'bob'), ('original', 'bob'),
            ], 1)]
    engine.advance(rows, {'alice', 'bob'}, start + timedelta(days=5))
    return engine


def test_duplicate_insertion_cannot_reuse_tokens_still_in_document() -> None:
    engine = restored_engine()
    at = datetime(2026, 1, 8, tzinfo=timezone.utc)
    engine.apply('Page', 'original original', at, 'bob', at.date(), 'bob', allow_removal_grace=True)
    assert {entry.user_id: entry.retained_characters for entry in engine.scores(engine.text, at).contributors()} == {
        'alice': 8, 'bob': 8,
    }


def test_restored_active_span_needs_no_historical_diff() -> None:
    engine = restored_engine()
    at = datetime(2026, 1, 8, tzinfo=timezone.utc)
    with patch.object(engine.differ, 'diff_main', wraps=engine.differ.diff_main) as compare:
        engine.restore('Page', 'original', 'bob', at.date(), at)
    assert compare.call_count == 0, 'Fully active historical tokens cannot be restored again'


def test_identical_deleted_text_is_compared_once_without_losing_priority() -> None:
    engine = DocumentContributionEngine('Page')
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for author in ('alice', 'bob'):
        ids = engine.create('Page', 'old text', author, at.date(), at)
        engine.remove(ids, at, None, None, None, False)
        engine.deleted_spans['Page'].append(('old text', ids))
    with patch.object(engine.differ, 'diff_main', wraps=engine.differ.diff_main) as compare:
        restored = engine.restore('Page', 'old text', 'carol', at.date(), at)
    assert all(engine.tokens[index].author in ('bob', None) for index in restored)
    assert compare.call_count == 1
