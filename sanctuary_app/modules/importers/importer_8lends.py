"""
Importateur CSV dédié aux rapports de prêt / Yield 8LENDS.
Traite nativement les journaux d'investissements, dépôts, remboursements et retraits 8LENDS.
"""
import re
import pandas as pd
from datetime import datetime

from ..schema import enforce_sanctuary_schema, create_empty_sanctuary_df

def _clean_numeric(val) -> float:
    if pd.isna(val) or val is None:
        return 0.0
    s = str(val).strip()
    s = re.sub(r"[\s\xa0\u202f\u200b\'\"]+", "", s).replace(",", ".")
    if s.startswith("+"):
        s = s[1:]
    if not s or s == "-":
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def import_8lends_csv(file_obj, column_mapping: dict = None) -> pd.DataFrame:
    """
    Importateur spécialisé pour 8Lends.
    Prend en compte les opérations en EUR/USDC et applique le schéma des 19 colonnes.
    """
    try:
        file_obj.seek(0)
        try:
            raw_df = pd.read_csv(file_obj, encoding="utf-8-sig", sep=None, engine="python")
        except Exception:
            file_obj.seek(0)
            try:
                raw_df = pd.read_csv(file_obj, encoding="latin1", sep=";")
            except Exception:
                file_obj.seek(0)
                raw_df = pd.read_csv(file_obj, encoding="utf-8", sep=",")

        if raw_df.empty:
            return create_empty_sanctuary_df()

        records = []

        for _, row in raw_df.iterrows():
            date_col = column_mapping.get("Date de la transaction", "Date") if column_mapping else "Date"
            type_col = column_mapping.get("Type de transaction", "Type") if column_mapping else "Type"
            amt_col = column_mapping.get("Montant d'origine", "Montant") if column_mapping else "Montant"
            curr_col = column_mapping.get("Devise d'origine", "Devise") if column_mapping else "Devise"
            notes_col = column_mapping.get("Notes", "Description") if column_mapping else "Description"

            dt_val = str(row.get(date_col, "")).strip() if date_col in raw_df.columns and pd.notna(row.get(date_col)) else datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            tx_type = str(row.get(type_col, "Mouvement")).strip() if type_col in raw_df.columns and pd.notna(row.get(type_col)) else "Mouvement"
            amt_val = _clean_numeric(row.get(amt_col, 0.0)) if amt_col in raw_df.columns else 0.0
            curr_val = str(row.get(curr_col, "EUR")).strip().upper() if curr_col in raw_df.columns and pd.notna(row.get(curr_col)) else "EUR"
            notes_val = str(row.get(notes_col, "")).strip() if notes_col in raw_df.columns and pd.notna(row.get(notes_col)) else ""

            if not curr_val:
                curr_val = "EUR"

            record = {
                "Date de la transaction": dt_val,
                "Type de transaction": tx_type,
                "ID du projet": "8LENDS_LENDING",
                "Nom du projet": "8Lends Platform",
                "APR %": 0.0,
                "Montant d'origine": abs(amt_val),
                "Devise d'origine": curr_val,
                "Montant du relevé": abs(amt_val), # Prêts en EUR/Stablecoin 1:1
                "Devise du relevé": "EUR",
                "Paire FX": f"{curr_val}/EUR",
                "Taux de change appliqué": 1.0,
                "Date du taux de change appliqué": str(dt_val)[:10],
                "Source du taux de change": "Parité EUR 1:1",
                "Statut de la transaction": "COMPLETED",
                "Réseau": "8LENDS",
                "Hash de la transaction blockchain": "",
                "Notes": notes_val,
                "Nom et numéro [Banque fiat ou compte] d'origine": "8Lends Account",
                "Nom et numéro [Banque fiat ou compte] de destination": "8Lends Lending Pool"
            }
            records.append(record)

        df_out = pd.DataFrame(records)
        return enforce_sanctuary_schema(df_out)

    except Exception as e:
        print(f"Erreur d'importation 8LENDS : {e}")
        return create_empty_sanctuary_df()
