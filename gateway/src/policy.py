"""Loads the safeguard policy + egress schema text from /data/policy.

The policy is the privacy contract gpt-oss-safeguard reasons from (bring-your-own-policy).
"""
from __future__ import annotations

from pathlib import Path

from .config import config

_DEFAULT_POLICY = """\
# Egress Privacy Policy (fallback)
You sanitize email-derived content before it leaves a private boundary to an untrusted
cloud client. Apply these rules:

1. REDACT all direct identifiers: full names, email addresses, phone numbers, postal
   addresses, account/card/IBAN numbers, government IDs, passwords, security codes.
2. GENERALIZE senders to a role (bank, employer, family, friend, vendor, government,
   healthcare, unknown) — never emit the real address or personal name.
3. BUCKET dates to year+quarter (e.g. 2024-Q1). Never emit exact dates.
4. MASK monetary amounts to ranges or "[amount]" unless the user explicitly needs the figure;
   if needed, round to a band.
5. DROP entirely any content in sensitive categories the user has not asked about:
   medical, legal, financial-account, sexual, religious, or political.
6. Never reproduce verbatim email text. Produce only short sanitized abstracts.

Label each evidence item: ok | redacted | dropped.
"""

_DEFAULT_SCHEMA = """\
Return ONLY valid JSON matching:
{
  "answer": string,                      // sanitized natural-language answer
  "evidence": [
    {
      "ref_id": string,                  // copy the opaque ref_id given for each excerpt
      "sender_role": string,             // bank|employer|family|vendor|government|healthcare|unknown
      "period": string,                  // e.g. "2024-Q1"
      "topic": string,                   // e.g. invoice|travel|medical|legal|personal|other
      "abstract": string,                // 1-2 sentence sanitized gist, PII masked
      "policy_label": "ok"|"redacted"|"dropped"
    }
  ],
  "dropped_count": integer
}
No prose outside the JSON.
"""


def load_policy() -> str:
    p = Path(config.POLICY_DIR) / "egress_policy.md"
    return p.read_text() if p.exists() else _DEFAULT_POLICY


def load_schema_instructions() -> str:
    p = Path(config.POLICY_DIR) / "egress_schema.txt"
    return p.read_text() if p.exists() else _DEFAULT_SCHEMA
