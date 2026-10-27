"""全局配置与运行时路径。

支持三种运行形态：
1. 源码运行（开发调试）
2. PyInstaller 打包后的可执行文件（onedir）
3. 便携/U 盘模式：整个目录拷到任意位置即可运行

路径约定
--------
* 只读资源（static / templates / 示例数据）：
  - 源码：仓库目录
  - 打包：sys._MEIPASS（PyInstaller 的 _internal 目录）
* 可写工作目录（data / tmp）：
  - 环境变量 BULKSEQ_HOME 优先
  - 否则 exe 同级 workspace（便携模式，可写时）
  - 否则 %LOCALAPPDATA%\\BulkSeqStudio（安装到 Program Files 等只读位置时）
* R 运行时：
  - 环境变量 BULKSEQ_R_HOME / RSCRIPT_PATH
  - 随包目录 <exe>\\R 或 <exe>\\runtime\\R
  - 最后才探测系统已安装的 R
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "BulkSeq Studio"
APP_VERSION = "1.1.0"

FROZEN = bool(getattr(sys, "frozen", False))


# ------------------------------------------------------------ 基础目录 ---
def _exe_dir() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _resource_root() -> Path:
    """只读资源根目录。"""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", str(_exe_dir())))
    return Path(__file__).resolve().parents[2]


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_base_dir() -> Path:
    env = os.environ.get("BULKSEQ_HOME", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if _is_writable(p):
            return p
    if FROZEN:
        portable = _exe_dir() / "workspace"
        if _is_writable(portable):
            return portable
        local = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BulkSeqStudio"
        if _is_writable(local):
            return local
        fallback = Path.home() / "BulkSeqStudio"
        _is_writable(fallback)
        return fallback
    # 源码模式：沿用既有工作目录（若存在），否则仓库下 workspace
    legacy = Path(r"D:\Program Files\testfield")
    if (legacy / "data").exists():
        return legacy
    return _exe_dir() / "workspace"


BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
EXAMPLE_DIR = DATA_DIR / "example"
PROJECTS_DIR = DATA_DIR / "projects"
TMP_DIR = BASE_DIR / "tmp"

RESOURCE_DIR = _resource_root()
STATIC_DIR = RESOURCE_DIR / "app" / "static"
TEMPLATE_DIR = RESOURCE_DIR / "app" / "templates"
# 随包附带的示例数据（首次运行时复制到可写目录）
BUNDLED_EXAMPLE_DIR = RESOURCE_DIR / "bundled_example"


def _ascii_dir(preferred: Path) -> Path:
    """R 在 Windows 上无法可靠处理含中文的命令行路径，给它一个纯 ASCII 工作目录。"""
    if str(preferred).isascii():
        return preferred
    candidates: list[Path] = []
    public = os.environ.get("PUBLIC", "").strip()
    if public:
        candidates.append(Path(public) / "BulkSeqStudio" / "rwork")
    program_data = os.environ.get("ProgramData", "").strip()
    if program_data:
        candidates.append(Path(program_data) / "BulkSeqStudio" / "rwork")
    system_drive = os.environ.get("SystemDrive", "C:").strip() or "C:"
    candidates.append(Path(system_drive + "\\") / "BulkSeqRWork")
    for c in candidates:
        if _is_writable(c):
            return c
    return preferred


# R 引擎使用的临时目录（保证纯 ASCII，避免中文路径导致 R 读文件失败）
R_WORK_DIR = _ascii_dir(TMP_DIR)

for _d in (DATA_DIR, EXAMPLE_DIR, PROJECTS_DIR, TMP_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------ R 运行时 ---
def _rscript_candidates() -> list[Path]:
    cands: list[Path] = []
    roots: list[Path] = []
    for key in ("BULKSEQ_R_HOME", "R_HOME"):
        v = os.environ.get(key, "").strip()
        if v:
            roots.append(Path(v))
    exe_dir = _exe_dir()
    roots += [
        exe_dir / "R",
        exe_dir / "runtime" / "R",
        exe_dir / "resources" / "R",
    ]
    if FROZEN:
        meipass = Path(getattr(sys, "_MEIPASS", str(exe_dir)))
        roots += [meipass / "R", meipass / "runtime" / "R"]
    for root in roots:
        if os.name == "nt":
            cands.append(root / "bin" / "Rscript.exe")
            cands.append(root / "bin" / "x64" / "Rscript.exe")
        else:
            cands.append(root / "bin" / "Rscript")
    return cands


def _export_r_home(rscript: Path) -> None:
    """让 R 明确知道自己所在目录，避免依赖注册表。"""
    rhome = rscript.parent.parent
    if (rhome / "bin").exists():
        os.environ.setdefault("R_HOME", str(rhome))


def find_rscript() -> str | None:
    """按优先级探测 Rscript：环境变量 → 便携随包 → 系统安装。"""
    env = os.environ.get("RSCRIPT_PATH", "").strip()
    if env and Path(env).exists():
        return env

    for c in _rscript_candidates():
        if c.exists():
            _export_r_home(c)
            return str(c)

    sys_dirs = [
        r"C:\Program Files\R",
        r"D:\Program_Files\R",
        r"C:\Program Files\Microsoft\R Open",
        "/usr/local/bin",
        "/usr/bin",
        "/opt/homebrew/bin",
        "/Library/Frameworks/R.framework/Resources/bin",
    ]
    for base in sys_dirs:
        p = Path(base)
        if not p.exists():
            continue
        if p.is_file():
            return str(p)
        for sub in sorted(p.glob("R-*"), reverse=True):
            exe = sub / "bin" / "Rscript.exe"
            if exe.exists():
                _export_r_home(exe)
                return str(exe)
        exe = p / "Rscript"
        if exe.exists():
            return str(exe)

    return shutil.which("Rscript") or shutil.which("Rscript.exe")


RSCRIPT_PATH: str = find_rscript() or ""
R_HOME_DIR: str = os.environ.get("R_HOME", "")


def short_path(path) -> str:
    """返回 Windows 8.3 短路径（纯 ASCII）。

    R 在 Windows 上不能正确处理含中文的 R_HOME / 命令行路径，
    用短路径可以绕过（NTFS 默认启用 8.3 名称）。
    """
    s = str(path)
    if os.name != "nt" or s.isascii():
        return s
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(s, buf, len(buf)):
            return buf.value.replace("/", "\\") or s
    except Exception:  # noqa: BLE001
        pass
    return s


def r_home_ascii() -> str:
    """R 安装目录的 ASCII 表示（供 subprocess 传参用）。"""
    if not RSCRIPT_PATH:
        return ""
    root = Path(RSCRIPT_PATH).resolve().parent.parent
    return short_path(root)

# 上传与数据规模限制
MAX_UPLOAD_MB = 200
MAX_GENES = 80000
MIN_SAMPLES = 2
