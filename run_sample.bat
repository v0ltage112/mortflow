@echo off
setlocal
REM ---------------------------------------------------------------
REM run_sample.bat  —  Demo run using the bundled data_sample/ data.
REM Outputs go to out\ (git-ignored).
REM No local config needed — runs out-of-the-box on a fresh clone.
REM For runs on your own data, use run.bat instead.
REM ---------------------------------------------------------------
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
call ".venv\Scripts\activate.bat"

pip install -r requirements.txt || goto :err

REM --- Force the data dir to the bundled sample folder.
REM     This env var overrides paths.local.yaml so no local config is needed.
set "MORTGAGE_DATA_DIR=%~dp0data_sample"
set "MORTGAGE_OUT_DIR=%~dp0out"

for /f "delims=" %%i in ('python -c "from src.paths import resolve_data_dir; print(resolve_data_dir())"') do set "DATA_DIR=%%i"
for /f "delims=" %%i in ('python -c "from src.paths import resolve_out_dir; print(resolve_out_dir())"') do set "OUT_DIR=%%i"

python -m tools.baseline --portfolio "%DATA_DIR%\portfolio.yaml" --out "%OUT_DIR%" || goto :err
python -m tools.portfolio --portfolio "%DATA_DIR%\portfolio.yaml" --out "%OUT_DIR%" || goto :err

echo.
echo Sample run complete.  Outputs in: "%OUT_DIR%"
pause
exit /b 0

:err
echo.
echo *** ERROR: Run failed. See messages above. ***
pause
exit /b 1