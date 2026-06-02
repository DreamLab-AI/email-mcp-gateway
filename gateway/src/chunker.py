"""Char-based chunking that approximates bge-m3 token windows (8k ctx, but we keep
chunks small for retrieval granularity)."""
from __future__ import annotations

from .config import config


def chunk_text(
    text: str,
    size: int | None = None,
    overlap: int | None = None,
    max_chunks: int | None = None,
    max_body: int | None = None,
) -> list[str]:
    size = size or config.CHUNK_CHARS
    overlap = overlap or config.CHUNK_OVERLAP
    max_chunks = max_chunks or config.CHUNK_MAX_PER_MSG
    max_body = max_body or config.CHUNK_MAX_BODY_CHARS

    text = text.strip()
    if not text:
        return []
    # Guard: truncate pathological bodies (huge inline/base64 blobs) so one message can't
    # explode into thousands of chunks and wedge the ingest.
    if len(text) > max_body:
        text = text[:max_body]
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n and len(chunks) < max_chunks:
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
