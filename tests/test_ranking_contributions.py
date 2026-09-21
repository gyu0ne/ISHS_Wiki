from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "route" / "tool"))

from ranking_contributions import HistoryRevision, compute_contributors


KST = timezone(timedelta(hours=9))
BASE = datetime(2026, 1, 1, tzinfo=KST)


def revision(
    revision_id: int,
    title: str,
    data: str,
    hours: int,
    author: str,
    *,
    mode: str = "",
    memo: str = "",
    length: int | None = None,
    hidden: str = "",
) -> HistoryRevision:
    return HistoryRevision(
        id=str(revision_id),
        title=title,
        data=data,
        date=BASE + timedelta(hours=hours),
        ip=author,
        send=memo,
        leng=len(data) if length is None else length,
        hide=hidden,
        type=mode,
    )


def results(*revisions: HistoryRevision, current: dict[str, str], hours: int = 200):
    return {
        entry.user_id: entry
        for entry in compute_contributors(
            revisions, current, {"alice", "bob", "carol"}, BASE + timedelta(hours=hours)
        )
    }


class RankingContributionsTest(unittest.TestCase):
    def test_backfills_first_complete_revision_and_aggregates_daily_reward(self) -> None:
        # Given: two retained additions by one member on one KST day.
        revisions = (
            revision(1, "A", "ab", 0, "alice", mode="r1"),
            revision(2, "A", "abcd", 1, "alice"),
        )

        # When: historical contributions are computed after maturation.
        actual = results(*revisions, current={"A": "abcd"})["alice"]

        # Then: four characters form one daily q bucket.
        self.assertEqual((actual.retained_characters, actual.active_days), (4, 1))
        self.assertAlmostEqual(actual.score, 400 / 1004)

    def test_same_day_saves_and_pages_do_not_change_score(self) -> None:
        # Given: equivalent text split across revisions and documents.
        split = (
            revision(1, "A", "ab", 0, "alice", mode="r1"),
            revision(2, "A", "abcd", 1, "alice"),
            revision(1, "B", "ef", 2, "alice", mode="r1"),
        )
        combined = (revision(1, "A", "abcdef", 0, "alice", mode="r1"),)

        # When: both histories are scored.
        split_result = results(*split, current={"A": "abcd", "B": "ef"})["alice"]
        combined_result = results(*combined, current={"A": "abcdef"})["alice"]

        # Then: aggregation by author and KST day is invariant.
        self.assertEqual(split_result, combined_result)

    def test_distinct_days_receive_distinct_rewards(self) -> None:
        revisions = (
            revision(1, "A", "a", 0, "alice", mode="r1"),
            revision(2, "A", "ab", 24, "alice"),
        )

        actual = results(*revisions, current={"A": "ab"})["alice"]

        self.assertEqual(actual.active_days, 2)
        self.assertAlmostEqual(actual.score, 200 / 1001)

    def test_equal_length_replacement_preserves_other_authors_text(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "axc", 80, "bob"),
        )

        actual = results(*revisions, current={"A": "axc"})

        self.assertEqual(actual["alice"].retained_characters, 2)
        self.assertEqual(actual["bob"].retained_characters, 1)

    def test_delete_and_restore_recovers_origin_without_new_reward(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "abc", 120, "bob"),
        )

        actual = results(*revisions, current={"A": "abc"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 3)

    def test_segmented_partial_restore_recovers_deleted_prefix_origin(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "a", 120, "bob"),
            revision(4, "A", "ab", 121, "bob"),
        )

        actual = results(*revisions, current={"A": "ab"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 2)

    def test_segmented_full_restore_does_not_mint_restorer_credit(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "a", 120, "bob"),
            revision(4, "A", "ab", 121, "bob"),
            revision(5, "A", "abc", 122, "bob"),
        )

        actual = results(*revisions, current={"A": "abc"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 3)

    def test_restore_with_new_suffix_only_credits_suffix(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "abcX", 120, "bob"),
        )

        actual = results(*revisions, current={"A": "abcX"})

        self.assertEqual(actual["alice"].retained_characters, 3)
        self.assertEqual(actual["bob"].retained_characters, 1)

    def test_segmented_restore_with_suffix_preserves_observed_prefix(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "a", 120, "bob"),
            revision(4, "A", "abX", 121, "bob"),
        )

        actual = results(*revisions, current={"A": "abX"})

        self.assertEqual(actual["alice"].retained_characters, 2)
        self.assertEqual(actual["bob"].retained_characters, 1)

    def test_restore_combines_nonconflicting_spans_from_multiple_deletions(self) -> None:
        revisions = (
            revision(1, "A", "abcdef", 0, "alice", mode="r1"),
            revision(2, "A", "def", 80, "bob"),
            revision(3, "A", "", 81, "bob", mode="delete"),
            revision(4, "A", "abcdeX", 120, "bob"),
        )

        actual = results(*revisions, current={"A": "abcdeX"})

        self.assertEqual(actual["alice"].retained_characters, 5)
        self.assertEqual(actual["bob"].retained_characters, 1)

    def test_full_restore_over_nonempty_text_recovers_known_origin(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "x", 120, "bob"),
            revision(4, "A", "abc", 121, "bob"),
        )

        actual = results(*revisions, current={"A": "abc"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 3)

    def test_known_copy_and_move_reuse_origin_without_duplication(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(1, "B", "abc", 80, "bob", mode="r1"),
            revision(2, "A", "", 81, "bob", mode="delete"),
        )

        actual = results(*revisions, current={"B": "abc"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 3)

    def test_signup_anonymous_metadata_and_hidden_authorship_are_excluded(self) -> None:
        revisions = (
            revision(1, "A", "a", 0, "alice", mode="r1", memo="회원가입"),
            revision(2, "A", "ab", 1, "10.0.0.1"),
            revision(1, "user:alice", "profile", 2, "alice", mode="user"),
            revision(3, "A", "abc", 3, "bob", hidden="O"),
            revision(4, "A", "abcd", 4, "carol"),
        )

        actual = results(*revisions, current={"A": "abcd", "user:alice": "profile"})

        self.assertEqual(set(actual), {"carol"})
        self.assertEqual(actual["carol"].retained_characters, 1)

    def test_incomplete_baseline_gap_and_ambiguous_request_do_not_gain_owner(self) -> None:
        revisions = (
            revision(7, "A", "base", 0, "alice"),
            revision(8, "A", "baseX", 1, "bob", mode="edit_request", length=0),
            revision(9, "A", "baseXY", 2, "carol", mode="edit_request", length=1),
        )

        actual = results(*revisions, current={"A": "baseXY"})

        self.assertEqual(actual, {})

    def test_new_text_matures_at_72_hours(self) -> None:
        revisions = (revision(1, "A", "a", 0, "alice", mode="r1"),)

        before = results(*revisions, current={"A": "a"}, hours=71)
        at_boundary = results(*revisions, current={"A": "a"}, hours=72)

        self.assertNotIn("alice", before)
        self.assertEqual(at_boundary["alice"].retained_characters, 1)

    def test_mature_text_removed_by_other_has_24_hour_grace(self) -> None:
        revisions = (
            revision(1, "A", "a", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
        )

        before = results(*revisions, current={"A": ""}, hours=103)
        at_boundary = results(*revisions, current={"A": ""}, hours=104)

        self.assertEqual(before["alice"].retained_characters, 1)
        self.assertNotIn("alice", at_boundary)

    def test_own_removal_is_immediate(self) -> None:
        revisions = (
            revision(1, "A", "a", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "alice", mode="delete"),
        )

        actual = results(*revisions, current={"A": ""}, hours=81)

        self.assertNotIn("alice", actual)

    def test_current_body_reconciliation_does_not_credit_unseen_text(self) -> None:
        revisions = (revision(1, "A", "a", 0, "alice", mode="r1"),)

        actual = results(*revisions, current={"A": "ab"})

        self.assertEqual(actual["alice"].retained_characters, 1)

    def test_untracked_current_deletion_never_invents_recomputation_grace(self) -> None:
        revisions = (revision(1, "A", "a", 0, "alice", mode="r1"),)

        first_run = results(*revisions, current={"A": ""}, hours=200)
        much_later_run = results(*revisions, current={"A": ""}, hours=2_000)

        self.assertNotIn("alice", first_run)
        self.assertNotIn("alice", much_later_run)

    def test_nfc_equivalent_restore_keeps_original_owner(self) -> None:
        revisions = (
            revision(1, "A", "가", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "가", 120, "bob"),
        )

        actual = results(*revisions, current={"A": "가"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 1)

    def test_ambiguous_request_does_not_become_the_next_applied_baseline(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "xyz", 80, "bob", mode="edit_request", length=0),
            revision(3, "A", "abcQ", 81, "carol", mode="edit_request", length=1),
            revision(4, "A", "abcQR", 82, "bob"),
        )

        actual = results(*revisions, current={"A": "abcQR"})

        self.assertEqual(actual["alice"].retained_characters, 3)
        self.assertEqual(actual["bob"].retained_characters, 1)
        self.assertNotIn("carol", actual)

    def test_document_revision_order_wins_over_stored_request_date(self) -> None:
        revisions = (
            revision(1, "A", "a", 100, "alice", mode="r1"),
            revision(2, "A", "ab", 0, "bob", mode="edit_request", length=1),
            revision(1, "B", "z", 1, "bob", mode="r1"),
        )

        actual = results(*revisions, current={"A": "ab", "B": "z"})

        self.assertEqual(actual["alice"].retained_characters, 1)
        self.assertEqual(actual["bob"].retained_characters, 2)
        self.assertEqual(actual["bob"].active_days, 1)

    def test_handles_100k_character_snapshot_within_budget(self) -> None:
        # Given: a production-sized initial snapshot.
        body = "x" * 100_000
        edited = body[:-1] + "y"
        revisions = (
            revision(1, "A", body, 0, "alice", mode="r1"),
            revision(2, "A", edited, 1, "bob"),
        )

        # When: scoring the snapshot.
        started = time.perf_counter()
        actual = results(*revisions, current={"A": edited})
        elapsed = time.perf_counter() - started

        # Then: all content is retained without a quadratic scan.
        self.assertEqual(actual["alice"].retained_characters, 99_999)
        self.assertEqual(actual["bob"].retained_characters, 1)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
