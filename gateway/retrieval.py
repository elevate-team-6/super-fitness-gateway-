import sqlite3
import logging

logger = logging.getLogger("gateway")

SEARCH_EXERCISES_SQL = """
SELECT id, name, name_ar, muscle_group, prime_mover, difficulty, difficulty_rank,
       equipment, mechanics, body_region, movement_patterns
  FROM exercise_card
 WHERE (:muscle_group     IS NULL OR muscle_group      =  :muscle_group)
   AND (:equipment        IS NULL OR equipment         =  :equipment)
   AND (:body_region      IS NULL OR body_region       =  :body_region)
   AND (:mechanics        IS NULL OR mechanics         =  :mechanics)
   AND (:max_difficulty   IS NULL OR difficulty_rank  <= :max_difficulty)
   AND (:movement_pattern IS NULL OR movement_patterns LIKE '%' || :movement_pattern || '%')
   AND (:exclude_equipment IS NULL OR equipment IS NOT :exclude_equipment)
 ORDER BY popularity DESC, difficulty_rank ASC, name ASC
 LIMIT :limit
"""

SEARCH_MEALS_SQL = """
SELECT id, name, name_ar, category, area, kcal, protein_g, carbs_g, fat_g,
       nutrition_is_estimate, nutrition_confidence, vegetarian, vegan, contains_gluten, tags
  FROM meal_card
 WHERE (:category       IS NULL OR category      = :category)
   AND (:area           IS NULL OR area          = :area)
   AND (:min_protein    IS NULL OR protein_g    >= :min_protein)
   AND (:max_kcal       IS NULL OR kcal         <= :max_kcal)
   AND (:vegetarian     IS NULL OR vegetarian    = :vegetarian)
   AND (:vegan          IS NULL OR vegan         = :vegan)
   AND (:gluten_free    IS NULL OR contains_gluten = 0)
   AND (:exclude_ingredient IS NULL OR id NOT IN (
       SELECT meal_id FROM meal_ingredient WHERE ingredient_id = :exclude_ingredient))
 ORDER BY (protein_g IS NULL), protein_g DESC, popularity DESC
 LIMIT :limit
"""

FTS_EXERCISES_SQL = """
SELECT c.id, c.name, c.muscle_group, c.difficulty
  FROM exercise_fts f
  JOIN exercise_card c ON c.id = f.id
 WHERE exercise_fts MATCH :q
 ORDER BY bm25(exercise_fts), c.popularity DESC
 LIMIT :limit
"""

FTS_MEALS_SQL = """
SELECT c.id, c.name, c.category, c.area
  FROM meal_fts f
  JOIN meal_card c ON c.id = f.id
 WHERE meal_fts MATCH :q
 ORDER BY bm25(meal_fts), c.popularity DESC
 LIMIT :limit
"""

DEFAULTS = {
    "muscle_group": None, "equipment": None, "body_region": None,
    "mechanics": None, "max_difficulty": None, "movement_pattern": None,
    "exclude_equipment": None, "limit": 8,
}

MEAL_DEFAULTS = {
    "category": None, "area": None, "min_protein": None, "max_kcal": None,
    "vegetarian": None, "vegan": None, "gluten_free": None,
    "exclude_ingredient": None, "limit": 8,
}

FILTER_ORDER = ["movement_pattern", "mechanics", "body_region",
                "max_difficulty", "equipment", "muscle_group"]

MEAL_FILTER_ORDER = ["area", "max_kcal", "min_protein", "category", "vegetarian", "vegan"]


def sanitize(args: dict) -> dict:
    allowed = {"muscle_group", "equipment", "max_difficulty", "movement_pattern",
               "body_region", "mechanics", "exclude_equipment", "limit",
               "category", "area", "min_protein", "max_kcal", "vegetarian",
               "vegan", "gluten_free", "exclude_ingredient", "query", "domain"}
    cleaned = {}
    for k, v in args.items():
        if k not in allowed:
            continue
        if k in ("max_difficulty", "limit", "min_protein", "max_kcal"):
            try:
                cleaned[k] = int(v)
            except (TypeError, ValueError):
                pass
        elif k in ("vegetarian", "vegan", "gluten_free"):
            if isinstance(v, bool):
                cleaned[k] = 1 if v else 0
            elif isinstance(v, int):
                cleaned[k] = v
        else:
            cleaned[k] = v
    return cleaned


def card_line_exercise(r: sqlite3.Row) -> str:
    parts = [f"id={r['id']}", r["name"]]
    if r["name_ar"]:
        parts.append(r["name_ar"])
    parts += [f"{r['muscle_group']}/{r['prime_mover']}", r["difficulty"],
              r["equipment"], r["body_region"], r["mechanics"],
              r["movement_patterns"] or "-"]
    return " | ".join(str(p) for p in parts)


def card_line_meal(r: sqlite3.Row) -> str:
    est = "yes" if r["nutrition_is_estimate"] else "no"
    conf = r["nutrition_confidence"] or 0
    prot = int(r["protein_g"]) if r["protein_g"] is not None else "?"
    name_ar = r["name_ar"] or ""
    parts = [f"id={r['id']}", r["name"]]
    if name_ar:
        parts.append(name_ar)
    parts += [f"~{prot}g protein", f"est={est} conf={conf}",
              r["category"] or "", r["area"] or ""]
    return " | ".join(str(p) for p in parts)


def render_exercise_candidates(rows: list, relaxed: list) -> str:
    lines = []
    if relaxed:
        lines.append(f"NOTE: no exact match. Relaxed filters: {', '.join(relaxed)}.")
        lines.append("Tell the user what you widened.")
    lines.append("CANDIDATE EXERCISES (cite by id, never invent an id):")
    for r in rows:
        lines.append(card_line_exercise(r))
    return "\n".join(lines)


def render_meal_candidates(rows: list, relaxed: list) -> str:
    lines = []
    if relaxed:
        lines.append(f"NOTE: no exact match. Relaxed filters: {', '.join(relaxed)}.")
        lines.append("Tell the user what you widened.")
    lines.append("CANDIDATE MEALS (macros are per-serving ESTIMATES):")
    for r in rows:
        lines.append(card_line_meal(r))
    return "\n".join(lines)


def search_exercises(con: sqlite3.Connection, **facets) -> tuple:
    params = {**DEFAULTS, **facets}
    relaxed = []
    for _ in range(len(FILTER_ORDER) + 1):
        rows = con.execute(SEARCH_EXERCISES_SQL, params).fetchall()
        if rows:
            return rows, relaxed
        for key in FILTER_ORDER:
            if params.get(key) is not None:
                params[key] = None
                relaxed.append(key)
                break
        else:
            break
    return [], relaxed


def search_meals(con: sqlite3.Connection, **facets) -> tuple:
    params = {**MEAL_DEFAULTS, **facets}
    relaxed = []
    for _ in range(len(MEAL_FILTER_ORDER) + 1):
        rows = con.execute(SEARCH_MEALS_SQL, params).fetchall()
        if rows:
            return rows, relaxed
        for key in MEAL_FILTER_ORDER:
            if params.get(key) is not None:
                params[key] = None
                relaxed.append(key)
                break
        else:
            break
    return [], relaxed


def fts_search(ex_con: sqlite3.Connection, ml_con: sqlite3.Connection,
               query: str, domain: str = "both", limit: int = 8) -> tuple:
    ex_rows = []
    ml_rows = []
    if domain in ("exercise", "both"):
        try:
            ex_rows = ex_con.execute(FTS_EXERCISES_SQL, {"q": query, "limit": limit}).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS exercise query failed: %s", e)
    if domain in ("meal", "both"):
        try:
            ml_rows = ml_con.execute(FTS_MEALS_SQL, {"q": query, "limit": limit}).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS meal query failed: %s", e)
    return ex_rows, ml_rows
