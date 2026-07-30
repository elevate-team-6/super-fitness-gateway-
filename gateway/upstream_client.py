import os
import random
import asyncio
from contextlib import asynccontextmanager

import httpx


OLLAMA = os.environ.get("OLLAMA_HOST", "https://ollama.com")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:31b")
_ollama_api_key = os.environ.get("OLLAMA_API_KEY")
if not _ollama_api_key:
    raise RuntimeError("OLLAMA_API_KEY is required")
HEADERS = {"Authorization": f"Bearer {_ollama_api_key}"}

MAX_INFLIGHT = int(os.environ.get("OLLAMA_MAX_INFLIGHT", "1"))
QUEUE_DEPTH = int(os.environ.get("OLLAMA_QUEUE_DEPTH", "8"))

_slots = asyncio.Semaphore(MAX_INFLIGHT)
_inflight = 0


class Busy(Exception):
    pass


class QuotaExhausted(Exception):
    pass


class UpstreamDown(Exception):
    pass


class BadCredentials(Exception):
    pass


class UpstreamRejected(Exception):
    pass


def raise_for_upstream(r: httpx.Response) -> None:
    if r.status_code in (401, 403):
        raise BadCredentials(f"{r.status_code}")
    if r.status_code == 429:
        raise QuotaExhausted(r.headers.get("retry-after", ""))
    if r.status_code >= 500:
        raise UpstreamDown(f"{r.status_code}")
    if r.status_code >= 400:
        raise UpstreamRejected(f"{r.status_code}")


@asynccontextmanager
async def upstream_slot():
    global _inflight
    if _inflight >= QUEUE_DEPTH:
        raise Busy()
    _inflight += 1
    try:
        async with _slots:
            yield
    finally:
        _inflight -= 1


async def post_json(path: str, body: dict, attempts: int = 2) -> dict:
    last = None
    for n in range(attempts):
        try:
            async with upstream_slot():
                r = await _client.post(
                    f"{OLLAMA}{path}", headers=HEADERS, json=body
                )
                raise_for_upstream(r)
                return r.json()
        except (UpstreamDown, httpx.RequestError) as e:
            last = e
            if n + 1 < attempts:
                await asyncio.sleep((0.4 * 2**n) + random.uniform(0, 0.2))
    raise UpstreamDown(str(last))


OPTIONS = {
    "temperature": 0.6,
    "top_p": 0.9,
    "repeat_penalty": 1.05,
    "num_predict": 512,
}

_client = httpx.AsyncClient(timeout=30)
