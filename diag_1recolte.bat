@echo off
echo --- DIAGNOSTIC 1RECOLTE ---
set PY_LOCAL="C:\Users\Pp\AppData\Local\Programs\Python\Python312\python.exe"

echo 1. Recherche du Python actif (PATH)...
where python
py -0

echo.
echo 2. Test presence Python Local (Vrai)...
if exist %PY_LOCAL% (
    echo OK: Python 3.12 local trouve.
    %PY_LOCAL% --version
) else (
    echo ERREUR: Python 3.12 introuvable a l'adresse specifiee.
)

echo.
echo 3. Test module Streamlit via Local...
%PY_LOCAL% -m streamlit --version
if %ERRORLEVEL% NEQ 0 (
    echo ERREUR: Streamlit ne repond pas via le Python local.
) else (
    echo OK: Streamlit est operationnel sur le Python local.
)

echo.
echo 3b. Test Pip via Local...
%PY_LOCAL% -m pip --version
if %ERRORLEVEL% NEQ 0 (
    echo ERREUR: Pip est inaccessible.
) else (
    echo OK: Pip est operationnel.
)

echo.
echo 4. Analyse du probleme...
echo Si 'where python' affiche System32 et que vous avez un Acces Refuse,
echo c'est que Windows Alias (Store) bloque l'appel.
echo SOLUTION: Utilisez lancer_1recolte.bat qui utilise le chemin Vrai (Etape 2).

echo ---------------------------
pause
