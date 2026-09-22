from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from .ranking_monthly_awards import Connection, MonthlyAwards, get_member_awards


@dataclass(frozen=True, slots=True)
class RankingChallenge:
    key: str
    title: str
    experience: int
    maximum_rank: int
    wins: int = 0
    alltime: bool = False

    def achieved(self, awards: MonthlyAwards) -> bool:
        if self.alltime:
            return awards.alltime_best_rank is not None and awards.alltime_best_rank <= self.maximum_rank
        return (
            awards.best_rank is not None
            and awards.best_rank <= self.maximum_rank
            and awards.wins >= self.wins
        )


RANKING_CHALLENGES: Final = (
    RankingChallenge("monthly_top3", "🥉", 1000, 3),
    RankingChallenge("monthly_first", "🥵", 3000, 1),
    RankingChallenge("monthly_first_twice", "🫪", 5000, 1, 2),
    RankingChallenge("alltime_top10", "🪨", 1000, 10, alltime=True),
    RankingChallenge("alltime_top3", "💎", 3000, 3, alltime=True),
    RankingChallenge("alltime_first", "🐐", 5000, 1, alltime=True),
)


def earned_ranking_challenges(
    connection: Connection, member_id: str, db_change: Callable[[str], str]
) -> tuple[RankingChallenge, ...]:
    awards = get_member_awards(connection, member_id, db_change)
    return tuple(item for item in RANKING_CHALLENGES if item.achieved(awards))
