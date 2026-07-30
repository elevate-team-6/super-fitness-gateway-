import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('pdf_extract.txt', 'r', encoding='utf-8') as f:
    text = f.read()
text = text.replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
text = text.replace('\u2264', '<=').replace('\u2265', '>=').replace('\u00d7', 'x')

targets = ['SEARCH_EXERCISES_SQL', 'SEARCH_MEALS_SQL', 'search_by_text',
           'SYSTEM_PROMPT', 'FILTER_ORDER', 'ReplyStreamer', 'classify_fast_path',
           'pipe-card', 'build_messages', 'exercise_card', 'meal_card',
           '[exercise_card]', 'table:exercise_card', 'OUTPUT_SCHEMA',
           'SEARCH_BY_TEXT_SQL', 'search_by_text', 'async def chat(',
           'async def handle_chat', 'def build_messages']

for t in targets:
    idx = 0
    count = 0
    while True:
        idx = text.find(t, idx)
        if idx < 0 or count > 2:
            break
        count += 1
        print(f'=== {t} at pos {idx} ===')
        print(text[max(0,idx-50):idx+800])
        print()
        idx += 1
