"""bge-m3 embeddings via the xinference OpenAI-compatible endpoint.

Batches are dispatched concurrently (xinference/A6000 handles parallel requests well), which
is the main ingest throughput lever.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from .config import config

_client = OpenAI(base_url=config.XINFERENCE_BASE_URL, api_key="not-needed", max_retries=4)

_BATCH = 64
_WORKERS = 8


def _embed_batch(batch: list[str]) -> list[list[float]]:
    resp = _client.embeddings.create(model=config.EMBED_MODEL, input=[t[:8000] for t in batch])
    return [d.embedding for d in resp.data]


def embed(texts: list[str], batch_size: int = _BATCH) -> list[list[float]]:
    """Embed a list of texts. Batches run concurrently; output order is preserved."""
    if not texts:
        return []
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    if len(batches) == 1:
        return _embed_batch(batches[0])
    out: list[list[float]] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for result in ex.map(_embed_batch, batches):
            out.extend(result)
    return out


def embed_one(text: str) -> list[float]:
    return _embed_batch([text])[0]
