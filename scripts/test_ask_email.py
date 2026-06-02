#!/usr/bin/env python3
"""External end-to-end test: call the running gateway's `ask_email` MCP tool over
streamable HTTP with a bearer token (a real external call, not an in-process call).

Usage:
  MCP_URL=http://127.0.0.1:8765/mcp MCP_BEARER_TOKEN=... \
    python scripts/test_ask_email.py "Is there anyone called Steven in my emails?"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp")
TOKEN = os.getenv("MCP_BEARER_TOKEN", "")


async def main(query: str) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            print(f"\n>>> ask_email({query!r})\n")
            result = await session.call_tool("ask_email", {"query": query})
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    try:
                        print(json.dumps(json.loads(text), indent=2, ensure_ascii=False))
                    except Exception:
                        print(text)


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Is there anyone called Steven in my emails?"
    asyncio.run(main(q))
