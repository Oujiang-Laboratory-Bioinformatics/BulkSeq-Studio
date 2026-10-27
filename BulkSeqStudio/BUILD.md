# BulkSeq Studio 打包说明（开发者）

把本应用分发成"任何 Windows 电脑双击即用"的独立软件。产物：

| 文件 | 说明 | 体积 |
|---|---|---|
| `release/BulkSeqStudio-Setup.exe` | 安装版（内嵌全部运行时，含卸载器） | ~210 MB |
| `release/BulkSeqStudio_v1.1.0_Portable.zip` | 免安装版，解压即用 | ~187 MB |
| `dist/BulkSeqStudio/` | 可运行目录（zip 与安装包的源） | ~370 MB |

安装 / 未安装都不需要目标机器上有 Python 或 R。

---

## 1. 组成

```
dist/BulkSeqStudio/
├─ BulkSeqStudio.exe        入口（PyInstaller onedir 引导程序）
├─ _internal/               Python 3.13 运行时 + 全部 pip 依赖 + app 代码/模板/静态资源
├─ R/                       便携 R 4.5.2（仅保留 DESeq2/edgeR/limma 依赖闭包）
├─ VCRUNTIME140*.dll        给 R 包的 DLL 兜底（目标机没装 VC++ 运行库时用）
└─ 使用说明.txt
```

首次运行会在 exe 同级创建 `workspace/{data,tmp}`；若目录不可写（如装在
`C:\Program Files`），自动回退到 `%LOCALAPPDATA%\BulkSeqStudio`。

## 2. 重新打包

前置：`D:\Users\Heisar\miniconda3\envs\bulkseq`（已含 pydeseq2 / PyInstaller）、
`D:\Program_Files\R\R-4.5.2`（已装 DESeq2/edgeR/limma）。

```powershell
# ① 便携 R（只需在 R 包有变动时重做，约 12 分钟）
powershell -File .tools\build_r.ps1

# ② 应用本体 + 组装（约 2 分钟）
powershell -File .tools\build_all.ps1

# ③ 安装包与便携包（约 7 分钟）
python .tools\make_zip.py payload
python -m PyInstaller installer.spec --noconfirm --distpath release
python .tools\make_zip.py portable
```

图标：`.tools/make_icon.py` 生成 `build/app.ico`。

## 3. 关键决策与坑

**R 运行时必须裁剪**　原始 R 安装 5.4 GB（含 BSgenome、TxDb 等单细胞/基因组包），
`tools::package_dependencies()` 求出 DESeq2/edgeR/limma 的递归依赖闭包后只保留 75 个包，
连同 base R 共 145 MB。包内 `help/`、`html/`、`doc/`、`src/` 一并删除。

**R 从包内定位自己的家**　`Rscript.exe` 按自身路径推导 `R_HOME`，不需要注册表，
所以整个 `R/` 目录可以被复制到任意位置。config 里的 `find_rscript()` 优先用
`<exe>/R`，其后才是环境变量和系统安装的 R。

**中文路径**（两级防御）
1. 传给 R 的所有文件路径走 `R_WORK_DIR`（纯 ASCII，默认就是 `tmp`；一旦 `tmp` 含
   非 ASCII 字符就切到 `%PUBLIC%\BulkSeqStudio\rwork`）。
2. 调用 Rscript 时从环境里剔除 `LANG/LC_*`：从 Git Bash 等环境继承的
   `LANG=*.UTF-8` 会让 Windows 版 R 的 locale 初始化失败，并把中文路径二次编码成
   乱码，表现为 `library(DESeq2): no library trees found`。同时用 8.3 短路径设置
   `R_HOME` 作为兜底。

**pydeseq2 不能走 joblib 多进程**　冻结后的 exe 被 joblib/loky 当解释器拉起时，
子进程会重新执行入口程序（表现为端口冲突、疯狂弹浏览器）。解决：打包环境
（`FROZEN`）下用 `_threaded_inference()` 把 pydeseq2 的 backend 换成 threading
（并剥掉它不接受的 `inner_max_num_threads`），`n_cpus=1`。

**matplotlib 后端要显式声明**　`backend_pdf` 是运行时动态导入的，
必须在 spec 的 `hiddenimports` 里列出，否则"导出 PDF"报 `No module named`。

**conda 的 DLL 与 Tk**　conda 把 OpenSSL/ffi/liblzma 放在 `Library\bin`，
Tcl/Tk 也在 `Library\{bin,lib}`；spec 里已手工收集（`libcrypto-3-x64.dll`、
`libssl-3-x64.dll`、`tcl86t.dll`、`tk86t.dll`、`tcl8.6/`、`tk8.6/`，并设置
`TCL_LIBRARY`/`TK_LIBRARY`），否则 HTTPS 请求、zlib、安装器界面都会挂。

**安装器不复制自身 200 MB**　`installer.spec` 内嵌 `payload.zip`（186 MB）；
卸载器是单独的 13 MB `Uninstall.exe`，由 `uninstall.spec` 构建后放进 payload 同级，
安装时被复制到安装目录。卸载时先把运行中的卸载器复制到 `%TEMP%` 再执行，否则
Windows 不允许删除正在运行的 exe。

## 4. 升级版本

1. 改 `app/core/config.py` 的 `APP_VERSION`；
2. 同步 `build/version_info.txt`、`installer.py` 的 `APP_VERSION`、`.tools/make_zip.py` 的 `VERSION`；
3. 重新执行第 2 节 ②③。

## 5. 已验证

- 干净 PATH（仅 `C:\Windows\system32`）下启动，四引擎/六图/富集/报告全通；
- 安装到含中文与空格的路径（`...\BulkSeq 测试\BulkSeqStudio`）后全流程通过；
- 静默安装 12 秒、卸载 4 秒，卸载后快捷方式清除、`workspace` 迁移到
  `我的文档\BulkSeqStudio_results`；
- 安装版启动后 `/api/info` 报告的 `rscript_path` 指向包内 `R\bin\Rscript.exe`。
