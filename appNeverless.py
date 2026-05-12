import os
import pandas as pd
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
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- Logic: Neverless Expansion ---
def process_neverless_csv(df):
    new_rows = []

    owners_map = load_owner_accounts() # {addr_low: label}

    # Detect IDs that are "Auto-conversion"
    # To mark corresponding legs as Achat/Vente by default.
    auto_withdrawal_ids = set(df[df["Description"].fillna("").str.contains("Auto-conversion when withdrawing fiat", case=False)]["ID"].unique())
    auto_deposit_ids = set(df[df["Description"].fillna("").str.contains("Auto-conversion when depositing fiat", case=False)]["ID"].unique())

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

        # Robust synthetic Hash including timestamp and unique index to avoid collisions
        ts_ms = int(dt.timestamp() * 1000)
        if tx_hash == "nan" or not tx_hash:
            base_hash = f"NVL-{ts_ms}-{raw_id}-{i}"
        else:
            base_hash = tx_hash

        desc_raw = str(row.get("Description", ""))
        desc = desc_raw.lower()
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

            # Case: Auto-conversion Withdraw (EURC -> EUR)
            if tx_type == "Trade" and "auto-conversion when withdrawing fiat" in desc:
                cat = "Vente"
                is_imp = True
            else:
                cat = "Vente" if tx_type == "Withdrawal" else ("Swap" if tx_type == "Trade" else "A vérifier")

            cp = "External" if tx_type == "Withdrawal" else "Swap"

            # --- SPECIAL WITHDRAWAL LOGIC ---
            bc_addr_raw = row.get("Blockchain address")
            if pd.isna(bc_addr_raw) or str(bc_addr_raw).lower() == "nan":
                bc_addr_raw = ""
            else:
                bc_addr_raw = str(bc_addr_raw).strip()

            bc_addr = resolve_raw_addr(bc_addr_raw).lower() if bc_addr_raw else ""

            if tx_type == "Withdrawal":
                # A. Bank Withdrawal (Crypto -> Fiat)
                if ("banq" in desc) and not bc_addr:
                    cat = "Vente"
                    is_imp = True
                    cp = desc_raw
                # B. Internal Transfer (Owner -> Owner)
                elif bc_addr in owners_map:
                    cat = "Transfert Interne"
                    is_imp = False
                    cp = owners_map[bc_addr]

            # Specific Neverless sub-labels (only if not already set by bank/owner logic)
            if cp in ["External", "Swap"]:
                if "strategies" in desc: cp = "Neverless Strategies"
                elif "prime" in desc: cp = "Neverless Prime"

            if ("banq_" in desc) and (tx_type != "Withdrawal" or not cp):
                cp = desc_raw

            new_rows.append({
                "Date": dt.isoformat(),
                "Chain": "Neverless",
                "Tx Hash": f"OUT-{base_hash}",
                "Type": "CEX_Mvt",
                "Method": tx_type,
                "Account": account,
                "From": account,
                "To": row.get("Blockchain address") or "Neverless_Internal",
                "From_Label": "",
                "To_Label": "",
                "Counterparty": cp,
                "Asset": str(asset_sent),
                "Amount": -amt_sent,
                "Fee_Asset": "",
                "Fee_Amount": 0.0,
                "Source_Way": "Way_3",
                "Audit_Status": "RAW",
                "Fee_Audit_Alert": "",
                "Source_Exchange_Rate": price_sent
            })

        # 2. Gestion du flux "ENTRANT" (RECEIVED)
        asset_rec = row.get("Asset received")
        amt_rec = pd.to_numeric(row.get("Amount received"), errors='coerce')
        if not pd.isna(asset_rec) and amt_rec > 0:
            price_rec = pd.to_numeric(row.get("USD price of asset received"), errors='coerce') or 0.0
            val_usd = amt_rec * price_rec

            if "interest" in desc:
                cat = "Récompense"
            elif tx_type == "Trade" and "auto-conversion when depositing fiat" in desc:
                cat = "Achat"
            else:
                cat = "Achat" if tx_type == "Deposit" else ("Swap" if tx_type == "Trade" else "A vérifier")

            cp = "Swap" if tx_type == "Trade" else ("Bank" if tx_type == "Deposit" and "auto-conversion" not in desc else "System")

            # Specific Neverless labels
            if "interest" in desc:
                cp = "Yield"
                if "strategies" in desc: cp = "Neverless Strategies (Yield)"
                elif "prime" in desc: cp = "Neverless Prime (Yield)"
            elif "strategies" in desc:
                cp = "Neverless Strategies"
            elif "prime" in desc:
                cp = "Neverless Prime"

            if "banq_" in desc: cp = desc_raw

            new_rows.append({
                "Date": dt.isoformat(),
                "Chain": "Neverless",
                "Tx Hash": f"IN-{base_hash}",
                "Type": "CEX_Mvt",
                "Method": tx_type,
                "Account": account,
                "From": "Neverless_Internal",
                "To": account,
                "From_Label": "",
                "To_Label": "",
                "Counterparty": cp,
                "Asset": str(asset_rec),
                "Amount": amt_rec,
                "Fee_Asset": "",
                "Fee_Amount": 0.0,
                "Source_Way": "Way_3",
                "Audit_Status": "RAW",
                "Fee_Audit_Alert": "",
                "Source_Exchange_Rate": price_rec
            })

        # 3. Gestion des FRAIS (FEES)
        fee_amt = pd.to_numeric(row.get("Fee"), errors='coerce')
        if not pd.isna(fee_amt) and fee_amt > 0:
            fee_asset = str(row.get("Asset of the fee", "USDC"))
            price_fee = pd.to_numeric(row.get("USD price of fee asset"), errors='coerce') or 1.0
            val_usd_fee = fee_amt * price_fee

            new_rows.append({
                "Date": dt.isoformat(),
                "Chain": "Neverless",
                "Tx Hash": f"FEE-{base_hash}",
                "Type": "CEX_Mvt",
                "Method": "Fee",
                "Account": account,
                "From": account,
                "To": "Neverless_Fees",
                "From_Label": "",
                "To_Label": "",
                "Counterparty": "Neverless_Fees",
                "Asset": fee_asset,
                "Amount": -fee_amt,
                "Fee_Asset": fee_asset,
                "Fee_Amount": fee_amt,
                "Source_Way": "Way_3",
                "Audit_Status": "RAW",
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
    st.dataframe(df_raw.head(5), width='stretch')

    if st.button("🚀 Lancer la transcription intelligente", type="primary", width='stretch'):
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
