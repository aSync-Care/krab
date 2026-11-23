# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
"""Nagebootste 'pydirectinput'-module voor tests en schermafdrukken.

Verstuurt geen echte toetsaanslagen, maar houdt ze bij in LOG. Net als in
het echt komen de 'verstuurde' toetsen ook bij de toetsenbord-hook binnen,
zodat getest wordt dat eigen toetsen geen nieuwe reeks starten.
"""

import string
import time

KEYBOARD_MAPPING = {k: 1 for k in list(string.ascii_lowercase) + list(string.digits)
                    + ["ctrl", "alt", "shift", "win", "esc", "escape", "enter", "space", "tab",
                       "pageup", "pagedown"] + [f"f{i}" for i in range(1, 13)]}
LOG = []
HOOK = None


def keyDown(toets):  # noqa: N802 - zelfde naam als pydirectinput
    LOG.append(("down", toets, time.monotonic()))
    if HOOK:
        HOOK(type("E", (), {"name": toets, "event_type": "down"})())


def keyUp(toets):  # noqa: N802
    LOG.append(("up", toets, time.monotonic()))
