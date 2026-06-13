@echo off
REM start-all.bat - bat ca server agent + UI roi mo trinh duyet.
REM Double-click la xong. Tham so tuy chon: start-all.bat [APIPORT] [UIPORT]
setlocal

set APIPORT=%1
if "%APIPORT%"=="" set APIPORT=8080
set UIPORT=%2
if "%UIPORT%"=="" set UIPORT=5500

cd /d "%~dp0"

echo === Business Knowledge Agent - start all ===
echo API : http://127.0.0.1:%APIPORT%/invocations
echo UI  : http://127.0.0.1:%UIPORT%/index.html
echo.

REM --- 1) Dung process cu dang chiem 2 port ---
echo [1/4] Don port cu...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%APIPORT%" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%UIPORT%" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

REM --- 2) Mo cua so chay SERVER agent ---
echo [2/4] Khoi dong server agent...
if exist "venv\Scripts\activate.bat" (
    start "Agent Server" cmd /k "cd /d "%~dp0" ^&^& call venv\Scripts\activate.bat ^&^& set PYTHONUTF8=1 ^&^& set PYTHONIOENCODING=utf-8 ^&^& set PORT=%APIPORT% ^&^& python main.py"
) else (
    start "Agent Server" cmd /k "cd /d "%~dp0" ^&^& set PYTHONUTF8=1 ^&^& set PYTHONIOENCODING=utf-8 ^&^& set PORT=%APIPORT% ^&^& python main.py"
)

REM --- 3) Mo cua so chay UI server ---
echo [3/4] Khoi dong UI server...
start "UI Server" cmd /k "cd /d "%~dp0ui" ^&^& python -m http.server %UIPORT%"

REM --- 4) Cho server san sang roi mo trinh duyet ---
echo [4/4] Cho server san sang (agent boot co the mat 10-20s)...
timeout /t 10 /nobreak >nul
start "" "http://127.0.0.1:%UIPORT%/index.html"

echo.
echo Da bat xong. Hai cua so cmd dang chay server va UI.
echo Dong 2 cua so do (hoac Ctrl+C) de tat.
echo Trong UI, Base URL de la: http://127.0.0.1:%APIPORT%
echo.
timeout /t 3 /nobreak >nul
endlocal
