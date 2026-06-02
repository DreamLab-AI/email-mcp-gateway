#!/usr/bin/env python3
"""Start-on-connect activator for the Private Email MCP Gateway.

A lightweight, always-listening TCP front (no GPU) that:
  1. listens on the public MCP port (default 8765),
  2. on the first incoming connection, runs `docker compose up -d gateway` and waits for the
     backend to become healthy,
  3. transparently proxies traffic to the backend (127.0.0.1:BACKEND_PORT),
  4. after IDLE_TTL seconds with no connections, runs `docker compose stop gateway` to free
     the GPU.

This realizes the "start-on-connect" lifecycle for the HTTP MCP transport: zero GPU cost when
idle, automatic bring-up when the Claude CLI connects.

Run on the host (e.g. via a tiny systemd unit):  python3 scripts/activator.py
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time

LISTEN_HOST = os.getenv("ACTIVATOR_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("ACTIVATOR_PORT", "8765"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8766"))
IDLE_TTL = int(os.getenv("IDLE_TTL", "900"))
COMPOSE_DIR = os.getenv("COMPOSE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_lock = asyncio.Lock()
_active = 0
_last_activity = time.monotonic()


def _compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=COMPOSE_DIR, check=False)


async def _backend_healthy() -> bool:
    try:
        r, w = await asyncio.open_connection(BACKEND_HOST, BACKEND_PORT)
        w.close()
        await w.wait_closed()
        return True
    except OSError:
        return False


async def ensure_up() -> None:
    async with _lock:
        if await _backend_healthy():
            return
        print("[activator] bringing gateway up ...", flush=True)
        await asyncio.to_thread(_compose, "up", "-d", "gateway")
        for _ in range(120):  # up to ~4 min for model warm-up
            if await _backend_healthy():
                print("[activator] gateway ready.", flush=True)
                return
            await asyncio.sleep(2)
        print("[activator] WARN: gateway did not become healthy.", flush=True)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    global _active, _last_activity
    _active += 1
    _last_activity = time.monotonic()
    try:
        await ensure_up()
        backend_r, backend_w = await asyncio.open_connection(BACKEND_HOST, BACKEND_PORT)
        await asyncio.gather(_pipe(client_r, backend_w), _pipe(backend_r, client_w))
    except OSError as e:
        print(f"[activator] proxy error: {e}", flush=True)
        client_w.close()
    finally:
        _active -= 1
        _last_activity = time.monotonic()


async def idle_reaper() -> None:
    while True:
        await asyncio.sleep(30)
        if _active == 0 and (time.monotonic() - _last_activity) > IDLE_TTL:
            if await _backend_healthy():
                print("[activator] idle TTL reached — stopping gateway.", flush=True)
                await asyncio.to_thread(_compose, "stop", "gateway")
            _last_activity = time.monotonic()


async def main() -> None:
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    asyncio.create_task(idle_reaper())
    print(f"[activator] listening on {LISTEN_HOST}:{LISTEN_PORT} -> "
          f"{BACKEND_HOST}:{BACKEND_PORT} (idle TTL {IDLE_TTL}s)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
