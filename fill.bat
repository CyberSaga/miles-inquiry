@echo off
rem Drop an .xlsx onto this file (or run: fill.bat file.xlsx [options]).
rem Output .xlsx and report .csv are written next to the input. No argument: opens the GUI.
rem Keep this file ASCII-only: cmd.exe misreads non-ASCII (UTF-8) lines in batch files.
rem Python prints Chinese messages correctly on the Windows console without chcp.
setlocal
if "%~1"=="" (
    call "%~dp0gui.bat"
    exit /b 0
)
rem Resolve the input path first (relative to the current directory), then cd to the tool
set "IN=%~f1"
cd /d "%~dp0"
python -m miles_inquiry fill "%IN%" %2 %3 %4 %5 %6 %7 %8 %9
pause
