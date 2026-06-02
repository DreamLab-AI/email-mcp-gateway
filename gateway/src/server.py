"""MCP gateway: a single `ask_email` tool over streamable HTTP, bearer-authenticated.

Pipeline per call:  embed query -> LanceDB search (+filters) -> Qwen synth -> safeguard
sanitize -> schema-conformant EgressResult. Raw mail never crosses this boundary.
"""
from __future__ import annotations

import logging

from dateutil import parser as dtparse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import embeddings, qwen, safeguard, store
from .config import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")

# Transport security: the SDK defaults to DNS-rebinding protection ON with an empty allow-list,
# which rejects LAN clients (non-localhost Host header). On a trusted LAN with bearer auth we
# turn it off by default; set MCP_ALLOWED_HOSTS to re-enable strict Host/Origin validation.
_allowed = [h.strip() for h in config.MCP_ALLOWED_HOSTS.split(",") if h.strip()]
if _allowed:
    _sec = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed,
        allowed_origins=_allowed,
    )
else:
    _sec = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "email-gateway",
    host=config.host_port()[0],
    port=config.host_port()[1],
    transport_security=_sec,
)


def _epoch(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        return int(dtparse.parse(date_str).timestamp())
    except Exception:
        return None


@mcp.tool()
def ask_email(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    sender: str | None = None,
    folder: str | None = None,
    top_k: int | None = None,
) -> dict:
    """Ask a natural-language question about the owner's private email archive.

    Returns a privacy-sanitized, schema-abstracted result (answer + abstracted evidence).
    Never returns raw email. Use optional filters to narrow by date/sender/folder.
    """
    k = top_k or config.TOP_K
    vec = embeddings.embed_one(query)
    chunks = store.search(
        vec,
        k,
        sender=sender,
        folder=folder,
        date_from_epoch=_epoch(date_from),
        date_to_epoch=_epoch(date_to),
    )
    if not chunks:
        return {"answer": "No matching email was found.", "evidence": [], "dropped_count": 0}
    draft = qwen.synthesize(query, chunks)
    result = safeguard.sanitize(query, draft, chunks)
    return result.model_dump_mcp()


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject any request without the configured bearer token."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        token = config.MCP_BEARER_TOKEN
        if not token:
            return JSONResponse({"error": "server missing MCP_BEARER_TOKEN"}, status_code=500)
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def _health(request: Request):
    """Auth-exempt liveness probe for orchestrators (returns 200 once the app is serving).
    Reports whether the index opens and whether deps are configured (cheap, no model calls)."""
    try:
        rows = store.open_or_create().count_rows()
        index_ok = True
    except Exception:
        rows, index_ok = 0, False
    return JSONResponse(
        {
            "status": "ok",
            "service": "email-mcp-gateway",
            "index_ok": index_ok,
            "indexed_chunks": rows,
            "tools": ["ask_email"],
        }
    )


def build_app():
    """Streamable-HTTP ASGI app with bearer auth wrapped around the MCP transport,
    plus an auth-exempt GET /health route."""
    from starlette.routing import Route

    app = mcp.streamable_http_app()
    app.router.routes.append(Route("/health", _health, methods=["GET"]))
    app.add_middleware(BearerAuthMiddleware)  # /health is exempted inside the middleware
    return app


# uvicorn entrypoint: `uvicorn src.server:app`
app = build_app()


if __name__ == "__main__":
    import uvicorn

    host, port = config.host_port()
    uvicorn.run(app, host=host, port=port)
