# Private Email MCP Gateway
# Bundles: MCP server + LanceDB + in-container gpt-oss-safeguard + Proton Mail Bridge.
#
# Stage 1 builds the headless Proton Bridge from source (on bookworm => older glibc, which
# runs fine on the newer ubuntu24.04 runtime). Stage 2 is the CUDA runtime that serves the
# safeguard GGUF and runs the MCP gateway + bundled Bridge.

# ---------- Stage 1: build Proton Bridge (headless) ----------
FROM golang:1.26-bookworm AS bridge-build
ARG BRIDGE_VERSION=v3.25.0
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential pkg-config ca-certificates \
        libsecret-1-dev libfido2-dev libcbor-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${BRIDGE_VERSION} \
        https://github.com/ProtonMail/proton-bridge.git /build
WORKDIR /build
RUN make build-nogui vault-editor

# ---------- Stage 2: runtime ----------
# devel (not runtime) base: nvcc is required to compile llama-cpp-python with CUDA.
FROM nvidia/cuda:12.8.1-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git curl ca-certificates build-essential \
        socat pass gnupg2 libsecret-1-0 libfido2-1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build llama-cpp-python against CUDA for the in-container safeguard model.
ENV CMAKE_ARGS="-DGGML_CUDA=on"
COPY requirements.txt .
RUN python3 -m pip install --break-system-packages -r requirements.txt

# Proton Bridge binaries + control scripts
COPY --from=bridge-build /build/bridge /protonmail/
COPY --from=bridge-build /build/proton-bridge /protonmail/
COPY --from=bridge-build /build/vault-editor /protonmail/
COPY bridge/gpgparams bridge/bridge.sh /protonmail/
RUN chmod +x /protonmail/bridge.sh \
    && ln -s /protonmail/bridge.sh /usr/local/bin/protonctl

# App
COPY src/ ./src/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Bridge keychain/vault persisted here (mount a volume); see compose.
ENV GNUPGHOME=/data/bridge/gnupg \
    PASSWORD_STORE_DIR=/data/bridge/password-store \
    XDG_CONFIG_HOME=/data/bridge/config \
    XDG_DATA_HOME=/data/bridge/data \
    XDG_CACHE_HOME=/data/bridge/cache

VOLUME ["/data/index", "/data/bridge"]
EXPOSE 8765
EXPOSE 1143/tcp 1025/tcp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["server"]
