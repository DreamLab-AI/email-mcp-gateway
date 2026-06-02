---
name: email-search
description: >-
  Answer questions about the owner's private personal email archive via the local
  Private Email MCP Gateway. TRIGGER when the user asks anything that requires looking
  in their personal email — "did I get an invoice from X", "when did Y email me about Z",
  "find the thread about my flight", "what's my account number with the bank", "summarize
  what HMRC sent me". The gateway runs locally, reasons over 25GB of mail with a local
  model, and returns ONLY privacy-sanitized, schema-abstracted results — never raw mail.
  SKIP for sending email, calendar, or non-personal/work mailboxes.
---

# Private Email Search (on-demand MCP gateway)

## What this is
A local, self-contained MCP gateway that searches the owner's ~25 GB personal email
archive. All reading and reasoning happen **locally** (abliterated Qwen + bge-m3 retrieval);
an on-box privacy filter (gpt-oss-safeguard) **sanitizes every response to a fixed schema**
before it reaches you. You receive abstractions, never verbatim mail.

> Privacy contract: you (Claude) are an *untrusted* consumer here. The gateway deliberately
> withholds raw email text. Do not ask for, infer around, or try to reconstruct redacted
> content. Work with the abstracted evidence you are given.

## Connection (on-demand)
The gateway is registered as a streamable-HTTP MCP server with bearer auth and connects
**on demand**. If the `ask_email` tool is not currently available, tell the user to bring it
up / register it rather than guessing answers:

```
claude mcp add --transport http email-gateway http://<gateway-host>:8765/mcp \
  --header "Authorization: Bearer <token>"
```

Transport is **plain HTTP + bearer over the trusted LAN** (no TLS unless a reverse proxy is
put in front — use `http://`, not `https://`). The gateway is at the LAN IP of the host that
holds the mail/index (e.g. `http://192.168.2.48:8765/mcp`), reachable from any LAN host that
can route to it. `GET /health` is auth-exempt and returns 200 — use it for readiness checks.
The first query may be slow (models lazy-load). Subsequent queries are fast until idle TTL.

## The only tool: `ask_email`
Use it for ANY personal-email question. Do not fabricate email contents — if `ask_email`
is unavailable or returns nothing, say so.

**Input**
- `query` (required): the natural-language question.
- `date_from`, `date_to` (optional, ISO): bound the search window.
- `sender` (optional): narrow by sender (matched server-side).
- `folder` (optional): e.g. inbox, archive, sent.
- `top_k` (optional): max evidence items (default server-side).

**Output (schema-abstracted — NOT raw mail)**
```json
{
  "answer": "natural-language answer, already sanitized",
  "evidence": [
    {
      "ref_id": "opaque-hash",
      "sender_role": "bank | employer | family | vendor | unknown",
      "period": "2024-Q1",
      "topic": "invoice | travel | medical | legal | ...",
      "abstract": "1-2 sentence sanitized gist, PII masked",
      "policy_label": "ok | redacted | dropped"
    }
  ],
  "dropped_count": 0
}
```

## How to use the result
- Lead with `answer`. Cite supporting `evidence` by `topic` + `period` + `sender_role`
  (e.g. "a vendor invoice from 2024-Q1"). Never present `ref_id` as if it were a real message ID.
- If `dropped_count > 0` or items are `dropped`/`redacted`, tell the user some matches were
  withheld by the privacy policy — do not speculate about their contents.
- If `answer` is empty / `evidence` is empty, report no matching mail was found; offer to
  refine the query or widen the date range. Do not invent details.

## Good vs bad

✅ "Find any invoices from my electricity supplier last winter, with amounts."
→ `ask_email({query:"electricity supplier invoices and amounts", date_from:"2024-11-01", date_to:"2025-03-01"})`

✅ "When did the bank last email me about the mortgage?"
→ `ask_email({query:"mortgage correspondence from the bank", sender:"bank"})`

❌ Do not call `ask_email` to fetch raw email bodies to paste back verbatim — the gateway
will not return them and that defeats the privacy design.
❌ Do not use this for work email, calendar, or to send mail.

## Failure handling
- Tool missing → instruct user to register/start the gateway (see Connection).
- Auth/401 → bearer token is wrong or expired; ask the user to re-provision.
- Timeout on first call → model warming up; retry once.
