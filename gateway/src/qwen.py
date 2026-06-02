"""Local abliterated Qwen client (llama.cpp). Synthesizes the draft answer from retrieved
context. Strips the reasoning channel — it must never reach egress."""
from __future__ import annotations

from openai import OpenAI

from .config import config
from .schema import RetrievedChunk

_client = OpenAI(base_url=config.QWEN_BASE_URL, api_key="not-needed")

_SYSTEM = (
    "You are a private, local email-analysis assistant. You answer ONLY from the provided "
    "email excerpts. If the excerpts don't contain the answer, say so plainly. Be concise and "
    "factual. Do not invent senders, amounts, dates, or numbers. Cite which excerpt(s) support "
    "each claim by their [n] index."
)


def _format_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(
            f"[{i}] from={c.sender} date={c.date_iso} folder={c.folder} subject={c.subject}\n"
            f"{c.text}"
        )
    return "\n\n".join(blocks)


def synthesize(query: str, chunks: list[RetrievedChunk]) -> str:
    """Return a plain-text draft answer (pre-sanitization)."""
    if not chunks:
        return "No matching email was found for that query."
    context = _format_context(chunks)
    resp = _client.chat.completions.create(
        model=config.QWEN_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": f"Email excerpts:\n\n{context}\n\nQuestion: {query}\n\n"
                "Answer using only the excerpts above, citing [n] indices.",
            },
        ],
        max_tokens=config.QWEN_MAX_TOKENS,
        temperature=0.3,
    )
    msg = resp.choices[0].message
    # llama.cpp deepseek reasoning split puts thinking in reasoning_content; we drop it.
    content = (msg.content or "").strip()
    if not content:
        # Model spent the budget thinking; retry once with a larger budget and a nudge.
        resp = _client.chat.completions.create(
            model=config.QWEN_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM + " Answer directly; keep thinking brief."},
                {"role": "user", "content": f"Email excerpts:\n\n{context}\n\nQuestion: {query}"},
            ],
            max_tokens=config.QWEN_MAX_TOKENS * 2,
            temperature=0.3,
        )
        content = (resp.choices[0].message.content or "").strip()
    return content or "Unable to produce an answer from the available email."
