"""打包版端到端测试：模拟前端调用全部 API。"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8600"
SID = "test-packaged-001"


def post(path: str, **fields):
    data = urllib.parse.urlencode({k: str(v) for k, v in fields.items()}).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"{path} -> HTTP {e.code}: {body}") from None
    return raw, time.time() - t0


def jpost(path: str, **fields):
    raw, dt = post(path, **fields)
    return json.loads(raw.decode("utf-8")), dt


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return r.read(), r.headers.get("content-type", "")


def main() -> int:
    ok = True

    info = json.loads(get("/api/info")[0])
    print("info:", info["version"], "| R:", info["engines"]["rscript_path"])

    html, _ = get("/")
    print("index html:", len(html), "bytes", "| 模板变量残留" if b"{{" in html else "| 渲染正常")

    res, dt = jpost("/api/upload", session_id=SID, use_example="true")
    s = res["summary"]
    print(f"upload: {dt:.1f}s  genes={s.get('n_genes')} samples={s.get('n_samples')} groups={s.get('groups')}")

    for method in ("DESeq2", "edgeR", "limma", "pydeseq2"):
        res, dt = jpost("/api/analyze", session_id=SID, method=method, alpha=0.05, lfc=1.0)
        r = res.get("result", res)
        print(f"analyze {method}: {dt:.1f}s  up={r.get('n_sig_up')} down={r.get('n_sig_down')}")

    # 最终用 DESeq2 结果做图
    jpost("/api/analyze", session_id=SID, method="DESeq2", alpha=0.05, lfc=1.0)
    res, dt = jpost("/api/plots", session_id=SID, plot_set="all")
    print(f"plots: {dt:.1f}s  keys={len(res['plots'])} errors={res.get('errors')}")
    if res.get("errors"):
        ok = False

    for key, url in res["plots"].items():
        raw, ctype = get(url)
        good = len(raw) > 2000 and raw[:4] == b"\x89PNG"
        print(f"  figure {key:14s} {len(raw):>8d} bytes {'OK' if good else 'BAD'}")
        ok = ok and good

    # 自定义尺寸重生成
    sizes = json.dumps({"volcano": {"w_px": 1400, "h_px": 1200}})
    res2, dt = jpost("/api/plots", session_id=SID, plot_set="all", only="volcano", sizes=sizes)
    img, _ = get(res2["plots"]["volcano"])
    print(f"volcano resize: {dt:.1f}s -> {len(img)} bytes")

    # 导出 PNG / PDF
    for fmt in ("png", "pdf"):
        raw, dt = post("/api/plots/export", session_id=SID, key="volcano", fmt=fmt, sizes=sizes)
        magic = raw[:4]
        print(f"export {fmt}: {dt:.1f}s {len(raw)} bytes magic={magic!r}")

    # 富集（在线 Enrichr，失败不算致命）
    try:
        res3, dt = jpost("/api/enrich", session_id=SID, library="KEGG_2021_Human",
                         direction="both", mode="enrichr", top_n=200, cutoff=0.5)
        terms = res3.get("terms") or res3.get("results") or []
        print(f"enrich KEGG: {dt:.1f}s n_query={res3.get('n_query')} terms={len(terms)}")
    except Exception as exc:  # noqa: BLE001
        print("enrich KEGG: 跳过（可能无网络）", exc)

    # 报告导出
    for path, name in (("/api/report/excel", "xlsx"), ("/api/report/html", "html")):
        raw, dt = post(path, session_id=SID)
        print(f"report {name}: {dt:.1f}s {len(raw)} bytes")
        if len(raw) < 10000:
            ok = False

    # 单基因表达图
    try:
        res4, dt = jpost("/api/gene_plot", session_id=SID, gene="TNF", sizes="")
        img, _ = get(res4["image"] if "image" in res4 else res4["url"])
        print(f"gene plot: {dt:.1f}s {len(img)} bytes")
    except Exception as exc:  # noqa: BLE001
        print("gene plot: 跳过", exc)

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
