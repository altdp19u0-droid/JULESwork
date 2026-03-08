@echo off
REM Lanceur 1Recolte V4.3 - Windows 11 Compatibility Version
REM Bypassing System32 decoy and handling corrupted aliases

set PY_EXE="C:\Users\Pp\AppData\Local\Programs\Python\Python312\python.exe"
set ST_EXE="C:\Users\Pp\AppData\Local\Programs\Python\Python312\Scripts\streamlit.exe"

echo --- Lancement de 1Recolte V4.3 ---

echo Tentative 1: via le Python Launcher (py -3.12)
py -3.12 -m streamlit run 1recolte.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Tentative 2: via le chemin absolu Python 3.12
    if exist %PY_EXE% (
        %PY_EXE% -m streamlit run 1recolte.py
    ) else (
        echo ERREUR: Le fichier %PY_EXE% est introuvable.
    )
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Tentative 3: via streamlit.exe direct
    if exist %ST_EXE% (
        %ST_EXE% run 1recolte.py
    ) else (
        echo ERREUR: Le fichier %ST_EXE% est introuvable.
    )
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
