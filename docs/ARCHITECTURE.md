# Architecture

## Components

| Component | Role | Location | Status |
|---|---|---|---|
| **Qwen abliterated** (`qwen3.6-35B-A3B-abliterix`, Q5_K_M) | Email reasoning / answer synthesis | local llama.cpp `:8080` | running, tested |
| **bge-m3** | Embeddings (query + ingest), multilingual, 8k ctx | xinference `xinference.local:9997` | needs launch (cache fix) |
| **gpt-oss-safeguard-20b** (MXFP4) | Egress sanitization to schema + policy labeling | in gateway container, GPU1 | downloading |
| **LanceDB** | Vector + metadata store | in gateway container (`/data/index`) | P1 |
| **MCP gateway** | `ask_email` tool, HTTP+bearer | gateway container `:8765` | P2 |

## Request flow (`ask_email`)

1. Client (Claude CLI) calls `ask_email(query, [filters])` over streamable HTTP + bearer.
2. Gateway embeds the query via bge-m3 (xinference).
3. LanceDB hybrid search (vector + metadata filters: sender / date / folder) → top-k chunks.
4. Gateway assembles context and calls **local Qwen** to synthesize an answer (reasoning-token
   budget handled — Qwen emits a `reasoning_content` channel that must not be returned).
5. **gpt-oss-safeguard** sanitizes Qwen's output to the egress abstraction schema and applies
   the policy (redact / drop). This is the last step before egress.
6. Gateway returns the schema-conformant, abstracted result. No raw mail crosses the boundary.

## Hardware / placement

Host (this box): 2× RTX 6000 Ada (48 GB), 48 cores, 251 GB RAM.
- GPU0: Qwen (~25 GB) + headroom
- GPU1: Qwen (~21 GB) + **gpt-oss-safeguard (~12–16 GB)**, container pinned via CDI `nvidia.com/gpu=1`
- Embeddings run on the xinference box (A6000, ~50 GB free) — no local VRAM cost.

xinference box `xinference.local`: xinference 2.3.0, 3 GPUs (A6000 + Quadro RTX 6000 + …), ~98 GB total VRAM.

## On-demand lifecycle (start-on-connect)

A thin shim brings the compose stack up when the Claude CLI first connects and tears it down
after an idle TTL. Zero standing resource cost when unused; first call pays a warm-up.

## Data pipeline (offline)

Two sources feed one LanceDB index:

**(1) Thunderbird mbox archive (historical bulk, one-time)** — `src/ingest.py`:
`maildata/ → mbox parse (Thunderbird "From - " format; .msf/.dat/.html skipped) → strip
quotes/sigs → attachment text → chunk → embed (bge-m3) → upsert`.

**(2) Proton account via bundled Proton Bridge (incremental)** — `src/imap_ingest.py`:
`Bridge IMAP 127.0.0.1:1143 → per-folder UID watermark (imap_state.json) → fetch new → parse
→ chunk → embed → upsert`. Run periodically (cron/systemd timer) for ongoing mail.

Estimate: ~25 GB raw → ~0.4–1M chunks → ~2–4 GB index.

## Proton Mail Bridge (bundled)

Built from source (`make build-nogui`) into the gateway image; runs headless inside the
container with a `pass`/GPG keychain. Exposes IMAP `127.0.0.1:1143` / SMTP `:1025` (container
-internal only). One-time login via `docker exec -it email-mcp-gateway protonctl login`
(Proton password + 2FA). Vault persists in `./bridge-data` (gitignored — credentials).
