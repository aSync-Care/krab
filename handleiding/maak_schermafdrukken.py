# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
"""Maakt de schermafdrukken voor de handleiding (handleiding/afbeeldingen/*.png).

Draait het echte programma met een tijdelijke centrale map. Gebruikt de
nagebootste toetsenbordmodules uit tests/stubs, zodat er geen echte
toetsaanslagen worden verstuurd. Werkt ook als het scherm vergrendeld is.
Opnieuw draaien na wijzigingen in de schermen:
    python handleiding\\maak_schermafdrukken.py
Vereist: Pillow.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="krab-shots-")
os.environ.update(APPDATA=os.path.join(TMP, "roaming"), LOCALAPPDATA=os.path.join(TMP, "local"),
                  KRAB_MAP=os.path.join(TMP, "centraal"), COMPUTERNAME="WS-0142")
os.makedirs(os.environ["KRAB_MAP"])
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (AttributeError, OSError):
    pass

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
sys.path.insert(0, os.path.join(os.path.dirname(HIER), "tests", "stubs"))
from PIL import Image  # noqa: E402
from tkinter import ttk  # noqa: E402

import krab as m  # noqa: E402

m.PBKDF2_ITERATIES = 1000
m.druk_combinatie = lambda toetsen: None  # geen echte toetsen versturen
UIT = os.path.join(HIER, "afbeeldingen")
os.makedirs(UIT, exist_ok=True)

app = m.App()
r = app.root
r.geometry("+40+40")


def pomp(sec=0.4):
    eind = time.monotonic() + sec
    while time.monotonic() < eind:
        r.update()
        time.sleep(0.01)


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def venster_afbeelding():
    """Legt het venster vast met PrintWindow; werkt ook als het scherm vergrendeld is."""
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = u32.GetParent(r.winfo_id())
    rc = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rc))
    zichtbaar = wt.RECT()  # zonder de onzichtbare randen van Windows 10/11
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(zichtbaar), ctypes.sizeof(zichtbaar))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    hdc = u32.GetWindowDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT
    bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    beeld = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    return beeld.crop((zichtbaar.left - rc.left, zichtbaar.top - rc.top,
                       zichtbaar.right - rc.left, zichtbaar.bottom - rc.top))


def foto(naam):
    pomp(0.5)
    venster_afbeelding().save(os.path.join(UIT, naam + ".png"))
    print("gemaakt:", naam)


def alle(w):
    for c in w.winfo_children():
        yield c
        yield from alle(c)


def velden():
    return [w for w in alle(app._tijdelijk) if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)]


def klik(tekst):
    for b in alle(app._tijdelijk or app.scherm_hoofd):
        if isinstance(b, ttk.Button) and b.cget("text") == tekst:
            b.invoke()
            pomp(0.2)
            return
    raise SystemExit("knop niet gevonden: " + tekst)


def zet(veld, waarde):
    veld.delete(0, "end")
    veld.insert(0, waarde)


E = lambda naam: type("E", (), {"name": naam, "event_type": "down"})()  # noqa: E731

foto("waarschuwing")
app.akkoord_var.set(True)
app._akkoord_gewijzigd()
app.akkoord_knop.invoke()
foto("niet-ingericht")

klik("Inrichten")
v = velden()
zet(v[0], "482915")
zet(v[1], "4829")
foto("inrichten-pincode")
zet(v[1], "482915")
klik("Volgende")
foto("inrichten-herstelcode")
[w for w in alle(app._tijdelijk) if isinstance(w, ttk.Checkbutton)][0].invoke()
klik("Volgende")
app._velden["trigger_modus"].set("vast")
app._trigger_modus_gewijzigd()
klik("Opslaan")
app._hoofd_melding = None
app._werk_hoofd_bij()
foto("hoofdscherm")

_echt_plan = m.maak_plan
m.maak_plan = lambda reeks, modus: {  # korte wachttijden, alleen voor de schermafdruk
    "trigger": reeks["trigger"],
    "stappen": [(n, t, 0.05) for n, t, _ in _echt_plan(reeks, modus)["stappen"]]}
app._start()
for _ in range(14):
    app._op_toets(E("f9"))
    pomp(0.7)
foto("hoofdscherm-actief")
m.maak_plan = lambda reeks, modus: {
    "trigger": reeks["trigger"],
    "stappen": [(n, t, 0.6) for n, t, _ in _echt_plan(reeks, modus)["stappen"]]}
app._plan = m.maak_plan(m.valideer_reeks(app.centraal)[0], "alle")
app._op_toets(E("f9"))
pomp(0.9)
app._op_toets(E("esc"))
pomp(0.4)
m.maak_plan = _echt_plan

app._toon_instellingen_lezen()
foto("instellingen-lezen")
klik("Ontgrendelen")
zet(velden()[0], "111222")
klik("Ontgrendelen")
foto("pincode")
zet(velden()[0], "482915")
klik("Ontgrendelen")
zet(app._velden["stappen"]["stap1"][0], "ctrl+shift+1")
zet(app._velden["stappen"]["stap3"][2], "1,5")
app._markeer_wijzigingen()
app._laatste_activiteit = time.monotonic() - 28
foto("instellingen-wijzigen")
app._velden["notebook"].select(1)
foto("instellingen-logboek")
app._velden["notebook"].select(0)
klik("Opslaan…")
zet(velden()[0], "Sneltoets gewijzigd na update")
foto("bevestigen")
klik("Opslaan voor iedereen")
foto("opgeslagen")

app._toon_logboek()
foto("logboek")
klik("Terug")

data = json.load(open(app.opslag.bestand, encoding="utf-8"))
data["trigger"] = "f8"
json.dump(data, open(app.opslag.bestand, "w", encoding="utf-8"))
app._ververs_centraal()
foto("geblokkeerd")
app.opslag.herstel_reserve()

echte = app.opslag
app.opslag = m.CentraleOpslag(r"\\fileserver\gedeeld\Krab")
app._ververs_centraal()
app.centraal_detail = "het netwerkpad is niet gevonden"
app._werk_hoofd_bij()
foto("onbereikbaar")
app.opslag = echte
app._afsluiten()
