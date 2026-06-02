"""Central configuration, sourced from environment (see docker-compose.yml / .env)."""
from __future__ import annotations

import os


def _b(name: str, default: str) -> str:
    return os.getenv(name, default)


class Config:
    # --- Local email-intelligence model (abliterated Qwen via llama.cpp) ---
    QWEN_BASE_URL = _b("QWEN_BASE_URL", "http://host.docker.internal:8080/v1")
    QWEN_MODEL = _b("QWEN_MODEL", "APEX-Q5_K_M.gguf")

    # --- Embeddings (bge-m3 on xinference, OpenAI-compatible) ---
    XINFERENCE_BASE_URL = _b("XINFERENCE_BASE_URL", "http://xinference.local:9997/v1")
    EMBED_MODEL = _b("EMBED_MODEL", "bge-m3")
    EMBED_DIM = int(_b("EMBED_DIM", "1024"))

    # --- In-container privacy filter (gpt-oss-safeguard via llama-cpp-python) ---
    SAFEGUARD_BASE_URL = _b("SAFEGUARD_BASE_URL", "http://127.0.0.1:8081/v1")
    SAFEGUARD_MODEL = _b("SAFEGUARD_MODEL", "gpt-oss-safeguard-20b")

    # --- Proton Mail Bridge (bundled in-container; IMAP source for the live Proton account) ---
    IMAP_HOST = _b("IMAP_HOST", "127.0.0.1")
    IMAP_PORT = int(_b("IMAP_PORT", "1143"))
    IMAP_USER = _b("IMAP_USER", "")        # Proton address; set after `protonctl login`
    IMAP_PASS = _b("IMAP_PASS", "")        # bridge-generated password (from `protonctl info`)
    IMAP_STARTTLS = _b("IMAP_STARTTLS", "1") == "1"
    IMAP_EXCLUDE = _b("IMAP_EXCLUDE", "Trash,Spam,All Mail")  # folders to skip

    # --- Storage ---
    MAIL_DIR = _b("MAIL_DIR", "/data/mail")
    INDEX_DIR = _b("INDEX_DIR", "/data/index")
    POLICY_DIR = _b("POLICY_DIR", "/data/policy")
    LANCE_TABLE = _b("LANCE_TABLE", "email_chunks")

    # --- Egress / privacy ---
    # Salt for opaque ref_id hashing; rotate to invalidate all prior refs.
    REF_SALT = _b("REF_SALT", "change-me-in-env")

    # --- MCP server ---
    MCP_BIND = _b("MCP_BIND", "0.0.0.0:8765")
    MCP_BEARER_TOKEN = _b("MCP_BEARER_TOKEN", "")

    # --- Retrieval / generation ---
    TOP_K = int(_b("TOP_K", "8"))
    CHUNK_CHARS = int(_b("CHUNK_CHARS", "3200"))      # ~800 tokens
    CHUNK_OVERLAP = int(_b("CHUNK_OVERLAP", "400"))
    QWEN_MAX_TOKENS = int(_b("QWEN_MAX_TOKENS", "1536"))  # room for reasoning + answer

    @classmethod
    def host_port(cls) -> tuple[str, int]:
        host, _, port = cls.MCP_BIND.partition(":")
        return host or "0.0.0.0", int(port or "8765")


config = Config()
