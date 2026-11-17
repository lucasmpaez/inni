# ePub del libretto

`build_epub.py` genera `libretto-inni.epub` (reflowable: il testo si ingrandisce, gli spartiti sono immagini, un rigo per immagine).

    python3 sorgenti/epub/build_epub.py index.html libretto-inni.pdf libretto-inni.epub

- I testi e le traduzioni vengono dall'app (`index.html`, oppure `canti.json` di `extract.py`).
- Gli spartiti vengono ritagliati dal PDF del libretto: dopo ogni nuova versione del PDF basta rilanciare lo script.
- Serve: Python 3 con numpy, pillow, scipy, fonttools; `pdftoppm` (poppler).
- Controllo: `epubcheck libretto-inni.epub`.
