"""LanceDB vector + metadata store. Lives entirely inside the container (/data/index)."""
from __future__ import annotations

import hashlib

import lancedb
import pyarrow as pa

from .config import config
from .schema import RetrievedChunk

_SCHEMA = pa.schema(
    [
        pa.field("vector", pa.list_(pa.float32(), config.EMBED_DIM)),
        pa.field("ref_id", pa.string()),
        pa.field("message_id", pa.string()),
        pa.field("sender", pa.string()),
        pa.field("sender_domain", pa.string()),
        pa.field("date_iso", pa.string()),
        pa.field("date_epoch", pa.int64()),
        pa.field("folder", pa.string()),
        pa.field("subject", pa.string()),
        pa.field("text", pa.string()),
        pa.field("chunk_idx", pa.int32()),
    ]
)


def ref_id_for(message_id: str) -> str:
    """Opaque, stable, non-reversible reference for a message (salted hash)."""
    h = hashlib.sha256((config.REF_SALT + "|" + message_id).encode()).hexdigest()
    return h[:16]


def _db():
    return lancedb.connect(config.INDEX_DIR)


def open_or_create():
    db = _db()
    if config.LANCE_TABLE in db.table_names():
        return db.open_table(config.LANCE_TABLE)
    return db.create_table(config.LANCE_TABLE, schema=_SCHEMA)


def add_rows(rows: list[dict]) -> None:
    if not rows:
        return
    tbl = open_or_create()
    tbl.add(rows)


def search(
    vector: list[float],
    top_k: int,
    *,
    sender: str | None = None,
    folder: str | None = None,
    date_from_epoch: int | None = None,
    date_to_epoch: int | None = None,
) -> list[RetrievedChunk]:
    tbl = open_or_create()
    q = tbl.search(vector).metric("cosine").limit(top_k * 4)  # over-fetch for filtering

    clauses: list[str] = []
    if sender:
        s = sender.replace("'", "''").lower()
        clauses.append(f"(lower(sender) LIKE '%{s}%' OR lower(sender_domain) LIKE '%{s}%')")
    if folder:
        f = folder.replace("'", "''")
        clauses.append(f"folder = '{f}'")
    if date_from_epoch is not None:
        clauses.append(f"date_epoch >= {date_from_epoch}")
    if date_to_epoch is not None:
        clauses.append(f"date_epoch <= {date_to_epoch}")
    if clauses:
        q = q.where(" AND ".join(clauses), prefilter=True)

    rows = q.limit(top_k).to_list()
    out: list[RetrievedChunk] = []
    for r in rows:
        out.append(
            RetrievedChunk(
                message_id=r.get("message_id", ""),
                sender=r.get("sender", ""),
                sender_domain=r.get("sender_domain", ""),
                date_iso=r.get("date_iso", ""),
                folder=r.get("folder", ""),
                subject=r.get("subject", ""),
                text=r.get("text", ""),
                chunk_idx=r.get("chunk_idx", 0),
                score=float(r.get("_distance", 0.0)),
            )
        )
    return out
