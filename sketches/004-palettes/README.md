## Variant: 001, three palettes (switchable)

### Design stance
The 001 layout is settled; what is switchable is the chroma. Because the TUI is a renderer, a palette is a table of about ten tokens and nothing else — it cannot touch the system prompt, the tool array or the log, so switching themes is free.

### Key choices
- Layout, type, spacing: identical to 001. Nothing moves.
- Blue: the one you picked. Ice-blue agent, near-black navy ground.
- Green: the phosphor register. Same structure, agent in mint, ground tinted green, and `ok` moves to cyan so "settled" stays distinct from the voice.
- Mixed: blue is the app's own voice (chrome, labels, the agent), green is the machine's vitals (tree bars, gauges, every number in the status line). That split is what `--data` exists for.
- Interaction: the three chips at the top swap the palette live — radio inputs and sibling selectors, no JavaScript.

### Trade-offs
- Strong at: taste in ten minutes; one layout to maintain; a palette you dislike costs one CSS block.
- Weak at: mixed is the only one that adds a *meaning* (blue = voice, green = vitals); blue and green are pure taste, so if you want them to differ by more than hue, that has to be decided.

### Best for
- Choosing the chroma without re-litigating the layout.
