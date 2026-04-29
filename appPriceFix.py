import os
import json
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import unicodedata
from shared_logic import get_price_eur
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Explorateur de Prix (appPriceFix)", layout="wide")
st.title("🔍 Explorateur & Collecteur de Prix")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"
SPAM_FILE = "spam_blacklist.json"

# --- Helpers ---
def load_spam_list():
    if os.path.exists(SPAM_FILE):
        try:
            with open(SPAM_FILE, "r", encoding="utf-8", errors="replace") as f:
                return set(json.load(f))
        except: return set()
    return set()

def load_price_cache():
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4)

def pd_read_csv_safe(path):
    try: return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try: return pd.read_csv(path, encoding="latin-1")
        except: return pd.read_csv(path, encoding="utf-8", errors="replace")


# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres de Scan")

    # Discovery of available years
    available_years = sorted([y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))], reverse=True)
    if not available_years: available_years = [str(datetime.now().year)]

    selected_years = st.multiselect("Années à traiter", options=available_years, default=available_years, help="Sélectionnez une ou plusieurs années pour limiter le scan.")

    exclude_spam = st.checkbox("🛡️ Exclure les Spams (Statut App 2)", value=True, help="Ignore les assets et dates liés uniquement à des transactions marquées comme Spam dans le journal qualifié.")

    st.divider()
    show_status()

# --- Scanner ---
def load_all_verified_prices():
    """Loads prices from both global cache and all annual sanctuarised files."""
    combined = load_price_cache()
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"verified_prices_{y}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        combined.update(json.load(f))
                except: pass
    return combined

def scan_needed_prices(target_years, exclude_spams=True):
    all_needed = [] # List of dicts: {'Year', 'Asset', 'Date', 'Type'}
    spam_list = load_spam_list() if exclude_spams else set()

    for y in target_years:
        y_int = int(y)
        # 1. Cession dates
        qual_path = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
        if os.path.exists(qual_path):
            df = pd_read_csv_safe(qual_path)
            if not df.empty:
                # Filtrage Spam si demandé
                if exclude_spams and "Status" in df.columns:
                    df = df[df["Status"] != "Spam"]

                df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
                # Identify cessions
                def is_imp(v): return str(v).upper().strip() in ["TRUE", "1", "1.0", "VRAI"]
                mask = (df["Imposable"].apply(is_imp)) | (df["Category"].fillna("").str.contains("Vente", case=False))
                cessions = df[mask & (df["Asset"] != "EUR")]
                for _, row in cessions.iterrows():
                    all_needed.append({
                        "Year": y_int, "Asset": str(row["Asset"]), "Date": row["Date"].date(), "Type": "Cession"
                    })

        # 2. End of year
        # Find all unique assets ever held in this year
        assets_in_year = set()
        y_dir = os.path.join(EXPORT_BASE_DIR, y)

        # We prioritize assets from the qualified journal if it exists,
        # as it contains the spam status.
        qual_path = os.path.join(y_dir, f"qualified_journal_{y}.csv")
        assets_from_qual = set()
        if os.path.exists(qual_path):
            df_q = pd_read_csv_safe(qual_path)
            if not df_q.empty:
                if exclude_spams and "Status" in df_q.columns:
                    df_q = df_q[df_q["Status"] != "Spam"]
                assets_from_qual = set(df_q["Asset"].dropna().unique())
                assets_in_year.update(assets_from_qual)

        # Complement with other files ONLY IF we want to be exhaustive
        # OR if the qualified journal doesn't exist yet for that year.
        # But we filter them against the global spam list if exclude_spams is active.
        for f in os.listdir(y_dir):
            if f.endswith(".csv") and not f.startswith("qualified_"):
                try:
                    tmp = pd_read_csv_safe(os.path.join(y_dir, f))
                    found = set()
                    if "Asset" in tmp.columns: found.update(tmp["Asset"].dropna().unique())
                    if "Token" in tmp.columns: found.update(tmp["Token"].dropna().unique())

                    for a in found:
                        a_str = str(a).upper().strip()
                        if exclude_spams:
                            # 1. Global Blacklist check
                            if a_str.lower() in spam_list: continue

                            # 2. Local Veto check: if a qualified journal exists and this asset
                            # is NOT in the non-spam assets, it means it's either spam
                            # or wasn't qualified (spam by default in some views).
                            if os.path.exists(qual_path) and a not in assets_from_qual:
                                continue

                        assets_in_year.add(a)
                except: pass

        eoy_date = datetime(y_int, 12, 31).date()
        for a in assets_in_year:
            if str(a) != "EUR" and str(a) != "nan":
                all_needed.append({
                    "Year": y_int, "Asset": str(a), "Date": eoy_date, "Type": "Fin d'année"
                })

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

if st.button("🚀 Scanner les besoins (Cessions & Fins d'années)", use_container_width=True):
    with st.spinner("Analyse des fichiers sanctuarisés..."):
        df_needed = scan_needed_prices(target_years=selected_years, exclude_spams=exclude_spam)
        cache = load_all_verified_prices()

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

        st.session_state.price_explorer_df = pd.DataFrame(results).sort_values(["Status", "Date"], ascending=[True, False])

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
        use_container_width=True,
        num_rows="dynamic",
        key="price_fix_editor"
    )

    st.download_button(
        "📥 Exporter ce tableau de collecte (Audit)",
        ed_prices.to_csv(index=False, encoding="utf-8-sig"),
        "collecte_prix_audit.csv",
        "text/csv",
        use_container_width=True
    )

    col_btn1, col_btn2 = st.columns(2)

    if col_btn1.button("🤖 Collecte Automatique (Manquants)", use_container_width=True, type="primary"):
        to_fetch = ed_prices[ed_prices["Prix (EUR)"] == 0]
        if to_fetch.empty:
            st.success("Aucun prix manquant à collecter.")
        else:
            pbar = st.progress(0)
            cache = load_price_cache()
            updated_count = 0
            fail_count = 0

            for idx, (i, row) in enumerate(to_fetch.iterrows()):
                dt_obj = datetime.combine(row["Date"], datetime.min.time())
                new_price = get_price_eur(row["Asset"], dt_obj)

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

    if col_btn2.button("🛡️ Sanctuariser (Global & Annuel)", use_container_width=True):
        cache = load_price_cache()
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
        save_price_cache(cache)

        # Save Annuals
        for y, prices in annual_updates.items():
            y_dir = os.path.join(EXPORT_BASE_DIR, y)
            os.makedirs(y_dir, exist_ok=True)
            path = os.path.join(y_dir, f"verified_prices_{y}.json")

            # Merge with existing if any
            existing = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f: existing = json.load(f)
                except: pass
            existing.update(prices)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=4)

        st.balloons()
        st.success(f"✅ {count} prix sanctuarisés (Cache Global + Fichiers Annuels).")

st.sidebar.divider()
st.sidebar.caption("Price Collector v1.0 - appPriceFix")
