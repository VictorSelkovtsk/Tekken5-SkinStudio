@echo off
cd /d "%~dp0"
start "" "%~dp0runtime\python\pythonw.exe" "%~dp0tools\skins_t5\launch.py" --home "%~dp0."
