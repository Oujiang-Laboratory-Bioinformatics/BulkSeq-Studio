"""BulkSeq Studio — bulk RNA-seq 差异分析 Web 应用入口。

启动：D:/Users/Heisar/miniconda3/envs/bulkseq/Scripts/python.exe run.py
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core import example_data
from app.core.config import APP_NAME, APP_VERSION, EXAMPLE_DIR, MAX_UPLOAD_MB, STATIC_DIR, TEMPLATE_DIR, TMP_DIR
from app.core.data_loader import (
    DataError, ExpressionData, expr_from_json, load_tables, read_uploaded_table,
)
from app.services import de_engine, enrichment as enrich_svc, plots as plots_svc, report as report_svc

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --------------------------------------------------------------- 会话状态 ---
class Session:
    def __init__(self):
        self.expr: Optional[ExpressionData] = None
        self.de: Optional[dict] = None
        self.plots: dict = {}
        self.project_name: str = "未命名项目"
        self.source: str = ""


SESSIONS: dict[str, Session] = {}


def _get_session(sid: str) -> Session:
    if sid not in SESSIONS:
        SESSIONS[sid] = Session()
    return SESSIONS[sid]


@app.get("/", response_class=HTMLResponse)
def index():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("index.html").render(
        version=APP_VERSION, app_name=APP_NAME
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/api/info")
def api_info():
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "engines": de_engine.available_engines(),
        "example_ready": bool(example_data.write_example_files() and
                              (EXAMPLE_DIR / "airway_like_counts.csv").exists()),
        "max_upload_mb": MAX_UPLOAD_MB,
    }


@app.post("/api/upload")
async def api_upload(
    counts: UploadFile = File(None),
    metadata: UploadFile = File(None),
    session_id: str = Form(...),
    use_example: str = Form("false"),
):
    try:
        if use_example == "true":
            paths = example_data.write_example_files(force=True)
            counts_df = pd.read_csv(paths["counts"], index_col=0)
            meta_df = pd.read_csv(paths["metadata"])
            source = "内置示例数据（模拟 airway 地塞米松处理数据集）"
        else:
            if counts is None:
                raise DataError("请上传表达矩阵文件。")
            raw = await counts.read()
            if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
                raise DataError(f"文件超过 {MAX_UPLOAD_MB} MB 限制。")
            counts_df = read_uploaded_table(raw, counts.filename or "counts.csv")
            if metadata is not None and (metadata.filename or "").strip():
                mraw = await metadata.read()
                meta_df = read_uploaded_table(mraw, metadata.filename or "meta.csv")
            else:
                # 用户未上传设计表：按 _untreated/_dex 等命名自动猜测分组
                cols = [str(c) for c in counts_df.columns[1:]]
                inferred = _infer_groups_from_names(cols)
                if inferred is None:
                    raise DataError("请上传设计表（样本名 + 分组），或将样本按「组名_编号」命名以自动识别分组。")
                meta_df = inferred
                source = "设计表由样本名自动推断"
            source = f"上传文件：{counts.filename}"

        expr = load_tables(counts_df, meta_df)
        s = _get_session(session_id)
        s.expr = expr
        s.de = None
        s.plots = {}
        s.source = source
        return {"ok": True, "summary": expr.to_summary(), "source": source}
    except DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"解析失败：{exc}")


def _infer_groups_from_names(samples: list[str]) -> Optional[pd.DataFrame]:
    import re
    groups = []
    for s in samples:
        m = re.match(r"^(.*)[_-](\d+|[A-Za-z])$", s)
        if m and m.group(1):
            groups.append(m.group(1))
        else:
            return None
    if len(set(groups)) < 2:
        return None
    return pd.DataFrame({"sample": samples, "group": groups})


@app.post("/api/analyze")
def api_analyze(
    session_id: str = Form(...),
    method: str = Form("DESeq2"),
    alpha: float = Form(0.05),
    lfc: float = Form(1.0),
    ref_group: str = Form(""),
):
    s = _get_session(session_id)
    if s.expr is None:
        raise HTTPException(status_code=400, detail="请先导入数据。")
    expr = s.expr
    # 允许用户指定参考组
    if ref_group and ref_group in set(expr.metadata["group"].astype(str)):
        meta = expr.metadata.copy()
        meta["group"] = pd.Categorical(meta["group"].astype(str),
                                       categories=[ref_group] + [g for g in sorted(meta["group"].astype(str).unique()) if g != ref_group])
        expr = ExpressionData(counts=expr.counts, metadata=meta, warnings=expr.warnings)
        s.expr = expr
    try:
        de = de_engine.run_de_analysis(expr, method=method, alpha=alpha, lfc_threshold=lfc)
    except de_engine.AnalysisError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    s.de = de
    return {"ok": True, "result": de_engine.results_to_payload(de),
            "summary": expr.to_summary()}


def _kw_from(sizes: str, key: str) -> dict:
    """把前端传来的像素尺寸换算成 matplotlib 的英寸尺寸（兼容 w_px / w 两种键名）。"""
    import json as _json
    try:
        cfg = (_json.loads(sizes) if sizes else {}).get(key) or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    dpi = max(72, min(int(cfg.get("dpi") or 150), 600))
    w_px = cfg.get("w_px") or cfg.get("w")
    h_px = cfg.get("h_px") or cfg.get("h")
    w = float(w_px) / dpi if w_px else None
    h = float(h_px) / dpi if h_px else None
    return {"width": max(2.0, min(w, 40.0)) if w else None,
            "height": max(1.5, min(h, 40.0)) if h else None, "dpi": dpi}


def _plot_generators(s, sizes: str) -> dict:
    """返回 {key: callable(**kw)}，供预览与导出共用。"""
    expr, de = s.expr, s.de
    groups = expr.metadata.set_index("sample").loc[expr.counts.columns, "group"]

    def _volcano():
        return plots_svc.plot_volcano(
            de["results"], de["alpha"], de["lfc_threshold"],
            title=f"火山图（{de['alt']} vs {de['ref']}）", **_kw_from(sizes, "volcano"))

    def _heatmap():
        sig = de["results"][
            (de["results"]["padj"] < de["alpha"]) &
            (de["results"]["log2FoldChange"].abs() >= de["lfc_threshold"])
        ].abs().sort_values("log2FoldChange", ascending=False).index.tolist()
        if not sig:
            raise ValueError("没有显著差异基因")
        return plots_svc.plot_de_heatmap(
            de["transformed"], sig, groups,
            title=f"Top 差异基因热图（{de['alt']} vs {de['ref']}）", **_kw_from(sizes, "heatmap"))

    return {
        "pca": lambda: plots_svc.plot_pca(de["transformed"], groups, **_kw_from(sizes, "pca")),
        "corr": lambda: plots_svc.plot_sample_correlation(de["transformed"], groups, **_kw_from(sizes, "corr")),
        "dist": lambda: plots_svc.plot_count_distribution(expr.counts, groups, **_kw_from(sizes, "dist")),
        "volcano": _volcano,
        "ma": lambda: plots_svc.plot_ma(de["results"], de["alpha"], **_kw_from(sizes, "ma")),
        "heatmap": _heatmap,
    }


@app.post("/api/plots")
def api_plots(session_id: str = Form(...), plot_set: str = Form("all"),
              only: str = Form(""), sizes: str = Form("")):
    s = _get_session(session_id)
    if s.expr is None or s.de is None:
        raise HTTPException(status_code=400, detail="请先完成差异分析。")

    gens = _plot_generators(s, sizes)
    out: dict = {}
    errors: dict = {}

    # only 指定时只重生成那一张（用于改尺寸后的快速刷新）
    keys = [only] if only in gens else list(gens)
    for k in keys:
        try:
            out[k] = gens[k]()
        except Exception as exc:  # noqa: BLE001
            errors[k] = str(exc)

    if only and only in gens:
        s.plots = {**(s.plots or {}), **out}       # 单张更新，保留其他图
    else:
        s.plots = out
    return {"ok": True, "plots": {k: _fig_url(v.get("image")) for k, v in out.items()},
            "interactive": {k: v.get("data") for k, v in out.items() if v.get("data")},
            "errors": {k: errors[k] for k in keys if k in errors}}


@app.post("/api/plots/export")
def api_plots_export(session_id: str = Form(...), key: str = Form(...),
                     fmt: str = Form("png"), sizes: str = Form(""),
                     gene: str = Form("")):
    """按用户设置的尺寸导出单张图为 PNG 或矢量 PDF。"""
    s = _get_session(session_id)
    if s.expr is None or s.de is None:
        raise HTTPException(status_code=400, detail="请先完成差异分析。")
    fmt = fmt.lower()
    if fmt not in ("png", "pdf"):
        raise HTTPException(status_code=400, detail="仅支持 png / pdf 格式。")

    token = plots_svc.set_save_formats(("png", "pdf") if fmt == "pdf" else ("png",))
    try:
        if key == "gene":
            if not gene:
                raise HTTPException(status_code=400, detail="缺少基因名。")
            match = next((g for g in s.expr.counts.index
                          if str(g).lower() == gene.strip().lower()), None)
            if match is None:
                raise HTTPException(status_code=404, detail=f"基因 {gene} 不在表达矩阵中。")
            groups = s.expr.metadata.set_index("sample").loc[s.expr.counts.columns, "group"]
            out = plots_svc.plot_gene_boxplot(
                s.expr.counts, s.de["transformed"], match, groups, **_kw_from(sizes, "gene"))
        else:
            gens = _plot_generators(s, sizes)
            if key not in gens:
                raise HTTPException(status_code=400, detail=f"未知图表：{key}")
            out = gens[key]()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导出失败：{exc}")
    finally:
        plots_svc.reset_save_formats(token)

    png = Path(out["image"])
    target = png.with_suffix(".pdf") if fmt == "pdf" else png
    if not target.exists():
        raise HTTPException(status_code=500, detail="导出文件未生成。")
    cfg = _kw_from(sizes, key)
    w_px = int(round((cfg["width"] or 0) * cfg["dpi"]))
    h_px = int(round((cfg["height"] or 0) * cfg["dpi"]))
    suffix = f"_{w_px}x{h_px}" if w_px and h_px else ""
    return FileResponse(
        target,
        media_type="application/pdf" if fmt == "pdf" else "image/png",
        filename=f"bulkseq_{key}{suffix}.{fmt}",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/image/pdf")
async def api_image_pdf(file: UploadFile = File(...), w_px: int = Form(0),
                        h_px: int = Form(0), dpi: int = Form(150)):
    """把前端交互图（ECharts 画布）导出的 PNG 包成同尺寸 PDF。"""
    data = await file.read()
    dpi = max(72, min(int(dpi or 150), 600))
    w_in = (w_px / dpi) if w_px else 10.0
    h_in = (h_px / dpi) if h_px else 6.0
    try:
        path = plots_svc.image_to_pdf(data, w_in, h_in)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PDF 生成失败：{exc}")
    return FileResponse(Path(path), media_type="application/pdf",
                        filename=f"chart_{w_px}x{h_px}.pdf",
                        headers={"Cache-Control": "no-store"})


def _fig_url(path: str | None) -> str:
    """把本地图片路径转换成 HTTP 访问地址（浏览器不能直接加载 file:// 路径）。

    用路径式 URL（而不是 ?name=...），避免某些预览面板/反向代理丢弃查询串导致图片 404。
    """
    if not path:
        return ""
    return f"/api/figure/{Path(path).name}"


def _serve_figure(name: str) -> FileResponse:
    safe = Path(name).name  # 防目录穿越
    if not safe.lower().endswith(".png"):
        raise HTTPException(status_code=404, detail="图片不存在")
    p = TMP_DIR / "figures" / safe
    if not p.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/figure/{name}")
def api_figure_path(name: str):
    return _serve_figure(name)


@app.get("/api/figure")
def api_figure(name: str):
    return _serve_figure(name)


@app.post("/api/enrich")
def api_enrich(
    session_id: str = Form(...),
    library: str = Form("KEGG"),
    direction: str = Form("both"),
    mode: str = Form("enrichr"),
    gmt_path: str = Form(""),
    top_n: int = Form(500),
    cutoff: float = Form(0.05),
):
    s = _get_session(session_id)
    if s.de is None:
        raise HTTPException(status_code=400, detail="请先完成差异分析。")
    res = s.de["results"]
    sig = res[(res["padj"] < s.de["alpha"]) & (res["log2FoldChange"].abs() >= s.de["lfc_threshold"])]
    if direction == "up":
        genes = sig[sig["log2FoldChange"] > 0].index.tolist()
    elif direction == "down":
        genes = sig[sig["log2FoldChange"] < 0].index.tolist()
    else:
        up = sig[sig["log2FoldChange"] > 0].sort_values("padj").index[:top_n // 2]
        down = sig[sig["log2FoldChange"] < 0].sort_values("padj").index[:top_n // 2]
        genes = list(up) + list(down)
    if not genes:
        raise HTTPException(status_code=400, detail="没有符合阈值的差异基因可做富集。")

    try:
        background = res.index.astype(str).tolist()  # 分析 universe 作为背景
        if mode == "gmt":
            if not gmt_path or not Path(gmt_path).exists():
                raise enrich_svc.EnrichError("GMT 文件路径无效。")
            df = enrich_svc.enrich_via_gmt(genes, gmt_path, background=background, cutoff=cutoff)
        else:
            df = enrich_svc.enrich_via_enrichr(genes, library, cutoff=cutoff)
    except enrich_svc.EnrichError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    s.enrich_results = getattr(s, "enrich_results", {}) or {}
    s.enrich_results[library] = df
    return {"ok": True, "n_query": len(genes), **enrich_svc.enrichment_to_payload(df)}


@app.post("/api/report/excel")
def api_report_excel(session_id: str = Form(...)):
    s = _get_session(session_id)
    if s.de is None:
        raise HTTPException(status_code=400, detail="请先完成差异分析。")
    out = TMP_DIR / "reports" / f"{uuid.uuid4().hex[:10]}.xlsx"
    report_svc.export_excel(s.de, s.plots, getattr(s, "enrich_results", None),
                            s.expr.to_summary(), out)
    return FileResponse(out, filename="bulkseq_report.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/report/html")
def api_report_html(session_id: str = Form(...), project_name: str = Form("未命名项目")):
    s = _get_session(session_id)
    if s.de is None:
        raise HTTPException(status_code=400, detail="请先完成差异分析。")
    out = TMP_DIR / "reports" / f"{uuid.uuid4().hex[:10]}.html"
    report_svc.export_html_report(
        s.de, s.plots, s.expr.to_summary(),
        s.expr.metadata.to_dict(orient="records"),
        getattr(s, "enrich_results", None), project_name, out)
    return FileResponse(out, filename="bulkseq_report.html", media_type="text/html")


@app.post("/api/gene_plot")
def api_gene_plot(session_id: str = Form(...), gene: str = Form(...), sizes: str = Form("")):
    """单基因表达箱线图（原始 counts + 归一化表达）。支持自定义尺寸。"""
    s = _get_session(session_id)
    if s.expr is None or s.de is None:
        raise HTTPException(status_code=400, detail="请先完成差异分析。")
    gene = gene.strip()
    # 允许大小写不敏感匹配
    match = next((g for g in s.expr.counts.index if str(g).lower() == gene.lower()), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"基因 {gene} 不在表达矩阵中。")
    groups = s.expr.metadata.set_index("sample").loc[s.expr.counts.columns, "group"]
    import json as _json
    try:
        cfg = (_json.loads(sizes) if sizes else {}).get("gene") or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    dpi = max(72, min(int(cfg.get("dpi") or 150), 600))
    w_px = cfg.get("w_px") or cfg.get("w")
    h_px = cfg.get("h_px") or cfg.get("h")
    kw = {"width": float(w_px) / dpi if w_px else None,
          "height": float(h_px) / dpi if h_px else None, "dpi": dpi}
    try:
        out = plots_svc.plot_gene_boxplot(s.expr.counts, s.de["transformed"], match, groups, **kw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"绘图失败：{exc}")
    stats_row = s.de["results"].loc[match].to_dict() if match in s.de["results"].index else {}
    return {"ok": True, "gene": match, "image": _fig_url(out["image"]),
            "stats": {k: (None if pd.isna(v) else float(v)) for k, v in stats_row.items()}}


@app.get("/api/template/metadata")
def api_template_metadata():
    """下载设计表模板（样本名 + 分组），带 UTF-8 BOM 以便 Excel 直接打开不乱码。"""
    import io

    content = (
        "sample,group\n"
        "control_1,control\n"
        "control_2,control\n"
        "control_3,control\n"
        "treated_1,treated\n"
        "treated_2,treated\n"
        "treated_3,treated\n"
    )
    from fastapi.responses import Response

    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="design_template.csv"'},
    )


@app.get("/api/example/preview")
def api_example_preview():
    paths = example_data.write_example_files()
    counts = pd.read_csv(paths["counts"], index_col=0, nrows=6)
    meta = pd.read_csv(paths["metadata"])
    return JSONResponse({
        "counts_head": counts.head(6).reset_index().to_dict(orient="records"),
        "meta": meta.to_dict(orient="records"),
        "n_genes": int(len(pd.read_csv(paths["counts"], index_col=0, usecols=[0]))),
        "n_samples": int(counts.shape[1] - 1),
    })
