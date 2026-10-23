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

import json
from pathlib import Path

REGISTRY_PATH = Path("sanctuary/platform_signatures.json")

KNOWN_SIGNATURES = {
    "BLEAP": [["created at", "currency", "fees"], ["created at", "amount", "currency", "status"]],
    "NEVERLESS": [["amount received", "asset received"], ["amount sent", "asset sent"], ["usd price of asset received"]],
    "8LENDS": [["8lends"], ["prêt", "emprunteur"], ["investissements 8lends"]]
}

def load_signature_registry() -> dict:
    """Charge le registre persistant des empreintes de colonnes par plateforme."""
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_custom_csv_signature(platform_name: str, csv_columns: list):
    """Enregistre l'empreinte des colonnes d'une plateforme pour la reconnaître automatiquement aux imports suivants."""
    if not platform_name or not csv_columns:
        return
    p_name = platform_name.strip().upper()
    cols_clean = sorted([str(c).strip().lower() for c in csv_columns if str(c).strip()])

    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry = load_signature_registry()

    if p_name not in registry:
        registry[p_name] = []

    if cols_clean not in registry[p_name]:
        registry[p_name].append(cols_clean)

    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

def detect_csv_source(csv_columns: list, filename: str = "") -> str:
    """
    Détecte automatiquement la plateforme d'origine (BLEAP, NEVERLESS, 8LENDS, etc.)
    en analysant les en-têtes du CSV et le registre d'apprentissage persistant.
    """
    if not csv_columns:
        return None

    cols_lower = set(str(c).strip().lower() for c in csv_columns)
    fname_lower = filename.lower() if filename else ""

    # 1. Vérification par le nom de fichier
    for p_name in ["BLEAP", "NEVERLESS", "8LENDS", "KRAKEN"]:
        if p_name.lower() in fname_lower:
            return p_name

    # 2. Vérification par le registre appris persistant
    custom_registry = load_signature_registry()
    for p_name, sig_list in custom_registry.items():
        for sig in sig_list:
            if all(s in cols_lower for s in sig):
                return p_name

    # 3. Empreintes natives intégrées
    for p_name, sig_list in KNOWN_SIGNATURES.items():
        for sig in sig_list:
            if all(s in cols_lower for s in sig):
                return p_name

    return None

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
