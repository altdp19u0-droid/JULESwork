import os
import json
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import unicodedata
import shared_logic as sl

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Price Fix (appPriceFix)", layout="wide")

st.title("🔍 Explorateur & Collecteur de Prix")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"
SPAM_FILE = "spam_blacklist.json"

# --- Helpers ---

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres de Scan")

    # Discovery of available years
    available_years = sorted([y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))], reverse=True)
    if not available_years: available_years = [str(datetime.now().year)]

    g_conf = sl.load_global_config()
    default_year = str(g_conf.get("processing_year") or datetime.now().year)

    # Pre-select the processing year if available
    default_selection = [default_year] if default_year in available_years else available_years

    selected_years = st.multiselect("Années à traiter", options=available_years, default=default_selection, help="Sélectionnez une ou plusieurs années pour limiter le scan.")

    exclude_spam = st.checkbox("🛡️ Exclure les Spams (Statut App 2)", value=True, help="Ignore les assets et dates liés uniquement à des transactions marquées comme Spam dans le journal qualifié.")

    # --- DOUBLE VÉRIFICATION SPAM À L'OUVERTURE ---
    if exclude_spam:
        total_leaked = 0
        for y in selected_years:
            q_path = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
            if os.path.exists(q_path):
                try:
                    df_q = sl.pd_read_csv_safe(q_path)
                    leaked = sl.validate_spam_exclusion(df_q)
                    if leaked: total_leaked += len(leaked)
                except: pass
        if total_leaked > 0:
            st.sidebar.warning(f"🛡️ {total_leaked} lignes suspectes détectées via Blacklist. Elles seront ignorées du scan.")

    st.divider()
    sl.show_status()

# --- Scanner ---
def scan_needed_prices(target_years, exclude_spams=True):
    all_needed = [] # List of dicts: {'Year', 'Asset', 'Date', 'Type'}

    for y in target_years:
        y_int = int(y)
        y_dir = os.path.join(EXPORT_BASE_DIR, y)
        if not os.path.exists(y_dir): continue

        assets_in_year = set()

        # 1. Scan CLEAN Journal for Cessions and Assets
        # GATEWAY: Prefer CLEAN journal for scanning needs
        clean_path = sl.get_file_path(y_int, 'qualified_clean')
        qual_path = sl.get_file_path(y_int, 'qualified')

        path_to_scan = None
        if clean_path and os.path.exists(clean_path): path_to_scan = clean_path
        elif qual_path and os.path.exists(qual_path): path_to_scan = qual_path

        if path_to_scan:
            df_q = sl.pd_read_csv_safe(path_to_scan)
            if not df_q.empty:
                # --- ZÉRO SPAM ---
                # Only filter if not already CLEAN
                if exclude_spams and "CLEAN" not in path_to_scan:
                    df_q = sl.apply_spam_filter(df_q, drop=True)

                df_q["Date"] = pd.to_datetime(df_q["Date"], utc=True, errors="coerce")

                # Identify assets held
                assets_in_year.update(df_q["Asset"].dropna().unique())

                # Identify cessions
                mask_cess = (df_q["Imposable"].apply(sl.is_imposable_robust)) | (df_q["Category"].fillna("").str.contains("Vente", case=False))
                cessions = df_q[mask_cess & (df_q["Asset"] != "EUR")]
                for _, row in cessions.iterrows():
                    all_needed.append({
                        "Year": y_int, "Asset": str(row["Asset"]), "Date": row["Date"].date(), "Type": "Cession"
                    })

        # 2. Scan Manual Positions for Assets
        pos_path = sl.get_file_path(y_int, 'positions')
        if os.path.exists(pos_path):
            df_p = sl.pd_read_csv_safe(pos_path)
            if not df_p.empty:
                # Manual positions don't usually have spam, but we check anyway if requested
                if exclude_spams:
                    df_p = sl.apply_spam_filter(df_p, drop=True)
                assets_in_year.update(df_p["Asset"].dropna().unique())

        # 3. Scan Previous Year Inventory (EOY Carryover)
        prev_year = y_int - 1
        inv_path = sl.get_file_path(prev_year, 'inventory_eoy')
        if os.path.exists(inv_path):
            df_inv = sl.pd_read_csv_safe(inv_path)
            if not df_inv.empty and "Asset" in df_inv.columns:
                # Assets carried over from previous year need an EOY price for current year
                assets_in_year.update(df_inv["Asset"].dropna().unique())

        # 4. Handle End of Year (31/12) for all identified assets
        eoy_date = datetime(y_int, 12, 31).date()
        for a in assets_in_year:
            a_str = str(a).upper().strip()
            if a_str not in ["EUR", "NAN", "NONE", ""]:
                all_needed.append({
                    "Year": y_int, "Asset": a_str, "Date": eoy_date, "Type": "Fin d'année"
                })

    if not all_needed: return pd.DataFrame()
    df_needed = pd.DataFrame(all_needed).drop_duplicates(subset=["Asset", "Date"])
    return df_needed

# --- Logic ---
st.subheader("📋 État de la collecte des prix")

# Alerte de conformité
st.warning("""
**⚠️ Règle d'Intégrité Strict :** Les calculs de VGP et de fiscalité n'autorisent aucune valeur de repli (approximation).
Tout prix affiché à **0.000000** bloquera la validation de l'année concernée.
Vous devez soit obtenir le prix via le bouton **Collecte Automatique**, soit le **saisir manuellement** dans le tableau ci-dessous.
""")

if st.button("🚀 Scanner les besoins (Cessions & Fins d'années)", width='stretch'):
    with st.spinner("Analyse des fichiers sanctuarisés..."):
        df_needed = scan_needed_prices(target_years=selected_years, exclude_spams=exclude_spam)
        cache = sl.load_price_cache() # Use centralized logic

        results = []
        for _, row in df_needed.iterrows():
            a_clean = unicodedata.normalize('NFKC', str(row["Asset"])).upper().strip()
            d_str = row["Date"].strftime("%d-%m-%Y")
            cache_key = f"{a_clean}_{d_str}"

            price = float(cache.get(cache_key, 0.0))
            results.append({
                "Année": row["Year"],
                "Asset": row["Asset"],
                "Date": row["Date"],
                "Type": row["Type"],
                "Prix (EUR)": price,
                "Status": "✅ OK" if price > 0 else "❌ Manquant"
            })

        if results:
            df_res = pd.DataFrame(results)
            st.session_state.price_explorer_df = df_res.sort_values(["Status", "Date"], ascending=[True, False])
        else:
            st.session_state.price_explorer_df = pd.DataFrame(columns=["Année", "Asset", "Date", "Type", "Prix (EUR)", "Status"])
            st.info("✨ Aucun besoin de prix détecté pour les critères sélectionnés.")

if "price_explorer_df" in st.session_state:
    df = st.session_state.price_explorer_df

    # Pre-calculate normalization for check
    nuance_map = {
        "\ua4f4": "U", "\ua4e2": "S", "\ua4d3": "D", "\ua4c1": "G", "\ua4c3": "H",
        "\u0421": "C", "\u0405": "S", "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T", "\u0425": "X",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u216d": "C", "\u2160": "I", "\u2164": "V", "\u2169": "X", "\u216c": "L", "\u216f": "M",
    }

    def normalize_asset(a):
        s = str(a)
        for k, v in nuance_map.items(): s = s.replace(k, v)
        return unicodedata.normalize('NFKC', s).upper().strip()

    col_t1, col_t2, col_t3 = st.columns([2, 1, 1])
    col_t1.write(f"Nombre de prix identifiés : **{len(df)}**")

    missing_count = len(df[df["Prix (EUR)"] == 0])
    col_t2.metric("Prix manquants", missing_count, delta=-missing_count if missing_count == 0 else missing_count, delta_color="inverse")

    # Indicateur de blocage
    if missing_count > 0:
        col_t3.error("🚨 Intervention Requise")
    else:
        col_t3.success("✨ Prêt pour VGP")

    st.info("💡 **Instructions :** 1. Cliquez sur 'Collecte Automatique'. 2. Saisissez manuellement les prix restant à 0 (⚠️). 3. Cliquez sur 'Sanctuariser'.")

    # Data Editor
    ed_prices = st.data_editor(
        df,
        column_config={
            "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.6f €"),
            "Date": st.column_config.DateColumn(disabled=True),
            "Asset": st.column_config.TextColumn(disabled=True),
            "Année": st.column_config.TextColumn(disabled=True),
            "Type": st.column_config.TextColumn(disabled=True),
            "Status": st.column_config.TextColumn(disabled=True),
        },
        width='stretch',
        num_rows="dynamic",
        key="price_fix_editor"
    )

    st.download_button(
        "📥 Exporter ce tableau de collecte (Audit)",
        ed_prices.to_csv(index=False, encoding="utf-8-sig"),
        "collecte_prix_audit.csv",
        "text/csv",
        width='stretch'
    )

    col_btn1, col_btn2 = st.columns(2)

    if col_btn1.button("🤖 Collecte Automatique (Manquants)", width='stretch', type="primary"):
        to_fetch = ed_prices[ed_prices["Prix (EUR)"] == 0]
        if to_fetch.empty:
            st.success("Aucun prix manquant à collecter.")
        else:
            pbar = st.progress(0)
            cache = sl.load_price_cache()
            updated_count = 0
            fail_count = 0

            for idx, (i, row) in enumerate(to_fetch.iterrows()):
                dt_obj = datetime.combine(row["Date"], datetime.min.time())
                new_price = sl.get_price_eur(row["Asset"], dt_obj)

                if new_price > 0:
                    ed_prices.at[i, "Prix (EUR)"] = new_price
                    ed_prices.at[i, "Status"] = "✅ Récupéré"
                    updated_count += 1
                else:
                    ed_prices.at[i, "Status"] = "🚨 ÉCHEC (Saisie Manuelle Obligatoire)"
                    fail_count += 1

                pbar.progress((idx + 1) / len(to_fetch))

            st.session_state.price_explorer_df = ed_prices
            if fail_count > 0:
                st.error(f"Collecte partielle : {updated_count} récupérés, {fail_count} restants à saisir manuellement.")
            else:
                st.success(f"Collecte terminée : {updated_count} prix récupérés.")
            st.rerun()

    if col_btn2.button("🛡️ Sanctuariser (Global & Annuel)", width='stretch'):
        cache = sl.load_price_cache()
        annual_updates = {} # {year: {key: val}}

        count = 0
        for _, r in ed_prices.iterrows():
            if r["Prix (EUR)"] > 0:
                y = str(r["Date"].year)
                a_clean = normalize_asset(r["Asset"])
                d_str = r["Date"].strftime("%d-%m-%Y")
                key = f"{a_clean}_{d_str}"
                val = float(r["Prix (EUR)"])

                # Update Global Cache
                cache[key] = val

                # Prepare Annual Sanctuarisation
                if y not in annual_updates: annual_updates[y] = {}
                annual_updates[y][key] = val
                count += 1

        # Save Global
        sl.save_price_cache(cache)

        # Save Annuals
        for y, prices in annual_updates.items():
            y_dir = os.path.join(EXPORT_BASE_DIR, y)
            os.makedirs(y_dir, exist_ok=True)
            s_dir = os.path.join(y_dir, "sanctuary"); os.makedirs(s_dir, exist_ok=True)

            path = os.path.join(y_dir, f"verified_prices_{y}.json")
            s_path = os.path.join(s_dir, f"verified_prices_{y}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

            # Merge with existing if any
            existing = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f: existing = json.load(f)
                except: pass
            existing.update(prices)

            # 1. Working copy
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=4)

            # 2. Sanctuary copy (permanent record)
            with open(s_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=4)

        st.balloons()
        st.success(f"✅ {count} prix sanctuarisés (Cache Global + Fichiers Annuels).")

st.sidebar.divider()
st.sidebar.caption("Price Collector v1.0 - appPriceFix")
