"""Markdown rendering and sanitization utility for CPJudge.

Safely converts Markdown to HTML and sanitizes output using Bleach.
"""
from markupsafe import Markup
import bleach
import markdown

# Allowed HTML tags for problem statements
ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "div", "span", "br", "hr",
    "pre", "code", "blockquote",
    "strong", "b", "em", "i", "u", "s", "strike", "del",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img",
    "sup", "sub",
]

# Allowed attributes per tag
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "code": ["class"],
    "pre": ["class"],
    "th": ["align", "scope"],
    "td": ["align"],
    "div": ["class"],
    "span": ["class"],
}

# Allowed protocols
ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]


def render_markdown(text: str) -> str:
    """Converts markdown text to safe, sanitized HTML.

    Args:
        text: Raw markdown string.

    Returns:
        Sanitized HTML string safe for rendering with Jinja2 |safe.
    """
    if not text:
        return ""

    # Convert Markdown to HTML with standard extensions (tables, code fences, etc.)
    raw_html = markdown.markdown(
        text,
        extensions=[
            "extra",
            "codehilite",
            "fenced_code",
            "tables",
            "nl2br",
            "sane_lists",
        ],
        output_format="html5",
    )

    # Sanitize HTML using bleach to strip XSS vectors, script tags, onclick handlers, etc.
    clean_html = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )

    # Automatically linkify URLs with rel="noopener noreferrer"
    clean_html = bleach.linkify(clean_html)

    return Markup(clean_html)
