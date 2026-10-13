"""will.I.A. is one endless chat where the chat itself is the memory.

Vendored from the opthermes engine at fc0b13e with the renames and section 8
deletions in docs/ENGINE.md applied. The canon is docs/optchat-gist.md.
"""

from . import prompts, toolkit
from .compactor import COMPACT_CONCURRENCY, CompactionRequest, Compactor, Summarizer
from .notes import import_notes
from .store import KINDS, Log, LogLockedError, Record
from .tree import Line, Tree
from .view import View, ViewStateUnavailable, due

__all__ = [
    "COMPACT_CONCURRENCY", "CompactionRequest", "Compactor", "Summarizer",
    "KINDS", "Line", "Log", "LogLockedError", "Record", "Tree", "View",
    "ViewStateUnavailable", "due", "import_notes", "prompts", "toolkit",
]
