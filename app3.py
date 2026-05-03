import os
import pandas as pd
import streamlit as st
from datetime import datetime
from shared_logic import (
    resolve_raw_addr, get_portfolio_snapshot, get_price_eur,
    get_fiat_rate, pd_read_csv_safe, load_price_cache, save_price_cache,
    calculate_fiscal_gains, get_file_path, check_file_freshness,
    validate_spam_exclusion, standardize_df_addresses
)
from fpdf import FPDF
from io import BytesIO, StringIO
import json
import tempfile
import unicodedata
import traceback
import time
import requests

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Fiscalité (app3)", layout="wide")
st.title("⚖️ Fiscalité Crypto France (Art. 150 VH bis)")

EXPORT_BASE_DIR = "sanctuarisation"
POSITIONS_FILE = "position_labels.json"

# --- Helpers ---
def load_eoy_prices(year):
    path = get_file_path(year, 'prices')
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_eoy_prices(year, prices_dict):
    path = get_file_path(year, 'prices')
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(prices_dict, f, indent=4)
            return True
        except: return False
    return False



def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}


def apply_position_labels(df):
    """Remplace l'adresse Counterparty par 'Label (0x...)' si un mapping existe."""
    if df.empty: return df
    from shared_logic import load_external_circuits

    labels = load_position_labels()
    circ_labels = load_external_circuits().get("labels", {})
    combined = {**circ_labels, **labels}

    if not combined: return df

    def format_cp(cp_str):
        raw = resolve_raw_addr(cp_str)
        if raw in combined:
            return f"{combined[raw]} ({raw})"
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

def load_data(year):
    paths = {
        'journal': get_file_path(year, 'qualified'),
        'fiat': get_file_path(year, 'fiat'),
        'positions': get_file_path(year, 'positions')
    }

    # Track load time for freshness
    st.session_state.last_app3_sync_time = time.time()

    data = {}
    for key, path in paths.items():
        if os.path.exists(path) and os.path.getsize(path) > 0:
            df = pd_read_csv_safe(path)
            # UNIFICATION
            df = standardize_df_addresses(df)
            # Standardisation Date
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')

            # Type Safety: Force numeric types to avoid pyarrow string errors
            num_cols = ["Amount", "Value ($)", "VGP (EUR)", "Prix de Cession (EUR)", "Montant EUR", "Quantité"]
            for col in num_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

            if key == 'journal':
                # --- DOUBLE VÉRIFICATION SPAM À L'OUVERTURE ---
                leaked_indices = validate_spam_exclusion(df)
                if leaked_indices:
                    df.loc[leaked_indices, "Status"] = "Spam"
                    # Only show toast/message once for the whole dataset
                    st.toast(f"🛡️ Art 150 VH bis : {len(leaked_indices)} lignes spams écartées automatiquement.")

                # FILTRAGE ANTI-SPAM GLOBAL
                if 'Status' in df.columns:
                    df = df[df['Status'] != 'Spam']

                df = apply_position_labels(df)

            data[key] = df
        else:
            data[key] = pd.DataFrame()
    return data

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres Fiscaux")

    # Unicode Diagnostics
    with st.expander("🛠️ Diagnostic PDF & Unicode"):
        import fpdf
        f_ver = getattr(fpdf, "__version__", "Inconnue")
        is_fpdf2 = int(f_ver.split(".")[0]) >= 2 if f_ver != "Inconnue" else False
        st.write(f"Bibliothèque : `fpdf2` {'✅' if is_fpdf2 else '❌ (Installez fpdf2)'}")
        st.write(f"Version : `{f_ver}`")

        if not os.path.exists("DejaVuSans.ttf"):
            st.error("Police DejaVuSans.ttf : Manquante")
        else:
            st.success("Police DejaVuSans.ttf : OK")

        if st.button("🧹 Nettoyer Cache Polices (.pkl)", key="btn_clean_font_cache"):
            import glob
            pkl_files = glob.glob("*.pkl")
            for pf in pkl_files:
                try: os.remove(pf)
                except: pass
            st.info(f"{len(pkl_files)} fichiers de cache supprimés.")

    target_year = st.number_input("Année fiscale", min_value=2015, max_value=2030, value=datetime.now().year)

    # Year switch detection
    if "last_target_year" not in st.session_state:
        st.session_state.last_target_year = target_year

    if target_year != st.session_state.last_target_year:
        # Full Reset on Year Switch
        for k in list(st.session_state.keys()):
            if k not in ["last_target_year"]: del st.session_state[k]
        st.session_state.last_target_year = target_year
        st.cache_data.clear()
        st.rerun()

    st.divider()
    flat_tax_rate = st.slider("Taux d'imposition (PFU)", 0.0, 1.0, 0.30, 0.01)
    abattement = st.number_input("Abattement annuel (EUR)", value=305.0)

    st.divider()
    if st.button("🔄 Forcer recharge (Disque)", key="btn_reload_disk", help="Relit les journaux qualifiés depuis le disque."):
        # Clear specific session states to force reload from CSV
        keys_to_clear = [
            "journal_df", "local_valued", "proto_valued", "manual_pos_valued",
            "bilan_fiscale", "fiscal_pdf_bytes", "full_inventory_csv"
        ]
        for k in keys_to_clear:
            if k in st.session_state: del st.session_state[k]
        st.cache_data.clear()
        st.success("Données rechargées.")
        st.rerun()

    # Data Freshness Warning
    qual_path = get_file_path(target_year, 'qualified')
    if os.path.exists(qual_path):
        last_load = st.session_state.get("last_app3_sync_time", 0)
        if check_file_freshness(qual_path, last_load):
            st.warning("⚠️ Données qualifiées mises à jour. Veuillez 'Recharger'.")

    if st.button("🧮 Recalculer tout (Session)", key="btn_recalc_all"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    show_status()

data = load_data(target_year)

# --- Vérification d'Intégrité (Zéro Fallback) ---
if 'journal' in data and not data['journal'].empty:
    j = data['journal']
    def is_imp_check(v): return str(v).upper().strip() in ["TRUE", "1", "1.0", "VRAI"]
    mask_cess_check = (j['Imposable'].apply(is_imp_check) | j['Category'].fillna("").str.contains("Vente", case=False)) & (j['Asset'] != 'EUR')
    if mask_cess_check.any() and 'VGP (EUR)' in j.columns:
        # Check for zero or negative VGP
        missing_vgp = j[mask_cess_check & (j['VGP (EUR)'].fillna(0) <= 0)]
        if not missing_vgp.empty:
            st.error(f"🚨 **Incohérence Fiscale :** {len(missing_vgp)} cessions ont une VGP nulle ou négative. Le calcul de la plus-value sera erroné ou ignoré. Veuillez régulariser dans l'**App 2 (VGP)** ou l'**AppPriceFix**.")

# --- Logic: Fiscal calculations ---
def calculate_acquisition_price(year):
    # Somme des flux fiat entrants (Achat) depuis le début (théoriquement cumulé)
    # Pour simplifier ici, on regarde l'année en cours + une saisie manuelle de l'historique
    fiat_df = data['fiat']
    if fiat_df.empty: return 0.0

    # On filtre sur les types "Achat"
    purchases = fiat_df[fiat_df['Type'].str.contains("Achat", na=False)]
    return purchases['Montant EUR'].sum()

# --- Tabs ---
tab_accounts, tab_acq, tab_cessions, tab_bilan = st.tabs([
    "📂 Comptes & Positions",
    "💰 Prix d'Acquisition",
    "📈 Cessions (2086)",
    "📋 Bilan Final"
])

with tab_accounts:
    st.subheader("🏦 Liste des Comptes Propriétaires Détectés")
    journal = data['journal']

    # Initialize variables to avoid NameError in downstream tabs/PDF generation
    accounts = []
    derived_local = pd.DataFrame()
    df_protocols = pd.DataFrame()

    # NEW: Accumulate manual positions from all years
    manual_all = []
    for y in range(2020, target_year + 1):
        p_path = os.path.join(EXPORT_BASE_DIR, str(y), f"manual_positions_{y}.csv")
        if os.path.exists(p_path):
            try:
                tmp_m = pd_read_csv_safe(p_path)
                manual_all.append(tmp_m)
            except: pass
    pos_df = pd.concat(manual_all) if manual_all else pd.DataFrame()

    if not journal.empty:
        accounts = list(journal['Account'].dropna().unique())
        st.write(f"Comptes identifiés dans le journal : `{', '.join(accounts)}`")

        # --- NEW: Report from Previous Year ---
        st.divider()
        with st.expander(f"📦 Report de l'année précédente ({target_year - 1})", expanded=False):
            st.info(f"Calcul des soldes au 31/12/{target_year - 1} pour initialiser l'année {target_year}.")
            prev_date = datetime(target_year - 1, 12, 31)

            # Use the same logic as VGP calculation but for the previous year-end
            journals_prev = []
            for y_p in range(2020, target_year):
                path_p = get_file_path(y_p, 'qualified')
                if os.path.exists(path_p):
                    try: journals_prev.append(pd_read_csv_safe(path_p))
                    except: pass

            if journals_prev:
                full_prev = pd.concat(journals_prev)
                full_prev = full_prev[full_prev["Asset"] != "EUR"]
                # Filter Spam/Dup
                if 'Status' in full_prev.columns: full_prev = full_prev[full_prev['Status'] != 'Spam']

                # Internal neutralization (simplified for report view)
                my_accs_prev = set(full_prev['Account'].dropna().unique())
                def is_neut_p(r):
                    if str(r.get('Category')) == "Transfert Interne": return True
                    if resolve_raw_addr(r.get('Counterparty', "")) in my_accs_prev: return True
                    return False

                # Sum of everything up to end of previous year
                eoy_prev_bals = full_prev.groupby(['Asset'])['Amount'].sum().reset_index()
                eoy_prev_bals = eoy_prev_bals[eoy_prev_bals['Amount'].abs() > 1e-8]

                if not eoy_prev_bals.empty:
                    st.write(f"**Soldes reportables au 01/01/{target_year} :**")
                    st.table(eoy_prev_bals)
                else:
                    st.write("Aucun solde à reporter.")
            else:
                st.write("Aucun historique trouvé avant cette année.")

        st.divider()
        st.subheader("📍 Positions de Fin d'Année")

        # 1. Chargement du référentiel Protocoles
        pos_labels = load_position_labels()
        protocol_addrs = set(pos_labels.keys())
        my_accounts = set(accounts)

        st.info("Ces positions servent à calculer la Valeur Globale du Portefeuille (VGP).")

        # 2. Factual Balance Calculation (Unified Snapshot)
        eoy_date = datetime(target_year, 12, 31)
        full_snapshot, _ = get_portfolio_snapshot(target_year, eoy_date)

        if full_snapshot.empty:
            st.warning("Aucun solde détecté pour cette année.")
            derived_local = pd.DataFrame()
            df_protocols = pd.DataFrame()
        else:
            # Map columns to match app3 legacy expectation
            # Snapshot returns: Location, Asset, Report, Entrées, Sorties, Solde, Prix (EUR), Valeur (EUR), Is_Circuit
            full_snapshot = full_snapshot.rename(columns={"Location": "Account", "Solde": "Amount", "Entrées": "In", "Sorties": "Out"})

        # Split Local vs Protocols vs Manual for UI legacy
        mask_wallet = full_snapshot["Account"].str.startswith("Account:", na=False)
        mask_manual = full_snapshot["Account"].str.startswith("Manual Position:", na=False)

        derived_local = full_snapshot[mask_wallet].copy()
        derived_local["Account"] = derived_local["Account"].str.replace("Account: ", "")

        df_manual_snap = full_snapshot[mask_manual].copy()
        df_manual_snap["Account"] = df_manual_snap["Account"].str.replace("Manual Position: ", "")

        df_protocols = full_snapshot[~mask_wallet & ~mask_manual].copy()

        # 4. Valorisation & Sanctuarisation
        col_v1, col_v2 = st.columns(2)
        if col_v1.button("🚀 Valoriser les Positions (Auto)", key="btn_valoriser"):
            with st.spinner("Recherche des prix..."):
                eoy_date = datetime(target_year, 12, 31)

                # Wallets
                unique_assets = set(derived_local["Asset"].unique())
                prices = {a: get_price_eur(a, eoy_date) for a in unique_assets}
                derived_local["Prix (EUR)"] = derived_local["Asset"].map(prices)
                derived_local["Valeur (EUR)"] = derived_local["Amount"] * derived_local["Prix (EUR)"]
                st.session_state.local_valued = derived_local

                # Protocoles
                if not df_protocols.empty:
                    unique_assets_proto = set(df_protocols["Asset"].unique())
                    prices_proto = {a: get_price_eur(a, eoy_date) for a in unique_assets_proto}
                    df_protocols["Prix (EUR)"] = df_protocols["Asset"].map(prices_proto)
                    df_protocols["Valeur (EUR)"] = df_protocols["Amount"] * df_protocols["Prix (EUR)"]
                    st.session_state.proto_valued = df_protocols

                # Positions Manuelles
                if not df_manual_snap.empty:
                    unique_assets_man = set(df_manual_snap["Asset"].unique())
                    prices_man = {a: get_price_eur(a, eoy_date) for a in unique_assets_man}
                    df_manual_snap["Prix (EUR)"] = df_manual_snap["Asset"].map(prices_man)
                    df_manual_snap["Valeur (EUR)"] = df_manual_snap["Amount"] * df_manual_snap["Prix (EUR)"]
                    st.session_state.manual_pos_valued = df_manual_snap

                st.success("Valorisation terminée.")

        if col_v2.button("💾 Sanctuariser les Prix", key="btn_sanctuariser_prix"):
            all_prices = {}
            if "local_valued" in st.session_state:
                df = st.session_state.local_valued
                for _, r in df.iterrows():
                    if r["Prix (EUR)"] > 0: all_prices[r["Asset"]] = float(r["Prix (EUR)"])
            if "proto_valued" in st.session_state:
                df = st.session_state.proto_valued
                for _, r in df.iterrows():
                    if r["Prix (EUR)"] > 0: all_prices[r["Asset"]] = float(r["Prix (EUR)"])
            if "manual_pos_valued" in st.session_state:
                df = st.session_state.manual_pos_valued
                for _, r in df.iterrows():
                    if r["Prix (EUR)"] > 0: all_prices[r["Asset"]] = float(r["Prix (EUR)"])

            if all_prices:
                if save_eoy_prices(target_year, all_prices):
                    st.success(f"✅ {len(all_prices)} prix sanctuarisés pour {target_year}.")
                else:
                    st.error("Erreur lors de la sauvegarde.")
            else:
                st.warning("Aucun prix à sauvegarder.")

        if "local_valued" in st.session_state:
            derived_local = st.session_state.local_valued

        if "proto_valued" in st.session_state and not df_protocols.empty:
            df_protocols = st.session_state.proto_valued

        # UI Affichage
        st.write("**📱 Portefeuilles (Local) :**")
        for col in derived_local.columns:
            if derived_local[col].dtype == object:
                derived_local[col] = derived_local[col].fillna("").astype(str)

        # UI Affichage avec mode édition pour les prix
        ed_local = st.data_editor(
            derived_local,
            column_config={
                "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                "Amount": st.column_config.NumberColumn("Solde Final", format="%.6f", disabled=True),
                "Report": st.column_config.NumberColumn("Report (Initial)", format="%.6f", disabled=True),
                "In": st.column_config.NumberColumn("Entrées (YTD)", format="%.6f", disabled=True),
                "Out": st.column_config.NumberColumn("Sorties (YTD)", format="%.6f", disabled=True),
                "Account": st.column_config.TextColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
                "Is_Circuit": st.column_config.CheckboxColumn("Circuit?", disabled=True),
            },
            use_container_width=True,
            key="local_pos_ed"
        )

        # Recalcul automatique des valeurs après édition manuelle des prix
        ed_local["Valeur (EUR)"] = ed_local["Amount"] * ed_local["Prix (EUR)"].fillna(0.0)
        st.session_state.local_valued = ed_local

        if (ed_local["Prix (EUR)"] == 0).any():
            st.warning("⚠️ Certains prix de portefeuilles locaux sont à 0.00.")

        if not df_protocols.empty:
            st.write("**🏦 Protocoles & Staking (Déporté) :**")
            for col in df_protocols.columns:
                if df_protocols[col].dtype == object:
                    df_protocols[col] = df_protocols[col].fillna("").astype(str)

            ed_proto = st.data_editor(
                df_protocols,
                column_config={
                    "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                    "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                    "Amount": st.column_config.NumberColumn("Solde Final", format="%.6f", disabled=True),
                    "Report": st.column_config.NumberColumn("Report (Initial)", format="%.6f", disabled=True),
                    "In": st.column_config.NumberColumn("Entrées (YTD)", format="%.6f", disabled=True),
                    "Out": st.column_config.NumberColumn("Sorties (YTD)", format="%.6f", disabled=True),
                    "Account": st.column_config.TextColumn(disabled=True),
                    "Asset": st.column_config.TextColumn(disabled=True),
                    "Is_Circuit": st.column_config.CheckboxColumn("Circuit?", disabled=True),
                },
                use_container_width=True,
                key="proto_pos_ed"
            )
            ed_proto["Valeur (EUR)"] = ed_proto["Amount"] * ed_proto["Prix (EUR)"].fillna(0.0)
            st.session_state.proto_valued = ed_proto
            if (ed_proto["Prix (EUR)"] == 0).any():
                st.warning("⚠️ Certains prix de protocoles sont à 0.00.")

        st.divider()
        st.write("**Positions déclarées manuellement (Off-chain, CEX, etc.) :**")
        if "manual_pos_valued" in st.session_state:
            df_manual_valued = st.session_state.manual_pos_valued
            for col in df_manual_valued.columns:
                if df_manual_valued[col].dtype == object: df_manual_valued[col] = df_manual_valued[col].fillna("").astype(str)

            ed_manual = st.data_editor(
                df_manual_valued,
                column_config={
                    "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                    "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                    "Amount": st.column_config.NumberColumn("Solde Final", format="%.6f", disabled=True),
                    "Report": st.column_config.NumberColumn("Report (Initial)", format="%.6f", disabled=True),
                    "In": st.column_config.NumberColumn("Entrées (YTD)", format="%.6f", disabled=True),
                    "Out": st.column_config.NumberColumn("Sorties (YTD)", format="%.6f", disabled=True),
                    "Asset": st.column_config.TextColumn(disabled=True),
                    "Account": st.column_config.TextColumn(disabled=True),
                },
                use_container_width=True,
                key="manual_pos_ed"
            )
            ed_manual["Valeur (EUR)"] = ed_manual["Amount"] * ed_manual["Prix (EUR)"].fillna(0.0)
            st.session_state.manual_pos_valued = ed_manual
        else:
            st.info("Aucune position manuelle valorisée.")

        # EXPORT CONSOLIDÉ CSV
        st.divider()
        col_ex1, col_ex2 = st.columns(2)

        with col_ex1:
            if st.button("📥 Préparer l'export consolidé (CSV)", use_container_width=True, key="btn_prepare_export"):
                frames = []
                if "local_valued" in st.session_state:
                    tmp = st.session_state.local_valued.copy()
                    tmp["Type"] = "Wallet"
                    frames.append(tmp)
                if "proto_valued" in st.session_state:
                    tmp = st.session_state.proto_valued.copy()
                    tmp["Type"] = "Protocol"
                    frames.append(tmp)
                if "manual_pos_valued" in st.session_state:
                    tmp = st.session_state.manual_pos_valued.copy()
                    tmp["Type"] = "Manual"
                    if "Quantité" in tmp.columns:
                        tmp = tmp.rename(columns={"Quantité": "Amount"})
                    frames.append(tmp)

                if frames:
                    full_snap = pd.concat(frames, ignore_index=True)
                    # Add unique accounts as a separate section
                    acc_df = pd.DataFrame({"Account": accounts, "Type": "Owner_Account_List", "Asset": "", "Amount": 0, "Prix (EUR)": 0, "Valeur (EUR)": 0})

                    # No reconciliation needed in factual mode
                    wealth_df = pd.DataFrame()

                    final_export_df = pd.concat([
                        acc_df,
                        pd.DataFrame([{"Account": "---", "Type": "SEPARATOR"}]),
                        full_snap,
                        pd.DataFrame([{"Account": "---", "Type": "SEPARATOR"}]),
                        pd.DataFrame([{"Account": "WEALTH_RECONCILIATION_REPORT", "Type": "HEADER"}]),
                        wealth_df
                    ], ignore_index=True)

                    st.session_state.full_inventory_csv = final_export_df.to_csv(index=False, encoding="utf-8-sig")
                    st.success("Export prêt.")

        with col_ex2:
            if "full_inventory_csv" in st.session_state:
                st.download_button(
                    label="💾 Télécharger l'inventaire complet (CSV)",
                    data=st.session_state.full_inventory_csv,
                    file_name=f"inventaire_fiscal_complet_{target_year}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="btn_download_export"
                )

with tab_acq:
    st.subheader("💵 Suivi du Prix d'Acquisition Global")
    st.write("Le prix d'acquisition est le total des montants en Euros investis pour acquérir des actifs numériques.")

    current_acq = calculate_acquisition_price(target_year)

    col_acq1, col_acq2 = st.columns(2)
    with col_acq1:
        hist_acq = st.number_input("Prix d'acquisition historique (années précédentes)", value=0.0, step=100.0, key="hist_acq_input")
        total_acq_price = current_acq + hist_acq
        st.session_state.total_acq_price_shared = total_acq_price
        st.metric("Prix d'acquisition Total (A)", f"{total_acq_price:,.2f} €")

    with col_acq2:
        st.info("Cette valeur 'A' est utilisée dans la formule de calcul de la plus-value brute.")

with tab_cessions:
    st.subheader("📝 Calcul des Cessions Imposables (Formulaire 2086)")
    journal = data['journal']

    if journal.empty:
        st.warning("Le journal qualifié est vide. Terminez l'étape 2 d'abord.")
    else:
        # On cherche les lignes marquées comme Imposable ou étant des retraits Fiat (Vente)
        # Mais on exclut formellement les lignes EUR (Fiat pur)
        def is_imposable_robust(val):
            s = str(val).upper().strip()
            return s in ["TRUE", "1", "1.0", "VRAI"]

        cessions = journal[
            (journal['Imposable'].apply(is_imposable_robust) |
             journal['Category'].fillna("").str.contains("Vente", case=False)) &
            (journal['Asset'] != 'EUR')
        ].copy()

        if cessions.empty:
            st.info("Aucune cession imposable détectée dans le journal.")
        else:
            st.write("Pour chaque cession, saisissez la **Valeur Globale du Portefeuille (VGP)** à la date de l'opération.")

            # On ajoute des colonnes pour le calcul fiscal
            # NEW: Tentative d'initialisation automatique via Value ($) et taux BCE
            if 'Prix de Cession (EUR)' not in cessions.columns or (cessions['Prix de Cession (EUR)'] == 0).all():
                def init_pc(row):
                    val_usd = float(row.get('Value ($)', 0))
                    if val_usd > 0:
                        rate = get_fiat_rate("USD", row['Date'])
                        return val_usd * rate
                    return 0.0
                cessions['Prix de Cession (EUR)'] = cessions.apply(init_pc, axis=1)

            # Récupération automatique de la VGP calculée dans app2VGP si elle existe
            if 'VGP (EUR)' not in cessions.columns:
                cessions['VGP (EUR)'] = 0.0
            else:
                cessions['VGP (EUR)'] = cessions['VGP (EUR)'].fillna(0.0)

            # Type safety
            for col in ["Account", "Counterparty", "Asset", "Tx Hash", "Category", "Status"]:
                if col in cessions.columns:
                    cessions[col] = cessions[col].fillna("").astype(str)

            edited_cessions = st.data_editor(
                cessions,
                column_config={
                    "VGP (EUR)": st.column_config.NumberColumn("VGP (EUR)", format="%.2f", required=True),
                    "Prix de Cession (EUR)": st.column_config.NumberColumn("Prix Cession (EUR)", format="%.2f"),
                    "Date": st.column_config.DatetimeColumn(disabled=True),
                    "Amount": st.column_config.NumberColumn(disabled=True),
                },
                use_container_width=True,
                key="cessions_ed"
            )

            if st.button("🧮 Calculer les Plus-Values", key="btn_calc_pv"):
                # Use centralized fiscal logic
                df_results, final_acq = calculate_fiscal_gains(edited_cessions, total_acq_price)

                if not df_results.empty:
                    st.session_state.bilan_fiscale = df_results
                    st.session_state.final_acq_remaining = final_acq
                    st.success("Calcul terminé. Voir l'onglet Bilan.")
                else:
                    st.warning("Aucune plus-value n'a pu être calculée. Vérifiez les valeurs VGP.")

with tab_bilan:
    st.subheader("📊 Bilan Annuel & Impôt Estimé")

    if "bilan_fiscale" in st.session_state and not st.session_state.bilan_fiscale.empty:
        df_bilan = st.session_state.bilan_fiscale
        st.table(df_bilan)

        total_pv = df_bilan['Plus-Value Brute'].sum()
        total_cessions = df_bilan['Prix Cession'].sum()

        col_b1, col_b2, col_b3 = st.columns(3)
        label_pv = "Plus-Value Totale Brute" if total_pv >= 0 else "Moins-Value Totale Brute"
        col_b1.metric(label_pv, f"{total_pv:,.2f} €", help="Somme des plus-values unitaires calculées par cession selon la formule du formulaire 2086.")

        # Logique fiscale : exonération si total des prix de cession <= abattement (305€)
        if total_pv > 0 and total_cessions <= abattement:
            pv_nette = 0.0
            st.warning(f"💡 Exonération appliquée : Le total des cessions ({total_cessions:.2f}€) est inférieur au seuil de {abattement}€.")
        else:
            pv_nette = total_pv

        label_nette = "Plus-Value Nette Imposable" if pv_nette >= 0 else "Moins-Value Nette Déclarant"
        col_b2.metric(label_nette, f"{pv_nette:,.2f} €", help="Plus-value brute après application de l'abattement annuel de 305€ si applicable (uniquement sur gains).")

        impot = pv_nette * flat_tax_rate if pv_nette > 0 else 0.0
        col_b3.metric(f"Impôt Estimé ({int(flat_tax_rate*100)}%)", f"{impot:,.2f} €", delta_color="inverse", help="Calculé selon le taux du Prélèvement Forfaitaire Unique (PFU) en vigueur.")

        # --- AJOUT INFOS COMPLÉMENTAIRES ---
        st.divider()
        c_inf1, c_inf2 = st.columns(2)

        # 1. Récupération du prix d'achat total (A)
        total_acq = st.session_state.get("total_acq_price_shared", 0.0)
        c_inf1.metric("Prix d'achat total (A)", f"{total_acq:,.2f} €", help="Capital investi (A) : Somme cumulée de vos apports fiat (Euros) dans l'écosystème crypto.")

        # 2. Calcul de la VGP consolidée au 31/12 (Calcul Réel)
        y_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        eoy_path = os.path.join(y_dir, f"inventory_EOY_{target_year}.csv")
        vgp_end = 0.0

        if os.path.exists(eoy_path):
            try:
                df_inv = pd_read_csv_safe(eoy_path)
                df_inv["Valeur (EUR)"] = pd.to_numeric(df_inv["Valeur (EUR)"], errors="coerce").fillna(0.0)
                vgp_end = df_inv["Valeur (EUR)"].sum()
                st.info(f"✅ VGP basée sur l'inventaire sanctuarisé au 31/12/{target_year}.")
            except: pass

        if vgp_end == 0:
            if f"vgp_eoy_{target_year}" in st.session_state:
                vgp_end = st.session_state[f"vgp_eoy_{target_year}"]

            if st.button(f"🧮 Calculer la VGP au 31/12/{target_year}", key="btn_calc_vgp_eoy"):
                with st.spinner("Calcul en cours..."):
                    # Use the shared logic to get a factual snapshot
                    eoy_date = datetime(target_year, 12, 31)
                    _, vgp_val = get_portfolio_snapshot(target_year, eoy_date)
                    st.session_state[f"vgp_eoy_{target_year}"] = vgp_val
                    st.success(f"VGP calculée : {vgp_val:,.2f} €")
                    st.rerun()

        c_inf2.metric(f"VGP consolidée (31/12/{target_year})", f"{vgp_end:,.2f} €", help="Valeur Globale du Portefeuille (VGP) au 31/12 : Somme factuelle des soldes par compte.")

        # --- NOUVEAU : SYNTHÈSE PERFORMANCE ---
        st.divider()
        st.subheader("📈 Synthèse de Performance & Gains")

        # 1. Plus-Value Réalisée (Déjà calculée dans le bilan fiscal)
        gain_realise = total_pv

        # 2. Plus-Value Non Réalisée (Latente)
        # Formule : VGP 31/12 - Capital Restant (Prix d'achat non encore utilisé pour des cessions)
        capital_restant = st.session_state.get("final_acq_remaining", total_acq)
        gain_latent = vgp_end - capital_restant

        # 3. Plus-Value Globale (Théorique)
        gain_global = gain_realise + gain_latent

        c_perf1, c_perf2, c_perf3 = st.columns(3)

        # Affichage pédagogique
        if gain_realise >= 0:
            c_perf1.success(f"**Gain Réalisé**\n\n{gain_realise:,.2f} €")
            c_perf1.caption("Gains effectifs suite à vos ventes de l'année.")
        else:
            c_perf1.warning(f"**Perte Réalisée**\n\n{gain_realise:,.2f} €")
            c_perf1.caption("Pertes effectives suite à vos ventes de l'année.")

        if gain_latent >= 0:
            c_perf2.info(f"**Gain Latent**\n\n{gain_latent:,.2f} €")
            c_perf2.caption("Plus-value potentielle si vous vendiez tout au 31/12.")
        else:
            c_perf2.error(f"**Perte Latente**\n\n{gain_latent:,.2f} €")
            c_perf2.caption("Perte potentielle sur vos actifs restants au 31/12.")

        if gain_global >= 0:
            c_perf3.metric("Plus-Value Globale", f"{gain_global:,.2f} €")
        else:
            c_perf3.metric("Perte Globale", f"{gain_global:,.2f} €", delta_color="inverse")

        st.info(f"💡 **Explication :** Votre performance globale ({gain_global:,.2f}€) combine les gains/pertes déjà 'encaissés' par vos ventes et la valeur actuelle de ce qu'il vous reste en portefeuille par rapport à ce qu'il vous a coûté ({capital_restant:,.2f}€ de capital restant).")

        st.divider()
        st.subheader("📥 Export de l'Historique Fiscal")
        st.write("Ce bouton génère un fichier CSV contenant l'intégralité des transactions (hors spams) utilisées pour la constitution de l'inventaire et le calcul des plus-values.")

        if st.button("📊 Préparer l'export Historique (Sans Spam)", use_container_width=True, key="btn_export_hist_fiscal"):
            # Aggregation logic (same as VGP/Portfolio but row-based)
            all_txs = []
            for y in range(2020, target_year + 1):
                path_j = get_file_path(y, 'qualified')
                if os.path.exists(path_j):
                    try:
                        df_y = pd_read_csv_safe(path_j)
                        # Standard exclusion filter
                        if 'Status' in df_y.columns:
                            df_y = df_y[df_y['Status'] != 'Spam']
                        if 'Category' in df_y.columns:
                            df_y = df_y[df_y['Category'] != 'Doublon à ignorer']
                        all_txs.append(df_y)
                    except: pass

            if all_txs:
                df_hist_full = pd.concat(all_txs, ignore_index=True)
                # Apply labels for audit clarity
                df_hist_full = apply_position_labels(df_hist_full)

                # Convert to CSV bytes
                csv_bytes = df_hist_full.to_csv(index=False, encoding="utf-8-sig")
                st.session_state.hist_fiscal_csv = csv_bytes
                st.success(f"Historique prêt ({len(df_hist_full)} lignes).")
            else:
                st.warning("Aucune transaction trouvée dans les journaux qualifiés.")

        if "hist_fiscal_csv" in st.session_state:
            st.download_button(
                label="💾 Télécharger l'historique complet (CSV)",
                data=st.session_state.hist_fiscal_csv,
                file_name=f"historique_fiscal_complet_{target_year}.csv",
                mime="text/csv",
                use_container_width=True,
                key="btn_download_hist_fiscal"
            )

        st.divider()
        if total_pv >= 0:
            st.write("📝 **Montant à reporter dans la case 3AN (Plus-value) :**")
        else:
            st.write("📝 **Montant à reporter dans la case 3BN (Moins-value) :**")
        st.code(f"{abs(round(total_pv))}")

        st.info("💡 N'oubliez pas de joindre l'annexe 2086 à votre déclaration de revenus.")

        # PDF Export for Fiscality (Full Report)
        def generate_fiscal_pdf_full(year, accounts, local_pos, proto_pos, manual_pos, fiat_df, bilan_df, total_pv, impot):
            import fpdf
            f_ver = getattr(fpdf, "__version__", "1.0")
            is_fpdf2 = int(f_ver.split(".")[0]) >= 2

            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.set_auto_page_break(auto=True, margin=15)

            # Unicode Font Registration
            font_path = "DejaVuSans.ttf"
            font_bold_path = "DejaVuSans-Bold.ttf"
            main_font = "helvetica"

            if os.path.exists(font_path) and os.path.exists(font_bold_path):
                try:
                    # On force l'utilisation des fichiers TTF
                    pdf.add_font("DejaVu", "", font_path)
                    pdf.add_font("DejaVu", "B", font_bold_path)
                    main_font = "DejaVu"
                except: pass

            # Gestion des glyphes manquants pour fpdf2
            if is_fpdf2 and main_font == "DejaVu":
                try: pdf.set_fallback_fonts(["DejaVu"])
                except: pass

            # --- Page 1: Comptes et Positions ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 18)
            pdf.cell(0, 15, f"RAPPORT FISCAL CRYPTO - {year}", ln=True, align='C')
            pdf.set_font(main_font, 'B', 14)
            pdf.cell(0, 10, "SECTION 1 : COMPTES & POSITIONS", ln=True)
            pdf.ln(5)

            pdf.set_font(main_font, 'B', 10)
            use_uni = (main_font == "DejaVu")
            acc_str = ", ".join([pdf_safe_str(a, use_uni) for a in accounts]) if accounts else "Aucun"
            pdf.multi_cell(0, 10, f"Comptes identifies : {acc_str}")
            pdf.ln(5)

            # Table Local Wallets
            pdf.set_font(main_font, 'B', 11)
            pdf.cell(0, 10, "Positions Portefeuilles (Local)", ln=True)
            pdf.set_fill_color(220, 220, 220)

            has_val = "Valeur (EUR)" in local_pos.columns
            cols_p = ["Account", "Asset", "Quantite", "Valeur EUR"] if has_val else ["Account", "Asset", "Quantite"]
            w_p = [100, 50, 55, 60] if has_val else [140, 60, 60]

            for i, c in enumerate(cols_p): pdf.cell(w_p[i], 8, c, border=1, fill=True)
            pdf.ln()
            pdf.set_font(main_font, '', 10)
            for _, r in local_pos.iterrows():
                pdf.cell(w_p[0], 8, pdf_safe_str(r["Account"], use_uni)[:45], border=1)
                pdf.cell(w_p[1], 8, pdf_safe_str(r["Asset"], use_uni), border=1)
                pdf.cell(w_p[2], 8, f"{r['Amount']:.6f}", border=1)
                if has_val:
                    pdf.cell(w_p[3], 8, f"{r.get('Valeur (EUR)', 0):,.2f} EUR", border=1)
                pdf.ln()
            pdf.ln(10)

            # Table Protocols
            if not proto_pos.empty:
                pdf.set_font(main_font, 'B', 11)
                pdf.cell(0, 10, "Positions Protocoles (Staking / Vaults)", ln=True)
                for i, c in enumerate(cols_p): pdf.cell(w_p[i], 8, c, border=1, fill=True)
                pdf.ln()
                pdf.set_font(main_font, '', 10)
                for _, r in proto_pos.iterrows():
                    # Calculer la hauteur nécessaire pour la ligne (basée sur Account)
                    # On utilise multi_cell en mode calcul si possible, sinon on estime
                    txt_acc = pdf_safe_str(r["Account"], use_uni)

                    # Approche robuste pour multi-colonne avec renvoi
                    y_start = pdf.get_y()
                    x_start = pdf.get_x()

                    if y_start > 180:
                        pdf.add_page()
                        y_start = pdf.get_y()
                        x_start = pdf.get_x()
                        pdf.set_font(main_font, 'B', 11)
                        for i, c in enumerate(cols_p): pdf.cell(w_p[i], 8, c, border=1, fill=True)
                        pdf.ln()
                        y_start = pdf.get_y()
                        pdf.set_font(main_font, '', 10)

                    # On dessine d'abord la cellule qui peut déborder pour obtenir la hauteur
                    pdf.multi_cell(w_p[0], 8, txt_acc, border=1)
                    h_row = pdf.get_y() - y_start

                    # On revient en haut pour dessiner les autres cellules avec la même hauteur
                    pdf.set_xy(x_start + w_p[0], y_start)
                    pdf.cell(w_p[1], h_row, pdf_safe_str(r["Asset"], use_uni), border=1)
                    pdf.cell(w_p[2], h_row, f"{r['Amount']:.6f}", border=1)
                    if has_val:
                        pdf.cell(w_p[3], h_row, f"{r.get('Valeur (EUR)', 0):,.2f} EUR", border=1)

                    pdf.set_y(y_start + h_row)
                pdf.ln(10)

            # --- Page 2: Prix d'Acquisition ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 14)
            pdf.cell(0, 10, "SECTION 2 : HISTORIQUE DES ACHATS (FIAT)", ln=True)
            pdf.ln(5)

            pdf.set_font(main_font, 'B', 10)
            # Adjusting widths to avoid overlap: Type needs more space, and total must fit A4 Landscape (~277mm usable)
            cols_f = ["Date", "Compte", "Asset", "Type", "Montant EUR", "Quantite"]
            w_f = [25, 45, 20, 85, 40, 40] # Total: 255mm
            for i, c in enumerate(cols_f): pdf.cell(w_f[i], 8, c, border=1, fill=True)
            pdf.ln()
            pdf.set_font(main_font, '', 9)
            for _, r in fiat_df.iterrows():
                try: ds_f = pd.to_datetime(r["Date"]).strftime("%d/%m/%Y")
                except: ds_f = "N/A"

                # Calcul de la hauteur maximale nécessaire pour la ligne
                # On vérifie Account et Type qui sont les plus susceptibles de déborder
                txt_acc = pdf_safe_str(r.get("Account", "Manual"), use_uni)
                txt_type = pdf_safe_str(r.get("Type", ""), use_uni)

                y_start = pdf.get_y()
                x_start = pdf.get_x()

                # Gestion du saut de page manuel si la hauteur estimée dépasse la page
                if y_start > 180: # Marge de sécurité pour le bas de page A4 Paysage
                    pdf.add_page()
                    y_start = pdf.get_y()
                    x_start = pdf.get_x()
                    # Répéter l'entête si nécessaire (optionnel mais recommandé pour la clarté)
                    pdf.set_font(main_font, 'B', 10)
                    for i, c in enumerate(cols_f): pdf.cell(w_f[i], 8, c, border=1, fill=True)
                    pdf.ln()
                    y_start = pdf.get_y()
                    pdf.set_font(main_font, '', 9)

                # On simule ou on trace pour obtenir les hauteurs
                # Colonne 1: Date (fixe)
                # Colonne 2: Compte (wrap)
                pdf.set_xy(x_start + w_f[0], y_start)
                pdf.multi_cell(w_f[1], 7, txt_acc, border=0) # On trace sans bordure d'abord pour mesurer
                h_acc = pdf.get_y() - y_start

                # Colonne 4: Type (wrap)
                pdf.set_xy(x_start + w_f[0] + w_f[1] + w_f[2], y_start)
                pdf.multi_cell(w_f[3], 7, txt_type, border=0)
                h_type = pdf.get_y() - y_start

                h_row = max(h_acc, h_type, 8)

                # Maintenant on trace la ligne réelle avec la hauteur unifiée
                pdf.set_xy(x_start, y_start)
                pdf.cell(w_f[0], h_row, ds_f, border=1)

                # Compte avec multi_cell et bordure manuelle si nécessaire ou juste multi_cell
                pdf.set_xy(x_start + w_f[0], y_start)
                pdf.multi_cell(w_f[1], 7, txt_acc, border=0)
                # Bordure rectangulaire pour la cellule multi_cell
                pdf.rect(x_start + w_f[0], y_start, w_f[1], h_row)

                pdf.set_xy(x_start + w_f[0] + w_f[1], y_start)
                pdf.cell(w_f[2], h_row, pdf_safe_str(r.get("Asset", "EUR"), use_uni), border=1)

                pdf.set_xy(x_start + w_f[0] + w_f[1] + w_f[2], y_start)
                pdf.multi_cell(w_f[3], 7, txt_type, border=0)
                pdf.rect(x_start + w_f[0] + w_f[1] + w_f[2], y_start, w_f[3], h_row)

                pdf.set_xy(x_start + w_f[0] + w_f[1] + w_f[2] + w_f[3], y_start)
                pdf.cell(w_f[4], h_row, f"{r.get('Montant EUR', 0):.2f} EUR", border=1)
                pdf.cell(w_f[5], h_row, f"{r.get('Quantité', 0):.6f}", border=1)

                pdf.set_y(y_start + h_row)

            # --- Page 3: Cessions ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 14)
            pdf.cell(0, 10, "SECTION 3 : DETAIL DES CESSIONS (FORMULAIRE 2086)", ln=True)
            pdf.ln(5)

            pdf.set_font(main_font, 'B', 9)
            cols_c = ["Date", "Asset", "Prix Cession", "VGP", "Abattement Acq", "PV Brute"]
            w_c = [40, 30, 50, 50, 50, 50]
            for i, c in enumerate(cols_c): pdf.cell(w_c[i], 8, c, border=1, fill=True)
            pdf.ln()
            pdf.set_font(main_font, '', 9)
            for _, row in bilan_df.iterrows():
                try: ds_c = pd.to_datetime(row["Date"]).strftime("%d/%m/%Y")
                except: ds_c = str(row["Date"])

                pdf.cell(w_c[0], 8, ds_c, border=1)
                pdf.cell(w_c[1], 8, pdf_safe_str(row["Asset"], use_uni), border=1)
                pdf.cell(w_c[2], 8, f"{row['Prix Cession']:.2f} EUR", border=1)
                pdf.cell(w_c[3], 8, f"{row['VGP']:.2f} EUR", border=1)
                pdf.cell(w_c[4], 8, f"{row['Abattement Acq']:.2f} EUR", border=1)
                pdf.cell(w_c[5], 8, f"{row['Plus-Value Brute']:.2f} EUR", border=1)
                pdf.ln()

            # --- Page 4: Bilan Final ---
            pdf.add_page()
            pdf.set_font(main_font, 'B', 16)
            pdf.cell(0, 15, "BILAN FISCAL RECAPITULATIF", ln=True, align='C')
            pdf.ln(10)

            pdf.set_font(main_font, 'B', 14)
            pdf.cell(100, 12, "PLUS-VALUE BRUTE TOTALE :", border=0)
            pdf.cell(0, 12, f"{total_pv:,.2f} EUR", border=0, ln=True, align='R')

            pdf.cell(100, 12, "IMPOT ESTIME (PFU 30%) :", border=0)
            pdf.cell(0, 12, f"{impot:,.2f} EUR", border=0, ln=True, align='R')

            pdf.ln(20)
            # If DejaVu is used, we only have Regular and Bold.
            # Style 'I' would require DejaVuSans-Oblique.ttf
            footer_style = 'I' if main_font == "helvetica" else ""
            pdf.set_font(main_font, footer_style, 10)
            pdf.multi_cell(0, 8, "Ce document est un assistant au calcul fiscal base sur les donnees fournies. Il appartient a l'utilisateur de verifier l'exactitude des montants reportes dans la declaration officielle.")

            # Extraction des bytes (Directement en mémoire pour éviter les erreurs de fichier/encodage sur Windows)
            return bytes(pdf.output())

        # Explicit trigger for PDF generation to ensure data is present
        if st.button("📊 Préparer le Rapport PDF Complet", use_container_width=True, key="btn_gen_pdf"):
            if df_bilan.empty:
                st.error("Le bilan est vide, impossible de générer le PDF.")
            else:
                # Clear stale cache
                if "fiscal_pdf_bytes" in st.session_state: del st.session_state.fiscal_pdf_bytes

                try:
                    final_bytes = generate_fiscal_pdf_full(
                        target_year, accounts, derived_local, df_protocols, pos_df, data['fiat'],
                        df_bilan, total_pv, impot
                    )
                    # Convert to bytes if it came as string/bytearray
                    if not isinstance(final_bytes, bytes):
                        final_bytes = bytes(final_bytes)

                    if len(final_bytes) > 1000:
                        st.session_state.fiscal_pdf_bytes = final_bytes
                        st.success(f"Rapport complet prêt ({len(final_bytes)} octets).")
                        st.rerun()
                    else:
                        st.error("Erreur : Le PDF généré est anormalement court.")
                except Exception as e:
                    st.error(f"Erreur de génération : {e}")
                    st.expander("Détails technique de l'erreur").code(traceback.format_exc())

        if "fiscal_pdf_bytes" in st.session_state:
            st.download_button(
                "📄 Télécharger le Rapport Fiscal PDF",
                data=st.session_state.fiscal_pdf_bytes,
                file_name=f"Rapport_Fiscal_{target_year}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    else:
        st.info("Réalisez le calcul dans l'onglet 'Cessions' pour voir le bilan.")

st.sidebar.divider()
st.sidebar.caption("Fiscalité v1.0 - app3")
