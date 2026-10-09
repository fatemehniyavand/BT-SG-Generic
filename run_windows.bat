@echo off
cd /d %~dp0
where swipl >nul 2>nul
if errorlevel 1 (
  echo SWI-Prolog is required and swipl.exe must be on PATH.
  exit /b 2
)
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
python verify_setup.py
python run_experiment.py --runs 1000 --seed 42 --output outputs\n1000_seed42
