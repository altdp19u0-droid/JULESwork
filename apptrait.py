"""
Point d'entrée racine : apptrait.py
Redirige vers sanctuary_app/apptrait.py pour permettre l'exécution directe depuis la racine (ex: streamlit run apptrait.py)
"""
import sys
import os
from pathlib import Path

# Désactivation des bytecodes .pyc
sys.dont_write_bytecode = True

ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "sanctuary_app"

for path_obj in [ROOT_DIR, APP_DIR]:
    p_str = str(path_obj)
    if p_str in sys.path:
        sys.path.remove(p_str)
    sys.path.insert(0, p_str)

# Exécution du script principal apptrait.py
target_apptrait = APP_DIR / "apptrait.py"
if target_apptrait.exists():
    with open(target_apptrait, "r", encoding="utf-8") as f:
        code = compile(f.read(), str(target_apptrait), "exec")
        exec(code, {"__file__": str(target_apptrait), "__name__": "__main__"})
else:
    raise FileNotFoundError("Impossible de trouver sanctuary_app/apptrait.py")
