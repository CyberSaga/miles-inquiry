@echo off
chcp 65001 >nul
REM 將 xlsx 拖曳到此檔上即可：輸出為 <檔名>_距離.xlsx 與 <檔名>_距離_report.csv（放在輸入檔旁）
REM 以 UTF-8 儲存（上方 chcp 65001 讓中文正常顯示）；行尾須為 CRLF（.gitattributes 已設定）。
setlocal
if "%~1"=="" (
    echo 用法：將 .xlsx 檔拖曳到 fill.bat 上，或 fill.bat 檔案.xlsx
    pause
    exit /b 1
)
REM 先取得輸入檔的完整路徑（相對路徑以目前目錄為準），再切換到工具目錄
set "IN=%~f1"
cd /d "%~dp0"
python -m miles_inquiry fill "%IN%" %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 (
    echo.
    echo 執行失敗，請檢查上方錯誤訊息。
)
pause
