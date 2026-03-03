"""
Standardized DRF exception handler.

All API error responses follow this contract:

    {
        "detail": "Human-readable summary",
        "errors": { ... }   # optional — field-level validation errors
    }

- `detail` (str): Always present. A single human-readable error message.
- `errors` (dict): Present only for field-level validation errors (400).
  Maps field names to lists of error strings, e.g.
  {"email": ["This field is required."], "password": ["Too short."]}.
- Any *extra* keys passed explicitly by views (e.g. `balance`, `cost`,
  `limit`, `used`) are preserved as-is for frontend consumption.

Why:
    DRF's default handler returns inconsistent shapes:
      - `{"detail": "Not found."}` for 404/403/401
      - `{"field": ["error"]}` for serializer ValidationError
    This handler normalises everything to the shape above so the
    frontend only needs to check `response.data.detail`.
"""

from rest_framework.views import exception_handler as drf_exception_handler


def standardized_exception_handler(exc, context):
    """
    Wraps DRF's default exception handler to ensure all error responses
    contain a top-level `detail` string.

    Field-level validation errors are moved under an `errors` key and
    `detail` is set to a generic summary.
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        # DRF didn't handle it (e.g. unhandled server error) — let Django handle
        return None

    data = response.data

    # ── Already has `detail` as a string → nothing to do ────────────────────
    if isinstance(data, dict) and isinstance(data.get('detail'), str):
        return response

    # ── DRF serializer validation errors: {"field": ["msg", ...], ...} ──────
    if isinstance(data, dict):
        # DRF sometimes puts `detail` as a list (e.g. throttled with extra info)
        if isinstance(data.get('detail'), list):
            response.data = {
                'detail': ' '.join(str(s) for s in data['detail']),
            }
            return response

        # Field-level errors dict  {"field": ["msg"], "non_field_errors": [...]}
        non_field = data.pop('non_field_errors', None)
        if non_field:
            summary = non_field[0] if len(non_field) == 1 else ' '.join(str(s) for s in non_field)
        else:
            # Pick the first field error as the summary
            first_field = next(iter(data), None)
            if first_field and isinstance(data[first_field], list):
                summary = data[first_field][0]
            else:
                summary = 'Validation error.'

        response.data = {
            'detail': str(summary),
            'errors': data,
        }
        return response

    # ── List of errors (rare) ───────────────────────────────────────────────
    if isinstance(data, list):
        response.data = {
            'detail': data[0] if data else 'Validation error.',
            'errors': data,
        }
        return response

    return response
