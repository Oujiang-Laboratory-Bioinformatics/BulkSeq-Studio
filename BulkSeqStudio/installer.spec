# -*- mode: python ; coding: utf-8 -*-
"""安装器打包配置（单文件 GUI 安装程序，内嵌 payload.zip）。"""
import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.getcwd())

datas = [(os.path.join(ROOT, "build", "payload.zip"), "."),
         (os.path.join(ROOT, "build", "app.ico"), ".")]
_uninst = os.path.join(ROOT, "build", "Uninstall.exe")
if os.path.exists(_uninst):
    datas.append((_uninst, "."))
binaries = []

# conda 的 tkinter 把 Tcl/Tk 放在 Library 下，PyInstaller 默认找不到 —— 手动收进来
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
    [os.path.join(ROOT, ".tools", "installer.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"],
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
    name="BulkSeqStudio-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "build", "app.ico"),
    version=os.path.join(ROOT, "build", "version_info.txt"),
)
