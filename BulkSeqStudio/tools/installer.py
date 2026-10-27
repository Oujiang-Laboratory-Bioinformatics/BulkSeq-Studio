"""BulkSeq Studio 安装/卸载程序。

打包方式（onefile，内嵌 payload.zip）：
    python -m PyInstaller installer.spec --noconfirm

用法：
    BulkSeqStudio-Setup.exe              图形化安装
    BulkSeqStudio-Setup.exe /uninstall   卸载
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import winreg
import zipfile
from pathlib import Path

APP_NAME = "BulkSeq Studio"
APP_ID = "BulkSeqStudio"
APP_VERSION = "1.1.0"
MAIN_EXE = "BulkSeqStudio.exe"
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / APP_ID
UNINST_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"

# 打包后 Tcl/Tk 库脚本在 _MEIPASS 下，需要显式告诉 tkinter
if getattr(sys, "frozen", False):
    _base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for _env, _sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
        _p = _base / _sub
        if _p.exists():
            os.environ.setdefault(_env, str(_p))


def _payload() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / "payload.zip", base / "build" / "payload.zip"):
        if cand.exists():
            return cand
    raise FileNotFoundError("找不到安装数据 payload.zip")


# --------------------------------------------------------------- 快捷方式 ---
def _ps(cmd: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def make_shortcut(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    cmd = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        f"$s.TargetPath='{target}';"
        f"$s.WorkingDirectory='{target.parent}';"
        f"$s.IconLocation='{target},0';"
        f"$s.Description='bulk RNA-seq 差异分析';"
        f"$s.Save()"
    )
    _ps(cmd)


def desktop_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            return Path(winreg.QueryValueEx(k, "Desktop")[0])
    except Exception:  # noqa: BLE001
        return Path.home() / "Desktop"


def start_menu_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


# ------------------------------------------------------------------ 安装 ---
def write_registry(target: Path) -> None:
    uninst = target / "Uninstall.exe"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINST_KEY) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(target))
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, str(target / MAIN_EXE))
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{uninst}" /uninstall')
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception:  # noqa: BLE001
        pass


def install(target: Path, progress) -> None:
    payload = _payload()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload) as zf:
        infos = zf.infolist()
        total = len(infos)
        batch = 250
        for start in range(0, total, batch):
            zf.extractall(target, infos[start:start + batch])
            done = min(start + batch, total)
            progress(done / total * 0.92, f"正在安装文件 {done}/{total} …")

    progress(0.94, "正在创建快捷方式 …")
    make_shortcut(desktop_dir() / f"{APP_NAME}.lnk", target / MAIN_EXE)
    make_shortcut(start_menu_dir() / f"{APP_NAME}.lnk", target / MAIN_EXE)

    progress(0.97, "正在注册卸载信息 …")
    me = Path(sys.executable)
    uninst = target / "Uninstall.exe"
    stub = Path(getattr(sys, "_MEIPASS", "")) / "Uninstall.exe"
    try:
        if stub.exists() and stub.stat().st_size < 80 * 1024 * 1024:
            shutil.copyfile(stub, uninst)   # 轻量卸载器（约 12 MB）
        else:
            os.link(me, uninst)             # 兜底：同盘硬链接
    except Exception:  # noqa: BLE001
        try:
            shutil.copyfile(me, uninst)
        except Exception:  # noqa: BLE001
            pass
    write_registry(target)
    progress(1.0, "安装完成")


def do_uninstall(target: Path) -> None:
    for lnk in (desktop_dir() / f"{APP_NAME}.lnk", start_menu_dir() / f"{APP_NAME}.lnk"):
        try:
            lnk.unlink()
        except Exception:  # noqa: BLE001
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
    except Exception:  # noqa: BLE001
        pass

    # 分析结果先搬到「我的文档」，避免卸载带走用户数据
    ws = target / "workspace"
    if ws.exists():
        import time

        dest = Path.home() / "Documents" / "BulkSeqStudio_results"
        try:
            if dest.exists():
                dest = dest.with_name(f"BulkSeqStudio_results_{time.strftime('%Y%m%d_%H%M%S')}")
            shutil.move(str(ws), str(dest))
        except Exception:  # noqa: BLE001
            pass

    # 正在运行的 exe 无法删除自身 → 无条件复制到临时目录，由副本清理安装目录。
    # 不能用"安装目录是否在 TEMP 下"来判断——用户可能就把软件装在临时目录。
    import tempfile
    import time

    tmpdir = Path(tempfile.gettempdir()).resolve()
    me = Path(sys.executable).resolve()

    if "--cleanup" in sys.argv[1:]:
        # 延迟清理模式：等原进程退出后删目录，最后删除临时副本自身。
        # 注意：进程当前目录会锁住目录本身，必须先切走，否则留下空目录。
        try:
            os.chdir(tmpdir)
        except Exception:  # noqa: BLE001
            os.chdir(Path.home())
        time.sleep(3)
        errs = []
        for i in range(30):  # 最长约 60s，兜底等原进程完全退出
            try:
                shutil.rmtree(target)
                break
            except Exception as exc:  # noqa: BLE001
                errs.append(f"try{i}: {exc}")
                time.sleep(2)
        try:
            (tmpdir / "bulkseq_uninst.log").write_text(
                "cleanup target=%s\n%s\n" % (target, "\n".join(errs) or "OK"),
                encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            os.remove(me)
        except Exception:  # noqa: BLE001
            pass
        return

    stub = tmpdir / "BulkSeqUninstall_tmp.exe"
    try:
        # 先切走工作目录：当前目录会锁住安装目录，原进程退出慢会让副本一直删不掉
        try:
            os.chdir(tmpdir)
        except Exception:  # noqa: BLE001
            pass
        shutil.copyfile(me, stub)
        subprocess.Popen(
            [str(stub), "--uninstall", "--yes", f"--target={target}", "--cleanup"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        # 兜底：cmd 延迟删除（ping 延时在无控制台进程里也可靠）
        subprocess.Popen(
            f'ping -n 8 127.0.0.1 >nul & rmdir /s /q "{target}"',
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


# -------------------------------------------------------------------- UI ---
def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    # 高分屏适配：声明 DPI 感知并按 DPI 缩放窗口，否则界面会模糊/拥挤
    scale = 1.0
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
        dc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, dc)
        scale = max(1.0, dpi / 96.0)
    except Exception:  # noqa: BLE001
        scale = 1.0

    root = tk.Tk()
    root.title(f"{APP_NAME} 安装程序")
    root.geometry(f"{int(660 * scale)}x{int(400 * scale)}")
    root.resizable(False, False)
    try:
        root.tk.call("tk", "scaling", 96 * scale / 72)
    except Exception:  # noqa: BLE001
        pass
    try:
        icon = Path(getattr(sys, "_MEIPASS", ".")) / "app.ico"
        if icon.exists():
            root.iconbitmap(str(icon))
    except Exception:  # noqa: BLE001
        pass

    bg = "#0f2a54"
    root.configure(bg="#f5f7fb")
    s = scale

    header = tk.Frame(root, bg=bg, height=int(104 * s))
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text=APP_NAME, bg=bg, fg="white",
             font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", padx=int(26 * s), pady=(int(20 * s), 0))
    tk.Label(header, text="bulk RNA-seq 差异分析 · 已内置 R 与 Python 运行时",
             bg=bg, fg="#9fc6f0", font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=int(26 * s), pady=(int(2 * s), 0))

    body = tk.Frame(root, bg="#f5f7fb")
    body.pack(fill="both", expand=True, padx=int(26 * s), pady=int(16 * s))

    tk.Label(body, text="安装位置：", bg="#f5f7fb", font=("Microsoft YaHei UI", 10)).grid(row=0, column=0, sticky="w")
    path_var = tk.StringVar(value=str(DEFAULT_DIR))
    entry = tk.Entry(body, textvariable=path_var, font=("Consolas", 10), width=30)
    entry.grid(row=0, column=1, sticky="we", padx=(int(6 * s), int(6 * s)))

    def browse():
        d = filedialog.askdirectory(title="选择安装位置", initialdir=str(Path(path_var.get()).parent))
        if d:
            path_var.set(str(Path(d) / APP_ID))

    tk.Button(body, text="浏览…", command=browse, font=("Microsoft YaHei UI", 9),
              width=7).grid(row=0, column=2, padx=(0, 0))
    body.columnconfigure(1, weight=1)

    tk.Label(body, text="安装后会在桌面和开始菜单创建快捷方式，可在“设置 → 应用”中卸载。",
             bg="#f5f7fb", fg="#5b6b82", font=("Microsoft YaHei UI", 9)).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(int(10 * s), 0))

    pb = ttk.Progressbar(body, mode="determinate", maximum=100)
    pb.grid(row=2, column=0, columnspan=3, sticky="we", pady=(int(22 * s), int(6 * s)))
    status = tk.Label(body, text="准备就绪，点击“开始安装”。", bg="#f5f7fb", fg="#33445c",
                      font=("Microsoft YaHei UI", 9))
    status.grid(row=3, column=0, columnspan=3, sticky="w")

    btns = tk.Frame(body, bg="#f5f7fb")
    btns.grid(row=4, column=0, columnspan=3, sticky="e", pady=(int(18 * s), 0))

    q: queue.Queue = queue.Queue()

    def worker(target: Path):
        def progress(frac: float, msg: str):
            q.put(("p", frac, msg))
        try:
            install(target, progress)
            q.put(("done", None, None))
        except Exception as exc:  # noqa: BLE001
            q.put(("err", None, str(exc)))

    def start():
        target = Path(path_var.get())
        try:
            free = shutil.disk_usage(target.anchor).free / (1024 ** 3)
            if free < 3:
                if not messagebox.askyesno("磁盘空间不足",
                                           f"{target.anchor} 剩余 {free:.1f} GB，建议至少 3 GB。\n仍要继续吗？"):
                    return
        except Exception:  # noqa: BLE001
            pass
        install_btn.config(state="disabled")
        start_btn.config(state="disabled")
        entry.config(state="disabled")
        threading.Thread(target=worker, args=(target,), daemon=True).start()

    def poll():
        try:
            while True:
                kind, frac, msg = q.get_nowait()
                if kind == "p":
                    pb["value"] = frac * 100
                    status.config(text=msg)
                elif kind == "done":
                    status.config(text="安装完成！")
                    pb["value"] = 100
                    install_btn.config(state="normal", text="立即启动")
                    install_btn.config(command=lambda: launch(Path(path_var.get())))
                    start_btn.config(state="normal", text="完成", command=root.destroy)
                    messagebox.showinfo("安装完成", f"{APP_NAME} 已安装到：\n{path_var.get()}\n\n双击桌面图标即可使用。")
                elif kind == "err":
                    status.config(text="安装失败")
                    messagebox.showerror("安装失败", str(msg))
                    install_btn.config(state="normal")
                    start_btn.config(state="normal")
        except queue.Empty:
            pass
        root.after(120, poll)

    def launch(target: Path):
        try:
            subprocess.Popen([str(target / MAIN_EXE)], cwd=str(target))
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("启动失败", str(exc))

    start_btn = tk.Button(btns, text="开始安装", command=start, width=14,
                          font=("Microsoft YaHei UI", 10), bg="#1d4ed8", fg="white",
                          activebackground="#1e40af", activeforeground="white", relief="flat", pady=int(7 * s))
    start_btn.pack(side="right", padx=(8, 0))
    install_btn = tk.Button(btns, text="取消", command=root.destroy, width=10,
                            font=("Microsoft YaHei UI", 10), relief="flat", pady=int(7 * s))
    install_btn.pack(side="right")

    poll()
    root.mainloop()
    return 0


def main() -> int:
    args = sys.argv[1:]
    # 卸载触发条件：显式 --uninstall 参数，或本进程就是 Uninstall.exe
    # （uninstaller.py 入口设置该环境变量；双击 Uninstall.exe 无参数时也走卸载）
    is_uninstaller = os.environ.get("BULKSEQ_UNINSTALLER") == "1" or "--uninstall" in args
    if is_uninstaller:
        target = Path(sys.executable).resolve().parent
        for a in args:
            if a.startswith("--target="):
                target = Path(a[9:].strip('"'))
        if "--yes" not in args:
            import tkinter as tk
            import tkinter.messagebox as mb
            r = tk.Tk()
            r.withdraw()
            ok = mb.askyesno("卸载", f"确定要卸载 {APP_NAME} 吗？\n\n"
                                      "分析结果（workspace 目录）会自动保留到：\n"
                                      r"我的文档\BulkSeqStudio_results")
            r.destroy()
            if not ok:
                return 0
        do_uninstall(target)
        return 0

    # 静默安装（便于批量部署/自动化测试）：Setup.exe /S [/D=<目录>]
    if "/S" in args or "--silent" in args:
        target = DEFAULT_DIR
        for a in args:
            if a.startswith("--dir="):
                target = Path(a[6:].strip('"'))
            elif a.upper().startswith("/D="):
                target = Path(a[3:].strip('"'))
        install(target, lambda frac, msg: None)
        return 0

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
