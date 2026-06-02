"""Offline ingest: mail dir -> parse -> chunk -> embed (bge-m3) -> LanceDB.

Run inside the container:  python -m src.ingest
Idempotent-ish: re-running appends; use --rebuild to drop the table first.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from dateutil import parser as dtparse
from tqdm import tqdm

from .chunker import chunk_text
from .config import config
from .embeddings import embed
from .mbox_parser import iter_mail_dir
from .store import _db, open_or_create, ref_id_for


def _epoch(date_iso: str) -> int:
    if not date_iso:
        return 0
    try:
        return int(dtparse.isoparse(date_iso).timestamp())
    except Exception:
        return 0


def run(rebuild: bool = False, batch: int = 256) -> None:
    if rebuild:
        db = _db()
        if config.LANCE_TABLE in db.table_names():
            db.drop_table(config.LANCE_TABLE)
            print(f"dropped existing table {config.LANCE_TABLE}")
    open_or_create()

    pending_text: list[str] = []
    pending_meta: list[dict] = []
    n_msgs = 0
    n_chunks = 0

    def flush():
        nonlocal pending_text, pending_meta, n_chunks
        if not pending_text:
            return
        vectors = embed(pending_text)
        rows = []
        for vec, meta in zip(vectors, pending_meta):
            rows.append({"vector": vec, **meta})
        from .store import add_rows

        add_rows(rows)
        n_chunks += len(rows)
        pending_text, pending_meta = [], []

    for _src, rec in tqdm(iter_mail_dir(config.MAIL_DIR), desc="ingest", unit="msg"):
        n_msgs += 1
        body = rec.body
        if rec.attachments:
            body += "\n[attachments: " + ", ".join(rec.attachments[:10]) + "]"
        if not body.strip():
            continue
        chunks = chunk_text(body)
        epoch = _epoch(rec.date_iso)
        for idx, ch in enumerate(chunks):
            pending_text.append(f"{rec.subject}\n{ch}" if rec.subject else ch)
            pending_meta.append(
                {
                    "ref_id": ref_id_for(rec.message_id or f"{_src}:{n_msgs}:{idx}"),
                    "message_id": rec.message_id or f"{_src}:{n_msgs}",
                    "sender": rec.sender,
                    "sender_domain": rec.sender_domain,
                    "date_iso": rec.date_iso,
                    "date_epoch": epoch,
                    "folder": rec.folder,
                    "subject": rec.subject,
                    "text": ch,
                    "chunk_idx": idx,
                }
            )
            if len(pending_text) >= batch:
                flush()
    flush()
    print(f"\ningested {n_msgs} messages -> {n_chunks} chunks into '{config.LANCE_TABLE}'")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Email ingest into LanceDB")
    ap.add_argument("--rebuild", action="store_true", help="drop the table before ingesting")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args(argv)
    run(rebuild=args.rebuild, batch=args.batch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
