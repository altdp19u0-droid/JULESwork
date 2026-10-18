"""
Module de gestion du schéma strict des 19 colonnes pour Sanctuary App.
"""
import pandas as pd

REQUIRED_COLUMNS = [
    "Date de la transaction",
    "Type de transaction",
    "ID du projet",
    "Nom du projet",
    "APR %",
    "Montant d'origine",
    "Devise d'origine",
    "Montant du relevé",
    "Devise du relevé",
    "Paire FX",
    "Taux de change appliqué",
    "Date du taux de change appliqué",
    "Source du taux de change",
    "Statut de la transaction",
    "Réseau",
    "Hash de la transaction blockchain",
    "Notes",
    "Nom et numéro [Banque fiat ou compte] d'origine",
    "Nom et numéro [Banque fiat ou compte] de destination"
]

def create_empty_sanctuary_df() -> pd.DataFrame:
    """Crée un DataFrame vide respectant la structure exacte des 19 colonnes."""
    return pd.DataFrame(columns=REQUIRED_COLUMNS)

def smart_parse_dates(series: pd.Series) -> pd.Series:
    """
    Parse intelligemment une série de dates sans inverser mois et jour.
    - Dates ISO (ex: YYYY-MM-DD / 2026-07-12) : Parsées en YYYY-MM-DD (12 Juillet) sans dayfirst.
    - Dates Françaises (ex: DD/MM/YYYY / 12/07/2026) : Parsées avec dayfirst=True (12 Juillet).
    """
    if series is None or series.empty:
        return pd.Series(dtype="datetime64[ns]")

    def parse_val(val):
        if pd.isna(val) or not str(val).strip():
            return pd.NaT
        v = str(val).strip()
        # ISO Format YYYY-MM-DD...
        if v.startswith(("20", "19")) and len(v) >= 10 and (v[4] in ["-", "/"]):
            return pd.to_datetime(v, utc=True, errors="coerce")
        else:
            return pd.to_datetime(v, dayfirst=True, utc=True, errors="coerce")

    parsed_res = series.apply(parse_val)
    return pd.to_datetime(parsed_res, utc=True, errors="coerce").dt.tz_localize(None)

def enforce_sanctuary_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    S'assure que le DataFrame contient exactement les 19 colonnes requises dans l'ordre,
    gère les valeurs manquantes et formate les types sans tronquer les numéros/adresses de compte.
    """
    if df is None or df.empty:
        return create_empty_sanctuary_df()

    res_df = df.copy()

    # Migration de rétrocompatibilité si l'ancienne colonne unique existe
    old_col = "Notes banque fiat d'origine ou de destination"
    if old_col in res_df.columns:
        if "Notes" not in res_df.columns or res_df["Notes"].dropna().empty:
            res_df["Notes"] = res_df[old_col]
        res_df = res_df.drop(columns=[old_col])

    # Ajout des colonnes manquantes si besoin
    for col in REQUIRED_COLUMNS:
        if col not in res_df.columns:
            res_df[col] = None

    # Conservation exacte des 19 colonnes dans l'ordre
    res_df = res_df[REQUIRED_COLUMNS]

    # Parsing intelligent des dates pour éviter l'inversion ISO YYYY-MM-DD en YYYY-DD-MM
    res_df["Date de la transaction"] = smart_parse_dates(res_df["Date de la transaction"])
    res_df["Montant d'origine"] = pd.to_numeric(res_df["Montant d'origine"], errors="coerce").fillna(0.0)
    res_df["Montant du relevé"] = pd.to_numeric(res_df["Montant du relevé"], errors="coerce").fillna(0.0)
    res_df["Taux de change appliqué"] = pd.to_numeric(res_df["Taux de change appliqué"], errors="coerce").fillna(1.0)
    res_df["APR %"] = pd.to_numeric(res_df["APR %"], errors="coerce").fillna(0.0)

    # Valeurs par défaut texte (sans aucune tronquature)
    res_df["Devise du relevé"] = res_df["Devise du relevé"].fillna("EUR")
    res_df["Statut de la transaction"] = res_df["Statut de la transaction"].fillna("Validé")
    res_df["Hash de la transaction blockchain"] = res_df["Hash de la transaction blockchain"].fillna("").astype(str)
    res_df["Notes"] = res_df["Notes"].fillna("").astype(str)
    res_df["Nom et numéro [Banque fiat ou compte] d'origine"] = res_df["Nom et numéro [Banque fiat ou compte] d'origine"].fillna("").astype(str)
    res_df["Nom et numéro [Banque fiat ou compte] de destination"] = res_df["Nom et numéro [Banque fiat ou compte] de destination"].fillna("").astype(str)

    return res_df
