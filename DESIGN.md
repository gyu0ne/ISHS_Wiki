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

## Pagination and contributor sidebar

The full contributor list uses 20 rows per page with native links in a labelled
centered pagination nav after the personal rank summary. Keep the current member's global
rank visible on every page. Only global ranks 1, 2 and 3 receive medal colors;
page position never controls accents. Use previous/next and at most five nearby
page numbers, `aria-current="page"`, 44px minimum targets, wrapping flex layout,
8px gaps, existing surface/text/border/radius tokens and visible keyboard focus.
Invalid page inputs resolve to page 1; out-of-range pages clamp to the last page.
An empty list has one logical page and no pagination controls.

Below recent changes and popular documents, reuse the sidebar card for
`기여자 순위`, five compact rows, and a text-labelled `전체 보기` link.
Use the same 32px rank badge and global rank tokens as the table; nickname text
wraps safely, and a right-aligned tabular score stays intact. Refresh every
300 seconds only while visible, retaining the inherited mobile sidebar behavior.
Loading, empty and unavailable states are plain readable text; unauthorized
sessions hide the contributor card. Nicknames are display labels; each account
keeps its own score. No person-identity matching or new settings are introduced.
The sidebar's full-list link uses `--text` for readable light/dark contrast.
Pager keyboard outlines sit 3px inside their targets because the inherited
article wrapper clips outside overflow; sidebar links retain 2px offset outlines.

## Period selection and personal document scores

Keep the heading `기여자 순위`. Above the table, `ringo_rank_period` provides
native `전체` and `월별` links with a visible active text-token border and
`aria-current="page"`; switching period resets pagination to page1. Monthly
mode opens the current KST calendar month and offers a labelled native month
input and `보기` submit button. Calendar months use original contribution
dates after full-history attribution, so restoration never renews the month. The sidebar retains the
all-time top5 and its existing all-time full-list link.

Use existing surface/background/text/accent/border/radius tokens. The period
control wraps, has4px internal spacing and44px minimum link height, and sits
20px above the table. No new colors, animations or client-side routing.
The month form uses a wrapping flex row,8px gap,44px minimum input/button
height and existing surface/text/border tokens. Month selection submits a
native GET request with YYYY-MM and resets to page1. Keep period on all pagination links. Preserve the centered44px pager.

Group the small 14px `내 순위` label above the selected-period values on the
left, using a 4px gap. The rank is 24px/700 with a 1.3 line height; the score
is 14px normal weight and baseline-aligned with a 12px gap. Place a separate
`기여한 문서 보기` link on the right, styled as a neutral outlined button with
44px minimum height, 8px/12px padding, 10px radius, and existing surface/text/hr
tokens. At 640px and below, the link spans the summary width below the values.
Keep visible focus and a text-color border on hover, without animation. The
document-specific own-rank summary reuses the label/value hierarchy. The link leads to the
session owner's `/rankings/me` page, with the same period links and a
`기여자 순위` back link. Other accounts' private identifiers never appear.

Use a neutral two-column `ringo_document_table`: `문서` and `기여 점수`.
Reuse table typography,12px/16px cell spacing,header surface and row separators.
Document links wrap at Korean word boundaries where possible, then anywhere
for long uninterrupted identifiers; scores stay right-aligned and unbroken.
Show20 documents perpage. A simple empty state replaces an empty table.
Every detail request checks current public visibility before exposing titles,
links, counts or totals. Preserve loading/error and no-contribution states.
Document-detail rows use four decimal places so small contributions remain
inspectable; the existing leaderboard and summary retain two decimal places.
Totals derive from unrounded scores, without rounding individual rows first.

## A document's contributors

After a readable document body, add one native `기여자 순위 보기` link in a
subtle separated footer row. Reuse surface/text/border/radius tokens,44px
minimum target and visible keyboard focus. Only the document render with a
ranking ticket and raw route name exposes the link; rankings pages do not.
The destination shows a linked document title and `문서로 돌아가기`, then the
same overall/month selector,20-row contributor table, top3 medals and the
viewer's rank within that document. Scores reuse existing original-document
buckets; do not introduce a second scoring formula. The sidebar remains the
overall wiki leaderboard. Current public visibility is checked before output.

## Ranking surface polish

Keep ranking data primary and use one control row above each table: period
links on the left and the native month form on the right, wrapping with a
12px gap and 20px bottom spacing. Controls retain 44px targets. A document
ranking uses the existing page heading followed by one 20px linked document
title, without repeating the heading in that title. Back links stay native.
The personal document page is titled `기여한 문서`; its total uses the same
neutral label/value hierarchy as personal rank, with 16px inset and 20px gap.

The document footer offers a right-aligned `기여자 순위 보기` action with a
decorative arrow, 44px target, and existing neutral button tokens; it is a
quiet continuation after reading, not a second section heading. At 640px
the action fills the available row. Contributor sidebar full-list links
have 44px touch height. Remove the unwanted fallback edit/discussion/bbs
controls and their now-unused handlers; keep configured sidebar HTML and
the recent-changes, popular-documents and contributor cards.

Back navigation belongs inside the period toolbar as a 44px outlined link
on the right, with a decorative left arrow. At 1024px and below, the native
month form follows the period/back row on its own wrapping row. Apply the
same pattern to personal documents, document rankings, loading and errors.
No new fonts, colors, motion, libraries, scoring rules or site-wide shell
redesign.
