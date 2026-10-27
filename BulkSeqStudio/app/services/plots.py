"""图表绘制：PCA、相关性热图、样本聚类、火山图、MA 图、差异基因热图、分布箱线图。

输出 PNG（预览用）+ 交互式数据（前端 ECharts 用）由 API 直接提供 JSON。
"""
from __future__ import annotations

import io
import uuid
from contextvars import ContextVar
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats
from sklearn.decomposition import PCA

from app.core.config import TMP_DIR

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

SAVE_DIR = TMP_DIR / "figures"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# 预览默认只输出 PNG；导出时临时追加 "pdf"（矢量，页面尺寸 = figsize 英寸）
_SAVE_FORMATS: ContextVar[tuple[str, ...]] = ContextVar("save_formats", default=("png",))

COLOR_UP = "#d62728"
COLOR_DOWN = "#1a9850"
COLOR_NS = "#9e9e9e"
PALETTE = ["#4c72b0", "#dd8452", "#55a868", "#c44e52", "#8172b3", "#937860"]


def _save(fig, dpi: int = 150, tight: bool = True) -> str:
    """保存图片。

    - tight=True 时按内容裁边（默认更紧凑）；用户自定义尺寸时应传 tight=False，
      否则 bbox_inches="tight" 会把画布裁回内容大小，导致指定尺寸失效。
    - 额外格式由 `_SAVE_FORMATS` 控制（正常预览只存 PNG；导出 PDF 时会同时存同尺寸
      的矢量 PDF），返回值为 PNG 路径，PDF 与 PNG 主名相同。
    """
    stem = SAVE_DIR / uuid.uuid4().hex[:12]
    bbox = "tight" if tight else None
    for fmt in _SAVE_FORMATS.get():
        fig.savefig(f"{stem}.{fmt}", dpi=dpi, bbox_inches=bbox, format=fmt)
    plt.close(fig)
    return f"{stem}.png"


def set_save_formats(formats: tuple[str, ...]):
    """请求级设置保存格式（ContextVar，线程安全）。"""
    return _SAVE_FORMATS.set(tuple(formats))


def reset_save_formats(token) -> None:
    _SAVE_FORMATS.reset(token)


def plot_pca(transformed: pd.DataFrame, group_series: pd.Series, title: str = "PCA",
             width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    """transformed: genes x samples（vst 或 log2 归一化矩阵）。返回 {image, data}。"""
    X = transformed.T  # samples x genes
    X = X.loc[:, X.std() > 0]
    n_comp = min(4, X.shape[0], X.shape[1])
    pca = PCA(n_components=n_comp)
    coords = pca.fit_transform(X)
    var = pca.explained_variance_ratio_ * 100

    groups = group_series.astype(str)
    uniq = list(dict.fromkeys(groups))
    cmap = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(uniq)}

    fig, ax = plt.subplots(figsize=(width or 7, height or 5.5))
    for g in uniq:
        m = (groups == g).to_numpy()
        ax.scatter(coords[m, 0], coords[m, 1], s=90, c=cmap[g], label=g, edgecolors="white", linewidths=1.2)
    for i, s in enumerate(X.index):
        ax.annotate(str(s), (coords[i, 0], coords[i, 1]), fontsize=8, xytext=(5, 4),
                    textcoords="offset points", alpha=0.75)
    ax.set_xlabel(f"PC1 ({var[0]:.1f}%)")
    ax.set_ylabel(f"PC2 ({var[1]:.1f}%)")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    image = _save(fig, dpi, tight=(width is None and height is None))
    return {
        "image": image,
        "data": {
            "samples": [str(s) for s in X.index],
            "groups": groups.tolist(),
            "pc1": [round(float(v), 4) for v in coords[:, 0]],
            "pc2": [round(float(v), 4) for v in coords[:, 1]],
            "var1": round(float(var[0]), 2),
            "var2": round(float(var[1]), 2),
            "colors": {g: cmap[g] for g in uniq},
        },
    }


def plot_sample_correlation(transformed: pd.DataFrame, group_series: pd.Series,
                            width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    corr = transformed.corr(method="spearman")
    fig, ax = plt.subplots(figsize=(width or max(6, 0.6 * len(corr)), height or max(5, 0.55 * len(corr))))
    sns.heatmap(corr, annot=len(corr) <= 12, fmt=".2f", cmap="RdYlBu_r", vmin=0.5, vmax=1,
                square=True, ax=ax, cbar_kws={"label": "Spearman 相关"})
    ax.set_title("样本相关性热图")
    image = _save(fig, dpi, tight=(width is None and height is None))
    return {
        "image": image,
        "data": {
            "samples": [str(s) for s in corr.columns],
            "matrix": [[round(float(v), 4) for v in row] for row in corr.to_numpy()],
            "groups": group_series.astype(str).tolist(),
        },
    }


def plot_sample_distance(transformed: pd.DataFrame, group_series: pd.Series,
                         width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    d = 1 - transformed.corr(method="spearman")
    fig, ax = plt.subplots(figsize=(width or max(6, 0.6 * len(d)), height or max(5, 0.55 * len(d))))
    sns.heatmap(d, cmap="viridis", square=True, ax=ax, cbar_kws={"label": "1 - 相关性"})
    ax.set_title("样本距离矩阵")
    return {"image": _save(fig, dpi, tight=(width is None and height is None))}


def plot_count_distribution(counts: pd.DataFrame, group_series: pd.Series,
                           width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    log_counts = np.log2(counts + 1)
    fig, ax = plt.subplots(figsize=(width or max(6, 0.7 * log_counts.shape[1]), height or 5))
    groups = group_series.astype(str)
    uniq = list(dict.fromkeys(groups))
    cmap = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(uniq)}
    data = [log_counts.iloc[:, i] for i in range(log_counts.shape[1])]
    bp = ax.boxplot(data, tick_labels=[str(c) for c in log_counts.columns], showfliers=False, patch_artist=True)
    for patch, col in zip(bp["boxes"], groups):
        patch.set_facecolor(cmap[col])
        patch.set_alpha(0.75)
    handles = [plt.Rectangle((0, 0), 1, 1, fc=cmap[g], alpha=0.75) for g in uniq]
    ax.legend(handles, uniq, frameon=False)
    ax.set_ylabel("log2(counts + 1)")
    ax.set_title("样本表达分布（箱线图）")
    ax.tick_params(axis="x", rotation=45)
    return {"image": _save(fig, dpi, tight=(width is None and height is None))}


def plot_volcano(results: pd.DataFrame, alpha: float, lfc_threshold: float,
                 label_top: int = 12, title: str = "火山图",
                 width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    df = results.dropna(subset=["padj", "log2FoldChange"]).copy()
    x = df["log2FoldChange"].to_numpy()
    y = -np.log10(np.clip(df["padj"].to_numpy(), 1e-300, None))

    up = (df["padj"] < alpha) & (df["log2FoldChange"] >= lfc_threshold)
    down = (df["padj"] < alpha) & (df["log2FoldChange"] <= -lfc_threshold)

    fig, ax = plt.subplots(figsize=(width or 7.5, height or 6))
    ax.scatter(x[~(up | down)], y[~(up | down)], s=8, c=COLOR_NS, alpha=0.5, label="NS", rasterized=True)
    ax.scatter(x[up.to_numpy()], y[up.to_numpy()], s=12, c=COLOR_UP, alpha=0.8, label=f"Up ({int(up.sum())})")
    ax.scatter(x[down.to_numpy()], y[down.to_numpy()], s=12, c=COLOR_DOWN, alpha=0.8, label=f"Down ({int(down.sum())})")

    if lfc_threshold > 0:
        for v in (lfc_threshold, -lfc_threshold):
            ax.axvline(v, color="#666", lw=0.8, ls="--")
    ax.axhline(-np.log10(alpha), color="#666", lw=0.8, ls="--")

    # 标注最显著基因
    top = df.assign(_y=y).sort_values("_y", ascending=False).head(label_top)
    for _, r in top.iterrows():
        ax.annotate(str(r.name), (r["log2FoldChange"], -np.log10(max(r["padj"], 1e-300))),
                    fontsize=7.5, alpha=0.9, xytext=(3, 3), textcoords="offset points")
    ymax = float(np.nanmax(y)) if len(y) else 1.0
    ax.set_ylim(0, min(ymax * 1.08, 400))
    ax.set_xlabel("log2 Fold Change")
    ax.set_ylabel("-log10(padj)")
    ax.set_title(title)
    ax.legend(frameon=False)
    return {"image": _save(fig, dpi, tight=(width is None and height is None))}


def plot_ma(results: pd.DataFrame, alpha: float, label_top: int = 10,
            width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    df = results.dropna(subset=["baseMean", "log2FoldChange"]).copy()
    x = np.log10(np.clip(df["baseMean"].to_numpy(), 1, None))
    y = df["log2FoldChange"]
    sig = df["padj"] < alpha

    fig, ax = plt.subplots(figsize=(width or 7.5, height or 5.5))
    ax.scatter(x[~sig.to_numpy()], y[~sig.to_numpy()], s=8, c=COLOR_NS, alpha=0.5, label="NS", rasterized=True)
    ax.scatter(x[sig.to_numpy()], y[sig.to_numpy()], s=12,
               c=np.where(y[sig].to_numpy() > 0, COLOR_UP, COLOR_DOWN), alpha=0.8, label="FDR")
    top = df[sig].abs().assign(_y=y[sig].abs()).sort_values("_y", ascending=False).head(label_top)
    for _, r in top.iterrows():
        ax.annotate(str(r.name), (np.log10(max(r["baseMean"], 1)), r["log2FoldChange"]),
                    fontsize=7.5, xytext=(3, 3), textcoords="offset points")
    ax.axhline(0, color="#666", lw=0.8)
    ax.set_xlabel("log10(baseMean)")
    ax.set_ylabel("log2 Fold Change")
    ax.set_title("MA 图")
    ax.legend(frameon=False)
    return {"image": _save(fig, dpi, tight=(width is None and height is None))}


def plot_de_heatmap(transformed: pd.DataFrame, sig_genes: list[str],
                    group_series: pd.Series, top_n: int = 50, title: str = "差异基因热图",
                    width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    if not sig_genes:
        raise ValueError("没有显著差异基因，无法绘制热图。")
    genes = sig_genes[:top_n]
    mat = transformed.loc[transformed.index.intersection(genes)]
    # 按行 z-score
    mat = mat.subtract(mat.mean(axis=1), axis=0).div(mat.std(axis=1).replace(0, 1), axis=0)
    groups = group_series.astype(str)
    uniq = list(dict.fromkeys(groups))
    cmap = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(uniq)}
    row_colors = pd.Series([cmap[g] for g in groups], index=transformed.columns, name="Group")

    g = sns.clustermap(
        mat, cmap="RdBu_r", center=0, figsize=(width or 7, height or max(6, 0.28 * len(mat))),
        row_colors=row_colors.loc[mat.columns], col_cluster=True, row_cluster=True,
        cbar_pos=(0.02, 0.82, 0.03, 0.15), dendrogram_ratio=0.12,
        xticklabels=True if len(mat.columns) <= 20 else False, yticklabels=False,
    )
    g.figure.suptitle(title, y=1.01 if (width is None and height is None) else 0.98)
    if len(mat.columns) <= 20:
        plt.setp(g.ax_heatmap.get_xticklabels(), rotation=45, fontsize=8)
    handles = [plt.Rectangle((0, 0), 1, 1, fc=cmap[grp]) for grp in uniq]
    g.figure.legend(handles, uniq, loc="upper right", frameon=False, ncol=len(uniq))
    return {"image": _save(g.figure, dpi, tight=(width is None and height is None))}


def plot_gene_boxplot(counts: pd.DataFrame, transformed: pd.DataFrame,
                      gene: str, group_series: pd.Series,
                      width: float | None = None, height: float | None = None, dpi: int = 150) -> dict:
    if gene not in counts.index:
        raise ValueError(f"基因 {gene} 不在矩阵中。")
    groups = group_series.astype(str)
    uniq = list(dict.fromkeys(groups))
    cmap = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(uniq)}

    fig, axes = plt.subplots(1, 2, figsize=(width or 10, height or 4.5))
    for ax, data, ylab in (
        (axes[0], counts.loc[gene], "raw counts"),
        (axes[1], transformed.loc[gene] if gene in transformed.index else np.log2(counts.loc[gene] + 1), "normalized"),
    ):
        vals = pd.Series(np.asarray(data), index=counts.columns)
        for g in uniq:
            m = (groups == g).to_numpy()
            ax.scatter([g] * int(m.sum()), vals[m], c=cmap[g], s=70, edgecolors="white", zorder=3)
            ax.bar(g, vals[m].mean(), width=0.6, color=cmap[g], alpha=0.25, zorder=2)
        ax.set_ylabel(ylab)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_title(gene)
    return {"image": _save(fig, dpi, tight=(width is None and height is None))}


def fig_to_data_uri(path: str) -> str:
    import base64
    p = Path(path)
    if not p.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def image_to_pdf(image_bytes: bytes, width_in: float, height_in: float) -> str:
    """把位图（如 ECharts 导出的画布）包成指定页面尺寸的 PDF（供交互图“保存为 PDF”）。"""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    fig = plt.figure(figsize=(width_in, height_in))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img)
    ax.axis("off")
    out = SAVE_DIR / f"{uuid.uuid4().hex[:12]}.pdf"
    fig.savefig(out, format="pdf", dpi=150)
    plt.close(fig)
    return str(out)
