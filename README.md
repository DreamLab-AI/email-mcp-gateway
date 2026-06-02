# Private Email MCP Gateway

A single, self-contained Docker container that exposes **one MCP gateway** over the local
network, letting a remote MCP client (Claude Desktop / Claude Code) ask natural-language
questions about a private ~25 GB personal email archive — **without the raw mail ever leaving
the local trust boundary**.

All reading and reasoning happen locally; an on-box privacy filter sanitizes every response
to a fixed schema before it crosses the network. The remote agent receives **abstractions,
never verbatim mail**.

> **Status:** core pipeline **validated on real mail** (11,785-message Thunderbird archive).
> Retrieval + local-Qwen synthesis returns accurate cited answers; bge-m3 + gpt-oss-safeguard
> verified; Docker image builds. Remaining: full MCP-through-gateway test with safeguard,
> Proton Bridge interactive login, and production hardening (P4). See [`PRD.md`](PRD.md) §9.

---

## Why

Searching personal email with a cloud LLM means shipping private mail to a third party. This
project keeps the intelligence local — a local abliterated model does the reading, local
retrieval finds the evidence, and a local policy model sanitizes the output — so a cloud client
(Claude) only ever sees structured, privacy-filtered abstractions.

## How it works

```
Claude CLI ──MCP (HTTP+bearer, on-demand)──▶ Gateway container
                                              ├─ embed query        → bge-m3 (xinference, LAN)
                                              ├─ vector search       → LanceDB (in-container)
                                              ├─ synthesize answer   → Qwen abliterated (local :8080)
                                              └─ sanitize to schema  → gpt-oss-safeguard-20b (in-container)
                                                 └▶ abstracted answer + evidence (no raw mail)
```

| Component | Choice |
|---|---|
| Email sources | Thunderbird **mbox** archive (one-time) + live **Proton** account via bundled **Proton Bridge** (incremental IMAP) |
| Email intelligence | `qwen3.6-35B-A3B-abliterix` (local llama.cpp, `:8080`) |
| Embeddings | `bge-m3` (multilingual, 8k ctx) on xinference `xinference.local:9997` |
| Privacy filter | `gpt-oss-safeguard-20b` (BYO-policy, schema-bound egress sanitization), in-container |
| Vector store | LanceDB (embedded) |
| Interface | single MCP tool `ask_email` |
| Transport | streamable HTTP + bearer token, **start-on-connect** |
| Client | Claude Desktop / Claude Code |

See [`PRD.md`](PRD.md) for the full spec and [`docs/`](docs/) for architecture, privacy, and deployment.

## Repository layout

```
.
├── PRD.md                       # full product requirements
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PRIVACY.md
│   └── DEPLOYMENT.md
├── docker-compose.yml           # gateway service (build ./gateway), GPU1, on-demand
├── gateway/                     # gateway image (MCP + safeguard + Proton Bridge)
│   ├── Dockerfile  entrypoint.sh  requirements.txt
│   ├── bridge/                  # Proton Bridge build glue (gpgparams, bridge.sh→protonctl)
│   └── src/                     # config, mbox_parser, chunker, embeddings, store, qwen,
│                                #   safeguard, policy, ingest, imap_ingest, server
├── bridge-data/  → /data/bridge (rw) ← Proton Bridge vault/keychain (gitignored, SECRET)
├── scripts/
│   ├── activator.py             # start-on-connect activator (owns :8765)
│   ├── test_ask_email.py        # external MCP call to ask_email (streamable HTTP + bearer)
│   └── quick_search.py          # local retrieval+synthesis diagnostic against the index
├── policy/     → /data/policy (ro) ← egress_policy.md + egress_schema.txt
├── maildata/   → /data/mail (ro)   ← drop .mbx/mbox here (gitignored)
├── index/      → /data/index (rw)  ← LanceDB (gitignored)
└── skill/email-search/SKILL.md  # Claude CLI skill writeup
```

## Quickstart (target state)

1. Drop your `.mbx` / `mbox` files into [`maildata/`](maildata/README.md).
2. `cp env.template .env` and set `MCP_BEARER_TOKEN` + `REF_SALT`.
3. Build + ingest (P1/P2): `docker compose run --rm gateway ingest`.
4. Register with the Claude CLI:
   ```
   claude mcp add --transport http email-gateway https://<host>:8765/mcp \
     --header "Authorization: Bearer $MCP_BEARER_TOKEN"
   ```
5. Ask: *"Find any invoices from my electricity supplier last winter."*

## Privacy guarantees

- Raw mail and the vector index never leave the container.
- Every MCP response is sanitized to the egress abstraction schema by `gpt-oss-safeguard`.
- No cloud LLM ever reads raw email — Claude (the client) receives abstractions only.
- See [`docs/PRIVACY.md`](docs/PRIVACY.md).
