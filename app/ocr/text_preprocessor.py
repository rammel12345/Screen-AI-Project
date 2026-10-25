"""OCR text cleanup that preserves line breaks and indentation."""
from __future__ import annotations

import re


def clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def is_effectively_empty(text: str) -> bool:
    """True if there is no real content (only whitespace / stray punctuation)."""
    return not re.search(r"[A-Za-z0-9\u00C0-\uFFFF]", text or "")
