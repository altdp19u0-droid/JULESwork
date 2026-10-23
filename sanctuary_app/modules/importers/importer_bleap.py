"""
Importateur CSV dédié à la plateforme BLEAP.
Traite nativement les exports BLEAP (Type, Created At, Amount, Currency, Description, Status)
et produit un DataFrame conforme au schéma des 19 colonnes Sanctuary.
"""
import pandas as pd
from datetime import datetime

try:
    from ..schema import enforce_sanctuary_schema, create_empty_sanctuary_df
    from ..fx_collector import convert_to_eur
except ImportError:
    try:
        from sanctuary_app.modules.schema import enforce_sanctuary_schema, create_empty_sanctuary_df
        from sanctuary_app.modules.fx_collector import convert_to_eur
    except ImportError:
        from modules.schema import enforce_sanctuary_schema, create_empty_sanctuary_df
        from modules.fx_collector import convert_to_eur

import re

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

def import_bleap_csv(file_obj, column_mapping: dict = None) -> pd.DataFrame:
    """
    Importateur spécialisé pour Bleap.
    Normalise les dépôts/retraits, les parités EURA/EURE/EUR 1:1, les coffres Earn, et les conversions en EUR.
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

        for idx_line, row in raw_df.iterrows():
            # Utilisation du mapping fourni ou détection directe des colonnes BLEAP natives
            date_col = column_mapping.get("Date de la transaction", "Created At") if column_mapping else "Created At"
            type_col = column_mapping.get("Type de transaction", "Type") if column_mapping else "Type"
            amt_col = column_mapping.get("Montant d'origine", "Amount") if column_mapping else "Amount"
            curr_col = column_mapping.get("Devise d'origine", "Currency") if column_mapping else "Currency"
            notes_col = column_mapping.get("Notes", "Description") if column_mapping else "Description"
            status_col = column_mapping.get("Statut de la transaction", "Status") if column_mapping else "Status"

            dt_val = str(row.get(date_col, "")).strip() if date_col in raw_df.columns and pd.notna(row.get(date_col)) else datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            tx_type = str(row.get(type_col, "Mouvement")).strip() if type_col in raw_df.columns and pd.notna(row.get(type_col)) else "Mouvement"
            raw_amt_val = row.get(amt_col, 0.0) if amt_col in raw_df.columns else 0.0
            raw_amt = _clean_numeric(raw_amt_val)
            curr_raw = str(row.get(curr_col, "EUR")).strip().upper() if curr_col in raw_df.columns and pd.notna(row.get(curr_col)) else "EUR"
            notes_val = str(row.get(notes_col, "")).strip() if notes_col in raw_df.columns and pd.notna(row.get(notes_col)) else ""
            status_val = str(row.get(status_col, "COMPLETED")).strip() if status_col in raw_df.columns and pd.notna(row.get(status_col)) else "COMPLETED"

            if not curr_raw:
                curr_raw = "EUR"

            amt_orig = abs(raw_amt)
            eur_pegged = ["EUR", "EURC", "EURA", "EURE"]

            if curr_raw in eur_pegged:
                amt_statement = amt_orig
                rate_applied = 1.0
                src_rate = "Parité EUR 1:1"
                fx_pair = f"{curr_raw}/EUR"
            else:
                dt_obj = pd.to_datetime(dt_val, errors="coerce")
                dt_obj = dt_obj.to_pydatetime() if pd.notna(dt_obj) else datetime.now()
                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(amt_orig, curr_raw, dt_obj)
                amt_statement = round(val_eur, 2)
                rate_applied = round(rate, 6)
                src_rate = r_src

            tx_type_lower = tx_type.lower()
            notes_lower = notes_val.lower()

            is_earn = "earn" in tx_type_lower or "earn" in notes_lower

            if is_earn:
                proj_id = "BLEAP_EARN"
                proj_name = "Bleap Earn Vault"
                if "deposit" in tx_type_lower or raw_amt < 0:
                    src_acc = "Bleap Wallet"
                    dst_acc = "Bleap Earn Vault"
                else:
                    src_acc = "Bleap Earn Vault"
                    dst_acc = "Bleap Wallet"
            else:
                proj_id = "BLEAP_WALLET"
                proj_name = "Bleap Wallet"
                if "top up" in tx_type_lower or "topup" in tx_type_lower:
                    src_acc = "Banque Fiat (Top Up)"
                    dst_acc = "Bleap Wallet"
                elif "off-ramp" in tx_type_lower or "offramp" in tx_type_lower:
                    src_acc = "Bleap Wallet"
                    dst_acc = "Banque Fiat (Off-Ramp)"
                elif "deposit" in tx_type_lower or "in" in tx_type_lower:
                    src_acc = "Compte Externe"
                    dst_acc = "Bleap Wallet"
                elif "withdrawal" in tx_type_lower or "out" in tx_type_lower:
                    src_acc = "Bleap Wallet"
                    dst_acc = "Compte Externe"
                else:
                    src_acc = "Bleap Wallet"
                    dst_acc = "Bleap Wallet"

            record = {
                "Date de la transaction": dt_val,
                "Type de transaction": tx_type,
                "ID du projet": proj_id,
                "Nom du projet": proj_name,
                "APR %": 0.0,
                "Montant d'origine": raw_amt, # Conservation du signe original pour la traçabilité
                "Devise d'origine": curr_raw,
                "Montant du relevé": amt_statement,
                "Devise du relevé": "EUR",
                "Paire FX": fx_pair,
                "Taux de change appliqué": rate_applied,
                "Date du taux de change appliqué": str(dt_val)[:10],
                "Source du taux de change": src_rate,
                "Statut de la transaction": status_val,
                "Réseau": "BLEAP",
                "Hash de la transaction blockchain": "",
                "Notes": notes_val,
                "Nom et numéro [Banque fiat ou compte] d'origine": src_acc,
                "Nom et numéro [Banque fiat ou compte] de destination": dst_acc
            }
            records.append(record)

        df_out = pd.DataFrame(records)
        return enforce_sanctuary_schema(df_out)

    except Exception as e:
        print(f"Erreur d'importation BLEAP : {e}")
        return create_empty_sanctuary_df()
