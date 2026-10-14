"""
Module de gestion du stockage local Windows CSV (sanctuary/{YEAR}/{compte}.csv).
"""
import os
from pathlib import Path
import pandas as pd
from .schema import enforce_sanctuary_schema, REQUIRED_COLUMNS

SANCTUARY_ROOT = Path("sanctuary")

def sanitize_filename(filename: str) -> str:
    """Nettoie un nom de fichier pour éviter les caractères invalides sous Windows."""
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()

def get_sanctuary_path(year: int, account_label: str) -> Path:
    """Retourne le chemin d'accès au fichier CSV du compte pour l'année donnée."""
    clean_label = sanitize_filename(account_label)
    folder = SANCTUARY_ROOT / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{clean_label}.csv"

def save_to_sanctuary(df: pd.DataFrame, year: int, account_label: str) -> Path:
    """
    Sauvegarde et dédoublonne les transactions dans le fichier CSV du compte.
    Format d'écriture : Windows CSV UTF-8-SIG.
    """
    path = get_sanctuary_path(year, account_label)
    df_clean = enforce_sanctuary_schema(df)

    if path.exists():
        try:
            existing_df = pd.read_csv(path, encoding="utf-8-sig")
            existing_df = enforce_sanctuary_schema(existing_df)
            combined = pd.concat([existing_df, df_clean], ignore_index=True)
        except Exception:
            combined = df_clean
    else:
        combined = df_clean

    # Dédoublonnage sur le trio (Hash, Devise d'origine, Date)
    combined["Statut de la transaction"] = "Sanctuarisé"

    # Remplacement des valeurs vides par chaîne vide pour dédoublonner proprement
    combined["Hash_Key"] = combined["Hash de la transaction blockchain"].fillna("")
    combined["Dev_Key"] = combined["Devise d'origine"].fillna("")
    combined["Date_Key"] = pd.to_datetime(combined["Date de la transaction"]).dt.strftime('%Y-%m-%d %H:%M:%S')

    deduped = combined.drop_duplicates(subset=["Hash_Key", "Dev_Key", "Date_Key"], keep="last")
    deduped = deduped.drop(columns=["Hash_Key", "Dev_Key", "Date_Key"])

    # Tri chronologique
    deduped = deduped.sort_values("Date de la transaction", ascending=False)

    # Sauvegarde au format Windows UTF-8-SIG
    deduped.to_csv(path, index=False, encoding="utf-8-sig")
    return path

def load_sanctuary_account(year: int, account_label: str) -> pd.DataFrame:
    """Charge le fichier CSV sanctuarisé d'un compte pour une année donnée."""
    path = get_sanctuary_path(year, account_label)
    if not path.exists():
        return enforce_sanctuary_schema(None)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        return enforce_sanctuary_schema(df)
    except Exception:
        return enforce_sanctuary_schema(None)

def list_sanctuary_years() -> list:
    """Liste les années disponibles dans le répertoire sanctuary."""
    if not SANCTUARY_ROOT.exists():
        return []
    years = [int(p.name) for p in SANCTUARY_ROOT.iterdir() if p.is_dir() and p.name.isdigit()]
    return sorted(years, reverse=True)

def list_accounts_for_year(year: int) -> list:
    """Liste les comptes ayant un fichier CSV pour l'année donnée."""
    folder = SANCTUARY_ROOT / str(year)
    if not folder.exists():
        return []
    accounts = [p.stem for p in folder.glob("*.csv")]
    return sorted(accounts)

def load_all_sanctuary_for_year(year: int) -> pd.DataFrame:
    """Charge et consolide l'ensemble des fichiers comptes pour une année donnée."""
    accounts = list_accounts_for_year(year)
    if not accounts:
        return enforce_sanctuary_schema(None)

    dfs = []
    for acc in accounts:
        df_acc = load_sanctuary_account(year, acc)
        df_acc["Compte_Sanctuaire"] = acc
        dfs.append(df_acc)

    combined = pd.concat(dfs, ignore_index=True)
    return combined
