import os
import json
import time
import requests
import pandas as pd
from datetime import datetime
import streamlit as st
import unicodedata

EXPORT_BASE_DIR = "sanctuarisation"
POSITIONS_FILE = "position_labels.json"
PRICE_CACHE_FILE = "historical_prices_cache.json"

def resolve_raw_addr(addr_str):
    s = str(addr_str).strip().lower()
    if "(" in s and ")" in s:
        return s.split("(")[-1].split(")")[0].strip()
    parts = s.split()
    for p in parts:
        if p.startswith("0x") and len(p) >= 40: return p
    return s

def pd_read_csv_safe(path):
    try: return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try: return pd.read_csv(path, encoding="latin-1")
        except: return pd.read_csv(path, encoding="utf-8", errors="replace")

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
    from_currency = str(from_currency).upper().strip()
    if from_currency == "EUR": return 1.0
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from={from_currency}&to=EUR"
        res = requests.get(url, timeout=5).json()
        if "rates" in res and "EUR" in res["rates"]:
            return float(res["rates"]["EUR"])
    except: pass
    return 0.0

def get_price_eur(asset, date_obj):
    # Unified normalization
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

    # 1. Stables & Direct Mappings
    if asset_clean in ["EUR", "EURA", "AGEUR", "STEUR", "EURC"]: return 1.0
    if asset_clean in ["USD", "USDC", "USDT", "DAI", "USDC.E", "STUSD", "SUSDS", "TWCOMPOUNDUSDC"]:
        return get_fiat_rate("USD", date_obj)
    if asset_clean == "ZCHF": return get_fiat_rate("CHF", date_obj)

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = load_price_cache()
    cache_key = f"{asset_clean}_{d_str}"
    if cache_key in cache: return float(cache[cache_key])

    # 2. API Call (Limited)
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
    return 0.0

def get_portfolio_snapshot(journal_or_year, target_date):
    """
    Factual Account-based calculation of VGP.
    journal_or_year: either a dataframe or a year (int) to load full history.
    """
    pos_labels = {}
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                mappings = json.load(f)
                for addr, val in mappings.items():
                    pos_labels[addr] = val.get("label") if isinstance(val, dict) else val
        except: pass

    target_date = pd.to_datetime(target_date, utc=True)
    target_year = target_date.year
    start_of_year = datetime(target_year, 1, 1, tzinfo=target_date.tzinfo)

    # Load history if needed
    journals_all = []
    manual_all = []

    for y in range(2020, target_year + 1):
        path_j = os.path.join(EXPORT_BASE_DIR, str(y), f"qualified_journal_{y}.csv")
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

    # Filter Spam/Dup/EUR
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
        df_pre = df_j[df_j["Date"] < start_of_year]
        pre_bals = df_pre.groupby(["Account", "Asset"])["Amount"].sum().reset_index()
        df_ytd = df_j[df_j["Date"] >= start_of_year]
        ytd_stats = df_ytd.groupby(["Account", "Asset"])["Amount"].agg([
            ('In', lambda s: s[s > 0].sum()), ('Out', lambda s: s[s < 0].sum())
        ]).reset_index()
        merged = pd.merge(pre_bals, ytd_stats, on=["Account", "Asset"], how="outer").fillna(0.0)
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
            ext_pre = df_ext[df_ext["Date"] < start_of_year].groupby(["Counterparty", "Asset"])["Amount"].sum().reset_index()
            ext_ytd = df_ext[df_ext["Date"] >= start_of_year].groupby(["Counterparty", "Asset"])["Amount"].agg([
                ('In', lambda s: s[s < 0].sum()), ('Out', lambda s: s[s > 0].sum())
            ]).reset_index()
            merged_ext = pd.merge(ext_pre, ext_ytd, on=["Counterparty", "Asset"], how="outer").fillna(0.0)
            merged_ext = merged_ext.rename(columns={"Amount": "Reported"})
            merged_ext["Final_Bal"] = merged_ext["Reported"] + merged_ext["In"] + merged_ext["Out"]
            for _, r in merged_ext.iterrows():
                if abs(r["Final_Bal"]) > 1e-8:
                    raw_cp = resolve_raw_addr(r["Counterparty"])
                    label = pos_labels.get(raw_cp, f"External/CEX: {r['Counterparty']}")
                    p = asset_prices.get(r["Asset"], 0.0)
                    details.append({
                        "Location": label, "Asset": r["Asset"],
                        "Report": -r["Reported"], "Entrées": abs(r["In"]), "Sorties": abs(r["Out"]),
                        "Solde": -r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": (-r["Final_Bal"]) * p
                    })

    # --- C. MANUAL POSITIONS ---
    if not df_m.empty:
        m_pre = df_m[df_m["Date"] < start_of_year].groupby(["Account", "Asset"])["Quantité"].sum().reset_index()
        m_ytd = df_m[df_m["Date"] >= start_of_year].groupby(["Account", "Asset"])["Quantité"].agg([
            ('In', lambda s: s[s > 0].sum()), ('Out', lambda s: s[s < 0].sum())
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

def get_known_accounts():
    """Aggregates account names from mapping file and all qualified journals."""
    known = set()

    # 1. From Mappings
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                mappings = json.load(f)
                for addr, val in mappings.items():
                    if isinstance(val, dict):
                        known.add(val.get("label", ""))
                    else:
                        known.add(val)
        except: pass

    # 2. From Journals (all years)
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
            if os.path.exists(path):
                try:
                    df = pd_read_csv_safe(path)
                    if "Account" in df.columns:
                        known.update(df["Account"].dropna().unique())
                except: pass

    # Clean and sort
    clean_known = sorted([str(x).strip() for x in known if str(x).strip() and str(x).lower() != "nan"])
    return clean_known

if __name__ == "__main__":
    st.set_page_config(page_title="Jules Crypto - Status Shared Logic", page_icon="⚙️")
    st.title("⚙️ Module de Logique Partagée")
    st.success("✅ Le module `shared_logic.py` est opérationnel et chargé correctement.")
    st.info("Ce fichier est une bibliothèque de fonctions utilisée par les autres applications de la suite. Il ne contient pas d'interface de saisie.")

    st.subheader("📊 Diagnostic des données")
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        st.write(f"Dossiers annuels détectés : `{', '.join(years)}`")
    else:
        st.warning("⚠️ Dossier `sanctuarisation` non détecté.")

    known_accs = get_known_accounts()
    st.write(f"Nombre de comptes connus indexés : `{len(known_accs)}`")

    if st.checkbox("Voir la liste des comptes"):
        st.write(known_accs)
