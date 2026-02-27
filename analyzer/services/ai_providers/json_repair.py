"""
Utility to repair common JSON issues from LLM outputs.

Delegates to the `json-repair` library which handles:
- Trailing commas before } or ]
- Unescaped newlines/control characters inside strings
- Truncated output (missing closing braces/brackets)
- Missing commas between elements
- Single-quoted strings
- Unquoted keys
- And many more edge cases

Previous hand-rolled regex approach was prone to corrupting valid JSON
(e.g., inserting commas between key:value pairs, miscounting braces
inside strings).
"""

from json_repair import repair_json  # noqa: F401 — re-export
