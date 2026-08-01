# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file cho CNPS Generator.
Mode: --onedir (thư mục)
"""
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect hidden imports & data files
hiddenimports = [
    'docx',
    'PIL',
    'PIL.Image',
    'numpy',
    'playwright',
    'playwright.async_api',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
]

datas = [
    ('data/CNPS template.docx', 'data'),
    ('data/Bang_Ke_Mau.csv', 'data'),
    ('data/Bang_Ke_Mau.xlsx', 'data'),
    ('src/core/Readability.js', 'src/core'),
    ('src/core/Readability.js', 'core'),
    ('chromium', 'chromium'),
]

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'pandas', 'IPython'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CNPS_Generator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI application, no console window
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CNPS_Generator',
)
