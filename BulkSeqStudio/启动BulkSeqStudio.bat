@echo off
REM BulkSeq Studio 启动脚本（双击运行）
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
REM 用户指定的工作路径（数据、临时文件都存这里）
set "BULKSEQ_HOME=D:\Program Files\testfield\Claw"
title BulkSeq Studio
cd /d "%~dp0"
"D:\Users\Heisar\miniconda3\envs\bulkseq\Scripts\python.exe" "%~dp0run.py"
if errorlevel 1 (
  echo.
  echo [启动失败] 请把上面的错误信息反馈给开发者。
  pause
)
