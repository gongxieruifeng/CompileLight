"""Chinese-friendly FTS5 document and query preparation."""

from __future__ import annotations

import re

_HAN = re.compile(r"[\u3400-\u9fff]+")
_ASCII = re.compile(r"[a-zA-Z0-9_]+")


def build_search_text(parts: list[str]) -> str:
    """Add Han bi/tri-grams so FTS5 can match short Chinese task terms."""
    text = " ".join(parts).lower()
    tokens = _ordered_unique(_ASCII.findall(text))
    for sequence in _HAN.findall(text):
        tokens.extend(_han_ngrams(sequence))
    return " ".join(_ordered_unique(tokens))


def build_match_query(text: str, *, max_terms: int = 32) -> str | None:
    """Build a safely quoted OR query from task text."""
    lowered = text.lower()
    tokens = _ASCII.findall(lowered)
    for sequence in _HAN.findall(lowered):
        tokens.extend(_han_ngrams(sequence))
    useful = [token for token in _ordered_unique(tokens) if len(token) >= 2]
    if not useful:
        return None
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in useful[:max_terms])


def lexical_overlap(query: str, phrases: list[str]) -> int:
    """Count explicit phrase hits used for transparent metadata tie-breaking."""
    lowered = query.lower()
    return sum(1 for phrase in phrases if phrase.lower() in lowered)


def _han_ngrams(sequence: str) -> list[str]:
    tokens: list[str] = []
    for size in (2, 3, 4):
        if len(sequence) < size:
            continue
        tokens.extend(
            sequence[index : index + size]
            for index in range(len(sequence) - size + 1)
        )
    return tokens


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
