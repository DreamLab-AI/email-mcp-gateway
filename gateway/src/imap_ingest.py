"""Incremental IMAP ingest from the bundled Proton Mail Bridge.

Bridge exposes the decrypted Proton account at IMAP 127.0.0.1:1143 (STARTTLS, self-signed
cert). This crawls each folder, fetching only messages newer than the last seen UID
(per-folder watermark persisted in /data/index/imap_state.json), parses, chunks, embeds via
bge-m3, and upserts into the same LanceDB table as the mbox archive.

Run inside the container:  python -m src.imap_ingest          (incremental)
                           python -m src.imap_ingest --full    (ignore watermarks)
"""
from __future__ import annotations

import argparse
import email
import json
import imaplib
import ssl
import sys
from pathlib import Path

from dateutil import parser as dtparse

from .chunker import chunk_text
from .config import config
from .embeddings import embed
from .mbox_parser import _record_from_message
from .store import add_rows, open_or_create, ref_id_for

_STATE = Path(config.INDEX_DIR) / "imap_state.json"


def _load_state() -> dict:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(state, indent=2))


def _connect() -> imaplib.IMAP4:
    if config.IMAP_STARTTLS:
        m = imaplib.IMAP4(config.IMAP_HOST, config.IMAP_PORT)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # Bridge uses a local self-signed cert
        m.starttls(ssl_context=ctx)
    else:
        m = imaplib.IMAP4(config.IMAP_HOST, config.IMAP_PORT)
    m.login(config.IMAP_USER, config.IMAP_PASS)
    return m


def _list_folders(m: imaplib.IMAP4) -> list[str]:
    typ, data = m.list()
    excl = {x.strip() for x in config.IMAP_EXCLUDE.split(",") if x.strip()}
    folders: list[str] = []
    for raw in data or []:
        line = raw.decode(errors="replace")
        # format: (\HasNoChildren) "/" "Folder Name"
        name = line.split(' "')[-1].strip().strip('"')
        if name and name not in excl:
            folders.append(name)
    return folders


def _epoch(date_iso: str) -> int:
    if not date_iso:
        return 0
    try:
        return int(dtparse.isoparse(date_iso).timestamp())
    except Exception:
        return 0


def run(full: bool = False, batch: int = 256) -> None:
    if not config.IMAP_USER or not config.IMAP_PASS:
        print("ERROR: IMAP_USER/IMAP_PASS not set. Run `protonctl login` then `protonctl info` "
              "and put the address + bridge password in .env.", file=sys.stderr)
        sys.exit(2)

    open_or_create()
    state = {} if full else _load_state()
    m = _connect()
    total_new = 0

    for folder in _list_folders(m):
        try:
            typ, _ = m.select(f'"{folder}"', readonly=True)
            if typ != "OK":
                continue
        except Exception:
            continue
        last_uid = int(state.get(folder, 0))
        typ, data = m.uid("search", None, f"UID {last_uid + 1}:*")
        if typ != "OK" or not data or not data[0]:
            continue
        uids = [int(u) for u in data[0].split() if int(u) > last_uid]
        if not uids:
            continue

        pend_text: list[str] = []
        pend_meta: list[dict] = []
        max_uid = last_uid

        def flush():
            nonlocal pend_text, pend_meta, total_new
            if not pend_text:
                return
            vectors = embed(pend_text)
            add_rows([{"vector": v, **meta} for v, meta in zip(vectors, pend_meta)])
            total_new += len(pend_text)
            pend_text, pend_meta = [], []

        for uid in uids:
            typ, msg_data = m.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            try:
                rec = _record_from_message(email.message_from_bytes(raw), f"proton/{folder}")
            except Exception:
                continue
            max_uid = max(max_uid, uid)
            body = rec.body
            if rec.attachments:
                body += "\n[attachments: " + ", ".join(rec.attachments[:10]) + "]"
            if not body.strip():
                continue
            mid = rec.message_id or f"proton/{folder}/{uid}"
            for idx, ch in enumerate(chunk_text(body)):
                pend_text.append(f"{rec.subject}\n{ch}" if rec.subject else ch)
                pend_meta.append({
                    "ref_id": ref_id_for(mid),
                    "message_id": mid,
                    "sender": rec.sender,
                    "sender_domain": rec.sender_domain,
                    "date_iso": rec.date_iso,
                    "date_epoch": _epoch(rec.date_iso),
                    "folder": f"proton/{folder}",
                    "subject": rec.subject,
                    "text": ch,
                    "chunk_idx": idx,
                })
                if len(pend_text) >= batch:
                    flush()
        flush()
        state[folder] = max_uid
        _save_state(state)
        print(f"  {folder}: up to UID {max_uid}")

    try:
        m.logout()
    except Exception:
        pass
    print(f"\nIMAP ingest complete: {total_new} new chunks indexed.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Incremental Proton (Bridge) IMAP ingest")
    ap.add_argument("--full", action="store_true", help="ignore watermarks, re-crawl all")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args(argv)
    run(full=args.full, batch=args.batch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
