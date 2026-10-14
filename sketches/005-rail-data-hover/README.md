## Variant: 005 — the data in the rail, and hover for meaning

### Design stance
One panel on the left holds everything the machine knows — the memory's shape *and* its vitals — so the turn gets the whole right side and nothing floats in a separate bar. Every non-obvious thing explains itself when you hover it.

### What changed from 004
- **No bottom bar.** `session`, `cache`, `jobs`, and the two subscriptions moved into the left rail, directly under the tree/view/queue/here group, separated by one hairline. The rail ends with the `/` palette, pinned to the bottom.
- **The packets have a header row.** `tool · command / arguments · exit · time`. Those bare `0`s were **exit codes**, not token counts — see below.
- **Contrast tuned** between the first sketches and Illan's own terminal, measured rather than eyeballed:

	                body   dim   hairline     (contrast vs background)
	001 prototypes  16.0   2.9   1.17
	005 tuned       16.0   5.9   1.30
	his terminal    12.5   5.5   1.99

  The body was never the problem — his terminal's is *lower* (12.5 vs 16.0). What was unreadable was the **dim** level (2.9) and the hairlines (1.17). 005 matches his dim readability at 5.9 and stops short of his hairlines at 1.30.
- **30 hover explanations**, every one with content (verified: no element carries the tooltip class without the text). They hang off a `.tip` class with a CSS `::after`, so there is no JavaScript.

### On per-tool tokens
They do not exist to show. Usage is measured **per model call** — that is what the relay reports — and one tool round is one part of one call. So the honest per-tool data is exit code and duration; the token accounting lives in the rail (`cache 95.3%`, and the meter's totals). The tooltip on the `exit` column says exactly this, because the bare `0` invited the wrong reading.

### Key choices
- Layout: 30ch rail, one wide centre column. Same 001 type and spacing.
- Colour: three palettes (blue / green / mixed), switchable live, 14 tokens each, identical token sets so nothing silently falls back.
- Interaction: palette switch, foldable reasoning, expandable tool output, hover explanations.

### Trade-offs
- Strong at: nothing needing an explanation outside the frame; readable all day; the turn keeps its width.
- Weak at: the rail is now dense — seven groups in one column. If it feels crowded, the queue/here pair is the first thing that could fold into a single line.
- Risk: hairlines at 1.30 are still subtle by design. If they read as invisible on his panel, the next lever is that number alone, up to his 1.99.
