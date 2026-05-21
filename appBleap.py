import os
import pandas as pd
import streamlit as st
import requests
from datetime import datetime
import shared_logic as sl
import time
import json
import io
import unicodedata

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Import Bleap (appBleap)", layout="wide")

st.title("🚜 Importeur Spécialisé Bleap")

EXPORT_BASE_DIR = "sanctuarisation"

# RAW V4 Standard columns
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- Processing Engine ---
def process_bleap_csv(df):
    new_rows = []
    account = "bleap_app" # Normalized to lowercase

    # Filter out non-completed
    df = df[df["Status"] == "COMPLETED"].copy()

    progress_bar = st.progress(0)
    total_rows = len(df)

    for i, (idx, row) in enumerate(df.iterrows()):
        # Parsing date
        dt_str = str(row.get("Created At", row.get("Completed At", "")))
        try:
            dt = pd.to_datetime(dt_str, utc=True)
        except:
            dt = datetime.now()

        t_type = str(row.get("Type", ""))
        desc = str(row.get("Description", ""))
        currency = str(row.get("Currency", "")).upper().strip()
        amount = pd.to_numeric(row.get("Amount"), errors='coerce') or 0.0
        fees = pd.to_numeric(row.get("Fees"), errors='coerce') or 0.0

        is_imp = False
        cp = "system"
        val = amount # Sign handled below

        # Detection category for audit metadata
        if t_type == "Top Up":
            cp = "banq n26"
            val = amount # Entry
        elif t_type == "Off-Ramp" and "Bank Transfer (Sell)" in desc:
            cp = "banq n26"
            val = -amount # Exit
            if currency == "EURA": is_imp = True
        elif "Earn" in t_type or "Bridge" in t_type:
            val = -amount if "Deposit" in t_type else amount
            cp = "bleap_earn"
        elif "Exchange" in t_type or "Trade" in t_type:
            val = amount # The leg we see
            cp = "swap"
        elif t_type == "Deposit":
            val = amount
            cp = "external"
        elif t_type == "Withdrawal":
            val = -amount
            cp = "external"

        # Robust synthetic Hash including timestamp to avoid collisions
        ts_ms = int(dt.timestamp() * 1000)
        safe_hash = f"BLP-{ts_ms}-{idx}-{i}"

        # Create row (Way 3 - Import)
        new_rows.append({
            "Date": dt.isoformat(),
            "Chain": "Bleap",
            "Tx_Hash": safe_hash,
            "Type": "CEX_Mvt",
            "Method": t_type,
            "Account": account,
            "From": cp if val > 0 else account,
            "To": account if val > 0 else cp,
            "From_Label": "",
            "To_Label": "",
            "Counterparty": cp,
            "Asset": currency,
            "Amount": val,
            "Fee_Asset": currency if fees > 0 else "",
            "Fee_Amount": fees,
            "Source_Way": "Way_3",
            "Audit_Status": "RAW",
            "Fee_Audit_Alert": "",
            "Source_Exchange_Rate": 0.0
        })

        progress_bar.progress((i + 1) / total_rows)

    return pd.DataFrame(new_rows, columns=RAW_V4_COLUMNS)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state:
        st.session_state["_hub_target_year"] = datetime.now().year

    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, key="_hub_target_year")
    st.divider()
    show_status()
    st.divider()
    st.info("💡 Ce module applique les règles N26 et identifie automatiquement les ventes imposables d'EURA.")

uploaded_file = st.file_uploader("📂 Déposez votre export CSV Bleap", type="csv")

if uploaded_file:
    df_raw = pd_read_csv_safe(uploaded_file)
    st.subheader("👀 Aperçu du fichier source")
    st.dataframe(df_raw.head(5), width='stretch')

    if st.button("🚀 Lancer la transcription Bleap", type="primary", width='stretch'):
        with st.spinner("Analyse et recherche des prix..."):
            df_final = process_bleap_csv(df_raw)
            # Apply standard identification
            df_final = sl.standardize_df_addresses(df_final)
            st.session_state.bleap_final = df_final
            st.success(f"Transcription terminée : {len(df_final)} lignes générées.")

    if "bleap_final" in st.session_state:
        st.divider()
        st.subheader("✅ Résultat au format RAW V4 (Voie 3)")

        # Display result
        edited_df = st.data_editor(
            st.session_state.bleap_final,
            column_config={
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(format="%.8f", disabled=True),
                "Fee_Amount": st.column_config.NumberColumn(format="%.8f", disabled=True),
            },
            width='stretch',
            num_rows="fixed",
            key="bleap_editor"
        )

        st.divider()
        if st.button("💾 Sanctuariser (Enregistrer les Brutes)", width='stretch'):
            year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
            os.makedirs(year_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"raw_token_transfers_bleap_{ts}.csv"
            save_path = os.path.join(year_dir, filename)

            edited_df.to_csv(save_path, index=False, encoding="utf-8-sig")
            st.session_state.bleap_final = edited_df
            st.balloons()
            st.success(f"Fichier sanctuarisé dans : `{save_path}`")

st.sidebar.divider()
sl.show_status()
st.sidebar.divider()
st.sidebar.caption("Import Bleap v1.0 - appBleap")
