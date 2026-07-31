"""Minimal self-contained HTML assembly for reporter renders.

Every render in this repo ships self-contained (the hosted surface is only
guaranteed to show the one render file), so images embed as base64 data
URIs. This module is deliberately tiny — sections, tables, embedded PNGs —
not a template engine.
"""

from __future__ import annotations

import base64
import html as _html
from typing import Iterable, Sequence

__all__ = ["embed_png", "page", "section", "table"]

_STYLE = """
body { background: #0d0d0d; color: #c3c2b7; font-family: system-ui, sans-serif;
       margin: 2rem auto; max-width: 70rem; padding: 0 1rem; }
h1, h2 { color: #ffffff; font-weight: 600; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
img { max-width: 100%; height: auto; border-radius: 4px; }
table { border-collapse: collapse; margin: 0.8rem 0; }
th, td { padding: 0.3rem 0.9rem 0.3rem 0; text-align: left;
         border-bottom: 1px solid #2c2c2a; font-size: 0.9rem; }
th { color: #898781; font-weight: 500; }
p { line-height: 1.5; }
""".strip()


def embed_png(png: bytes, alt: str = "") -> str:
    """An ``<img>`` tag with the PNG embedded as a base64 data URI."""
    b64 = base64.b64encode(png).decode("ascii")
    return f'<img src="data:image/png;base64,{b64}" alt="{_html.escape(alt)}">'


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    head = "".join(f"<th>{_html.escape(str(h))}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_html.escape(str(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def section(title: str, *body: str) -> str:
    return f"<h2>{_html.escape(title)}</h2>\n" + "\n".join(body)


def page(title: str, *sections: str) -> str:
    """A complete, self-contained HTML document."""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        f"<meta charset=\"utf-8\">\n<title>{_html.escape(title)}</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        f"<h1>{_html.escape(title)}</h1>\n" + "\n".join(sections) + "\n</body>\n</html>\n"
    )
