@echo off
chcp 65001 >nul
title AGGELIAFOROS - pl-predictor (kleise auto to parathyro gia stop)
cd /d "%~dp0"

set PY=
if exist "C:\Python314\python.exe" set PY=C:\Python314\python.exe
if not defined PY (
    where py >nul 2>&1 && set PY=py
)
if not defined PY (
    where python >nul 2>&1 && set PY=python
)

if not defined PY (
    echo.
    echo  DEN VRETHIKE PYTHON.
    echo  Vale ti diadromi tou python.exe stin metavliti PY parapano.
    echo.
    pause
    exit /b 1
)

"%PY%" "%~dp0runner.py"

echo.
echo  O aggeliaforos stamatise.
pause
