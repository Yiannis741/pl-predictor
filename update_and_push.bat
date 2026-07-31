@echo off
chcp 65001 >nul
setlocal
cd /d "C:\pl-predictor"
if not exist logs mkdir logs

set PY=
if exist "C:\pl-predictor\venv\Scripts\python.exe" set PY=C:\pl-predictor\venv\Scripts\python.exe
if not defined PY (where py >nul 2>&1 && set PY=py)
if not defined PY (where python >nul 2>&1 && set PY=python)

echo ============================== >> logs\update.log
echo %date% %time% >> logs\update.log
"%PY%" update.py >> logs\update.log 2>&1

set GIT="C:\Program Files\Git\cmd\git.exe"
if exist %GIT% (
    %GIT% add -A >> logs\update.log 2>&1
    %GIT% commit -m "Auto update: predictions %date% %time%" >> logs\update.log 2>&1
    %GIT% push origin main >> logs\update.log 2>&1
)

endlocal
