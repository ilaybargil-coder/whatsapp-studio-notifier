# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas_sel, bins_sel, hidden_sel = collect_all('selenium')
datas_wdm, bins_wdm, hidden_wdm = collect_all('webdriver_manager')
datas_pil, bins_pil, hidden_pil = collect_all('PIL')

a = Analysis(
    ['SendMessage.py'],
    pathex=[],
    binaries=bins_sel + bins_wdm + bins_pil,
    datas=datas_sel + datas_wdm + datas_pil + [
        ('logo.png', '.'),       # original full logo
        ('logo_icon.png', '.'),  # pre-cropped square icon
    ],
    hiddenimports=hidden_sel + hidden_wdm + hidden_pil + [
        'pkg_resources',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',
        'requests',
        'PIL.Image',
        'PIL.ImageTk',
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
    icon='logo.png',   # taskbar / exe icon on Windows
)
