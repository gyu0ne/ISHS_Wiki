# Ranking surface contract

## Reference and scope

This addition follows the existing Ringo surface contract: SUIT/system type,
`--surface`, `--bg`, `--text`, `--muted`, `--bar-a`, 14px card radius, and
the existing sidebar/table patterns. Ranking accents extend those tokens; no
imagery, new font, or animation is added.

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

## Top-three emphasis

Use `ringo_rank_badge` in contributor rows only. Popular documents keep plain
neutral rank numbers. Gold, silver, and bronze follow the live contributor
order, not a fixed user.
Numbers remain visible, so color is supplementary. Fourth place onward stays
neutral. Contributor names and scores in the first three rows use weight 700
and a light row tint. Keep one ordinary table, with right-aligned tabular scores.

Light badge tokens (background / text / border): gold `#fff0bd / #744600 / #dfb34c`,
silver `#edf1f6 / #45566c / #b7c3d3`, bronze `#f9e7db / #80451f / #d5a37e`.
Dark equivalents: gold `#493a19 / #ffdc82 / #8e7131`, silver
`#303b49 / #d4deeb / #65758c`, bronze `#493226 / #f1bf9f / #93694c`.
Row tint mixes 40% of the badge background with the existing surface token.
Badge size is 32px in the table; radius 50%; border 1px.
Neutral rank/header text uses existing `--muted` in light mode and `#aab3bf`
in dark mode to preserve readable contrast.
Table cells use 12px/16px spacing, existing type, and existing `--hr` separators.

The primary reader scans the leading names; mobile readers need intact short
Korean names, readable scores, and document links. Text contrast and numeric
rank labels take precedence over medal colors. No decorative hover or motion,
no podium cards, and no changes to the inherited page shell are needed.

## Personal rank

Place a neutral `내 순위` summary immediately below the contributor table.
Use the same authenticated snapshot as the table, resolving the account by
its private ID rather than its display name. Show rank and score as separate
tabular values; an unranked account sees `아직 순위가 없습니다.`.
The summary uses existing `--bg`, `--hr`, `--text`, and `--radius` tokens,
16px padding, 20px top spacing, and a wrapping flex row with a 12px gap.
Keep the label and each value intact on narrow screens. It has no medal tint,
hover treatment, or motion. Private account IDs never enter the page or API.
