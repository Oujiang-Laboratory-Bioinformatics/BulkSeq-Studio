# -*- mode: python ; coding: utf-8 -*-
"""轻量卸载器（不含 payload），安装时复制到安装目录。"""
import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.getcwd())

datas = [(os.path.join(ROOT, "build", "app.ico"), ".")]
binaries = []

_lib = Path(sys.base_prefix) / "Library"
for _name in ("tcl86t.dll", "tk86t.dll", "zlib.dll"):
    _p = _lib / "bin" / _name
    if _p.exists():
        binaries.append((str(_p), "."))
for _dir in ("tcl8.6", "tk8.6"):
    _p = _lib / "lib" / _dir
    if _p.exists():
        datas.append((str(_p), _dir))

a = Analysis(
    [os.path.join(ROOT, ".tools", "uninstaller.py")],
    pathex=[ROOT, os.path.join(ROOT, ".tools")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tkinter", "tkinter.messagebox"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pandas", "matplotlib", "scipy", "sklearn", "PIL",
              "fastapi", "uvicorn", "starlette", "jinja2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Uninstall",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "build", "app.ico"),
    version=os.path.join(ROOT, "build", "version_info.txt"),
)
