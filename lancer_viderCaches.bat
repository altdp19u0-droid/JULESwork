@echo off
title Sanctuary App - Nettoyage des Caches
cd /d "%~dp0"

echo ============================================================
echo   Nettoyage des Caches Python & Streamlit (Sanctuary App)
echo ============================================================
echo.

echo [1/3] Suppression des fichiers bytecode Python (.pyc, .pyo)...
del /s /q *.pyc *.pyo 2>nul

echo [2/3] Suppression des dossiers de cache Python (__pycache__)...
for /d /r %%i in (__pycache__) do (
    if exist "%%i" rmdir /s /q "%%i" 2>nul
)

echo [3/3] Invalidation du cache local Streamlit...
if exist "%USERPROFILE%\.streamlit\cache" (
    rmdir /s /q "%USERPROFILE%\.streamlit\cache" 2>nul
)

echo.
echo ============================================================
echo   ✅ Nettoyage des caches termine avec succes !
echo ============================================================
echo.
pause
