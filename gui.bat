@echo off
chcp 65001 >nul
REM 雙擊開啟圖形介面；也可把 .xlsx 拖曳到此檔上，開啟時預先帶入該檔。
REM 以 UTF-8 儲存；行尾須為 CRLF（.gitattributes 已設定）。
setlocal
set "IN="
if not "%~1"=="" set "IN=%~f1"
cd /d "%~dp0"
REM 有 pythonw 就用它（不留黑色命令視窗）；缺套件時介面會跳出提示
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw -m miles_inquiry.gui "%IN%"
    exit /b 0
)
python -m miles_inquiry.gui "%IN%"
if errorlevel 1 pause
