import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('pdf_extract.txt', 'r', encoding='utf-8') as f:
    text = f.read()
text = text.replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
text = text.replace('\u2264', '<=').replace('\u2265', '>=').replace('\u00d7', 'x')

targets = ['SYSTEM_PROMPT', 'SEARCH_MEALS_SQL', 'SEARCH_BY_TEXT_SQL',
           'classify_fast_path', 'build_messages', 'OUTPUT_SCHEMA',
           'render_exercise_candidates', 'render_meal_candidates',
           'sanitize', 'CANDIDATE_LIMIT', 'DEFAULTS',
           'def search_exercises (con', 'def search_meals (con',
           'meal_card', 'pipe', 'DEFINED_TOOLS', 'TOOLS =',
           'fast_path', 'APP_NAME', 'copy:', 'COPY_']

for t in targets:
    idx = 0
    count = 0
    while True:
        idx = text.find(t, idx)
        if idx < 0 or count > 1:
            break
        count += 1
        print(f'=== {t} at pos {idx} ===')
        print(text[max(0,idx-50):idx+800])
        print()
        idx += 1
