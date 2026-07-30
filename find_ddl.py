import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('pdf_extract.txt', 'r', encoding='utf-8') as f:
    t = f.read()
t = t.replace('\u2019', "'")

for term in ['CREATE TABLE', 'CREATE VIEW', 'exercise_card AS', 'meal_card AS', 'A.1 exercises.db', 'A.2 meals.db']:
    idx = 0
    count = 0
    while True:
        idx = t.find(term, idx)
        if idx < 0 or count > 3:
            break
        count += 1
        print(f'=== {term} at {idx} ===')
        print(t[max(0,idx-20):idx+1000])
        print()
        idx += 1
