"""Parse mail archives into normalized message records.

Handles Unix `mbox` (and many `.mbx` files that are really mbox under the hood) via the
stdlib `mailbox` module, plus a permissive "From "-delimited fallback. True Pegasus-Mail
binary `.mbx` is NOT yet supported — see TODO; the ingest job logs and skips unparseable
files rather than guessing.
"""
from __future__ import annotations

import email
import mailbox
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterator

from bs4 import BeautifulSoup


@dataclass
class MailRecord:
    message_id: str
    sender: str
    sender_domain: str
    to: str
    date_iso: str
    subject: str
    folder: str
    body: str
    attachments: list[str] = field(default_factory=list)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _html_to_text(html: str) -> str:
    try:
        return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    except Exception:
        return html


def _extract_body(msg: Message) -> tuple[str, list[str]]:
    """Prefer text/plain; fall back to stripped HTML. Returns (body, attachment_names)."""
    attachments: list[str] = []
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = (part.get("Content-Disposition") or "").lower()
            ctype = part.get_content_type()
            fname = _decode(part.get_filename())
            if "attachment" in disp or fname:
                if fname:
                    attachments.append(fname)
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace") if payload else ""
        except Exception:
            text = msg.get_payload() or ""
        if msg.get_content_type() == "text/html":
            html_parts.append(text)
        else:
            plain_parts.append(text)

    body = "\n".join(plain_parts).strip()
    if not body and html_parts:
        body = _html_to_text("\n".join(html_parts))
    return body.strip(), attachments


def strip_quotes_and_sigs(body: str) -> str:
    """Drop quoted reply chains and signature blocks to keep embeddings focused."""
    out: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s == "-- ":  # standard sig delimiter
            break
        if s.startswith(">"):
            continue
        if s.lower().startswith(("on ", "le ", "el ")) and "wrote:" in s.lower():
            break  # "On <date>, X wrote:" quote header
        out.append(line)
    return "\n".join(out).strip()


def _record_from_message(msg: Message, folder: str) -> MailRecord:
    sender_raw = _decode(msg.get("From"))
    addrs = getaddresses([msg.get("From", "")])
    sender_email = addrs[0][1] if addrs else ""
    domain = sender_email.split("@", 1)[1].lower() if "@" in sender_email else ""
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        date_iso = dt.isoformat() if dt else ""
    except Exception:
        date_iso = ""
    body, attachments = _extract_body(msg)
    body = strip_quotes_and_sigs(body)
    return MailRecord(
        message_id=_decode(msg.get("Message-ID")) or "",
        sender=sender_raw,
        sender_domain=domain,
        to=_decode(msg.get("To")),
        date_iso=date_iso,
        subject=_decode(msg.get("Subject")),
        folder=folder,
        body=body,
        attachments=attachments,
    )


def iter_mbox_file(path: Path) -> Iterator[MailRecord]:
    """Yield MailRecords from a single mbox/.mbx file."""
    folder = path.stem
    try:
        box = mailbox.mbox(str(path))
    except Exception:
        # permissive fallback: split on "\nFrom " lines
        yield from _fallback_split(path, folder)
        return
    for msg in box:
        try:
            yield _record_from_message(msg, folder)
        except Exception:
            continue


def _fallback_split(path: Path, folder: str) -> Iterator[MailRecord]:
    raw = path.read_bytes()
    if not raw.startswith(b"From "):
        # Likely a binary/Pegasus .mbx we can't parse yet.
        # TODO: implement Pegasus-Mail .mbx binary reader if archives use it.
        return
    chunks = raw.split(b"\nFrom ")
    for i, chunk in enumerate(chunks):
        blob = chunk if i == 0 else b"From " + chunk
        try:
            msg = email.message_from_bytes(blob)
            yield _record_from_message(msg, folder)
        except Exception:
            continue


def iter_mail_dir(root: str) -> Iterator[tuple[Path, MailRecord]]:
    """Walk a directory tree, yielding (source_file, record) for each message."""
    rootp = Path(root)
    for path in sorted(rootp.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".mbx", ".mbox", ""} and path.name.lower() != "mbox":
            continue
        if path.name == "README.md":
            continue
        for rec in iter_mbox_file(path):
            yield path, rec
