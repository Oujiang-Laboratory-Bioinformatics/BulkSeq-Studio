# -*- coding: utf-8 -*-
"""卸载器端到端测试：轮询等待对话框 -> 回车确认 -> 等待清理完成。"""
import ctypes
import subprocess
import sys
import time
from pathlib import Path

u = ctypes.windll.user32
target = Path.home() / "AppData/Local/Temp/BSS_FinalVerify"

p = subprocess.Popen([str(target / "Uninstall.exe")], cwd=str(target))
print("pid", p.pid)

found = False
for i in range(15):
    time.sleep(2)
    h = u.FindWindowW(None, "卸载")
    if h:
        print(f"dialog appeared at ~{(i + 1) * 2}s")
        found = True
        break

if not found:
    print("NO DIALOG in 30s; returncode:", p.poll())
    sys.exit(1)

u.SetForegroundWindow(h)
time.sleep(0.8)
u.keybd_event(0x0D, 0, 0, 0)
u.keybd_event(0x0D, 0, 2, 0)
print("confirmed")

deadline = time.time() + 60
while time.time() < deadline:
    time.sleep(2)
    if not target.exists():
        print("RESULT: install dir fully removed")
        break
    n = len(list(target.iterdir()))
    print(f"waiting... entries={n}")
else:
    print("RESULT: TIMEOUT, dir still:", list(target.iterdir()))
