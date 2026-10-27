[README.md](https://github.com/user-attachments/files/34011492/README.md)
# BulkSeq Studio

一个面向**非生信背景科研人员**的本地 bulk RNA-seq 差异分析软件。图形界面、一键分析、零命令行——从表达矩阵出发，几分钟内完成差异分析与通路富集。

> 从表达矩阵和分组信息开始，不包含上游测序质控与比对（fastq → counts 请使用 fastqc/hisat2/featureCounts 等）。

## 功能特性

- **四引擎差异分析**：R 的 DESeq2、edgeR、limma-voom，以及纯 Python 的 PyDESeq2，结果可交叉验证
- **探索性分析**：PCA（交互图）、样本相关性热图、层次聚类
- **差异可视化**：火山图、MA 图、差异基因热图，支持自定义尺寸重绘
- **富集分析**：GO / KEGG，支持在线（Enrichr）与本地 GMT 超几何检验两种模式；气泡图 / 条形图一键切换
- **报告导出**：全部分析结果一键导出 Excel 与内嵌图片的 HTML 报告；每张图可单独导出 PNG / 矢量 PDF
- **零环境依赖分发**：提供内置 Python + R 运行时的 Windows 安装包 / 便携版，无 Python/R 环境的电脑开箱即用

## 界面预览

（运行后截图占位：五步向导 —— 导入数据 → 选择引擎 → 差异分析 → 可视化 → 富集与报告）

## 快速开始

### 方式一：直接使用打包版（推荐）

从 [Releases](../../releases) 下载：

| 文件                                  | 说明                                |
| ----------------------------------- | --------------------------------- |
| `BulkSeqStudio-Setup.exe`           | 安装版，双击安装，自动创建桌面快捷方式，支持卸载          |
| `BulkSeqStudio_vX.Y.Z_Portable.zip` | 免安装版，解压后双击 `BulkSeqStudio.exe` 即可 |

两个版本均内置 Python 3.13 与 R 4.5.2（含 DESeq2 / edgeR / limma），目标电脑**无需安装任何环境**。内置示例数据，首次打开点"载入示例"即可体验全流程。

### 方式二：从源码运行

需要 Python 3.10+；如需 R 引擎，另装 R (≥4.2) 并安装 DESeq2、edgeR、limma（不装 R 时仍可使用 PyDESeq2 引擎）。

```bash
pip install -r requirements.txt
python run.py
```

启动后自动打开浏览器（默认 <http://127.0.0.1:8600，端口被占用时自动顺延）。>

### 数据格式

- **表达矩阵**：CSV / TSV / Excel，行为基因、列为样本，第一列为基因名
- **分组信息**：包含 `sample` 与 `group` 两列，`group` 为二分组（如 untreated / treated）

## 自定义工作路径

软件默认把数据与结果存放在安装目录下的 `workspace\`（源码模式默认仓库内 `workspace\`）。如需自定义，设置环境变量：

```
BULKSEQ_HOME=D:\your\path
```

## 从源码打包 Windows 版

详见 [BUILD.md](BUILD.md)。一键构建：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_all.ps1
```

流程：PyInstaller 打包 Python 端 → 依据 `tools/r_dep_closure.R` 计算的依赖闭包裁剪出便携 R（约 145 MB）→ 组装 dist → 生成安装包与便携 zip。

## 目录结构

```
app/
  main.py               # FastAPI 路由与 API
  core/                 # 配置、数据导入、示例数据
  services/             # 差异分析引擎、绘图、富集、报告
  static/ templates/    # 前端（原生 JS + ECharts）
tools/                  # 打包与测试脚本
run.py                  # 启动入口
*.spec                  # PyInstaller 配置
```

## 技术栈

FastAPI · Uvicorn · pandas/NumPy · PyDESeq2 · gseapy · matplotlib/seaborn · ECharts · R (DESeq2/edgeR/limma) · PyInstaller

## 已知限制

- 仅支持二分组差异分析（不支持多因素设计）
- 富集分析在线模式需要联网；离线请提供 GMT 文件
- 打包版仅支持 Windows 10/11 x64

## 许可证

本项目代码基于 [MIT License](LICENSE) 发布。内置的 ECharts 遵循 Apache-2.0；DESeq2/edgeR/limma 遵循其各自的开放源码许可，随包分发的 R 运行时为 GPL-3。
