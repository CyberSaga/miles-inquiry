@echo off
REM 將 xlsx 拖曳到此檔上即可：輸出為 <檔名>_距離.xlsx 與 <檔名>_距離_report.csv（放在輸入檔旁）
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    echo 用法：將 .xlsx 檔拖曳到 fill.bat 上，或 fill.bat 檔案.xlsx
    pause
    exit /b 1
)
python -m miles_inquiry fill "%~1" %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 (
    echo.
    echo 執行失敗，請檢查上方錯誤訊息。
)
pause
