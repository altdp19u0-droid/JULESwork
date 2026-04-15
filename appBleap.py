import os
import pandas as pd
import streamlit as st
import requests
from datetime import datetime
import time
import json
import io
import unicodedata

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Import Bleap (appBleap)", layout="wide")
st.title("🚜 Importeur Spécialisé Bleap")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"

# --- Pricing & Conversion Engine ---
def load_price_cache():
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

@st.cache_data(ttl=86400)
def get_eur_usd_rate(date_obj):
    """Récupère le taux EUR/USD pour une date donnée via Frankfurter API."""
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
        res = requests.get(url, timeout=5).json()
        return res["rates"]["EUR"]
    except:
        return 0.92

def get_price_eur(asset, date_obj):
    # Normalisation pour l'API
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

    if asset_clean in ["EUR", "EURA", "AGEUR"]: return 1.0
    if asset_clean in ["USDC", "USDT", "DAI", "USDC.E"]: return 0.92

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = load_price_cache()
    cache_key = f"{asset_clean}_{d_str}"
    if cache_key in cache: return float(cache[cache_key])

    asset_map = {
        "ETH": "ethereum", "BTC": "bitcoin", "POL": "polygon-ecosystem-token",
        "BNB": "binancecoin", "ARB": "arbitrum", "OP": "optimism", "WETH": "ethereum",
        "SOL": "solana", "MATIC": "matic-network", "AVAX": "avalanche-2", "DOT": "polkadot",
        "LINK": "chainlink", "UNI": "uniswap", "AAVE": "aave", "DAI": "dai"
    }

    cg_id = asset_map.get(asset_clean, asset_clean.lower())
    url_cg = f"https://api.coingecko.com/api/v3/coins/{cg_id}/history?date={d_str}&localization=false"

    try:
        time.sleep(1.5)
        res = requests.get(url_cg, timeout=10)
        if res.status_code == 200:
            data = res.json()
            price = float(data["market_data"]["current_price"]["eur"])
            cache[cache_key] = price
            save_price_cache(cache)
            return price
    except: pass

    try:
        ts = int(date_obj.timestamp())
        url_llama = f"https://coins.llama.fi/prices/historical/{ts}/coingecko:{cg_id}?searchWidth=4h"
        res = requests.get(url_llama, timeout=10)
        if res.status_code == 200:
            data = res.json()
            coins = data.get("coins", {})
            if coins:
                price_usd = float(next(iter(coins.values()))["price"])
                price = price_usd * 0.92
                cache[cache_key] = price
                save_price_cache(cache)
                return price
    except: pass

    return 0.0

# --- Helper: Robust CSV reading ---
def pd_read_csv_safe(file):
    try:
        return pd.read_csv(file, encoding="utf-8-sig", sep=None, engine='python')
    except:
        try:
            file.seek(0)
            return pd.read_csv(io.BytesIO(file.read()), encoding="latin-1", sep=None, engine='python')
        except:
            file.seek(0)
            return pd.read_csv(file, encoding="utf-8", errors="replace", sep=None, engine='python')

# --- Processing Engine ---
def process_bleap_csv(df):
    new_rows = []
    account = "Bleap_App"

    # Filter out non-completed
    df = df[df["Status"] == "COMPLETED"].copy()

    progress_bar = st.progress(0)
    total_rows = len(df)

    for idx, row in df.iterrows():
        # Parsing date
        dt_str = str(row.get("Created At", row.get("Completed At", "")))
        try:
            dt = pd.to_datetime(dt_str)
        except:
            dt = datetime.now()

        t_type = str(row.get("Type", ""))
        desc = str(row.get("Description", ""))
        currency = str(row.get("Currency", ""))
        amount = pd.to_numeric(row.get("Amount"), errors='coerce') or 0.0
        fees = pd.to_numeric(row.get("Fees"), errors='coerce') or 0.0

        is_imp = False
        cp = "System"
        val = 0.0

        if t_type == "Top Up":
            cp = "banq N26"
            cat = "Achat"
            val = amount # Entry
        elif t_type == "Off-Ramp" and "Bank Transfer (Sell)" in desc:
            cp = "banq N26"
            cat = "Vente"
            val = -amount # Exit
            if currency == "EURA":
                is_imp = True
        elif "Earn" in t_type or "Bridge" in t_type:
            cat = "Transfert Interne"
            # Logic simplified: Deposit is OUT to Earn, Withdrawal is IN from Earn
            val = -amount if "Deposit" in t_type else amount
            cp = "Bleap_Earn"
        elif "Exchange" in t_type or "Trade" in t_type:
            cat = "Swap"
            val = amount # The leg we see in the CSV
            cp = "Swap"
        elif t_type == "Deposit":
            cat = "Transfert In"
            val = amount
            cp = "External"
        elif t_type == "Withdrawal":
            cat = "Transfert Out"
            val = -amount
            cp = "External"
        else:
            cat = "A vérifier"
            val = amount
            cp = "Unknown"

        # Calculation of Value ($) and Value (EUR)
        price_eur = get_price_eur(currency, dt)
        val_eur = abs(val) * price_eur
        eur_rate = get_eur_usd_rate(dt)
        val_usd = val_eur / eur_rate if eur_rate > 0 else val_eur / 0.92

        # Create row
        new_rows.append({
            "Date": dt,
            "Chain": "Bleap",
            "Token": currency, # Preserve nuances
            "Token ID": "",
            "Tx Hash": f"BLP-{idx}",
            "From": cp if val > 0 else account,
            "To": account if val > 0 else cp,
            "Value": abs(val),
            "Value ($)": val_usd,
            "Rate ($)": (val_usd / abs(val)) if val != 0 else 0.0,
            "Account": account,
            "Counterparty": cp,
            "Imposable": is_imp
        })

        # Handle Fees
        if fees > 0:
             new_rows.append({
                "Date": dt,
                "Chain": "Bleap",
                "Token": currency,
                "Token ID": "",
                "Tx Hash": f"BLP-FEE-{idx}",
                "From": account,
                "To": "Fees",
                "Value": fees,
                "Value ($)": (fees * price_eur) / eur_rate if eur_rate > 0 else (fees * price_eur) / 0.92,
                "Rate ($)": price_eur / eur_rate if eur_rate > 0 else price_eur / 0.92,
                "Account": account,
                "Counterparty": "Bleap_Fees",
                "Imposable": False
            })

        progress_bar.progress((idx + 1) / total_rows)

    return pd.DataFrame(new_rows)

# --- Main App ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de destination", min_value=2015, max_value=2030, value=datetime.now().year)
    st.divider()
    st.info("💡 Ce module applique les règles N26 et identifie automatiquement les ventes imposables d'EURA.")

uploaded_file = st.file_uploader("📂 Déposez votre export CSV Bleap", type="csv")

if uploaded_file:
    df_raw = pd_read_csv_safe(uploaded_file)
    st.subheader("👀 Aperçu du fichier source")
    st.dataframe(df_raw.head(5), use_container_width=True)

    if st.button("🚀 Lancer la transcription Bleap", type="primary", use_container_width=True):
        with st.spinner("Analyse et recherche des prix..."):
            df_final = process_bleap_csv(df_raw)
            st.session_state.bleap_final = df_final
            st.success(f"Transcription terminée : {len(df_final)} lignes générées.")

    if "bleap_final" in st.session_state:
        st.divider()
        st.subheader("✅ Résultat au format Sanctuarisation")

        # Interactivité pour la colonne Imposable
        edited_df = st.data_editor(
            st.session_state.bleap_final,
            column_config={
                "Imposable": st.column_config.CheckboxColumn("Taxable (Imp.)", help="Coché pour les Off-Ramp EURA vers N26."),
                "Value ($)": st.column_config.NumberColumn(format="%.2f", disabled=True),
                "Value": st.column_config.NumberColumn(format="%.8f", disabled=True),
                "Date": st.column_config.DatetimeColumn(disabled=True),
            },
            use_container_width=True,
            num_rows="fixed",
            key="bleap_editor"
        )

        st.divider()
        if st.button("💾 Sanctuariser (Enregistrer les Brutes)", use_container_width=True):
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
st.sidebar.caption("Import Bleap v1.0 - appBleap")
