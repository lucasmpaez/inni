#!/usr/bin/env python3
"""Estrae canti e preghiere da libro.ly in canti.json."""
import re, json, sys, unicodedata

SRC = sys.argv[1]
OUT = sys.argv[2]
SEZ = {'sec_to': "Inni del tempo ordinario", 'sec_lit': "Inni di altri tempi liturgici",
       'sec_cant': "Cantici e altri inni", 'sec_app': "Appendice", 'sec_pre': "Preghiere"}
QS = r'"((?:[^"\\]|\\.)*)"'

def unq(s): return s.replace('\\"', '"').replace('\\\\', '\\')

def vowel_groups(w):
    w = unicodedata.normalize('NFD', w.lower())
    w = ''.join(c for c in w if c.isalpha())
    return max(1, len(re.findall(r'[aeiouy]+', w)))

def est_syll(line):
    return sum(vowel_groups(w) for w in line.split())

def parse_lyrics(body):
    """Testo sotto la partitura (sillabe) -> {numero: [parole]}"""
    body = re.sub(r'\\override\s+\S+\s*=\s*#\'?\S+', ' ', body)
    toks = re.findall(r'\\set stanza = "(\d+)\."|(\\markup)|("(?:[^"\\]|\\.)*"|\S+)', body)
    stanzas = {}; cur = None; words = []; join = False
    def flush():
        if cur is not None and words: stanzas[cur] = words[:]
    for num, mk, t in toks:
        if num:
            flush(); cur = int(num); words = []; join = False; continue
        if mk or not t: continue
        if t in ('_', '__', '{', '}'): continue
        if t == '--': join = True; continue
        if t.startswith('\\'): continue
        if cur is None: cur = 0
        t = unq(t.strip('"')).replace('~', '\u0001')
        if join and words:
            words[-1] = (words[-1][0] + t, words[-1][1] + 1)
        else:
            words.append((t, 1))
        join = False
    flush()
    return stanzas

def parse_tone_lyrics(body):
    """Testo sotto il tono salmodico (\\markup \\concat {...})"""
    m = re.search(r'\\set stanza = "(\d+)\."', body)
    n = int(m.group(1)) if m else None
    parts = re.split(r'\\markup', body)[1:]
    out = ''
    for p in parts:
        s = ''.join(unq(x) for x in re.findall(QS, p))
        if out.endswith('-'): out = out[:-1] + s
        elif out: out += ' ' + s
        else: out = s
    out = re.sub(r'\s+', ' ', out).strip()
    lines = [l.strip() for l in re.split(r'(?<=[,;:.])\s+', out) if l.strip()]
    return n, lines

def break_lines(words, target_lines):
    """Divide la strofa 1 (dalla partitura) in versi, usando la metrica della strofa 2."""
    text_words = [w.replace('\u0001', ' ') for w, _ in words]
    syl = [s for _, s in words]
    if not target_lines or len(target_lines) < 2:
        return [' '.join(text_words)]
    est = [est_syll(l) for l in target_lines]
    total = sum(syl); tot_est = sum(est)
    cum = []; acc = 0
    for e in est[:-1]:
        acc += e; cum.append(acc / tot_est * total)
    breaks = []; start = 0
    pref = [0]
    for s in syl: pref.append(pref[-1] + s)
    for c in cum:
        best = None
        for i in range(start + 1, len(words)):
            d = abs(pref[i] - c)
            if text_words[i - 1][-1:] in ',;:.!?': d -= 1.6
            if best is None or d < best[0]: best = (d, i)
        if best is None: break
        breaks.append(best[1]); start = best[1]
    lines = []; prev = 0
    for b in breaks + [len(words)]:
        lines.append(' '.join(text_words[prev:b])); prev = b
    return [l for l in lines if l]

def parse_text_markup(line):
    """\\markup \\testo ... -> lista di blocchi {n, lines:[{t,mark,it,rub}]}"""
    blocks = []
    cur = None
    pending_mark = None
    for m in re.finditer(r'(\\italic\s+(?:\\override #\(cons \(quote line-width\) [\d.]+\)\s+)?(?:\\justify-string|\\wordwrap-string)?\s*)?' + QS, line):
        s = unq(m.group(2)); pre = line[max(0, m.start() - 60):m.start()]
        it = bool(m.group(1)) or bool(re.search(r'\\italic\s*$', pre))
        if re.fullmatch(r'\d+\.', s) and '0.35 0.35 0.35' in pre:
            cur = {'n': int(s[:-1]), 'lines': []}; blocks.append(cur); continue
        if s in ('℣.', '℟.'):
            pending_mark = s[0]; continue
        rub = bool(re.search(r'0\.72 0\.1 0\.1\)\s*(\\italic\s*)?$', pre)) and not pending_mark
        if cur is None:
            cur = {'n': None, 'lines': []}; blocks.append(cur)
        ln = {'t': s}
        if it: ln['it'] = 1
        if rub: ln['rub'] = 1
        if pending_mark: ln['mark'] = pending_mark; pending_mark = None
        cur['lines'].append(ln)
    return blocks

def main():
    src = open(SRC, encoding='utf-8').read()
    lines = src.split('\n')
    sec = None; items = []; cur = None; mode = None
    i = 0
    started = False
    while i < len(lines):
        l = lines[i].strip()
        m = re.match(r"\\label #'(sec_\w+)", l)
        if m:
            if m.group(1) in SEZ: sec = m.group(1); started = True
            i += 1; continue
        if not started or sec is None: i += 1; continue
        if l.startswith('\\markup \\sezione') or 'File audio' in l:
            i += 1; continue
        m = re.match(r'\\markup \\titolo ' + QS, l)
        t15 = l.startswith('\\markup \\column { \\abs-fontsize #15')
        if m or t15:
            raw = unq(m.group(1)) if m else ' '.join(unq(x) for x in re.findall(QS, l))
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
            def nm(x): return ''.join(ch for ch in unicodedata.normalize('NFD', x.lower()) if ch.isalpha())
            if cur and nm(raw.split('@@')[0]) in (nm(cur['name']), nm(cur['incipit'])):
                if nxt.startswith('\\markup \\sottotitolo "Traduzione"'):
                    cur['blocks'].append({'head': 'Traduzione'}); mode = 'trad'; i += 2
                else: i += 1
                continue
            head, _, inc = raw.partition('@@')
            name, _, ora = head.partition(' | ')
            cur = {'raw': raw, 'sec': sec, 'name': name.strip(), 'ora': ora.strip(), 'incipit': inc.strip(),
                   'blocks': []}
            items.append(cur); mode = None
            i += 1; continue
        m = re.match(r'\\markup \\sottotitolo ' + QS, l)
        if m and cur:
            s = unq(m.group(1))
            cur['blocks'].append({'head': s})
            mode = 'trad' if s == 'Traduzione' else ('ant' if s == 'Antifona' else None)
            i += 1; continue
        if '\\lyricsto' in l and cur:
            # raccogli tutte le righe Lyrics di questo \score
            lyr = []
            j = i
            while j < len(lines) and '\\lyricsto' in lines[j]:
                lyr.append(lines[j]); j += 1
            if '\\lyricsto "t"' in l:
                n, tl = parse_tone_lyrics(l)
                cur['blocks'].append({'n': n, 'lines': [{'t': x} for x in tl], 'score': 1})
            else:
                italic = "font-shape = #'italic" in l
                st = {}
                for ly in lyr:
                    body = ly[ly.index('{') + 1: ly.rindex('}')]
                    st.update(parse_lyrics(body))
                for n in sorted(st):
                    cur['blocks'].append({'n': (n or None), 'words': st[n], 'score': 1,
                                          **({'ant': 1} if italic else {})})
            i = j; continue
        if l.startswith('\\markup \\testo') and cur:
            for b in parse_text_markup(l):
                if mode == 'trad':
                    for ln in b['lines']: ln['it'] = 1
                    b['trad'] = 1
                cur['blocks'].append(b)
            i += 1; continue
        i += 1

    # post-elaborazione: versi della strofa 1, Amen finale, id
    out = []
    for k, c in enumerate(items):
        blocks = c['blocks']
        # traduzioni affiancate (es. Veni): ordina per numero
        if any(b.get('trad') for b in blocks):
            fi = next(ix for ix, b in enumerate(blocks) if b.get('trad'))
            tr = [b for b in blocks[fi:] if b.get('trad')]
            if all(b.get('n') for b in tr) and len(tr) == len(blocks[fi:]):
                blocks[fi:] = sorted(tr, key=lambda b: b['n'])
        text_blocks = [b for b in blocks if 'lines' in b and not b.get('trad')]
        for b in blocks:
            if 'words' in b:
                ref = next((tb['lines'] for tb in text_blocks if tb.get('n') and not tb.get('score')), None)
                if b.get('ant'): ref = None
                for key, nl in (('VENI', 3), ('OMNI', 4)):
                    if c['name'].startswith(key) or c['incipit'].upper().startswith(key):
                        ref = [{'t': 'la la la la la la la'}] * nl
                words = b['words']
                later_amen = any('Amen' in ln['t'] for tb in text_blocks if not tb.get('score') for ln in tb['lines'])
                if later_amen and words and words[-1][0].rstrip('.').endswith('men') and len(words[-1][0]) <= 6:
                    words = words[:-1]
                if ref:
                    b['lines'] = [{'t': x} for x in break_lines(words, [x['t'] for x in ref])]
                else:
                    txt = ' '.join(w.replace('\u0001', ' ') for w, _ in words)
                    b['lines'] = [{'t': x} for x in re.split(r'(?<=[,;:.])\s+', txt) if x]
                if b.get('ant'):
                    for ln in b['lines']: ln['it'] = 1
                del b['words']
        # Amen isolato in mezzo (Veni): spostalo in fondo all'ultima strofa
        sc = [b for b in blocks if b.get('score') and not b.get('ant')]
        for b in sc[:-1]:
            if b['lines'] and b['lines'][-1]['t'].strip() == 'Amen.' and len(sc) > 1:
                b['lines'].pop(); sc[-1]['lines'][-1]['t'] += ' Amen.'
            elif b['lines'] and b['lines'][-1]['t'].endswith(' Amen.') and len(sc) > 1:
                b['lines'][-1]['t'] = b['lines'][-1]['t'][:-6]; sc[-1]['lines'][-1]['t'] += ' Amen.'
        for b in blocks:
            ls = b.get('lines')
            if not ls: continue
            # orazione dopo Preghiamo/Orémus: paragrafo unico
            if ls[0].get('mark') == '℣'[0] and re.match(r'(Preghiamo|Orémus)', ls[0]['t']) and len(ls) > 2:
                body = [x['t'] for x in ls[1:]]
                tail = []
                while body and re.match(r'(Per Cri|Per Chri|Amen)', body[-1]): tail.insert(0, body.pop())
                if body and re.search(r'(Per Cri\w+ \w+ \w+\.)\s*(Amen\.)?$', body[-1]):
                    pass
                b['lines'] = [ls[0], dict(ls[1], t=' '.join(body))] + [dict(ls[1], t=t) for t in tail]
            # traduzioni in prosa: un solo paragrafo
            elif b.get('trad') and len(ls) > 1 and any(len(x['t']) > 48 for x in ls) and not any(x.get('mark') for x in ls[1:]):
                b['lines'] = [dict(ls[0], t=' '.join(x['t'] for x in ls))]
        title = c['incipit'] or c['name'].title() if c['name'].isupper() else (c['incipit'] or c['name'])
        if not c['incipit'] and c['name'].isupper():
            title = c['name'].title().replace("'S", "'s")
        sub = ' · '.join(x for x in [c['name'].title() if c['incipit'] else '', c['ora']] if x)
        if c['name'] == 'APPENDICE': sub = c['ora']
        if title.isupper() or (not c['incipit'] and c['name'].isupper()):
            title = title[0] + title[1:].lower()
        if blocks and 'head' in blocks[0] and blocks[0]['head'] not in ('Antifona', 'Traduzione'):
            sub = blocks.pop(0)['head']
        out.append({'id': 'c%d' % (k + 1), 'sec': SEZ[c['sec']], 'title': title, 'sub': sub,
                    'name': c['name'], 'ora': c['ora'], 'blocks': blocks})
    for c in out:
        for b in c['blocks']:
            for ln in b.get('lines', []):
                ln['t'] = ln['t'].replace('Per Te sollo', 'Per Te solo')
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(len(out), 'canti')

main()
