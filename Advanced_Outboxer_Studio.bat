@echo off
rem Starts Advanced Outboxer Studio with a Python that has PySide6 (there may be several Pythons on this PC).
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0advanced_outboxer_studio.py"
set "FOUND="
for /f "delims=" %%P in ('where python 2^>nul') do call :try "%%~dpP"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*" "%ProgramFiles%\Python*") do call :try "%%~fD\"
if defined FOUND (
  start "" "%FOUND%" "%SCRIPT%" %*
  exit /b 0
)
echo PySide6 was not found in any Python on this PC.
echo Install it with:   python -m pip install PySide6 Pillow
pause
exit /b 1

:try
if defined FOUND exit /b 0
if not exist "%~1python.exe" exit /b 0
if not exist "%~1pythonw.exe" exit /b 0
"%~1python.exe" -c "import PySide6" >nul 2>&1 || exit /b 0
set "FOUND=%~1pythonw.exe"
exit /b 0
