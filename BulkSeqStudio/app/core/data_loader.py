"""表达矩阵与设计表(metadata)的读取、校验、规范化。"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


class DataError(ValueError):
    """数据格式或内容不符合要求。"""


SEP_CANDIDATES = [",", "\t", ";"]
META_SAMPLE_KEYS = ["sample", "samples", "sample_id", "sampleid", "sample name", "sample_name", "id", "名称", "样本"]
META_GROUP_HINTS = ["condition", "group", "groups", "treatment", "class", "status", "分组", "组别", "condition_group"]


def _read_table_from_bytes(raw: bytes, filename: str = "") -> pd.DataFrame:
    """自动嗅探分隔符，读取 csv/tsv/txt 文本。"""
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise DataError("无法解码文件内容，请另存为 UTF-8 编码后重试。")

    first_line = text.split("\n", 1)[0]
    sep = None
    best = -1
    for cand in SEP_CANDIDATES:
        cnt = first_line.count(cand)
        if cnt > best:
            best, sep = cnt, cand
    if best <= 0:
        raise DataError("未能识别分隔符。请使用逗号或制表符分隔的文本文件（csv / tsv / txt）。")

    df = pd.read_csv(io.StringIO(text), sep=sep, index_col=None)
    if df.shape[1] < 2:
        raise DataError("文件至少需要 2 列（基因列 + 至少 1 个样本列）。")
    return df


def read_uploaded_table(raw: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls", ".xlsm")):
        try:
            df = pd.read_excel(io.BytesIO(raw), sheet_name=0)
        except Exception as exc:  # noqa: BLE001
            raise DataError(f"Excel 读取失败：{exc}") from exc
        if df.shape[1] < 2:
            raise DataError("Excel 至少需要 2 列。")
        return df
    return _read_table_from_bytes(raw, filename)


@dataclass
class ExpressionData:
    counts: pd.DataFrame          # index=gene, columns=sample
    metadata: pd.DataFrame        # 第一列是 sample
    warnings: list[str] = field(default_factory=list)

    @property
    def genes(self) -> list[str]:
        return [str(g) for g in self.counts.index]

    @property
    def samples(self) -> list[str]:
        return [str(s) for s in self.counts.columns]

    def to_summary(self) -> dict:
        meta = self.metadata.copy()
        groups: dict[str, int] = {}
        if "group" in meta.columns:
            for val, cnt in meta["group"].astype(str).value_counts().items():
                groups[val] = int(cnt)
        return {
            "n_genes": int(self.counts.shape[0]),
            "n_samples": int(self.counts.shape[1]),
            "samples": self.samples,
            "columns": [c for c in meta.columns],
            "groups": groups,
            "warnings": self.warnings,
            "preview": {
                "index": [str(x) for x in self.counts.index[:8]],
                "columns": self.samples[:12],
                "rows": [[_safe_int(v) for v in row] for row in self.counts.iloc[:8, :12].to_numpy()],
            },
        }


def _safe_int(v):
    try:
        f = float(v)
        if np.isnan(f):
            return None
        return int(round(f))
    except (TypeError, ValueError):
        return None


def normalize_counts(df: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """把第一列（或索引）当作基因标识，其余列当作样本计数。"""
    df = df.copy()
    # 兼容基因名已在索引中的输入（如 read_csv(index_col=0) 的结果）
    if not isinstance(df.index, pd.RangeIndex):
        idx_name = str(df.index.name or "gene").strip()
        df = df.reset_index().rename(columns={idx_name: "gene"})
    df.columns = [str(c).strip() for c in df.columns]
    gene_col = df.columns[0]
    df = df.rename(columns={gene_col: "gene"})
    df["gene"] = df["gene"].astype(str).str.strip()
    df = df[df["gene"].ne("") & df["gene"].ne("nan")]
    df = df.drop_duplicates(subset="gene", keep="first")
    df = df.set_index("gene")

    # 丢弃全空列
    df = df.dropna(axis=1, how="all")
    if df.shape[1] < 2:
        raise DataError("样本数不足：至少需要 2 个样本列。")

    numeric = df.apply(pd.to_numeric, errors="coerce")
    bad_cols = [c for c in numeric.columns if numeric[c].isna().mean() > 0.5]
    if bad_cols:
        warnings.append(f"以下列不是数值型且被忽略：{', '.join(bad_cols[:6])}")
        numeric = numeric.drop(columns=bad_cols)
    if numeric.shape[1] < 2:
        raise DataError("有效样本列不足 2 个，请检查矩阵内容。")

    nonzero_before = len(numeric.columns)
    numeric = numeric.dropna(axis=1, how="all")
    dropped = nonzero_before - len(numeric.columns)
    if dropped:
        warnings.append(f"{dropped} 个样本列全为空值，已忽略。")

    if numeric.isna().any().any():
        n_na = int(numeric.isna().sum().sum())
        warnings.append(f"发现 {n_na} 个缺失值，已按 0 处理。")
        numeric = numeric.fillna(0)

    arr = numeric.to_numpy(dtype=float)
    if np.any(arr < 0):
        raise DataError("检测到负值。表达矩阵应为原始 counts（非负整数）。若为已归一化/对数化数据，请改用原始 counts。")
    if np.any(arr > 0) and np.allclose(arr, np.round(arr), atol=1e-6) is False:
        frac = float(np.mean(~np.isclose(arr, np.round(arr), atol=1e-6)))
        if frac > 0.01:
            warnings.append(
                f"{frac:.1%} 的数值不是整数，可能已做过归一化。DESeq2 类方法要求原始 counts，"
                "结果可能不可靠；如需分析此类数据请改用 limma-voom 或先还原为 counts。"
            )
    if numeric.shape[0] > 80000:
        raise DataError(f"基因数过多（{numeric.shape[0]}），超过上限 80000。")

    totals = numeric.sum(axis=0)
    if (totals <= 0).any():
        zero_samples = [c for c in numeric.columns if totals[c] <= 0]
        raise DataError(f"以下样本总计数为 0，无法分析：{', '.join(zero_samples)}")
    numeric = numeric.astype(np.int64)
    # 去掉在所有样本中计数都为 0 的基因
    keep = numeric.sum(axis=1) > 0
    n_zero = int((~keep).sum())
    if n_zero:
        warnings.append(f"{n_zero} 个基因在所有样本中计数为 0，已在计算时自动剔除。")
    return numeric.loc[keep]


def normalize_metadata(df: pd.DataFrame, sample_names: list[str], warnings: list[str]) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if df.shape[1] < 2:
        raise DataError("设计表至少需要两列：样本名 + 分组。")

    lower_map = {c.lower(): c for c in df.columns}
    sample_col = None
    for key in META_SAMPLE_KEYS:
        if key in lower_map:
            sample_col = lower_map[key]
            break
    if sample_col is None:
        sample_col = df.columns[0]
        warnings.append(f"未找到明显的样本名列，已使用第一列「{sample_col}」作为样本名。")

    df = df.rename(columns={sample_col: "sample"})
    df["sample"] = df["sample"].astype(str).str.strip()

    group_col = None
    for key in META_GROUP_HINTS:
        if key in {c.lower() for c in df.columns}:
            group_col = {c.lower(): c for c in df.columns}[key]
            break
    if group_col is None:
        remaining = [c for c in df.columns if c != "sample"]
        if not remaining:
            raise DataError("设计表缺少分组列。")
        group_col = remaining[0]
        warnings.append(f"未找到明显的分组列，已使用「{group_col}」作为分组变量。")
    df = df.rename(columns={group_col: "group"})
    df["group"] = df["group"].astype(str).str.strip()
    df = df[df["group"].ne("") & df["group"].ne("nan")]

    dup = df["sample"][df["sample"].duplicated()].tolist()
    if dup:
        raise DataError(f"设计表中样本名重复：{', '.join(sorted(set(dup))[:8])}")

    missing_meta = [s for s in sample_names if s not in set(df["sample"])]
    extra_meta = [s for s in df["sample"] if s not in set(sample_names)]
    if missing_meta:
        raise DataError(
            "设计表缺少以下样本（与表达矩阵列名不一致）：" + ", ".join(missing_meta[:10])
            + ("" if len(missing_meta) <= 10 else f" 等 {len(missing_meta)} 个")
        )
    if extra_meta:
        warnings.append(f"设计表中 {len(extra_meta)} 个样本在矩阵中不存在，已忽略：{', '.join(extra_meta[:6])}")

    df = df[df["sample"].isin(set(sample_names))].reset_index(drop=True)
    # 按矩阵列顺序排列
    order = {s: i for i, s in enumerate(sample_names)}
    df = df.sort_values("sample", key=lambda s: s.map(order)).reset_index(drop=True)

    counts = df["group"].value_counts()
    if len(counts) < 2:
        raise DataError(f"分组只有 1 个水平（{counts.index.tolist()}），无法做差异比较。")
    small = counts[counts < 2]
    for g, n in small.items():
        warnings.append(f"分组「{g}」只有 {n} 个重复样本，统计功效有限，建议每组至少 3 个重复。")
    return df


def load_tables(counts_df: pd.DataFrame, meta_df: pd.DataFrame) -> ExpressionData:
    warnings: list[str] = []
    counts = normalize_counts(counts_df, warnings)
    meta = normalize_metadata(meta_df, list(counts.columns), warnings)
    if counts.shape[1] < 4:
        warnings.append("样本数较少（<4），差异分析结果仅供探索参考。")
    return ExpressionData(counts=counts, metadata=meta, warnings=warnings)


def load_from_files(counts_path: Path, meta_path: Path) -> ExpressionData:
    counts_df = read_uploaded_table(Path(counts_path).read_bytes(), Path(counts_path).name)
    meta_df = read_uploaded_table(Path(meta_path).read_bytes(), Path(meta_path).name)
    return load_tables(counts_df, meta_df)


def expr_to_json(expr: ExpressionData) -> dict:
    return {
        "counts": {
            "genes": expr.genes,
            "samples": expr.samples,
            "values": expr.counts.to_numpy().astype(int).tolist(),
        },
        "metadata": expr.metadata.to_dict(orient="records"),
        "warnings": expr.warnings,
    }


def expr_from_json(obj: dict) -> ExpressionData:
    counts_obj = obj["counts"]
    counts = pd.DataFrame(
        counts_obj["values"], index=counts_obj["genes"], columns=counts_obj["samples"]
    )
    meta = pd.DataFrame(obj["metadata"])
    return ExpressionData(counts=counts, metadata=meta, warnings=obj.get("warnings", []))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
