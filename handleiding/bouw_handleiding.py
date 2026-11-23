# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
"""Bouwt handleiding.pdf en handleiding_paginas.json uit handleiding.html.

Gebruik:  python handleiding\\bouw_handleiding.py
Vereist:  PyMuPDF (pip install pymupdf)

Elk <section id="..." data-titel="..."> wordt een hoofdstuk dat op een nieuwe
pagina begint. De startpagina per hoofdstuk komt in handleiding_paginas.json;
het programma gebruikt dat om Help op de juiste pagina te openen. Draai dit
script dus opnieuw na elke wijziging in de tekst of de afbeeldingen, en
voordat u de exe bouwt.
"""

import io
import json
import os
import re

import pymupdf

HIER = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HIER)
BRON = os.path.join(HIER, "handleiding.html")
PDF = os.path.join(HIER, "handleiding.pdf")
PAGINAS = os.path.join(HIER, "handleiding_paginas.json")

A4 = pymupdf.paper_rect("a4")
MARGE = 56
INHOUD = pymupdf.Rect(MARGE, MARGE, A4.width - MARGE, A4.height - MARGE - 10)
GRIJS = (0.36, 0.41, 0.47)


def versie():
    with open(os.path.join(PROJECT, "krab.py"), encoding="utf-8") as f:
        return re.search(r'^VERSIE = "([^"]+)"', f.read(), re.M).group(1)


def main():
    with open(BRON, encoding="utf-8") as f:
        html = f.read()
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    hoofdstukken = re.findall(r'<section id="([a-z]+)" data-titel="([^"]+)">(.*?)</section>', html, re.S)
    archief = pymupdf.Archive(os.path.join(HIER, "afbeeldingen"))
    archief.add(PROJECT)  # voor het logo
    v = versie()

    # 1. Hoofdstukken, elk vanaf een nieuwe pagina. Pagina 1 is voor titel en inhoud.
    buffer = io.BytesIO()
    schrijver = pymupdf.DocumentWriter(buffer)
    pagina = 1
    inhoud = []
    for nr, (sleutel, titel, tekst) in enumerate(hoofdstukken, 1):
        eerste = pagina + 1
        # <!--pagina--> in de tekst dwingt een nieuwe pagina af
        for deel_nr, deel in enumerate(tekst.split("<!--pagina-->")):
            kop = f"<h1>{nr}. {titel}</h1>" if deel_nr == 0 else ""
            story = pymupdf.Story(html=kop + deel, user_css=css, archive=archief)
            meer = True
            while meer:
                apparaat = schrijver.begin_page(A4)
                meer, _ = story.place(INHOUD)
                story.draw(apparaat)
                schrijver.end_page()
                pagina += 1
        inhoud.append((nr, sleutel, titel, eerste))
    schrijver.close()
    doc = pymupdf.open("pdf", buffer.getvalue())

    # 2. Titelpagina met inhoudsopgave
    rijen = "".join(f'<tr><td>{nr}.  {titel}</td>'
                    f'<td style="text-align:right">{blz}</td></tr>' for nr, _, titel, blz in inhoud)
    titel_html = f"""
      <p><img src="icoon.png" width="64"/></p>
      <p class="titel">Krab</p>
      <p class="ondertitel">Handleiding · versie {v}</p>
      <div class="let"><b>Gebruik op eigen risico.</b> Het programma stuurt automatisch sneltoetsen naar het
      actieve venster. Alles wat het zo uitvoert, geldt als een handeling van uzelf. Esc stopt altijd direct.</div>
      <h2>Inhoud</h2>
      <table class="inhoud">{rijen}</table>
      <p class="klein">Help of F1 in het programma opent deze handleiding op de pagina die bij het scherm hoort.</p>
      <p class="klein">© 2026 aSync B.V. · Open source onder de MIT-licentie · Geleverd zoals het is, zonder
      garantie, onderhoud of ondersteuning.</p>"""
    titelpagina = doc.new_page(0, width=A4.width, height=A4.height)
    titelpagina.insert_htmlbox(INHOUD, titel_html, css=css, archive=archief)

    # 3. Voettekst, bladwijzers en metadata
    for p in doc:
        if p.number == 0:
            continue
        y = A4.height - 34
        p.insert_text((MARGE, y), f"Krab {v} · Handleiding", fontsize=8, color=GRIJS)
        tekst = f"{p.number + 1} / {doc.page_count}"
        breedte = pymupdf.get_text_length(tekst, fontsize=8)
        p.insert_text((A4.width - MARGE - breedte, y), tekst, fontsize=8, color=GRIJS)
    doc.set_toc([[1, f"{nr}. {titel}", blz] for nr, _, titel, blz in inhoud])
    doc.set_metadata({"title": "Krab – Handleiding", "subject": f"versie {v}",
                      "author": "aSync B.V.", "creator": "bouw_handleiding.py", "producer": ""})
    doc.save(PDF, garbage=4, deflate=True)

    paginas = {sleutel: blz for _, sleutel, _, blz in inhoud}
    with open(PAGINAS, "w", encoding="utf-8") as f:
        json.dump(paginas, f, indent=2)
    print(f"{PDF}: {doc.page_count} pagina's, {os.path.getsize(PDF) // 1024} kB")
    print("Help-pagina's:", paginas)


if __name__ == "__main__":
    main()
