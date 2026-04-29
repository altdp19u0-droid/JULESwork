import os
import pandas as pd
import streamlit as st
import requests
from datetime import datetime
from shared_logic import get_fiat_rate, get_price_eur
import time
import json
import io
import unicodedata

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Import Neverless (appNeverless)", layout="wide")
st.title("🚜 Importeur Spécialisé Neverless")

EXPORT_BASE_DIR = "sanctuarisation"


# --- Logic: Neverless Expansion ---
def process_neverless_csv(df):
    new_rows = []

    # Detect IDs that are "Auto-conversion when withdrawing fiat"
    # To mark the corresponding EUR Withdrawal as taxable by default.
    auto_withdrawal_ids = set(df[df["Description"].fillna("").str.contains("Auto-conversion when withdrawing fiat", case=False)]["ID"].unique())

    progress_bar = st.progress(0)
    total_rows = len(df)

    for i, (idx, row) in enumerate(df.iterrows()):
        dt_str = str(row.get("Date", ""))
        try:
            dt = pd.to_datetime(dt_str)
        except:
            dt = datetime.now()

        tx_type = str(row.get("Type", ""))
        raw_id = str(row.get("ID", ""))
        tx_hash = str(row.get("Blockchain transaction hash", ""))

        # Robust synthetic Hash including timestamp and type to avoid collisions
        ts_ms = int(dt.timestamp() * 1000)
        if tx_hash == "nan" or not tx_hash:
            base_hash = f"NVL-{ts_ms}-{raw_id}"
        else:
            base_hash = tx_hash

        desc = str(row.get("Description", "")).lower()
        account = "Neverless_App"

        # --- LOGIQUE D'EXPANSION ---

        # 1. Gestion du flux "SORTANT" (SENT)
        asset_sent = row.get("Asset sent")
        amt_sent = pd.to_numeric(row.get("Amount sent"), errors='coerce')
        if not pd.isna(asset_sent) and amt_sent > 0:
            price_sent = pd.to_numeric(row.get("USD price of asset sent"), errors='coerce') or 0.0
            val_usd = amt_sent * price_sent

            # Detection logic for Taxable Withdrawal
            is_imp = False
            is_eur_withdrawal = (str(asset_sent).upper() == "EUR" and tx_type == "Withdrawal")
            if is_eur_withdrawal and raw_id in auto_withdrawal_ids:
                is_imp = True

            cat = "Vente" if tx_type == "Withdrawal" else ("Swap" if tx_type == "Trade" else "A vérifier")

            new_rows.append({
                "Date": dt,
                "Chain": "Neverless",
                "Token": str(asset_sent), # Préservation nuance
                "Token ID": "",
                "Tx Hash": f"OUT-{base_hash}",
                "From": account,
                "To": row.get("Blockchain address") or "Neverless_Internal",
                "Value": amt_sent, # Positif en brut, app2 gère le signe
                "Value ($)": val_usd,
                "Rate ($)": price_sent,
                "Account": account,
                "Counterparty": "External" if tx_type == "Withdrawal" else "Swap",
                "Category": cat,
                "Imposable": is_imp
            })

        # 2. Gestion du flux "ENTRANT" (RECEIVED)
        asset_rec = row.get("Asset received")
        amt_rec = pd.to_numeric(row.get("Amount received"), errors='coerce')
        if not pd.isna(asset_rec) and amt_rec > 0:
            price_rec = pd.to_numeric(row.get("USD price of asset received"), errors='coerce') or 0.0
            val_usd = amt_rec * price_rec

            cat = "Achat" if tx_type == "Deposit" else ("Swap" if tx_type == "Trade" else "A vérifier")

            new_rows.append({
                "Date": dt,
                "Chain": "Neverless",
                "Token": str(asset_rec), # Préservation nuance
                "Token ID": "",
                "Tx Hash": f"IN-{base_hash}",
                "From": "Neverless_Internal",
                "To": account,
                "Value": amt_rec,
                "Value ($)": val_usd,
                "Rate ($)": price_rec,
                "Account": account,
                "Counterparty": "Swap" if tx_type == "Trade" else ("Bank" if tx_type == "Deposit" and "auto-conversion" not in desc else "System"),
                "Category": cat,
                "Imposable": False
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
                "Tx Hash": f"FEE-{base_hash}",
                "From": account,
                "To": "Fees",
                "Value": fee_amt,
                "Value ($)": val_usd_fee,
                "Rate ($)": price_fee,
                "Account": account,
                "Counterparty": "Neverless_Fees",
                "Category": "Frais",
                "Imposable": False
            })

        progress_bar.progress((i + 1) / total_rows)

    return pd.DataFrame(new_rows)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=datetime.now().year)
    st.divider()
    st.info("💡 Ce module transforme les lignes mixtes de Neverless en écritures comptables simples (In/Out/Fees) tout en préservant les prix USD natifs.")

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
    st.dataframe(df_raw.head(5), use_container_width=True)

    if st.button("🚀 Lancer la transcription intelligente", type="primary", use_container_width=True):
        with st.spinner("Traitement en cours..."):
            df_final = process_neverless_csv(df_raw)
            st.session_state.nvl_final = df_final
            st.success(f"Transcription réussie : {len(df_final)} lignes générées à partir de {len(df_raw)} opérations.")

    if "nvl_final" in st.session_state:
        st.divider()
        st.subheader("✅ Résultat au format Sanctuarisation")

        # Affichage avec possibilité de modification
        edited_df = st.data_editor(
            st.session_state.nvl_final,
            column_config={
                "Imposable": st.column_config.CheckboxColumn("Taxable (Imp.)", help="Coché par défaut pour les sorties Fiat EUR liées à une vente."),
                "Value ($)": st.column_config.NumberColumn(format="%.2f", disabled=True),
                "Value": st.column_config.NumberColumn(format="%.8f", disabled=True),
                "Rate ($)": st.column_config.NumberColumn(format="%.4f", disabled=True),
                "Date": st.column_config.DatetimeColumn(disabled=True),
            },
            use_container_width=True,
            num_rows="fixed",
            key="nvl_editor"
        )

        st.divider()
        if st.button("💾 Sanctuariser (Enregistrer les Brutes)", use_container_width=True):
            year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
            os.makedirs(year_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"raw_token_transfers_neverless_{ts}.csv"
            save_path = os.path.join(year_dir, filename)

            # On enregistre la version éditée
            edited_df.to_csv(save_path, index=False, encoding="utf-8-sig")

            # Mise à jour de la session pour refléter les changements
            st.session_state.nvl_final = edited_df

            st.balloons()
            st.success(f"Fichier enregistré avec succès dans : `{save_path}`")

st.sidebar.divider()
st.sidebar.caption("Import Neverless v1.0 - appNeverless")
