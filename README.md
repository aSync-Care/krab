# Krab

Krab neemt herhalend toetswerk over. Na elke toetsaanslag stuurt het een instelbare reeks sneltoetsen naar het venster dat op dat moment actief is.

Versie: **3.1beta**. Dit is een bètaversie.

> [!WARNING]
> **Gebruik op eigen risico.** Krab kijkt niet naar wat er op het scherm staat. Het controleert niet welk venster actief is en ook niet of een sneltoets het bedoelde resultaat had. Alles wat het via sneltoetsen uitvoert, geldt als een handeling van de gebruiker. **Esc stopt altijd direct.**

## Beoogd gebruik

Krab automatiseert toetsaanslagen, meer niet. Het neemt geen beslissingen en leest geen gegevens uit andere programma's.

Gebruik Krab niet waar een verkeerde of onbedoelde toetsaanslag kan leiden tot letsel of andere ernstige schade.

Wie Krab wil inzetten in een organisatie:

- beoordeelt zelf of dat past binnen de regels van die organisatie en de afspraken met de leveranciers van de programma's waarin het wordt gebruikt;
- test het zelf in de eigen omgeving voordat het in gebruik gaat;
- is zelf verantwoordelijk voor installatie, beheer en gebruik.

## Geen ondersteuning, geen garantie

Krab wordt gratis gedeeld en geleverd zoals het is, zonder garantie, onderhoud of ondersteuning. Zie [LICENSE](LICENSE). Meldingen en voorstellen zijn welkom, maar er is geen toezegging dat ze worden opgepakt.

## Wat het doet

- **Opties:** tot 10 reeksen met een eigen naam, elk van 1 tot 10 sneltoetsen met instelbare wachttijden. Gebruikers kiezen een optie; beheer stelt ze in met de pincode. De reeks start met één vaste toets (aanbevolen, bijvoorbeeld F9) of met elke toets.
- **Esc stopt altijd**, ook midden in een reeks.
- **Centrale instellingen** in één bestand voor alle gebruikers. Iedereen kan ze bekijken, wijzigen kan alleen met een beheerpincode. Een herstelcode helpt bij een vergeten pincode.
- **Verzegeld bestand.** Is het instellingenbestand buiten het programma om gewijzigd, dan kan niemand starten tot de reservekopie is teruggezet.
- **Logboek** per pc en per dag, zonder namen en zonder gegevens van het scherm.
- **Handleiding** (pdf) ingebouwd. Help en F1 openen die in de browser op de juiste pagina.

Alles staat in de [handleiding](handleiding/handleiding.pdf).

## Installeren

1. Download `Krab-v3.1beta.exe` bij de [release](https://github.com/aSync-Care/krab/releases). Controleer de SHA-256-controlesom die bij de release staat.
2. Zet de exe in een centrale map die alle gebruikers kunnen lezen én beschrijven, bijvoorbeeld op een netwerkschijf. Staat de exe op elke pc lokaal, zet dan naast de exe een bestand `locatie.txt` met op de eerste regel het pad naar de centrale map.
3. Start het programma en richt het in: kies een beheerpincode, bewaar de herstelcode en stel de reeks in. Zie hoofdstuk 8 van de handleiding.

De exe is niet digitaal ondertekend. Windows SmartScreen kan daarom bij de eerste start waarschuwen. Wie dat niet wil, bouwt de exe zelf en ondertekent die met een eigen certificaat.

## Zelf bouwen

Vereist: Windows en Python 3.12.

```
pip install -r requirements-bouwen.txt
python tests/test_krab.py
python handleiding/maak_schermafdrukken.py     (alleen als de schermen zijn veranderd)
python handleiding/bouw_handleiding.py
pyinstaller --noconfirm krab.spec
```

De exe komt in `dist/`. De tests en het script voor de schermafdrukken gebruiken nagebootste toetsenbordmodules uit `tests/stubs`. Ze versturen geen echte toetsaanslagen en raken geen echte instellingen aan.

Om het programma direct vanuit Python te starten: `pip install -r requirements.txt` en daarna `python krab.py`.

## Beperkingen

- **De pincode is een drempel, geen beveiliging.** De centrale map moet voor alle gebruikers schrijfbaar zijn. Iedereen kan de bestanden dus buiten het programma om verwijderen of overschrijven. Het programma merkt dat en blokkeert, maar kan het niet voorkomen.
- **De sleutel van de controlecode staat in deze broncode.** De controlecode vangt per ongeluk of handmatig wijzigen af. Tegen iemand die bewust een geldig bestand wil maken, beschermt hij niet.
- **Het logboek is geen sluitend bewijsstuk.** Het staat in dezelfde schrijfbare map.
- **Alleen Windows.** Het programma gebruikt Windows-specifieke toetsenbordfuncties.

## Licentie

MIT-licentie, © 2026 aSync B.V. Zie [LICENSE](LICENSE).

De exe bevat onderdelen van derden met hun eigen licenties. Zie [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
