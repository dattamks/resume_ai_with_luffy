"""
Utility to repair common JSON issues from LLM outputs.

LLMs frequently produce JSON with:
- Trailing commas before } or ]
- Unescaped newlines inside strings
- Truncated output (missing closing braces)
- Control characters
"""

import re


def repair_json(text: str) -> str:
    """
    Attempt to repair common JSON formatting issues produced by LLMs.
    Returns the repaired string (still needs json.loads() after).
    """
    s = text

    # Remove control characters except \n, \r, \t
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)

    # Fix trailing commas: ,} or ,]
    s = re.sub(r',\s*}', '}', s)
    s = re.sub(r',\s*]', ']', s)

    # Fix missing commas between array elements: "value1" "value2" -> "value1", "value2"
    s = re.sub(r'"\s*\n\s*"', '",\n"', s)

    # Balance unclosed braces/brackets (truncated output)
    open_braces = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')

    if open_braces > 0 or open_brackets > 0:
        # Try to find a clean cut point: last complete key-value pair
        # First close any open strings
        in_string = False
        escape_next = False
        for ch in s:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
        if in_string:
            s += '"'

        # Remove any trailing partial key-value pair after last comma
        # This handles cases where the LLM was cut off mid-value
        last_complete = s.rfind(',')
        if last_complete > 0 and open_braces > 0:
            after_comma = s[last_complete + 1:].strip()
            # If what's after the last comma doesn't look complete, remove it
            if after_comma and not after_comma.startswith('}') and not after_comma.startswith(']'):
                # Check if this trailing part has balanced quotes
                quote_count = after_comma.count('"') - after_comma.count('\\"')
                if quote_count % 2 != 0:
                    s = s[:last_complete]

        # Now close remaining open brackets/braces
        open_brackets = s.count('[') - s.count(']')
        open_braces = s.count('{') - s.count('}')
        s += ']' * max(0, open_brackets)
        s += '}' * max(0, open_braces)

    return s
