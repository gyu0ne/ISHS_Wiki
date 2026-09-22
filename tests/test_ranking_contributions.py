from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone

from ranking_package_support import bootstrap_route_tool_package


bootstrap_route_tool_package()

from route.tool.ranking_contributions import HistoryRevision, compute_contributors


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
        self.assertAlmostEqual(actual.score, 0.0664894401)

    def test_same_document_day_saves_do_not_change_score(self) -> None:
        body = "abcdefghij"
        split = tuple(
            revision(
                index + 1,
                "A",
                body[: index + 1],
                index,
                "alice",
                mode="r1" if index == 0 else "",
            )
            for index in range(len(body))
        )
        combined = (revision(1, "A", body, 0, "alice", mode="r1"),)

        split_result = results(*split, current={"A": body})["alice"]
        combined_result = results(*combined, current={"A": body})["alice"]

        self.assertEqual(split_result, combined_result)

    def test_distinct_documents_on_same_day_receive_distinct_rewards(self) -> None:
        split = (
            revision(1, "A", "a", 0, "alice", mode="r1"),
            revision(1, "B", "b", 1, "alice", mode="r1"),
        )
        combined = (revision(1, "A", "ab", 0, "alice", mode="r1"),)

        split_result = results(*split, current={"A": "a", "B": "b"})["alice"]
        combined_result = results(*combined, current={"A": "ab"})["alice"]

        self.assertGreater(split_result.score, combined_result.score)
        self.assertEqual(split_result.active_days, 1)

    def test_distinct_days_receive_distinct_rewards(self) -> None:
        revisions = (
            revision(1, "A", "a", 0, "alice", mode="r1"),
            revision(2, "A", "ab", 24, "alice"),
        )

        actual = results(*revisions, current={"A": "ab"})["alice"]

        self.assertEqual(actual.active_days, 2)
        self.assertAlmostEqual(actual.score, 0.0333111284)

    def test_equal_length_replacement_preserves_other_authors_text(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "axc", 80, "bob"),
        )

        actual = results(*revisions, current={"A": "axc"})

        self.assertEqual(actual["alice"].retained_characters, 2)
        self.assertEqual(actual["bob"].retained_characters, 1)

    def test_shrinking_replacement_counts_maximum_side_once(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "x", 80, "bob"),
        )

        actual = results(*revisions, current={"A": "x"})

        self.assertEqual(set(actual), {"bob"})
        self.assertEqual(actual["bob"].retained_characters, 1)
        self.assertAlmostEqual(actual["bob"].score, 0.0499002327)

    def test_pure_other_user_deletion_receives_retained_editing_credit(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
        )

        actual = results(*revisions, current={"A": ""})

        self.assertEqual(set(actual), {"bob"})
        self.assertEqual(actual["bob"].retained_characters, 0)
        self.assertAlmostEqual(actual["bob"].score, 0.0499002327)

    def test_deletion_credit_matures_at_24_hours(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
        )

        before = results(*revisions, current={"A": ""}, hours=103)
        at_boundary = results(*revisions, current={"A": ""}, hours=104)

        self.assertNotIn("bob", before)
        self.assertEqual(at_boundary["bob"].retained_characters, 0)

    def test_hidden_deletion_does_not_mint_credit(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete", hidden="O"),
        )

        self.assertEqual(results(*revisions, current={"A": ""}), {})

    def test_replacement_then_delete_matches_direct_delete_on_same_day(self) -> None:
        replacement_then_delete = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "xyz", 80, "bob"),
            revision(3, "A", "", 81, "bob", mode="delete"),
        )
        direct_delete = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
        )

        split = results(*replacement_then_delete, current={"A": ""})["bob"]
        direct = results(*direct_delete, current={"A": ""})["bob"]

        self.assertEqual(split, direct)

    def test_own_added_then_deleted_text_receives_no_new_credit(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "alice", mode="delete"),
        )

        self.assertEqual(results(*revisions, current={"A": ""}), {})

    def test_repeated_removal_keeps_first_deletion_author_day_and_lineage(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(2, "A", "", 80, "bob", mode="delete"),
            revision(3, "A", "x", 81, "bob"),
            revision(4, "A", "abcx", 120, "carol"),
            revision(1, "B", "abc", 121, "carol", mode="r1"),
            revision(5, "A", "x", 122, "carol"),
            revision(2, "B", "", 130, "carol", mode="delete"),
        )

        actual = results(*revisions, current={"A": "x", "B": ""}, hours=250)

        self.assertEqual(set(actual), {"bob"})
        self.assertEqual((actual["bob"].retained_characters, actual["bob"].active_days), (1, 1))
        self.assertAlmostEqual(actual["bob"].score, 0.0499002328)

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

        self.assertEqual(set(actual), {"alice", "bob"})
        self.assertEqual(actual["alice"].retained_characters, 2)
        self.assertEqual(actual["bob"].retained_characters, 0)

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

    def test_identical_text_in_independent_documents_keeps_each_author(self) -> None:
        revisions = (
            revision(1, "A", "abc", 0, "alice", mode="r1"),
            revision(1, "B", "abc", 80, "bob", mode="r1"),
        )

        actual = results(*revisions, current={"A": "abc", "B": "abc"})

        self.assertEqual(set(actual), {"alice", "bob"})
        self.assertEqual(actual["alice"].retained_characters, 3)
        self.assertEqual(actual["bob"].retained_characters, 3)

    def test_move_history_rewritten_to_destination_keeps_original_author(self) -> None:
        revisions = (
            revision(1, "B", "abc", 0, "alice", mode="r1"),
            revision(2, "B", "abc", 80, "bob", mode="move"),
        )

        actual = results(*revisions, current={"B": "abc"})

        self.assertEqual(set(actual), {"alice"})
        self.assertEqual(actual["alice"].retained_characters, 3)

    def test_requested_curve_values_and_tiny_edit_ordering(self) -> None:
        expected = {
            1: 0.01665556,
            100: 1.56353,
            1_000: 10.31497,
            10_000: 27.51778,
            100_000: 39.26350,
        }

        for quantity, score in expected.items():
            with self.subTest(quantity=quantity):
                body = "x" * quantity
                actual = results(
                    revision(1, "A", body, 0, "alice", mode="r1"), current={"A": body}
                )["alice"]
                self.assertAlmostEqual(actual.score, score, places=5)

        tiny_revisions = tuple(
            revision(1, f"D{index}", chr(65 + index), index, "alice", mode="r1")
            for index in range(10)
        )
        tiny = results(
            *tiny_revisions,
            current={f"D{index}": chr(65 + index) for index in range(10)},
        )["alice"]

        self.assertAlmostEqual(tiny.score, 0.1665556, places=6)
        self.assertLess(tiny.score, expected[100])
        self.assertLess(expected[100], expected[1_000])

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

    def test_new_text_matures_at_24_hours(self) -> None:
        revisions = (revision(1, "A", "a", 0, "alice", mode="r1"),)

        before = results(*revisions, current={"A": "a"}, hours=23)
        at_boundary = results(*revisions, current={"A": "a"}, hours=24)

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
