"""把 dist/BulkSeqStudio 打成安装器用的 payload.zip。"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "dist" / "BulkSeqStudio"
OUT = ROOT / "build" / "payload.zip"
EXTRA = [ROOT / "build" / "使用说明.txt"]


def main() -> int:
    if not SRC.exists():
        print("dist not found:", SRC)
        return 1
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    print(f"packing {len(files)} files, {total/1024/1024:.0f} MB -> {OUT}")
    if OUT.exists():
        OUT.unlink()
    done = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, p in enumerate(files, 1):
            zf.write(p, p.relative_to(SRC).as_posix())
            done += p.stat().st_size
            if i % 500 == 0:
                print(f"  {i}/{len(files)}  {done/1024/1024:.0f} MB", flush=True)
        for extra in EXTRA:
            if extra.exists():
                zf.write(extra, extra.name)
    print(f"payload: {OUT.stat().st_size/1024/1024:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
