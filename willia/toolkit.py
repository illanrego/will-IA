"""The fixed tool array for turns and compactions (docs/TOOLS.md sections 2-7)."""

from copy import deepcopy


TOOL_NAMES: tuple[str, ...] = (
    "zoom", "date", "delegate_codex", "delegate_hermes", "web_search", "web_extract", "vision",
    "terminal", "read_file", "write_file", "patch", "search_files",
    "mcp", "skills", "todo",
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
                            "gpt-5.6-sol",
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
    },
    {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Run a shell command and return its output. Use for anything the other tools do not cover.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command line to run."
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Absolute directory to run in (defaults to the workspace)."
                    },
                    "timeout_s": {
                        "type": "integer",
                        "description": "Seconds before the process group is killed (default 120, max 600)."
                    }
                },
                "required": [
                    "command"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file, with line numbers and pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "First line to read, 1-indexed (default 1)."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum lines (default 2000)."
                    }
                },
                "required": [
                    "path"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file, replacing it whole. Writing a new path creates it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "content": {
                        "type": "string"
                    }
                },
                "required": [
                    "path",
                    "content"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patch",
            "description": "Replace one exact string in a file. The old text must appear exactly once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "old_string": {
                        "type": "string"
                    },
                    "new_string": {
                        "type": "string"
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence instead of requiring one (default false)."
                    }
                },
                "required": [
                    "path",
                    "old_string",
                    "new_string"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Find files by name, or search inside files by regular expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "A regex, or a glob such as *.py when target is files."
                    },
                    "target": {
                        "type": "string",
                        "enum": [
                            "content",
                            "files"
                        ],
                        "description": "Search inside files (default), or find files by name."
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search (defaults to the workspace)."
                    },
                    "file_glob": {
                        "type": "string",
                        "description": "Restrict a content search to matching files, e.g. *.py."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default 50)."
                    }
                },
                "required": [
                    "pattern"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mcp",
            "description": "List configured MCP servers and their tools, or call one tool over stdio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "call"
                        ]
                    },
                    "server": {
                        "type": "string"
                    },
                    "name": {
                        "type": "string",
                        "description": "The MCP tool name to call."
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for the MCP tool."
                    }
                },
                "required": [
                    "action"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skills",
            "description": "List available SKILL.md procedures or read one in full.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "read"
                        ]
                    },
                    "name": {
                        "type": "string",
                        "description": "The skill name to read."
                    }
                },
                "required": [
                    "action"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Add, list, complete or drop durable planning items in the chat log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "add",
                            "list",
                            "done",
                            "drop"
                        ]
                    },
                    "text": {
                        "type": "string",
                        "description": "The item text to add."
                    },
                    "id": {
                        "type": "integer",
                        "description": "The item id to complete or drop."
                    }
                },
                "required": [
                    "action"
                ]
            }
        }
    }
]


def schemas() -> list[dict]:
    """Return a fresh deep copy so callers cannot mutate the cache anchor."""
    return deepcopy(_SCHEMAS)
