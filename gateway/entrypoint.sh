#!/usr/bin/env bash
# Container entrypoint. In `server` mode it boots, in the background:
#   1. Proton Mail Bridge (IMAP 1143 / SMTP 1025) — if enabled and logged in
#   2. gpt-oss-safeguard (llama-cpp-python OpenAI server) on GPU
# then runs the MCP gateway (uvicorn). `ingest` / `imap-ingest` run one-shot jobs.
set -euo pipefail

SAFEGUARD_GGUF="${SAFEGUARD_GGUF:-/models/gpt-oss-safeguard-20b-MXFP4.gguf}"
SAFEGUARD_PORT="${SAFEGUARD_PORT:-8081}"
PROTON_BRIDGE_ENABLED="${PROTON_BRIDGE_ENABLED:-1}"
CMD="${1:-server}"

start_bridge() {
  [[ "$PROTON_BRIDGE_ENABLED" == "1" ]] || { echo "Proton Bridge disabled."; return 0; }
  if [[ ! -f "${PASSWORD_STORE_DIR:-/data/bridge/password-store}/.gpg-id" ]]; then
    echo "WARN: Proton Bridge not logged in yet. Run: docker exec -it <ctr> protonctl login" >&2
  fi
  echo "starting Proton Bridge ..."
  protonctl run &
}

start_safeguard() {
  if [[ ! -f "$SAFEGUARD_GGUF" ]]; then
    echo "WARN: safeguard GGUF not found at $SAFEGUARD_GGUF — egress filter fails closed." >&2
    return 0
  fi
  echo "starting gpt-oss-safeguard on :$SAFEGUARD_PORT ..."
  # No --chat_format: let llama-cpp-python use the GGUF's embedded (harmony) chat template,
  # which is what gpt-oss requires. (Verified working with llama.cpp --jinja on the host.)
  python3 -m llama_cpp.server \
    --model "$SAFEGUARD_GGUF" \
    --model_alias gpt-oss-safeguard-20b \
    --host 127.0.0.1 --port "$SAFEGUARD_PORT" \
    --n_gpu_layers 999 --n_ctx 8192 &
  for i in $(seq 1 60); do
    curl -sf "http://127.0.0.1:${SAFEGUARD_PORT}/v1/models" >/dev/null 2>&1 && { echo "safeguard ready."; return 0; }
    sleep 2
  done
  echo "WARN: safeguard did not come up in time." >&2
}

case "$CMD" in
  ingest)        shift || true; exec python3 -m src.ingest "$@" ;;          # mbox archive
  imap-ingest)   shift || true; exec python3 -m src.imap_ingest "$@" ;;     # Proton via Bridge
  server)
    start_bridge
    start_safeguard
    HOST="${MCP_BIND%%:*}"; PORT="${MCP_BIND##*:}"
    exec uvicorn src.server:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8765}"
    ;;
  *) exec "$@" ;;
esac
