# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— BulkSeq Studio 独立运行版。

产物：dist/BulkSeqStudio/BulkSeqStudio.exe（onedir，含 _internal 依赖目录）
R 运行时由 build_exe.ps1 另外放入 dist/BulkSeqStudio/R。
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.getcwd())

# conda 环境把 OpenSSL / liblzma / libffi 等放在 Library\bin，PyInstaller 默认找不到，
# 缺了会导致 https 请求、压缩模块不可用 —— 显式收进来。
binaries = []
_conda_bin = Path(sys.base_prefix) / "Library" / "bin"
for _dll in ("libcrypto-3-x64.dll", "libssl-3-x64.dll", "liblzma.dll",
             "LIBBZ2.dll", "ffi.dll", "libexpat.dll", "zlib.dll"):
    _p = _conda_bin / _dll
    if _p.exists():
        binaries.append((str(_p), "."))

datas = [
    (os.path.join(ROOT, "app", "static"), os.path.join("app", "static")),
    (os.path.join(ROOT, "app", "templates"), os.path.join("app", "templates")),
]
_bundled_example = os.path.join(ROOT, "build", "bundled_example")
if os.path.isdir(_bundled_example):
    datas.append((_bundled_example, "bundled_example"))

hiddenimports = [
    "multipart",
    "jinja2.ext",
    "openpyxl",
    "pydantic_settings",
    "anyio._backends._asyncio",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # matplotlib 后端是动态导入的，必须显式声明（否则 PDF 导出报 No module named ...）
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_svg",
    "matplotlib.backends.backend_ps",
    "matplotlib.pyplot",
    "matplotlib.font_manager",
    "matplotlib.ft2font",
    "mpl_toolkits.axes_grid1",
]
for pkg in ("uvicorn", "pydeseq2", "anndata"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# matplotlib 的字体与样式数据
for pkg in ("matplotlib", "seaborn", "gseapy"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

excludes = [
    "tkinter", "IPython", "notebook", "jupyter", "jupyter_core", "pytest",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "torch", "tensorflow",
    "plotly", "bokeh", "sphinx", "docutils", "numba", "llvmlite",
]

a = Analysis(
    ["run.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BulkSeqStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=os.path.join(ROOT, "build", "app.ico") if os.path.exists(os.path.join(ROOT, "build", "app.ico")) else None,
    version=os.path.join(ROOT, "build", "version_info.txt") if os.path.exists(os.path.join(ROOT, "build", "version_info.txt")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BulkSeqStudio",
)
