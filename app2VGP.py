import os
import time
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import unicodedata
from shared_logic import resolve_raw_addr

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Calcul VGP Pro (app2VGP)", layout="wide")
st.title("🧮 Calculateur de VGP Historique (Version Pro)")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"
POSITIONS_FILE = "position_labels.json"

# --- Cache Engine ---
def load_price_cache():
    """Loads prices from both global cache and all annual sanctuarised files."""
    combined = {}
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8", errors="replace") as f:
                combined = json.load(f)
        except: pass

    # Merge with annual verified prices
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

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

    parts = s.split()
    for p in parts:
        if p.startswith("0x") and len(p) >= 40: return p
    return s


def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

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

def get_qualified_path(year):
    return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")

def get_fiat_rate(from_currency, date_obj):
    """Fetches official BCE exchange rates via Frankfurter API."""
    from_currency = from_currency.upper().strip()
    if from_currency == "EUR": return 1.0
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from={from_currency}&to=EUR"
        res = requests.get(url, timeout=5).json()
        return float(res["rates"]["EUR"])
    except:
        return 0.0

def get_price_eur(asset, date_obj):
    # CRUCIAL: On normalise pour l'API tout en gardant l'original pour l'affichage UI
    nuance_map = {
        "\ua4f4": "U", "\ua4e2": "S", "\ua4d3": "D", "\ua4c1": "G", "\ua4c3": "H",
        "\u0421": "C", "\u0405": "S", "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T", "\u0425": "X",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u216d": "C", "\u2160": "I", "\u2164": "V", "\u2169": "X", "\u216c": "L", "\u216f": "M",
    }
    asset_clean = str(asset)
    for k, v in nuance_map.items():
        asset_clean = asset_clean.replace(k, v)
    asset_clean = unicodedata.normalize('NFKC', asset_clean).upper().strip()

    # 1. Stables & Direct Mappings (BCE Forex Data)
    if asset_clean in ["EUR", "EURA", "AGEUR", "STEUR", "EURC"]:
        return 1.0

    if asset_clean in ["USD", "USDC", "USDT", "DAI", "USDC.E", "STUSD", "SUSDS", "TWCOMPOUNDUSDC"]:
        return get_fiat_rate("USD", date_obj)

    if asset_clean == "ZCHF":
        return get_fiat_rate("CHF", date_obj)

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = load_price_cache()
    cache_key = f"{asset_clean}_{d_str}"

    if cache_key in cache:
        return float(cache[cache_key])

    # 2. CoinGecko Mapping
    asset_map = {
        "ETH": "ethereum", "BTC": "bitcoin", "POL": "polygon-ecosystem-token",
        "BNB": "binancecoin", "ARB": "arbitrum", "OP": "optimism", "WETH": "ethereum",
        "SOL": "solana", "MATIC": "matic-network", "AVAX": "avalanche-2", "DOT": "polkadot",
        "LINK": "chainlink", "UNI": "uniswap", "AAVE": "aave", "DAI": "dai",
        "ZCHF": "cryptofranc", "BCH": "bitcoin-cash", "HBAR": "hedera-hashgraph",
        "TWT": "trust-wallet-token", "ME": "magic-eden", "ORDER": "orderly-network",
        "IP": "story-ip", "AUNT": "auntie-whale"
    }

    cg_id = asset_map.get(asset_clean, asset_clean.lower())
    url_cg = f"https://api.coingecko.com/api/v3/coins/{cg_id}/history?date={d_str}&localization=false"

    try:
        time.sleep(1.2)
        res = requests.get(url_cg, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "market_data" in data:
                price = float(data["market_data"]["current_price"]["eur"])
                cache[cache_key] = price
                save_price_cache(cache)
                return price
    except: pass

    # 3. Fallback DefiLlama
    try:
        ts = int(date_obj.timestamp())
        url_llama = f"https://coins.llama.fi/prices/historical/{ts}/coingecko:{cg_id}?searchWidth=12h"
        res = requests.get(url_llama, timeout=10)
        if res.status_code == 200:
            coins = res.json().get("coins", {})
            if coins:
                price_usd = float(next(iter(coins.values()))["price"])
                rate = get_fiat_rate("USD", date_obj)
                price = price_usd * rate
                cache[cache_key] = price
                save_price_cache(cache)
                return price
    except: pass

    return 0.0

def get_portfolio_snapshot(journal, target_date):
    """
    Factual Account-based calculation of VGP.
    Strictly follows: Starting Balance + Period Entries - Period Exits = Final Balance.
    """
    pos_labels = load_position_labels()
    target_year = target_date.year
    start_of_year = datetime(target_year, 1, 1, tzinfo=target_date.tzinfo)

    # 1. Load History (2020 -> target_date)
    journals_all = []
    manual_all = []
    for y in range(2020, target_year + 1):
        path_j = get_qualified_path(y)
        if os.path.exists(path_j):
            try:
                df_y = pd_read_csv_safe(path_j)
                df_y["Date"] = pd.to_datetime(df_y["Date"], utc=True, errors="coerce")
                journals_all.append(df_y[df_y["Date"] <= target_date])
            except: pass

        path_m = os.path.join(EXPORT_BASE_DIR, str(y), f"manual_positions_{y}.csv")
        if os.path.exists(path_m):
            try:
                tmp_m = pd_read_csv_safe(path_m)
                tmp_m["Date"] = pd.to_datetime(tmp_m["Date"], utc=True, errors="coerce")
                manual_all.append(tmp_m[tmp_m["Date"] <= target_date])
            except: pass

    if not journals_all and not manual_all: return pd.DataFrame(), 0.0

    df_j = pd.concat(journals_all) if journals_all else pd.DataFrame()
    df_m = pd.concat(manual_all) if manual_all else pd.DataFrame()

    # Filtering Spam/Duplicates/EUR
    if not df_j.empty:
        df_j = df_j[(df_j["Status"] != "Spam") & (df_j.get("Category", "") != "Doublon à ignorer") & (df_j["Asset"] != "EUR")]
    if not df_m.empty:
        df_m = df_m[df_m["Asset"] != "EUR"]

    # 2. Pricing
    all_assets = set()
    if not df_j.empty: all_assets.update(df_j["Asset"].unique())
    if not df_m.empty: all_assets.update(df_m["Asset"].unique())
    asset_prices = {a: get_price_eur(a, target_date) for a in all_assets}

    details = []
    owned_accs = set(df_j["Account"].dropna().unique()) if not df_j.empty else set()

    # --- A. OWNED ACCOUNTS ---
    if not df_j.empty:
        # Breakdown into Reported (pre-year) and Period (YTD)
        # 1. Reported
        df_pre = df_j[df_j["Date"] < start_of_year]
        pre_bals = df_pre.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

        # 2. Period
        df_ytd = df_j[df_j["Date"] >= start_of_year]
        ytd_stats = df_ytd.groupby(["Account", "Asset"])["Amount"].agg([
            ('In', lambda s: s[s > 0].sum()),
            ('Out', lambda s: s[s < 0].sum())
        ]).reset_index()

        # Merge for final view
        merged = pd.merge(pre_bals, ytd_stats, on=["Account", "Asset"], how="outer").fillna(0.0)
        # Rename 'Amount' to 'Reported' for clarity
        merged = merged.rename(columns={"Amount": "Reported"})
        merged["Final_Bal"] = merged["Reported"] + merged["In"] + merged["Out"]

        for _, r in merged.iterrows():
            if abs(r["Final_Bal"]) > 1e-8:
                p = asset_prices.get(r["Asset"], 0.0)
                details.append({
                    "Location": f"Account: {r['Account']}", "Asset": r["Asset"],
                    "Report": r["Reported"], "Entrées": r["In"], "Sorties": abs(r["Out"]),
                    "Solde": r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": r["Final_Bal"] * p
                })

    # --- B. INTERNAL TRANSFER OFFSET LEGS ---
    if not df_j.empty:
        mask_int = (df_j["Category"] == "Transfert Interne")
        df_ext = df_j[mask_int].copy()
        df_ext["cp_low"] = df_ext["Counterparty"].apply(resolve_raw_addr)
        df_ext = df_ext[~df_ext["cp_low"].isin(owned_accs)]

        if not df_ext.empty:
            df_ext_pre = df_ext[df_ext["Date"] < start_of_year]
            ext_pre = df_ext_pre.groupby(["Counterparty", "Asset"])["Amount"].sum().reset_index()

            df_ext_ytd = df_ext[df_ext["Date"] >= start_of_year]
            ext_ytd = df_ext_ytd.groupby(["Counterparty", "Asset"])["Amount"].agg([
                ('In', lambda s: s[s < 0].sum()), # negative for us = in for them
                ('Out', lambda s: s[s > 0].sum()) # positive for us = out for them
            ]).reset_index()

            merged_ext = pd.merge(ext_pre, ext_ytd, on=["Counterparty", "Asset"], how="outer").fillna(0.0)
            merged_ext = merged_ext.rename(columns={"Amount": "Reported"})
            merged_ext["Final_Bal"] = merged_ext["Reported"] + merged_ext["In"] + merged_ext["Out"]

            for _, r in merged_ext.iterrows():
                if abs(r["Final_Bal"]) > 1e-8:
                    raw_cp = resolve_raw_addr(r["Counterparty"])
                    label = pos_labels.get(raw_cp, f"External/CEX: {r['Counterparty']}")
                    p = asset_prices.get(r["Asset"], 0.0)
                    # For them, signs are inverted
                    details.append({
                        "Location": label, "Asset": r["Asset"],
                        "Report": -r["Reported"], "Entrées": abs(r["In"]), "Sorties": abs(r["Out"]),
                        "Solde": -r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": (-r["Final_Bal"]) * p
                    })

    # --- C. MANUAL POSITIONS ---
    if not df_m.empty:
        df_m_pre = df_m[df_m["Date"] < start_of_year]
        m_pre = df_m_pre.groupby(["Account", "Asset"])["Quantité"].sum().reset_index()

        df_m_ytd = df_m[df_m["Date"] >= start_of_year]
        m_ytd = df_m_ytd.groupby(["Account", "Asset"])["Quantité"].agg([
            ('In', lambda s: s[s > 0].sum()),
            ('Out', lambda s: s[s < 0].sum())
        ]).reset_index()

        merged_m = pd.merge(m_pre, m_ytd, on=["Account", "Asset"], how="outer").fillna(0.0)
        merged_m = merged_m.rename(columns={"Quantité": "Reported"})
        merged_m["Final_Bal"] = merged_m["Reported"] + merged_m["In"] + merged_m["Out"]

        for _, r in merged_m.iterrows():
            if abs(r["Final_Bal"]) > 1e-8:
                p = asset_prices.get(r["Asset"], 0.0)
                details.append({
                    "Location": f"Manual Position: {r['Account']}", "Asset": r["Asset"],
                    "Report": r["Reported"], "Entrées": r["In"], "Sorties": abs(r["Out"]),
                    "Solde": r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": r["Final_Bal"] * p
                })

    full_details = pd.DataFrame(details)
    total_vgp = full_details["Valeur (EUR)"].sum() if not full_details.empty else 0.0

    return full_details, total_vgp

def is_imposable_robust(val):
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI"]

# --- UI sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année à traiter", min_value=2015, max_value=2030, value=datetime.now().year)

    # Year switch detection
    if "last_vgp_year" not in st.session_state:
        st.session_state.last_vgp_year = target_year

    if target_year != st.session_state.last_vgp_year:
        if "journal_active" in st.session_state: del st.session_state.journal_active
        if "active_path" in st.session_state: del st.session_state.active_path
        st.session_state.last_vgp_year = target_year
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.subheader("🔍 Critères de détection")
    use_imposable_col = st.checkbox("Basé sur 'Imposable'", value=True, help="Détecte les lignes marquées explicitement comme imposables dans l'App 2")
    use_category_vente = st.checkbox("Basé sur 'Vente'", value=True, help="Détecte les lignes dont la catégorie contient 'Vente'")

    st.divider()
    st.info("💡 **Mode Incrémental** : Le calcul ignore les lignes ayant déjà une VGP non nulle.")

    if st.button("🗑️ Vider le cache des prix"):
        if os.path.exists(PRICE_CACHE_FILE):
            os.remove(PRICE_CACHE_FILE)
            st.success("Cache effacé.")

    st.divider()
    if st.button("🔄 Forcer la recharge (Disque)", use_container_width=True, help="Relit les journaux qualifiés depuis le disque pour prendre en compte les modifs de l'App 2."):
        if "journal_active" in st.session_state: del st.session_state.journal_active
        if "active_path" in st.session_state: del st.session_state.active_path
        st.cache_data.clear()
        st.success("Données rechargées.")
        st.rerun()

    st.divider()
    show_status()

# --- Main logic ---
path = get_qualified_path(target_year)

if not os.path.exists(path):
    st.warning(f"📂 En attente de données : Le fichier '{os.path.basename(path)}' n'existe pas encore.")
    st.info("💡 Utilisez l'**App 2** pour synchroniser et sanctuariser vos premières données qualifiées.")
else:
    # --- Persistence Logic ---
    # We use session state to ensure UI updates after calculation
    if "journal_active" not in st.session_state or st.session_state.get("active_path") != path:
        journal = pd_read_csv_safe(path)
        journal["Date"] = pd.to_datetime(journal["Date"], utc=True, errors="coerce")
        st.session_state.journal_active = journal
        st.session_state.active_path = path

    journal = st.session_state.journal_active

    # Force numeric conversion & initialization
    for col in ["Amount", "Value ($)", "VGP (EUR)"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce").fillna(0.0)
        else:
            journal[col] = 0.0

    # Construction du masque de détection (Exclude manual duplicates and Spam)
    mask_valid = (journal["Status"] != "Spam") & (journal.get("Category", "") != "Doublon à ignorer")
    mask_imposable = (journal["Imposable"].apply(is_imposable_robust)) & mask_valid if use_imposable_col else pd.Series(False, index=journal.index)
    mask_category = (journal["Category"].fillna("").str.contains("Vente", case=False)) & mask_valid if use_category_vente else pd.Series(False, index=journal.index)

    mask_cessions = (mask_imposable | mask_category) & (journal["Asset"] != "EUR")
    cessions_all = journal[mask_cessions].copy()

    # --- Vérification d'Intégrité (Zéro Fallback) ---
    if not cessions_all.empty:
        # On vérifie si des cessions ont une VGP à 0
        missing_vgp_count = len(cessions_all[cessions_all["VGP (EUR)"] == 0])
        if missing_vgp_count > 0:
            st.error(f"🚨 **Attention :** {missing_vgp_count} cessions n'ont pas encore de VGP calculée ou validée. Les rapports fiscaux seront incomplets.")
            if st.button("🔍 Résoudre les prix manquants (AppPriceFix)", use_container_width=True):
                st.info("Basculez sur l'onglet **AppPriceFix** dans le menu principal pour collecter les prix manquants.")

    if cessions_all.empty:
        st.warning("⚠️ Aucune cession imposable détectée avec les critères actuels.")
        with st.expander("👀 Diagnostic : Voir tout le journal (pour vérifier les colonnes 'Imposable' / 'Category')"):
            st.write("Vérifiez dans l'**App 2** que vos ventes sont bien marquées comme 'Imposable' ou 'Vente'.")
            st.dataframe(journal, use_container_width=True)
    else:
        # 1. État des lieux
        nb_total = len(cessions_all)
        # We consider missing if VGP is exactly 0.0 or NaN
        mask_manquant = (cessions_all["VGP (EUR)"].isna()) | (cessions_all["VGP (EUR)"] == 0)
        nb_manquant = len(cessions_all[mask_manquant])

        # Error check: negative VGP
        mask_error = cessions_all["VGP (EUR)"] < -1e-8
        nb_error = len(cessions_all[mask_error])

        st.subheader(f"📈 Suivi des VGP ({nb_total} cessions au total)")
        col1, col2, col3 = st.columns(3)
        col1.metric("Cessions identifiées", nb_total)

        # Real-time counter logic: we use the session state directly for the counter
        col2.metric("VGP à calculer", nb_manquant, delta=-nb_manquant, delta_color="inverse")

        col3.metric("VGP en erreur (Négatives)", nb_error, delta=nb_error, delta_color="normal" if nb_error == 0 else "inverse")

        # 2. Boutons d'action
        if nb_manquant > 0:
            with st.expander("🔍 Voir les cessions sans VGP"):
                st.write(cessions_all[mask_manquant][["Date", "Asset", "Amount"]])

            if st.button("🚀 Lancer le calcul automatique (Incrémental)", type="primary", use_container_width=True):
                pbar = st.progress(0)
                # On ne calcule que pour les manquants
                to_calc = cessions_all[cessions_all["VGP (EUR)"] <= 0]

                for idx, (i, row) in enumerate(to_calc.iterrows()):
                    _, vgp_val = get_portfolio_snapshot(journal, row["Date"])
                    journal.at[i, "VGP (EUR)"] = vgp_val
                    pbar.progress((idx + 1) / len(to_calc))

                st.session_state.journal_active = journal
                st.success("Calcul incrémental terminé.")
                st.rerun()

        # 3. Édition manuelle et Contrôle
        st.divider()
        st.subheader("📋 Liste des Cessions & Contrôle des VGP")
        st.info("Vous pouvez modifier directement les valeurs VGP dans le tableau ci-dessous.")

        # On affiche uniquement les cessions pour édition
        # Type safety pour editor
        display_cols = ["Date", "Account", "Asset", "Amount", "Value ($)", "VGP (EUR)", "Tx Hash"]
        edit_df = journal[mask_cessions][display_cols].copy()
        for c in ["Account", "Asset", "Tx Hash"]:
            edit_df[c] = edit_df[c].fillna("").astype(str)

        edited_cessions = st.data_editor(
            edit_df,
            column_config={
                "VGP (EUR)": st.column_config.NumberColumn("VGP (EUR)", format="%.2f", help="Valeur totale du portefeuille à cette date"),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
            },
            use_container_width=True,
            key="vgp_editor"
        )

        # Injection des modifs manuelles dans le journal principal
        if st.button("💾 Sanctuariser les VGP (Enregistrer sur disque)", use_container_width=True):
            journal.loc[mask_cessions, "VGP (EUR)"] = edited_cessions["VGP (EUR)"].values
            journal.to_csv(path, index=False, encoding="utf-8-sig")
            st.success(f"Journal mis à jour avec les VGP dans {path}")
            st.balloons()

        # 4. Audit détaillé
        st.divider()
        st.subheader("🔍 Audit : Détail du Portefeuille à une Date")

        audit_options = sorted(list(cessions_all["Date"].unique()), reverse=True)
        eoy_date = datetime(target_year, 12, 31, tzinfo=audit_options[0].tzinfo if audit_options else None)
        audit_options = [eoy_date] + [d for d in audit_options if d != eoy_date]

        selected_date = st.selectbox("Choisir une date pour voir le détail", options=audit_options, format_func=lambda x: f"{x.strftime('%d/%m/%Y')} {'(🏁 Fin d’année)' if x == eoy_date else '(📈 Cession)'}")

        if selected_date:
            snapshot_df, total_val = get_portfolio_snapshot(journal, selected_date)
            if not snapshot_df.empty:
                st.write(f"Composition du portefeuille au **{selected_date}** :")

                # --- NEW: UNLABELED ACCOUNTS ALERT ---
                unlabeled = snapshot_df[snapshot_df["Location"].str.contains("External/CEX:", na=False)]
                if not unlabeled.empty:
                    st.warning(f"🚨 **Alerte :** {len(unlabeled)} comptes identifiés comme 'External/CEX' ont un solde non nul. "
                               "Ceci indique des transferts internes vers des comptes non récoltés. "
                               "Vous devriez soit ajouter ces comptes dans 'Mapping des Protocoles' (App 2), "
                               "soit vérifier vos types de transactions.")

                    with st.expander("📋 Liste des comptes 'External/CEX' à mapper"):
                        # Extract addresses from "External/CEX: 0x..."
                        cp_list = unlabeled["Location"].unique()
                        clean_list = [cp.replace("External/CEX: ", "").strip() for cp in cp_list]
                        st.code("\n".join(clean_list), language="text")
                        st.info("💡 Copiez ces adresses pour les ajouter à votre mapping de protocoles ou pour investiguer les transferts manquants.")

                # Highlight 0 prices
                zero_prices = snapshot_df[snapshot_df["Prix (EUR)"] == 0]
                if not zero_prices.empty:
                    st.warning(f"⚠️ {len(zero_prices)} actifs n'ont pas pu être valorisés automatiquement (Prix = 0).")

                # Interactive Editor for Audit
                ed_snapshot = st.data_editor(
                    snapshot_df,
                    column_config={
                        "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                        "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                        "Solde": st.column_config.NumberColumn("Solde Final", format="%.6f", disabled=True),
                        "Report": st.column_config.NumberColumn("Report (Initial)", format="%.6f", disabled=True),
                        "Entrées": st.column_config.NumberColumn("Total Entrées", format="%.6f", disabled=True),
                        "Sorties": st.column_config.NumberColumn("Total Sorties", format="%.6f", disabled=True),
                        "Asset": st.column_config.TextColumn(disabled=True),
                        "Location": st.column_config.TextColumn(disabled=True),
                    },
                    use_container_width=True,
                    key=f"audit_ed_{selected_date}"
                )

                # Recalculate Total with manual edits
                ed_snapshot["Valeur (EUR)"] = ed_snapshot["Solde"] * ed_snapshot["Prix (EUR)"].fillna(0.0)
                new_total = ed_snapshot["Valeur (EUR)"].sum()
                st.metric("VGP Totale Corrigée", f"{new_total:,.2f} €")

                col_save_audit1, col_save_audit2 = st.columns(2)

                if col_save_audit1.button("💾 Enregistrer ces prix dans le cache"):
                    cache = load_price_cache()
                    d_str = selected_date.strftime("%d-%m-%Y")

                    # On identifie les prix modifiés par rapport au cache actuel
                    count = 0
                    for _, r in ed_snapshot.iterrows():
                        a_clean = unicodedata.normalize('NFKC', str(r["Asset"])).upper().strip()
                        p_val = float(r["Prix (EUR)"])
                        if p_val > 0:
                            cache[f"{a_clean}_{d_str}"] = p_val
                            count += 1

                    save_price_cache(cache)

                    # Sanctuarisation annuelle automatique pour pérennité
                    y = str(selected_date.year)
                    y_dir = os.path.join(EXPORT_BASE_DIR, y)
                    os.makedirs(y_dir, exist_ok=True)
                    ann_path = os.path.join(y_dir, f"verified_prices_{y}.json")

                    existing_ann = {}
                    if os.path.exists(ann_path):
                        try:
                            with open(ann_path, "r", encoding="utf-8") as f: existing_ann = json.load(f)
                        except: pass

                    # Update with new values
                    for _, r in ed_snapshot.iterrows():
                        a_clean = unicodedata.normalize('NFKC', str(r["Asset"])).upper().strip()
                        p_val = float(r["Prix (EUR)"])
                        if p_val > 0:
                            existing_ann[f"{a_clean}_{d_str}"] = p_val

                    with open(ann_path, "w", encoding="utf-8") as f:
                        json.dump(existing_ann, f, indent=4)

                    st.success(f"{count} prix enregistrés (Global & Annuel). Relancez le calcul pour rafraîchir.")

                if col_save_audit2.button("🛡️ Sanctuariser l'Inventaire", use_container_width=True):
                    y_dir = os.path.join(EXPORT_BASE_DIR, str(selected_date.year))
                    os.makedirs(y_dir, exist_ok=True)

                    is_eoy = (selected_date.month == 12 and selected_date.day == 31)
                    if is_eoy:
                        inv_path = os.path.join(y_dir, f"inventory_EOY_{selected_date.year}.csv")
                        # Legacy support
                        legacy_path = os.path.join(y_dir, f"inventory_{selected_date.year}.csv")
                        ed_snapshot.to_csv(legacy_path, index=False, encoding="utf-8-sig")
                    else:
                        d_str = selected_date.strftime("%Y%m%d")
                        inv_path = os.path.join(y_dir, f"inventory_audit_{selected_date.year}_{d_str}.csv")

                    ed_snapshot.to_csv(inv_path, index=False, encoding="utf-8-sig")
                    st.success(f"Inventaire sanctuarisé : {os.path.basename(inv_path)}")
                    st.balloons()

            else:
                st.warning("Aucun historique trouvé pour cette date.")

st.sidebar.divider()
st.sidebar.caption("Calculateur VGP Pro v2.0 - app2VGP")
