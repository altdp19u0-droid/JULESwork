"""
Moteur d'analyse et de totalisation à DEUX NIVEAUX pour Sanctuary App.
Niveau A : Totalisation par période pour chaque compte individuel.
Niveau B : Totalisation par période sur la globalisation multi-comptes.
"""
import pandas as pd
from .schema import enforce_sanctuary_schema

def filter_by_period(df: pd.DataFrame, period_type: str, year: int = None, quarter: str = None, month: int = None, start_date = None, end_date = None) -> pd.DataFrame:
    """
    Filtre le DataFrame selon la période sélectionnée.
    Gère la comparaison uniforme entre datetimes tz-aware (ex: UTC) et tz-naive.
    """
    if df is None or df.empty:
        return enforce_sanctuary_schema(None)

    res_df = df.copy()

    # Conversion en UTC strict (utc=True) pour absorber les entrées tz-mixed et tz-naive
    dt_series = pd.to_datetime(res_df["Date de la transaction"], dayfirst=True, format="mixed", utc=True, errors="coerce")

    # Normalisation tz-naive (remotion du fuseau horaire) pour comparaison sécurisée avec start_date/end_date
    res_df["Date_DT"] = dt_series.dt.tz_localize(None)
    res_df = res_df.dropna(subset=["Date_DT"])

    if period_type == "Année" and year:
        res_df = res_df[res_df["Date_DT"].dt.year == int(year)]

    elif period_type == "Trimestre" and year and quarter:
        res_df = res_df[res_df["Date_DT"].dt.year == int(year)]
        q_map = {"Q1": [1, 2, 3], "Q2": [4, 5, 6], "Q3": [7, 8, 9], "Q4": [10, 11, 12]}
        months = q_map.get(quarter, [])
        res_df = res_df[res_df["Date_DT"].dt.month.isin(months)]

    elif period_type == "Mois" and year and month:
        res_df = res_df[(res_df["Date_DT"].dt.year == int(year)) & (res_df["Date_DT"].dt.month == int(month))]

    elif period_type == "Personnalisée" and start_date and end_date:
        st_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

        if hasattr(st_dt, "tzinfo") and st_dt.tzinfo is not None:
            st_dt = st_dt.tz_localize(None)
        if hasattr(end_dt, "tzinfo") and end_dt.tzinfo is not None:
            end_dt = end_dt.tz_localize(None)

        res_df = res_df[(res_df["Date_DT"] >= st_dt) & (res_df["Date_DT"] <= end_dt)]

    return res_df.drop(columns=["Date_DT"])

def totalize_level_a(account_df: pd.DataFrame) -> dict:
    """
    Niveau A : Totalisation par période choisie pour un compte individuel.
    """
    if account_df is None or account_df.empty:
        return {
            "total_count": 0,
            "total_eur": 0.0,
            "by_currency": pd.DataFrame(),
            "by_type": pd.DataFrame()
        }

    df = account_df.copy()
    df["Devise d'origine"] = df["Devise d'origine"].fillna("Inconnue")
    df["Type de transaction"] = df["Type de transaction"].fillna("Autre")

    total_count = len(df)
    total_eur = float(df["Montant du relevé"].sum())

    by_currency = df.groupby("Devise d'origine").agg(
        Total_Brut=("Montant d'origine", "sum"),
        Total_EUR=("Montant du relevé", "sum"),
        Nombre_TX=("Date de la transaction", "count")
    ).reset_index()

    by_type = df.groupby("Type de transaction").agg(
        Total_EUR=("Montant du relevé", "sum"),
        Nombre_TX=("Date de la transaction", "count")
    ).reset_index()

    return {
        "total_count": total_count,
        "total_eur": total_eur,
        "by_currency": by_currency,
        "by_type": by_type
    }

def totalize_level_b(all_accounts_df: pd.DataFrame) -> dict:
    """
    Niveau B : Totalisation par période choisie sur la globalisation de l'ensemble des comptes.
    """
    if all_accounts_df is None or all_accounts_df.empty:
        return {
            "total_count": 0,
            "total_eur": 0.0,
            "by_account": pd.DataFrame(),
            "by_network": pd.DataFrame(),
            "by_project": pd.DataFrame(),
            "by_type": pd.DataFrame()
        }

    df = all_accounts_df.copy()

    # Résolution prioritaire du nom du compte pour la répartition par compte
    if "Compte_Sanctuaire" not in df.columns or df["Compte_Sanctuaire"].dropna().empty:
        df["Compte_Sanctuaire"] = df["Nom du projet"].fillna(df["ID du projet"]).fillna(df["Réseau"]).fillna("Compte_Inconnu")
    else:
        df["Compte_Sanctuaire"] = df["Compte_Sanctuaire"].fillna(df["Nom du projet"]).fillna(df["Réseau"]).fillna("Compte_Inconnu")

    total_count = len(df)
    total_eur = float(df["Montant du relevé"].sum())

    df["Réseau"] = df["Réseau"].fillna("Inconnu")
    df["Nom du projet"] = df["Nom du projet"].fillna("Non spécifié")
    df["Type de transaction"] = df["Type de transaction"].fillna("Autre")

    by_account = df.groupby("Compte_Sanctuaire").agg(
        Total_EUR=("Montant du relevé", "sum"),
        Nombre_TX=("Date de la transaction", "count")
    ).reset_index().sort_values("Total_EUR", ascending=False)

    by_network = df.groupby("Réseau").agg(
        Total_EUR=("Montant du relevé", "sum"),
        Nombre_TX=("Date de la transaction", "count")
    ).reset_index().sort_values("Total_EUR", ascending=False)

    by_project = df.groupby("Nom du projet").agg(
        Total_EUR=("Montant du relevé", "sum"),
        Nombre_TX=("Date de la transaction", "count")
    ).reset_index().sort_values("Total_EUR", ascending=False)

    by_type = df.groupby("Type de transaction").agg(
        Total_EUR=("Montant du relevé", "sum"),
        Nombre_TX=("Date de la transaction", "count")
    ).reset_index().sort_values("Total_EUR", ascending=False)

    return {
        "total_count": total_count,
        "total_eur": total_eur,
        "by_account": by_account,
        "by_network": by_network,
        "by_project": by_project,
        "by_type": by_type
    }
