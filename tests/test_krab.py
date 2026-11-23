# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
"""Doorloopt alle flows van Krab met nagebootste toetsenbordmodules.

Gebruik:  python tests/test_krab.py
Verstuurt geen echte toetsaanslagen en raakt geen echte instellingen aan:
alles gebeurt in een tijdelijke map.
"""
import os, sys, time, json, tempfile
T = tempfile.mkdtemp()
os.environ.update(APPDATA=os.path.join(T, 'roaming'), LOCALAPPDATA=os.path.join(T, 'local'),
                  KRAB_MAP=os.path.join(T, 'centraal'), COMPUTERNAME='WS-TEST-01')
os.makedirs(os.environ['KRAB_MAP'])
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
sys.path.insert(0, os.path.join(HIER, 'stubs'))
sys.stdout.reconfigure(encoding='utf-8')
import pydirectinput as pyd  # noqa: F401  (stub)
import krab as m  # noqa: E402
m.PBKDF2_ITERATIES = 1000
from tkinter import ttk, messagebox
import tkinter as tk
fouten_getoond = []
messagebox.showerror = lambda *a, **k: fouten_getoond.append(a)


def ok(c, msg):
    if not c:
        raise AssertionError(msg)
    print('  ok ', msg)


def E(n):
    return type('E', (), {'name': n, 'event_type': 'down'})()


# ---------- unit
ok(m.pincode_fout('482915') is None, 'geldige pincode')
ok(all(m.pincode_fout(p) for p in ('123456', '654321', '111111', '12345', '12a456')), 'ongeldige pincodes afgewezen')
ok(m.normaliseer_herstelcode('k7qf-2m9x hd4r') == 'K7QF2M9XHD4R', 'herstelcode normaliseren')
d = {'a': 1}; d['controlecode'] = m.zegel(d); ok(m.zegel_klopt(d), 'zegel klopt')
d['a'] = 2; ok(not m.zegel_klopt(d), 'zegel detecteert wijziging')
r_, f_ = m.valideer_reeks({'trigger': 'f1', 'stappen': m.STANDAARD_REEKS['stappen'], 'logboek': {'bewaardagen': 5}})
ok('trigger' in f_ and 'bewaardagen' in f_, 'F1 als starttoets en 5 dagen afgewezen')
oud, _ = m.valideer_reeks(m.STANDAARD_REEKS)
nieuw = json.loads(json.dumps(oud)); nieuw['stappen']['stap1']['toetsen'] = 'ctrl+shift+1'; nieuw['trigger'] = 'f9'
ok(m.verschillen(oud, nieuw) == [('Starttoets', 'elke toets', 'toets F9'), ('Stap 1', 'ctrl+alt+1', 'ctrl+shift+1')],
   'verschillen')

# ---------- helpers
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
                      if isinstance(w, (ttk.Label, tk.Label)) and w.cget('text'))


def zet(e, v):
    e.configure(state='normal'); e.delete(0, 'end'); e.insert(0, v)


def herstelcode_op_scherm():
    return [w.cget('text') for w in alle(scherm()) if isinstance(w, ttk.Label) and str(w.cget('style')) == 'Code.TLabel'][0]


def vink_aan():
    [w for w in alle(scherm()) if isinstance(w, ttk.Checkbutton)][0].invoke()


def log(soort=None):
    pump(0.3)
    return [x for x in app.logboek.lees(None, '0000') if soort is None or x['soort'] == soort]


for s in m.STANDAARD_REEKS['stappen'].values():
    s['wacht'] = 0.1

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
klik('Opslaan')
ok(app.centraal_status == 'ok' and app.centraal['versie'] == 1, 'versie 1 opgeslagen')
ok(os.path.exists(app.opslag.reserve) and os.path.exists(app.opslag.wijzigingen), 'reserve en wijzigingen.log')
ok(str(app.start_knop.cget('state')) == 'normal', 'Start aan')

print('flow B: starten')
app._start(); app._op_toets(E('space')); pump(0.8)
ok(app._cycli == 1, 'een reeks uitgevoerd')
app._op_toets(E('a')); pump(0.12); app._op_toets(E('esc')); pump(0.4)
ok(not app._actief.is_set(), 'Esc stopt')
ok(log('REEKS') and log('AFGEBROKEN') and log('STOP') and log('START'), 'START/REEKS/AFGEBROKEN/STOP gelogd')

print('flow C: wijzigen')
app._toon_instellingen_lezen(); pump()
ok('Alleen-lezen' in tekst_in_scherm(), 'alleen-lezen scherm')
klik('Ontgrendelen'); zet(entries()[0], '111222'); knop('Ontgrendelen').invoke(); pump()
ok('Nog 4 pogingen' in tekst_in_scherm(), 'foute pincode: nog 4 pogingen')
zet(entries()[0], '482915'); knop('Ontgrendelen').invoke(); pump()
ok(app._ontgrendeld and app._velden, 'ontgrendeld')
v = app._velden; zet(v['stappen']['stap1'][0], 'ctrl+shift+1'); app._markeer_wijzigingen()
ok(str(v['stappen']['stap1'][0].cget('style')) == 'Gewijzigd.TEntry', 'gewijzigd veld blauw')
zet(v['bewaardagen'], '3'); klik('Opslaan…')
ok('bewaartermijn' in tekst_in_scherm(), 'bewaartermijn 3 geweigerd')
zet(app._velden['bewaardagen'], '30'); klik('Opslaan…')
ok('Stap 1' in tekst_in_scherm() and 'ctrl+shift+1' in tekst_in_scherm(), 'bevestigscherm toont wijziging')
klik('Opslaan voor iedereen'); ok('reden' in tekst_in_scherm().lower(), 'reden verplicht')
zet(entries()[0], 'Sneltoets gewijzigd'); klik('Opslaan voor iedereen')
ok(app.centraal['versie'] == 2 and app.centraal['stappen']['stap1']['toetsen'] == 'ctrl+shift+1'
   and app.centraal['logboek']['bewaardagen'] == 30, 'versie 2 opgeslagen')
ok(not app._ontgrendeld and 'Opgeslagen als versie 2' in tekst_in_scherm(), 'weer vergrendeld, melding')

print('flow D3: tegelijk opslaan')
app._toon_instellingen_lezen(); klik('Ontgrendelen'); zet(entries()[0], '482915'); knop('Ontgrendelen').invoke(); pump()
zet(app._velden['stappen']['stap2'][2], '0,7'); klik('Opslaan…')
ander = json.loads(json.dumps(app.centraal)); ander['trigger'] = 'f9'
app.opslag.opslaan(ander, 2, 'andere pc', 'starttoets')
zet(entries()[0], 'test'); klik('Opslaan voor iedereen')
ok('versie 3' in tekst_in_scherm() and 'niet opgeslagen' in tekst_in_scherm(), 'conflict gemeld')
klik('Nieuwe versie laden')
ok(app.centraal['versie'] == 3 and 'Alleen-lezen' in tekst_in_scherm(), 'nieuwe versie geladen')

print('flow D1: buiten de app gewijzigd + reservekopie')
d = json.load(open(app.opslag.bestand, encoding='utf-8')); d['stappen']['stap1']['toetsen'] = 'ctrl+alt+9'
json.dump(d, open(app.opslag.bestand, 'w', encoding='utf-8'))
app._naar_hoofd(); pump()
ok(app.centraal_status == 'gewijzigd' and 'Starten geblokkeerd' in tekst_in_scherm(), 'geblokkeerd')
ok(str(app.start_knop.cget('state')) == 'disabled', 'Start uit')
klik('Reservekopie terugzetten (versie 3)'); zet(entries()[0], '482915'); knop('Ontgrendelen').invoke(); pump()
ok(app.centraal_status == 'ok' and app.centraal['stappen']['stap1']['toetsen'] == 'ctrl+shift+1', 'reservekopie teruggezet')
os.remove(app.opslag.bestand); app._ververs_centraal()
ok(app.centraal_status == 'ontbreekt', 'ontbrekend bestand gedetecteerd (geen nieuwe inrichting)')
app.opslag.herstel_reserve()
open(app.opslag.bestand, 'w').write('{ kapot'); app._ververs_centraal()
ok(app.centraal_status == 'onleesbaar' and 'regel 1' in app.centraal_detail, 'onleesbaar met regelnummer')
app.opslag.herstel_reserve(); app._ververs_centraal()
st, _, det = m.CentraleOpslag(os.path.join(T, 'bestaat-niet')).lees(); ok(st == 'onbereikbaar', 'onbereikbare map')

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
   and not m.controleer_hash(m.normaliseer_herstelcode(code), app.centraal['herstelcode']), 'nieuwe herstelcode, oude vervallen')

print('pincode wijzigen + automatisch vergrendelen')
app._toon_instellingen_lezen(); klik('Ontgrendelen'); zet(entries()[0], '736251'); knop('Ontgrendelen').invoke(); pump()
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
oud_bestand = os.path.join(echte, 'WS-OUD', '2020-01-01.jsonl')
os.makedirs(os.path.dirname(oud_bestand)); open(oud_bestand, 'w').close()
app.logboek.opschonen(30); pump(0.3); ok(not os.path.exists(oud_bestand), 'oude logbestanden opgeschoond')

print('help')
pdf = os.path.join(T, 'handleiding.pdf'); open(pdf, 'wb').write(b'%PDF-1.4 test')
geopend = []
_orig = m.zoek_resource
m.zoek_resource = lambda n: pdf if n == 'handleiding.pdf' else _orig(n)
m._start_standaardbrowser = lambda url: geopend.append(url) or True
app._toon_logboek(); app._help(); pump()
ok(geopend and geopend[-1].endswith('#page=%d' % app.help_paginas['logboek']), f'help opent ...{geopend[-1][-45:]}')
ok(os.path.exists(os.path.join(os.environ['LOCALAPPDATA'], 'Krab', 'handleiding-' + m.VERSIE + '.pdf')), 'kopie in LOCALAPPDATA')
print('\nwijzigingen.log:\n' + open(app.opslag.wijzigingen, encoding='utf-8').read())
ok(not fouten_getoond, 'geen foutvensters')
app._afsluiten(); print('ALLE TESTS GESLAAGD')
