import os
import json
import time
import requests
import pandas as pd
import streamlit as st
from fpdf import FPDF
from io import BytesIO, StringIO
import tempfile
import unicodedata
import traceback
from datetime import datetime, time as dt_time
from shared_logic import resolve_raw_addr, get_portfolio_snapshot, get_price_eur

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Helpers ---
def pd_read_csv_safe(path):
    """Robust CSV reading for Windows with encoding fallbacks."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try:
            return pd.read_csv(path, encoding="latin-1")
        except:
            return pd.read_csv(path, encoding="utf-8", errors="replace")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Explorateur (appcons)", layout="wide")
st.title("🔍 Explorateur de Données Sanctuarisées")

EXPORT_BASE_DIR = "sanctuarisation"
POSITIONS_FILE = "position_labels.json"

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

def apply_position_labels(df):
    if df.empty: return df
    from shared_logic import load_external_circuits
    labels = load_position_labels()
    circ_labels = load_external_circuits().get("labels", {})
    combined = {**circ_labels, **labels}

    if not combined: return df
    def format_cp(cp_str):
        raw = resolve_raw_addr(cp_str)
        if raw in combined: return f"{combined[raw]} ({raw})"
        return cp_str
    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    return df


def pdf_safe_str(val, use_unicode=True):
    """Sanitize string for PDF encoding.
    If use_unicode is True, we preserve exotic characters as much as possible.
    """
    if val is None: return ""
    s = str(val)

    if use_unicode:
        # ABSOLUTE PRESERVATION OF NUANCES:
        # We skip NFKC normalization and homoglyph mapping.
        # We only remove null bytes and extremely problematic control characters.
        return "".join(c for c in s if ord(c) >= 32 or c in "\n\r\t")

    # Minimal normalization for fallback mode (Latin-1)
    s = unicodedata.normalize('NFKC', s)

    # Fallback to ASCII-ish mapping if we are forced to Latin-1
    nuance_map = {
        "\ua4f4": "U", "\ua4e2": "S", "\ua4d3": "D", "\ua4c1": "G", "\ua4c3": "H",
        "\u0421": "C", "\u0405": "S", "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T", "\u0425": "X",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u216d": "C", "\u2160": "I", "\u2164": "V", "\u2169": "X", "\u216c": "L", "\u216f": "M",
        "\u200a": " ", "\u2009": " ", "\u202f": " ", "\u2019": "'", "\u20ac": "EUR"
    }
    for k, v in nuance_map.items():
        s = s.replace(k, v)

    return s.encode('latin-1', 'replace').decode('latin-1')

# --- Sidebar ---
with st.sidebar:
    st.header("📂 Sélection des Données")

    # Unicode Diagnostics
    with st.expander("🛠️ Diagnostic PDF & Unicode"):
        import fpdf
        f_ver = getattr(fpdf, "__version__", "Inconnue")
        is_fpdf2 = int(f_ver.split(".")[0]) >= 2 if f_ver != "Inconnue" else False
        st.write(f"Bibliothèque : `fpdf2` {'✅' if is_fpdf2 else '❌ (Installez fpdf2)'}")
        st.write(f"Version : `{f_ver}`")
        if st.button("🧹 Nettoyer Cache Polices (.pkl)", key="btn_clean_font_cache_cons"):
            import glob
            pkl_files = glob.glob("*.pkl")
            for pf in pkl_files:
                try: os.remove(pf)
                except: pass
            st.info(f"{len(pkl_files)} fichiers de cache supprimés.")

    # 1. Années disponibles
    available_years = sorted([y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))], reverse=True)
    if not available_years:
        st.warning("Aucune donnée trouvée dans 'sanctuarisation/'.")
        st.stop()

    selected_years = st.multiselect("Années", available_years, default=available_years[:1])

    # 2. Mode de sélection des fichiers
    sel_mode = st.radio("Mode de sélection", ["Thématique (Rapide)", "Manuel (Précis)"])

    files_to_load = []

    if sel_mode == "Thématique (Rapide)":
        theme = st.selectbox("Thème", ["Sanctuarisation (Qualifié)", "Collecte (Raw)", "Fiat & Registres", "Tout fusionner"])
        for y in selected_years:
            y_dir = os.path.join(EXPORT_BASE_DIR, y)
            all_files = os.listdir(y_dir)
            if theme == "Sanctuarisation (Qualifié)":
                files_to_load.extend([os.path.join(y_dir, f) for f in all_files if f.startswith("qualified_")])
            elif theme == "Collecte (Raw)":
                files_to_load.extend([os.path.join(y_dir, f) for f in all_files if f.startswith("raw_")])
            elif theme == "Fiat & Registres":
                files_to_load.extend([os.path.join(y_dir, f) for f in all_files if "fiat" in f or "swaps" in f or "positions" in f])
            else: # Tout
                files_to_load.extend([os.path.join(y_dir, f) for f in all_files if f.endswith(".csv") and not "backup" in f])
    else:
        # Manuel
        for y in selected_years:
            y_dir = os.path.join(EXPORT_BASE_DIR, y)
            all_files = sorted([f for f in os.listdir(y_dir) if f.endswith(".csv")])
            sel_files = st.multiselect(f"Fichiers {y}", all_files, key=f"sel_{y}")
            files_to_load.extend([os.path.join(y_dir, f) for f in sel_files])

    st.divider()
    st.header("📊 Filtres Globaux")
    exclude_spam = st.checkbox("Exclure les Spams", value=True)

# --- Data Loading Engine ---
@st.cache_data
def load_and_merge(files):
    all_dfs = []
    for f_path in files:
        try:
            temp_df = pd_read_csv_safe(f_path)
            # Add metadata
            temp_df["_source_file"] = os.path.basename(f_path)

            # Standardization
            if "Date" in temp_df.columns:
                temp_df["Date"] = pd.to_datetime(temp_df["Date"], utc=True, errors="coerce")

            # Resolve Account for raw files
            if "Account" not in temp_df.columns:
                from shared_logic import extract_source_from_filename
                temp_df["Account"] = extract_source_from_filename(os.path.basename(f_path))

            # Resolve Counterparty for raw files
            if "Counterparty" not in temp_df.columns:
                if "From" in temp_df.columns and "To" in temp_df.columns:
                    acc_col = temp_df["Account"].astype(str).str.lower()
                    def get_cp_fast(row):
                        f_addr = resolve_raw_addr(str(row.get("From", "")))
                        return str(row.get("To", "")) if f_addr == str(row.get("Account", "")).lower() else str(row.get("From", ""))
                    temp_df["Counterparty"] = temp_df.apply(get_cp_fast, axis=1)
                else:
                    temp_df["Counterparty"] = "n/a"

            # Rename variations to common schema
            rename_map = {
                "Chain": "Network",
                "Token": "Asset",
                "Value": "Amount",
                "Value ETH": "Amount"
            }
            temp_df = temp_df.rename(columns={k: v for k, v in rename_map.items() if k in temp_df.columns and v not in temp_df.columns})

            all_dfs.append(temp_df)
        except: continue

    if not all_dfs: return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)

df_raw = load_and_merge(files_to_load)

if not df_raw.empty:
    df_raw = apply_position_labels(df_raw)

if df_raw.empty:
    st.info("Sélectionnez des fichiers dans le sidebar pour commencer.")
    st.stop()

# --- Post-Processing & Filtering ---
df = df_raw.copy()

# 1. Spam & Duplicate filter
if exclude_spam and "Status" in df.columns:
    df = df[df["Status"].fillna("").astype(str).str.lower() != "spam"]

if "Category" in df.columns:
    df = df[df["Category"].fillna("").astype(str) != "Doublon à ignorer"]

# 2. Date Filter
if "Date" in df.columns:
    df = df.dropna(subset=["Date"])
    min_date = df["Date"].min().date()
    max_date = df["Date"].max().date()

    with st.sidebar:
        st.divider()
        st.header("📅 Période")
        date_range = st.date_input("Intervalle", value=(min_date, max_date), min_value=min_date, max_value=max_date)

    if len(date_range) == 2:
        df = df[(df["Date"].dt.date >= date_range[0]) & (df["Date"].dt.date <= date_range[1])]

# 3. Dynamic Filters
with st.sidebar:
    st.divider()
    st.header("🔍 Filtres de Colonnes")

    filter_cols = ["Asset", "Account", "Network", "Category"]
    active_filters = {}
    for c in filter_cols:
        if c in df.columns:
            options = sorted([str(x) for x in df[c].dropna().unique()])
            sel = st.multiselect(f"Filtrer par {c}", options)
            if sel: active_filters[c] = sel

    # Manual Counterparty Filter
    cp_search = st.text_input("Filtrer par Counterparty (0x...)", "")

for col, val in active_filters.items():
    df = df[df[col].astype(str).isin(val)]

if cp_search:
    if "Counterparty" in df.columns:
        df = df[df["Counterparty"].astype(str).str.contains(cp_search, case=False, na=False)]

# 4. Sorting
with st.sidebar:
    st.divider()
    cols_avail = list(df.columns)
    sort_col = st.selectbox("Trier par", cols_avail, index=cols_avail.index("Date") if "Date" in cols_avail else 0)
    sort_order = st.radio("Sens", ["Décroissant", "Croissant"])
    df = df.sort_values(by=sort_col, ascending=(sort_order == "Croissant"))

    st.divider()
    show_status()

# --- Main App Tabs ---
tab_list, tab_vgp = st.tabs(["📋 Liste de Consultation", "💰 Soldes & VGP"])

with tab_list:
    st.subheader(f"📊 Données Consolidées ({len(df)} lignes)")

    search = st.text_input("🔍 Recherche globale (tous champs)", "")
    if search:
        df = df[df.apply(lambda row: row.astype(str).str.contains(search, case=False).any(), axis=1)]
        st.caption(f"Résultats après recherche : {len(df)} lignes.")

    # Cast for editor
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna("").astype(str)

    st.data_editor(df, width='stretch', disabled=True, key="cons_editor")

    st.download_button(
        "📥 Exporter cette vue en CSV",
        df.to_csv(index=False, encoding="utf-8-sig"),
        "export_consolidated.csv",
        "text/csv",
        width='stretch'
    )

with tab_vgp:
    st.subheader("🏁 État des lieux & VGP Consolidé")

    if df.empty:
        st.warning("Aucune donnée disponible avec les filtres actuels pour calculer la VGP.")
    else:
        # Logic: Balances at end date
        end_date = df["Date"].max()
        st.write(f"Calcul des soldes au **{end_date.strftime('%d/%m/%Y %H:%M')}** (Fin de période)")

        # 1. Aggrégation des soldes par Compte et par Asset
        # On utilise toutes les transactions jusqu'à la date de fin (pas seulement celles filtrées dans la liste)
        df_snapshot_base = df_raw.copy()
        if exclude_spam and "Status" in df_snapshot_base.columns:
            df_snapshot_base = df_snapshot_base[df_snapshot_base["Status"].fillna("").astype(str).str.lower() != "spam"]

        if "Category" in df_snapshot_base.columns:
            df_snapshot_base = df_snapshot_base[df_snapshot_base["Category"].fillna("").astype(str) != "Doublon à ignorer"]

        df_at_date = df_snapshot_base[df_snapshot_base["Date"] <= end_date]

        # Filter EUR which doesn't count for VGP crypto
        df_at_date = df_at_date[df_at_date["Asset"] != "EUR"]

        if df_at_date.empty:
            st.warning("Aucun mouvement trouvé pour calculer des soldes.")
        else:
            balances = df_at_date.groupby(["Account", "Asset"])["Amount"].sum().reset_index()
            balances = balances[balances["Amount"].abs() > 1e-8]

            # UI: Bouton de conversion
            st.divider()
            st.write("📈 **Valorisation des actifs**")

            if st.button("🚀 Rechercher les prix & Calculer la VGP", type="primary", width='stretch'):
                pbar = st.progress(0)
                assets_unique = balances["Asset"].unique()
                prices = {}
                for i, a in enumerate(assets_unique):
                    prices[a] = get_price_eur(a, end_date)
                    pbar.progress((i + 1) / len(assets_unique))

                balances["Prix (EUR)"] = balances["Asset"].map(prices)
                balances["Valeur (EUR)"] = balances["Amount"] * balances["Prix (EUR)"]

                st.session_state.vgp_df = balances
                st.success("Calcul de valorisation terminé.")

            if "vgp_df" in st.session_state:
                res_df = st.session_state.vgp_df

                # Vérification d'intégrité
                zero_prices = res_df[res_df["Prix (EUR)"] == 0]
                if not zero_prices.empty:
                    st.error(f"🚨 **Calcul Compromis :** {len(zero_prices)} actifs ont un prix de 0.00. La VGP totale est sous-estimée. Veuillez utiliser l'**AppPriceFix**.")

                # Total par compte
                st.write("🔍 **Détail par Compte et Asset**")
                st.dataframe(res_df, width='stretch')

                st.divider()
                col_v1, col_v2 = st.columns(2)

                # 1. Total Global
                total_vgp = res_df["Valeur (EUR)"].sum()
                col_v1.metric("Valeur Globale du Portefeuille (VGP)", f"{total_vgp:,.2f} €")

                # 2. Total par Compte
                st.write("📊 **Répartition par Compte**")
                by_acc = res_df.groupby("Account")["Valeur (EUR)"].sum().reset_index()
                st.dataframe(by_acc, width='stretch')

                # Export results
                st.divider()
                c1, c2 = st.columns(2)
                c1.download_button(
                    "📥 Exporter en CSV",
                    res_df.to_csv(index=False, encoding="utf-8-sig"),
                    f"vgp_snapshot_{end_date.strftime('%Y%m%d')}.csv",
                    "text/csv",
                    width='stretch'
                )

                # PDF Generation
                def generate_vgp_pdf(data_df, date_str, total_val):
                    import fpdf
                    f_ver = getattr(fpdf, "__version__", "1.0")
                    is_fpdf2 = int(f_ver.split(".")[0]) >= 2

                    pdf = FPDF(orientation='L', unit='mm', format='A4')
                    pdf.set_auto_page_break(auto=True, margin=15)

                    font_path = "DejaVuSans.ttf"
                    font_bold_path = "DejaVuSans-Bold.ttf"
                    main_font = "helvetica"

                    if os.path.exists(font_path) and os.path.exists(font_bold_path):
                        try:
                            pdf.add_font("DejaVu", "", font_path)
                            pdf.add_font("DejaVu", "B", font_bold_path)
                            main_font = "DejaVu"
                        except: pass

                    if is_fpdf2 and main_font == "DejaVu":
                        try: pdf.set_fallback_fonts(["DejaVu"])
                        except: pass

                    pdf.add_page()
                    pdf.set_font(main_font, 'B', 16)
                    pdf.cell(0, 10, f"Etat des Lieux & VGP - {date_str}", ln=True, align='C')
                    pdf.ln(10)

                    pdf.set_font(main_font, 'B', 10)
                    pdf.set_fill_color(200, 200, 200)
                    cols = ["Account", "Asset", "Amount", "Prix (EUR)", "Valeur (EUR)"]
                    # Expanded Account to 110mm, reduced others to fit (Total 270mm for A4 L)
                    col_widths = [110, 30, 45, 40, 45]
                    for i, c in enumerate(cols):
                        pdf.cell(col_widths[i], 10, c, border=1, fill=True)
                    pdf.ln()

                    pdf.set_font(main_font, '', 10)
                    use_uni = (main_font == "DejaVu")
                    for _, row in data_df.iterrows():
                        acc = pdf_safe_str(row["Account"], use_uni)[:40]
                        asset = pdf_safe_str(row["Asset"], use_uni)
                        pdf.cell(col_widths[0], 10, acc, border=1)
                        pdf.cell(col_widths[1], 10, asset, border=1)
                        pdf.cell(col_widths[2], 10, f"{row['Amount']:.4f}", border=1)
                        pdf.cell(col_widths[3], 10, f"{row['Prix (EUR)']:.2f} EUR", border=1)
                        pdf.cell(col_widths[4], 10, f"{row['Valeur (EUR)']:.2f} EUR", border=1)
                        pdf.ln()

                    pdf.ln(10)
                    pdf.set_font(main_font, 'B', 12)
                    pdf.cell(0, 10, f"VALEUR GLOBALE DU PORTEFEUILLE : {total_val:,.2f} EUR", ln=True, align='R')

                    # Extraction des bytes (Directement en mémoire pour éviter les erreurs de fichier/encodage sur Windows)
                    return bytes(pdf.output())

                if c2.button("📊 Préparer le Rapport PDF", width='stretch'):
                    if "vgp_pdf_bytes" in st.session_state: del st.session_state.vgp_pdf_bytes
                    try:
                        final_bytes = generate_vgp_pdf(res_df, end_date.strftime('%d/%m/%Y'), total_vgp)
                        # Convert to bytes if it came as string/bytearray
                        if not isinstance(final_bytes, bytes):
                            final_bytes = bytes(final_bytes)

                        if len(final_bytes) > 500:
                            st.session_state.vgp_pdf_bytes = final_bytes
                            st.success(f"Rapport PDF prêt ({len(final_bytes)} octets).")
                            st.rerun()
                        else:
                            st.error("Erreur : Le PDF généré est trop petit.")
                    except Exception as e:
                        st.error(f"Erreur de génération : {e}")
                        st.expander("Détails technique de l'erreur").code(traceback.format_exc())

                if "vgp_pdf_bytes" in st.session_state:
                    c2.download_button(
                        "📄 Télécharger le Rapport PDF",
                        data=st.session_state.vgp_pdf_bytes,
                        file_name=f"Rapport_VGP_{end_date.strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        width='stretch'
                    )

st.sidebar.divider()
st.sidebar.caption("Explorateur v1.0 - appcons")
