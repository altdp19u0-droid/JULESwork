import os
import pandas as pd
import streamlit as st
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
    "Asset", "Amount", "Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset",
    "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

def create_v4_row(dt, method, account, cp, asset, val, fees=0.0, tx_hash="", eur_val=0.0):
    # If eur_val is provided, we can store it in Source_Exchange_Rate or similar if needed,
    # but RAW V4 usually expects USD for valuations.
    # For EURA, 1 EURA = 1 EUR.
    return {
        "Date": dt.isoformat(),
        "Chain": "Bleap",
        "Tx_Hash": tx_hash,
        "Type": "CEX_Mvt",
        "Method": method,
        "Account": account,
        "From": cp if val > 0 else account,
        "To": account if val > 0 else cp,
        "From_Label": "",
        "To_Label": "",
        "Counterparty": cp,
        "Asset": asset,
        "Amount": val,
        "Valeur $": 0.0, # Will be filled if needed, but for EUR stables it's better to use fiat rate later
        "USD prix asset reçu": 0.0,
        "USD prix asset envoyé": 0.0,
        "USD prix de fée asset": 0.0,
        "Fee_Asset": asset if fees > 0 else "",
        "Fee_Amount": fees,
        "Source_Way": "Way_3",
        "Audit_Status": "RAW",
        "Fee_Audit_Alert": "",
        "Source_Exchange_Rate": 0.0
    }

# --- Processing Engine ---
def process_bleap_csv(df):
    new_rows = []
    account = "bleap_app"

    # Handle Status
    if "Status" in df.columns:
        df = df[df["Status"] == "COMPLETED"].copy()

    progress_bar = st.progress(0)
    total_rows = len(df)

    # Column name cleaning
    df.columns = [c.strip() for c in df.columns]

    for i, (idx, row) in enumerate(df.iterrows()):
        # Parsing date
        dt_str = str(row.get("Completed At", row.get("Created At", row.get("Date", ""))))
        try:
            dt = pd.to_datetime(dt_str, utc=True)
        except:
            dt = datetime.now()

        t_type = str(row.get("Type", ""))
        desc = str(row.get("Description", ""))
        currency = str(row.get("Currency", "")).upper().strip()

        # Numeric cleanup for French format (1 000,00)
        def clean_num(v):
            if pd.isna(v) or str(v).lower() in ["nan", ""]: return 0.0
            s = str(v).replace(" ", "").replace("€", "").replace(",", ".")
            try: return float(s)
            except: return 0.0

        amount = clean_num(row.get("Amount"))
        fees = clean_num(row.get("Fees"))

        ts_ms = int(dt.timestamp() * 1000)
        safe_hash = f"BLP-{ts_ms}-{idx}-{i}"

        # --- LOGIQUE D'IMPORTATION BLEAP V3 (Multi-colonnes) ---

        if "Exchange" in t_type or "Trade" in t_type:
            # Look for specific movement columns
            val_usdc = clean_num(row.get("Valeur mouvement USDC"))
            val_eura = clean_num(row.get("Valeur mouvement EURA"))
            val_eth = clean_num(row.get("Valeur mouvement ETH")) # Just in case

            # If we are on the row where Currency is the RECEIVED asset
            # we check if we have the SENT asset value in another column
            if currency == "USDC":
                # Received USDC, sent what?
                new_rows.append(create_v4_row(dt, t_type, account, "swap", "USDC", amount, fees, safe_hash))
                if val_eura < 0:
                    new_rows.append(create_v4_row(dt, t_type, account, "swap", "EURA", val_eura, 0.0, safe_hash))
            elif currency == "EURA":
                new_rows.append(create_v4_row(dt, t_type, account, "swap", "EURA", amount, fees, safe_hash))
                if val_usdc < 0:
                    new_rows.append(create_v4_row(dt, t_type, account, "swap", "USDC", val_usdc, 0.0, safe_hash))
            elif currency == "ETH":
                new_rows.append(create_v4_row(dt, t_type, account, "swap", "ETH", amount, fees, safe_hash))
                if val_usdc < 0:
                    new_rows.append(create_v4_row(dt, t_type, account, "swap", "USDC", val_usdc, 0.0, safe_hash))
            else:
                # Fallback to single leg if nothing else found
                new_rows.append(create_v4_row(dt, t_type, account, "swap", currency, amount, fees, safe_hash))

        elif t_type == "Top Up":
            # Identify source
            cp = "banq n26"
            orig = str(row.get("origine", "")).lower()
            if "banq" in orig: cp = orig

            # Acquisition price tracking
            fiat_acq = clean_num(row.get("Fiat EUR acquisition"))
            # We mark as RAW_TAXABLE if it has fiat info to help user identify acquisitions
            row_obj = create_v4_row(dt, t_type, account, cp, currency, amount, fees, safe_hash)
            if fiat_acq > 0:
                row_obj["Audit_Status"] = "RAW_ACQUISITION" # Custom status for easier filtering
                # Store fiat value in Source_Exchange_Rate for Step 2 Injection logic
                row_obj["Source_Exchange_Rate"] = fiat_acq / amount if amount > 0 else 0.0

            new_rows.append(row_obj)

        elif t_type == "Off-Ramp":
            cp = "banq n26"
            dest = str(row.get("destination", "")).lower()
            if "banq" in dest: cp = dest

            fiat_cess = clean_num(row.get("Fiat EUR cession"))
            row_obj = create_v4_row(dt, t_type, account, cp, currency, -amount, fees, safe_hash)
            if fiat_cess < 0 or "Bank Transfer (Sell)" in desc:
                row_obj["Audit_Status"] = "RAW_TAXABLE"

            new_rows.append(row_obj)

        elif "Earn" in t_type:
            val = -amount if "Deposit" in t_type else amount
            new_rows.append(create_v4_row(dt, t_type, account, "bleap_earn", currency, val, fees, safe_hash))

        elif "Bridge" in t_type:
            # Bridge is usually internal or to specific chain
            val = -amount if amount > 0 and "Withdraw" in desc else amount
            new_rows.append(create_v4_row(dt, t_type, account, "bridge", currency, val, fees, safe_hash))

        elif t_type == "Deposit":
            new_rows.append(create_v4_row(dt, t_type, account, "external", currency, amount, fees, safe_hash))
        elif t_type == "Withdrawal":
            new_rows.append(create_v4_row(dt, t_type, account, "external", currency, -amount, fees, safe_hash))
        else:
            new_rows.append(create_v4_row(dt, t_type, account, "system", currency, amount, fees, safe_hash))

        progress_bar.progress((i + 1) / total_rows)

    return pd.DataFrame(new_rows, columns=RAW_V4_COLUMNS)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.session_state.get("_hub_target_year")
    if target_year is None:
        g_conf = sl.load_global_config()
        target_year = g_conf.get("processing_year") or datetime.now().year
        st.session_state["_hub_target_year"] = target_year

    st.write(f"📅 Année active : **{target_year}**")
    st.divider()
    sl.show_status()
    st.divider()
    st.info("💡 Version 3.0 : Support des colonnes de valeur mouvement (USDC/EURA) et détection des prix d'acquisition Fiat.")

uploaded_file = st.file_uploader("📂 Déposez votre export CSV Bleap (Format Natif)", type="csv")

if uploaded_file:
    # Use standard pandas with proper separator detection
    try:
        content = uploaded_file.read().decode("utf-8-sig")
        # Try semicolon then comma
        if ";" in content.split("\n")[0]:
            df_raw = pd.read_csv(io.StringIO(content), sep=";")
        else:
            df_raw = pd.read_csv(io.StringIO(content))
    except:
        uploaded_file.seek(0)
        df_raw = pd.read_csv(uploaded_file, encoding="latin-1")

    st.subheader("👀 Aperçu du fichier source")
    st.dataframe(df_raw.head(5), width='stretch')

    if st.button("🚀 Lancer la transcription Bleap", type="primary", width='stretch'):
        with st.spinner("Analyse et transcription..."):
            df_final = process_bleap_csv(df_raw)
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
                "Audit_Status": st.column_config.SelectboxColumn("Status", options=["RAW", "RAW_ACQUISITION", "RAW_TAXABLE"])
            },
            width='stretch',
            num_rows="fixed",
            key="bleap_editor_v3"
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
st.sidebar.caption("Import Bleap v3.0 (Natif) - appBleap")
