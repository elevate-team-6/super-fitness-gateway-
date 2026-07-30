import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('pdf_extract.txt', 'r', encoding='utf-8') as f:
    t = f.read()
t = t.replace('\u2019', "'")

for term in ['SYSTEM_PROMPT =', 'system_prompt =', 'You are a', 'APP_NAME', 'CATALOG VOCABULARY', 'RELUCTANT']:
    idx = 0
    while True:
        idx = t.find(term, idx)
        if idx < 0:
            break
        print(f'=== {term} at {idx} ===')
        print(t[max(0,idx-30):idx+500])
        print()
        idx += 1
