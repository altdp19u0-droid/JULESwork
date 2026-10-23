"""
Module d'importation et mapping dynamique de CSV arbitraires vers le schéma Sanctuary des 19 colonnes.
"""
import pandas as pd
from datetime import datetime
from .schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, create_empty_sanctuary_df
from .fx_collector import convert_to_eur

def _clean_numeric_value(val) -> float:
    """Nettoie et convertit une valeur en float (gère la virgule française et les espaces)."""
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0.0
    s = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

try:
    from .importers import (
        import_bleap_csv,
        import_neverless_csv,
        import_8lends_csv,
        import_generic_csv
    )
except ImportError:
    from modules.importers import (
        import_bleap_csv,
        import_neverless_csv,
        import_8lends_csv,
        import_generic_csv
    )

def map_csv_to_sanctuary(file_obj, column_mapping: dict = None, default_network: str = "FIAT") -> pd.DataFrame:
    """
    Routeur central d'importation CSV.
    Achemine la requête vers l'importateur dédié spécialisé (BLEAP, NEVERLESS, 8LENDS, GENERIC)
    selon la source / réseau spécifié.
    """
    net_upper = str(default_network).strip().upper()

    if "BLEAP" in net_upper:
        return import_bleap_csv(file_obj, column_mapping)
    elif "NEVERLESS" in net_upper:
        return import_neverless_csv(file_obj, column_mapping)
    elif "8LENDS" in net_upper or "8LEND" in net_upper:
        return import_8lends_csv(file_obj, column_mapping)
    else:
        return import_generic_csv(file_obj, column_mapping, default_network=default_network)
