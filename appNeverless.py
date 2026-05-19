import os
import pandas as pd
import numpy as np
import streamlit as st
import requests
from datetime import datetime
from shared_logic import get_fiat_rate, get_price_eur, show_status, load_owner_accounts, resolve_raw_addr
import time
import json
import io
import unicodedata

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Import Neverless (appNeverless)", layout="wide")
st.title("🚜 Importeur Spécialisé Neverless")

EXPORT_BASE_DIR = "sanctuarisation"

# RAW V4 Standard columns
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset",
    "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- Logic: Neverless Expansion ---
def process_neverless_csv(df):
    new_rows = []

    # Normalisation des colonnes pour gérer la casse et les espaces
    df.columns = [c.strip() for c in df.columns]
    col_map = {c.lower(): c for c in df.columns}

    def get_val(row, col_name, default=None):
        c = col_map.get(col_name.lower())
        if c: return row[c]
        return default

    owners_map = load_owner_accounts() # {addr_low: label}

    # Detect IDs that are "Auto-conversion"
    desc_col = col_map.get("description")
    id_col = col_map.get("id")

    auto_withdrawal_ids = set()
    auto_deposit_ids = set()

    if desc_col and id_col:
        auto_withdrawal_ids = set(df[df[desc_col].fillna("").str.contains("Auto-conversion when withdrawing fiat", case=False)][id_col].unique())
        auto_deposit_ids = set(df[df[desc_col].fillna("").str.contains("Auto-conversion when depositing fiat", case=False)][id_col].unique())

    progress_bar = st.progress(0)
    total_rows = len(df)

    # Use actual column name for 'imposable' if it exists in any case
    imposable_col = col_map.get("imposable")

    for i, (idx, row) in enumerate(df.iterrows()):
        dt_str = str(get_val(row, "Date", ""))
        try:
            dt = pd.to_datetime(dt_str)
        except:
            dt = datetime.now()

        tx_type = str(get_val(row, "Type", ""))
        raw_id = str(get_val(row, "ID", ""))
        tx_hash = str(get_val(row, "Blockchain transaction hash", ""))

        # Robust synthetic Hash including timestamp and unique index to avoid collisions
        ts_ms = int(dt.timestamp() * 1000)
        if tx_hash == "nan" or not tx_hash or str(tx_hash).lower() == "false":
            base_hash = f"NVL-{ts_ms}-{raw_id}-{i}"
        else:
            base_hash = tx_hash

        desc_raw = str(get_val(row, "Description", ""))
        desc = desc_raw.lower()
        account = "Neverless_App"

        # Nouvelles colonnes from/to
        f_val = str(get_val(row, "from", "")).strip()
        t_val = str(get_val(row, "to", "")).strip()

        # Calculation of Audit_Status based on imposable flag
        # We handle boolean, string 'true', etc.
        is_imp_val = False
        if imposable_col:
            val = row[imposable_col]
            if isinstance(val, (bool, np.bool_)):
                is_imp_val = bool(val)
            else:
                # String comparison - ensure it handles 'True' case-insensitively
                is_imp_val = str(val).strip().lower() in ["true", "vrai", "1", "yes", "oui"]

        # --- LOGIQUE D'OUTREPASSEMENT FISCALE ---
        # Si c'est un retrait EUR avec description 'banq', c'est imposable par défaut
        if tx_type == "Withdrawal" and str(get_val(row, "Asset sent", "")).upper() == "EUR":
            if "banq" in desc:
                is_imp_val = True

        audit_stat = "RAW_TAXABLE" if is_imp_val else "RAW"

        # --- LOGIQUE D'EXPANSION ---

        # 1. Gestion du flux "SORTANT" (SENT)
        asset_sent = get_val(row, "Asset sent")
        amt_sent = pd.to_numeric(get_val(row, "Amount sent"), errors='coerce')
        if not pd.isna(asset_sent) and amt_sent > 0:
            price_sent = pd.to_numeric(get_val(row, "USD price of asset sent"), errors='coerce') or 0.0

            # Counterparty logic using new columns
            if f_val == "neverless_app" and t_val and t_val != "nan":
                cp = t_val
            else:
                cp = "External" if tx_type == "Withdrawal" else "Swap"

            # --- SPECIAL WITHDRAWAL LOGIC ---
            bc_addr_raw = get_val(row, "Blockchain address")
            if pd.isna(bc_addr_raw) or str(bc_addr_raw).lower() == "nan":
                bc_addr_raw = ""
            else:
                bc_addr_raw = str(bc_addr_raw).strip()

            bc_addr = resolve_raw_addr(bc_addr_raw).lower() if bc_addr_raw else ""

            if tx_type == "Withdrawal":
                # A. Internal Transfer (Owner -> Owner)
                if bc_addr in owners_map:
                    cp = owners_map[bc_addr]
                # B. Bank Withdrawal (Crypto -> Fiat)
                elif not bc_addr and "banq" in desc:
                    cp = desc_raw if not t_val or t_val == "nan" else t_val

            # Specific Neverless sub-labels
            if cp in ["External", "Swap"]:
                if "strategies" in desc: cp = "Neverless Strategies"
                elif "prime" in desc: cp = "Neverless Prime"

            new_rows.append({
                "Date": dt.isoformat(),
                "Chain": "Neverless",
                "Tx_Hash": f"OUT-{base_hash}",
                "Type": "CEX_Mvt",
                "Method": tx_type,
                "Account": account,
                "From": account,
                "To": bc_addr_raw or (t_val if t_val and t_val != "nan" else "Neverless_Internal"),
                "From_Label": "",
                "To_Label": "",
                "Counterparty": cp,
                "Asset": str(asset_sent).upper(),
                "Amount": -amt_sent,
                "Valeur $": amt_sent * price_sent,
                "USD prix asset reçu": 0.0,
                "USD prix asset envoyé": price_sent,
                "USD prix de fée asset": 0.0,
                "Fee_Asset": "",
                "Fee_Amount": 0.0,
                "Source_Way": "Way_3",
                "Audit_Status": audit_stat,
                "Fee_Audit_Alert": "",
                "Source_Exchange_Rate": price_sent
            })

        # 2. Gestion du flux "ENTRANT" (RECEIVED)
        asset_rec = get_val(row, "Asset received")
        amt_rec = pd.to_numeric(get_val(row, "Amount received"), errors='coerce')
        if not pd.isna(asset_rec) and amt_rec > 0:
            price_rec = pd.to_numeric(get_val(row, "USD price of asset received"), errors='coerce') or 0.0

            # Counterparty logic using new columns
            if t_val == "neverless_app" and f_val and f_val != "nan":
                cp = f_val
            else:
                cp = "Swap" if tx_type == "Trade" else "System"

            if "interest" in desc:
                cp = "Yield"
                if "strategies" in desc: cp = "Neverless Strategies (Yield)"
                elif "prime" in desc: cp = "Neverless Prime (Yield)"
            elif "strategies" in desc:
                cp = "Neverless Strategies"
            elif "prime" in desc:
                cp = "Neverless Prime"

            new_rows.append({
                "Date": dt.isoformat(),
                "Chain": "Neverless",
                "Tx_Hash": f"IN-{base_hash}",
                "Type": "CEX_Mvt",
                "Method": tx_type,
                "Account": account,
                "From": f_val if f_val and f_val != "nan" else "Neverless_Internal",
                "To": account,
                "From_Label": "",
                "To_Label": "",
                "Counterparty": cp,
                "Asset": str(asset_rec).upper(),
                "Amount": amt_rec,
                "Valeur $": amt_rec * price_rec,
                "USD prix asset reçu": price_rec,
                "USD prix asset envoyé": 0.0,
                "USD prix de fée asset": 0.0,
                "Fee_Asset": "",
                "Fee_Amount": 0.0,
                "Source_Way": "Way_3",
                "Audit_Status": audit_stat,
                "Fee_Audit_Alert": "",
                "Source_Exchange_Rate": price_rec
            })

        # 3. Gestion des FRAIS (FEES)
        fee_amt = pd.to_numeric(get_val(row, "Fee"), errors='coerce')
        if not pd.isna(fee_amt) and fee_amt > 0:
            fee_asset = str(get_val(row, "Asset of the fee", "USDC"))
            price_fee = pd.to_numeric(get_val(row, "USD price of fee asset"), errors='coerce') or 1.0

            new_rows.append({
                "Date": dt.isoformat(),
                "Chain": "Neverless",
                "Tx_Hash": f"FEE-{base_hash}",
                "Type": "CEX_Mvt",
                "Method": "Fee",
                "Account": account,
                "From": account,
                "To": "Neverless_Fees",
                "From_Label": "",
                "To_Label": "",
                "Counterparty": "Neverless_Fees",
                "Asset": fee_asset.upper(),
                "Amount": -fee_amt,
                "Valeur $": fee_amt * price_fee,
                "USD prix asset reçu": 0.0,
                "USD prix asset envoyé": 0.0,
                "USD prix de fée asset": price_fee,
                "Fee_Asset": fee_asset.upper(),
                "Fee_Amount": fee_amt,
                "Source_Way": "Way_3",
                "Audit_Status": audit_stat,
                "Fee_Audit_Alert": "",
                "Source_Exchange_Rate": price_fee
            })

        progress_bar.progress((i + 1) / total_rows)

    return pd.DataFrame(new_rows, columns=RAW_V4_COLUMNS)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state: st.session_state["_hub_target_year"] = datetime.now().year
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=st.session_state["_hub_target_year"], key="_hub_target_year")
    st.divider()
    st.info("💡 Ce module transforme les lignes mixtes de Neverless en écritures comptables simples (In/Out/Fees) aux normes RAW V4.")

    st.divider()
    show_status()

uploaded_file = st.file_uploader("📂 Déposez votre export CSV Neverless", type="csv")

if uploaded_file:
    try:
        content = uploaded_file.read().decode("utf-8-sig")
        df_raw = pd.read_csv(io.StringIO(content))
    except:
        uploaded_file.seek(0)
        df_raw = pd.read_csv(uploaded_file, encoding="latin-1")

    st.subheader("👀 Aperçu du fichier source")
    st.dataframe(df_raw.head(5), width='stretch')

    if st.button("🚀 Lancer la transcription intelligente", type="primary", width='stretch'):
        with st.spinner("Traitement en cours..."):
            df_final = process_neverless_csv(df_raw)
            st.session_state.nvl_final = df_final
            st.success(f"Transcription réussie : {len(df_final)} lignes générées à partir de {len(df_raw)} opérations.")

    if "nvl_final" in st.session_state:
        st.divider()
        st.subheader("✅ Résultat au format Sanctuarisation (RAW V4)")

        # Affichage avec possibilité de modification
        edited_df = st.data_editor(
            st.session_state.nvl_final,
            column_config={
                "Amount": st.column_config.NumberColumn(format="%.8f", disabled=True),
                "Source_Exchange_Rate": st.column_config.NumberColumn(format="%.4f", disabled=True),
                "Date": st.column_config.DatetimeColumn(disabled=True),
            },
            width='stretch',
            num_rows="fixed",
            key="nvl_editor"
        )

        st.divider()
        if st.button("💾 Sanctuariser (Enregistrer les Brutes)", width='stretch'):
            # Chemin standard : sanctuarisation/{year}/sanctuary/
            year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year), "sanctuary")
            os.makedirs(year_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"raw_transactions_consolidated_neverless_app_{ts}.csv"
            save_path = os.path.join(year_dir, filename)

            # On enregistre la version éditée
            edited_df.to_csv(save_path, index=False, encoding="utf-8-sig")

            # Mise à jour de la session pour refléter les changements
            st.session_state.nvl_final = edited_df

            st.balloons()
            st.success(f"Fichier enregistré avec succès dans : `{save_path}`")

st.sidebar.divider()
st.sidebar.caption("Import Neverless v1.1 - appNeverless")
