"""
Jinja2 template environment for resume HTML rendering.

Provides a shared Jinja2 Environment pointed at the templates/resumes/
directory with auto-escaping and helper functions for common patterns.
"""
import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'templates' / 'resumes'
_FONTS_DIR = Path(__file__).resolve().parent.parent / 'static' / 'fonts'

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(['html']),
)


def _font_data_uri(filename: str) -> str:
    """Return a base64 data URI for a WOFF2 font file."""
    font_path = _FONTS_DIR / filename
    if not font_path.is_file():
        return ''
    data = font_path.read_bytes()
    b64 = base64.b64encode(data).decode('ascii')
    return f'data:font/woff2;base64,{b64}'


def _font_face(family: str, filename: str, weight: str = 'normal',
               style: str = 'normal') -> str:
    """Generate a @font-face CSS rule with embedded font data."""
    uri = _font_data_uri(filename)
    if not uri:
        return ''
    return (
        f"@font-face {{\n"
        f"  font-family: '{family}';\n"
        f"  src: url('{uri}') format('woff2');\n"
        f"  font-weight: {weight};\n"
        f"  font-style: {style};\n"
        f"  font-display: swap;\n"
        f"}}\n"
    )


# Register globals available in all templates
_env.globals['font_face'] = lambda *a, **kw: Markup(_font_face(*a, **kw))


def render_template(template_name: str, context: dict) -> str:
    """Render a Jinja2 template with the given context."""
    tmpl = _env.get_template(template_name)
    return tmpl.render(**context)
