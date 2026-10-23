@echo off
title Sanctuary App - Execution USB Portable
cd /d "%~dp0"

echo ============================================================
echo   Lancement de Sanctuary App en Mode Portable (Cle USB)
echo ============================================================
echo.

IF NOT EXIST "venv\Scripts\activate.bat" (
    echo [CRITIQUE] Environnement virtuel 'venv' introuvable dans la cle USB.
    echo Veuillez executer l'installation initiale une premiere fois.
    pause
    exit
)

call venv\Scripts\activate.bat

echo Configuration des chemins PYTHONPATH...
set PYTHONPATH=%~dp0;%~dp0sanctuary_app;%PYTHONPATH%

echo Lancement du serveur Streamlit local...
streamlit run sanctuary_app\app.py

pause
