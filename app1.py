import os
import pandas as pd
import streamlit as st
from datetime import datetime
import json

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Import CSV (app1)", layout="wide")
st.title("📥 Import CSV Universel")

EXPORT_BASE_DIR = "sanctuarisation"

# --- RAW V4 Standard (19 colonnes) ---
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- UI Mapping Assistants ---
UI_MAPPING_SCHEMAS = {
    "Portfolio": ["Chain", "Asset", "Amount"],
    "Transactions (Native)": ["Date", "Chain", "Tx_Hash", "From", "To", "Asset", "Amount", "Fee_Amount"],
    "Token Transfers": ["Date", "Chain", "Tx_Hash", "From", "To", "Asset", "Amount"]
}

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres d'Import")
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state: st.session_state["_hub_target_year"] = datetime.now().year
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=st.session_state["_hub_target_year"], key="_hub_target_year")
    import_type = st.selectbox("Type de données", list(UI_MAPPING_SCHEMAS.keys()))

    st.divider()
    st.info("💡 Cet outil transforme vos exports (Exchange, Ledger) au format standard du système.")

    st.divider()
    show_status()

# --- Helpers (Centralized logic) ---
import shared_logic as sl

# --- Main App ---
uploaded_file = st.file_uploader("Choisir un fichier CSV", type="csv")

if uploaded_file:
    df_raw = pd_read_csv_safe(uploaded_file)
    st.subheader("👀 Aperçu du fichier importé")
    st.dataframe(df_raw.head(10), width='stretch')

    st.divider()
    st.subheader("🗺️ Mapping des colonnes")

    source_cols = ["(Aucun / Ignorer)"] + list(df_raw.columns)
    target_cols = UI_MAPPING_SCHEMAS[import_type]

    mapping = {}
    col1, col2 = st.columns(2)

    for i, t_col in enumerate(target_cols):
        with (col1 if i % 2 == 0 else col2):
            # Attempt auto-detection
            default_idx = 0
            for j, s_col in enumerate(source_cols):
                if t_col.lower() in s_col.lower() or s_col.lower() in t_col.lower():
                    default_idx = j
                    break

            mapping[t_col] = st.selectbox(f"Colonne pour **{t_col}**", source_cols, index=default_idx, key=f"map_{t_col}")

    st.divider()
    if st.button("🚀 Transformer & Préparer l'Export", type="primary", width='stretch'):
        final_rows = []
        for _, row in df_raw.iterrows():
            v4_row = {c: "" for c in RAW_V4_COLUMNS}
            v4_row["Source_Way"] = "Way_3"
            v4_row["Audit_Status"] = "RAW"
            v4_row["Amount"] = 0.0
            v4_row["Fee_Amount"] = 0.0
            v4_row["Source_Exchange_Rate"] = 0.0

            for t_col, s_col in mapping.items():
                if s_col != "(Aucun / Ignorer)":
                    val = row[s_col]
                    if t_col in RAW_V4_COLUMNS:
                        v4_row[t_col] = val
                    elif t_col == "Chain":
                        v4_row["Chain"] = val

            final_rows.append(v4_row)

        df_mapped = pd.DataFrame(final_rows, columns=RAW_V4_COLUMNS)
        # Apply standard identification
        df_mapped = sl.standardize_df_addresses(df_mapped)

        if "Date" in df_mapped.columns:
            df_mapped["Date"] = pd.to_datetime(df_mapped["Date"], errors='coerce', utc=True)
            df_mapped["Date"] = df_mapped["Date"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        for c in ["Amount", "Fee_Amount", "Source_Exchange_Rate"]:
            df_mapped[c] = pd.to_numeric(df_mapped[c].astype(str).str.replace(',', '.'), errors='coerce').fillna(0.0)

        st.session_state.df_mapped = df_mapped
        st.success("Transformation terminée au format RAW V4 !")

    if "df_mapped" in st.session_state:
        st.subheader("✅ Résultat de la transformation")
        st.dataframe(st.session_state.df_mapped, width='stretch')

        st.divider()
        addr_label = st.text_input("Identifiant du compte (ex: Binance_Pp, Ledger_1)", "Import_Manuel")

        if st.button("💾 Sanctuariser (Enregistrer sur disque)", width='stretch'):
            year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
            os.makedirs(year_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = f"{addr_label}_{ts}"

            file_name = ""
            if import_type == "Portfolio": file_name = f"raw_portfolio_{prefix}.csv"
            elif import_type == "Transactions (Native)": file_name = f"raw_transactions_native_{prefix}.csv"
            else: file_name = f"raw_token_transfers_token_{prefix}.csv"

            save_path = os.path.join(year_dir, file_name)
            st.session_state.df_mapped.to_csv(save_path, index=False, encoding="utf-8-sig")

            st.balloons()
            st.success(f"📂 Fichier sanctuarisé avec succès : `{save_path}`")
            st.info("Vous pouvez maintenant utiliser l'App 2 pour qualifier ces données.")

st.sidebar.divider()
st.sidebar.caption("Import CSV v1.0 - app1")
