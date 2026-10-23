"""
Module de gestion du stockage local Windows CSV (sanctuary/{YEAR}/{compte}.csv).
"""
import os
from pathlib import Path
import pandas as pd
from .schema import enforce_sanctuary_schema, smart_parse_dates, REQUIRED_COLUMNS

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
    Format d'écriture : Windows CSV UTF-8-SIG (Migre automatiquement les anciens CSV vers 19 colonnes).
    """
    df_clean = enforce_sanctuary_schema(df)
    if df_clean.empty:
        return []

    saved_paths = []

    if auto_dispatch_year:
        # Ventilation dynamique selon l'année réelle de chaque transaction
        df_clean["Year_Group"] = smart_parse_dates(df_clean["Date de la transaction"]).dt.year
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
    """Sauvegarde un sous-ensemble de transactions dans une année spécifique avec migration de schéma automatique et nettoyage strict des années."""
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

    # Nettoyage strict : ne conserver dans sanctuary/{year}/ QUE les transactions de cette année spécifique
    combined["_year_val"] = smart_parse_dates(combined["Date de la transaction"]).dt.year
    combined = combined[combined["_year_val"] == int(year)].drop(columns=["_year_val"])

    import re
    def _clean_str_amt(v):
        if pd.isna(v) or v is None:
            return 0.0
        s = re.sub(r"[\s\xa0\u202f\u200b\'\"]+", "", str(v)).replace(",", ".")
        if s.startswith("+"):
            s = s[1:]
        try:
            return float(s)
        except Exception:
            return 0.0

    # Remplacement des anciennes lignes à zéro par la nouvelle version renseignée si même (Date, Type, Devise, Notes)
    combined["_dt_parsed"] = smart_parse_dates(combined["Date de la transaction"])
    combined["_amt_orig_clean"] = combined["Montant d'origine"].apply(_clean_str_amt)
    combined["Montant d'origine"] = combined["_amt_orig_clean"]

    # Si présence de lignes identiques avec montant=0 et montant!=0, conserver en priorité la ligne avec montant!=0
    combined["_has_nonzero"] = combined.groupby(["_dt_parsed", "Type de transaction", "Devise d'origine", "Notes"])["_amt_orig_clean"].transform(lambda x: (x.abs() > 0).any())
    mask_to_drop = combined["_has_nonzero"] & (combined["_amt_orig_clean"].abs() == 0.0)
    combined = combined[~mask_to_drop].drop(columns=["_amt_orig_clean", "_has_nonzero"])

    # Clefs de dédoublonnage robustes incluant l'ensemble des 19 colonnes de données métier
    dedup_cols = [c for c in REQUIRED_COLUMNS if c not in ["Statut de la transaction"]]
    deduped = combined.drop_duplicates(subset=dedup_cols, keep="last")

    # Tri chronologique décroissant sécurisé sur type datetime
    deduped = deduped.sort_values("_dt_parsed", ascending=False).drop(columns=["_dt_parsed"])

    # Ré-application stricte du schéma des 19 colonnes
    deduped = enforce_sanctuary_schema(deduped)

    # Sauvegarde au format Windows UTF-8-SIG
    deduped.to_csv(path, index=False, encoding="utf-8-sig")
    return path

def load_sanctuary_account(year: int, account_label: str) -> pd.DataFrame:
    """Charge le fichier CSV sanctuarisé d'un compte pour une année donnée et migre vers 19 colonnes."""
    path = get_sanctuary_path(year, account_label)
    if not path.exists():
        return enforce_sanctuary_schema(None)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        df_clean = enforce_sanctuary_schema(df)
        df_clean["Compte_Sanctuaire"] = account_label
        return df_clean
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

def list_all_accounts_all_years() -> list:
    """Liste l'ensemble des nom de comptes uniques disponibles dans toutes les années."""
    years = list_sanctuary_years()
    accounts = set()
    for y in years:
        accounts.update(list_accounts_for_year(y))
    return sorted(list(accounts))

def load_all_sanctuary_for_year(year: int) -> pd.DataFrame:
    """Charge et consolide l'ensemble des fichiers comptes pour une année donnée en préservant le nom du compte."""
    accounts = list_accounts_for_year(year)
    if not accounts:
        return enforce_sanctuary_schema(None)

    dfs = []
    for acc in accounts:
        df_acc = load_sanctuary_account(year, acc)
        if not df_acc.empty:
            df_acc["Compte_Sanctuaire"] = acc
            dfs.append(df_acc)

    if not dfs:
        return enforce_sanctuary_schema(None)

    combined = pd.concat(dfs, ignore_index=True)
    return combined

def load_all_sanctuary_all_years() -> pd.DataFrame:
    """Charge et consolide l'ensemble des fichiers sanctuarisés de toutes les années."""
    years = list_sanctuary_years()
    if not years:
        return enforce_sanctuary_schema(None)

    dfs = []
    for y in years:
        df_y = load_all_sanctuary_for_year(y)
        if not df_y.empty:
            dfs.append(df_y)

    if not dfs:
        return enforce_sanctuary_schema(None)

    return pd.concat(dfs, ignore_index=True)

def load_account_all_years(account_label: str) -> pd.DataFrame:
    """Charge l'historique complet d'un compte à travers toutes les années."""
    years = list_sanctuary_years()
    if not years:
        return enforce_sanctuary_schema(None)

    dfs = []
    for y in years:
        df_acc = load_sanctuary_account(y, account_label)
        if not df_acc.empty:
            df_acc["Compte_Sanctuaire"] = account_label
            dfs.append(df_acc)

    if not dfs:
        return enforce_sanctuary_schema(None)

    return pd.concat(dfs, ignore_index=True)
