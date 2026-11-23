# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
# Geleverd zoals het is, zonder enige garantie. Zie LICENSE en README.md.
"""Krab v3

Stuurt per toetsaanslag een reeks sneltoetsen naar het actieve venster
(stap 1 en 2, en in modus 'Alle stappen' ook stap 3).

Opzet
- Centrale instellingen: instellingen.json in de centrale map (naast de exe,
  of de map die in locatie.txt naast de exe staat). Iedereen leest, wijzigen
  kan alleen met de beheerpincode. Het bestand is verzegeld met een
  controlecode; is het buiten de app om gewijzigd, dan kan niemand starten
  tot iemand met de pincode de reservekopie terugzet.
- Logboek: één JSON-regel per gebeurtenis in logboek\\<pc>\\<datum>.jsonl in de
  centrale map. Valt de map weg, dan wordt lokaal gebufferd.
- Help: de handleiding (pdf) zit in de exe en opent in de browser op de
  pagina die bij het scherm hoort.
- Eén globale toetsenbord-hook; Esc stopt altijd. Eén daemon-werkthread voert
  reeksen uit en raakt Tk nooit aan; UI-updates lopen via een queue die de
  hoofdthread met root.after leest.
"""

import copy
import csv
import datetime as dt
import hashlib
import hmac
import json
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keyboard
import pydirectinput as pyd

APP_NAAM = "Krab"
VERSIE = "3beta"

# (sleutel, weergavenaam, alleen in modus 'Alle stappen')
STAPPEN = (
    ("stap1", "Stap 1", False),
    ("stap2", "Stap 2", False),
    ("stap3", "Stap 3", True),
)

STANDAARD_REEKS = {
    "trigger": "",  # "" = elke toets
    "stappen": {
        "stap1": {"toetsen": "ctrl+alt+1", "wacht": 1.8},
        "stap2": {"toetsen": "ctrl+alt+2", "wacht": 0.5},
        "stap3": {"toetsen": "ctrl+alt+3", "wacht": 1.0},
    },
    "logboek": {"bewaardagen": 90},
}

MODUS_TEKST = {"alle": "Alle stappen", "zonder3": "Zonder stap 3"}
MODIFIERS = {"ctrl", "alt", "shift", "win"}
GERESERVEERD = {"esc": "Esc is gereserveerd voor stoppen.", "f1": "F1 is gereserveerd voor Help."}
MIN_WACHT, MAX_WACHT = 0.1, 10.0
BEWAAR_MIN, BEWAAR_MAX = 7, 3650
AFKOELTIJD = 0.4  # eigen geïnjecteerde toetsen starten geen nieuwe reeks
ALIASSEN = {"control": "ctrl", "windows": "win", "escape": "esc", "return": "enter",
            "page up": "pageup", "page down": "pagedown"}

PIN_LENGTE = 6
MAX_POGINGEN = 5
BLOKKEER_SEC = 60
AUTO_VERGRENDEL_SEC = 5 * 60
PBKDF2_ITERATIES = 600_000
HERSTEL_TEKENS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# Sleutel voor de controlecode. Deze staat openbaar in de broncode: de
# controlecode vangt alleen per ongeluk of handmatig wijzigen af en is geen
# beveiliging tegen iemand die bewust een geldig bestand wil maken.
ZEGEL_SLEUTEL = b"Krab/zegel/v1/7f3c9a51e2d84b06a1c5"

# Reserve als handleiding_paginas.json ontbreekt; bouw_handleiding.py schrijft de echte waarden.
HELP_PAGINAS_STANDAARD = {"waarschuwing": 2, "hoofdscherm": 3, "instellingen": 6, "wijzigen": 7,
                          "logboek": 9, "problemen": 11, "inrichten": 13}

STATUS_TEKST = {"ok": "in orde", "niet_ingericht": "nog niet ingericht", "gewijzigd": "buiten de app gewijzigd",
                "ontbreekt": "ontbreken", "onleesbaar": "onleesbaar", "onbereikbaar": "niet bereikbaar"}

SOORT_GROEPEN = {
    "Alle soorten": None,
    "Starten en stoppen": {"OPEN", "AKKOORD", "START", "STOP"},
    "Reeksen": {"REEKS", "AFGEBROKEN"},
    "Fouten": {"FOUT"},
    "Instellingen": {"INSTELLINGEN"},
}
PERIODES = {"Vandaag": 0, "Afgelopen 7 dagen": 6, "Afgelopen 30 dagen": 29, "Alles": None}

# Kleuren
WIT, VLAK, LIJN = "#FFFFFF", "#F3F5F8", "#D8DEE6"
TEKST, GRIJS = "#1E2733", "#5C6878"
BLAUW, GROEN, ROOD = "#1F5FA8", "#2E7D4F", "#B3261E"
WAARSCHUWING_BG, WAARSCHUWING_RAND, WAARSCHUWING_TEKST = "#FFF4E0", "#E0A12E", "#6B4200"
FOUT_BG = "#FDECEA"
BANNER_KLEUREN = {
    "warn": (WAARSCHUWING_BG, WAARSCHUWING_RAND, WAARSCHUWING_TEKST),
    "err": (FOUT_BG, ROOD, "#7A1A14"),
    "info": ("#EAF1FA", BLAUW, "#173F6E"),
    "ok": ("#E8F4EC", GROEN, "#1D5234"),
    "lock": (VLAK, LIJN, GRIJS),
}

DISCLAIMER_INTRO = (
    "Krab stuurt per toetsaanslag automatisch een reeks sneltoetsen naar het "
    "venster dat op dat moment actief is. Lees dit voordat u verdergaat."
)
DISCLAIMER_PUNTEN = (
    "Alles wat het programma via sneltoetsen uitvoert, geldt als een handeling "
    "van uzelf. U blijft daar volledig verantwoordelijk voor.",
    "Het programma kijkt niet naar wat er op het scherm staat. Het controleert "
    "niet welk venster actief is en ook niet of een sneltoets het bedoelde "
    "resultaat had.",
    "Controleer zelf wat er gebeurt voordat u de toets indrukt die de reeks start.",
    "Druk op Esc om direct te stoppen. Esc werkt altijd, ook midden in een reeks.",
    "Gebruik Krab niet waar een verkeerde of onbedoelde toetsaanslag kan leiden "
    "tot letsel of andere ernstige schade.",
    "Gebruik het alleen als uw organisatie dit toestaat.",
    "Krab is open source (MIT-licentie) en wordt geleverd zoals het is, "
    "zonder enige garantie. De makers zijn niet aansprakelijk voor fouten of "
    "schade door het gebruik ervan, voor zover de wet dat toestaat.",
)
DISCLAIMER_AKKOORD = "Ik heb dit gelezen en gebruik Krab op eigen risico."


# ================================================================ paden

def programma_map():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def zoek_resource(naam):
    """Zoekt een meegeleverd bestand: in de exe, of bij ontwikkelen in de projectmap."""
    for basis in (getattr(sys, "_MEIPASS", None), programma_map(),
                  os.path.join(programma_map(), "handleiding")):
        if basis and os.path.exists(os.path.join(basis, naam)):
            return os.path.join(basis, naam)
    return None


def centrale_map():
    if os.environ.get("KRAB_MAP"):
        return os.environ["KRAB_MAP"]
    try:
        with open(os.path.join(programma_map(), "locatie.txt"), encoding="utf-8-sig") as f:
            regel = f.readline().strip().strip('"')
        if regel:
            return regel
    except OSError:
        pass
    return programma_map()


LOKALE_MAP = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAAM)
LOKALE_DATA = os.path.join(os.environ.get("LOCALAPPDATA") or LOKALE_MAP, APP_NAAM)
PC_NAAM = os.environ.get("COMPUTERNAME") or socket.gethostname()


def nu():
    return dt.datetime.now().replace(microsecond=0)


def datum_nl(iso):
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d-%m-%Y %H:%M")
    except (TypeError, ValueError):
        return "?"


# ================================================================ validatie

def normaliseer_toets(naam):
    """Zet een toetsnaam van de keyboard-module om naar de pydirectinput-naam."""
    n = (naam or "").strip().lower()
    for prefix in ("left ", "right "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return ALIASSEN.get(n, n).replace(" ", "")


def formatteer_getal(getal):
    return f"{getal:.1f}".replace(".", ",")


def parse_combinatie(tekst):
    """'ctrl+alt+1' -> ['ctrl', 'alt', '1']. Geeft ValueError met uitleg."""
    if not str(tekst).strip():
        raise ValueError("Vul een toetscombinatie in, bijvoorbeeld ctrl+alt+1.")
    delen = [normaliseer_toets(d) for d in str(tekst).split("+")]
    if any(not d for d in delen):
        raise ValueError("Schrijf de combinatie als toets+toets, bijvoorbeeld ctrl+alt+1.")
    for d in delen:
        if d not in pyd.KEYBOARD_MAPPING:
            raise ValueError(f"'{d}' is geen bekende toets.")
    if "esc" in delen:
        raise ValueError(GERESERVEERD["esc"])
    if len(set(delen)) != len(delen):
        raise ValueError("Een toets staat dubbel in de combinatie.")
    if all(d in MODIFIERS for d in delen):
        raise ValueError("Voeg naast ctrl, alt of shift ook een gewone toets toe.")
    return delen


def parse_wacht(waarde):
    """Accepteert 1.8, '1.8' en '1,8'."""
    fout = f"Vul een wachttijd in tussen {formatteer_getal(MIN_WACHT)} en {MAX_WACHT:g} seconden."
    try:
        getal = float(str(waarde).strip().replace(",", "."))
    except ValueError:
        raise ValueError(fout) from None
    if not MIN_WACHT <= getal <= MAX_WACHT:
        raise ValueError(fout)
    return round(getal, 2)


def parse_trigger(tekst):
    """Eén losse toets die de reeks start."""
    tekst = str(tekst)
    if not tekst.strip():
        raise ValueError("Vul een toets in, of kies 'Elke toets'.")
    if "+" in tekst:
        raise ValueError("Kies één losse toets, geen combinatie.")
    naam = normaliseer_toets(tekst)
    if naam not in pyd.KEYBOARD_MAPPING:
        raise ValueError(f"'{naam}' is geen bekende toets.")
    if naam in GERESERVEERD:
        raise ValueError(GERESERVEERD[naam])
    if naam in MODIFIERS:
        raise ValueError("Kies een gewone toets, zoals F9, geen ctrl, alt of shift.")
    return naam


def parse_bewaardagen(waarde):
    fout = f"Vul een bewaartermijn in van {BEWAAR_MIN} tot {BEWAAR_MAX} dagen."
    try:
        getal = int(str(waarde).strip())
    except ValueError:
        raise ValueError(fout) from None
    if not BEWAAR_MIN <= getal <= BEWAAR_MAX:
        raise ValueError(fout)
    return getal


def valideer_reeks(data):
    """Controleert starttoets, stappen en bewaartermijn.

    Geeft (genormaliseerd, fouten); fouten is een dict veld -> melding.
    """
    fouten = {}
    uit = {"trigger": "", "stappen": {}, "logboek": {}}
    trigger = data.get("trigger", "")
    if trigger:
        try:
            uit["trigger"] = parse_trigger(trigger)
        except ValueError as e:
            fouten["trigger"] = str(e)
    stappen = data.get("stappen") if isinstance(data.get("stappen"), dict) else {}
    for sleutel, _, _ in STAPPEN:
        stap = stappen.get(sleutel) if isinstance(stappen.get(sleutel), dict) else {}
        nieuw = {}
        try:
            nieuw["toetsen"] = "+".join(parse_combinatie(stap.get("toetsen", "")))
        except ValueError as e:
            fouten[f"{sleutel}.toetsen"] = str(e)
        try:
            nieuw["wacht"] = parse_wacht(stap.get("wacht", ""))
        except ValueError as e:
            fouten[f"{sleutel}.wacht"] = str(e)
        uit["stappen"][sleutel] = nieuw
    combinaties = [uit["stappen"][s].get("toetsen") for s, _, _ in STAPPEN]
    for sleutel, _, _ in STAPPEN:
        eigen = uit["stappen"][sleutel].get("toetsen")
        if eigen and combinaties.count(eigen) > 1:
            fouten[f"{sleutel}.toetsen"] = "Deze combinatie wordt al bij een andere stap gebruikt."
    logboek = data.get("logboek") if isinstance(data.get("logboek"), dict) else {}
    try:
        uit["logboek"]["bewaardagen"] = parse_bewaardagen(logboek.get("bewaardagen", ""))
    except ValueError as e:
        fouten["bewaardagen"] = str(e)
    return uit, fouten


def maak_plan(reeks, modus):
    return {
        "trigger": reeks["trigger"],
        "stappen": [(naam, reeks["stappen"][s]["toetsen"].split("+"), reeks["stappen"][s]["wacht"])
                    for s, naam, alleen_stap3 in STAPPEN if not alleen_stap3 or modus == "alle"],
    }


def verschillen(oud, nieuw):
    """Lijst van (onderwerp, oud, nieuw) tussen twee genormaliseerde reeksen."""
    def trig(t):
        return f"toets {t.upper()}" if t else "elke toets"

    uit = []
    if oud["trigger"] != nieuw["trigger"]:
        uit.append(("Starttoets", trig(oud["trigger"]), trig(nieuw["trigger"])))
    for s, naam, _ in STAPPEN:
        a, b = oud["stappen"][s], nieuw["stappen"][s]
        if a["toetsen"] != b["toetsen"]:
            uit.append((naam, a["toetsen"], b["toetsen"]))
        if a["wacht"] != b["wacht"]:
            uit.append((f"Wacht vóór {naam}", f"{formatteer_getal(a['wacht'])} s",
                        f"{formatteer_getal(b['wacht'])} s"))
    a, b = oud["logboek"]["bewaardagen"], nieuw["logboek"]["bewaardagen"]
    if a != b:
        uit.append(("Bewaartermijn logboek", f"{a} dagen", f"{b} dagen"))
    return uit


# ================================================================ pincode en zegel

def pincode_fout(pin):
    if not (len(pin) == PIN_LENGTE and pin.isascii() and pin.isdigit()):
        return f"De pincode moet uit precies {PIN_LENGTE} cijfers bestaan."
    if len(set(pin)) == 1:
        return "Kies niet zes keer hetzelfde cijfer."
    if {int(b) - int(a) for a, b in zip(pin, pin[1:])} in ({1}, {-1}):
        return "Kies geen oplopende of aflopende reeks zoals 123456."
    return None


def maak_hash(geheim):
    zout = secrets.token_bytes(16)
    waarde = hashlib.pbkdf2_hmac("sha256", geheim.encode(), zout, PBKDF2_ITERATIES)
    return {"methode": "pbkdf2-sha256", "iteraties": PBKDF2_ITERATIES, "zout": zout.hex(), "hash": waarde.hex()}


def controleer_hash(geheim, opgeslagen):
    try:
        waarde = hashlib.pbkdf2_hmac("sha256", geheim.encode(), bytes.fromhex(opgeslagen["zout"]),
                                     int(opgeslagen["iteraties"]))
        return hmac.compare_digest(waarde.hex(), opgeslagen["hash"])
    except (KeyError, TypeError, ValueError):
        return False


def maak_herstelcode():
    code = "".join(secrets.choice(HERSTEL_TEKENS) for _ in range(12))
    return "-".join(code[i:i + 4] for i in (0, 4, 8))


def normaliseer_herstelcode(tekst):
    return "".join(c for c in tekst.upper() if c.isalnum())


def _canoniek(data):
    inhoud = {k: v for k, v in data.items() if k != "controlecode"}
    return json.dumps(inhoud, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def zegel(data):
    return "hmac-sha256:" + hmac.new(ZEGEL_SLEUTEL, _canoniek(data), hashlib.sha256).hexdigest()


def zegel_klopt(data):
    code = data.get("controlecode")
    return isinstance(code, str) and hmac.compare_digest(code, zegel(data))


# ================================================================ centrale opslag

class Conflict(Exception):
    """Iemand anders heeft de instellingen intussen opgeslagen."""

    def __init__(self, data):
        super().__init__("conflict")
        self.data = data


class CentraleOpslag:
    def __init__(self, map_):
        self.map = map_
        self.bestand = os.path.join(map_, "instellingen.json")
        self.reserve = os.path.join(map_, "instellingen.reserve.json")
        self.wijzigingen = os.path.join(map_, "wijzigingen.log")
        self.logmap = os.path.join(map_, "logboek")

    def _lees_bestand(self, pad):
        try:
            with open(pad, encoding="utf-8") as f:
                tekst = f.read()
        except FileNotFoundError:
            return "ontbreekt", None, ""
        except OSError as e:
            return "onbereikbaar", None, str(e)
        try:
            data = json.loads(tekst)
        except json.JSONDecodeError as e:
            return "onleesbaar", None, f"regel {e.lineno}: {e.msg}"
        if not isinstance(data, dict):
            return "onleesbaar", None, "het bestand bevat geen instellingen"
        if not zegel_klopt(data):
            return "gewijzigd", None, ""
        _, fouten = valideer_reeks(data)
        if fouten or not isinstance(data.get("versie"), int) or "pincode" not in data:
            return "onleesbaar", None, "de inhoud klopt niet"
        return "ok", data, ""

    def lees(self):
        """Geeft (status, data, detail). data is alleen gevuld bij status 'ok'."""
        if not os.path.isdir(self.map):
            return "onbereikbaar", None, f"map niet gevonden: {self.map}"
        status, data, detail = self._lees_bestand(self.bestand)
        if status == "ontbreekt" and not (os.path.exists(self.wijzigingen) or os.path.exists(self.reserve)):
            return "niet_ingericht", None, ""
        return status, data, detail

    def lees_reserve(self):
        status, data, _ = self._lees_bestand(self.reserve)
        return data if status == "ok" else None

    @staticmethod
    def _schrijf_atomair(pad, data):
        tijdelijk = f"{pad}.tmp-{os.getpid()}"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tijdelijk, pad)

    def opslaan(self, data, basis_versie, reden, wijziging, controleer=True):
        """Slaat een nieuwe versie op.

        basis_versie None betekent eerste inrichting: er mag dan nog geen
        bestand zijn. Anders moet de huidige versie gelijk zijn aan
        basis_versie, tenzij controleer False is (herstel vanuit reserve).
        """
        if controleer:
            status, huidig, _ = self.lees()
            if basis_versie is None and status != "niet_ingericht":
                raise Conflict(huidig)
            if basis_versie is not None and status == "ok" and huidig["versie"] != basis_versie:
                raise Conflict(huidig)
        nieuw = copy.deepcopy(data)
        nieuw.pop("controlecode", None)
        nieuw["formaat"] = 1
        nieuw["versie"] = (basis_versie or 0) + 1
        nieuw["gewijzigd"] = {"op": nu().isoformat(), "pc": PC_NAAM, "reden": reden}
        nieuw["controlecode"] = zegel(nieuw)
        self._schrijf_atomair(self.bestand, nieuw)
        self._schrijf_atomair(self.reserve, nieuw)
        self._log_wijziging(nieuw["versie"], wijziging, reden)
        return nieuw

    def herstel_reserve(self):
        data = self.lees_reserve()
        if data is None:
            raise ValueError("Er is geen bruikbare reservekopie.")
        self._schrijf_atomair(self.bestand, data)
        self._log_wijziging(data["versie"], "reservekopie teruggezet", "-")
        return data

    def _log_wijziging(self, versie, wijziging, reden):
        try:
            with open(self.wijzigingen, "a", encoding="utf-8") as f:
                f.write(f"{nu():%Y-%m-%d %H:%M}  versie {versie}  {PC_NAAM}  {wijziging}  reden: {reden}\n")
        except OSError:
            pass


# ================================================================ logboek

class Logboek:
    """Schrijft in een eigen daemon-thread, zodat netwerkvertraging de app niet ophoudt."""

    def __init__(self, logmap, lokale_map, pc):
        self.map = logmap
        self.buffer = os.path.join(lokale_map, "logboek-buffer.jsonl")
        self.pc = pc
        self.buffer_actief = os.path.exists(self.buffer)
        self._wachtrij = queue.Queue()
        self._lees_lock = threading.Lock()
        self._thread = threading.Thread(target=self._schrijver, name="logboek", daemon=True)
        self._thread.start()

    # -- schrijven
    def schrijf(self, soort, tekst, **extra):
        record = {"tijd": nu().isoformat(), "pc": self.pc, "soort": soort, "tekst": tekst}
        record.update(extra)
        self._wachtrij.put(("record", record))

    def opschonen(self, bewaardagen):
        self._wachtrij.put(("opschonen", bewaardagen))

    def sluit(self, timeout=3.0):
        self._wachtrij.put(("stop", None))
        self._thread.join(timeout)

    def _schrijver(self):
        while True:
            try:
                soort, inhoud = self._wachtrij.get(timeout=30)
            except queue.Empty:
                if self.buffer_actief:
                    self._probeer_buffer_legen()
                continue
            if soort == "stop":
                return
            if soort == "opschonen":
                self._verwijder_oud(inhoud)
                continue
            regel = json.dumps(inhoud, ensure_ascii=False)
            with self._lees_lock:
                try:
                    if self.buffer_actief:
                        self._leeg_buffer()
                    self._voeg_toe(inhoud["tijd"][:10], [regel])
                    self.buffer_actief = False
                except OSError:
                    if not self.buffer_actief:
                        self.buffer_actief = True
                        melding = {"tijd": inhoud["tijd"], "pc": self.pc, "soort": "FOUT",
                                   "tekst": "Centrale map niet bereikbaar · logboek tijdelijk op deze pc bewaard"}
                        self._naar_buffer(json.dumps(melding, ensure_ascii=False))
                    self._naar_buffer(regel)

    def _voeg_toe(self, datum, regels):
        map_pc = os.path.join(self.map, self.pc)
        os.makedirs(map_pc, exist_ok=True)
        with open(os.path.join(map_pc, f"{datum}.jsonl"), "a", encoding="utf-8") as f:
            f.write("".join(r + "\n" for r in regels))

    def _naar_buffer(self, regel):
        try:
            os.makedirs(os.path.dirname(self.buffer), exist_ok=True)
            with open(self.buffer, "a", encoding="utf-8") as f:
                f.write(regel + "\n")
        except OSError:
            pass

    def _leeg_buffer(self):
        if not os.path.exists(self.buffer):
            return
        with open(self.buffer, encoding="utf-8") as f:
            regels = [r.rstrip("\n") for r in f if r.strip()]
        per_datum = {}
        for regel in regels:
            try:
                datum = json.loads(regel)["tijd"][:10]
            except (ValueError, KeyError, TypeError):
                continue
            per_datum.setdefault(datum, []).append(regel)
        for datum, groep in per_datum.items():
            self._voeg_toe(datum, groep)
        os.remove(self.buffer)

    def _probeer_buffer_legen(self):
        with self._lees_lock:
            try:
                self._leeg_buffer()
                self.buffer_actief = False
            except OSError:
                pass

    def _verwijder_oud(self, bewaardagen):
        grens = (dt.date.today() - dt.timedelta(days=bewaardagen)).isoformat()
        try:
            pcs = os.listdir(self.map)
        except OSError:
            return
        for pc in pcs:
            map_pc = os.path.join(self.map, pc)
            try:
                for naam in os.listdir(map_pc):
                    if naam.endswith(".jsonl") and naam[:10] < grens:
                        os.remove(os.path.join(map_pc, naam))
            except OSError:
                continue

    # -- lezen
    def pcs(self):
        try:
            gevonden = {p for p in os.listdir(self.map) if os.path.isdir(os.path.join(self.map, p))}
        except OSError:
            gevonden = set()
        return sorted(gevonden | {self.pc})

    def lees(self, pcs, vanaf):
        """pcs None = alle pc's. vanaf = 'JJJJ-MM-DD'. Nieuwste eerst."""
        records = []
        with self._lees_lock:
            for pc in (self.pcs() if pcs is None else pcs):
                map_pc = os.path.join(self.map, pc)
                try:
                    namen = os.listdir(map_pc)
                except OSError:
                    continue
                for naam in namen:
                    if naam.endswith(".jsonl") and naam[:10] >= vanaf:
                        records.extend(self._lees_regels(os.path.join(map_pc, naam)))
            if pcs is None or self.pc in pcs:
                records.extend(r for r in self._lees_regels(self.buffer) if r.get("tijd", "")[:10] >= vanaf)
        records.sort(key=lambda r: r.get("tijd", ""), reverse=True)
        return records

    @staticmethod
    def _lees_regels(pad):
        uit = []
        try:
            with open(pad, encoding="utf-8") as f:
                for regel in f:
                    try:
                        record = json.loads(regel)
                    except ValueError:
                        continue
                    if isinstance(record, dict):
                        uit.append(record)
        except OSError:
            pass
        return uit


# ================================================================ help

def laad_help_paginas():
    paginas = dict(HELP_PAGINAS_STANDAARD)
    pad = zoek_resource("handleiding_paginas.json")
    if pad:
        try:
            with open(pad, encoding="utf-8") as f:
                paginas.update({k: int(v) for k, v in json.load(f).items()})
        except (OSError, ValueError, AttributeError):
            pass
    return paginas


def _start_standaardbrowser(url):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\shell\open\command") as k:
            opdracht = winreg.QueryValueEx(k, "")[0]
    except (OSError, ImportError):
        return False
    if "%1" not in opdracht:
        opdracht += ' "%1"'
    try:
        subprocess.Popen(opdracht.replace("%1", url), close_fds=True)
        return True
    except OSError:
        return False


def open_handleiding(pagina):
    """Opent de ingebouwde handleiding in de browser. Geeft de gebruikte manier terug."""
    bron = zoek_resource("handleiding.pdf")
    if not bron:
        raise FileNotFoundError("De ingebouwde handleiding ontbreekt in deze versie van het programma.")
    os.makedirs(LOKALE_DATA, exist_ok=True)
    doel = os.path.join(LOKALE_DATA, f"handleiding-{VERSIE}.pdf")
    if not os.path.exists(doel) or os.path.getsize(doel) != os.path.getsize(bron):
        shutil.copyfile(bron, doel)
    url = Path(doel).as_uri() + f"#page={pagina}"
    if _start_standaardbrowser(url):
        return "browser"
    try:
        os.startfile("microsoft-edge:" + url)
        return "edge"
    except OSError:
        os.startfile(doel)
        return "pdf-app"


# ================================================================ overig

def laad_lokaal():
    try:
        with open(os.path.join(LOKALE_MAP, "lokaal.json"), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("modus") in MODUS_TEKST:
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {"modus": "alle"}


def bewaar_lokaal(data):
    try:
        os.makedirs(LOKALE_MAP, exist_ok=True)
        with open(os.path.join(LOKALE_MAP, "lokaal.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def druk_combinatie(toetsen):
    ingedrukt = []
    try:
        for t in toetsen:
            pyd.keyDown(t)
            ingedrukt.append(t)
    finally:
        for t in reversed(ingedrukt):
            pyd.keyUp(t)


def concept_uit(data):
    """Formulierwaarden (tekst) uit centrale of standaard-instellingen."""
    trigger = data.get("trigger") or ""
    return {
        "trigger_modus": "vast" if trigger else "elke",
        "trigger": trigger or "f9",
        "stappen": {s: {"toetsen": data["stappen"][s]["toetsen"],
                        "wacht": formatteer_getal(float(data["stappen"][s]["wacht"]))} for s, _, _ in STAPPEN},
        "bewaardagen": str(data.get("logboek", {}).get("bewaardagen", STANDAARD_REEKS["logboek"]["bewaardagen"])),
    }


def maak_banner(parent, soort, titel=None, tekst=None, knoppen=(), link=None, breedte=380):
    bg, rand, fg = BANNER_KLEUREN[soort]
    b = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=rand, padx=10, pady=8)
    if titel:
        tk.Label(b, text=titel, bg=bg, fg=fg, font=("Segoe UI Semibold", 10),
                 anchor="w", justify="left").pack(fill="x")
    b.tekst_label = None
    if tekst:
        b.tekst_label = tk.Label(b, text=tekst, bg=bg, fg=fg, font=("Segoe UI", 9),
                                 wraplength=breedte, justify="left", anchor="w")
        b.tekst_label.pack(fill="x")
    if knoppen or link:
        rij = tk.Frame(b, bg=bg)
        rij.pack(fill="x", pady=(6, 0))
        for label, opdracht in knoppen:
            ttk.Button(rij, text=label, command=opdracht).pack(side="left", padx=(0, 6))
        if link:
            lbl = tk.Label(rij, text=link[0], bg=bg, fg=fg, font=("Segoe UI", 9, "underline"), cursor="hand2")
            lbl.pack(side="right")
            lbl.bind("<Button-1>", lambda _e: link[1]())
    return b


# ================================================================ app

class App:
    def __init__(self):
        self.opslag = CentraleOpslag(centrale_map())
        self.logboek = Logboek(self.opslag.logmap, LOKALE_MAP, PC_NAAM)
        self.lokaal = laad_lokaal()
        self.help_paginas = laad_help_paginas()
        self.centraal_status, self.centraal, self.centraal_detail = "onbekend", None, ""
        self.reserve = None

        # Gedeelde toestand tussen threads (geen Tk-objecten!)
        self._actief = threading.Event()
        self._stop = threading.Event()
        self._bezig = threading.Event()
        self._lock = threading.Lock()
        self._triggers = queue.Queue(maxsize=1)
        self._ui = queue.Queue()
        self._plan = None
        self._laatst_verzonden = 0.0
        self._reeks_nr = 0

        # Alleen hoofdthread
        self._cycli = 0
        self._start_moment = None
        self._opname_bezig = False
        self._hoofd_melding = None
        self._ontgrendeld = False
        self._laatste_activiteit = time.monotonic()
        self._pin_fouten = 0
        self._pin_geblokkeerd_tot = 0.0
        self._bewerk = None
        self._velden = None
        self._aftel_label = None
        self._tijdelijk = None
        self._opgeschoond_op = None
        self._help_onderwerp = "waarschuwing"
        self._akkoord_gelogd = False

        self.root = tk.Tk()
        self.root.title(f"{APP_NAAM} v{VERSIE}")
        self.root.configure(background=WIT)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self._laad_icoon()
        self._stijlen()
        self._vcmd_pin = self.root.register(lambda p: p == "" or (p.isdigit() and len(p) <= PIN_LENGTE))

        self.scherm_disclaimer = self._bouw_disclaimer()
        self.scherm_hoofd = self._bouw_hoofd()

        self.root.protocol("WM_DELETE_WINDOW", self._afsluiten)
        self.root.bind_all("<F1>", lambda _e: self._help())
        for gebeurtenis in ("<Any-KeyPress>", "<Any-ButtonPress>", "<Motion>"):
            self.root.bind_all(gebeurtenis, self._activiteit, add="+")

        keyboard.on_press(self._op_toets)
        threading.Thread(target=self._werker, name="werker", daemon=True).start()
        self.root.after(100, self._verwerk_ui_queue)

        status, data, _ = self.opslag.lees()
        self.logboek.schrijf("OPEN", f"{APP_NAAM} {VERSIE} · instellingen "
                             + (f"versie {data['versie']}" if status == "ok" else STATUS_TEKST[status]),
                             versie=VERSIE)
        self._toon(self.scherm_disclaimer, "waarschuwing")

    # ------------------------------------------------------------ opmaak

    def _laad_icoon(self):
        self.icoon = self.logo = None
        pad = zoek_resource("icoon.png")
        if not pad:
            return
        try:
            self.icoon = tk.PhotoImage(file=pad)
            self.root.iconphoto(True, self.icoon)
            factor = max(1, self.icoon.width() // 36)
            self.logo = self.icoon.subsample(factor, factor)
        except tk.TclError:
            pass

    def _stijlen(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=WIT, foreground=TEKST, font=("Segoe UI", 10))
        s.configure("TFrame", background=WIT)
        s.configure("Vlak.TFrame", background=VLAK)
        s.configure("TLabel", background=WIT, foreground=TEKST)
        s.configure("Titel.TLabel", font=("Segoe UI Semibold", 14))
        s.configure("Kop.TLabel", font=("Segoe UI Semibold", 9), foreground=GRIJS)
        s.configure("Klein.TLabel", font=("Segoe UI", 9), foreground=GRIJS)
        s.configure("Vlak.TLabel", background=VLAK)
        s.configure("VlakKlein.TLabel", background=VLAK, font=("Segoe UI", 9), foreground=GRIJS)
        s.configure("VlakMono.TLabel", background=VLAK, font=("Consolas", 10))
        s.configure("VlakUit.TLabel", background=VLAK, foreground="#A3ACB8")
        s.configure("Fout.TLabel", foreground=ROOD, font=("Segoe UI", 9))
        s.configure("Code.TLabel", font=("Consolas", 18, "bold"), background=VLAK, padding=(14, 10))
        s.configure("Waarschuwing.TFrame", background=WAARSCHUWING_BG)
        s.configure("Waarschuwing.TLabel", background=WAARSCHUWING_BG, foreground=WAARSCHUWING_TEKST)
        s.configure("WaarschuwingTitel.TLabel", background=WAARSCHUWING_BG,
                    foreground=WAARSCHUWING_TEKST, font=("Segoe UI Semibold", 15))
        s.configure("Waarschuwing.TCheckbutton", background=WAARSCHUWING_BG,
                    foreground=WAARSCHUWING_TEKST, font=("Segoe UI Semibold", 10))
        s.map("Waarschuwing.TCheckbutton", background=[("active", WAARSCHUWING_BG)])
        s.configure("TCheckbutton", background=WIT)
        s.map("TCheckbutton", background=[("active", WIT)])
        s.configure("TRadiobutton", background=WIT)
        s.map("TRadiobutton", background=[("active", WIT)])
        s.configure("TButton", padding=(10, 5), background=VLAK, bordercolor=LIJN)
        s.configure("Klein.TButton", padding=(6, 2), font=("Segoe UI", 9))
        s.configure("Primair.TButton", background=BLAUW, foreground=WIT, bordercolor=BLAUW)
        s.map("Primair.TButton", background=[("disabled", "#A9BCD6"), ("active", "#184C87")],
              foreground=[("disabled", WIT)])
        s.configure("Start.TButton", background=GROEN, foreground=WIT, bordercolor=GROEN,
                    font=("Segoe UI Semibold", 12), padding=(10, 8))
        s.map("Start.TButton", background=[("disabled", "#B7CFC0"), ("active", "#23653F")],
              foreground=[("disabled", WIT)])
        s.configure("Stop.TButton", background=ROOD, foreground=WIT, bordercolor=ROOD,
                    font=("Segoe UI Semibold", 12), padding=(10, 8))
        s.map("Stop.TButton", background=[("disabled", "#E3B5B2"), ("active", "#8E1E18")],
              foreground=[("disabled", WIT)])
        s.configure("Link.TButton", background=WIT, foreground=BLAUW, bordercolor=WIT, lightcolor=WIT,
                    darkcolor=WIT, padding=(0, 0), font=("Segoe UI", 9, "underline"))
        s.map("Link.TButton", background=[("active", WIT), ("disabled", WIT)],
              foreground=[("disabled", "#A3ACB8")], bordercolor=[("disabled", WIT)],
              lightcolor=[("disabled", WIT)], darkcolor=[("disabled", WIT)])
        s.configure("TEntry", padding=4, fieldbackground=WIT, bordercolor=LIJN)
        s.configure("Fout.TEntry", padding=4, fieldbackground=FOUT_BG, bordercolor=ROOD)
        s.configure("Gewijzigd.TEntry", padding=4, fieldbackground="#F2F7FD", bordercolor=BLAUW)
        s.configure("TNotebook", background=WIT, bordercolor=LIJN)
        s.configure("TNotebook.Tab", padding=(12, 4), background=VLAK)
        s.map("TNotebook.Tab", background=[("selected", WIT)])
        s.configure("Treeview", rowheight=22, font=("Segoe UI", 9), fieldbackground=WIT)
        s.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background=VLAK)

    def _toon(self, scherm, onderwerp):
        for vast in (self.scherm_disclaimer, self.scherm_hoofd):
            if vast is not scherm:
                vast.pack_forget()
        if self._tijdelijk is not None and self._tijdelijk is not scherm:
            self._tijdelijk.destroy()
            self._tijdelijk = None
        if scherm not in (self.scherm_disclaimer, self.scherm_hoofd):
            self._tijdelijk = scherm
        scherm.pack(fill="both", expand=True)
        self._help_onderwerp = onderwerp

    def _scherm(self, titel, stap=None):
        """Nieuw tijdelijk scherm met titel en Help-knop."""
        f = ttk.Frame(self.root, padding=(18, 16))
        kop = ttk.Frame(f)
        kop.pack(fill="x")
        ttk.Label(kop, text=titel, style="Titel.TLabel").pack(side="left")
        ttk.Button(kop, text="? Help", style="Klein.TButton", command=self._help).pack(side="right")
        if stap:
            ttk.Label(f, text=stap.upper(), style="Kop.TLabel").pack(anchor="w")
        return f

    @staticmethod
    def _knoppenrij(parent, rechts, links=()):
        rij = ttk.Frame(parent)
        rij.pack(fill="x", pady=(14, 0))
        for tekst, opdracht in links:
            ttk.Button(rij, text=tekst, command=opdracht).pack(side="left")
        knoppen = []
        for tekst, opdracht, primair in reversed(rechts):
            k = ttk.Button(rij, text=tekst, command=opdracht, style="Primair.TButton" if primair else "TButton")
            k.pack(side="right", padx=(8, 0))
            knoppen.append(k)
        return list(reversed(knoppen))

    # ------------------------------------------------------------ waarschuwing

    def _bouw_disclaimer(self):
        f = ttk.Frame(self.root, style="Waarschuwing.TFrame", padding=20)
        ttk.Label(f, text="⚠  Gebruik op eigen risico", style="WaarschuwingTitel.TLabel").pack(anchor="w")
        ttk.Label(f, text=DISCLAIMER_INTRO, style="Waarschuwing.TLabel",
                  wraplength=360, justify="left").pack(anchor="w", pady=(8, 10))
        for punt in DISCLAIMER_PUNTEN:
            rij = ttk.Frame(f, style="Waarschuwing.TFrame")
            rij.pack(anchor="w", fill="x", pady=2)
            ttk.Label(rij, text="•", style="Waarschuwing.TLabel").pack(side="left", anchor="n")
            ttk.Label(rij, text=punt, style="Waarschuwing.TLabel", wraplength=345,
                      justify="left").pack(side="left", padx=(6, 0))
        tk.Frame(f, height=1, background=WAARSCHUWING_RAND).pack(fill="x", pady=12)
        self.akkoord_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=DISCLAIMER_AKKOORD, variable=self.akkoord_var,
                        style="Waarschuwing.TCheckbutton", command=self._akkoord_gewijzigd).pack(anchor="w")
        knoppen = ttk.Frame(f, style="Waarschuwing.TFrame")
        knoppen.pack(fill="x", pady=(14, 0))
        handleiding = tk.Label(knoppen, text="Handleiding", bg=WAARSCHUWING_BG, fg=WAARSCHUWING_TEKST,
                               font=("Segoe UI", 9, "underline"), cursor="hand2")
        handleiding.pack(side="left")
        handleiding.bind("<Button-1>", lambda _e: self._help("waarschuwing"))
        self.akkoord_knop = ttk.Button(knoppen, text="Akkoord", style="Primair.TButton",
                                       command=self._akkoord, state="disabled")
        self.akkoord_knop.pack(side="right")
        ttk.Button(knoppen, text="Afsluiten", command=self._afsluiten).pack(side="right", padx=8)
        return f

    def _akkoord_gewijzigd(self):
        self.akkoord_knop.configure(state="normal" if self.akkoord_var.get() else "disabled")

    def _akkoord(self):
        if not self._akkoord_gelogd:
            self.logboek.schrijf("AKKOORD", "Waarschuwing geaccepteerd")
            self._akkoord_gelogd = True
        self._naar_hoofd()

    # ------------------------------------------------------------ hoofdscherm

    def _bouw_hoofd(self):
        f = ttk.Frame(self.root, padding=(18, 16))

        kop = ttk.Frame(f)
        kop.pack(fill="x")
        self._hoofd_kop = kop
        if self.logo:
            ttk.Label(kop, image=self.logo).pack(side="left", padx=(0, 10))
        titels = ttk.Frame(kop)
        titels.pack(side="left")
        ttk.Label(titels, text=APP_NAAM, style="Titel.TLabel").pack(anchor="w")
        ttk.Label(titels, text=f"versie {VERSIE}", style="Klein.TLabel").pack(anchor="w")
        ttk.Button(kop, text="? Help", style="Klein.TButton", command=self._help).pack(side="right", anchor="n")
        self.logboek_knop = ttk.Button(kop, text="Logboek", style="Klein.TButton", command=self._toon_logboek)
        self.logboek_knop.pack(side="right", anchor="n", padx=(0, 6))

        self.banner_vak = None  # wordt in _werk_hoofd_bij steeds opnieuw gemaakt

        ttk.Label(f, text="MODUS", style="Kop.TLabel").pack(anchor="w", pady=(12, 4))
        self.modus_var = tk.StringVar(value=self.lokaal["modus"])
        self.modus_knoppen = [
            ttk.Radiobutton(f, text="Alle stappen  –  stap 1, 2 en 3",
                            variable=self.modus_var, value="alle", command=self._modus_gewijzigd),
            ttk.Radiobutton(f, text="Zonder stap 3  –  stap 1 en 2",
                            variable=self.modus_var, value="zonder3", command=self._modus_gewijzigd),
        ]
        for k in self.modus_knoppen:
            k.pack(anchor="w", pady=1)

        rij = ttk.Frame(f)
        rij.pack(fill="x", pady=(14, 4))
        ttk.Label(rij, text="REEKS PER TOETSAANSLAG", style="Kop.TLabel").pack(side="left")
        self.instellingen_knop = ttk.Button(rij, text="Instellingen", style="Link.TButton",
                                            command=self._toon_instellingen_lezen)
        self.instellingen_knop.pack(side="right")

        self.reeks_vlak = ttk.Frame(f, style="Vlak.TFrame", padding=(10, 8))
        self.reeks_vlak.pack(fill="x")
        self.trigger_label = ttk.Label(f, style="Klein.TLabel")
        self.trigger_label.pack(anchor="w", pady=(4, 0))
        self.info_label = ttk.Label(f, style="Klein.TLabel")
        self.info_label.pack(anchor="w")

        knoppen = ttk.Frame(f)
        knoppen.pack(fill="x", pady=(14, 8))
        knoppen.columnconfigure((0, 1), weight=1, uniform="k")
        self.start_knop = ttk.Button(knoppen, text="Start", style="Start.TButton", command=self._start)
        self.start_knop.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_knop = ttk.Button(knoppen, text="Stop  (Esc)", style="Stop.TButton",
                                    command=lambda: self._stop_nu("Gestopt met de knop"), state="disabled")
        self.stop_knop.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        status = ttk.Frame(f, style="Vlak.TFrame", padding=(10, 6))
        status.pack(fill="x")
        self.status_stip = tk.Label(status, text="●", bg=VLAK, fg=GRIJS, font=("Segoe UI", 12))
        self.status_stip.pack(side="left")
        self.status_label = ttk.Label(status, text="Gestopt", style="Vlak.TLabel")
        self.status_label.pack(side="left", padx=(4, 0))
        self.teller_label = ttk.Label(status, text="Reeksen: 0", style="VlakKlein.TLabel")
        self.teller_label.pack(side="right")
        self.buffer_label = tk.Label(f, text="⚠  Centrale map niet bereikbaar. Het logboek wordt tijdelijk "
                                     "op deze pc bewaard.", bg=WAARSCHUWING_BG, fg=WAARSCHUWING_TEKST,
                                     font=("Segoe UI", 9), wraplength=370, justify="left", anchor="w",
                                     padx=8, pady=4, highlightthickness=1, highlightbackground=WAARSCHUWING_RAND)
        self.melding_label = ttk.Label(f, style="Fout.TLabel", wraplength=370, justify="left")
        self.melding_label.pack(anchor="w", pady=(4, 0))

        self.voet = tk.Frame(f, background=WAARSCHUWING_BG, highlightthickness=1,
                             highlightbackground=WAARSCHUWING_RAND)
        self.voet.pack(fill="x", pady=(8, 0))
        ttk.Label(self.voet, text="⚠  Esc stopt altijd direct. Gebruik op eigen risico.",
                  style="Waarschuwing.TLabel", padding=(8, 6)).pack(side="left")
        lees = tk.Label(self.voet, text="Lees meer", bg=WAARSCHUWING_BG, fg=WAARSCHUWING_TEKST,
                        font=("Segoe UI", 9, "underline"), cursor="hand2")
        lees.pack(side="right", padx=8)
        lees.bind("<Button-1>", lambda _e: None if self._actief.is_set()
                  else self._toon(self.scherm_disclaimer, "waarschuwing"))
        return f

    def _naar_hoofd(self):
        self._ontgrendeld = False
        self._bewerk = self._velden = self._aftel_label = None
        self._ververs_centraal()
        self._toon(self.scherm_hoofd, "hoofdscherm")

    def _ververs_centraal(self):
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            status, data, detail = self.opslag.lees()
            self.reserve = (self.opslag.lees_reserve()
                            if status in ("gewijzigd", "ontbreekt", "onleesbaar") else None)
        finally:
            self.root.configure(cursor="")
        self.centraal_status, self.centraal, self.centraal_detail = status, data, detail
        if status == "ok" and self._opgeschoond_op != dt.date.today():
            self._opgeschoond_op = dt.date.today()
            self.logboek.opschonen(data["logboek"]["bewaardagen"])
        self._werk_hoofd_bij()

    def _werk_hoofd_bij(self):
        # Een Tk-frame krimpt niet als de inhoud verdwijnt, dus elke keer een nieuw vak.
        if self.banner_vak is not None:
            self.banner_vak.destroy()
        self.banner_vak = ttk.Frame(self.scherm_hoofd)
        self.banner_vak.pack(fill="x", after=self._hoofd_kop)
        st = self.centraal_status
        actief = self._actief.is_set()
        if self._hoofd_melding and (self._hoofd_melding[0] != "ok" or st == "ok"):
            maak_banner(self.banner_vak, *self._hoofd_melding).pack(fill="x", pady=(10, 0))
        probleem = lambda: self._help("problemen")  # noqa: E731
        if st == "niet_ingericht":
            maak_banner(self.banner_vak, "warn", "Nog niet ingericht",
                        f"Er zijn nog geen centrale instellingen in {self.opslag.map}. Wie de pincode gaat "
                        "beheren, richt het programma eerst in.",
                        knoppen=[("Inrichten", self._start_inrichten)],
                        link=("Wat moet ik doen?", lambda: self._help("inrichten"))).pack(fill="x", pady=(10, 0))
        elif st in ("gewijzigd", "ontbreekt", "onleesbaar"):
            reden = {
                "gewijzigd": "De centrale instellingen zijn buiten Krab om gewijzigd.",
                "ontbreekt": "Het centrale instellingenbestand ontbreekt.",
                "onleesbaar": f"Het centrale instellingenbestand is onleesbaar ({self.centraal_detail}).",
            }[st]
            if self.reserve:
                tekst = reden + " Vraag iemand met de beheerpincode om de reservekopie terug te zetten."
                knoppen = [(f"Reservekopie terugzetten (versie {self.reserve['versie']})", self._start_terugzetten)]
            else:
                tekst = reden + (" Er is geen bruikbare reservekopie. Beheer moet de centrale map leegmaken "
                                 "en het programma opnieuw inrichten.")
                knoppen = []
            maak_banner(self.banner_vak, "err", "Starten geblokkeerd", tekst, knoppen=knoppen,
                        link=("Wat moet ik doen?", probleem)).pack(fill="x", pady=(10, 0))
        elif st == "onbereikbaar":
            maak_banner(self.banner_vak, "err", "Centrale instellingen niet bereikbaar",
                        f"{self.opslag.bestand} kon niet worden geopend ({self.centraal_detail}). Controleer de "
                        "netwerkverbinding of neem contact op met ICT.",
                        knoppen=[("Opnieuw proberen", self._ververs_centraal)],
                        link=("Wat moet ik doen?", probleem)).pack(fill="x", pady=(10, 0))

        self._ververs_reeks()
        if st == "ok":
            d = self.centraal
            self.info_label.configure(text=f"Centraal beheerd · versie {d['versie']} · "
                                           f"{datum_nl(d['gewijzigd']['op'])[:10]}")
        else:
            self.info_label.configure(text="")
        self.start_knop.configure(state="normal" if st == "ok" and not actief else "disabled")
        self.stop_knop.configure(state="normal" if actief else "disabled")
        self.instellingen_knop.configure(state="normal" if st == "ok" and not actief else "disabled")
        self.logboek_knop.configure(state="disabled" if actief else "normal")
        for k in self.modus_knoppen:
            k.configure(state="disabled" if actief else "normal")

    def _vul_reeks_vlak(self, vlak, stappen, modus=None):
        for w in vlak.winfo_children():
            w.destroy()
        for i, (sleutel, naam, alleen_stap3) in enumerate(STAPPEN):
            stap = stappen[sleutel]
            uit = alleen_stap3 and modus == "zonder3"
            stijl = "VlakUit.TLabel" if uit else "Vlak.TLabel"
            achter = " (niet in deze modus)" if uit else (" *" if alleen_stap3 and modus is None else "")
            ttk.Label(vlak, text=f"{i + 1}", style=stijl, width=2).grid(row=i, column=0, sticky="w")
            ttk.Label(vlak, text=naam + achter, style=stijl).grid(row=i, column=1, sticky="w", padx=(0, 10))
            ttk.Label(vlak, text=stap["toetsen"], style="VlakUit.TLabel" if uit else "VlakMono.TLabel").grid(
                row=i, column=2, sticky="w")
            ttk.Label(vlak, text=f"na {formatteer_getal(float(stap['wacht']))} s",
                      style="VlakUit.TLabel" if uit else "VlakKlein.TLabel").grid(row=i, column=3, sticky="e",
                                                                                 padx=(10, 0))
        vlak.columnconfigure(1, weight=1)

    def _ververs_reeks(self):
        if self.centraal_status == "ok":
            self._vul_reeks_vlak(self.reeks_vlak, self.centraal["stappen"], self.modus_var.get())
            trig = self.centraal["trigger"]
            self.trigger_label.configure(text=f"Start met: toets {trig.upper()}" if trig else "Start met: elke toets")
        else:
            for w in self.reeks_vlak.winfo_children():
                w.destroy()
            tekst = "Nog geen reeks ingesteld." if self.centraal_status == "niet_ingericht" else "Reeks niet beschikbaar."
            ttk.Label(self.reeks_vlak, text=tekst, style="VlakKlein.TLabel").grid(row=0, column=0, sticky="w")
            self.trigger_label.configure(text="")

    def _modus_gewijzigd(self):
        self.lokaal["modus"] = self.modus_var.get()
        bewaar_lokaal(self.lokaal)
        self._ververs_reeks()

    # ------------------------------------------------------------ starten en stoppen

    def _start(self):
        if self._actief.is_set():
            return
        self._hoofd_melding = None
        self._ververs_centraal()
        if self.centraal_status != "ok":
            self.melding_label.configure(text="Niet gestart: de centrale instellingen zijn niet in orde. "
                                              "Zie de melding bovenaan.")
            self.logboek.schrijf("FOUT", f"Niet gestart: instellingen {STATUS_TEKST[self.centraal_status]}")
            return
        reeks, fouten = valideer_reeks(self.centraal)
        if fouten:  # kan alleen bij een fout in het programma; zegel en validatie zijn al gecontroleerd
            self.melding_label.configure(text="Niet gestart: " + next(iter(fouten.values())))
            return
        self.melding_label.configure(text="")
        modus = self.modus_var.get()
        self._plan = maak_plan(reeks, modus)
        while True:
            try:
                self._triggers.get_nowait()
            except queue.Empty:
                break
        self._stop.clear()
        self._cycli = 0
        self._reeks_nr = 0
        self._start_moment = time.monotonic()
        self.teller_label.configure(text="Reeksen: 0")
        self._actief.set()
        self._werk_hoofd_bij()
        trig = reeks["trigger"].upper() if reeks["trigger"] else "een toets"
        self._zet_status(f"Actief – klik in het doelvenster en druk op {trig}", GROEN)
        self.logboek.schrijf("START", f"{MODUS_TEKST[modus]} · starttoets {reeks['trigger'].upper() or 'elke toets'} · "
                                      f"instellingen versie {self.centraal['versie']}",
                             modus=modus, trigger=reeks["trigger"], instellingen=self.centraal["versie"])

    def _stop_nu(self, reden):
        """Mag vanuit elke thread worden aangeroepen; raakt Tk niet aan."""
        with self._lock:
            if not self._actief.is_set():
                return
            self._actief.clear()
            self._stop.set()
        self._ui.put(("gestopt", reden))

    def _zet_status(self, tekst, kleur):
        self.status_label.configure(text=tekst)
        self.status_stip.configure(fg=kleur)

    # ------------------------------------------------------------ threads

    def _op_toets(self, event):
        """Draait in de thread van de keyboard-module. Raakt Tk niet aan."""
        naam = normaliseer_toets(event.name)
        if naam == "esc":
            self._stop_nu("Gestopt met Esc")
            return
        if not self._actief.is_set() or self._bezig.is_set():
            return
        if time.monotonic() - self._laatst_verzonden < AFKOELTIJD:
            return
        plan = self._plan
        if plan["trigger"] and naam != plan["trigger"]:
            return
        self._bezig.set()
        try:
            self._triggers.put_nowait(plan)
        except queue.Full:
            pass

    def _werker(self):
        """Eén daemon-thread die reeksen uitvoert. Raakt Tk niet aan."""
        while True:
            plan = self._triggers.get()
            try:
                if self._actief.is_set() and not self._stop.is_set():
                    self._voer_reeks_uit(plan)
            except Exception as e:  # noqa: BLE001
                self.logboek.schrijf("FOUT", f"Reeks gestopt door fout: {e}")
                self._stop_nu(f"Gestopt door fout: {e}")
            finally:
                self._laatst_verzonden = time.monotonic()
                self._bezig.clear()

    def _voer_reeks_uit(self, plan):
        self._reeks_nr += 1
        nr, aantal = self._reeks_nr, len(plan["stappen"])
        self._ui.put(("status", "Reeks wordt uitgevoerd…"))
        begin = time.monotonic()
        verstuurd = 0
        for _naam, toetsen, wacht in plan["stappen"]:
            if self._stop.wait(wacht) or not self._actief.is_set():
                self.logboek.schrijf("AFGEBROKEN", f"Reeks {nr} gestopt na stap {verstuurd} van {aantal}",
                                     nr=nr, na_stap=verstuurd, van=aantal)
                return
            druk_combinatie(toetsen)
            verstuurd += 1
            self._laatst_verzonden = time.monotonic()
        duur = time.monotonic() - begin
        combinaties = ["+".join(t) for _, t, _ in plan["stappen"]]
        self.logboek.schrijf("REEKS", f"Reeks {nr} · {' → '.join(combinaties)} · {formatteer_getal(duur)} s",
                             nr=nr, stappen=combinaties, duur_s=round(duur, 1))
        self._ui.put(("reeks_klaar", None))

    def _verwerk_ui_queue(self):
        """Draait in de hoofdthread via root.after: de enige plek die Tk vanuit threads bijwerkt."""
        try:
            while True:
                soort, data = self._ui.get_nowait()
                if soort == "gestopt":
                    self._na_stop(data)
                elif soort == "status" and self._actief.is_set():
                    self._zet_status(data, BLAUW)
                elif soort == "reeks_klaar" and self._actief.is_set():
                    self._cycli += 1
                    self.teller_label.configure(text=f"Reeksen: {self._cycli}")
                    self._zet_status("Actief – wacht op toets", GROEN)
                elif soort == "opname":
                    self._opname_klaar(*data)
        except queue.Empty:
            pass
        self._periodiek()
        self.root.after(100, self._verwerk_ui_queue)

    def _na_stop(self, reden):
        minuten = (time.monotonic() - self._start_moment) / 60 if self._start_moment else 0
        duur = "minder dan 1 min" if minuten < 1 else f"{round(minuten)} min"
        self.logboek.schrijf("STOP", f"{reden} · {self._cycli} reeksen in {duur}", reeksen=self._cycli)
        self._werk_hoofd_bij()
        self._zet_status(reden, ROOD if "fout" in reden else GRIJS)

    def _periodiek(self):
        # logboek-buffer melding
        getoond = bool(self.buffer_label.winfo_manager())
        if self.logboek.buffer_actief and not getoond:
            self.buffer_label.pack(fill="x", pady=(6, 0), before=self.melding_label)
        elif not self.logboek.buffer_actief and getoond:
            self.buffer_label.pack_forget()
        # automatisch vergrendelen
        if self._ontgrendeld:
            rest = AUTO_VERGRENDEL_SEC - (time.monotonic() - self._laatste_activiteit)
            if rest <= 0:
                self._vergrendel_automatisch()
            elif self._aftel_label is not None and self._aftel_label.winfo_exists():
                r = int(rest)
                self._aftel_label.configure(text=f"Wijzigingen gelden voor alle gebruikers. "
                                                 f"Vergrendelt automatisch over {r // 60}:{r % 60:02d}.")
        # dagelijks opschonen
        if self.centraal_status == "ok" and self._opgeschoond_op != dt.date.today():
            self._opgeschoond_op = dt.date.today()
            self.logboek.opschonen(self.centraal["logboek"]["bewaardagen"])

    def _activiteit(self, _event=None):
        self._laatste_activiteit = time.monotonic()

    # ------------------------------------------------------------ help

    def _help(self, onderwerp=None):
        onderwerp = onderwerp or self._help_onderwerp
        pagina = self.help_paginas.get(onderwerp, 1)
        try:
            manier = open_handleiding(pagina)
        except OSError as e:
            self.logboek.schrijf("FOUT", f"Handleiding kon niet worden geopend: {e}")
            messagebox.showerror(APP_NAAM, f"De handleiding kon niet worden geopend.\n\n{e}", parent=self.root)
            return
        if manier == "pdf-app":
            self.logboek.schrijf("FOUT", "Browser kon niet worden gestart; handleiding geopend in de pdf-app "
                                         "(op pagina 1)")

    # ------------------------------------------------------------ instellingen bekijken

    def _toon_instellingen_lezen(self, melding=None):
        if self._actief.is_set() or self.centraal_status != "ok":
            return
        d = self.centraal
        f = self._scherm("Instellingen")
        maak_banner(f, "lock", None, "Alleen-lezen. Deze instellingen gelden voor alle gebruikers. "
                                     "Wijzigen kan met de beheerpincode.").pack(fill="x", pady=(10, 0))
        if melding:
            maak_banner(f, *melding).pack(fill="x", pady=(8, 0))
        ttk.Label(f, text="START DE REEKS MET", style="Kop.TLabel").pack(anchor="w", pady=(12, 2))
        ttk.Label(f, text=f"Alleen toets {d['trigger'].upper()}" if d["trigger"] else "Elke toets").pack(anchor="w")
        ttk.Label(f, text="STAPPEN", style="Kop.TLabel").pack(anchor="w", pady=(12, 4))
        vlak = ttk.Frame(f, style="Vlak.TFrame", padding=(10, 8))
        vlak.pack(fill="x")
        self._vul_reeks_vlak(vlak, d["stappen"])
        ttk.Label(f, text="* alleen in modus 'Alle stappen'", style="Klein.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(f, text="LOGBOEK", style="Kop.TLabel").pack(anchor="w", pady=(12, 2))
        ttk.Label(f, text=f"Bewaren: {d['logboek']['bewaardagen']} dagen").pack(anchor="w")
        tk.Frame(f, height=1, background=LIJN).pack(fill="x", pady=12)
        g = d["gewijzigd"]
        ttk.Label(f, text=f"Versie {d['versie']} · {datum_nl(g['op'])} · {g['pc']}\nReden: {g['reden']}",
                  style="Klein.TLabel", wraplength=380, justify="left").pack(anchor="w")
        self._knoppenrij(f, [("Terug", self._naar_hoofd, False), ("Ontgrendelen", self._ontgrendel, True)])
        self._toon(f, "instellingen")

    def _ontgrendel(self):
        self._toon_pin_invoer(
            titel="Instellingen ontgrendelen", intro="Voer de beheerpincode in.", controle=self.centraal,
            bij_succes=self._na_ontgrendelen, terug=self._toon_instellingen_lezen, onderwerp="wijzigen")

    def _na_ontgrendelen(self):
        self.logboek.schrijf("INSTELLINGEN", "Instellingen ontgrendeld")
        self._ontgrendeld = True
        self._activiteit()
        self._bewerk = {"modus": "wijzigen", "basis": self.centraal, "concept": concept_uit(self.centraal)}
        self._toon_bewerken()

    def _vergrendel_automatisch(self):
        self.logboek.schrijf("INSTELLINGEN", "Automatisch vergrendeld na 5 minuten zonder activiteit")
        self._ontgrendeld = False
        self._bewerk = self._velden = self._aftel_label = None
        self._ververs_centraal()
        if self.centraal_status == "ok":
            self._toon_instellingen_lezen(("warn", "Automatisch vergrendeld",
                                           "Niet-opgeslagen wijzigingen zijn niet bewaard."))
        else:
            self._toon(self.scherm_hoofd, "hoofdscherm")

    def _vergrendel(self):
        self._ontgrendeld = False
        self._bewerk = self._velden = self._aftel_label = None
        self._ververs_centraal()
        if self.centraal_status == "ok":
            self._toon_instellingen_lezen()
        else:
            self._toon(self.scherm_hoofd, "hoofdscherm")

    # ------------------------------------------------------------ pincode invoeren

    def _pin_blokkade_rest(self):
        return max(0.0, self._pin_geblokkeerd_tot - time.monotonic())

    def _registreer_foute_poging(self, wat):
        """Telt een foute pincode of herstelcode. Geeft de melding terug."""
        self._pin_fouten += 1
        if self._pin_fouten >= MAX_POGINGEN:
            self._pin_fouten = 0
            self._pin_geblokkeerd_tot = time.monotonic() + BLOKKEER_SEC
            self.logboek.schrijf("INSTELLINGEN", f"{MAX_POGINGEN} keer een onjuiste {wat} · "
                                                 f"{BLOKKEER_SEC} seconden geblokkeerd")
            return None
        self.logboek.schrijf("INSTELLINGEN", f"Onjuiste {wat} ingevoerd")
        over = MAX_POGINGEN - self._pin_fouten
        return f"Onjuiste {wat}. Nog {over} {'poging' if over == 1 else 'pogingen'}."

    def _pin_veld(self, parent):
        var = tk.StringVar()
        veld = ttk.Entry(parent, textvariable=var, show="•", width=10, font=("Segoe UI", 16), justify="center",
                         validate="key", validatecommand=(self._vcmd_pin, "%P"))
        return var, veld

    def _toon_pin_invoer(self, *, titel, intro, controle, bij_succes, terug, onderwerp, bron_is_reserve=False):
        f = self._scherm(titel)
        ttk.Label(f, text=intro, style="Klein.TLabel", wraplength=340, justify="left").pack(anchor="w", pady=(8, 8))
        var, veld = self._pin_veld(f)
        veld.pack(anchor="w")
        fout = ttk.Label(f, style="Fout.TLabel", wraplength=340, justify="left")
        fout.pack(anchor="w", pady=(4, 0))
        ttk.Button(f, text="Pincode vergeten?", style="Link.TButton",
                   command=lambda: self._start_herstel(controle, bron_is_reserve, terug)).pack(anchor="w", pady=(6, 0))
        _, knop = self._knoppenrij(f, [("Annuleren", terug, False), ("Ontgrendelen", lambda: controleer(), True)])
        toestand = {"geblokkeerd": False}

        def controleer(_e=None):
            if self._pin_blokkade_rest() > 0:
                return
            pin = var.get()
            if len(pin) != PIN_LENGTE:
                fout.configure(text=f"Vul de {PIN_LENGTE} cijfers van de pincode in.")
                return
            self.root.configure(cursor="watch")
            self.root.update_idletasks()
            try:
                goed = controleer_hash(pin, controle["pincode"])
            finally:
                self.root.configure(cursor="")
            if goed:
                self._pin_fouten = 0
                bij_succes()
                return
            var.set("")
            melding = self._registreer_foute_poging("pincode")
            if melding:
                fout.configure(text=melding)
            bijwerken()

        def bijwerken():
            if not f.winfo_exists():
                return
            rest = self._pin_blokkade_rest()
            if rest > 0:
                toestand["geblokkeerd"] = True
                veld.configure(state="disabled")
                knop.configure(state="disabled")
                r = int(rest) + 1
                fout.configure(text=f"Te veel onjuiste pogingen. Probeer het over {r // 60}:{r % 60:02d} opnieuw.")
                f.after(500, bijwerken)
            elif toestand["geblokkeerd"]:
                toestand["geblokkeerd"] = False
                veld.configure(state="normal")
                knop.configure(state="normal")
                fout.configure(text="")
                veld.focus_set()

        veld.bind("<Return>", controleer)
        self._toon(f, onderwerp)
        bijwerken()
        veld.focus_set()

    # ------------------------------------------------------------ instellingen wijzigen

    def _toon_bewerken(self, banner=None):
        b = self._bewerk
        c = b["concept"]
        inrichten = b["modus"] == "inrichten"
        f = self._scherm("Instellingen")
        if inrichten:
            maak_banner(f, "info", "Inrichten · stap 3 van 3",
                        "Controleer de reeks. Opslaan maakt versie 1 voor alle gebruikers.").pack(fill="x", pady=(10, 0))
            self._aftel_label = None
        else:
            bn = maak_banner(f, "info", "Ontgrendeld", "Wijzigingen gelden voor alle gebruikers.")
            bn.pack(fill="x", pady=(10, 0))
            self._aftel_label = bn.tekst_label
        if banner:
            maak_banner(f, *banner).pack(fill="x", pady=(8, 0))

        nb = ttk.Notebook(f)
        nb.pack(fill="x", pady=(12, 0))
        tab_reeks = ttk.Frame(nb, padding=(12, 10))
        tab_log = ttk.Frame(nb, padding=(12, 10))
        nb.add(tab_reeks, text="Reeks")
        nb.add(tab_log, text="Logboek")
        v = {"notebook": nb, "tabs": (tab_reeks, tab_log)}

        # -- tab Reeks
        ttk.Label(tab_reeks, text="START DE REEKS MET", style="Kop.TLabel").pack(anchor="w")
        v["trigger_modus"] = tk.StringVar(value=c["trigger_modus"])
        ttk.Radiobutton(tab_reeks, text="Elke toets", variable=v["trigger_modus"], value="elke",
                        command=self._trigger_modus_gewijzigd).pack(anchor="w")
        rij = ttk.Frame(tab_reeks)
        rij.pack(anchor="w", fill="x", pady=(2, 0))
        ttk.Radiobutton(rij, text="Alleen deze toets:", variable=v["trigger_modus"], value="vast",
                        command=self._trigger_modus_gewijzigd).pack(side="left")
        v["trigger"] = ttk.Entry(rij, width=8)
        v["trigger"].insert(0, c["trigger"])
        v["trigger"].pack(side="left", padx=(6, 4))
        v["trigger_opname"] = ttk.Button(rij, text="Opnemen", command=lambda: self._neem_op("trigger"))
        v["trigger_opname"].pack(side="left")
        v["trigger_fout"] = ttk.Label(tab_reeks, style="Fout.TLabel", wraplength=380, justify="left")
        v["trigger_fout"].pack(anchor="w")
        ttk.Label(tab_reeks, text="Aanbevolen: een vaste toets zoals F9. Met 'elke toets' start typen in "
                                  "welk programma dan ook een reeks.",
                  style="Klein.TLabel", wraplength=380, justify="left").pack(anchor="w")

        ttk.Label(tab_reeks, text="STAPPEN", style="Kop.TLabel").pack(anchor="w", pady=(12, 4))
        tabel = ttk.Frame(tab_reeks)
        tabel.pack(fill="x")
        for kol, kop in enumerate(("Stap", "Toetscombinatie", "", "Wacht vooraf (s)")):
            ttk.Label(tabel, text=kop, style="Klein.TLabel").grid(row=0, column=kol, sticky="w", padx=(0, 6))
        v["stappen"] = {}
        for i, (sleutel, naam, alleen_stap3) in enumerate(STAPPEN):
            r = 1 + i * 2
            ttk.Label(tabel, text=naam + (" *" if alleen_stap3 else "")).grid(row=r, column=0, sticky="w",
                                                                              padx=(0, 8), pady=(4, 0))
            toetsen = ttk.Entry(tabel, width=16, font=("Consolas", 10))
            toetsen.insert(0, c["stappen"][sleutel]["toetsen"])
            toetsen.grid(row=r, column=1, sticky="w", pady=(4, 0))
            opname = ttk.Button(tabel, text="Opnemen", command=lambda s=sleutel: self._neem_op(s))
            opname.grid(row=r, column=2, padx=6, pady=(4, 0))
            wacht = ttk.Entry(tabel, width=6, justify="right")
            wacht.insert(0, c["stappen"][sleutel]["wacht"])
            wacht.grid(row=r, column=3, sticky="w", pady=(4, 0))
            fout = ttk.Label(tabel, style="Fout.TLabel", wraplength=380, justify="left")
            fout.grid(row=r + 1, column=0, columnspan=4, sticky="w")
            v["stappen"][sleutel] = (toetsen, opname, wacht, fout)
        ttk.Label(tab_reeks, text="* alleen in modus 'Alle stappen'. Schrijf combinaties als ctrl+alt+1. "
                                  "Esc kan niet, die is voor stoppen.",
                  style="Klein.TLabel", wraplength=380, justify="left").pack(anchor="w", pady=(6, 0))
        v["opname_label"] = ttk.Label(tab_reeks, style="Kop.TLabel", foreground=BLAUW)
        v["opname_label"].pack(anchor="w", pady=(4, 0))
        ttk.Button(tab_reeks, text="Standaard herstellen", command=self._herstel_standaard).pack(anchor="w",
                                                                                             pady=(6, 0))

        # -- tab Logboek
        ttk.Label(tab_log, text="BEWAARTERMIJN", style="Kop.TLabel").pack(anchor="w")
        rij = ttk.Frame(tab_log)
        rij.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(rij, text="Bewaren").pack(side="left")
        v["bewaardagen"] = ttk.Entry(rij, width=6, justify="right")
        v["bewaardagen"].insert(0, c["bewaardagen"])
        v["bewaardagen"].pack(side="left", padx=6)
        ttk.Label(rij, text="dagen").pack(side="left")
        ttk.Button(rij, text="Logmap openen", command=self._open_logmap).pack(side="right")
        v["bewaardagen_fout"] = ttk.Label(tab_log, style="Fout.TLabel")
        v["bewaardagen_fout"].pack(anchor="w")
        ttk.Label(tab_log, text=f"Oudere regels worden één keer per dag automatisch verwijderd. "
                                f"Toegestaan: {BEWAAR_MIN} tot {BEWAAR_MAX} dagen. Het logboek bevat geen namen "
                                "en niets van wat er op het scherm staat.",
                  style="Klein.TLabel", wraplength=380, justify="left").pack(anchor="w", pady=(6, 0))

        v["algemeen_fout"] = ttk.Label(f, style="Fout.TLabel", wraplength=400, justify="left")
        v["algemeen_fout"].pack(anchor="w", pady=(6, 0))
        if not inrichten:
            ttk.Button(f, text="Pincode wijzigen", style="Link.TButton",
                       command=self._toon_pin_wijzigen).pack(anchor="w")
            self._knoppenrij(f, [("Vergrendelen", self._vergrendel, False),
                                 ("Opslaan…", self._bewerken_opslaan, True)])
        else:
            self._knoppenrij(f, [("Annuleren", self._naar_hoofd, False),
                                 ("Opslaan", self._bewerken_opslaan, True)])
        self._velden = v
        self._trigger_modus_gewijzigd()
        if not inrichten:
            for w in self._alle_invoervelden():
                w.bind("<KeyRelease>", lambda _e: self._markeer_wijzigingen(), add="+")
            self._markeer_wijzigingen()
        self._toon(f, "inrichten" if inrichten else "wijzigen")

    def _alle_invoervelden(self):
        v = self._velden
        velden = [v["trigger"], v["bewaardagen"]]
        for toetsen, _, wacht, _ in v["stappen"].values():
            velden += [toetsen, wacht]
        return velden

    def _trigger_modus_gewijzigd(self):
        v = self._velden
        if not v:
            return
        staat = "normal" if v["trigger_modus"].get() == "vast" else "disabled"
        v["trigger"].configure(state=staat)
        v["trigger_opname"].configure(state=staat)
        self._markeer_wijzigingen()

    def _lees_concept(self):
        v = self._velden
        return {
            "trigger_modus": v["trigger_modus"].get(),
            "trigger": v["trigger"].get().strip().lower(),
            "stappen": {s: {"toetsen": v["stappen"][s][0].get().strip().lower(),
                            "wacht": v["stappen"][s][2].get().strip()} for s, _, _ in STAPPEN},
            "bewaardagen": v["bewaardagen"].get().strip(),
        }

    @staticmethod
    def _reeks_uit_concept(c):
        return {
            "trigger": c["trigger"] if c["trigger_modus"] == "vast" else "",
            "stappen": {s: dict(c["stappen"][s]) for s, _, _ in STAPPEN},
            "logboek": {"bewaardagen": c["bewaardagen"]},
        }

    def _markeer_wijzigingen(self):
        """Kleurt velden blauw die afwijken van de opgeslagen versie (alleen bij wijzigen)."""
        b, v = self._bewerk, self._velden
        if not b or not v or b["modus"] != "wijzigen":
            return
        oud = concept_uit(b["basis"])
        nieuw = self._lees_concept()

        def stijl(veld, gelijk):
            if veld.cget("style") != "Fout.TEntry":
                veld.configure(style="TEntry" if gelijk else "Gewijzigd.TEntry")

        trig_oud = oud["trigger"] if oud["trigger_modus"] == "vast" else ""
        trig_nieuw = nieuw["trigger"] if nieuw["trigger_modus"] == "vast" else ""
        stijl(v["trigger"], trig_oud == trig_nieuw)
        stijl(v["bewaardagen"], oud["bewaardagen"] == nieuw["bewaardagen"])
        for s, _, _ in STAPPEN:
            stijl(v["stappen"][s][0], oud["stappen"][s]["toetsen"] == nieuw["stappen"][s]["toetsen"])
            stijl(v["stappen"][s][2], oud["stappen"][s]["wacht"] == nieuw["stappen"][s]["wacht"])

    def _toon_veldfouten(self, fouten):
        v = self._velden
        v["trigger_fout"].configure(text=fouten.get("trigger", ""))
        v["trigger"].configure(style="Fout.TEntry" if "trigger" in fouten else "TEntry")
        for sleutel, _, _ in STAPPEN:
            toetsen, _, wacht, fout = v["stappen"][sleutel]
            ft, fw = fouten.get(f"{sleutel}.toetsen"), fouten.get(f"{sleutel}.wacht")
            toetsen.configure(style="Fout.TEntry" if ft else "TEntry")
            wacht.configure(style="Fout.TEntry" if fw else "TEntry")
            fout.configure(text="  ".join(m for m in (ft, fw) if m))
        v["bewaardagen_fout"].configure(text=fouten.get("bewaardagen", ""))
        v["bewaardagen"].configure(style="Fout.TEntry" if "bewaardagen" in fouten else "TEntry")
        v["algemeen_fout"].configure(text="")
        if fouten:
            tab = 1 if set(fouten) == {"bewaardagen"} else 0
            v["notebook"].select(v["tabs"][tab])
        self._markeer_wijzigingen()

    def _herstel_standaard(self):
        v = self._velden
        c = concept_uit(STANDAARD_REEKS)
        v["trigger_modus"].set(c["trigger_modus"])
        for veld, waarde in [(v["trigger"], c["trigger"])] + [
                (v["stappen"][s][0], c["stappen"][s]["toetsen"]) for s, _, _ in STAPPEN] + [
                (v["stappen"][s][2], c["stappen"][s]["wacht"]) for s, _, _ in STAPPEN]:
            staat = str(veld.cget("state"))
            veld.configure(state="normal")
            veld.delete(0, "end")
            veld.insert(0, waarde)
            veld.configure(state=staat)
        self._trigger_modus_gewijzigd()
        self._toon_veldfouten({})

    def _bewerken_opslaan(self):
        if self._opname_bezig:
            return
        b = self._bewerk
        concept = self._lees_concept()
        b["concept"] = concept
        reeks, fouten = valideer_reeks(self._reeks_uit_concept(concept))
        if concept["trigger_modus"] == "vast" and not concept["trigger"]:
            fouten["trigger"] = "Vul een toets in, of kies 'Elke toets'."
        self._toon_veldfouten(fouten)
        if fouten:
            return
        if b["modus"] == "inrichten":
            self._inrichten_opslaan(reeks)
            return
        oud, _ = valideer_reeks(b["basis"])
        wijzigingen = verschillen(oud, reeks)
        if not wijzigingen:
            self._velden["algemeen_fout"].configure(text="Er is niets gewijzigd.")
            return
        self._toon_bevestigen(reeks, wijzigingen)

    def _toon_bevestigen(self, reeks, wijzigingen):
        b = self._bewerk
        f = self._scherm("Opslaan voor alle gebruikers?")
        self._aftel_label = None
        ttk.Label(f, text="WIJZIGINGEN", style="Kop.TLabel").pack(anchor="w", pady=(12, 4))
        vlak = ttk.Frame(f, style="Vlak.TFrame", padding=(10, 8))
        vlak.pack(fill="x")
        for i, (onderwerp, oud, nieuw) in enumerate(wijzigingen):
            ttk.Label(vlak, text=onderwerp, style="Vlak.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 12))
            ttk.Label(vlak, text=f"{oud}  →  {nieuw}", style="VlakMono.TLabel").grid(row=i, column=1, sticky="w")
        ttk.Label(f, text="REDEN VAN WIJZIGING (VERPLICHT)", style="Kop.TLabel").pack(anchor="w", pady=(12, 4))
        reden = ttk.Entry(f, width=48)
        reden.pack(anchor="w", fill="x")
        fout = ttk.Label(f, style="Fout.TLabel", wraplength=380, justify="left")
        fout.pack(anchor="w", pady=(4, 0))
        ttk.Label(f, text=f"Wordt versie {b['basis']['versie'] + 1}. Andere gebruikers krijgen dit bij hun "
                          "volgende Start.", style="Klein.TLabel", wraplength=380, justify="left").pack(anchor="w")

        def opslaan():
            tekst_reden = reden.get().strip()
            if len(tekst_reden) < 3:
                fout.configure(text="Vul een reden in. Die komt in het logboek en bij de instellingen.")
                return
            nieuw = copy.deepcopy(b["basis"])
            nieuw.update(trigger=reeks["trigger"], stappen=reeks["stappen"], logboek=reeks["logboek"])
            omschrijving = "; ".join(f"{o}: {a} → {n}" for o, a, n in wijzigingen)
            try:
                opgeslagen = self.opslag.opslaan(nieuw, b["basis"]["versie"], tekst_reden, omschrijving)
            except Conflict as c:
                self._toon_conflict(c.data)
                return
            except OSError as e:
                fout.configure(text=f"Opslaan is mislukt: {e}")
                return
            self.logboek.schrijf("INSTELLINGEN", f"Versie {opgeslagen['versie']} opgeslagen op {PC_NAAM} · "
                                                 f"{omschrijving} · reden: {tekst_reden}",
                                 versie=opgeslagen["versie"])
            self._hoofd_melding = ("ok", f"Opgeslagen als versie {opgeslagen['versie']}",
                                   "De instellingen zijn weer vergrendeld. Andere pc's gebruiken deze versie bij "
                                   "hun volgende Start.")
            self._naar_hoofd()

        reden.bind("<Return>", lambda _e: opslaan())
        self._knoppenrij(f, [("Terug", lambda: self._toon_bewerken(), False),
                             ("Opslaan voor iedereen", opslaan, True)])
        self._toon(f, "wijzigen")
        reden.focus_set()

    def _toon_conflict(self, data):
        self._ontgrendeld = False
        self._bewerk = self._velden = self._aftel_label = None
        if data:
            g = data["gewijzigd"]
            self.logboek.schrijf("INSTELLINGEN", f"Opslaan geweigerd: versie {data['versie']} is intussen "
                                                 f"opgeslagen door {g['pc']}")
            tekst = (f"Iemand anders heeft de instellingen intussen opgeslagen als versie {data['versie']} "
                     f"({datum_nl(g['op'])}, {g['pc']}). Uw wijzigingen zijn niet opgeslagen.")
        else:
            self.logboek.schrijf("INSTELLINGEN", "Opslaan geweigerd: de centrale instellingen zijn intussen veranderd")
            tekst = "De centrale instellingen zijn intussen veranderd. Uw wijzigingen zijn niet opgeslagen."
        f = self._scherm("Niet opgeslagen")
        maak_banner(f, "warn", None, tekst).pack(fill="x", pady=(10, 0))
        ttk.Label(f, text="Laad de nieuwe versie, bekijk die en voer uw wijziging zo nodig opnieuw in.",
                  style="Klein.TLabel", wraplength=380, justify="left").pack(anchor="w", pady=(10, 0))

        def laden():
            self._ververs_centraal()
            if self.centraal_status == "ok":
                self._toon_instellingen_lezen()
            else:
                self._naar_hoofd()

        self._knoppenrij(f, [("Nieuwe versie laden", laden, True)])
        self._toon(f, "problemen")

    # ------------------------------------------------------------ pincode wijzigen

    def _toon_pin_wijzigen(self):
        b = self._bewerk
        concept = self._lees_concept()
        if concept != concept_uit(b["basis"]):
            self._velden["algemeen_fout"].configure(
                text="Sla uw wijzigingen eerst op, of maak ze ongedaan met Vergrendelen, voordat u de pincode wijzigt.")
            return
        f = self._scherm("Pincode wijzigen")
        bn = maak_banner(f, "info", "Ontgrendeld", "")
        bn.pack(fill="x", pady=(10, 0))
        self._aftel_label = bn.tekst_label
        velden = {}
        for sleutel, label in (("huidig", "Huidige pincode"), ("nieuw", "Nieuwe pincode"), ("herhaal", "Herhaal nieuwe pincode")):
            ttk.Label(f, text=label.upper(), style="Kop.TLabel").pack(anchor="w", pady=(10, 2))
            var, veld = self._pin_veld(f)
            veld.pack(anchor="w")
            velden[sleutel] = var
        ttk.Label(f, text="6 cijfers. Niet zes keer hetzelfde cijfer en geen reeks zoals 123456.",
                  style="Klein.TLabel").pack(anchor="w", pady=(6, 0))
        fout = ttk.Label(f, style="Fout.TLabel", wraplength=380, justify="left")
        fout.pack(anchor="w", pady=(4, 0))

        def opslaan():
            if self._pin_blokkade_rest() > 0:
                fout.configure(text="Te veel onjuiste pogingen. Probeer het over een minuut opnieuw.")
                return
            huidig, nieuw, herhaal = (velden[k].get() for k in ("huidig", "nieuw", "herhaal"))
            if not controleer_hash(huidig, b["basis"]["pincode"]):
                velden["huidig"].set("")
                melding = self._registreer_foute_poging("pincode")
                fout.configure(text=melding or "Te veel onjuiste pogingen. Probeer het over een minuut opnieuw.")
                return
            probleem = pincode_fout(nieuw) or (None if nieuw == herhaal else "De twee nieuwe pincodes zijn niet gelijk.")
            if probleem:
                fout.configure(text=probleem)
                return
            data = copy.deepcopy(b["basis"])
            data["pincode"] = maak_hash(nieuw)
            try:
                opgeslagen = self.opslag.opslaan(data, b["basis"]["versie"], "Pincode gewijzigd", "pincode gewijzigd")
            except Conflict as c:
                self._toon_conflict(c.data)
                return
            except OSError as e:
                fout.configure(text=f"Opslaan is mislukt: {e}")
                return
            self.logboek.schrijf("INSTELLINGEN", f"Pincode gewijzigd · versie {opgeslagen['versie']}",
                                 versie=opgeslagen["versie"])
            self.centraal = opgeslagen
            self._bewerk = {"modus": "wijzigen", "basis": opgeslagen, "concept": concept_uit(opgeslagen)}
            self._toon_bewerken(banner=("ok", f"Pincode gewijzigd (versie {opgeslagen['versie']})", None))

        self._knoppenrij(f, [("Terug", lambda: self._toon_bewerken(), False), ("Opslaan", opslaan, True)])
        self._toon(f, "wijzigen")

    # ------------------------------------------------------------ inrichten

    def _toon_pin_nieuw(self, *, stap, titel, intro, volgende, annuleren, onderwerp):
        f = self._scherm(titel, stap)
        ttk.Label(f, text=intro, style="Klein.TLabel", wraplength=360, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(f, text="NIEUWE PINCODE", style="Kop.TLabel").pack(anchor="w", pady=(10, 2))
        var1, veld1 = self._pin_veld(f)
        veld1.pack(anchor="w")
        ttk.Label(f, text="HERHAAL PINCODE", style="Kop.TLabel").pack(anchor="w", pady=(10, 2))
        var2, veld2 = self._pin_veld(f)
        veld2.pack(anchor="w")
        ttk.Label(f, text="6 cijfers. Niet zes keer hetzelfde cijfer en geen reeks zoals 123456.",
                  style="Klein.TLabel").pack(anchor="w", pady=(6, 0))
        fout = ttk.Label(f, style="Fout.TLabel", wraplength=360, justify="left")
        fout.pack(anchor="w", pady=(4, 0))

        def verder(_e=None):
            probleem = pincode_fout(var1.get()) or (None if var1.get() == var2.get()
                                                    else "De twee pincodes zijn niet gelijk.")
            if probleem:
                fout.configure(text=probleem)
                return
            volgende(var1.get())

        veld2.bind("<Return>", verder)
        self._knoppenrij(f, [("Annuleren", annuleren, False), ("Volgende", verder, True)])
        self._toon(f, onderwerp)
        veld1.focus_set()

    def _toon_herstelcode(self, *, stap, code, volgende, onderwerp):
        f = self._scherm("Bewaar de herstelcode", stap)
        ttk.Label(f, text="Met deze code stelt u een nieuwe pincode in als de pincode vergeten is. De code wordt "
                          "maar één keer getoond.", style="Klein.TLabel", wraplength=360,
                  justify="left").pack(anchor="w", pady=(8, 8))
        ttk.Label(f, text=code, style="Code.TLabel", anchor="center").pack(fill="x")
        ttk.Label(f, text="Bewaar hem in de kluis of wachtwoordmanager van de afdeling, niet bij de pincode.",
                  style="Klein.TLabel", wraplength=360, justify="left").pack(anchor="w", pady=(8, 8))
        bewaard = tk.BooleanVar(value=False)

        def kopieer():
            self.root.clipboard_clear()
            self.root.clipboard_append(code)

        ttk.Checkbutton(f, text="Ik heb de herstelcode veilig bewaard", variable=bewaard,
                        command=lambda: knop.configure(state="normal" if bewaard.get() else "disabled")).pack(anchor="w")
        (knop,) = self._knoppenrij(f, [("Volgende", volgende, True)], links=[("Kopiëren", kopieer)])
        knop.configure(state="disabled")
        self._toon(f, onderwerp)

    def _start_inrichten(self):
        self._ververs_centraal()
        if self.centraal_status != "niet_ingericht":
            return
        wizard = {}

        def stap2(pin):
            wizard["pincode"] = maak_hash(pin)
            code = maak_herstelcode()
            wizard["herstelcode"] = maak_hash(normaliseer_herstelcode(code))
            self._toon_herstelcode(stap="Inrichten · stap 2 van 3", code=code, volgende=stap3, onderwerp="inrichten")

        def stap3():
            self._bewerk = {"modus": "inrichten", "basis": None, "concept": concept_uit(STANDAARD_REEKS),
                            "wizard": wizard}
            self._toon_bewerken()

        self._toon_pin_nieuw(stap="Inrichten · stap 1 van 3", titel="Kies een beheerpincode",
                             intro="Met deze pincode kan iedereen die hem kent de instellingen wijzigen voor alle "
                                   "gebruikers.", volgende=stap2, annuleren=self._naar_hoofd, onderwerp="inrichten")

    def _inrichten_opslaan(self, reeks):
        w = self._bewerk["wizard"]
        data = {"pincode": w["pincode"], "herstelcode": w["herstelcode"], **reeks}
        try:
            opgeslagen = self.opslag.opslaan(data, None, "Eerste inrichting", "eerste inrichting")
        except Conflict as c:
            self._toon_conflict(c.data)
            return
        except OSError as e:
            self._velden["algemeen_fout"].configure(text=f"Opslaan is mislukt: {e}")
            return
        self.logboek.schrijf("INSTELLINGEN", f"Ingericht op {PC_NAAM} · versie {opgeslagen['versie']}",
                             versie=opgeslagen["versie"])
        self._hoofd_melding = ("ok", "Ingericht als versie 1", "Het programma is klaar voor gebruik.")
        self._naar_hoofd()

    # ------------------------------------------------------------ pincode vergeten en reservekopie

    def _start_herstel(self, bron, bron_is_reserve, terug):
        f = self._scherm("Nieuwe pincode instellen")
        ttk.Label(f, text="Voer de herstelcode in die bij het inrichten is getoond.", style="Klein.TLabel",
                  wraplength=360, justify="left").pack(anchor="w", pady=(8, 8))
        ttk.Label(f, text="HERSTELCODE", style="Kop.TLabel").pack(anchor="w")
        veld = ttk.Entry(f, width=18, font=("Consolas", 13))
        veld.pack(anchor="w", pady=(2, 0))
        fout = ttk.Label(f, style="Fout.TLabel", wraplength=360, justify="left")
        fout.pack(anchor="w", pady=(4, 0))
        ttk.Label(f, text="Daarna kiest u een nieuwe pincode en krijgt u een nieuwe herstelcode. De huidige "
                          "herstelcode vervalt.", style="Klein.TLabel", wraplength=360,
                  justify="left").pack(anchor="w", pady=(6, 0))
        nieuw = {}

        def verder(_e=None):
            if self._pin_blokkade_rest() > 0:
                fout.configure(text="Te veel onjuiste pogingen. Probeer het over een minuut opnieuw.")
                return
            code = normaliseer_herstelcode(veld.get())
            if not code or not controleer_hash(code, bron.get("herstelcode", {})):
                melding = self._registreer_foute_poging("herstelcode")
                fout.configure(text=melding or "Te veel onjuiste pogingen. Probeer het over een minuut opnieuw.")
                return
            self._pin_fouten = 0
            self._toon_pin_nieuw(stap="Nieuwe pincode · stap 1 van 2", titel="Kies een nieuwe pincode",
                                 intro="Kies een nieuwe beheerpincode.", volgende=stap2, annuleren=terug,
                                 onderwerp="problemen")

        def stap2(pin):
            nieuw["pincode"] = maak_hash(pin)
            code = maak_herstelcode()
            nieuw["herstelcode"] = maak_hash(normaliseer_herstelcode(code))
            self._toon_herstelcode(stap="Nieuwe pincode · stap 2 van 2", code=code, volgende=opslaan,
                                   onderwerp="problemen")

        def opslaan():
            data = copy.deepcopy(bron)
            data.update(nieuw)
            try:
                opgeslagen = self.opslag.opslaan(data, bron["versie"], "Pincode opnieuw ingesteld met herstelcode",
                                                 "pincode opnieuw ingesteld", controleer=not bron_is_reserve)
            except Conflict as c:
                self._toon_conflict(c.data)
                return
            except OSError as e:
                self._hoofd_melding = ("err", "Nieuwe pincode niet opgeslagen", str(e))
                self._naar_hoofd()
                return
            self.logboek.schrijf("INSTELLINGEN", f"Pincode opnieuw ingesteld met herstelcode · versie "
                                                 f"{opgeslagen['versie']}", versie=opgeslagen["versie"])
            self._hoofd_melding = ("ok", f"Nieuwe pincode ingesteld (versie {opgeslagen['versie']})",
                                   "Bewaar de nieuwe herstelcode goed. De oude werkt niet meer.")
            self._naar_hoofd()

        veld.bind("<Return>", verder)
        self._knoppenrij(f, [("Annuleren", terug, False), ("Volgende", verder, True)])
        self._toon(f, "problemen")
        veld.focus_set()

    def _start_terugzetten(self):
        reserve = self.opslag.lees_reserve()
        if not reserve:
            self._ververs_centraal()
            return
        self._toon_pin_invoer(
            titel="Reservekopie terugzetten",
            intro=f"Voer de beheerpincode in om versie {reserve['versie']} van "
                  f"{datum_nl(reserve['gewijzigd']['op'])} terug te zetten.",
            controle=reserve, bij_succes=lambda: self._terugzetten(), terug=self._naar_hoofd,
            onderwerp="problemen", bron_is_reserve=True)

    def _terugzetten(self):
        try:
            data = self.opslag.herstel_reserve()
        except (OSError, ValueError) as e:
            self._hoofd_melding = ("err", "Terugzetten is mislukt", str(e))
            self._naar_hoofd()
            return
        self.logboek.schrijf("INSTELLINGEN", f"Reservekopie teruggezet · versie {data['versie']}", versie=data["versie"])
        self._hoofd_melding = ("ok", f"Reservekopie teruggezet (versie {data['versie']})", "Starten kan weer.")
        self._naar_hoofd()

    # ------------------------------------------------------------ opnemen van toetsen

    def _neem_op(self, doel):
        v = self._velden
        if self._opname_bezig or self._actief.is_set() or not v:
            return
        self._opname_bezig = True
        v["opname_label"].configure(
            text="Druk nu de toets in…  (Esc = annuleren)" if doel == "trigger"
            else "Druk nu de combinatie in en laat los…  (Esc = annuleren)")

        def opnemen():
            try:
                if doel == "trigger":
                    while True:
                        ev = keyboard.read_event(suppress=False)
                        if ev.event_type == keyboard.KEY_DOWN:
                            resultaat = ev.name or ""
                            break
                else:
                    resultaat = keyboard.read_hotkey(suppress=False)
            except Exception:  # noqa: BLE001 - opname mag de app nooit stoppen
                resultaat = ""
            self._ui.put(("opname", (doel, resultaat)))

        threading.Thread(target=opnemen, daemon=True).start()

    def _opname_klaar(self, doel, resultaat):
        self._opname_bezig = False
        v = self._velden
        if not v or not v["opname_label"].winfo_exists():
            return
        v["opname_label"].configure(text="")
        delen = [normaliseer_toets(d) for d in resultaat.split("+") if d.strip()]
        if not delen or "esc" in delen:
            return
        veld = v["trigger"] if doel == "trigger" else v["stappen"][doel][0]
        veld.delete(0, "end")
        veld.insert(0, delen[0] if doel == "trigger" else "+".join(delen))
        self._markeer_wijzigingen()

    # ------------------------------------------------------------ logboek

    def _open_logmap(self):
        try:
            os.makedirs(self.opslag.logmap, exist_ok=True)
            os.startfile(self.opslag.logmap)
        except OSError as e:
            messagebox.showerror(APP_NAAM, f"De logmap kon niet worden geopend.\n\n{e}", parent=self.root)

    def _toon_logboek(self):
        if self._actief.is_set():
            return
        f = self._scherm("Logboek")
        filters = ttk.Frame(f)
        filters.pack(fill="x", pady=(10, 6))
        deze_pc = f"Deze pc ({PC_NAAM})"
        pc_keuzes = [deze_pc, "Alle pc's"] + [p for p in self.logboek.pcs() if p != PC_NAAM]
        pc_var, periode_var, soort_var = tk.StringVar(value=deze_pc), tk.StringVar(value="Vandaag"), \
            tk.StringVar(value="Alle soorten")
        for var, keuzes, breedte in ((pc_var, pc_keuzes, 22), (periode_var, list(PERIODES), 18),
                                     (soort_var, list(SOORT_GROEPEN), 18)):
            cb = ttk.Combobox(filters, textvariable=var, values=keuzes, state="readonly", width=breedte)
            cb.pack(side="left", padx=(0, 6))
            cb.bind("<<ComboboxSelected>>", lambda _e: laad())

        lijst = ttk.Frame(f)
        lijst.pack(fill="both", expand=True)
        boom = ttk.Treeview(lijst, columns=("tijd", "pc", "soort", "details"), show="headings", height=15)
        for kol, kop, breedte in (("tijd", "Tijd", 130), ("pc", "Pc", 100), ("soort", "Soort", 100),
                                  ("details", "Details", 360)):
            boom.heading(kol, text=kop, anchor="w")
            boom.column(kol, width=breedte, anchor="w", stretch=kol == "details")
        boom.tag_configure("warn", background="#FFF8EC", foreground="#7A4B00")
        boom.tag_configure("err", background="#FDF1F0", foreground="#7A1A14")
        boom.tag_configure("inst", foreground=BLAUW)
        schuif = ttk.Scrollbar(lijst, orient="vertical", command=boom.yview)
        boom.configure(yscrollcommand=schuif.set)
        boom.pack(side="left", fill="both", expand=True)
        schuif.pack(side="right", fill="y")

        bewaar = self.centraal["logboek"]["bewaardagen"] if self.centraal_status == "ok" else "?"
        voet = ttk.Label(f, style="Klein.TLabel")
        voet.pack(anchor="w", pady=(6, 0))
        rijen = []

        def laad():
            keuze = pc_var.get()
            pcs = [PC_NAAM] if keuze == deze_pc else (None if keuze == "Alle pc's" else [keuze])
            dagen = PERIODES[periode_var.get()]
            vanaf = "0000-00-00" if dagen is None else (dt.date.today() - dt.timedelta(days=dagen)).isoformat()
            soorten = SOORT_GROEPEN[soort_var.get()]
            self.root.configure(cursor="watch")
            self.root.update_idletasks()
            try:
                records = [r for r in self.logboek.lees(pcs, vanaf) if soorten is None or r.get("soort") in soorten]
            finally:
                self.root.configure(cursor="")
            boom.delete(*boom.get_children())
            rijen.clear()
            for r in records:
                tijd = datum_nl(r.get("tijd")) + r.get("tijd", "")[16:19]
                soort = r.get("soort", "")
                tag = {"AFGEBROKEN": "warn", "FOUT": "err", "INSTELLINGEN": "inst"}.get(soort, "")
                rij = (tijd, r.get("pc", ""), soort, r.get("tekst", ""))
                rijen.append(rij)
                boom.insert("", "end", values=rij, tags=(tag,) if tag else ())
            voet.configure(text=f"{len(records)} regels · bewaard: {bewaar} dagen · bevat geen namen of "
                                "schermgegevens")

        def exporteer():
            pad = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv",
                                               filetypes=[("CSV-bestand", "*.csv")],
                                               initialfile=f"logboek-{dt.date.today().isoformat()}.csv")
            if not pad:
                return
            try:
                with open(pad, "w", newline="", encoding="utf-8-sig") as fh:
                    schrijver = csv.writer(fh, delimiter=";")
                    schrijver.writerow(("Tijd", "Pc", "Soort", "Details"))
                    schrijver.writerows(rijen)
            except OSError as e:
                messagebox.showerror(APP_NAAM, f"Exporteren is mislukt.\n\n{e}", parent=self.root)

        self._knoppenrij(f, [("Exporteren (CSV)", exporteer, False), ("Terug", self._naar_hoofd, True)],
                         links=[("Logmap openen", self._open_logmap)])
        laad()
        self._toon(f, "logboek")

    # ------------------------------------------------------------ afsluiten

    def _afsluiten(self):
        self._stop_nu("Afgesloten")
        try:  # een eventuele stopmelding nog in het logboek zetten
            while True:
                soort, data = self._ui.get_nowait()
                if soort == "gestopt":
                    self._na_stop(data)
        except queue.Empty:
            pass
        self.logboek.sluit()
        try:
            keyboard.unhook_all()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
