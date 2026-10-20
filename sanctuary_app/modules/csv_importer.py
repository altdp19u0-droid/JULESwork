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

            # Saisie de secours intelligente pour les CSV multi-colonnes (ex: Neverless Amount sent / Amount received)
            amt_orig = _clean_numeric_value(record["Montant d'origine"])
            curr_orig = str(record["Devise d'origine"] or "").upper().strip()

            amt_statement = _clean_numeric_value(record["Montant du relevé"])
            curr_statement = str(record["Devise du relevé"] or "").upper().strip()

            # Si Montant d'origine est nul (ex: Dépôt/Intérêts), vérifier si Montant du relevé est renseigné
            if amt_orig == 0.0 and amt_statement != 0.0:
                amt_orig = amt_statement
                if not curr_orig and curr_statement:
                    curr_orig = curr_statement

            # Inversement, si Montant du relevé est nul (ex: Retrait), utiliser Montant d'origine
            if amt_statement == 0.0 and amt_orig != 0.0:
                amt_statement = amt_orig
                if not curr_statement and curr_orig:
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

            # 1. Si le taux de change n'est pas fourni, le déduire du rapport relevé / origine si disponible
            if rate_applied == 0.0 and amt_statement != 0.0 and amt_orig != 0.0:
                rate_applied = abs(amt_statement / amt_orig)
                record["Taux de change appliqué"] = round(rate_applied, 6)
                if not record["Source du taux de change"]:
                    record["Source du taux de change"] = "Calculé (Relevé/Origine)"
                if not record["Paire FX"]:
                    record["Paire FX"] = f"{curr_orig}/EUR"
                if not record["Date du taux de change appliqué"]:
                    record["Date du taux de change appliqué"] = str(dt_val)[:10]

            # 2. Si le montant du relevé ET le taux ne sont pas fournis, interroger l'API FX historique
            elif (amt_statement == 0.0 or rate_applied == 0.0) and amt_orig != 0.0:
                dt_obj = pd.to_datetime(dt_val, dayfirst=True, errors="coerce")
                dt_obj = dt_obj.to_pydatetime() if pd.notna(dt_obj) else datetime.now()
                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(amt_orig, curr_orig, dt_obj)
                if amt_statement == 0.0:
                    amt_statement = val_eur
                if rate_applied == 0.0:
                    rate_applied = rate
                record["Montant du relevé"] = amt_statement
                record["Taux de change appliqué"] = round(rate_applied, 6)
                record["Date du taux de change appliqué"] = r_date
                record["Source du taux de change"] = r_src
                record["Paire FX"] = fx_pair
            else:
                record["Montant du relevé"] = amt_statement
                record["Taux de change appliqué"] = round(rate_applied, 6) if rate_applied > 0 else 1.0

            mapped_records.append(record)

        df_mapped = pd.DataFrame(mapped_records)
        return enforce_sanctuary_schema(df_mapped)

    except Exception as e:
        print(f"Erreur d'importation CSV : {e}")
        return create_empty_sanctuary_df()
