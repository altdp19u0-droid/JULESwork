@echo off
title AppTrait - Qualification & Legitimite
cd /d "%~dp0"

echo ============================================================
echo   Lancement de AppTrait (Qualification, Anti-Spam & Soldes)
echo ============================================================
echo.

IF NOT EXIST "venv\Scripts\activate.bat" (
    echo [ATTENTION] Environnement virtuel 'venv' introuvable dans le dossier.
    echo Tentative de lancement direct avec le Python du systeme...
    streamlit run sanctuary_app\apptrait.py
    pause
    exit
)

call venv\Scripts\activate.bat

echo Configuration des chemins PYTHONPATH...
set PYTHONPATH=%~dp0;%~dp0sanctuary_app;%PYTHONPATH%

echo Lancement de AppTrait via Streamlit...
streamlit run sanctuary_app\apptrait.py

pause
