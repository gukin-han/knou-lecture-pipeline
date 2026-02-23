from __future__ import annotations

import re

# Korean sentence-ending patterns (마침표, 느낌표, 물음표 + optional closing brackets/quotes)
_SENTENCE_END = re.compile(r"""[.!?][)\]"']*\s+""")


def split_into_chunks(text: str, chunk_size: int = 6000, overlap: int = 200) -> list[str]:
    """
    Split text into chunks of at most `chunk_size` characters, preferring
    sentence boundaries.  Adjacent chunks share `overlap` characters so
    the LLM has context across boundaries.

    Strategy:
    1. Try to split at the last sentence boundary before `chunk_size`.
    2. If no sentence boundary is found within the window, fall back to the
       last whitespace character.
    3. If there is no whitespace either, hard-cut at `chunk_size`.
    """
    if not text:
        return []

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            # Last chunk — take everything that's left
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Try to find the last sentence boundary in the window
        window = text[start:end]
        best_cut = _find_sentence_boundary(window)

        if best_cut is None:
            # Fall back to last whitespace
            last_ws = window.rfind(" ")
            best_cut = last_ws if last_ws > 0 else chunk_size

        # best_cut is relative to `start`
        chunk = text[start : start + best_cut].strip()
        if chunk:
            chunks.append(chunk)

        # Advance, keeping `overlap` characters from the end of this chunk
        advance = best_cut - overlap
        if advance <= 0:
            advance = best_cut  # safety: always move forward
        start += advance

    return chunks


def _find_sentence_boundary(text: str) -> int | None:
    """
    Return the index *just after* the last sentence-ending punctuation in
    `text`, or None if no boundary was found.
    """
    best: int | None = None
    for m in _SENTENCE_END.finditer(text):
        best = m.end()
    return best


def continuation_hint(previous_chunk: str, n_chars: int = 300) -> str:
    """Return the last `n_chars` of the previous chunk as a context hint."""
    return previous_chunk[-n_chars:].strip() if previous_chunk else ""
