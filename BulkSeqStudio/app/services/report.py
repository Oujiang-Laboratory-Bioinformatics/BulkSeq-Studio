"""报告导出：HTML 交互报告 + Excel 结果工作簿。"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import APP_NAME, APP_VERSION, TEMPLATE_DIR, TMP_DIR
from app.services.plots import fig_to_data_uri

REPORT_DIR = TMP_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _img(path: str | None) -> str:
    if not path:
        return ""
    return fig_to_data_uri(path)


def _df_records(df: pd.DataFrame, max_rows: int = 500) -> list[dict]:
    return df.head(max_rows).reset_index().to_dict(orient="records")


def export_excel(de: dict, plots: dict, enrich_results: dict[str, pd.DataFrame] | None,
                 expr_summary: dict, out_path: Path) -> Path:
    res = de["results"].copy()
    res.index.name = "gene"
    sig = res[(res["padj"] < de["alpha"]) & (res["log2FoldChange"].abs() >= de["lfc_threshold"])]

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary = pd.DataFrame([
            ("软件", f"{APP_NAME} v{APP_VERSION}"),
            ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("分析引擎", de["engine"]),
            ("基因数", expr_summary.get("n_genes")),
            ("样本数", expr_summary.get("n_samples")),
            ("分组", json.dumps(expr_summary.get("groups", {}), ensure_ascii=False)),
            ("比较方向", f"{de['alt']} vs {de['ref']}"),
            ("显著性阈值", f"padj < {de['alpha']}, |log2FC| >= {de['lfc_threshold']}"),
            ("上调基因数", de["n_sig_up"]),
            ("下调基因数", de["n_sig_down"]),
        ], columns=["项目", "值"])
        summary.to_excel(writer, sheet_name="汇总", index=False)
        sig.sort_values("padj").to_excel(writer, sheet_name="显著差异基因", index=True)
        res.sort_values("padj").to_excel(writer, sheet_name="全部结果", index=True)
        de["normalized"].to_excel(writer, sheet_name="归一化矩阵", index=True)
        for name, df in (enrich_results or {}).items():
            if df is not None and not df.empty:
                sheet = name[:28].replace("/", "_").replace("\\", "_")
                df.to_excel(writer, sheet_name=sheet, index=False)
    return out_path


def export_html_report(
    de: dict, plots: dict, expr_summary: dict, meta_table: list[dict],
    enrich_results: dict[str, pd.DataFrame] | None, project_name: str, out_path: Path,
) -> Path:
    res = de["results"].copy().sort_values("padj")
    sig = res[(res["padj"] < de["alpha"]) & (res["log2FoldChange"].abs() >= de["lfc_threshold"])]

    enrich_tables = {}
    for name, df in (enrich_results or {}).items():
        if df is not None and not df.empty:
            enrich_tables[name] = _df_records(df, max_rows=30)

    html = _env.get_template("report.html").render(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        project_name=project_name,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        engine=de["engine"],
        comparison=f"{de['alt']} vs {de['ref']}",
        alpha=de["alpha"],
        lfc_threshold=de["lfc_threshold"],
        n_up=de["n_sig_up"],
        n_down=de["n_sig_down"],
        summary=expr_summary,
        meta_table=meta_table,
        sig_table=_df_records(sig, 100),
        size_factors=de.get("size_factors", {}),
        plots={k: _img(v.get("image")) for k, v in plots.items() if isinstance(v, dict)},
        enrich_tables=enrich_tables,
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path
