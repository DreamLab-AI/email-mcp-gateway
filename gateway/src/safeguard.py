"""gpt-oss-safeguard egress sanitizer.

Takes Qwen's draft answer + the (internal) retrieved chunks and the written policy, and
produces a schema-conformant, sanitized EgressResult. This is the LAST step before anything
crosses the MCP boundary. On any failure it fails CLOSED (returns a minimal, safe result).
"""
from __future__ import annotations

import json
import re

from openai import OpenAI

from .config import config
from .policy import load_policy, load_schema_instructions
from .schema import EgressResult, Evidence, PolicyLabel, RetrievedChunk
from .store import ref_id_for

_client = OpenAI(base_url=config.SAFEGUARD_BASE_URL, api_key="not-needed")


def _evidence_payload(chunks: list[RetrievedChunk]) -> str:
    items = []
    for c in chunks:
        items.append(
            {
                "ref_id": ref_id_for(c.message_id),
                "sender": c.sender,
                "sender_domain": c.sender_domain,
                "date_iso": c.date_iso,
                "subject": c.subject,
                "excerpt": c.text[:1500],
            }
        )
    return json.dumps(items, ensure_ascii=False)


def _extract_json(raw: str) -> str:
    """gpt-oss emits harmony channels (analysis/final). Depending on the server, `content`
    may contain the raw `<|channel|>final<|message|>…` markup rather than parsed text. Take the
    final channel if present, strip control tokens, and isolate the JSON object."""
    s = raw
    marker = "<|channel|>final<|message|>"
    if marker in s:
        s = s.rsplit(marker, 1)[1]
    s = re.sub(r"<\|[^|]*\|>", "", s)          # drop any remaining harmony control tokens
    a, b = s.find("{"), s.rfind("}")
    return s[a : b + 1] if (a != -1 and b > a) else s.strip()


def _fail_closed(reason: str) -> EgressResult:
    return EgressResult(
        answer="The response was withheld by the privacy filter.",
        evidence=[],
        dropped_count=0,
    )


def sanitize(query: str, draft_answer: str, chunks: list[RetrievedChunk]) -> EgressResult:
    policy = load_policy()
    schema_instr = load_schema_instructions()
    evidence_json = _evidence_payload(chunks)

    system = (
        "You are a privacy egress filter. Apply the POLICY to the assistant's draft answer and "
        "the source excerpts, then output sanitized data per the SCHEMA. Reproduce nothing "
        "verbatim. Use each excerpt's given ref_id.\n\n"
        f"POLICY:\n{policy}\n\nSCHEMA:\n{schema_instr}"
    )
    user = (
        f"USER QUERY:\n{query}\n\n"
        f"ASSISTANT DRAFT (may contain PII to be sanitized):\n{draft_answer}\n\n"
        f"SOURCE EXCERPTS (JSON):\n{evidence_json}\n\n"
        "Produce the sanitized JSON now."
    )

    try:
        # No response_format=json_object: with gpt-oss's harmony template a JSON grammar
        # collides with the channel tokens. We instruct JSON in the prompt and parse the
        # final channel out of the raw output instead.
        resp = _client.chat.completions.create(
            model=config.SAFEGUARD_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=3072,
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(_extract_json(raw))
        result = EgressResult.model_validate(data)
    except Exception as e:  # parse / validation / transport failure -> fail closed
        return _fail_closed(str(e))

    # Defense in depth: recompute dropped_count and guarantee ref_ids are opaque.
    valid_refs = {ref_id_for(c.message_id) for c in chunks}
    cleaned: list[Evidence] = []
    for ev in result.evidence:
        if ev.ref_id not in valid_refs:
            # Drop any evidence whose ref the model invented.
            continue
        if ev.policy_label == PolicyLabel.dropped:
            continue
        cleaned.append(ev)
    dropped = max(len(chunks) - len(cleaned), 0)
    return EgressResult(answer=result.answer, evidence=cleaned, dropped_count=dropped)
