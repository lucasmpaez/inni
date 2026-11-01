#!/usr/bin/env python3
"""Genera index.html (app autonoma) da canti.json + pagine del PDF."""
import json, base64, re, subprocess, sys, unicodedata, os

CANTI, PDF, PAGEDIR, TEMPLATE, OUT = sys.argv[1:6]
canti = json.load(open(CANTI, encoding='utf-8'))

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if c.isalnum())

# prima riga di ogni pagina del PDF
npages = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', PDF], capture_output=True, text=True).stdout).group(1))
first = {}
for p in range(1, npages + 1):
    t = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-layout', PDF, '-'], capture_output=True, text=True).stdout
    ls = [x.strip() for x in t.split('\n') if x.strip()]
    first[p] = ls[0] if ls else ''

# pagina iniziale di ogni canto (in ordine)
p = 1
starts = []
for c in canti:
    key = norm(c['name'] + (c['title'] if c['sub'] and c['name'] != c['title'].upper() else ''))
    key2 = norm(c['title'])
    while p <= npages:
        f = norm(first[p])
        if f.startswith(norm(c['name'])) and (key2 in f or norm(c['name']) == key2 or c['name'].upper() == c['title'].upper()):
            break
        if norm(c['title']) and (f.startswith(key2) or (len(f) > 8 and key2.startswith(f))):
            break
        p += 1
    starts.append(p)
    p += 1
TRAD_PAGES = set()
for q in range(1, npages + 1):
    t = subprocess.run(['pdftotext', '-f', str(q), '-l', str(q), '-layout', PDF, '-'], capture_output=True, text=True).stdout
    ls = [x.strip() for x in t.split('\n') if x.strip()]
    if len(ls) > 1 and ls[1] == 'Traduzione': TRAD_PAGES.add(q)
SECTION_PAGES = {p for p, f in first.items() if f in ('Inni del tempo ordinario', 'Inni di altri tempi liturgici', 'Appendice', 'Preghiere', 'File audio')}
for k, c in enumerate(canti):
    s = starts[k]
    e = (starts[k + 1] if k + 1 < len(canti) else npages) - 1
    pages = [q for q in range(s, e + 1) if q not in SECTION_PAGES and q not in TRAD_PAGES]
    c['page'] = s - 1          # numero stampato nel libretto
    c['pdfpages'] = pages if c['sec'] != 'Preghiere' else []

imgs = {}
for c in canti:
    for q in c['pdfpages']:
        fn = os.path.join(PAGEDIR, 'p-%02d.webp' % q)
        imgs[q] = 'data:image/webp;base64,' + base64.b64encode(open(fn, 'rb').read()).decode()

for c in canti:
    print(c['id'], c['page'], c['pdfpages'], c['title'], file=sys.stderr)

html = open(TEMPLATE, encoding='utf-8').read()
html = html.replace('/*__CANTI__*/null', json.dumps(canti, ensure_ascii=False))
html = html.replace('/*__IMGS__*/null', json.dumps(imgs))
open(OUT, 'w', encoding='utf-8').write(html)
print('ok', len(html) / 1e6, 'MB')
