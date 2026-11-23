# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
"""Doorloopt alle flows van Krab met nagebootste toetsenbordmodules.

Gebruik:  python tests/test_krab.py
Verstuurt geen echte toetsaanslagen en raakt geen echte instellingen aan:
alles gebeurt in een tijdelijke map.
"""
import json
import os
import sys
import tempfile
import time

T = tempfile.mkdtemp()
os.environ.update(APPDATA=os.path.join(T, 'roaming'), LOCALAPPDATA=os.path.join(T, 'local'),
                  KRAB_MAP=os.path.join(T, 'centraal'), COMPUTERNAME='WS-TEST-01')
os.makedirs(os.environ['KRAB_MAP'])
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
sys.path.insert(0, os.path.join(HIER, 'stubs'))
sys.stdout.reconfigure(encoding='utf-8')
import pydirectinput as pyd  # noqa: E402  (nagebootst)
import krab as m  # noqa: E402
import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402

m.PBKDF2_ITERATIES = 1000
fouten_getoond = []
messagebox.showerror = lambda *a, **k: fouten_getoond.append(a)


def ok(c, msg):
    if not c:
        raise AssertionError(msg)
    print('  ok ', msg)


def E(n):
    return type('E', (), {'name': n, 'event_type': 'down'})()


# ================================================================ losse functies
print('functies')
ok(m.pincode_fout('482915') is None, 'geldige pincode')
ok(all(m.pincode_fout(p) for p in ('123456', '654321', '111111', '12345', '12a456')), 'ongeldige pincodes afgewezen')
ok(m.normaliseer_herstelcode('k7qf-2m9x hd4r') == 'K7QF2M9XHD4R', 'herstelcode normaliseren')
d = {'a': 1}; d['controlecode'] = m.zegel(d); ok(m.zegel_klopt(d), 'zegel klopt')
d['a'] = 2; ok(not m.zegel_klopt(d), 'zegel detecteert wijziging')

_, f = m.valideer_reeks({'trigger': 'f1', 'opties': m.STANDAARD_REEKS['opties'], 'logboek': {'bewaardagen': 5}})
ok('trigger' in f and 'bewaardagen' in f, 'F1 als starttoets en 5 dagen afgewezen')
_, f = m.valideer_reeks({'opties': [{'id': 'a', 'naam': 'X', 'stappen': [{'toetsen': 'tab', 'wacht': 1}]},
                                    {'id': 'b', 'naam': 'x', 'stappen': []}], 'logboek': {'bewaardagen': 90}})
ok(f.get('1.naam', '').startswith('Deze naam') and '1.stappen' in f, 'dubbele naam en optie zonder stappen afgewezen')
_, f = m.valideer_reeks({'opties': [{'id': 'a', 'naam': 'X', 'stappen': [{'toetsen': 'tab', 'wacht': 1},
                                                                         {'toetsen': 'tab', 'wacht': 1}]}],
                         'logboek': {'bewaardagen': 90}})
ok(not f, 'dezelfde toets twee keer in een optie mag')
_, f = m.valideer_reeks({'opties': [], 'logboek': {'bewaardagen': 90}})
ok('opties' in f, 'geen enkele optie afgewezen')

oud, _ = m.valideer_reeks(m.STANDAARD_REEKS)
nieuw = json.loads(json.dumps(oud))
nieuw['trigger'] = 'f9'
nieuw['opties'][0]['stappen'][0]['toetsen'] = 'ctrl+shift+1'
nieuw['opties'][1]['naam'] = 'Kort'
nieuw['opties'][1]['stappen'].pop()
nieuw['opties'].append({'id': 'o9', 'naam': 'Snel', 'stappen': [{'toetsen': 'tab', 'wacht': 0.5}]})
v_ = m.verschillen(oud, nieuw)
ok(('Starttoets', 'elke toets', 'toets F9') in v_ and ('Optie 1, stap 1', 'ctrl+alt+1', 'ctrl+shift+1') in v_
   and ('Naam van optie', 'Optie 2', 'Kort') in v_ and ('Kort, stap 2', 'ctrl+alt+2, 0,5 s', 'verwijderd') in v_
   and ('Optie toegevoegd', '–', 'Snel (1 stap)') in v_, 'verschillen tussen opties')
omgedraaid = json.loads(json.dumps(oud)); omgedraaid['opties'].reverse()
ok(m.verschillen(oud, omgedraaid) == [('Volgorde van opties', 'Optie 1, Optie 2', 'Optie 2, Optie 1')], 'volgorde')
ok(m.kies_optie(oud, 'bestaat-niet')['id'] == 'o1', 'onbekende optie valt terug op de eerste')
plan = m.maak_plan(oud, 'o2')
ok(plan['optie'] == 'Optie 2' and [t for _, t, _ in plan['stappen']] == [['ctrl', 'alt', '1'], ['ctrl', 'alt', '2']],
   'plan voor optie 2')

print('omzetten van instellingen uit versie 3beta')
map_oud = os.path.join(T, 'oude-versie'); os.makedirs(map_oud)
oud_bestand = {'formaat': 1, 'versie': 4, 'gewijzigd': {'op': '2026-11-20T10:00:00', 'pc': 'WS-1', 'reden': 'x'},
               'pincode': m.maak_hash('482915'), 'herstelcode': m.maak_hash('ABCD'), 'trigger': 'f9',
               'stappen': {'stap1': {'toetsen': 'ctrl+alt+7', 'wacht': 1.8},
                           'stap2': {'toetsen': 'ctrl+alt+8', 'wacht': 0.5},
                           'stap3': {'toetsen': 'ctrl+alt+9', 'wacht': 1.0}},
               'logboek': {'bewaardagen': 90}}
oud_bestand['controlecode'] = m.zegel(oud_bestand)
json.dump(oud_bestand, open(os.path.join(map_oud, 'instellingen.json'), 'w', encoding='utf-8'))
opslag_oud = m.CentraleOpslag(map_oud)
st, data, _ = opslag_oud.lees()
ok(st == 'ok' and [(o['naam'], len(o['stappen'])) for o in data['opties']] == [('Optie 1', 3), ('Optie 2', 2)],
   'oude stappen worden Optie 1 (3 stappen) en Optie 2 (2 stappen)')
opgeslagen = opslag_oud.opslaan(data, 4, 'test', 'test')
ruw = json.load(open(os.path.join(map_oud, 'instellingen.json'), encoding='utf-8'))
ok(ruw['formaat'] == 2 and 'stappen' not in ruw and len(ruw['opties']) == 2 and opslag_oud.lees()[0] == 'ok',
   'opgeslagen in de nieuwe opbouw, zegel klopt')

# ================================================================ hulpfuncties voor het scherm
app = m.App(); r = app.root


def pump(sec=0.15):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        r.update(); time.sleep(0.01)


def alle(w):
    for c in w.winfo_children():
        yield c
        yield from alle(c)


def scherm():
    if app._tijdelijk is not None:
        return app._tijdelijk
    return app.scherm_hoofd if app.scherm_hoofd.winfo_manager() else app.scherm_disclaimer


def entries():
    return [w for w in alle(scherm()) if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)]


def knop(tekst):
    for b in alle(scherm()):
        if isinstance(b, ttk.Button) and b.cget('text') == tekst:
            return b
    raise AssertionError('knop niet gevonden: ' + tekst)


def klik(tekst):
    knop(tekst).invoke(); pump()


def tekst_in_scherm():
    return ' | '.join(str(w.cget('text')) for w in alle(scherm())
                      if isinstance(w, (ttk.Label, tk.Label, ttk.Radiobutton)) and w.cget('text'))


def zet(e, v):
    e.configure(state='normal'); e.delete(0, 'end'); e.insert(0, v)


def herstelcode_op_scherm():
    return [w.cget('text') for w in alle(scherm())
            if isinstance(w, ttk.Label) and str(w.cget('style')) == 'Code.TLabel'][0]


def vink_aan():
    [w for w in alle(scherm()) if isinstance(w, ttk.Checkbutton)][0].invoke()


def log(soort=None):
    pump(0.3)
    return [x for x in app.logboek.lees(None, '0000') if soort is None or x['soort'] == soort]


def kies_in_lijst(i):
    lijst = app._velden['lijst']
    lijst.selection_clear(0, 'end'); lijst.selection_set(i); app._optie_gekozen(); pump(0.05)


def ontgrendel(pin='482915'):
    app._toon_instellingen_lezen(); klik('Ontgrendelen')
    zet(entries()[0], pin); knop('Ontgrendelen').invoke(); pump()


def toetsen_verstuurd():
    return [k for t, k, _ in pyd.LOG if t == 'down']


for optie in m.STANDAARD_REEKS['opties']:
    for s in optie['stappen']:
        s['wacht'] = 0.1

# ================================================================ flows
print('flow A: inrichten')
app.akkoord_var.set(True); app._akkoord_gewijzigd(); app.akkoord_knop.invoke(); pump()
ok(app.centraal_status == 'niet_ingericht', 'status niet ingericht')
ok(str(app.start_knop.cget('state')) == 'disabled', 'Start uit')
klik('Inrichten')
e = entries(); zet(e[0], '123456'); zet(e[1], '123456'); klik('Volgende')
ok('oplopende' in tekst_in_scherm(), 'oplopende pincode geweigerd')
zet(e[0], '482915'); zet(e[1], '482915'); klik('Volgende')
code = herstelcode_op_scherm()
ok(len(code) == 14 and str(knop('Volgende').cget('state')) == 'disabled', f'herstelcode {code} getoond, Volgende uit')
vink_aan(); klik('Volgende')
ok(app._velden['lijst'].size() == 2, 'inrichten begint met Optie 1 en Optie 2')
klik('Opslaan')
ok(app.centraal_status == 'ok' and app.centraal['versie'] == 1 and app.centraal['formaat'] == 2, 'versie 1 opgeslagen')
ok(os.path.exists(app.opslag.reserve) and os.path.exists(app.opslag.wijzigingen), 'reserve en wijzigingen.log')
ok('Optie 1  –  3 stappen' in tekst_in_scherm() and 'Optie 2  –  2 stappen' in tekst_in_scherm(), 'opties op hoofdscherm')

print('flow B: starten met een optie')
pyd.LOG.clear(); app._start(); app._op_toets(E('space')); pump(0.8)
ok(app._cycli == 1 and toetsen_verstuurd() == ['ctrl', 'alt', '1', 'ctrl', 'alt', '2', 'ctrl', 'alt', '3'],
   'Optie 1 verstuurt drie stappen')
pyd.LOG.clear(); app._op_toets(E('a')); pump(0.12); app._op_toets(E('esc')); pump(0.4)
ok(not app._actief.is_set() and '3' not in toetsen_verstuurd(), 'Esc stopt midden in de reeks')
app.optie_var.set('o2'); app._optie_gewijzigd()
ok(json.load(open(os.path.join(m.LOKALE_MAP, 'lokaal.json')))['optie'] == 'o2', 'gekozen optie onthouden op deze pc')
pyd.LOG.clear(); app._start(); app._op_toets(E('space')); pump(0.8)
ok(toetsen_verstuurd() == ['ctrl', 'alt', '1', 'ctrl', 'alt', '2'], 'Optie 2 verstuurt twee stappen')
app.stop_knop.invoke(); pump(0.2)
ok(any('Optie 2' in x['tekst'] for x in log('START')), 'logboek noemt de optie bij Start')

print('flow C: opties wijzigen')
app._toon_instellingen_lezen(); pump()
ok('Alleen-lezen' in tekst_in_scherm() and 'Optie 1' in tekst_in_scherm() and 'Optie 2' in tekst_in_scherm(),
   'alleen-lezen toont alle opties')
klik('Ontgrendelen'); zet(entries()[0], '111222'); knop('Ontgrendelen').invoke(); pump()
ok('Nog 4 pogingen' in tekst_in_scherm(), 'foute pincode: nog 4 pogingen')
zet(entries()[0], '482915'); knop('Ontgrendelen').invoke(); pump()
v = app._velden
ok(app._ontgrendeld and v['lijst'].size() == 2 and len(v['stap_rijen']) == 3, 'ontgrendeld, Optie 1 met 3 stappen')
v['stap_rijen'][0][0].set('ctrl+shift+1'); app._markeer_wijzigingen()
ok(v['stap_rijen'][0][0].stijl == 'gewijzigd', 'gewijzigd veld blauw')
app._optie_toevoegen(); pump()
ok(app._velden['lijst'].size() == 3 and app._bewerk['keuze'] == 2, 'optie toegevoegd en gekozen')
zet(app._velden['naam'], 'Snel'); app._naam_getypt(); app._stap_toevoegen(); pump()
ok(len(app._velden['stap_rijen']) == 2 and app._velden['stap_rijen'][1][0].get() == 'ctrl+alt+2', 'stap toegevoegd')
kies_in_lijst(1); zet(app._velden['naam'], ''); app._naam_getypt()
kies_in_lijst(0); zet(app._velden['bewaardagen'], '30'); klik('Opslaan…')
ok(app._bewerk['keuze'] == 1 and 'Geef de optie een naam' in app._velden['naam_fout'].cget('text')
   and app._velden['lijst'].get(1).startswith('⚠'), 'fout in andere optie: die wordt gekozen en gemarkeerd')
zet(app._velden['naam'], 'Optie 2'); app._naam_getypt(); klik('Opslaan…')
tekst = tekst_in_scherm()
ok('Optie toegevoegd' in tekst and 'Optie 1, stap 1' in tekst and 'Bewaartermijn' in tekst, 'bevestigscherm')
klik('Opslaan voor iedereen'); ok('reden' in tekst_in_scherm().lower(), 'reden verplicht')
zet(entries()[0], 'Nieuwe optie Snel'); klik('Opslaan voor iedereen')
c = app.centraal
ok(c['versie'] == 2 and [o['naam'] for o in c['opties']] == ['Optie 1', 'Optie 2', 'Snel']
   and c['opties'][0]['stappen'][0]['toetsen'] == 'ctrl+shift+1' and c['logboek']['bewaardagen'] == 30,
   'versie 2 opgeslagen met drie opties')
ok(not app._ontgrendeld and 'Opgeslagen als versie 2' in tekst_in_scherm()
   and 'Snel  –  2 stappen' in tekst_in_scherm(), 'weer vergrendeld, nieuwe optie op hoofdscherm')

print('opnemen, kiezen en testen')


def Ev(keycode, keysym=''):
    return type('Ev', (), {'keycode': keycode, 'keysym': keysym})()


def druk(veld, *codes):
    """Simuleert indrukken en weer loslaten van toetsen op Windows-toetscode."""
    for c in codes:
        veld._toets_neer(Ev(c))
    for c in reversed(codes):
        veld._toets_op(Ev(c))


ontgrendel()
veld = app._velden['stap_rijen'][1][0]
veld._klik(); ok(veld.opname and app._opname_bezig, 'klik op een toetscombinatie start het opnemen')
druk(veld, 0x11, 0x12, 0x35)
ok(veld.get() == 'ctrl+alt+5' and not veld.opname and veld.stijl == 'gewijzigd', 'Ctrl+Alt+5 opgenomen')
veld._klik(); druk(veld, 0x10, 0x11)
ok(veld.opname and 'gewone toets' in app._velden['opname_label'].cget('text'), 'alleen Ctrl+Shift: melding, blijft opnemen')
druk(veld, 0x61)
ok(veld.opname and 'kan Krab niet versturen' in app._velden['opname_label'].cget('text'), 'numerieke toets geweigerd')
druk(veld, 0x1B); ok(not veld.opname and veld.get() == 'ctrl+alt+5', 'Esc annuleert, oude waarde blijft')
veld._klik(); veld._toets_neer(Ev(0x12)); veld._toets_neer(Ev(0x73))  # Alt en F4 ingedrukt
app._afsluiten(); ok(r.winfo_exists(), 'Alt+F4 tijdens opnemen sluit het programma niet')
veld._toets_op(Ev(0x73)); veld._toets_op(Ev(0x12))
ok(veld.get() == 'alt+f4', 'Alt+F4 is gewoon opgenomen als combinatie')
trig = app._velden['trigger']
trig._klik(); ok(not trig.opname, 'starttoets-veld is uitgeschakeld bij "Elke toets"')
app._velden['trigger_modus'].set('vast'); app._trigger_modus_gewijzigd()
trig._klik(); trig._toets_neer(Ev(0x11)); ok(trig.opname, 'starttoets: Ctrl alleen wordt niet geaccepteerd')
trig._toets_neer(Ev(0x70)); ok(trig.opname and 'F1' in app._velden['opname_label'].cget('text'), 'F1 gereserveerd')
trig._toets_neer(Ev(0x78)); ok(trig.get() == 'f9' and not trig.opname, 'F9 als starttoets opgenomen')
veld.set('ctrl+alt+5')
app._kies_toets(veld); pump(0.1)
kies = app._kies_venster
vinkjes = [w for w in alle(kies) if isinstance(w, ttk.Checkbutton)]
for w in vinkjes:
    if w.cget('text') in ('Alt', 'Shift'):
        w.invoke()  # Ctrl+Alt stond aan -> Ctrl+Shift
[w for w in alle(kies) if isinstance(w, ttk.Combobox)][0].set('Tab')
[w for w in alle(kies) if isinstance(w, ttk.Button) and w.cget('text') == 'OK'][0].invoke(); pump(0.1)
ok(veld.get() == 'ctrl+shift+tab' and not kies.winfo_exists(), 'kiezen: Ctrl+Shift+Tab')
app._is_voorgrond = lambda hwnd: True
app._optie_testen(); pump(0.1)
ok(app._test is not None and len(app._test['boom'].get_children()) == 3, 'testvenster met 3 stappen')
app._test_start(); vak = app._test
for combi in (['ctrl', 'shift', 'tab'], ['ctrl', 'shift', 'tab'], ['ctrl', 'alt', '3']):
    codes = {'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12, 'tab': 0x09, '3': 0x33}
    for k in combi:
        app._test_neer(Ev(codes[k]))
    for k in reversed(combi):
        app._test_op(Ev(codes[k]))
pump(1.5)
ok(vak['uitslag'].cget('text').startswith('✗') and 'fout' in vak['boom'].item('0', 'tags'),
   'test toont dat stap 1 anders aankwam dan verwacht')
ok('goed' in vak['boom'].item('1', 'tags') and 'goed' in vak['boom'].item('2', 'tags'), 'stap 2 en 3 goed')
app._is_voorgrond = lambda hwnd: False
app._test_start(); pump(0.8)
ok('niet meer vooraan' in vak['uitslag'].cget('text'), 'test stopt als het testvenster niet vooraan staat')
app._test_sluiten(); ok(app._test is None, 'testvenster gesloten')
klik('Vergrendelen')

print('kopiëren, verplaatsen, verwijderen')
ontgrendel()
app._optie_kopieren(); pump()
ok(app._velden['lijst'].size() == 4 and app._bewerk['concept']['opties'][1]['naam'] == 'Optie 1 (kopie)', 'gekopieerd')
app._optie_verplaats(1); pump()
ok(app._bewerk['keuze'] == 2 and app._bewerk['concept']['opties'][2]['naam'] == 'Optie 1 (kopie)', 'verplaatst')
app._optie_verwijderen(); pump()
ok(app._velden['lijst'].size() == 3, 'verwijderd')
klik('Opslaan…'); ok('Er is niets gewijzigd' in tekst_in_scherm(), 'per saldo niets gewijzigd')
kies_in_lijst(2); app._optie_verplaats(-1); klik('Opslaan…')
ok('Volgorde van opties' in tekst_in_scherm(), 'volgorde staat in het bevestigscherm')
klik('Terug'); app._optie_verplaats(1); klik('Vergrendelen')

print('flow D3: tegelijk opslaan')
ontgrendel()
zet(app._velden['stap_rijen'][1][2], '0,7'); klik('Opslaan…')
ander = json.loads(json.dumps(app.centraal)); ander['trigger'] = 'f9'
app.opslag.opslaan(ander, 2, 'andere pc', 'starttoets')
zet(entries()[0], 'test'); klik('Opslaan voor iedereen')
ok('versie 3' in tekst_in_scherm() and 'niet opgeslagen' in tekst_in_scherm(), 'conflict gemeld')
klik('Nieuwe versie laden')
ok(app.centraal['versie'] == 3 and 'Alleen-lezen' in tekst_in_scherm(), 'nieuwe versie geladen')

print('flow D1: buiten de app gewijzigd + reservekopie')
d = json.load(open(app.opslag.bestand, encoding='utf-8')); d['opties'][0]['stappen'][0]['toetsen'] = 'ctrl+alt+9'
json.dump(d, open(app.opslag.bestand, 'w', encoding='utf-8'))
app._naar_hoofd(); pump()
ok(app.centraal_status == 'gewijzigd' and 'Starten geblokkeerd' in tekst_in_scherm(), 'geblokkeerd')
ok(str(app.start_knop.cget('state')) == 'disabled', 'Start uit')
klik('Reservekopie terugzetten (versie 3)'); zet(entries()[0], '482915'); knop('Ontgrendelen').invoke(); pump()
ok(app.centraal_status == 'ok' and app.centraal['opties'][0]['stappen'][0]['toetsen'] == 'ctrl+shift+1',
   'reservekopie teruggezet')
os.remove(app.opslag.bestand); app._ververs_centraal()
ok(app.centraal_status == 'ontbreekt', 'ontbrekend bestand gedetecteerd (geen nieuwe inrichting)')
app.opslag.herstel_reserve()
open(app.opslag.bestand, 'w').write('{ kapot'); app._ververs_centraal()
ok(app.centraal_status == 'onleesbaar' and 'regel 1' in app.centraal_detail, 'onleesbaar met regelnummer')
app.opslag.herstel_reserve(); app._ververs_centraal()
ok(m.CentraleOpslag(os.path.join(T, 'bestaat-niet')).lees()[0] == 'onbereikbaar', 'onbereikbare map')

print('flow D4: te vaak fout')
app._toon_instellingen_lezen(); klik('Ontgrendelen')
for _ in range(5):
    zet(entries()[0], '000111'); knop('Ontgrendelen').invoke(); pump(0.05)
pump(0.6)
ok('Te veel onjuiste pogingen' in tekst_in_scherm() and str(entries()[0].cget('state')) == 'disabled',
   'geblokkeerd na 5 pogingen')
app._pin_geblokkeerd_tot = 0; pump(0.6); ok(str(entries()[0].cget('state')) == 'normal', 'na wachttijd weer vrij')

print('flow D5: pincode vergeten')
knop('Pincode vergeten?').invoke(); pump()
zet(entries()[0], 'FOUT-FOUT-FOUT'); klik('Volgende'); ok('Onjuiste herstelcode' in tekst_in_scherm(), 'foute herstelcode')
zet(entries()[0], code.lower()); klik('Volgende')
e = entries(); zet(e[0], '736251'); zet(e[1], '736251'); klik('Volgende')
code2 = herstelcode_op_scherm(); vink_aan(); klik('Volgende')
ok(app.centraal['versie'] == 4 and m.controleer_hash('736251', app.centraal['pincode'])
   and not m.controleer_hash('482915', app.centraal['pincode']), 'nieuwe pincode actief, oude niet')
ok(m.controleer_hash(m.normaliseer_herstelcode(code2), app.centraal['herstelcode'])
   and not m.controleer_hash(m.normaliseer_herstelcode(code), app.centraal['herstelcode']),
   'nieuwe herstelcode, oude vervallen')

print('pincode wijzigen + automatisch vergrendelen')
ontgrendel('736251')
knop('Pincode wijzigen').invoke(); pump()
e = entries(); zet(e[0], '736251'); zet(e[1], '590372'); zet(e[2], '590372'); klik('Opslaan')
ok(app.centraal['versie'] == 5 and m.controleer_hash('590372', app.centraal['pincode']) and app._ontgrendeld,
   'pincode gewijzigd, nog ontgrendeld')
app._laatste_activiteit -= 400; app._periodiek(); pump()
ok(not app._ontgrendeld and 'Automatisch vergrendeld' in tekst_in_scherm(), 'automatisch vergrendeld')

print('flow F: logboek')
app._naar_hoofd(); app._toon_logboek(); pump()
boom = [w for w in alle(scherm()) if isinstance(w, ttk.Treeview)][0]
ok(len(boom.get_children()) > 10, f'{len(boom.get_children())} logregels getoond')
soorten = {boom.item(i, 'values')[2] for i in boom.get_children()}
ok({'OPEN', 'AKKOORD', 'START', 'REEKS', 'AFGEBROKEN', 'STOP', 'INSTELLINGEN'} <= soorten, 'alle soorten aanwezig')
klik('Terug')
echte = app.logboek.map; blok = os.path.join(T, 'geen-map'); open(blok, 'w').close()
app.logboek.map = os.path.join(blok, 'logboek'); app.logboek.schrijf('START', 'tijdens storing'); pump(0.4)
app._periodiek(); pump()
ok(app.logboek.buffer_actief and os.path.exists(app.logboek.buffer) and app.buffer_label.winfo_manager(),
   'lokaal gebufferd + melding')
app.logboek.map = echte; app.logboek.schrijf('STOP', 'na storing'); pump(0.4); app._periodiek(); pump()
ok(not app.logboek.buffer_actief and not os.path.exists(app.logboek.buffer) and not app.buffer_label.winfo_manager(),
   'buffer overgezet, melding weg')
ok(any(x['tekst'] == 'tijdens storing' for x in log()), 'gebufferde regel in centraal logboek')
oud_log = os.path.join(echte, 'WS-OUD', '2020-01-01.jsonl')
os.makedirs(os.path.dirname(oud_log)); open(oud_log, 'w').close()
app.logboek.opschonen(30); pump(0.3); ok(not os.path.exists(oud_log), 'oude logbestanden opgeschoond')

print('help')
pdf = os.path.join(T, 'handleiding.pdf'); open(pdf, 'wb').write(b'%PDF-1.4 test')
geopend = []
_orig = m.zoek_resource
m.zoek_resource = lambda n: pdf if n == 'handleiding.pdf' else _orig(n)
m._start_standaardbrowser = lambda url: geopend.append(url) or True
app._toon_logboek(); app._help(); pump()
ok(geopend and geopend[-1].endswith('#page=%d' % app.help_paginas['logboek']), 'help opent de juiste pagina')
ok(os.path.exists(os.path.join(os.environ['LOCALAPPDATA'], m.APP_NAAM, f'handleiding-{m.VERSIE}.pdf')),
   'kopie in LOCALAPPDATA')
ok(not fouten_getoond, 'geen foutvensters')
app._afsluiten()

json.dump({'modus': 'zonder3'}, open(os.path.join(m.LOKALE_MAP, 'lokaal.json'), 'w'))
ok(m.laad_lokaal() == {'optie': 'o2'}, 'gekozen modus uit 3beta wordt Optie 2')
print('ALLE TESTS GESLAAGD')
