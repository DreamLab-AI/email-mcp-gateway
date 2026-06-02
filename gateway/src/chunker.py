"""Char-based chunking that approximates bge-m3 token windows (8k ctx, but we keep
chunks small for retrieval granularity)."""
from __future__ import annotations

from .config import config


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = size or config.CHUNK_CHARS
    overlap = overlap or config.CHUNK_OVERLAP
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        # try to break on a paragraph/sentence boundary near the end
        if end < n:
            window = text[start:end]
            for sep in ("\n\n", "\n", ". "):
                idx = window.rfind(sep)
                if idx > size * 0.5:
                    end = start + idx + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]
