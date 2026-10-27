"""GO / KEGG 富集分析。

- 在线路径：gseapy.enrichr 调用 Enrichr 数据库（GO_Biological_Process_2023、KEGG_2021_Human 等）
- 离线路径：用户提供 GMT 文件，本地超几何检验（与 Enrichr 同算法）
"""
from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd


class EnrichError(RuntimeError):
    pass


# Enrichr 库：中文名 -> 库 ID
ENRICHR_LIBRARIES = {
    "GO-BP": "GO_Biological_Process_2023",
    "GO-CC": "GO_Cellular_Component_2023",
    "GO-MF": "GO_Molecular_Function_2023",
    "KEGG": "KEGG_2021_Human",
    "Reactome": "Reactome_2022",
    "MSigDB-Hallmark": "MSigDB_Hallmark_2020",
}


def read_gmt(path: str) -> dict[str, list[str]]:
    """读取 GMT 文件（每行：name<TAB>description<TAB>gene1<TAB>gene2...）。支持 .gz。"""
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    sets: dict[str, list[str]] = {}
    with opener(p, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            name = parts[0].strip()
            genes = [g.strip() for g in parts[2:] if g.strip()]
            if name and genes:
                sets[name] = genes
    if not sets:
        raise EnrichError("GMT 文件解析失败：未找到有效条目。")
    return sets


def _hypergeom_enrichr_style(
    query: list[str], gene_sets: dict[str, list[str]], background: list[str] | None, cutoff: float = 0.05
) -> pd.DataFrame:
    """标准超几何富集。背景基因集应传入分析时检测到的全部基因（universe）。"""
    from scipy.stats import hypergeom

    universe = set(background) if background else set()
    query_set = set(query)
    if len(universe) < len(query_set) * 2:
        # 背景无效时退化为宽松估计，避免显著性被高估
        universe = universe | query_set | {g for genes in gene_sets.values() for g in genes}
    query_set = query_set & universe if universe else query_set

    rows = []
    for name, genes in gene_sets.items():
        gs = set(genes)
        if universe:
            gs = gs & universe
        if not gs:
            continue
        overlap = gs & query_set
        M = len(universe)
        N = len(query_set)
        K = len(gs)
        k = len(overlap)
        if k == 0:
            pval = 1.0
        else:
            pval = float(hypergeom.sf(k - 1, M, K, N))
        rows.append({
            "Term": name,
            "Overlap": f"{k}/{K}",
            "overlap_count": k,
            "set_size": K,
            "Genes": ";".join(sorted(overlap)),
            "P-value": pval,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # BH 校正
    df = df.sort_values("P-value").reset_index(drop=True)
    n = len(df)
    ranks = np.arange(1, n + 1)
    padj = df["P-value"].to_numpy() * n / ranks
    padj = np.minimum.accumulate(padj[::-1])[::-1]
    df["Adjusted P-value"] = np.clip(padj, 0, 1)
    df["Combined Score"] = df["Adjusted P-value"].apply(lambda p: -np.log10(max(p, 1e-300)) * 1.0)
    df = df[df["Adjusted P-value"] < cutoff].sort_values("Combined Score", ascending=False).reset_index(drop=True)
    return df


def enrich_via_enrichr(query: list[str], library: str, cutoff: float = 0.05) -> pd.DataFrame:
    import gseapy as gp

    lib_id = ENRICHR_LIBRARIES.get(library, library)
    try:
        enr = gp.enrichr(
            gene_list=query, gene_sets=lib_id, organism="human",
            outdir=None, no_plot=True, cutoff=cutoff,
        )
    except Exception as exc:  # noqa: BLE001
        raise EnrichError(
            f"在线 Enrichr 查询失败（{exc}）。网络受限时可改用本地 GMT 文件模式。"
        ) from exc
    df = enr.results.rename(columns={
        "Term": "Term", "Overlap": "Overlap", "P-value": "P-value",
        "Adjust P-value": "Adjusted P-value", "Genes": "Genes",
    })
    df = df[df["Adjusted P-value"] < cutoff].sort_values("Combined Score", ascending=False).reset_index(drop=True)
    return df[["Term", "Overlap", "P-value", "Adjusted P-value", "Genes", "Combined Score"]]


def enrich_via_gmt(query: list[str], gmt_path: str, background: list[str] | None = None,
                   cutoff: float = 0.05) -> pd.DataFrame:
    sets = read_gmt(gmt_path)
    return _hypergeom_enrichr_style(query, sets, background, cutoff)


def enrichment_to_payload(df: pd.DataFrame, top: int = 40) -> dict:
    if df.empty:
        return {"terms": [], "n_total": 0}
    df = df.head(top)
    terms = []
    for _, r in df.iterrows():
        try:
            ov = str(r["Overlap"]).split("/")
            k, K = int(ov[0]), int(ov[1]) if len(ov) > 1 else int(ov[0])
        except Exception:  # noqa: BLE001
            k, K = 0, 1
        terms.append({
            "term": str(r["Term"]),
            "overlap": str(r["Overlap"]),
            "k": k, "K": K,
            "p": float(r["P-value"]),
            "padj": float(r["Adjusted P-value"]),
            "genes": str(r["Genes"]),
            "score": round(-np.log10(max(float(r["Adjusted P-value"]), 1e-300)), 2),
        })
    return {"terms": terms, "n_total": int(len(df))}
