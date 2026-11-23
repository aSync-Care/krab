# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) 2026 aSync B.V.
# SPDX-License-Identifier: MIT
#
# Bouwen van Krab (zie README.md):
#   1. python handleiding/maak_schermafdrukken.py   (alleen als de schermen zijn veranderd)
#   2. python handleiding/bouw_handleiding.py       (maakt handleiding.pdf + handleiding_paginas.json)
#   3. pyinstaller --noconfirm krab.spec
# De handleiding en de paginanummers voor Help gaan mee in de exe.


a = Analysis(
    ['krab.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icoon.png', '.'),
        ('handleiding/handleiding.pdf', '.'),
        ('handleiding/handleiding_paginas.json', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pyautogui', 'pymupdf', 'fitz', 'PIL'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Krab-v3.1beta',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icoon.ico'],
)
