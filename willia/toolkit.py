"""The fixed tool array for turns and compactions (docs/TOOLS.md sections 2-7)."""

from copy import deepcopy


TOOL_NAMES: tuple[str, ...] = (
    "zoom", "date", "delegate_codex", "delegate_hermes", "web_search", "web_extract", "vision",
)

# Section 4 defines delegate_hermes as delegate_codex minus model/dir;
# its description is consequently preserved verbatim too.
_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "zoom",
            "description": "Open a child chat by name, a chat span, or a raw message. Without scope, an integer id resolves against the chat whose view you are reading; a returned child chat names the scope its ids resolve with.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "anyOf": [
                            {
                                "type": "integer"
                            },
                            {
                                "type": "string"
                            }
                        ]
                    },
                    "n": {
                        "type": "integer"
                    },
                    "scope": {
                        "type": "string",
                        "description": "A subagent's name: resolve the id against that child's chat instead of the chat whose view you are reading."
                    }
                },
                "required": [
                    "id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "date",
            "description": "Get the stored ISO timestamp of a raw message, from the chat whose view you are reading or from the subagent's chat named by scope.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer"
                    },
                    "scope": {
                        "type": "string",
                        "description": "A subagent's name: read the id from that child's chat instead of the chat whose view you are reading."
                    }
                },
                "required": [
                    "id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_codex",
            "description": "Spawn a Codex coding agent on a task, in the background, and get its report later as a work message. Use for code, tests, builds, refactors. It has its own shell and works in the given directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The full brief: what to do, where, and how to prove it."
                    },
                    "dir": {
                        "type": "string",
                        "description": "Absolute working directory (defaults to the configured workspace)."
                    },
                    "model": {
                        "type": "string",
                        "enum": [
                            "gpt-6-sol",
                            "gpt-6-astra"
                        ],
                        "description": "sol for most tasks; astra only where precision matters more than cost."
                    },
                    "name": {
                        "type": "string",
                        "description": "Short label for this child, used by zoom(\"Name\") and in the report's [Name] tag."
                    }
                },
                "required": [
                    "task"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_hermes",
            "description": "Spawn a Codex coding agent on a task, in the background, and get its report later as a work message. Use for code, tests, builds, refactors. It has its own shell and works in the given directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The full brief: what to do, where, and how to prove it."
                    },
                    "name": {
                        "type": "string",
                        "description": "Short label for this child, used by zoom(\"Name\") and in the report's [Name] tag."
                    }
                },
                "required": [
                    "task"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns titles, URLs and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Results to return (default 5, max 10)."
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_extract",
            "description": "Fetch pages and return their text, one entry per URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "maxItems": 5
                    },
                    "char_limit": {
                        "type": "integer",
                        "description": "Per-page character budget (default 15000)."
                    }
                },
                "required": [
                    "urls"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "vision",
            "description": "Look at an image (a local path or an http(s) URL) and answer a question about it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "A local file path or an http(s) URL."
                    },
                    "question": {
                        "type": "string"
                    }
                },
                "required": [
                    "image_url",
                    "question"
                ]
            }
        }
    }
]


def schemas() -> list[dict]:
    """Return a fresh deep copy so callers cannot mutate the cache anchor."""
    return deepcopy(_SCHEMAS)
