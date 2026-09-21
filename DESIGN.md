# Ranking surface contract

## Reference and scope

This addition follows the existing Ringo surface contract: SUIT/system type,
`--surface`, `--bg`, `--text`, `--muted`, `--bar-a`, 14px card radius, and
the existing sidebar/table patterns. It adds no new visual tokens or imagery.

## Content and hierarchy

The sidebar heading is `실시간 인기 문서`; each row leads with a compact rank
and preserves the document title exactly. The primary navigation list includes
the accessible `기여자 순위` link to the server-rendered contributor table.

## Reusable states

`ringo_trending_list` uses the existing `rc_wrap` list rhythm. A rank uses
`ringo_trending_rank`; ordinary loading, empty, and fetch-failure text use
`ringo_trending_message`. Structured API titles are assigned through DOM
`textContent`, and internal URLs remain same-origin.

## Responsive and interaction behavior

The same ranking snapshot renders in the desktop sidebar and a focused empty
mobile search result. At 640px and below, that result is fixed 10px from each
viewport edge and positioned below its input; rank and title stay in one flex
row. The sidebar refreshes every 30 seconds only while the tab is visible,
resumes immediately when it becomes visible, and does not use stale day-level
fallback content. Existing keyboard focus and link behavior remain in force.
The timed view event is invisible and creates no new control.

## Accessibility constraints

The contributor entry is a text-labelled link. Empty and error states are
plain readable text. Ranks are supplementary ordering context, while titles
remain intact text links. No motion is introduced.
