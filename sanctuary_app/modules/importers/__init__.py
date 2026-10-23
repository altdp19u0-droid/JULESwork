"""
Package d'importateurs CSV dédiés par source pour Sanctuary App.
"""
import sys
from pathlib import Path

_CURRENT_DIR = Path(__file__).resolve().parent
_MOD_DIR = _CURRENT_DIR.parent
_APP_DIR = _MOD_DIR.parent
_ROOT_DIR = _APP_DIR.parent

for _p in [str(_ROOT_DIR), str(_APP_DIR), str(_MOD_DIR), str(_CURRENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .importer_bleap import import_bleap_csv
from .importer_neverless import import_neverless_csv
from .importer_8lends import import_8lends_csv
from .importer_generic import import_generic_csv

__all__ = [
    "import_bleap_csv",
    "import_neverless_csv",
    "import_8lends_csv",
    "import_generic_csv"
]
