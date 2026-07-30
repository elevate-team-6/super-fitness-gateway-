import sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('pdf_extract.txt', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('\u2019', "'").replace('\u2018', "'").replace('\u201c', '"').replace('\u201d', '"')
text = text.replace('\u2264', '<=').replace('\u2265', '>=').replace('\u00d7', 'x')

searches = [
    ('VOCAB_SQL', 'VOCAB_SQL'),
    ('build_vocabulary_block', 'build_vocabulary_block'),
    ('SYSTEM_PROMPT', 'SYSTEM_PROMPT'),
    ('search_exercises tool def', 'search_exercises'),
    ('search_meals tool def', 'search_meals'),
    ('search_by_text tool def', 'search_by_text'),
    ('SEARCH_EXERCISES_SQL', 'SEARCH_EXERCISES_SQL'),
    ('SEARCH_MEALS_SQL', 'SEARCH_MEALS_SQL'),
    ('SEARCH_BY_TEXT_SQL', 'SEARCH_BY_TEXT_SQL'),
    ('FILTER_ORDER', 'FILTER_ORDER'),
    ('card serialization', 'pipe-card'),
    ('ReplyStreamer', 'ReplyStreamer'),
    ('async def chat (two-turn)', 'async def chat'),
    ('async def handle_chat', 'async def handle_chat'),
    ('fast path', 'classify_fast_path'),
    ('fast path', 'fast_path'),
    ('OUTPUT_SCHEMA in context', 'OUTPUT_SCHEMA'),
    ('build_messages', 'build_messages'),
    ('exercise_card', 'exercise_card'),
    ('meal_card', 'meal_card'),
]

found_any = False
for label, term in searches:
    idx = 0
    occurrences = 0
    while True:
        idx = text.find(term, idx)
        if idx < 0:
            break
        occurrences += 1
        if occurrences > 3:
            idx += 1
            continue
        found_any = True
        snippet = text[max(0,idx-80):idx+1200]
        print(f'=== {label} (occ {occurrences} at {idx}) ===')
        print(snippet)
        print()
        idx += 1

if not found_any:
    print("Nothing found. Trying broader search...")
    for term in ['build_vocabulary', 'VOCAB_SQL', 'VOCABULARY', 'SYSTEM_PROMPT', 
                 'FILTER_ORDER', 'ReplyStreamer', 'search_exercises', 'search_meals',
                 'search_by_text', 'fast_path', 'pipe-card', 'build_messages',
                 'exercise_card', 'meal_card']:
        idx = text.find(term)
        if idx >= 0:
            print(f'=== {term} at {idx} ===')
            print(text[max(0,idx-50):idx+500])
            print()
