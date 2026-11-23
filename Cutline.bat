@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m clipper.launch
