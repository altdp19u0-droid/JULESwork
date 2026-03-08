@echo off
REM Lanceur 1Recolte V4.3 - Bypassing Windows System32 Alias
REM Version Robuste pour Windows 11

set PY_PATH="C:\Users\Pp\AppData\Local\Programs\Python\Python312\python.exe"

echo --- Lancement de 1Recolte V4.3 ---

echo Tentative 1: via le Python Launcher (py -3.12)
py -3.12 -m streamlit run 1recolte.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Tentative 2: via le chemin absolu Python 3.12
    %PY_PATH% -m streamlit run 1recolte.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Tentative 3: via streamlit.exe direct
    "C:\Users\Pp\AppData\Local\Programs\Python\Python312\Scripts\streamlit.exe" run 1recolte.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERREUR CRITIQUE: Acces toujours refuse.
    echo 1. Desactivez les 'Alias d'execution' dans les parametres Windows.
    echo 2. Verifiez que l'Antivirus ne bloque pas python.exe dans AppData.
    pause
)
