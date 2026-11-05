@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Tekken5_SkinStudio ^
  --icon assets\t5skin.ico --version-file assets\version_info.txt ^
  --add-data "tools\skins_t5\lang;tools\skins_t5\lang" ^
  --add-data "tools\skins_t5\blender279_edit.py;tools\skins_t5" ^
  --hidden-import PyQt5._QOpenGLFunctions_2_1 --exclude-module tkinter skin_studio.py
if errorlevel 1 pause
