## Variant: Signal, dense (tool-first)

### Design stance
Everything the machine knows, on screen at once, without scrolling to find it. The turn shares the frame with the telemetry it produced.

### Key choices
- Layout: three columns — a compact tree sparkline, the turn, and a telemetry rail (cache read, reasoning tokens, plan windows, jobs, session).
- Typography: 12.5px with 1.5 leading; tighter than variant 1 by design, so more fits above the fold.
- Colour: same cold-blue family, but the accent does more work: every number you'd want to watch is ice-blue, failures are the only red.
- Interaction: reasoning folds; tool output is *inline* rather than collapsed (density is the point); `/` palette stays in the rail.

### Trade-offs
- Strong at: seeing the machine's condition at a glance; comparing turns; watching the cache and the plan windows while you work.
- Weak at: reading long prose; the two side columns eat the centre, and the right rail duplicates what `willia --usage` prints.

### Best for
- You, while building this thing: when the question is "is the cache holding and what is it spending", not "what did it just say".
