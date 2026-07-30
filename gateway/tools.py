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

SEARCH_MEALS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_meals",
        "description": "Find meals in the app's catalog. Use the exact vocabulary values listed in the system prompt. Call this before recommending any meal.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "area": {"type": "string"},
                "min_protein": {"type": "integer", "minimum": 0},
                "max_kcal": {"type": "integer", "minimum": 0},
                "vegetarian": {"type": "boolean"},
                "vegan": {"type": "boolean"},
                "gluten_free": {"type": "boolean"},
                "exclude_ingredient": {"type": "string"},
                "limit": {"type": "integer", "default": 6, "maximum": 8}
            },
            "required": []
        }
    }
}

SEARCH_BY_TEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "search_by_text",
        "description": "Search exercises or meals by free text. Use when the user's query doesn't map cleanly to the structured fields of search_exercises/search_meals.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                    "description": "Free-text search terms in the user's language."},
                "domain": {"type": "string", "enum": ["exercise", "meal", "both"],
                    "description": "Which catalog to search."},
                "limit": {"type": "integer", "default": 6, "maximum": 8}
            },
            "required": ["query"]
        }
    }
}

TOOLS = [SEARCH_EXERCISES_TOOL, SEARCH_MEALS_TOOL, SEARCH_BY_TEXT_TOOL]
