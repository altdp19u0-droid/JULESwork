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

# --- Target Schemas ---
SCHEMAS = {
    "Portfolio": ["Chain", "Asset", "Quantity", "Price ($)", "Value ($)", "Contract"],
    "Transactions (Native)": ["Date", "Chain", "Tx Hash", "Type", "Method", "From", "To", "Value ETH", "Value ($)", "Rate ($)", "Fee ETH", "Fee ($)", "Account", "Counterparty"],
    "Token Transfers": ["Date", "Chain", "Token", "Token ID", "Tx Hash", "From", "To", "Value", "Value ($)", "Rate ($)", "Account", "Counterparty"]
}

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres d'Import")
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=datetime.now().year)
    import_type = st.selectbox("Type de données", list(SCHEMAS.keys()))

    st.divider()
    st.info("💡 Cet outil transforme vos exports (Exchange, Ledger) au format standard du système.")

    st.divider()
    show_status()

# --- Helpers ---
def pd_read_csv_safe(file):
    """Robust CSV reading with encoding fallbacks."""
    try:
        # Try to read first few bytes to detect delimiter or encoding issues
        return pd.read_csv(file, encoding="utf-8-sig")
    except:
        try:
            file.seek(0)
            return pd.read_csv(file, encoding="latin-1")
        except:
            file.seek(0)
            return pd.read_csv(file, encoding="utf-8", errors="replace")

# --- Main App ---
uploaded_file = st.file_uploader("Choisir un fichier CSV", type="csv")

if uploaded_file:
    df_raw = pd_read_csv_safe(uploaded_file)
    st.subheader("👀 Aperçu du fichier importé")
    st.dataframe(df_raw.head(10), use_container_width=True)

    st.divider()
    st.subheader("🗺️ Mapping des colonnes")

    source_cols = ["(Aucun / Ignorer)"] + list(df_raw.columns)
    target_cols = SCHEMAS[import_type]

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
    if st.button("🚀 Transformer & Préparer l'Export", type="primary", use_container_width=True):
        # 1. Selection des colonnes
        final_rows = []
        for _, row in df_raw.iterrows():
            new_row = {}
            for t_col, s_col in mapping.items():
                if s_col == "(Aucun / Ignorer)":
                    new_row[t_col] = None
                else:
                    new_row[t_col] = row[s_col]
            final_rows.append(new_row)

        df_mapped = pd.DataFrame(final_rows)

        # 2. Nettoyage & Parsing
        # Dates
        if "Date" in df_mapped.columns:
            df_mapped["Date"] = pd.to_datetime(df_mapped["Date"], errors='coerce')

        # Numbers
        num_cols = ["Quantity", "Price ($)", "Value ($)", "Value ETH", "Value", "Rate ($)", "Fee ETH", "Fee ($)"]
        for c in num_cols:
            if c in df_mapped.columns:
                df_mapped[c] = pd.to_numeric(df_mapped[c].astype(str).str.replace(',', '.'), errors='coerce').fillna(0.0)

        st.session_state.df_mapped = df_mapped
        st.success("Transformation terminée !")

    if "df_mapped" in st.session_state:
        st.subheader("✅ Résultat de la transformation")
        st.dataframe(st.session_state.df_mapped, use_container_width=True)

        st.divider()
        addr_label = st.text_input("Identifiant du compte (ex: Binance_Pp, Ledger_1)", "Import_Manuel")

        if st.button("💾 Sanctuariser (Enregistrer sur disque)", use_container_width=True):
            year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
            os.makedirs(year_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = f"{addr_label}_{ts}"

            file_name = ""
            if import_type == "Portfolio": file_name = f"raw_portfolio_{prefix}.csv"
            elif import_type == "Transactions (Native)": file_name = f"raw_transactions_{prefix}.csv"
            else: file_name = f"raw_token_transfers_{prefix}.csv"

            save_path = os.path.join(year_dir, file_name)
            st.session_state.df_mapped.to_csv(save_path, index=False, encoding="utf-8-sig")

            st.balloons()
            st.success(f"📂 Fichier sanctuarisé avec succès : `{save_path}`")
            st.info("Vous pouvez maintenant utiliser l'App 2 pour qualifier ces données.")

st.sidebar.divider()
st.sidebar.caption("Import CSV v1.0 - app1")
