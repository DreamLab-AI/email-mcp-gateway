# Deployment

> Status: scaffold. The gateway image (`gateway/`) is built in P2/P3; steps below are the
> target operating procedure.

## Prerequisites (already running)

- **Qwen** abliterated model on local llama.cpp at `http://<host>:8080/v1`.
- **xinference** at `http://xinference.local:9997` with **bge-m3** launched (see cache fix below).
- Docker + NVIDIA CDI runtime (`nvidia-ctk` present; `runtime: nvidia`).

## Fixing bge-m3 on xinference

`bge-m3` is a builtin but a partial/corrupt download blocks loading
(`Unrecognized model in .../cache/v2/bge-m3-pytorch-none`). On the xinference host:

```bash
# inside the xinference container
docker exec -it xinference rm -rf /root/.xinference/cache/v2/bge-m3-pytorch-none
# then relaunch from any client:
curl -X POST http://xinference.local:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"bge-m3","model_type":"embedding"}'
```

## gpt-oss-safeguard model

Bundled in the gateway image. GGUF: `lmstudio-community/gpt-oss-safeguard-20b-MXFP4.gguf`
(native MXFP4, ~12 GB, fits 16 GB VRAM). Served in-container via llama.cpp, pinned to GPU1.

## Configuration

Copy `env.template` → `.env` and set (generate with `openssl rand -hex 32`):

```
MCP_BEARER_TOKEN=<long-random-token>
REF_SALT=<long-random-token>   # salts opaque ref_ids; rotating invalidates prior refs
```

`docker-compose.yml` env:
- `QWEN_BASE_URL=http://host.docker.internal:8080/v1`
- `XINFERENCE_BASE_URL=http://xinference.local:9997/v1`, `EMBED_MODEL=bge-m3`
- `MCP_BIND=0.0.0.0:8765`, `SAFEGUARD_IDLE_TTL=900`

Volumes: `./maildata:/data/mail:ro`, `./index:/data/index`, `./policy:/data/policy:ro`.
GPU: pinned to device `1` via CDI.

## Bring-up

```bash
# 1. drop the Thunderbird mbox archive into maildata/ (historical bulk)
# 2. build + ingest the archive (one-time index build)
docker compose run --rm gateway ingest --rebuild
# 3. (Proton) log in to the bundled Bridge once, then ingest the Proton account — see below
# 4. start the on-demand activator (owns public :8765, brings the gateway up on connect)
python3 scripts/activator.py    # or install as a systemd unit
```

## Proton Mail Bridge (bundled in the gateway container)

The live Proton account (`you@proton.me`) is read via Proton Bridge, built into the gateway
image and managed through the docker CLI.

```bash
# bring the gateway up (Bridge starts but is not yet logged in)
docker compose up -d gateway

# one-time interactive login (Proton password + 2FA):
docker exec -it email-mcp-gateway protonctl login
#   > login            # type this, enter address/password, complete 2FA
#   > info             # shows the Bridge IMAP username + generated password
#   > exit

# put the Bridge creds in .env, then recreate:
#   IMAP_USER=<address>     IMAP_PASS=<bridge password from `info`>
docker compose up -d gateway

# crawl the Proton account into the index (full first time, then incremental):
docker compose exec gateway python3 -m src.imap_ingest --full   # initial
docker compose exec gateway python3 -m src.imap_ingest          # incremental (cron/timer)
```

The Bridge vault/keychain persists in `./bridge-data` (gitignored — contains credentials).
Bridge listens on `127.0.0.1:1143` (IMAP) / `:1025` (SMTP) inside the container only.

### Start-on-connect activator
`scripts/activator.py` is a tiny always-on TCP front (no GPU) on `:8765`. On the first client
connection it runs `docker compose up -d gateway`, waits for health, and proxies to the gateway
(`127.0.0.1:8766`). After `IDLE_TTL` (default 900 s) with no connections it `docker compose stop`s
the gateway to free the GPU. Env: `ACTIVATOR_PORT`, `BACKEND_PORT`, `IDLE_TTL`, `COMPOSE_DIR`.

## Register with the Claude CLI (on-demand MCP)

```bash
claude mcp add --transport http email-gateway https://<host>:8765/mcp \
  --header "Authorization: Bearer $MCP_BEARER_TOKEN"
```

First call warms the models (start-on-connect); subsequent calls are fast until idle TTL.

## Health checks

- Qwen reachable (`/v1/models` on :8080)
- xinference bge-m3 reachable (`/v1/models`)
- safeguard loaded
- LanceDB opens
