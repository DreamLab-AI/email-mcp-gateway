# Privacy & Security Model

## Trust boundary

The **gateway container is the trust boundary**. Raw mail (`/data/mail`, read-only) and the
LanceDB index (`/data/index`) never leave it. The remote MCP client (Claude Desktop / Code) is
treated as **untrusted** — it receives only schema-bound abstractions.

## Egress = schema-bound abstraction

Every MCP response is sanitized, as the final step, by **gpt-oss-safeguard-20b** to conform to
the egress abstraction schema. The model:
- generalizes / redacts identifiers (senders → roles, exact dates → buckets, amounts → masked/ranged),
- labels each evidence item against the written policy (`ok` / `redacted` / `dropped`),
- never emits verbatim mail.

This is what makes the Anthropic round-trip safe and satisfies "do not use Claude for the email
data" — the cloud client only ever sees abstractions produced locally.

### Egress abstraction schema (straw-man — see PRD §6.1)

```json
{
  "answer": "natural-language answer, sanitized",
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

The schema is the privacy contract; abstraction aggressiveness (date bucketing, sender
generalization, amount masking) is policy-driven and tunable.

## Filter responsibilities

1. **PII redaction on egress** — mask names, addresses, account numbers, etc.
2. **Result-level policy labeling** — classify each retrieved item against policy; drop/flag violations.

## Transport & auth

- Streamable HTTP + **bearer token**; gateway bound to the LAN interface only, never public.
- TLS via self-signed CA or reverse proxy.
- Single-owner, single token in v1. Token in `.env` / secret — never committed.

## At rest

- Archive + index live on the host's LUKS-encrypted volume.
- Container read-only rootfs where feasible; only `/data/index` is writable.

## What is gitignored (never committed)

`*.mbx *.mbox *.eml *.pst`, `maildata/**` (except its README), `index/**`, `*.gguf`,
`*.safetensors`, `.env`, keys/tokens. See `.gitignore`.
