"""BulkSeq Studio 启动器。

用法：
    源码：python run.py
    打包：直接双击 BulkSeqStudio.exe

特性：
- 端口被占用时自动向后尝试（8600 ~ 8610）
- 若占用者就是本软件，则直接打开浏览器并退出（不会报错）
- 启动后自动打开默认浏览器
- 所有数据仅在本机处理，不上传任何服务器
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
if not FROZEN:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _setup_console() -> None:
    """控制台标题与 UTF-8 输出（打包后默认代码页会导致中文乱码）。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleTitleW("BulkSeq Studio")
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


# joblib / loky 会 fork 新的解释器进程，在打包环境里不可用 —— pydeseq2 已在
# de_engine 中切换为线程后端，这里不再全局禁用（避免影响其它库的线程池）。

_setup_console()

from app.core.config import APP_NAME, APP_VERSION, BASE_DIR, RSCRIPT_PATH

# 打包运行时：把缓存写到可写工作目录，避免漫游到用户目录或只读位置
_CACHE = BASE_DIR / ".cache"
try:
    (_CACHE / "matplotlib").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(_CACHE / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE))
except Exception:  # noqa: BLE001
    pass

HOST = "127.0.0.1"
PORT_RANGE = range(8600, 8611)
LOG_FILE = BASE_DIR / "server.log"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port)) == 0


def _is_bulkseq_server(port: int) -> bool:
    """探测该端口是否已经是本软件在运行。"""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/info", timeout=2) as resp:
            info = json.loads(resp.read().decode("utf-8"))
            return info.get("app") == APP_NAME
    except Exception:  # noqa: BLE001
        return False


def _pick_port() -> tuple[int | None, str | None]:
    for p in PORT_RANGE:
        if not _port_in_use(p):
            return p, None
        if _is_bulkseq_server(p):
            return None, f"http://{HOST}:{p}"
    return None, None


def _banner(url: str, port: int) -> None:
    line = "=" * 64
    print(line)
    print(f"  {APP_NAME} v{APP_VERSION}  ·  bulk RNA-seq 差异分析")
    print(line)
    print(f"  访问地址：{url}")
    print(f"  工作目录：{BASE_DIR}")
    if RSCRIPT_PATH:
        print(f"  R 引擎  ：{RSCRIPT_PATH}")
    else:
        print("  R 引擎  ：未找到（将使用内置 Python 引擎 pydeseq2）")
    print("-" * 64)
    print("  浏览器会自动打开。若没有自动打开，请手动复制上面的地址到浏览器。")
    print("  ★ 使用期间请勿关闭本窗口；关闭本窗口即退出软件。")
    print("  所有数据仅在本机处理，不会上传到任何服务器。")
    print(line)


def main() -> int:
    port, running_url = _pick_port()
    if running_url:
        print(f"  软件已经在运行：{running_url}")
        print("  正在打开浏览器…")
        webbrowser.open(running_url)
        time.sleep(2)
        return 0
    if port is None:
        print("  错误：8600~8610 端口均被占用，无法启动。")
        print("  请关闭占用端口的程序后重试。")
        _pause()
        return 1

    url = f"http://{HOST}:{port}"
    _banner(url, port)

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn

    from app.main import app as fastapi_app

    try:
        uvicorn.run(fastapi_app, host=HOST, port=port, log_level="info",
                    use_colors=False, access_log=False)
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        try:
            LOG_FILE.write_text(err, encoding="utf-8")
            print(f"\n启动失败，详细信息已写入：{LOG_FILE}")
        except Exception:  # noqa: BLE001
            pass
        print(err)
        _pause()
        return 1
    return 0


def _pause() -> None:
    if FROZEN:
        try:
            input("\n按回车键退出…")
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    try:
        import multiprocessing

        multiprocessing.freeze_support()
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
