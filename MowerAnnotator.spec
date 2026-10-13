# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('config/classes.yaml', 'config')],
    hiddenimports=['PySide6.QtTest'] + collect_submodules('PIL'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'ultralytics', 'rclpy', 'tensorflow', 'cv2'],
    noarchive=False,
)
# This PySide6 wheel uses the Windows 11 ICU API. PyInstaller may collect an
# unrelated versioned icuuc.dll from the build host, which breaks Qt loading.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MowerAnnotator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
