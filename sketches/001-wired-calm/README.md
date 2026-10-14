## Variant: Wired, calm (content-first)

### Design stance
The turn is the only thing that matters; everything else is a hairline at the edge of your vision. Cold blue field, one warm signal, no fills.

### Key choices
- Layout: narrow left rail (the memory ladder), one wide centre column for the turn, a single status line at the bottom.
- Typography: one monospace size, 1.65 leading, generous vertical space; labels are 10px uppercase with wide tracking.
- Colour: near-black navy field, ice-blue agent, dim slate-blue reasoning in a left-ruled gutter, amber reserved for `work` and anything running, red only for failure.
- Interaction: reasoning folds on click (`<details>`), tool output collapses to a summary line, the `/` row is the command palette.

### Trade-offs
- Strong at: reading a long turn; the reasoning/answer separation is unmistakable; feels calm for hours of use.
- Weak at: the tree is decorative at this width; you cannot see the whole memory shape, only the level counts.

### Best for
- Long sessions where most of the screen should be the conversation, and you want the memory's *state* without the memory's *shape*.
