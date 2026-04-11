# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas_sel, bins_sel, hidden_sel = collect_all('selenium')
datas_wdm, bins_wdm, hidden_wdm = collect_all('webdriver_manager')

a = Analysis(
    ['SendMessage.py'],
    pathex=[],
    binaries=bins_sel + bins_wdm,
    datas=datas_sel + datas_wdm,
    hiddenimports=hidden_sel + hidden_wdm + [
        'pkg_resources',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',
        'requests',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WhatsApp_Notifier',
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
    icon=None,
)
