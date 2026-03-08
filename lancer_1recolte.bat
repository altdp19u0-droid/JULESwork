@echo off
REM Lanceur 1Recolte V4.3 pour Windows 11
REM Force l'utilisation du bon chemin Python

set PYTHON_PATH="C:\Users\Pp\AppData\Local\Programs\Python\Python312\python.exe"

echo 🚀 Lancement de 1Recolte V4.3...
%PYTHON_PATH% -m streamlit run 1recolte.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Erreur lors du lancement. Verifiez les droits ou les alias Windows.
    pause
)
