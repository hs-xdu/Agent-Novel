# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path


a = Analysis(
    ['run_desktop.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['tiktoken_ext.openai_public', 'keyring.backends.Windows'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['nicegui'],
    noarchive=False,
    optimize=0,
)
# Qt 6.12 Windows 使用系统 ICU 的无版本符号。PATH 中的 Conda ICU
# 导出带版本号的符号，不能随包覆盖 System32 的 icuuc.dll。
if sys.platform == 'win32':
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != 'icuuc.dll']
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Shiguang',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Shiguang',
)
