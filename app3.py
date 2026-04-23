import os
import pandas as pd
import streamlit as st
from datetime import datetime
from fpdf import FPDF
from io import BytesIO, StringIO
import json
import tempfile
import unicodedata
import traceback
import time
import requests

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
st.set_page_config(page_title="Jules Crypto - Fiscalité (app3)", layout="wide")
st.title("⚖️ Fiscalité Crypto France (Art. 150 VH bis)")

EXPORT_BASE_DIR = "sanctuarisation"
POSITIONS_FILE = "position_labels.json"

# --- Helpers ---
def get_file_path(year, category):
    # category: 'qualified', 'fiat', 'positions', 'prices'
    base = os.path.join(EXPORT_BASE_DIR, str(year))
    if category == 'qualified':
        return os.path.join(base, f"qualified_journal_{year}.csv")
    if category == 'fiat':
        return os.path.join(base, f"manual_fiat_{year}.csv")
    if category == 'positions':
        return os.path.join(base, f"manual_positions_{year}.csv")
    if category == 'prices':
        return os.path.join(base, f"eoy_prices_{year}.json")
    return None

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

PRICE_CACHE_FILE = "historical_prices_cache.json"

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

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

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
    # Same logic as app2VGP for consistency
    asset_clean = unicodedata.normalize('NFKC', str(asset)).upper().strip()

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
    if cache_key in cache: return float(cache[cache_key])

    # 2. CoinGecko Mapping
    asset_map = {
        "ETH": "ethereum", "BTC": "bitcoin", "POL": "polygon-ecosystem-token",
        "BNB": "binancecoin", "ARB": "arbitrum", "OP": "optimism", "WETH": "ethereum",
        "SOL": "solana", "MATIC": "matic-network", "AVAX": "avalanche-2", "DOT": "polkadot",
        "LINK": "chainlink", "UNI": "uniswap", "AAVE": "aave", "DAI": "dai",
        "ZCHF": "cryptofranc", "BCH": "bitcoin-cash", "HBAR": "hedera-hashgraph",
        "TWT": "trust-wallet-token", "ME": "magic-eden", "ORDER": "orderly-network",
        "IP": "story-ip", "AUNT": "auntie-whale" # Fallback guess for AUNT
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

    # 3. Fallback DefiLlama (Prix Spot approximation pour les petites capitalisations)
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

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

def resolve_raw_addr(addr_str):
    if "(" in str(addr_str) and ")" in str(addr_str):
        return str(addr_str).split("(")[-1].split(")")[0].strip().lower()
    return str(addr_str).strip().lower()

def apply_position_labels(df):
    """Remplace l'adresse Counterparty par 'Label (0x...)' si un mapping existe."""
    if df.empty: return df
    labels = load_position_labels()
    if not labels: return df

    def format_cp(cp_str):
        raw = resolve_raw_addr(cp_str)
        if raw in labels:
            return f"{labels[raw]} ({raw})"
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

    data = {}
    for key, path in paths.items():
        if os.path.exists(path) and os.path.getsize(path) > 0:
            df = pd_read_csv_safe(path)
            # Standardisation Date
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')

            # Type Safety: Force numeric types to avoid pyarrow string errors
            num_cols = ["Amount", "Value ($)", "VGP (EUR)", "Prix de Cession (EUR)", "Montant EUR", "Quantité"]
            for col in num_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

            # FILTRAGE ANTI-SPAM GLOBAL (uniquement pour le journal qualifié)
            if key == 'journal' and 'Status' in df.columns:
                df = df[df['Status'] != 'Spam']

            if key == 'journal':
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

        if st.button("🧹 Nettoyer Cache Polices (.pkl)"):
            import glob
            pkl_files = glob.glob("*.pkl")
            for pf in pkl_files:
                try: os.remove(pf)
                except: pass
            st.info(f"{len(pkl_files)} fichiers de cache supprimés.")

    target_year = st.number_input("Année fiscale", min_value=2015, max_value=2030, value=datetime.now().year)

    st.divider()
    flat_tax_rate = st.slider("Taux d'imposition (PFU)", 0.0, 1.0, 0.30, 0.01)
    abattement = st.number_input("Abattement annuel (EUR)", value=305.0)

    st.divider()
    if st.button("🔄 Recalculer tout"):
        st.cache_data.clear()
        st.rerun()

data = load_data(target_year)

# --- Vérification d'Intégrité (Zéro Fallback) ---
if 'journal' in data and not data['journal'].empty:
    j = data['journal']
    def is_imp_check(v): return str(v).upper().strip() in ["TRUE", "1", "1.0", "VRAI"]
    mask_cess_check = (j['Imposable'].apply(is_imp_check) | j['Category'].fillna("").str.contains("Vente", case=False)) & (j['Asset'] != 'EUR')
    if mask_cess_check.any() and 'VGP (EUR)' in j.columns:
        missing_vgp = j[mask_cess_check & (j['VGP (EUR)'].fillna(0) == 0)]
        if not missing_vgp.empty:
            st.error(f"🚨 **Incohérence Fiscale :** {len(missing_vgp)} cessions ont une VGP à 0.00. Le calcul de la plus-value sera erroné. Veuillez régulariser dans l'**App 2 (VGP)** ou l'**AppPriceFix**.")

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
    pos_df = data.get('positions', pd.DataFrame())

    if not journal.empty:
        accounts = list(journal['Account'].dropna().unique())
        st.write(f"Comptes identifiés dans le journal : `{', '.join(accounts)}`")

        st.divider()
        st.subheader("📍 Positions de Fin d'Année")

        # 1. Chargement du référentiel Protocoles
        pos_labels = load_position_labels()
        protocol_addrs = set(pos_labels.keys())
        my_accounts = set(accounts)

        st.info("Ces positions servent à calculer la Valeur Globale du Portefeuille (VGP).")

        # 2. Calcul des soldes Locaux (Wallets)
        derived_local = journal.groupby(['Account', 'Asset']).agg({'Amount': 'sum'}).reset_index()
        derived_local = derived_local[derived_local['Amount'].abs() > 1e-8]

        # Chargement des prix sanctuarisés
        eoy_prices = load_eoy_prices(target_year)

        if "Prix (EUR)" not in derived_local.columns:
            derived_local["Prix (EUR)"] = derived_local["Asset"].map(eoy_prices).fillna(0.0)
        derived_local["Valeur (EUR)"] = derived_local["Amount"] * derived_local["Prix (EUR)"]

        # 3. Calcul des soldes Protocoles (Mapping Counterparty)
        # On cherche les flux vers des protocoles qui n'ont pas été retirés
        # Solde Protocole = Sum(Sent to Protocol) - Sum(Received from Protocol)
        protocol_rows = []
        for addr, label in pos_labels.items():
            # Flux ENVOYÉS au protocole (Amount négatif dans le journal car sort du wallet)
            # Mais pour le solde du protocole, c'est une entrée.
            # On simplifie : Solde = - (Somme des Amount du journal dont Counterparty est le protocole)
            mask_prot = journal["Counterparty"].fillna("").apply(resolve_raw_addr) == addr
            if mask_prot.any():
                df_prot = journal[mask_prot].groupby("Asset")["Amount"].sum().reset_index()
                for _, r in df_prot.iterrows():
                    if abs(r["Amount"]) > 1e-8:
                        protocol_rows.append({
                            "Account": label,
                            "Asset": r["Asset"],
                            "Amount": -r["Amount"] # Inversion car c'est une créance sur le protocole
                        })

        df_protocols = pd.DataFrame(protocol_rows)
        if not df_protocols.empty:
            if "Prix (EUR)" not in df_protocols.columns:
                df_protocols["Prix (EUR)"] = df_protocols["Asset"].map(eoy_prices).fillna(0.0)
            df_protocols["Valeur (EUR)"] = df_protocols["Amount"] * df_protocols["Prix (EUR)"]

        # 4. Valorisation & Sanctuarisation
        col_v1, col_v2 = st.columns(2)
        if col_v1.button("🚀 Valoriser les Positions (Auto)"):
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
                if not pos_df.empty:
                    unique_assets_man = set(pos_df["Asset"].unique())
                    prices_man = {a: get_price_eur(a, eoy_date) for a in unique_assets_man}
                    pos_df["Prix (EUR)"] = pos_df["Asset"].map(prices_man)
                    pos_df["Valeur (EUR)"] = pos_df["Quantité"] * pos_df["Prix (EUR)"]
                    st.session_state.manual_pos_valued = pos_df

                st.success("Valorisation terminée.")

        if col_v2.button("💾 Sanctuariser les Prix"):
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
                "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €", help="Saisissez ou corrigez le prix manuellement"),
                "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
                "Account": st.column_config.TextColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
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
                    "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €", help="Saisissez ou corrigez le prix manuellement"),
                    "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                    "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
                    "Account": st.column_config.TextColumn(disabled=True),
                    "Asset": st.column_config.TextColumn(disabled=True),
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
        if not pos_df.empty:
            for col in pos_df.columns:
                if pos_df[col].dtype == object:
                    pos_df[col] = pos_df[col].fillna("").astype(str)

            if "Prix (EUR)" not in pos_df.columns:
                pos_df["Prix (EUR)"] = pos_df["Asset"].map(eoy_prices).fillna(0.0)

            ed_manual = st.data_editor(
                pos_df,
                column_config={
                    "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                    "Quantité": st.column_config.NumberColumn(format="%.6f", disabled=True),
                    "Asset": st.column_config.TextColumn(disabled=True),
                    "Account": st.column_config.TextColumn(disabled=True),
                },
                use_container_width=True,
                key="manual_pos_ed"
            )
            # Recalcul de la valeur pour ces positions
            ed_manual["Valeur (EUR)"] = ed_manual["Quantité"] * ed_manual["Prix (EUR)"].fillna(0.0)
            st.session_state.manual_pos_valued = ed_manual
        else:
            st.info("Aucune position manuelle saisie dans l'App 0.")

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
            # Note: Le prix de cession en EUR doit être vérifié (basé sur Value ($) convertie via BCE ou saisi manuellement)
            if 'Prix de Cession (EUR)' not in cessions.columns:
                cessions['Prix de Cession (EUR)'] = 0.0

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

            if st.button("🧮 Calculer les Plus-Values"):
                # Formule: PV = Prix Cession - [Total Acq * (Prix Cession / VGP)]
                # Note: Le Total Acq doit théoriquement être mis à jour après chaque cession.
                # Crucial: Le calcul doit être fait dans l'ordre chronologique (Ascendant).
                results = []
                temp_acq = total_acq_price

                # Tri chronologique obligatoire pour la fiscalité française
                cessions_sorted = edited_cessions.sort_values("Date", ascending=True)

                for _, row in cessions_sorted.iterrows():
                    pc = row['Prix de Cession (EUR)']
                    vgp = row['VGP (EUR)']

                    if vgp > 0:
                        fraction_acq = temp_acq * (pc / vgp)
                        pv = pc - fraction_acq
                        results.append({
                            "Date": row['Date'],
                            "Asset": row['Asset'],
                            "Prix Cession": pc,
                            "VGP": vgp,
                            "Abattement Acq": fraction_acq,
                            "Plus-Value Brute": pv
                        })
                        # En fiscalité réelle, on soustrait fraction_acq du temp_acq pour la cession suivante
                        temp_acq -= fraction_acq
                    else:
                        st.error(f"VGP manquante pour la cession du {row['Date']}")

                if results:
                    st.session_state.bilan_fiscale = pd.DataFrame(results)
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
        col_b1.metric("Plus-Value Totale Brute", f"{total_pv:,.2f} €", help="Somme des plus-values unitaires calculées par cession selon la formule du formulaire 2086.")

        # Logique fiscale : exonération si total des prix de cession <= abattement (305€)
        if total_cessions <= abattement:
            pv_nette = 0.0
            st.warning(f"💡 Exonération appliquée : Le total des cessions ({total_cessions:.2f}€) est inférieur au seuil de {abattement}€.")
        else:
            pv_nette = total_pv

        col_b2.metric("Plus-Value Nette Imposable", f"{pv_nette:,.2f} €", help="Plus-value brute après application de l'abattement annuel de 305€ si applicable.")

        impot = pv_nette * flat_tax_rate if pv_nette > 0 else 0.0
        col_b3.metric(f"Impôt Estimé ({int(flat_tax_rate*100)}%)", f"{impot:,.2f} €", delta_color="inverse", help="Calculé selon le taux du Prélèvement Forfaitaire Unique (PFU) en vigueur.")

        # --- AJOUT INFOS COMPLÉMENTAIRES ---
        st.divider()
        c_inf1, c_inf2 = st.columns(2)

        # 1. Récupération du prix d'achat total (A)
        total_acq = st.session_state.get("total_acq_price_shared", 0.0)
        col_inf1.metric("Prix d'achat total (A)", f"{total_acq:,.2f} €", help="Capital investi (A) : Somme cumulée de vos apports fiat (Euros) dans l'écosystème crypto.")

        # 2. Calcul de la VGP consolidée à fin de période
        vgp_end = 0.0
        if "local_valued" in st.session_state:
            vgp_end += st.session_state.local_valued["Valeur (EUR)"].sum()
        if "proto_valued" in st.session_state:
            vgp_end += st.session_state.proto_valued["Valeur (EUR)"].sum()
        if "manual_pos_valued" in st.session_state:
            vgp_end += st.session_state.manual_pos_valued["Valeur (EUR)"].sum()

        c_inf2.metric(f"VGP consolidée (31/12/{target_year})", f"{vgp_end:,.2f} €", help="Valeur Globale du Portefeuille (VGP) au 31/12 : Somme des Wallets + Protocoles + Positions Manuelles.")

        st.divider()
        st.write("📝 **Montant à reporter dans la case 3AN (ou 3BN si moins-value) :**")
        st.code(f"{round(total_pv)}")

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
                    pdf.cell(w_p[0], 8, pdf_safe_str(r["Account"], use_uni), border=1)
                    pdf.cell(w_p[1], 8, pdf_safe_str(r["Asset"], use_uni), border=1)
                    pdf.cell(w_p[2], 8, f"{r['Amount']:.6f}", border=1)
                    if has_val:
                        pdf.cell(w_p[3], 8, f"{r.get('Valeur (EUR)', 0):,.2f} EUR", border=1)
                    pdf.ln()
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
                pdf.cell(w_f[0], 8, ds_f, border=1)
                pdf.cell(w_f[1], 8, pdf_safe_str(r.get("Account", "Manual"), use_uni)[:30], border=1)
                pdf.cell(w_f[2], 8, pdf_safe_str(r.get("Asset", "EUR"), use_uni), border=1)
                pdf.cell(w_f[3], 8, pdf_safe_str(r.get("Type", ""), use_uni), border=1)
                pdf.cell(w_f[4], 8, f"{r.get('Montant EUR', 0):.2f} EUR", border=1)
                pdf.cell(w_f[5], 8, f"{r.get('Quantité', 0):.6f}", border=1)
                pdf.ln()

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
        if st.button("📊 Préparer le Rapport PDF Complet", use_container_width=True):
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
