import os
import pandas as pd
import streamlit as st
import requests
from datetime import datetime
from shared_logic import get_known_accounts, get_price_eur, get_fiat_rate
import time
import json
import io
import unicodedata

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Import Bleap (appBleap)", layout="wide")
st.title("🚜 Importeur Spécialisé Bleap")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"


# --- Helper: Robust CSV reading ---
def pd_read_csv_safe(file):
    try:
        return pd.read_csv(file, encoding="utf-8-sig", sep=None, engine='python')
    except:
        try:
            file.seek(0)
            return pd.read_csv(io.BytesIO(file.read()), encoding="latin-1", sep=None, engine='python')
        except:
            file.seek(0)
            return pd.read_csv(file, encoding="utf-8", errors="replace", sep=None, engine='python')

# --- Processing Engine ---
def process_bleap_csv(df):
    new_rows = []
    account = "Bleap_App"

    # Filter out non-completed
    df = df[df["Status"] == "COMPLETED"].copy()

    progress_bar = st.progress(0)
    total_rows = len(df)

    for i, (idx, row) in enumerate(df.iterrows()):
        # Parsing date
        dt_str = str(row.get("Created At", row.get("Completed At", "")))
        try:
            dt = pd.to_datetime(dt_str)
        except:
            dt = datetime.now()

        t_type = str(row.get("Type", ""))
        desc = str(row.get("Description", ""))
        currency = str(row.get("Currency", ""))
        amount = pd.to_numeric(row.get("Amount"), errors='coerce') or 0.0
        fees = pd.to_numeric(row.get("Fees"), errors='coerce') or 0.0

        is_imp = False
        cp = "System"
        val = 0.0

        if t_type == "Top Up":
            cp = "banq N26"
            cat = "Achat"
            val = amount # Entry
        elif t_type == "Off-Ramp" and "Bank Transfer (Sell)" in desc:
            cp = "banq N26"
            cat = "Vente"
            val = -amount # Exit
            if currency == "EURA":
                is_imp = True
        elif "Earn" in t_type or "Bridge" in t_type:
            cat = "Transfert Interne"
            # Logic simplified: Deposit is OUT to Earn, Withdrawal is IN from Earn
            val = -amount if "Deposit" in t_type else amount
            cp = "Bleap_Earn"
        elif "Exchange" in t_type or "Trade" in t_type:
            cat = "Swap"
            val = amount # The leg we see in the CSV
            cp = "Swap"
        elif t_type == "Deposit":
            cat = "Transfert In"
            val = amount
            cp = "External"
        elif t_type == "Withdrawal":
            cat = "Transfert Out"
            val = -amount
            cp = "External"
        else:
            cat = "A vérifier"
            val = amount
            cp = "Unknown"

        # Calculation of Value ($) and Value (EUR)
        price_eur = get_price_eur(currency, dt)
        val_eur = abs(val) * price_eur
        rate_usd_eur = get_fiat_rate("USD", dt)
        val_usd = val_eur / rate_usd_eur if rate_usd_eur > 0 else 0.0

        # Robust synthetic Hash including timestamp to avoid collisions
        ts_ms = int(dt.timestamp() * 1000)
        # Use idx (row index) and a secondary counter to ensure absolute uniqueness
        safe_hash = f"BLP-{ts_ms}-{idx}-{i}"

        # Create row
        new_rows.append({
            "Date": dt,
            "Chain": "Bleap",
            "Token": currency, # Preserve nuances
            "Token ID": "",
            "Tx Hash": safe_hash,
            "From": cp if val > 0 else account,
            "To": account if val > 0 else cp,
            "Value": abs(val),
            "Value ($)": val_usd,
            "Rate ($)": (val_usd / abs(val)) if val != 0 else 0.0,
            "Account": account,
            "Counterparty": cp,
            "Category": cat,
            "Imposable": is_imp
        })

        # Handle Fees
        if fees > 0:
             new_rows.append({
                "Date": dt,
                "Chain": "Bleap",
                "Token": currency,
                "Token ID": "",
                "Tx Hash": f"FEE-{safe_hash}",
                "From": account,
                "To": "Fees",
                "Value": fees,
                "Value ($)": (fees * price_eur) / rate_usd_eur if rate_usd_eur > 0 else 0.0,
                "Rate ($)": price_eur / rate_usd_eur if rate_usd_eur > 0 else 0.0,
                "Account": account,
                "Counterparty": "Bleap_Fees",
                "Imposable": False
            })

        progress_bar.progress((i + 1) / total_rows)

    return pd.DataFrame(new_rows)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state: st.session_state["_hub_target_year"] = datetime.now().year
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=st.session_state["_hub_target_year"], key="_hub_target_year")
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
            st.session_state.bleap_final = df_final
            st.success(f"Transcription terminée : {len(df_final)} lignes générées.")

    if "bleap_final" in st.session_state:
        st.divider()
        st.subheader("✅ Résultat au format Sanctuarisation")

        # Interactivité pour la colonne Imposable
        edited_df = st.data_editor(
            st.session_state.bleap_final,
            column_config={
                "Imposable": st.column_config.CheckboxColumn("Taxable (Imp.)", help="Coché pour les Off-Ramp EURA vers N26."),
                "Value ($)": st.column_config.NumberColumn(format="%.2f", disabled=True),
                "Value": st.column_config.NumberColumn(format="%.8f", disabled=True),
                "Date": st.column_config.DatetimeColumn(disabled=True),
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
st.sidebar.caption("Import Bleap v1.0 - appBleap")
