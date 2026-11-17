#!/usr/bin/env python3
"""Genera l'ePub (reflowable) del libretto «Inni».

Uso: build_epub.py canti.json libretto.pdf uscita.epub

- canti.json: testi e traduzioni (lo stesso file dell'app; si estrae da
  libro.ly con extract.py). Si può passare anche direttamente l'index.html
  dell'app: i testi vengono presi da lì.
- libretto.pdf: il PDF del libretto; da qui si ritagliano gli spartiti,
  un'immagine per ogni rigo musicale.
"""
import json, os, re, subprocess, sys, tempfile, uuid, zipfile, html, io
from datetime import datetime, timezone
import numpy as np
from PIL import Image

DPI = 200
AUDIO = "https://drive.google.com/drive/folders/1ak3Kv8y1ltFpNXcO46MDwW5sgQFkRUjz"
SITO = "https://lucasmpaez.github.io/inni/"
SEZIONI = ["Inni del tempo ordinario", "Inni di altri tempi liturgici",
           "Cantici e altri inni", "Appendice", "Preghiere"]
# etichette dell'indice (come nel PDF) dove il campo «sub» non basta
ETICHETTA = {'c15': 'Ora media', 'c16': 'Inno mariano', 'c17': 'Compieta',
             'c18': 'Compieta, oppure', 'c29': 'Dedicazione'}


def esc(s):
    return html.escape(s, quote=True)


# ---------------------------------------------------------------- spartiti
def staff_systems(im):
    """Righi musicali: gruppi di 5 linee orizzontali lunghe ed equidistanti."""
    H, W = im.shape
    rows = im.sum(1)
    lines = []
    for y in np.nonzero(rows > 0.45 * W)[0]:
        if lines and y - lines[-1][1] <= 1:
            lines[-1][1] = y
        else:
            lines.append([y, y])
    ls = [(a + b) / 2 for a, b in lines]
    out = []
    i = 0
    while i + 4 < len(ls):
        g = ls[i:i + 5]
        d = np.diff(g)
        if d.max() - d.min() < 3 and d.mean() < 30:
            out.append((g[0], g[4], d.mean()))
            i += 5
        else:
            i += 1
    return out


def page_regions(png):
    """Blocchi di spartito della pagina: liste di (y0, y1) per ciascun rigo."""
    im = np.array(Image.open(png).convert('L')) < 128
    H, W = im.shape
    rows = im.sum(1)
    sy = staff_systems(im)
    # piè di pagina: l'ultimo gruppo di righe con inchiostro
    ink = np.nonzero(rows)[0]
    foot = ink[-1]
    while foot > 0 and rows[foot - 1] > 0:
        foot -= 1
    gapf = foot - 1
    while gapf > 0 and rows[gapf] == 0: gapf -= 1
    foot_top = gapf + 1 + (foot - gapf - 1) // 2   # a metà dello spazio bianco
    ext = []
    for k, (t, b, sp) in enumerate(sy):
        gap = int(2.2 * sp)
        y = int(b) + 1; last = y
        lim = int(sy[k + 1][0] - 4 * sp) if k + 1 < len(sy) else foot_top
        while y < lim:
            if rows[y] > 0: last = y
            elif y - last >= gap: break
            y += 1
        y = int(t) - 1; first = y
        while y > int(t - 4 * sp):           # non prendere titoli o «Antifona» sopra il rigo
            if rows[y] >= 0.3 * W: break          # filetto dell'intestazione
            if rows[y] > 0: first = y
            elif first - y >= gap: break
            y -= 1
        ext.append(dict(top=first, bot=last, st=t, sb=b, sp=sp))
    groups = []
    for r in ext:
        if groups and r['top'] - groups[-1][-1]['bot'] < 3 * r['sp']:
            groups[-1].append(r)
        else:
            groups.append([r])
    # tagli tra un rigo e l'altro: lo spazio vuoto più basso (senza contare chiave e armatura)
    body = im[:, int(0.15 * W):].sum(1)
    out = []
    for g in groups:
        cuts = [g[0]['top'] - 8]
        for a, b in zip(g, g[1:]):
            lo, hi = int(a['sb'] + a['sp']), int(b['st'] - 0.6 * a['sp'])
            seg = body[lo:hi]
            m = seg.min()
            best = None; y = 0
            while y < len(seg):
                if seg[y] <= m + 2:
                    s0 = y
                    while y < len(seg) and seg[y] <= m + 2: y += 1
                    # il più basso tra gli spazi vuoti: le seconde righe di testo restano col loro rigo
                    if best is None or y - s0 >= 3 or y - s0 > best[1] - best[0]: best = (s0, y)
                y += 1
            cuts.append(lo + (best[0] + best[1]) // 2)
        cuts.append(g[-1]['bot'] + 8)
        out.append([dict(cut0=c0, cut1=c1, st=r['st'], sb=r['sb'])
                    for c0, c1, r in zip(cuts, cuts[1:], g)])
    return out


def system_image(pg, s, prev, nxt):
    """Ritaglio di un rigo: tiene solo i segni il cui centro sta tra i due tagli
    (così la chiave del rigo sotto non finisce sopra il testo, e viceversa)."""
    lab, cen = pg
    y0 = int(prev['sb']) if prev else s['cut0']
    y1 = int(nxt['st']) + 1 if nxt else s['cut1']
    sub = lab[y0:y1]
    keep = (cen[sub] >= s['cut0']) & (cen[sub] < s['cut1']) & (sub > 0)
    ys = np.nonzero(keep.any(1))[0]
    a = max(0, ys[0] - 6)
    return keep[a:ys[-1] + 7], y0 + a


def render_pages(pdf, tmp):
    subprocess.run(['pdftoppm', '-r', str(DPI), '-gray', '-png', pdf, os.path.join(tmp, 'p')], check=True)
    files = sorted(f for f in os.listdir(tmp) if f.startswith('p-'))
    return {int(re.search(r'(\d+)', f).group(1)): os.path.join(tmp, f) for f in files}


def label_page(png):
    from scipy import ndimage
    im = np.array(Image.open(png).convert('L')) < 160
    lab, n = ndimage.label(im, structure=np.ones((3, 3)))
    cen = np.zeros(n + 1)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        cen[i] = (sl[0].start + sl[0].stop) / 2
    return lab, cen


def score_images(canti, pages):
    """{id canto: [[(png, size) per rigo] per blocco di spartito]}"""
    raw = {}
    for c in canti:
        regs = []
        for k, p in enumerate(c['pdfpages']):
            for r in page_regions(pages[p]):
                r = [dict(x, p=p) for x in r]
                if k > 0 and r[0]['cut0'] < 0.65 * DPI and regs:   # continua dalla pagina prima
                    regs[-1] += r
                else:
                    regs.append(r)
        raw[c['id']] = regs
    labs = {}
    masks = {}
    xs = []
    for cid, regs in raw.items():
        for reg in regs:
            for i, s in enumerate(reg):
                p = s['p']
                if p not in labs: labs[p] = label_page(pages[p])
                prev = reg[i - 1] if i and reg[i - 1]['p'] == p else None
                nxt = reg[i + 1] if i + 1 < len(reg) and reg[i + 1]['p'] == p else None
                m, ya = system_image(labs[p], s, prev, nxt)
                masks[(cid, id(s))] = (m, ya)
                cols = np.nonzero(masks[(cid, id(s))][0].any(0))[0]
                xs += [cols[0], cols[-1]]
    x0, x1 = min(xs) - 6, max(xs) + 6     # stessi margini per tutti: stessa scala
    out = {}; grays = {}
    for cid, regs in raw.items():
        out[cid] = []
        for reg in regs:
            imgs = []
            for s in reg:
                from scipy import ndimage
                m, ya = masks[(cid, id(s))]
                m = ndimage.binary_dilation(m, iterations=2)[:, x0:x1]   # bordi sfumati
                g = grays.setdefault(s['p'], np.array(Image.open(pages[s['p']]).convert('L')))
                g = g[ya:ya + m.shape[0], x0:x1]
                im = Image.fromarray(np.where(m, g, 255).astype(np.uint8))
                im = im.quantize(16, dither=Image.Dither.NONE)
                buf = io.BytesIO(); im.save(buf, 'PNG', optimize=True)
                imgs.append((buf.getvalue(), im.size))
            out[cid].append(imgs)
    return out


# ---------------------------------------------------------------- XHTML
def page(title, body, cls=''):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="it" lang="it">
<head><meta charset="utf-8"/><title>{esc(title)}</title>
<link rel="stylesheet" type="text/css" href="../css/inni.css"/></head>
<body{f' class="{cls}"' if cls else ''}>
{body}
</body>
</html>
'''


def block_html(b):
    if b.get('head'):
        return f'<h3>{esc(b["head"])}</h3>'
    cls = ['st']
    if b.get('trad'): cls.append('trad')
    if b.get('ant'): cls.append('ant')
    if any(len(l['t']) > 70 for l in b['lines']): cls.append('prose')
    n = f'<span class="n">{b["n"]}.</span>' if b.get('n') else ''
    ls = []
    for l in b['lines']:
        c = ['l'] + (['it'] if l.get('it') else []) + (['rub'] if l.get('rub') else [])
        mk = f'<span class="mk">{l["mark"]}.</span> ' if l.get('mark') else ''
        ls.append(f'<p class="{" ".join(c)}">{mk}{esc(l["t"])}</p>')
    return f'<div class="{" ".join(cls)}">{n}{"".join(ls)}</div>'


def canto_html(c, regs, imgnames):
    sub = c['sub'] or ''
    if c['sec'] == 'Preghiere': sub = ''
    head = f'<p class="sub">{esc(sub)}</p>' if sub else ''
    body = [f'<section epub:type="chapter" role="doc-chapter">', head,
            f'<h2 id="t">{esc(c["title"])}</h2>']
    sb = [i for i, b in enumerate(c['blocks']) if b.get('score')]
    # a quale blocco va ciascuno spartito
    where = {}
    if len(sb) == len(regs):
        for i, r in zip(sb, range(len(regs))): where[i] = [r]
    elif regs:
        where[sb[0] if sb else 0] = list(range(len(regs)))
    for i, b in enumerate(c['blocks']):
        for r in where.get(i, []):
            imgs = ''.join(f'<img src="../img/{n}" alt=""/>' for n in imgnames[r])
            label = 'Spartito' + (' dell’antifona' if b.get('ant') else '')
            body.append(f'<div class="score" role="img" aria-label="{label}">{imgs}</div>')
        body.append(block_html(b))
    body.append('</section>')
    return page(c['title'], '\n'.join(body))


CSS = '''@charset "utf-8";
@font-face { font-family: "InniSegni"; src: url(../fonts/segni.ttf); }
body { margin: 0 4%; line-height: 1.35; }
h1 { font-weight: normal; text-align: center; margin: 30% 0 0; font-size: 1.7em; }
h2 { font-size: 1.35em; font-weight: bold; margin: 0 0 0.8em; padding-bottom: 0.3em;
     border-bottom: 1px solid #999; line-height: 1.2; }
h3 { font-size: 1em; font-style: italic; font-weight: normal; margin: 1.2em 0 0.4em; }
.sub { margin: 0 0 0.15em; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.06em;
       color: #8a2424; }
.score { margin: 0.6em 0 1em; page-break-inside: auto; }
.score img { display: block; width: 100%; height: auto; margin: 0; }
.st { position: relative; margin: 0 0 0.9em; padding-left: 1.7em; }
.st .n { position: absolute; left: 0; top: 0; width: 1.4em; text-align: right; color: #777; }
.st p.l { margin: 0; text-indent: -1em; padding-left: 1em; text-align: left; }
.st.prose p.l { margin-bottom: 0.3em; }
.st.trad { color: #555; }
.it { font-style: italic; }
.rub { color: #8a2424; }
.mk { font-family: "InniSegni", serif; color: #8a2424; font-style: normal; }
.indice h3 { font-style: normal; font-weight: bold; margin-top: 1.4em; }
.indice p { margin: 0 0 0.35em; padding-left: 1em; text-indent: -1em; }
.indice .et { color: #8a2424; font-size: 0.85em; }
.indice a { text-decoration: none; color: inherit; }
.copertina { margin: 0; padding: 0; text-align: center; }
.copertina img { max-width: 100%; max-height: 100%; }
.note p { margin: 0 0 0.8em; }
'''


def make_cover():
    from PIL import ImageDraw, ImageFont
    W, H = 1200, 1800
    im = Image.new('RGB', (W, H), (138, 36, 36))
    d = ImageDraw.Draw(im)
    f = None
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
              '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf']:
        if os.path.exists(p): f = ImageFont.truetype(p, 260); break
    f = f or ImageFont.load_default()
    d.text((W / 2, H * 0.42), 'INNI', font=f, fill=(250, 244, 236), anchor='mm')
    d.line((W * 0.3, H * 0.52, W * 0.7, H * 0.52), fill=(250, 244, 236), width=4)
    buf = io.BytesIO(); im.save(buf, 'JPEG', quality=88)
    return buf.getvalue()


def segni_font():
    """Sottoinsieme di DejaVu Sans con ℣ e ℟ (molti lettori non li hanno)."""
    from fontTools import subset
    src = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    opt = subset.Options(); opt.layout_features = []; opt.name_IDs = ['*']; opt.notdef_outline = True
    f = subset.load_font(src, opt)
    s = subset.Subsetter(opt); s.populate(unicodes=[0x2123, 0x211F, 0x2E]); s.subset(f)
    buf = io.BytesIO(); f.save(buf); return buf.getvalue()


def main():
    CANTI, PDF, OUT = sys.argv[1:4]
    if CANTI.endswith('.html'):
        h = open(CANTI, encoding='utf-8').read()
        canti, _ = json.JSONDecoder().raw_decode(h, h.index('CANTI = ') + 8)
    else:
        canti = json.load(open(CANTI, encoding='utf-8'))
    tmp = tempfile.mkdtemp()
    pages = render_pages(PDF, tmp)
    scores = score_images(canti, pages)

    files = {}      # nome nel pacchetto -> (bytes, media-type, id, proprietà)
    spine = []
    def add(name, data, mt, props=None, linear=True, in_spine=False):
        iid = re.sub(r'[^A-Za-z0-9]', '_', name)
        files[name] = (data if isinstance(data, bytes) else data.encode('utf-8'), mt, iid, props)
        if in_spine: spine.append((iid, linear))

    add('css/inni.css', CSS, 'text/css')
    add('fonts/segni.ttf', segni_font(), 'font/ttf')
    add('img/copertina.jpg', make_cover(), 'image/jpeg', 'cover-image')
    add('text/copertina.xhtml', page('Inni', '<div><img src="../img/copertina.jpg" alt="Inni"/></div>', 'copertina'),
        'application/xhtml+xml', in_spine=True)

    # indice stampabile (anche nella spina), e nav
    toc = []; ind = ['<section epub:type="toc" role="doc-toc" class="indice"><h2>Indice</h2>']
    nav_ol = []
    for sec in SEZIONI:
        cs = [c for c in canti if c['sec'] == sec]
        if not cs: continue
        sid = 's%d' % (SEZIONI.index(sec) + 1)
        add(f'text/{sid}.xhtml', page(sec, f'<h1>{esc(sec)}</h1>'), 'application/xhtml+xml', in_spine=True)
        items = []
        ind.append(f'<h3><a href="{sid}.xhtml">{esc(sec)}</a></h3>')
        for c in cs:
            imgnames = []
            for k, reg in enumerate(scores.get(c['id'], [])):
                names = []
                for j, (data, size) in enumerate(reg):
                    nm = f'{c["id"]}-{k + 1}-{j + 1}.png'
                    add('img/' + nm, data, 'image/png'); names.append(nm)
                imgnames.append(names)
            add(f'text/{c["id"]}.xhtml', canto_html(c, scores.get(c['id'], []), imgnames),
                'application/xhtml+xml', in_spine=True)
            et = ETICHETTA.get(c['id']) or ('' if sec in ('Preghiere',) else c['sub'])
            label = f'{et}: {c["title"]}' if et and et != c['title'] else c['title']
            items.append(f'<li><a href="text/{c["id"]}.xhtml">{esc(label)}</a></li>')
            ind.append(f'<p><a href="{c["id"]}.xhtml">' + (f'<span class="et">{esc(et)}</span> ' if et and et != c['title'] else '')
                       + f'{esc(c["title"])}</a></p>')
        nav_ol.append(f'<li><a href="text/{sid}.xhtml">{esc(sec)}</a><ol>{"".join(items)}</ol></li>')
    ind.append('<h3><a href="audio.xhtml">File audio</a></h3></section>')
    add('text/indice.xhtml', page('Indice', '\n'.join(ind)), 'application/xhtml+xml')
    # l'indice va subito dopo la copertina
    files_order = list(files)
    spine.insert(1, (files['text/indice.xhtml'][2], True))

    add('text/audio.xhtml', page('File audio', f'''<h1>File audio</h1>
<div class="note"><p style="text-align:center;margin-top:2em">Le registrazioni dei canti sono su Google Drive:</p>
<p style="text-align:center"><a href="{AUDIO}">Apri la cartella dei file audio</a></p>
<p style="text-align:center;margin-top:2em">App per il telefono: <a href="{SITO}">{esc(SITO)}</a></p></div>'''),
        'application/xhtml+xml', in_spine=True)

    nav = page('Indice', f'''<nav epub:type="toc" role="doc-toc" id="toc"><h2>Indice</h2>
<ol><li><a href="text/indice.xhtml">Indice</a></li>{"".join(nav_ol)}<li><a href="text/audio.xhtml">File audio</a></li></ol></nav>
<nav epub:type="landmarks" hidden=""><ol>
<li><a epub:type="cover" href="text/copertina.xhtml">Copertina</a></li>
<li><a epub:type="toc" href="text/indice.xhtml">Indice</a></li>
<li><a epub:type="bodymatter" href="text/s1.xhtml">Inni</a></li></ol></nav>''').replace('../css/', 'css/')
    add('nav.xhtml', nav, 'application/xhtml+xml', 'nav')

    uid = 'urn:uuid:' + str(uuid.uuid5(uuid.NAMESPACE_URL, SITO + 'libretto.epub'))
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest = '\n'.join(
        f'<item id="{iid}" href="{n}" media-type="{mt}"' + (f' properties="{p}"' if p else '') + '/>'
        for n, (_, mt, iid, p) in files.items())
    spine_x = '\n'.join(f'<itemref idref="{i}"' + ('' if lin else ' linear="no"') + '/>' for i, lin in spine)
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="it">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="uid">{uid}</dc:identifier>
<dc:title>Inni</dc:title>
<dc:language>it</dc:language>
<dc:description>Inni e preghiere per Lodi, Vespri e Compieta, con spartiti e traduzioni.</dc:description>
<meta property="dcterms:modified">{now}</meta>
<meta name="cover" content="img_copertina_jpg"/>
</metadata>
<manifest>
{manifest}
</manifest>
<spine>
{spine_x}
</spine>
</package>
'''
    with zipfile.ZipFile(OUT, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', '''<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
''', compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('OEBPS/content.opf', opf, compress_type=zipfile.ZIP_DEFLATED)
        for n, (data, *_r) in files.items():
            z.writestr('OEBPS/' + n, data, compress_type=zipfile.ZIP_DEFLATED)
    n_img = sum(len(r) for v in scores.values() for r in v)
    print('ok', OUT, round(os.path.getsize(OUT) / 1e6, 2), 'MB,', n_img, 'righi musicali')


if __name__ == '__main__':
    main()
