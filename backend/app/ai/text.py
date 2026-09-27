"""Input normalisation shared by every provider and by the source-text check."""

from __future__ import annotations

import re
import unicodedata

_DIGITS = str.maketrans(
    {
        **{chr(0x0C66 + i): str(i) for i in range(10)},  # Telugu ౦–౯
        **{chr(0x0966 + i): str(i) for i in range(10)},  # Devanagari ०–९
    }
)

MAX_INPUT_CHARS = 4000


def normalise(text: str) -> str:
    """NFC, Telugu/Devanagari digits → ASCII, control characters removed, spaces tidied.

    Only one-to-one character changes happen after NFC, so spans found in the normalised
    text can be shown to the user as-is.
    """
    text = unicodedata.normalize("NFC", text).translate(_DIGITS)
    text = "".join(ch if ch in "\n\t" or unicodedata.category(ch)[0] != "C" else " " for ch in text)
    return re.sub(r"[ \t]+", " ", text).strip()


def appears_in(fragment: str, text: str) -> bool:
    """Whether a quoted fragment really occurs in the input (case- and space-insensitive)."""

    def squash(s: str) -> str:
        return re.sub(r"\s+", " ", normalise(s)).casefold()

    return bool(fragment.strip()) and squash(fragment) in squash(text)
