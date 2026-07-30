"""Phase 0a — Capability Check — exact definitions from PDF §3.4 & §3.8"""
import os, json, sys
import requests

# Fix console encoding for Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OLLAMA_BASE_URL = "https://ollama.com"
MODEL_NAME = "gemma4:31b"

# ── Tool definition — exact copy from PDF section 3.4 ──────────────────────
SEARCH_EXERCISES_TOOL = {
    "type": "function",
    "function": {
        "name": "search_exercises",
        "description": "Find exercises in the app's catalog. Use the exact vocabulary values listed in the system prompt. Call this before recommending any exercise.",
        "parameters": {
            "type": "object",
            "properties": {
                "muscle_group": {"type": "string"},
                "equipment": {"type": "string"},
                "max_difficulty": {"type": "integer", "minimum": 1, "maximum": 8,
                    "description": "1=Beginner .. 8=Legendary. Returns everything at or below this level."},
                "movement_pattern": {"type": "string"},
                "body_region": {"type": "string",
                    "enum": ["Upper Body", "Lower Body", "Midsection", "Full Body"]},
                "mechanics": {"type": "string", "enum": ["Compound", "Isolation"]},
                "exclude_equipment": {"type": "string"},
                "limit": {"type": "integer", "default": 6, "maximum": 8}
            },
            "required": []
        }
    }
}

# ── OUTPUT_SCHEMA — exact copy from PDF section 3.8 ────────────────────────
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


def step1_get_api_key() -> str:
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        raise ValueError("OLLAMA_API_KEY is not set or empty")
    return api_key


def step2_check_model(api_key: str) -> bool:
    url = f"{OLLAMA_BASE_URL}/api/tags"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        models = r.json().get("models", [])
        return any(m.get("name") == MODEL_NAME for m in models)
    except Exception as e:
        print(f"  Exception: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response body: {e.response.text[:500]}")
        return False


def step3_test_tool_calls(api_key: str) -> bool:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": "beginner glute exercises, mat only"}],
        "tools": [SEARCH_EXERCISES_TOOL],
        "stream": False
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        tc = msg.get("tool_calls", [])
        if tc and tc[0].get("function", {}).get("name") == "search_exercises":
            return True
        print(f"  Unexpected tool_calls: {json.dumps(tc, indent=2)[:500]}")
        return False
    except Exception as e:
        print(f"  Exception: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response body: {e.response.text[:1000]}")
        return False


def step4_test_structured_output(api_key: str) -> bool:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You must reply with valid JSON only, no other text, matching this schema: "
             '{"type":"object","properties":{"reply":{"type":"string"},"exercise_refs":{"type":"array","items":{"type":"string"}},"meal_refs":{"type":"array","items":{"type":"string"}},"action":{"type":"object","properties":{"type":{"type":"string"},"payload":{"type":"object"}},"required":["type"]},"safety_flag":{"type":"string"}},"required":["reply"]}'},
            {"role": "user", "content": "beginner glute exercises"}
        ],
        "format": "json",
        "stream": False
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        content = msg.get("content", "")
        parsed = json.loads(content)
        return "reply" in parsed and bool(parsed["reply"])
    except Exception as e:
        print(f"  Exception: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response body: {e.response.text[:1000]}")
        return False


def main():
    print("=" * 60)
    print("Phase 0a — Ollama Cloud Capability Check")
    print(f"Model: {MODEL_NAME}")
    print("=" * 60)

    results = []

    # ── Step 1 ──────────────────────────────────────────────────────────────
    print("\n[1/4] OLLAMA_API_KEY … ", end="", flush=True)
    try:
        key = step1_get_api_key()
        print("PASS")
        results.append(("OLLAMA_API_KEY", True, ""))
    except ValueError as e:
        print(f"FAIL — {e}")
        results.append(("OLLAMA_API_KEY", False, str(e)))
        print("\nCannot proceed without an API key. Aborting.")
        print_summary(results)
        sys.exit(1)

    # ── Step 2 ──────────────────────────────────────────────────────────────
    print("[2/4] Model gemma4:31b exists … ", end="", flush=True)
    if step2_check_model(key):
        print("PASS")
        results.append(("model_exists", True, ""))
    else:
        print("FAIL")
        results.append(("model_exists", False, ""))
        print("\n⚠  MODEL NOT AVAILABLE — stop and inform the user.")
        print_summary(results)
        sys.exit(1)

    # ── Step 3 ──────────────────────────────────────────────────────────────
    print("[3/4] Tool calls (search_exercises) … ", end="", flush=True)
    if step3_test_tool_calls(key):
        print("PASS")
        results.append(("tool_calls", True, ""))
    else:
        print("FAIL")
        results.append(("tool_calls", False, ""))

    # ── Step 4 ──────────────────────────────────────────────────────────────
    print("[4/4] Structured output (OUTPUT_SCHEMA) … ", end="", flush=True)
    if step4_test_structured_output(key):
        print("PASS")
        results.append(("structured_output", True, ""))
    else:
        print("FAIL")
        results.append(("structured_output", False, ""))

    # ── Summary ─────────────────────────────────────────────────────────────
    print_summary(results)


def print_summary(results):
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}" + (f"  — {err}" if err else ""))
    print(f"\n  {passed}/{total} passed")
    if passed == total:
        print("\n[OK] All checks passed -- Phase 0a complete.")
    else:
        print("\n[FAIL] Some checks failed -- review above.")
    print("=" * 60)


if __name__ == "__main__":
    main()
