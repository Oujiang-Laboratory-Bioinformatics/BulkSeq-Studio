"""示例数据集：内置一套公开的 airway RNA-seq 计数矩阵（genes x samples）。

基因名取自人类 Ensembl ID 对应的常用 symbol 集合，表达量按支气管平滑肌细胞
经地塞米松（dexamethasone）处理前后的真实生物学特征模拟生成：
- 一部分基因在 dex 处理后显著下调（如炎症通路基因）
- 一部分显著上调
- 其余为噪声背景，并保留负二项离散度特征
这样分析流程可以真实地跑出有生物学意义的差异基因。
"""
from __future__ import annotations

import shutil

import numpy as np
import pandas as pd

from app.core.config import BUNDLED_EXAMPLE_DIR, EXAMPLE_DIR

# 用于构造示例矩阵的基因集合：炎症 / 糖皮质激素响应 / 管家基因等
_DOWN_IN_DEX = [
    "CCL2", "CXCL1", "CXCL2", "CXCL8", "IL6", "IL1B", "TNF", "NFKB1", "NFKB2",
    "PTGS2", "ICAM1", "VCAM1", "SELE", "MMP1", "MMP9", "PLAUR", "SERPINE1",
    "CXCL5", "CXCL6", "CXCR4", "CCL20", "TNFAIP6", "BIRC3", "NFKBIZ", "RELB",
    "SOCS3", "STAT3", "JUN", "JUNB", "FOS", "EGR1", "ATF3", "DUSP1", "KLF6",
]
_UP_IN_DEX = [
    "DUSP1", "TSC22D3", "FKBP5", "PER1", "KLF15", "ANGPTL4", "MT1X", "MT2A",
    "SERPINA3", "CGB", "PLK3", "GDF15", "DDIT4", "TXNIP", "SGK1", "CCNG2",
    "SPARCL1", "PHLDA1", "SERPINF1", "ERRFI1",
]
_HOUSEKEEPING = [
    "ACTB", "GAPDH", "TUBB", "RPL13A", "EEF1A1", "PPIA", "B2M", "HPRT1",
    "TBP", "SDHA", "PGK1", "VIM", "TPM4", "CALM1", "UBB", "UBC",
]
_OTHER = [
    "COL1A1", "COL1A2", "COL3A1", "FN1", "SPARC", "LUM", "DCN", "THBS1",
    "CTGF", "CYR61", "SERPINH1", "LOX", "FBN1", "ELN", "MFAP4", "CD44",
    "KRT19", "KRT8", "KRT18", "EPCAM", "CLDN3", "CLDN4", "MUC1", "TFF3",
    "AGR2", "S100A2", "S100A10", "ANXA1", "ANXA2", "LGALS1", "LGALS3", "TAGLN",
    "MYL9", "CNN1", "ACTA2", "DES", "MYH11", "LMOD1", "CSRP1", "CALD1",
    "TPM2", "TMSB4X", "TMSB10", "PFN1", "CFL1", "GSN", "ARPC2", "ARPC3",
    "RPLP0", "RPS6", "RPS18", "RPL8", "EIF4B", "EIF3L", "NCL", "NPM1",
    "HNRNPA1", "SRSF3", "SRSF7", "YBX1", "PTMA", "HMGB1", "HMGB2", "CHCHD2",
    "ATP5F1E", "COX4I1", "COX6C", "NDUFA4", "UQCRB", "ATP5MC3", "TOMM7",
]


def _all_genes() -> list[str]:
    genes = list(dict.fromkeys(_DOWN_IN_DEX + _UP_IN_DEX + _HOUSEKEEPING + _OTHER))
    # 补齐到 2000 个基因，用合成 symbol 填充（背景基因）
    i = 1
    while len(genes) < 2000:
        name = f"GENE{i:04d}"
        if name not in genes:
            genes.append(name)
        i += 1
    return genes


def build_example_dataset(seed: int = 2024, n_rep: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (counts, metadata)。counts: genes x samples 整数矩阵。"""
    rng = np.random.default_rng(seed)
    genes = _all_genes()
    n_genes = len(genes)

    sample_names: list[str] = []
    conditions: list[str] = []
    for rep in range(1, n_rep + 1):
        sample_names.append(f"untreated_{rep}")
        conditions.append("untreated")
    for rep in range(1, n_rep + 1):
        sample_names.append(f"dex_{rep}")
        conditions.append("dex")

    library_size = rng.integers(18_000_000, 32_000_000, size=len(sample_names)).astype(float)

    # 基础表达强度：对数正态分布
    base_mean = np.exp(rng.normal(loc=4.2, scale=1.6, size=n_genes))
    # 让管家基因高表达
    for g in _HOUSEKEEPING:
        if g in genes:
            base_mean[genes.index(g)] *= 30

    counts = np.zeros((n_genes, len(sample_names)), dtype=np.int64)
    mean_lib = float(np.mean(library_size))

    # 每个样本的整体缩放因子（模拟文库与批次差异）
    sample_scale = rng.lognormal(mean=0.0, sigma=0.18, size=len(sample_names))
    lib_ratio = library_size / mean_lib

    for gi in range(n_genes):
        g = genes[gi]
        mu = base_mean[gi]
        effect = 1.0
        if g in _DOWN_IN_DEX:
            effect = rng.uniform(0.15, 0.45)   # 下调
        elif g in _UP_IN_DEX:
            effect = rng.uniform(2.2, 6.0)     # 上调
        elif g in _HOUSEKEEPING:
            effect = rng.uniform(0.92, 1.08)
        else:
            # 背景基因大部分无变化，少量随机波动
            effect = float(np.exp(rng.normal(0, 0.25)))

        for si, cond in enumerate(conditions):
            target = mu * (effect if cond == "dex" else 1.0) * sample_scale[si] * lib_ratio[si]
            # 负二项抽样：离散度随表达量变化
            dispersion = 0.08 + 3.0 / (target + 1.0)
            size = 1.0 / dispersion
            p = size / (size + target)
            counts[gi, si] = rng.negative_binomial(size, p)

    counts_df = pd.DataFrame(counts, index=genes, columns=sample_names)
    meta_df = pd.DataFrame({
        "sample": sample_names,
        "condition": conditions,
        "replicate": list(range(1, n_rep + 1)) * 2,
    })
    return counts_df, meta_df


def write_example_files(force: bool = False) -> dict[str, str]:
    counts_path = EXAMPLE_DIR / "airway_like_counts.csv"
    meta_path = EXAMPLE_DIR / "airway_like_metadata.csv"
    if force or not counts_path.exists() or not meta_path.exists():
        # 随包附带的示例数据优先（安装包内只带一份，避免每次生成）
        bundled = (BUNDLED_EXAMPLE_DIR / "airway_like_counts.csv",
                   BUNDLED_EXAMPLE_DIR / "airway_like_metadata.csv")
        if all(p.exists() for p in bundled):
            try:
                EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
                for src, dst in zip(bundled, (counts_path, meta_path)):
                    shutil.copyfile(src, dst)
                return {"counts": str(counts_path), "metadata": str(meta_path)}
            except Exception:  # noqa: BLE001
                pass
        counts, meta = build_example_dataset()
        counts.to_csv(counts_path, index_label="gene")
        meta.to_csv(meta_path, index=False)
    return {"counts": str(counts_path), "metadata": str(meta_path)}
