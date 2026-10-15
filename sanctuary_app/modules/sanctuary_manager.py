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

def save_to_sanctuary(df: pd.DataFrame, year: int, account_label: str, auto_dispatch_year: bool = True) -> list:
    """
    Sauvegarde et dédoublonne les transactions dans le(s) fichier(s) CSV du compte.
    Si auto_dispatch_year=True, ventile automatiquement chaque transaction selon l'année réelle de sa date.
    Sinon, force la sauvegarde dans l'année spécifiée en paramètre `year`.
    Format d'écriture : Windows CSV UTF-8-SIG.
    """
    df_clean = enforce_sanctuary_schema(df)
    if df_clean.empty:
        return []

    saved_paths = []

    if auto_dispatch_year:
        # Ventilation dynamique selon l'année réelle de chaque transaction
        df_clean["Year_Group"] = pd.to_datetime(df_clean["Date de la transaction"], errors="coerce").dt.year
        # Les dates non valides retombent sur l'année spécifiée
        df_clean["Year_Group"] = df_clean["Year_Group"].fillna(year).astype(int)

        for actual_year, group_df in df_clean.groupby("Year_Group"):
            group_clean = group_df.drop(columns=["Year_Group"])
            path = _save_single_year(group_clean, actual_year, account_label)
            saved_paths.append(path)
    else:
        path = _save_single_year(df_clean, year, account_label)
        saved_paths.append(path)

    return saved_paths

def _save_single_year(df_clean: pd.DataFrame, year: int, account_label: str) -> Path:
    """Sauvegarde un sous-ensemble de transactions dans une année spécifique."""
    path = get_sanctuary_path(year, account_label)

    if path.exists():
        try:
            existing_df = pd.read_csv(path, encoding="utf-8-sig")
            existing_df = enforce_sanctuary_schema(existing_df)
            combined = pd.concat([existing_df, df_clean], ignore_index=True)
        except Exception:
            combined = df_clean
    else:
        combined = df_clean

    combined["Statut de la transaction"] = "Sanctuarisé"

    combined["Hash_Key"] = combined["Hash de la transaction blockchain"].fillna("")
    combined["Dev_Key"] = combined["Devise d'origine"].fillna("")
    combined["Date_Key"] = pd.to_datetime(combined["Date de la transaction"]).dt.strftime('%Y-%m-%d %H:%M:%S')

    deduped = combined.drop_duplicates(subset=["Hash_Key", "Dev_Key", "Date_Key"], keep="last")
    deduped = deduped.drop(columns=["Hash_Key", "Dev_Key", "Date_Key"])

    # Tri chronologique décroissant
    deduped = deduped.sort_values("Date de la transaction", ascending=False)

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
