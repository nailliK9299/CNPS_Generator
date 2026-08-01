# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file cho CNPS Generator trên macOS.
Mode: BUNDLE (.app)
"""
import os
import sys
from pathlib import Path

block_cipher = None

# Hidden imports cho macOS
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
]

# Tự động tìm thư mục Chromium của Playwright trên macOS nếu có
pw_cache = Path.home() / "Library/Caches/ms-playwright"
if pw_cache.exists():
    for chromium_dir in pw_cache.glob("chromium-*"):
        if chromium_dir.is_dir():
            datas.append((str(chromium_dir), f"chromium/{chromium_dir.name}"))

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
    console=False,
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

app = BUNDLE(
    coll,
    name='CNPS_Generator.app',
    icon=None,
    bundle_identifier='com.cnps.generator',
    info_plist={
        'NSHighResolutionCapable': 'True',
        'LSBackgroundOnly': 'False',
        'CFBundleShortVersionString': '1.0.0',
    },
)
