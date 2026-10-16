@echo off
rem Double-click to open the GUI, or drop an .xlsx onto this file to preselect it.
rem Keep this file ASCII-only: cmd.exe misreads non-ASCII (UTF-8) lines in batch files.
setlocal
set "IN="
if not "%~1"=="" set "IN=%~f1"
cd /d "%~dp0"
rem Prefer pythonw (no console window); the GUI shows its own error dialogs.
where pythonw >nul 2>&1
if errorlevel 1 goto console
start "" pythonw -m miles_inquiry.gui "%IN%"
exit /b 0
:console
python -m miles_inquiry.gui "%IN%"
if errorlevel 1 pause
