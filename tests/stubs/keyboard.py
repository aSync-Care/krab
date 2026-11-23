# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
"""Nagebootste 'keyboard'-module voor tests en schermafdrukken.

Plaatst geen echte toetsenbord-hook. Toetsaanslagen worden in de tests
gesimuleerd door App._op_toets direct aan te roepen.
"""

KEY_DOWN = "down"
_hooks = []


def on_press(callback):
    _hooks.append(callback)
    import pydirectinput
    pydirectinput.HOOK = callback


def unhook_all():
    _hooks.clear()


def read_event(suppress=False):
    raise RuntimeError("read_event wordt in de tests niet gebruikt")


def read_hotkey(suppress=False):
    return "left ctrl+right alt+K"
