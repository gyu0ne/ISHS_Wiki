from itertools import product
import json
import sqlite3
from pathlib import Path

from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_text_diff import ContributionDiffer
from test_ranking_incremental import observe_history_reads, restarted
from test_document_contributor_cache import build_cache


def test_alignment_reconstructs_unicode_and_repeated_text() -> None:
    # Given repeated code points, whitespace and characters outside the BMP.
    bodies = ['', '가나다😀𐐀', 'abababa', 'bababab', '  가\n나😀', '😀😀가😀']
    differ = ContributionDiffer()
    # When matching each pair, both sides must be recoverable without lost characters.
    for old, new in product(bodies, repeat=2):
        parts = differ.diff_main(old, new)
        assert ''.join(text for operation, text in parts if operation != 1) == old
        assert ''.join(text for operation, text in parts if operation != -1) == new
        assert parts == differ.diff_main(old, new)


def test_old_algorithm_metadata_rebuilds_once_even_without_source_edits(tmp_path: Path) -> None:
    # Given a saved ranking from the previous matching algorithm.
    cache = build_cache(tmp_path)
    expected = cache.snapshot('member-a')
    database = tmp_path / 'document-contributors.sqlite3'
    with sqlite3.connect(database) as connection:
        rows = connection.execute('select title, metadata from contributor_checkpoints').fetchall()
        for title, payload in rows:
            metadata = json.loads(payload)
            metadata['version'] = 1
            connection.execute('update contributor_checkpoints set metadata = ? where title = ?',
                               (json.dumps(metadata), title))
    reads = observe_history_reads(cache)
    # When refreshing unchanged source data after an algorithm upgrade.
    cache = restarted(cache)
    cache._refresh()
    # Then the history is rebuilt once and subsequent requests use its persisted result.
    assert reads
    assert cache.snapshot('member-a') == expected
    reads.clear()
    cache._refresh()
    assert reads == []
