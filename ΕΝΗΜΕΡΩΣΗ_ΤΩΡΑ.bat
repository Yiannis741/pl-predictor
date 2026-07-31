@echo off
chcp 65001 >nul
title PL Predictor - Χειροκίνητη ενημέρωση
cd /d "%~dp0"

set PY=venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo.
echo === Ενημερωση αγωνων και προβλεψεων ===
echo.
"%PY%" update.py
if errorlevel 1 (
    echo.
    echo !!! Κατι πηγε στραβα, δες το μηνυμα σφαλματος παραπανω.
    pause
    exit /b 1
)

set GIT="C:\Program Files\Git\cmd\git.exe"
if exist %GIT% (
    echo.
    echo === Αποθηκευση στο GitHub ===
    %GIT% add -A
    %GIT% commit -m "Χειροκινητη ενημερωση προβλεψεων" 2>nul
    %GIT% push origin main
)

echo.
echo === Ανοιγμα αποτελεσματος ===
start "" "output\index.html"

echo.
echo Ολοκληρωθηκε.
pause
