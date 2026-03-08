@echo off
REM Lanceur 1Recolte V4.3 - Windows 11 Compatibility Version
REM Bypassing System32 decoy and handling corrupted aliases

REM Chemins standard apres installation "All Users"
set PY_EXE="C:\Program Files\Python312\python.exe"
set PY_LAUNCHER="py"

echo --- Lancement de 1Recolte V4.3 ---

echo Tentative 1: via le Python Launcher
%PY_LAUNCHER% -3.12 -m streamlit run 1recolte.py

if %ERRORLEVEL% NEQ 0 (
    echo Tentative 2: via le chemin standard Program Files
    %PY_EXE% -m streamlit run 1recolte.py
)

if %ERRORLEVEL% NEQ 0 (
    echo Tentative 3: via la commande directe
    python -m streamlit run 1recolte.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo --- DIAGNOSTIC CRITIQUE ---
    echo Si vous voyez 'Acces refuse' ou '%1 n'est pas valide', l'installation est CORROMPUE.
    echo 1. Allez dans Parametres Windows > Alias d'execution.
    echo 2. DESACTIVEZ TOUT ce qui concerne Python et Streamlit.
    echo 3. REDEMARREZ VOTRE ORDINATEUR.
    echo 4. Si rien ne change, REINSTALLEZ Python 3.12.
    echo ---------------------------
    pause
)
