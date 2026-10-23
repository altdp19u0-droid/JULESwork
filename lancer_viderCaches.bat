@echo off
title Vider les Caches Python (SanctuaryApp)
cd /d "%~dp0"

echo ============================================================
echo   Suppression de TOUS les dossiers de cache __pycache__
echo ============================================================
echo.

for /d /r . %%d in (__pycache__) do (
    if exist "%%d" (
        echo Suppression de : %%d
        rd /s /q "%%d"
    )
)

del /s /q *.pyc >nul 2>&1

echo.
echo ============================================================
echo   [OK] Tous les caches Python ont ete supprimes.
echo ============================================================
pause
