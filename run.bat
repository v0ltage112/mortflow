@echo off
setlocal
REM Run from the repo root so "src.paths" imports and repo-relative defaults work.
cd /d "%~dp0"

REM Create the virtual environment on first run.
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
call ".venv\Scripts\activate.bat"

REM Install dependencies before resolving config (the resolver imports src.paths).
pip install -r requirements.txt || goto :err

REM --- Resolve data and output folders from the Phase 2 config layer ---
REM DATA_DIR / OUT_DIR honour CLI > env > paths.local.yaml > repo defaults.
for /f "delims=" %%i in ('python -c "from src.paths import resolve_data_dir; print(resolve_data_dir())"') do set "DATA_DIR=%%i"
for /f "delims=" %%i in ('python -c "from src.paths import resolve_out_dir; print(resolve_out_dir())"') do set "OUT_DIR=%%i"

REM --- Phase S0: build frozen baselines (contract + as-of) ---
python -m tools.baseline --portfolio "%DATA_DIR%\portfolio.yaml" --out "%OUT_DIR%" || goto :err

REM --- Regular portfolio run (XLSX + CSVs + summary) ---
python -m tools.portfolio --portfolio "%DATA_DIR%\portfolio.yaml" --out "%OUT_DIR%" || goto :err

echo.
echo All runs complete. See "%OUT_DIR%"
pause
exit /b 0

:err
echo.
echo *** ERROR: Run failed. See messages above. ***
pause
exit /b 1