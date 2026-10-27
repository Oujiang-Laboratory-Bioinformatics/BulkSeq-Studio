"""差异表达分析引擎。

支持两种后端：
- R 引擎（推荐）：调用本地 Rscript，支持 DESeq2 / edgeR / limma-voom
- Python 引擎：pydeseq2（DESeq2 的 Python 实现）

统一输出结果结构：
{
  "engine": "R/DESeq2",
  "results": DataFrame-like list[dict],   # 基因级别统计
  "normalized": DataFrame,                # 归一化表达矩阵 (genes x samples)
  "size_factors": dict,                   # 各样本文库因子
  "n_sig_up": int, "n_sig_down": int,
}
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import (
    FROZEN, RSCRIPT_PATH, R_WORK_DIR, TMP_DIR, r_home_ascii, short_path,
)
from app.core.data_loader import ExpressionData


class AnalysisError(RuntimeError):
    pass


R_METHODS = {"DESeq2", "edgeR", "limma"}
PY_METHODS = {"pydeseq2"}


def available_engines() -> dict:
    r_ok = Path(RSCRIPT_PATH).exists()
    py_ok = True
    try:
        import pydeseq2  # noqa: F401
    except ImportError:
        py_ok = False
    return {
        "r_available": r_ok,
        "rscript_path": RSCRIPT_PATH if r_ok else None,
        "pydeseq2_available": py_ok,
        "methods": {
            "DESeq2": r_ok,
            "edgeR": r_ok,
            "limma": r_ok,
            "pydeseq2": py_ok,
        },
        "default": "DESeq2" if r_ok else ("pydeseq2" if py_ok else None),
    }


# ---------------------------------------------------------------- R 引擎 ---

_R_SCRIPT = r"""
args <- commandArgs(trailingOnly = TRUE)
counts_file <- args[1]
meta_file   <- args[2]
out_prefix  <- args[3]
method      <- args[4]

counts <- read.delim(counts_file, row.names = 1, check.names = FALSE)
meta   <- read.delim(meta_file, stringsAsFactors = FALSE)
meta$group <- factor(meta$group)

# 按矩阵列顺序对齐
meta <- meta[match(colnames(counts), meta$sample), ]
if (any(is.na(meta$sample))) stop("样本名无法对齐")
counts <- as.matrix(counts)
storage.mode(counts) <- "integer"
ref <- levels(meta$group)[1]
alt <- levels(meta$group)[2]
meta$group <- relevel(meta$group, ref = ref)

write_lines <- function(df, path) write.csv(df, path, row.names = TRUE, quote = FALSE, na = "")

if (method == "DESeq2") {
  suppressPackageStartupMessages(library(DESeq2))
  dds <- DESeqDataSetFromMatrix(countData = counts, colData = meta, design = ~ group)
  dds <- DESeq(dds, quiet = TRUE)
  res <- results(dds, contrast = c("group", alt, ref))
  res_df <- as.data.frame(res)
  res_df$gene <- rownames(res_df)
  norm <- as.data.frame(counts(dds, normalized = TRUE))
  sf <- sizeFactors(dds)
  # VST 用于下游 PCA / 热图
  vsd <- tryCatch(vst(dds, blind = TRUE), error = function(e) NULL)
  if (is.null(vsd)) {
    transformed <- as.data.frame(log2(counts(dds, normalized = TRUE) + 1))
  } else {
    transformed <- as.data.frame(assay(vsd))
  }
} else if (method == "edgeR") {
  suppressPackageStartupMessages(library(edgeR))
  y <- DGEList(counts = counts, group = meta$group)
  y <- calcNormFactors(y)
  design <- model.matrix(~ group, data = meta)
  y <- estimateDisp(y, design)
  fit <- glmQLFit(y, design)
  res <- glmQLFTest(fit, coef = 2)
  tt <- topTags(res, n = Inf)$table
  res_df <- data.frame(
    gene = rownames(tt), baseMean = rowMeans(y$counts[rownames(tt), , drop = FALSE]),
    log2FoldChange = tt$logFC, lfcSE = NA, stat = NA,
    pvalue = tt$PValue, padj = tt$FDR
  )
  norm <- as.data.frame(cpm(y, normalized.lib.sizes = TRUE))  # CPM
  sf <- y$samples$norm.factors
  names(sf) <- rownames(y$samples)
  transformed <- as.data.frame(log2(norm + 1))
} else if (method == "limma") {
  suppressPackageStartupMessages(library(edgeR))
  suppressPackageStartupMessages(library(limma))
  norm_lib <- calcNormFactors(DGEList(counts = counts))
  cpm_mat <- cpm(norm_lib)
  keep <- rowSums(cpm_mat > 1) >= 2
  design <- model.matrix(~ 0 + group, data = meta)
  colnames(design) <- levels(meta$group)
  v <- voom(norm_lib[keep, ], design, plot = FALSE)
  fit <- lmFit(v, design)
  contrast_name <- paste0(alt, "_vs_", ref)
  cont <- makeContrasts(contrasts = paste0(alt, " - ", ref), levels = design)
  fit2 <- eBayes(contrasts.fit(fit, cont))
  tt <- topTable(fit2, number = Inf, adjust.method = "BH")
  res_df <- data.frame(
    gene = rownames(tt), baseMean = rowMeans(cpm_mat[rownames(tt), ]),
    log2FoldChange = tt$logFC, lfcSE = NA, stat = tt$t,
    pvalue = tt$P.Value, padj = tt$adj.P.Val
  )
  norm <- as.data.frame(cpm_mat)
  sf <- norm_lib$samples$norm.factors
  names(sf) <- rownames(norm_lib$samples)
  transformed <- as.data.frame(log2(norm + 1))
} else {
  stop("未知方法: ", method)
}

res_df <- res_df[order(res_df$pvalue, na.last = TRUE), ]
write_lines(res_df, paste0(out_prefix, "_results.csv"))
write_lines(norm, paste0(out_prefix, "_norm.csv"))
write_lines(transformed, paste0(out_prefix, "_transformed.csv"))
write.csv(data.frame(sample = names(sf), size_factor = as.numeric(sf)),
          paste0(out_prefix, "_sizefactors.csv"), row.names = FALSE, quote = FALSE)
cat("OK\t", method, "\t", nrow(res_df), "\t", ref, "\t", alt, "\n")
"""


def run_r_engine(
    expr: ExpressionData, method: str, alpha: float = 0.05, lfc_threshold: float = 0.0
) -> dict:
    if method not in R_METHODS:
        raise AnalysisError(f"不支持的 R 方法：{method}")
    rscript = RSCRIPT_PATH
    if not Path(rscript).exists():
        raise AnalysisError(f"未找到 Rscript：{rscript}")

    job = uuid.uuid4().hex[:12]
    # R 对含中文/空格的路径支持不稳定，统一放到纯 ASCII 的 R_WORK_DIR 下
    work = R_WORK_DIR / f"de_{job}"
    work.mkdir(parents=True, exist_ok=True)
    counts_f = work / "counts.tsv"
    meta_f = work / "meta.tsv"
    out_prefix = str(work / "out")

    expr.counts.to_csv(counts_f, sep="\t", index_label="gene")
    expr.metadata[["sample", "group"]].to_csv(meta_f, sep="\t", index=False)

    script_f = work / "run.R"
    script_f.write_text(_R_SCRIPT, encoding="utf-8")

    cmd = [short_path(rscript), str(script_f), str(counts_f), str(meta_f), out_prefix, method]
    env = os.environ.copy()
    # R 自己的临时目录也指向 ASCII 路径，避免 tempfile 写入失败
    env["TMPDIR"] = str(R_WORK_DIR)
    env["TEMP"] = str(R_WORK_DIR)
    env["TMP"] = str(R_WORK_DIR)
    # Windows 版 R 不需要 POSIX locale 变量；若从 Git Bash 等环境继承 LANG=*.UTF-8，
    # R 的 locale 初始化会失败，并把中文路径二次编码成乱码（library() 直接报错）。
    for _k in ("LANG", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME",
               "LC_COLLATE", "LC_MONETARY", "LC_MESSAGES"):
        env.pop(_k, None)
    # R_HOME 用 8.3 短路径，规避中文安装路径下 library() 找不到包的问题
    rhome = r_home_ascii()
    if rhome:
        env["R_HOME"] = rhome
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
            encoding="utf-8", errors="replace", env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError("R 分析超时（30 分钟）。") from exc
    if proc.returncode != 0:
        err_tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        raise AnalysisError(f"R {method} 运行失败：\n{err_tail}")

    results = pd.read_csv(work / "out_results.csv", index_col=0)
    results.columns = [c if c != "gene" else "gene" for c in results.columns]
    if "gene" in results.columns:
        results = results.drop(columns=["gene"])
    norm = pd.read_csv(work / "out_norm.csv", index_col=0)
    transformed = pd.read_csv(work / "out_transformed.csv", index_col=0)
    sf_df = pd.read_csv(work / "out_sizefactors.csv")

    sig = results[(results["padj"] < alpha) & (results["log2FoldChange"].abs() >= lfc_threshold)]
    n_up = int((sig["log2FoldChange"] > 0).sum())
    n_down = int((sig["log2FoldChange"] < 0).sum())

    return {
        "engine": f"R/{method}",
        "results": results,
        "normalized": norm,
        "transformed": transformed,
        "size_factors": dict(zip(sf_df["sample"].astype(str), sf_df["size_factor"].astype(float))),
        "n_sig_up": n_up,
        "n_sig_down": n_down,
        "alpha": alpha,
        "lfc_threshold": lfc_threshold,
        "ref": str(expr.metadata["group"].iloc[0]) if method != "DESeq2" else _levels_ref(expr),
        "alt": _levels_alt(expr),
    }


def _levels_ref(expr: ExpressionData) -> str:
    return sorted(expr.metadata["group"].astype(str).unique())[0]


def _levels_alt(expr: ExpressionData) -> str:
    lv = sorted(expr.metadata["group"].astype(str).unique())
    return lv[1] if len(lv) > 1 else lv[0]


# --------------------------------------------------------- Python 引擎 ---

def _threaded_inference():
    """为打包环境构造基于线程后端的 pydeseq2 inference 对象。

    pydeseq2 内部用 ``joblib.Parallel`` + loky 多进程；在 PyInstaller 冻结的
    可执行文件中，loky 无法启动子进程（子进程会重新执行入口程序）。这里把它
    的 ``parallel_backend`` 包装成 threading，并去掉 threading 不支持的
    ``inner_max_num_threads`` 参数。
    """
    try:
        from contextlib import contextmanager

        import pydeseq2.default_inference as di
        from pydeseq2.default_inference import DefaultInference

        if not getattr(di, "_bulkseq_threading_patched", False):
            _orig = di.parallel_backend

            @contextmanager
            def _pb(backend=None, **kw):
                kw.pop("inner_max_num_threads", None)
                with _orig("threading", **kw) as ctx:
                    yield ctx

            di.parallel_backend = _pb
            di._bulkseq_threading_patched = True

        return DefaultInference(n_cpus=1, backend="threading")
    except Exception:  # noqa: BLE001
        return None


def run_py_engine(
    expr: ExpressionData, method: str = "pydeseq2", alpha: float = 0.05, lfc_threshold: float = 0.0
) -> dict:
    if method not in PY_METHODS:
        raise AnalysisError(f"不支持的 Python 方法：{method}")
    try:
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.ds import DeseqStats
    except ImportError as exc:
        raise AnalysisError("pydeseq2 未安装，无法使用 Python 引擎。") from exc

    counts = expr.counts.T  # samples x genes
    meta = expr.metadata.set_index("sample").loc[counts.index]
    ref, alt = _levels_ref(expr), _levels_alt(expr)

    # 打包成 exe 后 joblib 的 loky 子进程无法启动（子进程会再次拉起本程序），
    # 改用线程后端 + 单进程；源码运行时仍用默认多进程以利用多核。
    inference = _threaded_inference() if FROZEN else None

    dds_kw = dict(counts=counts, metadata=meta[["group"]], design_factors="group",
                  refit_cooks=True, n_cpus=1)
    stat_kw = dict(contrast=["group", alt, ref], alpha=alpha, n_cpus=1)
    if inference is not None:
        dds_kw["inference"] = inference
        stat_kw["inference"] = inference

    try:
        dds = DeseqDataSet(quiet=True, **dds_kw)
    except TypeError:
        dds = DeseqDataSet(**dds_kw)
    dds.deseq2()
    try:
        stat = DeseqStats(dds, quiet=True, **stat_kw)
    except TypeError:
        stat = DeseqStats(dds, **stat_kw)
    stat.summary()
    res = stat.results_df.copy()  # index=gene

    results = pd.DataFrame({
        "baseMean": res["baseMean"],
        "log2FoldChange": res["log2FoldChange"],
        "lfcSE": res["lfcSE"],
        "stat": res["stat"],
        "pvalue": res["pvalue"],
        "padj": res["padj"],
    })
    norm_vals = dds.layers["normed_counts"] if "normed_counts" in dds.layers else None
    if norm_vals is not None:
        norm = pd.DataFrame(np.asarray(norm_vals).T, index=counts.columns, columns=counts.index)
    else:
        sf_vec = dds.obsm["size_factors"]
        norm = counts.div(sf_vec, axis=0).T
    transformed = np.log2(norm + 1)

    sig = results[(results["padj"] < alpha) & (results["log2FoldChange"].abs() >= lfc_threshold)]
    n_up = int((sig["log2FoldChange"] > 0).sum())
    n_down = int((sig["log2FoldChange"] < 0).sum())
    if "size_factors" in dds.obsm:
        sf = pd.Series(dds.obsm["size_factors"], index=counts.index)
    else:
        sf = counts.sum(axis=1) / norm.sum(axis=0).reindex(counts.index)
    return {
        "engine": "Python/pydeseq2",
        "results": results,
        "normalized": norm,
        "transformed": transformed,
        "size_factors": {str(k): float(v) for k, v in sf.dropna().items()},
        "n_sig_up": n_up,
        "n_sig_down": n_down,
        "alpha": alpha,
        "lfc_threshold": lfc_threshold,
        "ref": ref,
        "alt": alt,
    }


def run_de_analysis(
    expr: ExpressionData, method: str, alpha: float = 0.05, lfc_threshold: float = 0.0
) -> dict:
    if method in R_METHODS:
        return run_r_engine(expr, method, alpha, lfc_threshold)
    if method in PY_METHODS:
        return run_py_engine(expr, method, alpha, lfc_threshold)
    raise AnalysisError(f"未知方法：{method}")


def results_to_payload(de: dict) -> dict:
    res = de["results"]
    res = res.replace([np.inf, -np.inf], np.nan)
    payload = {
        "engine": de["engine"],
        "n_sig_up": de["n_sig_up"],
        "n_sig_down": de["n_sig_down"],
        "alpha": de["alpha"],
        "lfc_threshold": de["lfc_threshold"],
        "ref": de["ref"],
        "alt": de["alt"],
        "size_factors": de["size_factors"],
        "columns": ["gene"] + [str(c) for c in res.columns],
        "rows": [
            [str(idx)] + [_fnum(v) for v in row]
            for idx, row in zip(res.index, res.to_numpy())
        ],
    }
    return payload


def _fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(f):
        return None
    return round(f, 6)
