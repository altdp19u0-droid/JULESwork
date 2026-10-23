"""
Importateur CSV dédié à la plateforme NEVERLESS.
Traite nativement les exports multi-colonnes NEVERLESS (Amount sent, Asset sent, Amount received, Asset received, Description, USD prices)
et produit un DataFrame conforme au schéma des 19 colonnes Sanctuary.
"""
import pandas as pd
from datetime import datetime
from ..schema import enforce_sanctuary_schema, create_empty_sanctuary_df
from ..fx_collector import convert_to_eur

def _clean_numeric(val) -> float:
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0.0
    s = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def import_neverless_csv(file_obj, column_mapping: dict = None) -> pd.DataFrame:
    """
    Importateur spécialisé pour Neverless.
    Gère les paires d'échange sent/received, l'auto-conversion fiat (EUR -> EURC),
    les crédits d'intérêts quotidiens (Prime interest, Strategies interest), et la traçabilité blockchain.
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
            amt_orig_col = column_mapping.get("Montant d'origine", "Amount sent") if column_mapping else "Amount sent"
            curr_orig_col = column_mapping.get("Devise d'origine", "Asset sent") if column_mapping else "Asset sent"
            amt_stmt_col = column_mapping.get("Montant du relevé", "Amount received") if column_mapping else "Amount received"
            curr_stmt_col = column_mapping.get("Devise du relevé", "Asset received") if column_mapping else "Asset received"
            notes_col = column_mapping.get("Notes", "Description") if column_mapping else "Description"
            hash_col = column_mapping.get("Hash de la transaction blockchain", "Blockchain transaction hash") if column_mapping else "Blockchain transaction hash"
            address_col = column_mapping.get("Nom et numéro [Banque fiat ou compte] d'origine", "Blockchain address") if column_mapping else "Blockchain address"

            dt_val = str(row.get(date_col, "")).strip() if date_col in raw_df.columns and pd.notna(row.get(date_col)) else datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            tx_type = str(row.get(type_col, "Mouvement")).strip() if type_col in raw_df.columns and pd.notna(row.get(type_col)) else "Mouvement"

            amt_sent = _clean_numeric(row.get(amt_orig_col, 0.0)) if amt_orig_col in raw_df.columns else 0.0
            asset_sent = str(row.get(curr_orig_col, "")).strip().upper() if curr_orig_col in raw_df.columns and pd.notna(row.get(curr_orig_col)) else ""

            amt_received = _clean_numeric(row.get(amt_stmt_col, 0.0)) if amt_stmt_col in raw_df.columns else 0.0
            asset_received = str(row.get(curr_stmt_col, "")).strip().upper() if curr_stmt_col in raw_df.columns and pd.notna(row.get(curr_stmt_col)) else ""

            notes_val = str(row.get(notes_col, "")).strip() if notes_col in raw_df.columns and pd.notna(row.get(notes_col)) else ""
            hash_val = str(row.get(hash_col, "")).strip() if hash_col in raw_df.columns and pd.notna(row.get(hash_col)) else ""
            address_val = str(row.get(address_col, "")).strip() if address_col in raw_df.columns and pd.notna(row.get(address_col)) else ""

            # Saisie de secours intelligente pour Neverless :
            # 1. Dépôt / Intérêts : Amount sent est vide, utiliser Amount received
            if amt_sent == 0.0 and amt_received != 0.0:
                amt_sent = amt_received
                if not asset_sent:
                    asset_sent = asset_received

            # 2. Retrait : Amount received est vide, utiliser Amount sent
            if amt_received == 0.0 and amt_sent != 0.0:
                amt_received = amt_sent
                if not asset_received:
                    asset_received = asset_sent

            if not asset_sent:
                asset_sent = "EUR"
            if not asset_received:
                asset_received = asset_sent

            eur_pegged = ["EUR", "EURC", "EURA", "EURE"]

            # Valorisation exacte du Relevé EUR
            if asset_sent in eur_pegged and amt_sent != 0.0:
                val_eur = abs(amt_sent)
                rate_applied = 1.0
                src_rate = "Parité EUR 1:1"
                fx_pair = f"{asset_sent}/EUR"
            elif asset_received in eur_pegged and amt_received != 0.0:
                val_eur = abs(amt_received)
                rate_applied = round(abs(amt_received / amt_sent), 6) if amt_sent > 0 else 1.0
                src_rate = "Parité EUR 1:1"
                fx_pair = f"{asset_sent}/EUR"
            else:
                dt_obj = pd.to_datetime(dt_val, errors="coerce")
                dt_obj = dt_obj.to_pydatetime() if pd.notna(dt_obj) else datetime.now()
                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(amt_sent, asset_sent, dt_obj)
                rate_applied = round(rate, 6)
                src_rate = r_src

            record = {
                "Date de la transaction": dt_val,
                "Type de transaction": tx_type,
                "ID du projet": "NEVERLESS_PLATFORM",
                "Nom du projet": "Neverless App",
                "APR %": 0.0,
                "Montant d'origine": abs(amt_sent),
                "Devise d'origine": asset_sent,
                "Montant du relevé": round(val_eur, 2),
                "Devise du relevé": "EUR",
                "Paire FX": fx_pair,
                "Taux de change appliqué": rate_applied,
                "Date du taux de change appliqué": str(dt_val)[:10],
                "Source du taux de change": src_rate,
                "Statut de la transaction": "COMPLETED",
                "Réseau": "NEVERLESS",
                "Hash de la transaction blockchain": hash_val,
                "Notes": notes_val,
                "Nom et numéro [Banque fiat ou compte] d'origine": address_val or "Neverless Prime / Wallet",
                "Nom et numéro [Banque fiat ou compte] de destination": f"Neverless Strategies / {asset_received}" if asset_received != asset_sent else "Neverless Wallet"
            }
            records.append(record)

        df_out = pd.DataFrame(records)
        return enforce_sanctuary_schema(df_out)

    except Exception as e:
        print(f"Erreur d'importation NEVERLESS : {e}")
        return create_empty_sanctuary_df()
