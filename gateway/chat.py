import os
import re
import json
import time
import logging
from datetime import datetime, timezone

import httpx

from .upstream_client import (
    OLLAMA, MODEL, HEADERS, OPTIONS,
    Busy, QuotaExhausted, UpstreamDown, BadCredentials, UpstreamRejected,
    upstream_slot, post_json, raise_for_upstream,
)
from .tools import TOOLS
from .retrieval import (
    sanitize, search_exercises, search_meals, fts_search,
    render_exercise_candidates, render_meal_candidates,
)

logger = logging.getLogger("gateway")

SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt_v1.txt")
with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
    _SYSTEM_TEMPLATE = f.read()

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["reply"],
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string",
            "description": "Plain prose in the user's language. No markdown, no URLs, no ids."},
        "exercise_refs": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
        "meal_refs": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
        "action": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string",
                    "enum": ["open_exercise", "open_meal", "open_filtered_list", "start_workout", "none"]},
                "payload": {"type": "object"}
            }
        },
        "safety_flag": {"type": "string",
            "enum": ["none", "medical", "injury", "nutrition_extreme", "off_topic"]}
    }
}

MUSCLE_WORDS = {
    "chest": "Chest", "glute": "Glutes", "glutes": "Glutes",
    "ab": "Abdominals", "abs": "Abdominals", "core": "Abdominals",
    "back": "Back", "shoulder": "Shoulders", "shoulders": "Shoulders",
    "bicep": "Biceps", "biceps": "Biceps", "tricep": "Triceps", "triceps": "Triceps",
    "leg": "Quadriceps", "legs": "Quadriceps", "quad": "Quadriceps",
    "hamstring": "Hamstrings", "calf": "Calves", "calves": "Calves",
}
EQUIP_WORDS = {
    "bodyweight": "Bodyweight", "no equipment": "Bodyweight",
    "at home": "Bodyweight", "mat": "Bodyweight",
    "dumbbell": "Dumbbell", "barbell": "Barbell", "cable": "Cable",
}
DIFF_WORDS = {"beginner": 1, "novice": 2, "intermediate": 3, "advanced": 4}
QUESTION_RE = re.compile(r"\b(why|how|should i|is it|am i|can i|hurt|pain|safe|program|plan)\b", re.I)

CANNED = {
    "quota": {
        "en": "I can't write you a full answer right now, but here's what matches in the catalog.",
        "ar": "لا أستطيع كتابة إجابة كاملة الآن، لكن هذه هي النتائج المتاحة في الكتالوج.",
    },
    "upstream": {
        "en": "I'm having trouble reaching the coach. Here's what matches in the catalog.",
        "ar": "تواجهني مشكلة في الوصول إلى المدرب. هذه هي النتائج المتاحة في الكتالوج.",
    },
}


class ReplyStreamer:
    def __init__(self):
        self.buf = ""
        self._reply_emitted = 0

    def feed(self, piece: str) -> str:
        self.buf += piece
        m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', self.buf)
        if m:
            full = m.group(1)
            new = full[self._reply_emitted:]
            self._reply_emitted = len(full)
            return new
        return ""

    def final(self) -> dict:
        text = self.buf.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        return json.loads(text)


def loc(req: dict) -> str:
    return "ar" if str(req.get("locale", "en")).lower().startswith("ar") else "en"


def classify(message: str) -> dict | None:
    m = message.lower()
    if QUESTION_RE.search(m) or len(m) > 120:
        return None
    facets = {}
    for word, value in MUSCLE_WORDS.items():
        if re.search(rf"\b{word}\w*\b", m):
            facets["muscle_group"] = value
            break
    for word, value in EQUIP_WORDS.items():
        if word in m:
            facets["equipment"] = value
            break
    for word, rank in DIFF_WORDS.items():
        if word in m:
            facets["max_difficulty"] = rank
            break
    return facets if "muscle_group" in facets else None


def _user_context_block(req: dict) -> str:
    uc = req.get("user_context") or {}
    parts = []
    for k in ("name", "age", "weight", "height", "gender", "activity_level", "goal"):
        v = uc.get(k)
        if v is not None:
            parts.append(f"{k}={v}")
    return " | ".join(parts) if parts else ""


def build_messages(req: dict, vocab_block: str, output_schema_str: str,
                   turn_b: bool = False) -> list:
    if turn_b:
        uc_block = _user_context_block(req)
        system = (
            f"You are the in-app fitness coach for Super Fitness.\n\n"
            f"LANGUAGE\nReply in the same language the user wrote in. The user's app locale is {req.get('locale', 'en')}.\n"
            f"For Arabic, use Modern Standard Arabic and give the English name of each exercise in parentheses on first mention.\n\n"
            f"USER PROFILE\n"
            f"level={req.get('profile', {}).get('level', 'beginner')} | "
            f"goal={req.get('profile', {}).get('goal', 'general fitness')} | "
            f"available equipment={req.get('profile', {}).get('equipment', 'bodyweight')} | "
            f"injuries/limits={req.get('profile', {}).get('limits', 'none')} | "
            f"age_band={req.get('profile', {}).get('age_band', 'adult')} | "
            f"units={req.get('profile', {}).get('units', 'metric')}"
        )
        if uc_block:
            system += f"\nUSER CONTEXT\n{uc_block}"
        system += (
            f"\n\nAll necessary tool calls have already been made and their results are shown below.\n"
            f"Do NOT call any tools. Reply only in valid JSON matching this schema:\n"
            f"{output_schema_str}"
        )
    else:
        system = _SYSTEM_TEMPLATE.replace("{locale}", req.get("locale", "en"))
        profile = req.get("profile", {})
        system = system.replace("{level}", str(profile.get("level", "beginner")))
        system = system.replace("{goal}", profile.get("goal", "general fitness"))
        system = system.replace("{equipment}", profile.get("equipment", "bodyweight"))
        system = system.replace("{limits}", profile.get("limits", "none"))
        system = system.replace("{age_band}", profile.get("age_band", "adult"))
        system = system.replace("{units}", profile.get("units", "metric"))
        system = system.replace("{VOCABULARY_BLOCK}", vocab_block)
        uc_block = _user_context_block(req)
        if uc_block:
            system += f"\n\nUSER CONTEXT\n{uc_block}"
        system += f"\n\nOUTPUT SCHEMA — reply must be valid JSON matching this schema:\n{output_schema_str}"

    messages = [{"role": "system", "content": system}]
    for turn in (req.get("history") or []):
        messages.append(turn)
    messages.append({"role": "user", "content": req["message"]})
    return messages


def validate_refs(model_refs: list, candidate_ids: set, con) -> tuple:
    seen, kept, dropped = set(), [], []
    for ref in (model_refs or []):
        if ref in seen:
            continue
        seen.add(ref)
        if ref not in candidate_ids:
            entry = (ref, "not_in_candidate_set")
            dropped.append(entry)
            logger.info("drop ref %s reason=%s", ref, "not_in_candidate_set")
            continue
        row = con.execute(
            "SELECT id, name, name_ar, muscle_group, difficulty, demo_url"
            "  FROM exercise_card WHERE id = ?", (ref,)
        ).fetchone()
        if row is None:
            entry = (ref, "not_in_catalog")
            dropped.append(entry)
            logger.info("drop ref %s reason=%s", ref, "not_in_catalog")
            continue
        kept.append(dict(row))
    return kept, dropped


def validate_meal_refs(model_refs: list, candidate_ids: set, con) -> tuple:
    seen, kept, dropped = set(), [], []
    for ref in (model_refs or []):
        if ref in seen:
            continue
        seen.add(ref)
        if ref not in candidate_ids:
            entry = (ref, "not_in_candidate_set")
            dropped.append(entry)
            logger.info("drop meal_ref %s reason=%s", ref, "not_in_candidate_set")
            continue
        row = con.execute(
            "SELECT id, name, name_ar, category, area, protein_g, kcal"
            "  FROM meal_card WHERE id = ?", (ref,)
        ).fetchone()
        if row is None:
            entry = (ref, "not_in_catalog")
            dropped.append(entry)
            logger.info("drop meal_ref %s reason=%s", ref, "not_in_catalog")
            continue
        kept.append(dict(row))
    return kept, dropped


async def chat(req: dict, ex_con, ml_con, vocab_block: str, output_schema_str: str,
               emit, path_label: str = "two_turn"):
    t0 = time.monotonic()

    # ---- turn A: system with tools; let the model decide what to look up ---
    turn_a_messages = build_messages(req, vocab_block, output_schema_str, turn_b=False)
    turn_a = None
    if path_label == "two_turn":
        turn_a_resp = await post_json("/api/chat", {
            "model": MODEL, "messages": turn_a_messages, "tools": TOOLS,
            "stream": False, "think": False, "options": OPTIONS,
        })
        turn_a = turn_a_resp.get("message", {})

    candidate_ids, tool_blocks = set(), []
    if turn_a and turn_a.get("tool_calls"):
        for call in turn_a["tool_calls"]:
            fn = call["function"]["name"]
            args = call["function"]["arguments"]
            if fn == "search_exercises":
                rows, relaxed = search_exercises(ex_con, **sanitize(args))
                candidate_ids |= {r["id"] for r in rows}
                tool_blocks.append(render_exercise_candidates(rows, relaxed))
            elif fn == "search_meals":
                rows, relaxed = search_meals(ml_con, **sanitize(args))
                candidate_ids |= {r["id"] for r in rows}
                tool_blocks.append(render_meal_candidates(rows, relaxed))
            elif fn == "search_by_text":
                ex_rows, ml_rows = fts_search(ex_con, ml_con, **sanitize(args))
                candidate_ids |= {r["id"] for r in ex_rows} | {r["id"] for r in ml_rows}
                if ex_rows:
                    tool_blocks.append(render_exercise_candidates(ex_rows, []))
                if ml_rows:
                    tool_blocks.append(render_meal_candidates(ml_rows, []))
    elif path_label == "fast_path":
        facets = classify(req["message"]) or {}
        cleaned = sanitize(facets)
        rows, relaxed = search_exercises(ex_con, **{**cleaned, "limit": 6})
        candidate_ids |= {r["id"] for r in rows}
        tool_blocks.append(render_exercise_candidates(rows, relaxed))

    # ---- build turn-B messages: inject candidates directly into system prompt ----
    if tool_blocks:
        candidates_text = "\n\n".join(tool_blocks)
        messages = build_messages(req, vocab_block, output_schema_str, turn_b=True)
        # Prepend candidates info into the system message
        messages[0]["content"] = (
            messages[0]["content"]
            + "\n\n"
            + candidates_text
        )

    # ---- turn B: stream the answer, constrained format -------------------
    streamer, chars = ReplyStreamer(), 0
    final = None

    for attempt in range(2):
        if attempt > 0:
            if chars > 0:
                break
            logger.info("turn B retry attempt %d", attempt + 1)
            streamer = ReplyStreamer()
        try:
            async with upstream_slot():
                async with httpx.AsyncClient(timeout=120) as client:
                    turn_b_opts = {**OPTIONS, "temperature": 0.3} if attempt > 0 else OPTIONS
                    async with client.stream("POST", f"{OLLAMA}/api/chat",
                                             headers=HEADERS, json={
                                "model": MODEL, "messages": messages, "stream": True,
                                "format": OUTPUT_SCHEMA, "think": False, "options": turn_b_opts,
                            }) as resp:
                        raise_for_upstream(resp)
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            if line.startswith("data: "):
                                line = line[6:]
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            piece = data.get("message", {}).get("content", "")
                            if not piece:
                                continue
                            text = streamer.feed(piece)
                            if text:
                                chars += len(text)
                                await emit("token", {"t": text})
            # Streaming succeeded — try to parse
            try:
                final = streamer.final()
                break
            except json.JSONDecodeError:
                if chars == 0 and attempt == 0:
                    logger.info("turn B JSON decode failed, retrying with temp=0.3")
                    continue
                # Non-retryable: model emitted non-JSON after tokens; log and fall through
                break
        except (UpstreamDown, httpx.RequestError):
            if attempt == 0 and chars == 0:
                continue
            raise

    if final is None:
        final = {"reply": "", "exercise_refs": [], "meal_refs": [], "action": {"type": "none"},
                 "safety_flag": "none"}

    kept_ex, dropped = validate_refs(final.get("exercise_refs", []), candidate_ids, ex_con)
    kept_ml, d2 = validate_meal_refs(final.get("meal_refs", []), candidate_ids, ml_con)

    await emit("refs", {
        "exercise_refs": [r["id"] for r in kept_ex],
        "meal_refs": [r["id"] for r in kept_ml],
        "action": final.get("action", {"type": "none"}),
        "snapshots": kept_ex + kept_ml,
    })

    data_version = "2026.07.25"
    await emit("done", {
        "reply_chars": chars,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "data_version": "2026.07.25",
        "dropped_refs": len(dropped) + len(d2),
        "degraded": False,
        "path": path_label,
    })

    # Log turn
    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": req.get("conversation_id", ""),
        "locale": req.get("locale", ""),
        "path": path_label,
        "turn_a_tool": (
            turn_a["tool_calls"][0]["function"]["name"]
            if turn_a and turn_a.get("tool_calls")
            else None
        ),
        "candidate_count": len(candidate_ids),
        "refs_count": len(final.get("exercise_refs", [])) + len(final.get("meal_refs", [])),
        "dropped_refs": len(dropped) + len(d2),
        "reply_chars": chars,
        "safety_flag": final.get("safety_flag", "none"),
        "degraded": False,
    }
    logger.info(json.dumps(log_entry, default=str))

    return {
        "final": final,
        "turn_a": turn_a,
        "candidate_ids": list(candidate_ids),
        "dropped": dropped + d2,
    }


async def chat_degraded(req: dict, ex_con, ml_con, emit, reason: str):
    facets = classify(req["message"]) or {}
    cleaned = sanitize(facets)
    rows, _ = search_exercises(ex_con, **{**cleaned, "limit": 6})
    lang = loc(req)
    line = CANNED.get(reason, CANNED["upstream"])[lang]
    await emit("token", {"t": line})
    await emit("refs", {
        "exercise_refs": [r["id"] for r in rows],
        "meal_refs": [],
        "action": {"type": "open_filtered_list", "payload": facets} if facets else {"type": "none"},
        "snapshots": [dict(r) for r in rows],
    })
    await emit("error", {"code": reason, "message": line, "retryable": reason != "quota"})
    await emit("done", {
        "reply_chars": len(line), "latency_ms": 0,
        "data_version": "2026.07.25", "dropped_refs": 0, "degraded": True,
    })


async def handle_chat(req: dict, ex_con, ml_con, vocab_block: str, output_schema_str: str, emit):
    # Try fast path first
    facets = classify(req["message"])
    path = "fast_path" if facets else "two_turn"
    if path == "fast_path":
        logger.info(json.dumps({"event": "fast_path", "message": req["message"], "facets": facets}))
    try:
        turn_info = await chat(req, ex_con, ml_con, vocab_block, output_schema_str, emit, path_label=path)
        req["_turn_info"] = turn_info
    except Busy:
        await emit("error", {"code": "busy", "message": "The coach is busy, try again.", "retryable": True})
    except QuotaExhausted:
        await chat_degraded(req, ex_con, ml_con, emit, "quota")
    except BadCredentials:
        logger.error("ollama credentials rejected")
        await chat_degraded(req, ex_con, ml_con, emit, "upstream")
    except UpstreamRejected:
        logger.error("upstream rejected our request — malformed tools/format")
        await chat_degraded(req, ex_con, ml_con, emit, "upstream")
    except (UpstreamDown, httpx.HTTPError):
        await chat_degraded(req, ex_con, ml_con, emit, "upstream")
