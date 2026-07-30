import sqlite3
import logging

logger = logging.getLogger("gateway")

VOCAB_SQL = """
SELECT (SELECT group_concat(name, ' | ') FROM muscle_group      ORDER BY name) AS muscle_groups,
       (SELECT group_concat(name, ' | ') FROM equipment         ORDER BY name) AS equipment,
       (SELECT group_concat(name, ' | ') FROM movement_pattern  ORDER BY name) AS patterns,
       (SELECT group_concat(name || '=' || rank, ' | ')
          FROM difficulty_level ORDER BY rank)                                 AS difficulty
"""


def build_vocabulary_block(con: sqlite3.Connection) -> str:
    r = con.execute(VOCAB_SQL).fetchone()
    if not r:
        logger.warning("vocabulary SQL returned no rows — falling back to empty block")
        return ""
    return (
        "CATALOG VOCABULARY — use these exact values in tool arguments: \n"
        f"muscle_group: {r['muscle_groups']}\n"
        f"equipment: {r['equipment']}\n"
        f"movement_pattern: {r['patterns']}\n"
        f"max_difficulty (integer): {r['difficulty']}\n"
        f"body_region: Upper Body | Lower Body | Midsection | Full Body \n"
        f"mechanics: Compound | Isolation"
    )
