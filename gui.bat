@echo off
rem Double-click to open the GUI, or drop one or more .xlsx files onto this file to preselect them.
rem Keep this file ASCII-only: cmd.exe misreads non-ASCII (UTF-8) lines in batch files.
setlocal
rem Do not cd: relative paths in %* stay valid; PYTHONPATH lets -m find the package.
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
rem Prefer pythonw (no console window); the GUI shows its own error dialogs.
where pythonw >nul 2>&1
if errorlevel 1 goto console
start "" pythonw -m miles_inquiry.gui %*
exit /b 0
:console
python -m miles_inquiry.gui %*
if errorlevel 1 pause
