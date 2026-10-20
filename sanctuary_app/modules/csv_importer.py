"""
Module d'importation et mapping dynamique de CSV arbitraires vers le schéma Sanctuary des 19 colonnes.
"""
import pandas as pd
from datetime import datetime
from .schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, create_empty_sanctuary_df
from .fx_collector import convert_to_eur

def _clean_numeric_value(val) -> float:
    """Nettoie et convertit une valeur en float (gère la virgule française et les espaces)."""
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0.0
    s = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def map_csv_to_sanctuary(file_obj, column_mapping: dict, default_network: str = "FIAT") -> pd.DataFrame:
    """
    Prend un fichier CSV téléchargé et un dictionnaire de correspondance de colonnes
    pour générer un DataFrame conforme au schéma des 19 colonnes.
    Gère les virgules françaises, les espaces et les encodages sous Windows.
    """
    try:
        # Toujours repositionner le pointeur de fichier au début
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

            # Mapping des colonnes
            for target_col in REQUIRED_COLUMNS:
                source_col = column_mapping.get(target_col)
                if source_col and source_col in raw_df.columns and pd.notna(row[source_col]):
                    record[target_col] = str(row[source_col]).strip()
                else:
                    record[target_col] = ""

            # Attributs par défaut
            if not record["Date de la transaction"]:
                record["Date de la transaction"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

            if not record["Type de transaction"]:
                record["Type de transaction"] = "Mouvement"

            if not record["Réseau"]:
                record["Réseau"] = default_network

            # Traitement multi-colonnes spécifique (ex: Neverless Amount sent vs Amount received / Trade / Swap)
            amt_orig = _clean_numeric_value(record["Montant d'origine"])
            curr_orig = str(record["Devise d'origine"] or "").upper().strip()

            amt_statement = _clean_numeric_value(record["Montant du relevé"])
            curr_statement = str(record["Devise du relevé"] or "").upper().strip()

            tx_type = str(record["Type de transaction"] or "").strip()

            # Pour les Dépôts / Intérêts à flux unique reçu
            if amt_orig == 0.0 and amt_statement != 0.0 and not curr_orig:
                curr_orig = curr_statement

            # Pour les Retraits à flux unique envoyé
            if amt_statement == 0.0 and amt_orig != 0.0 and not curr_statement:
                curr_statement = curr_orig

            if not curr_orig:
                curr_orig = "EUR"
            if not curr_statement:
                curr_statement = curr_orig

            record["Montant d'origine"] = amt_orig
            record["Devise d'origine"] = curr_orig
            record["Montant du relevé"] = amt_statement
            record["Devise du relevé"] = curr_statement

            rate_applied = _clean_numeric_value(record["Taux de change appliqué"])
            dt_val = record["Date de la transaction"]

            # La colonne 'Devise du relevé' du schéma Sanctuary représente TOUJOURS l'évaluation en EUR
            record["Devise du relevé"] = "EUR"

            # 1. Si la devise d'origine est EUR ou EURC (parité 1:1 EUR), le montant du relevé en EUR = amt_orig
            if curr_orig in ["EUR", "EURC"] and amt_orig != 0.0:
                val_eur = amt_orig
                rate_applied = 1.0
                record["Montant du relevé"] = round(val_eur, 2)
                record["Taux de change appliqué"] = rate_applied
                record["Paire FX"] = f"{curr_orig}/EUR"
                record["Source du taux de change"] = "Parité EUR"

            # 2. Si l'actif reçu dans le trade/swap est EUR ou EURC, le montant du relevé en EUR = amt_statement
            elif curr_statement in ["EUR", "EURC"] and amt_statement != 0.0:
                val_eur = amt_statement
                rate_applied = round(amt_statement / amt_orig, 6) if amt_orig > 0 else 1.0
                record["Montant du relevé"] = round(val_eur, 2)
                record["Taux de change appliqué"] = rate_applied
                record["Paire FX"] = f"{curr_orig}/EUR"
                record["Source du taux de change"] = "Parité EUR"

            # 3. Pour les trades crypto/crypto non-EUR (ex: EURC -> USDC ou BTC -> USDC), valoriser en EUR via convert_to_eur
            else:
                dt_obj = pd.to_datetime(dt_val, dayfirst=True, errors="coerce")
                dt_obj = dt_obj.to_pydatetime() if pd.notna(dt_obj) else datetime.now()
                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(amt_orig, curr_orig, dt_obj)

                # Si amt_orig était nul mais qu'on a un montant de relevé (ex: staking / bonus en crypto)
                if val_eur == 0.0 and amt_statement != 0.0:
                    val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(amt_statement, curr_statement, dt_obj)

                record["Montant du relevé"] = round(val_eur, 2)
                record["Taux de change appliqué"] = round(rate, 6) if rate > 0 else 1.0
                record["Date du taux de change appliqué"] = r_date
                record["Source du taux de change"] = r_src
                record["Paire FX"] = fx_pair

            mapped_records.append(record)

        df_mapped = pd.DataFrame(mapped_records)
        return enforce_sanctuary_schema(df_mapped)

    except Exception as e:
        print(f"Erreur d'importation CSV : {e}")
        return create_empty_sanctuary_df()
