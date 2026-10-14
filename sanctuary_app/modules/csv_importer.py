"""
Module d'importation et mapping dynamique de CSV arbitraires vers le schéma Sanctuary des 17 colonnes.
"""
import pandas as pd
from datetime import datetime
from .schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, create_empty_sanctuary_df
from .fx_collector import convert_to_eur

def map_csv_to_sanctuary(file_obj, column_mapping: dict, default_network: str = "FIAT") -> pd.DataFrame:
    """
    Prend un fichier CSV téléchargé et un dictionnaire de correspondance de colonnes
    pour générer un DataFrame conforme au schéma des 17 colonnes.
    """
    try:
        # Essai de lecture avec séparateurs courants et encodages
        try:
            raw_df = pd.read_csv(file_obj, encoding="utf-8-sig", sep=None, engine="python")
        except Exception:
            file_obj.seek(0)
            raw_df = pd.read_csv(file_obj, encoding="latin1", sep=";")

        if raw_df.empty:
            return create_empty_sanctuary_df()

        mapped_records = []

        for _, row in raw_df.iterrows():
            record = {}

            # Map standard columns
            for target_col in REQUIRED_COLUMNS:
                source_col = column_mapping.get(target_col)
                if source_col and source_col in raw_df.columns and pd.notna(row[source_col]):
                    record[target_col] = row[source_col]
                else:
                    record[target_col] = None

            # Attributs par défaut
            if not record["Date de la transaction"]:
                record["Date de la transaction"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if not record["Type de transaction"]:
                record["Type de transaction"] = "Mouvement"

            if not record["Réseau"]:
                record["Réseau"] = default_network

            amt_orig = float(pd.to_numeric(record["Montant d'origine"], errors="coerce") or 0.0)
            record["Montant d'origine"] = amt_orig

            curr_orig = str(record["Devise d'origine"] or "EUR").upper().strip()
            record["Devise d'origine"] = curr_orig

            # Calcul automatique des taux FX si non fournis dans le CSV
            if not record["Montant du relevé"] or float(record["Montant du relevé"] or 0) == 0:
                dt_val = record["Date de la transaction"]
                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(amt_orig, curr_orig, dt_val)
                record["Montant du relevé"] = val_eur
                record["Taux de change appliqué"] = rate
                record["Date du taux de change appliqué"] = r_date
                record["Source du taux de change"] = r_src
                record["Paire FX"] = fx_pair

            mapped_records.append(record)

        df_mapped = pd.DataFrame(mapped_records)
        return enforce_sanctuary_schema(df_mapped)

    except Exception:
        return create_empty_sanctuary_df()
