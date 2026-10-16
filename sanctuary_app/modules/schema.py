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

    # Formattage et nettoyage des types
    res_df["Date de la transaction"] = pd.to_datetime(res_df["Date de la transaction"], errors="coerce")
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
