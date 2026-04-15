import os
import pandas as pd
import streamlit as st
import requests
from datetime import datetime
import time
import json
import io
import unicodedata

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Import Neverless (appNeverless)", layout="wide")
st.title("🚜 Importeur Spécialisé Neverless")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Cache & APIs ---
@st.cache_data(ttl=86400)
def get_eur_usd_rate(date_obj):
    """Récupère le taux EUR/USD pour une date donnée via Frankfurter API."""
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
        res = requests.get(url, timeout=5).json()
        return res["rates"]["EUR"]
    except:
        return 0.92

# --- Logic: Neverless Expansion ---
def process_neverless_csv(df):
    new_rows = []
    progress_bar = st.progress(0)
    total_rows = len(df)

    for idx, row in df.iterrows():
        dt_str = str(row.get("Date", ""))
        try:
            dt = pd.to_datetime(dt_str)
        except:
            dt = datetime.now()

        tx_type = str(row.get("Type", ""))
        raw_id = str(row.get("ID", ""))
        tx_hash = str(row.get("Blockchain transaction hash", ""))
        if tx_hash == "nan" or not tx_hash:
            tx_hash = f"NVL-{raw_id}"

        desc = str(row.get("Description", "")).lower()
        account = "Neverless_App"

        # --- LOGIQUE D'EXPANSION ---

        # 1. Gestion du flux "SORTANT" (SENT)
        asset_sent = row.get("Asset sent")
        amt_sent = pd.to_numeric(row.get("Amount sent"), errors='coerce')
        if not pd.isna(asset_sent) and amt_sent > 0:
            price_sent = pd.to_numeric(row.get("USD price of asset sent"), errors='coerce') or 0.0
            val_usd = amt_sent * price_sent

            new_rows.append({
                "Date": dt,
                "Chain": "Neverless",
                "Token": str(asset_sent), # Préservation nuance
                "Token ID": "",
                "Tx Hash": tx_hash,
                "From": account,
                "To": row.get("Blockchain address") or "Neverless_Internal",
                "Value": amt_sent, # Positif en brut, app2 gère le signe
                "Value ($)": val_usd,
                "Rate ($)": price_sent,
                "Account": account,
                "Counterparty": "External" if tx_type == "Withdrawal" else "Swap"
            })

        # 2. Gestion du flux "ENTRANT" (RECEIVED)
        asset_rec = row.get("Asset received")
        amt_rec = pd.to_numeric(row.get("Amount received"), errors='coerce')
        if not pd.isna(asset_rec) and amt_rec > 0:
            price_rec = pd.to_numeric(row.get("USD price of asset received"), errors='coerce') or 0.0
            val_usd = amt_rec * price_rec

            new_rows.append({
                "Date": dt,
                "Chain": "Neverless",
                "Token": str(asset_rec), # Préservation nuance
                "Token ID": "",
                "Tx Hash": tx_hash,
                "From": "Neverless_Internal",
                "To": account,
                "Value": amt_rec,
                "Value ($)": val_usd,
                "Rate ($)": price_rec,
                "Account": account,
                "Counterparty": "Swap" if tx_type == "Trade" else ("Bank" if tx_type == "Deposit" and "auto-conversion" not in desc else "System")
            })

        # 3. Gestion des FRAIS (FEES)
        fee_amt = pd.to_numeric(row.get("Fee"), errors='coerce')
        if not pd.isna(fee_amt) and fee_amt > 0:
            fee_asset = str(row.get("Asset of the fee", "USDC"))
            price_fee = pd.to_numeric(row.get("USD price of fee asset"), errors='coerce') or 1.0
            val_usd_fee = fee_amt * price_fee

            new_rows.append({
                "Date": dt,
                "Chain": "Neverless",
                "Token": fee_asset,
                "Token ID": "",
                "Tx Hash": tx_hash,
                "From": account,
                "To": "Fees",
                "Value": fee_amt,
                "Value ($)": val_usd_fee,
                "Rate ($)": price_fee,
                "Account": account,
                "Counterparty": "Neverless_Fees"
            })

        progress_bar.progress((idx + 1) / total_rows)

    return pd.DataFrame(new_rows)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=datetime.now().year)
    st.divider()
    st.info("💡 Ce module transforme les lignes mixtes de Neverless en écritures comptables simples (In/Out/Fees) tout en préservant les prix USD natifs.")

uploaded_file = st.file_uploader("📂 Déposez votre export CSV Neverless", type="csv")

if uploaded_file:
    try:
        content = uploaded_file.read().decode("utf-8-sig")
        df_raw = pd.read_csv(io.StringIO(content))
    except:
        uploaded_file.seek(0)
        df_raw = pd.read_csv(uploaded_file, encoding="latin-1")

    st.subheader("👀 Aperçu du fichier source")
    st.dataframe(df_raw.head(5), use_container_width=True)

    if st.button("🚀 Lancer la transcription intelligente", type="primary", use_container_width=True):
        with st.spinner("Traitement en cours..."):
            df_final = process_neverless_csv(df_raw)
            st.session_state.nvl_final = df_final
            st.success(f"Transcription réussie : {len(df_final)} lignes générées à partir de {len(df_raw)} opérations.")

    if "nvl_final" in st.session_state:
        st.divider()
        st.subheader("✅ Résultat au format Sanctuarisation")
        st.dataframe(st.session_state.nvl_final, use_container_width=True)

        st.divider()
        if st.button("💾 Sanctuariser (Enregistrer les Brutes)", use_container_width=True):
            year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
            os.makedirs(year_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"raw_token_transfers_neverless_{ts}.csv"
            save_path = os.path.join(year_dir, filename)

            st.session_state.nvl_final.to_csv(save_path, index=False, encoding="utf-8-sig")
            st.balloons()
            st.success(f"Fichier enregistré avec succès dans : `{save_path}`")

st.sidebar.divider()
st.sidebar.caption("Import Neverless v1.0 - appNeverless")
