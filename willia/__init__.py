"""will.I.A. is one endless chat where the chat itself is the memory.

Vendored from the opthermes engine at fc0b13e with the renames and section 8
deletions in docs/ENGINE.md applied. The canon is docs/optchat-gist.md.
"""

from . import client, config, envfile, jobs, prompts, session, toolkit
from .compactor import COMPACT_CONCURRENCY, CompactionRequest, Compactor, Summarizer
from .notes import import_notes
from .store import KINDS, Log, LogLockedError, Record
from .tree import Line, Tree
from .view import View, ViewStateUnavailable, due
from .chat import Chat

__all__ = [
    "Chat", "COMPACT_CONCURRENCY", "CompactionRequest", "Compactor", "Summarizer",
    "KINDS", "Line", "Log", "LogLockedError", "Record", "Tree", "View",
    "ViewStateUnavailable", "client", "config", "due", "envfile", "import_notes",
    "jobs", "prompts", "session", "toolkit",
]
