"""
Importateur CSV générique / multi-sources.
Traite arbitrairement tout fichier CSV (Kraken, Banque, Exchange, Wallet) en utilisant l'assistant de mapping.
"""
import re
import pandas as pd
from datetime import datetime

try:
    from ..schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, create_empty_sanctuary_df
    from ..fx_collector import convert_to_eur
except (ImportError, ValueError):
    try:
        from sanctuary_app.modules.schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, create_empty_sanctuary_df
        from sanctuary_app.modules.fx_collector import convert_to_eur
    except (ImportError, ValueError):
        from modules.schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, create_empty_sanctuary_df
        from modules.fx_collector import convert_to_eur

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

def import_generic_csv(file_obj, column_mapping: dict, default_network: str = "FIAT") -> pd.DataFrame:
    """
    Importateur générique utilisant le dictionnaire de mapping fourni.
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

        mapped_records = []

        for _, row in raw_df.iterrows():
            record = {}
            for target_col in REQUIRED_COLUMNS:
                source_col = column_mapping.get(target_col)
                if source_col and source_col in raw_df.columns and pd.notna(row[source_col]):
                    record[target_col] = str(row[source_col]).strip()
                else:
                    record[target_col] = ""

            if not record["Date de la transaction"]:
                record["Date de la transaction"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

            if not record["Type de transaction"]:
                record["Type de transaction"] = "Mouvement"

            if not record["Réseau"]:
                record["Réseau"] = default_network

            amt_orig = _clean_numeric(record["Montant d'origine"])
            curr_orig = str(record["Devise d'origine"] or "").upper().strip()

            amt_statement = _clean_numeric(record["Montant du relevé"])
            curr_statement = str(record["Devise du relevé"] or "").upper().strip()

            if amt_orig == 0.0 and amt_statement != 0.0:
                amt_orig = amt_statement
                if not curr_orig:
                    curr_orig = curr_statement

            if amt_statement == 0.0 and amt_orig != 0.0:
                amt_statement = amt_orig
                if not curr_statement:
                    curr_statement = curr_orig

            if not curr_orig:
                curr_orig = "EUR"
            if not curr_statement:
                curr_statement = "EUR"

            record["Montant d'origine"] = amt_orig
            record["Devise d'origine"] = curr_orig
            record["Devise du relevé"] = "EUR"

            dt_val = record["Date de la transaction"]
            eur_pegged = ["EUR", "EURC", "EURA", "EURE"]

            if curr_orig in eur_pegged and amt_orig != 0.0:
                val_eur = abs(amt_orig)
                rate_applied = 1.0
                src_rate = "Parité EUR 1:1"
                fx_pair = f"{curr_orig}/EUR"
            elif curr_statement in eur_pegged and amt_statement != 0.0:
                val_eur = abs(amt_statement)
                rate_applied = round(abs(amt_statement / amt_orig), 6) if amt_orig > 0 else 1.0
                src_rate = "Parité EUR 1:1"
                fx_pair = f"{curr_orig}/EUR"
            else:
                dt_obj = pd.to_datetime(dt_val, errors="coerce")
                dt_obj = dt_obj.to_pydatetime() if pd.notna(dt_obj) else datetime.now()
                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(abs(amt_orig), curr_orig, dt_obj)
                rate_applied = round(rate, 6)
                src_rate = r_src

            record["Montant du relevé"] = round(val_eur, 2) if amt_orig >= 0 else -round(val_eur, 2)
            record["Taux de change appliqué"] = rate_applied
            record["Date du taux de change appliqué"] = str(dt_val)[:10]
            record["Source du taux de change"] = src_rate
            record["Paire FX"] = fx_pair

            mapped_records.append(record)

        df_mapped = pd.DataFrame(mapped_records)
        return enforce_sanctuary_schema(df_mapped)

    except Exception as e:
        print(f"Erreur d'importation générique : {e}")
        return create_empty_sanctuary_df()
