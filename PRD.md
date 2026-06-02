# PRD — Private Email MCP Gateway

**Status:** DRAFT (settling) · **Date:** 2026-06-02 · **Owner:** John

---

## 1. Summary

A single, self-contained Docker container that exposes **one MCP gateway** over the
local network. It lets a remote MCP client (Claude Desktop / Claude Code) ask
natural-language questions about a private 25 GB personal email archive **without
the raw mail ever leaving the local trust boundary**. All reading, retrieval, and
reasoning happen on local/LAN infrastructure; an on-box privacy filter scrubs every
response before it crosses the network.

### Goals
- Natural-language Q&A over ~25 GB of personal email, fully local intelligence.
- Retrieval-augmented answers synthesized by the **local abliterated Qwen** model (never Claude).
- **Egress privacy enforcement**: PII redaction + result-level policy labeling on everything returned.
- Ship as one compose stack; minimal moving parts; pinned to spare local GPU VRAM.

### Non-goals
- No use of Claude / any cloud LLM for email *reasoning or reading* (Claude is only the chat client).
- No write access to mail (read-only archive). No sending email.
- No multi-user / tenancy in v1 (single owner, single bearer token).

---

## 2. Confirmed decisions (from scoping Q&A)

| Area | Decision |
|---|---|
| Email intelligence LLM | **qwen3.6-35B-A3B-abliterix** (`APEX-Q5_K_M.gguf`), local llama.cpp @ `localhost:8080`. Already running, tested OK (~152 tok/s gen). |
| Embedding model | **bge-m3** (1024-dim, 8192-token, multilingual) — downloaded/served on **xinference** `xinference.local:9997`. *(Currently only bge-small-en-v1.5 loaded; needs launch.)* |
| Privacy filter | **gpt-oss-safeguard-20b** (Apache-2.0, BYO-policy classifier, ~16 GB VRAM) — **bundled inside the gateway container**, GPU slice. |
| Filter role | (1) **PII redaction on egress**, (2) **result-level policy labeling** (drop/flag snippets by policy). |
| Vector store | **LanceDB** (embedded, file-based, in-container). |
| MCP interface | **Agentic `ask_email`** only — remote never receives raw mail directly. |
| Transport / auth | **Streamable HTTP + bearer token** over trusted LAN. |
| Email sources | **(1)** Thunderbird **mbox** archive (historical bulk, one-time) dropped in `maildata/`; **(2)** live **Proton account** via **Proton Mail Bridge bundled in the gateway container**, ingested incrementally over IMAP. |
| Proton Bridge | Built from source into the gateway image (v3.25.0), headless, `pass`/GPG keychain, IMAP `127.0.0.1:1143`. Logged in via `docker exec -it … protonctl login`. Vault persisted in `./bridge-data` (gitignored). |
| MCP client | **Claude Desktop / Claude Code** (on another LAN machine). |
| Answer mode | **Schema-abstracted search data** — the container sanitizes every response to a defined schema; the remote Claude agent receives *abstractions, never raw mail*. Safeguard enforces schema conformance + redaction on egress. |

---

## 3. Architecture

```
                 LAN (trusted)
  ┌─────────────────────────┐         ┌──────────────────────────────────────────────┐
  │ Claude Desktop / Code    │  MCP    │            email-mcp-gateway  (Docker)        │
  │ (MCP client)             │ HTTPS   │                                                │
  │                          │ +bearer │  ┌──────────────┐   ask_email()               │
  │  user asks a question ───┼────────►│  │ MCP server   │                              │
  │  ◄── filtered answer     │         │  │ (streamable  │                              │
  └─────────────────────────┘         │  │  HTTP)       │                              │
                                       │  └──────┬───────┘                              │
                                       │         │ 1. embed query (bge-m3)              │
                                       │         ▼                                      │
                                       │  ┌──────────────┐   2. vector+metadata search  │
                                       │  │  LanceDB      │◄──── (sender/date/folder)    │
                                       │  │  (embedded)   │                              │
                                       │  └──────┬───────┘                              │
                                       │         │ 3. top-k snippets                    │
                                       │         ▼                                      │
                                       │  ┌──────────────┐  4. synthesize answer        │
                                       │  │ Qwen (local) │◄──── localhost:8080          │
                                       │  └──────┬───────┘                              │
                                       │         │ 5. answer + citations                │
                                       │         ▼                                      │
                                       │  ┌──────────────────────────┐  6. redact+label │
                                       │  │ gpt-oss-safeguard-20b     │  (in-container,  │
                                       │  │ (PII redaction + policy)  │   GPU1 slice)    │
                                       │  └──────┬───────────────────┘                  │
                                       │         │ 7. FILTERED answer + citations        │
                                       └─────────┼──────────────────────────────────────┘
                                                 ▼  back to client
        xinference @ xinference.local:9997 (bge-m3)  ◄── used at ingest + query time
```

**VRAM placement (this box, 2× RTX 6000 Ada 48 GB):**
- GPU0: Qwen (~25 GB) + headroom (~24 GB free)
- GPU1: Qwen (~21 GB) + **gpt-oss-safeguard-20b (~16 GB)** pinned via CDI `nvidia.com/gpu=1` (~27 GB free — fits)
- Embeddings run remotely on xinference A6000 (~50 GB free) — no local VRAM cost.

---

## 4. Data / ingest pipeline (offline, one-time + optional incremental)

1. **Mount** archive read-only into an ingest job (path/format TBD — see Open Questions).
2. **Parse** mbox/mbx → per-message records: headers (from/to/cc/date/subject/folder/message-id), body (prefer text/plain, fall back to stripped HTML), thread refs.
3. **Clean**: strip quoted reply chains & signatures; decode encodings; handle attachments (default: index filename + extracted text from PDFs/Office/txt, skip binaries — *confirm*).
4. **Chunk**: ~512–1024 token windows w/ overlap; carry message metadata on each chunk.
5. **Embed** each chunk via xinference **bge-m3**; **upsert** into LanceDB with metadata columns for filtering.
6. **Estimate**: ~25 GB raw (attachments inflate this) → est. 100k–300k messages → ~0.4–1M chunks → ~2–4 GB index. Well within 325 GB free.
7. **Incremental** (if archive grows): track message-id watermark; re-embed only new messages.

---

## 5. MCP interface (v1)

**Tool: `ask_email`**
- Input: `query` (string), optional filters: `date_from`, `date_to`, `sender`, `folder`, `top_k`.
- Pipeline: embed → LanceDB hybrid search (+metadata filter) → assemble context → Qwen synthesis (reasoning budget handled) → **safeguard sanitizes to the egress abstraction schema** → return.
- Output: **schema-conformant abstracted result** — NOT raw snippets. The remote Claude agent receives only the abstracted shape defined in §6.1.

*(Possible v2 tools: `list_threads`, `summarize_thread`, `find_attachments` — out of scope for v1.)*

---

## 6. Privacy & security model

- **Trust boundary** = the gateway container. Raw mail + LanceDB index never leave it.
- **Egress = schema-bound abstraction (mandatory, last step):** the container returns only data that conforms to a defined **egress abstraction schema**. gpt-oss-safeguard sanitizes Qwen's output to that schema — generalizing/redacting identifiers and dropping policy-violating content — so the remote Claude agent receives abstractions, never verbatim mail. This is what keeps the Anthropic round-trip privacy-safe and satisfies "do not use Claude for the email data."

### 6.1 Egress abstraction schema (to be defined — see Open Q)
Returned objects are abstractions, e.g. (straw-man, for discussion):
```
{
  "answer": "natural-language answer, sanitized",
  "evidence": [
    {
      "ref_id": "opaque-hash",          // not the real message-id
      "sender_role": "bank | employer | family | vendor | unknown",  // generalized, not the address
      "period": "2024-Q1",              // bucketed, not exact date
      "topic": "invoice | travel | medical | legal | ...",
      "abstract": "1-2 sentence sanitized gist, PII masked",
      "policy_label": "ok | redacted | dropped"
    }
  ],
  "dropped_count": 0
}
```
The schema is the privacy contract. Levels of abstraction (how aggressively to bucket dates, generalize senders, mask amounts) are tunable and policy-driven.
- **Auth**: single bearer token; bind gateway to LAN interface only; TLS (self-signed CA or reverse proxy). No public exposure.
- **At rest**: archive + index on LUKS-encrypted volume (host already LUKS). Container read-only rootfs where possible.
- **Secrets**: bearer token + xinference URL via env/secret, not baked into image.

---

## 7. Deployment

- `docker compose` stack (pattern mirrors existing `~/llm-stack/docker-compose.yml`):
  - service `gateway`: MCP server + LanceDB + bundled gpt-oss-safeguard (llama.cpp or vLLM), `nvidia` runtime, pinned `nvidia.com/gpu=1`, bearer/env config, volume for archive (ro) + index (rw).
- Depends on (external, already up): llama.cpp Qwen @ host `:8080`, xinference @ `xinference.local:9997`.
- Health checks: Qwen reachable, xinference bge-m3 reachable, safeguard loaded, LanceDB open.

---

## 8. Open questions / blockers

1. ~~Email archive path~~ **RESOLVED**: owner drops `.mbx`/`mbox` files into `./maildata/` (host), mounted **read-only** at `/data/mail` in the container; index written to `./index` (rw). Ingest runs after files are present. *(Still useful to confirm exact format — Pegasus `.mbx` vs Unix `mbox` — so the parser is right; can detect at ingest.)*
2. ~~Citation privacy~~ **RESOLVED**: container sanitizes to the egress abstraction schema (§6.1); remote Claude agent receives abstractions only.
3. **Egress abstraction schema**: confirm/tune the §6.1 straw-man — abstraction levels for senders, dates, amounts, topics.
4. **Attachment handling**: index extracted text (PDF/Office) or metadata-only? *Assumed: text-extract common types, skip binaries.*
5. **Safeguard policy content**: which PII categories to redact; which topics to drop/flag. (I'll draft a starter policy.)
6. **Safeguard engine in-container**: llama.cpp (matches existing) vs vLLM (faster, more VRAM). *Leaning llama.cpp for consistency.*
7. **Index freshness**: one-time build acceptable for v1, or need scheduled incremental?
8. ~~On-demand lifecycle~~ **RESOLVED**: **start-on-connect** — a thin shim brings the compose stack up when the Claude CLI first connects and tears it down on idle.

---

## 10. Claude CLI deliverables

### 10.1 Skill writeup
A Claude Code **Skill** (`SKILL.md` + frontmatter) that teaches the Claude CLI when and how to
use the gateway: invoke `ask_email` for any question about personal email, respect the abstracted
schema (never expect raw mail), pass metadata filters, and interpret `policy_label`/`dropped_count`.
Draft lives at `skill/email-search/SKILL.md`.

### 10.2 On-demand MCP for the Claude CLI
The gateway is registered with the Claude CLI as a **streamable-HTTP MCP server + bearer token**,
connected **on demand** (not a persistent always-on cloud link):
- Registration: `claude mcp add --transport http email-gateway https://<host>:<port>/mcp --header "Authorization: Bearer <token>"`.
- On-demand lifecycle options (Open Q #8):
  - **(a) Always-listening, lazy load** — gateway process stays up but gpt-oss-safeguard + Qwen context load on first `ask_email` and idle-unload after a TTL (lowest friction).
  - **(b) Start-on-connect** — a thin stdio/HTTP shim brings the compose stack up when the CLI first connects and tears down on idle (lowest resource use when unused).

---

## 9. Phased plan

- **P0:** ✅ Qwen verified. ✅ bge-m3 launched on xinference (1024-dim). ✅ gpt-oss-safeguard-20b downloaded + smoke-tested (schema-conformant, zero PII leaks).
- **P1:** ✅ **validated on real data** — ingest pipeline → LanceDB. Corpus = **11,785 messages** (Thunderbird mbox: `Local Folders` + `legacy-imap.example`). `.msf`/`.dat`/`.html` correctly skipped. Embedding parallelized (`ThreadPoolExecutor`, 8 workers) for throughput.
- **P2:** ✅ **validated** — retrieval + Qwen synthesis returns accurate, cited answers (a name-lookup test returned a correct, cited profile of the queried person, via external bge-m3 + Qwen calls).
- **P3:** ✅ safeguard egress sanitizer + policy/schema; smoke-tested standalone. *Full `ask_email`-through-MCP-with-safeguard test pending (scripts/test_ask_email.py ready).*
- **P3.5:** ✅ start-on-connect activator (`scripts/activator.py`).
- **P3.6:** ✅ **Docker image builds** (`email-mcp-gateway-gateway:latest`, 16 GB): Proton Bridge v3.25.0 from source (Go 1.26, libfido2), llama-cpp-python w/ CUDA (devel base), MCP server.
- **P4:** ⬜ hardening (TLS, read-only rootfs, health endpoint); Proton Bridge login + incremental IMAP ingest; end-to-end test from Claude Code on a remote machine.

> **Status:** core pipeline validated on real mail; image builds. Remaining: full MCP-through-gateway
> test with safeguard, Proton Bridge interactive login (owner), and production hardening.
