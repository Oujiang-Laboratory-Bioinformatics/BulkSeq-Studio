# -*- coding: utf-8 -*-
"""卸载器入口：无参数时默认执行卸载（带确认对话框）。

uninstall.spec 以本文件为入口打包出 Uninstall.exe；
安装器 installer.spec 打包出的 Uninstall.exe 副本同样生效。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 标记卸载模式，installer.main() 据此走卸载分支
os.environ["BULKSEQ_UNINSTALLER"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer  # noqa: E402

if __name__ == "__main__":
    sys.exit(installer.main())
