"""Plain-language explanations used by the TUI status line and help panel."""

HINTS = {
    "memory": (
        "The memory tree. Every message becomes one line; adjacent lines merge in pairs, "
        "again and again, so each level up covers twice as much as the one below."
    ),
    "l0": (
        "One line per message. This is what the view reads from first."
    ),
    "l1": "Each line here stands for two messages from the level below.",
    "l2": "Each line here stands for four messages from the bottom level.",
    "l3": "Each line here stands for eight messages from the bottom level.",
    "l4": "Each line here stands for sixteen messages from the bottom level.",
    "l5": "Each line here stands for thirty-two messages from the bottom level.",
    "l6": "Each line here stands for sixty-four messages from the bottom level.",
    "l7": (
        "The youngest level: one single line standing in for the whole chat so far. Zoom "
        "descends from here — that is the only way the model navigates its memory."
    ),
    "view": (
        "What the model actually reads on every turn: the whole chat as one-liners, oldest "
        "first, capped at 128 KB. It is rendered BEFORE your message is logged."
    ),
    "queue": (
        "Compactions waiting for a model call. This runs in the background while you talk; "
        "each item here is a node whose parent is ready to merge."
    ),
    "here": "The newest record id. The next thing you type gets the following number.",
    "session": (
        "The chat's session id. The relay pins one upstream backend per id, which is what "
        "keeps the prompt cache warm. It is generated once and never regenerated."
    ),
    "cache": (
        "Share of this turn's prompt that came from the cache instead of being re-sent. This "
        "number is the whole design working — it is why the prompt and tool array never change."
    ),
    "jobs": (
        "Codex delegates running in the background right now. Their reports arrive on their "
        "own, as work records; nothing here waits for them."
    ),
    "go": (
        "OpenCode Go, your chat route: rolling (5h) / weekly / monthly percent of the plan "
        "used. Live from GET /usage — the same call that already feeds this line."
    ),
    "go ↺": (
        "Your OpenCode Go reset countdowns, in the same rolling / weekly / monthly order. "
        "They arrive with the percentages, so checking them costs no extra call."
    ),
    "codex": (
        "Your Codex account's 5-hour and 7-day windows. The payload also tells you whether "
        "the expensive Astra model is available."
    ),
    "codex ↺": (
        "Your Codex reset countdowns, in 5-hour / 7-day order. They arrive with the window "
        "percentages, so checking them costs no extra call."
    ),
    "model": (
        "The model doing the talking. Compactions use the same one — a different model would "
        "forfeit the shared cache prefix."
    ),
    "user": "You. Logged as a user record — the kind the compaction rubric ranks highest.",
    "will": (
        "The reply. Summaries keep little of tool output, so the lines that matter have to be "
        "said here."
    ),
    "reasoning": (
        "The model's thinking. Shown to you, and deliberately NEVER written to the memory — "
        "the log holds only what was said."
    ),
    "tool": (
        "Runs a real tool in the workspace. Its call lands in the log, with long values clipped "
        "before they can flood the screen."
    ),
    "echo": (
        "Tool output is collapsed here because summaries keep so little of it. Unfold it to "
        "see what it actually said."
    ),
    "work": (
        "A delegate's report, arriving on its own as one work record — the only thing a "
        "background job puts in your chat."
    ),
    "note": "An imported note from your memory, hidden from the transcript until you ask to see it.",
    # The rest of the rail's rows. Every row must explain itself: a mute row is a dead end.
    "nodes": (
        "Every line in the tree. Each one was written once by a model and never rewritten, so "
        "this only grows."
    ),
    "bytes": (
        "Current size of the view in bytes. It grows as lines are added until it passes 128 KB, "
        "then compactions trim it back to 64 KB — the sawtooth."
    ),
    "64K-128K": "Where the view sits between the 64 KB floor and the 128 KB ceiling.",
    "state": (
        "Whether every line the view points at has been summarized. The number after it is how "
        "many nodes the drain still has to build, which is the compaction progress."
    ),
    "newest": "The newest record id. The next thing you type becomes the one after it.",
    "resets": (
        "How long until each usage window resets. The provider sends this with the percentages, "
        "so it costs no extra call."
    ),
    "facts": (
        "The machine's own numbers: which chat this is, what the last turn cost, what is running "
        "right now, and what both of the plans have left."
    ),
}


__all__ = ["HINTS"]
