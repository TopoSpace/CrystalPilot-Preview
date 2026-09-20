"""Interface language for text the server sends to the browser.

The interface is translated in the browser; the few messages the server
composes itself (error details, generated conversation titles, short notes)
follow the same choice. The browser states its language with the
``X-CrystalPilot-Language`` header (or a ``lang`` query parameter where a
header cannot be set); the server binds it to a context variable for the
request, and code that runs outside a request captures ``current()`` first.
"""
from __future__ import annotations

from contextvars import ContextVar, Token

LANGUAGES = ("zh", "en")
DEFAULT = "zh"
HEADER = "X-CrystalPilot-Language"

_current: ContextVar[str] = ContextVar("crystalpilot_language", default=DEFAULT)


def normalize(value: str | None) -> str:
    """Map a header or setting value onto a supported language."""
    if not value:
        return DEFAULT
    code = value.strip().lower().replace("_", "-")
    base = code.split("-", 1)[0]
    return base if base in LANGUAGES else DEFAULT


def current() -> str:
    return _current.get()


def bind(value: str | None) -> Token:
    """Set the language for the current context; pass the token to reset()."""
    return _current.set(normalize(value))


def reset(token: Token) -> None:
    _current.reset(token)


def msg(zh: str, en: str, lang: str | None = None) -> str:
    """Pick the text for ``lang`` (default: the current context's language)."""
    return en if (lang or current()) == "en" else zh
