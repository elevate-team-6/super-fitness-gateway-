import os
import json
import time
import asyncio
import logging
from datetime import datetime, timezone
from collections import defaultdict

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from .upstream_client import (
    OLLAMA, MODEL, HEADERS,
    Busy, QuotaExhausted, UpstreamDown, BadCredentials,
)
from .data import build_vocabulary_block
from .chat import (
    handle_chat, classify,
    OUTPUT_SCHEMA,
)

# ── Pydantic models ──────────────────────────────────────────────────────────
class UserContext(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    gender: Optional[str] = None
    activity_level: Optional[str] = None
    goal: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    user_context: Optional[UserContext] = None
    conversation_id: Optional[str] = ""
    locale: Optional[str] = "en"
    profile: Optional[dict] = {}
    history: Optional[list] = []


logger = logging.getLogger("gateway")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ── DB connections (opened at boot) ──────────────────────────────────────────
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

import sqlite3

_ex_con: sqlite3.Connection | None = None
_ml_con: sqlite3.Connection | None = None
_vocab_block: str = ""
_output_schema_str: str = ""


def _open_dbs():
    global _ex_con, _ml_con, _vocab_block, _output_schema_str
    ex_path = os.path.join(DB_DIR, "exercises.db")
    ml_path = os.path.join(DB_DIR, "meals.db")
    if not os.path.exists(ex_path):
        logger.warning("exercises.db not found at %s", ex_path)
    else:
        _ex_con = sqlite3.connect(ex_path, check_same_thread=False)
        _ex_con.row_factory = sqlite3.Row
        _vocab_block = build_vocabulary_block(_ex_con)
        logger.info("vocabulary block built (%d chars)", len(_vocab_block))
    if not os.path.exists(ml_path):
        logger.warning("meals.db not found at %s", ml_path)
    else:
        _ml_con = sqlite3.connect(ml_path, check_same_thread=False)
        _ml_con.row_factory = sqlite3.Row
    _output_schema_str = json.dumps(OUTPUT_SCHEMA, indent=2)
    logger.info("databases: exercises=%s meals=%s",
                "ok" if _ex_con else "missing",
                "ok" if _ml_con else "missing")


_open_dbs()

app = FastAPI(title="Super Fitness Gateway", version="0.3.0")


def log_turn(req: dict, turn_a: dict | None, candidate_ids: list,
             final_output: dict, dropped: list):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": req.get("conversation_id", ""),
        "locale": req.get("locale", ""),
        "turn_a_duration_ms": turn_a.get("duration_ms") if turn_a else None,
        "turn_a_tool": (
            turn_a["tool_calls"][0]["function"]["name"]
            if turn_a and turn_a.get("tool_calls")
            else None
        ),
        "candidate_count": len(candidate_ids),
        "refs_count": len(final_output.get("exercise_refs", [])) + len(final_output.get("meal_refs", [])),
        "dropped_refs": len(dropped),
        "reply_chars": len(final_output.get("reply", "")),
        "safety_flag": final_output.get("safety_flag", "none"),
        "degraded": False,
    }
    logger.info(json.dumps(entry, default=str))


# ── Auth ─────────────────────────────────────────────────────────────────────
AUTH_ENDPOINT = "https://fitness.elevateegy.com/api/v1/auth/profile-data"


async def verify_user_token(token: str) -> bool:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(AUTH_ENDPOINT, headers=headers)
        if r.status_code == 200:
            return True
        if r.status_code in (401, 403):
            return False
        return False
    except (httpx.RequestError, httpx.TimeoutException):
        return False


# ── Rate limiting ────────────────────────────────────────────────────────────
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "6"))
_rate_store: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(user_id: str) -> tuple[bool, int]:
    now = time.monotonic()
    window = 60.0
    cutoff = now - window
    timestamps = _rate_store[user_id]
    timestamps[:] = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= RATE_LIMIT:
        retry_after = int(window - (now - timestamps[0])) + 1
        return False, retry_after
    timestamps.append(now)
    return True, 0


# ── Healthz ──────────────────────────────────────────────────────────────────
_healthz_cache: tuple[float, dict] | None = None
_HEALTHZ_TTL = 60.0


async def get_healthz() -> dict:
    global _healthz_cache
    now = time.monotonic()
    if _healthz_cache and (now - _healthz_cache[0]) < _HEALTHZ_TTL:
        return _healthz_cache[1]

    db_status = "ok"
    db_detail = []
    if _ex_con:
        try:
            row = _ex_con.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()
            db_detail.append(f"exercises: connected (version={row['value'] if row else '?'})")
        except Exception as e:
            db_status = "degraded"
            db_detail.append(f"exercises: error ({e})")
    else:
        db_status = "degraded"
        db_detail.append("exercises: not connected")

    if _ml_con:
        try:
            row = _ml_con.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()
            db_detail.append(f"meals: connected (version={row['value'] if row else '?'})")
        except Exception as e:
            db_status = "degraded"
            db_detail.append(f"meals: error ({e})")
    else:
        db_status = "degraded"
        db_detail.append("meals: not connected")

    result = {
        "status": db_status,
        "database": {"status": db_status, "detail": "; ".join(db_detail)},
        "upstream": {"status": "unknown"},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA}/api/tags", headers=HEADERS)
        if r.status_code == 200:
            models = r.json().get("models", [])
            model_names = [m.get("name") for m in models]
            if MODEL in model_names:
                result["upstream"] = {"status": "ok", "detail": f"model {MODEL} found"}
            else:
                result["upstream"] = {
                    "status": "degraded",
                    "detail": f"model {MODEL} not in tags list",
                }
        elif r.status_code in (401, 403):
            result["status"] = "degraded"
            result["upstream"] = {"status": "fail", "detail": "API key invalid"}
        else:
            result["status"] = "degraded"
            result["upstream"] = {
                "status": "fail",
                "detail": f"ollama returned {r.status_code}",
            }
    except httpx.RequestError:
        result["status"] = "degraded"
        result["upstream"] = {"status": "fail", "detail": "unreachable"}

    _healthz_cache = (now, result)
    return result


@app.get("/healthz")
async def healthz():
    return await get_healthz()


# ── Chat ─────────────────────────────────────────────────────────────────────
@app.post("/v1/chat")
async def chat_endpoint(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed token")
    token = auth_header.removeprefix("Bearer ")

    is_valid = await verify_user_token(token)
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid token")

    body = await request.json()
    chat_req = ChatRequest(**body)
    user_context = chat_req.user_context.model_dump() if chat_req.user_context else {}
    user_id = token[:16]
    allowed, retry_after = check_rate_limit(user_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    req = {
        "conversation_id": chat_req.conversation_id or "",
        "message": chat_req.message,
        "locale": chat_req.locale or "en",
        "profile": chat_req.profile or {},
        "history": chat_req.history or [],
        "user_context": user_context,
    }

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: str, data: dict):
            await queue.put(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")

        task = asyncio.create_task(
            handle_chat(req, _ex_con, _ml_con,
                        _vocab_block, _output_schema_str, emit)
        )

        while True:
            done = task.done()
            try:
                event_str = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield event_str
            except asyncio.TimeoutError:
                if done:
                    break
                continue

        exc = task.exception()
        if exc:
            logger.error("chat task failed: %s", exc)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
