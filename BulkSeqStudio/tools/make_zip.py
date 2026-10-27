"""生成发布包：便携 zip 与安装器 payload.zip。

用法：
    python .tools/make_zip.py portable   # release/BulkSeqStudio_v1.1.0_Portable.zip
    python .tools/make_zip.py payload    # build/payload.zip（供安装器内嵌）
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "dist" / "BulkSeqStudio"
VERSION = "1.1.0"
RELEASE = ROOT / "release"


def pack(dest: Path, arc_prefix: str = "") -> int:
    if not SRC.exists():
        print("dist not found:", SRC)
        return 1
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    print(f"packing {len(files)} files ({total/1024/1024:.0f} MB) -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, p in enumerate(files, 1):
            zf.write(p, arc_prefix + p.relative_to(SRC).as_posix())
            if i % 400 == 0:
                print(f"  {i}/{len(files)}", flush=True)
    print(f"done: {dest}  {dest.stat().st_size/1024/1024:.0f} MB")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "portable"
    if mode == "portable":
        return pack(RELEASE / f"BulkSeqStudio_v{VERSION}_Portable.zip", "BulkSeqStudio/")
    if mode == "payload":
        return pack(ROOT / "build" / "payload.zip", "")
    print("unknown mode:", mode)
    return 1


if __name__ == "__main__":
    sys.exit(main())
