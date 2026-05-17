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
EXTERNAL_CIRCUITS_FILE = "external_circuits.json"
OWNERS_FILE = "owner_accounts.json"
SPAM_FILE = "spam_blacklist.json"
NOTES_FILE = "manual_notes.json"
VALID_ASSETS_FILE = "valid_assets.json"
GLOBAL_CONFIG_FILE = "global_config.json"

def load_global_config():
    """Loads global settings like activity start year and current processing year."""
    defaults = {
        "start_year": None,
        "processing_year": datetime.now().year
    }
    if os.path.exists(GLOBAL_CONFIG_FILE):
        try:
            with open(GLOBAL_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure types are correct
                if data.get("start_year"): data["start_year"] = int(data["start_year"])
                if data.get("processing_year"): data["processing_year"] = int(data["processing_year"])
                return {**defaults, **data}
        except: pass
    return defaults

def save_global_config(config):
    """Saves global settings."""
    with open(GLOBAL_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def clean_session_state(preserve_keys=[]):
    """
    Clears session state while preserving Hub navigation and specific keys.
    """
    hub_keys = [k for k in st.session_state.keys() if k.startswith("_hub_")]
    to_keep = set(preserve_keys + hub_keys)

    for k in list(st.session_state.keys()):
        if k not in to_keep:
            del st.session_state[k]

def resolve_raw_addr(addr_str):
    """
    Extracts the pure technical identifier (hex address or label) from a display string.
    Supports: '0x123... (Name)', 'Name (0x123...)', 'Name (Label)', '0x123...', 'Label'
    """
    s = str(addr_str).strip().lower()

    # 1. Search for a hex address anywhere (strongest identifier)
    import re
    match = re.search(r'0x[a-f0-9]{40,}', s)
    if match:
        return match.group(0)

    # 2. If no hex, handle parentheses 'Identifier (Name)' or 'Name (Identifier)'
    if "(" in s and ")" in s:
        # We assume the first part is the identifier if it's not a hex address
        return s.split("(")[0].strip()

    return s

def standardize_address_string(addr_str):
    """
    Enforces the absolute standard: 'Identifier (Name)'
    - If input is a known label, resolves to 'Address (Label)'.
    - If input is a known address, resolves to 'Address (Label)'.
    - Always lowercases hex addresses.
    - Preserves case for labels if not in owners map.
    """
    if not addr_str or str(addr_str).lower() in ["nan", "none", ""]: return ""

    s = str(addr_str).strip()
    raw = resolve_raw_addr(s).lower()

    owners_map = load_owner_accounts() # addr -> label
    # Create reverse map: label -> addr
    label_to_addr = {str(v).lower(): k for k, v in owners_map.items() if str(v).lower() != "nan"}

    # 1. Resolution
    if raw in owners_map:
        # It's a known address
        return format_owner_display(raw, owners_map[raw])

    if raw in label_to_addr:
        # It's a known label
        addr = label_to_addr[raw]
        return format_owner_display(addr, owners_map[addr])

    # 2. Heuristic for unknown entries that might already be formatted
    name = ""
    if "(" in s and ")" in s:
        # Extract components from 'Id (Name)'
        parts = s.split("(")
        p1 = parts[0].strip()
        p2 = parts[1].replace(")", "").strip()

        # If p1 is hex, it's the id, p2 is name
        if p1.lower().startswith("0x"):
            raw = p1.lower()
            name = p2
        else:
            # p2 might be the hex address
            if p2.lower().startswith("0x"):
                raw = p2.lower()
                name = p1
            else:
                raw = p1 # Orphan label with notes in parens
                name = p2

    return format_owner_display(raw, name)

def standardize_df_addresses(df):
    """Applies unification in lowercase for technical addresses in a DataFrame."""
    if df.empty: return df
    df = df.copy()
    for col in ["Account", "Counterparty", "From", "To"]:
        if col in df.columns:
            df[col] = df[col].apply(standardize_address_string)
    return df

def format_owner_display(identifier, name):
    """
    Standardized display for owner accounts: 'Identifier (Name)'
    Absolute standard: Primary technical ID followed by friendly label in parentheses.
    """
    ident = str(identifier).strip()
    nm = str(name).strip() if name and str(name).lower() != "nan" else ""

    if not nm or nm == ident:
        return ident

    return f"{ident} ({nm})"

def resolve_owner_display(identifier):
    """
    Resolves any identifier (hex or label) to its standardized owner display string.
    Uses owner_accounts.json for mapping.
    """
    owners_map = load_owner_accounts()
    low_id = str(identifier).lower().strip()

    # 1. Check if it's a known address
    if low_id in owners_map:
        return format_owner_display(identifier, owners_map[low_id])

    # 2. Check if it's a known label
    label_to_addr = {str(v).lower(): k for k, v in owners_map.items() if str(v).lower() != "nan"}
    if low_id in label_to_addr:
        addr = label_to_addr[low_id]
        return format_owner_display(addr, owners_map[addr])

    return identifier # Fallback if unknown

def pd_read_csv_safe(path):
    try: return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try: return pd.read_csv(path, encoding="latin-1")
        except: return pd.read_csv(path, encoding="utf-8", errors="replace")

def is_imposable_robust(val):
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI", "YES", "OUI"]

def get_safe_opts(df, col):
    """Safely extracts unique sorted string options for Streamlit widgets."""
    if df is None or df.empty or col not in df.columns: return []
    return sorted([str(x) for x in df[col].dropna().unique()])

def standardize_asset(asset):
    """Unified asset normalization for the whole suite."""
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
    return unicodedata.normalize('NFKC', asset_clean).upper().strip()

def get_file_path(year, category, sanctuary=False):
    """Centralized path resolution for all apps."""
    base = os.path.join(EXPORT_BASE_DIR, str(year))
    if sanctuary:
        base = os.path.join(base, "sanctuary")
        os.makedirs(base, exist_ok=True)

    if category == 'qualified':
        return os.path.join(base, f"qualified_journal_{year}.csv")
    if category == 'fiat':
        return os.path.join(base, f"manual_fiat_{year}.csv")
    if category == 'positions':
        return os.path.join(base, f"manual_positions_{year}.csv")
    if category == 'swaps':
        return os.path.join(base, f"manual_swaps_{year}.csv")
    if category == 'prices':
        return os.path.join(base, f"eoy_prices_{year}.json")
    if category == 'verified_prices':
        return os.path.join(base, f"verified_prices_{year}.json")
    if category == 'inventory_eoy':
        return os.path.join(base, f"inventory_EOY_{year}.csv")
    if category == 'qualified_clean':
        return os.path.join(base, f"qualified_journal_CLEAN_{year}.csv")
    return None

def get_all_raw_files(year):
    """Returns ALL raw CSV files in a given year directory, sorted by name descending (latest first)."""
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir): return []
    files = [f for f in os.listdir(year_dir) if f.endswith(".csv") and f.startswith("raw_")]
    return [os.path.join(year_dir, f) for f in sorted(files, reverse=True)]

def extract_source_from_filename(filename):
    """Isolates the source/account identifier from a raw filename."""
    import re
    ts_pattern = re.compile(r'_(\d{8}(?:_\d{6})?)$')
    basename = os.path.basename(filename).replace(".csv", "")

    # Strip timestamp if exists
    match = ts_pattern.search(basename)
    prefix_full = basename[:match.start()] if match else basename

    # Strip standard type prefixes
    for t in ["raw_portfolio_", "raw_transactions_", "raw_token_transfers_"]:
        if prefix_full.startswith(t):
            return prefix_full.replace(t, "")
    return prefix_full

def get_latest_raw_files(year):
    """
    Returns only the most recent raw CSV files per source in a given year directory.
    Identifies timestamps (YYYYMMDD or YYYYMMDD_HHMMSS) to group different versions of the same harvest.
    """
    all_raw = get_all_raw_files(year)
    if not all_raw: return []

    # Map: prefix -> latest_filename
    latest_map = {}

    import re
    # Pattern for timestamp: _YYYYMMDD or _YYYYMMDD_HHMMSS
    ts_pattern = re.compile(r'_(\d{8}(?:_\d{6})?)$')

    for f_path in all_raw:
        f = os.path.basename(f_path)
        basename = f.replace(".csv", "")

        match = ts_pattern.search(basename)
        # If match, prefix is everything before the timestamp
        prefix = basename[:match.start()] if match else basename

        if prefix not in latest_map:
            latest_map[prefix] = f_path
        else:
            # Comparison between full paths (string comparison works for timestamps)
            if f_path > latest_map[prefix]:
                latest_map[prefix] = f_path

    return sorted(list(latest_map.values()))

def get_sanctuary_transactions(year):
    """
    Collects all transactions from ALL files in the sanctuary folder for a given year.
    Used for audit and recovery.
    """
    s_dir = os.path.join(EXPORT_BASE_DIR, str(year), "sanctuary")
    if not os.path.exists(s_dir): return pd.DataFrame()

    files = [os.path.join(s_dir, f) for f in os.listdir(s_dir) if f.endswith(".csv") and f.startswith("raw_")]
    if not files: return pd.DataFrame()

    all_rows = []
    for f in files:
        try:
            df = pd_read_csv_safe(f)
            if df.empty: continue
            df["_orig_file"] = os.path.basename(f)
            all_rows.append(df)
        except: pass

    if not all_rows: return pd.DataFrame()
    return pd.concat(all_rows).reset_index(drop=True)

def check_file_freshness(path, last_load_time):
    """Returns True if the file has been modified since last_load_time."""
    if not os.path.exists(path): return False
    mtime = os.path.getmtime(path)
    return mtime > last_load_time

def load_price_cache():
    combined = {}
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8", errors="replace") as f:
                combined = json.load(f)
        except: pass
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"verified_prices_{y}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f: combined.update(json.load(f))
                except: pass
    return combined

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

def get_fiat_rate(from_currency, date_obj):
    """Fetches official BCE exchange rates via Frankfurter API."""
    from_curr = str(from_currency).upper().strip()
    if from_curr == "EUR": return 1.0
    # Handle common mappings
    if from_curr == "USD": ticker = "USD"
    elif from_curr == "CHF": ticker = "CHF"
    else: ticker = from_curr

    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from={ticker}&to=EUR"
        res = requests.get(url, timeout=5).json()
        if "rates" in res and "EUR" in res["rates"]:
            return float(res["rates"]["EUR"])
    except: pass
    return 0.0

def get_price_eur(asset, date_obj, cache=None):
    if not isinstance(date_obj, datetime):
        date_obj = datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=None)

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
    if asset_clean in ["EUR", "EURA", "AGEUR", "STEUR", "EURC", "EURT", "EURCV"]: return 1.0
    if asset_clean in [
        "USD", "USDC", "USDT", "DAI", "USDC.E", "STUSD", "SUSDS",
        "TWCOMPOUNDUSDC", "TWCOMPUSDC", "CUSDC", "CUSDT", "CDAI",
        "FDUSD", "PYUSD", "BUSD", "FRAX", "LUSD", "GUSD", "ZUSD", "USDS"
    ]:
        return get_fiat_rate("USD", date_obj)
    if asset_clean == "ZCHF": return get_fiat_rate("CHF", date_obj)

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = cache if cache is not None else load_price_cache()
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

    # Fallback DefiLlama
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
                if price > 0:
                    cache[cache_key] = price
                    save_price_cache(cache)
                    return price
    except: pass

    return 0.0

def get_portfolio_snapshot(journal_or_year, target_date, force_full_history=False, start_recalc_year=2020):
    """
    Factual Account-based calculation of VGP.
    journal_or_year: either a dataframe or a year (int) to load current year data.
    Mandatory starting point: inventory_EOY_{year-1}.csv if force_full_history is False.
    """
    pos_labels = load_position_labels()

    target_date = pd.to_datetime(target_date, utc=True)
    target_year_val = target_date.year
    start_of_year = datetime(target_year_val, 1, 1, tzinfo=target_date.tzinfo)

    # Load global config to check for Activity Start Year
    config = load_global_config()
    activity_start_year = config.get("start_year")

    journals_to_process = []
    manual_to_process = []
    starting_balances = [] # List of DataFrames: [Location, Asset, Solde]

    # 1. Mandatory Inventory Check
    found_inventory = False

    # Rule: If target year is the Activity Start Year, we FORCE zero starting balance.
    is_start_year = (activity_start_year is not None and int(target_year_val) == int(activity_start_year))

    if not force_full_history and not is_start_year:
        prev_year = target_year_val - 1
        inv_path = os.path.join(EXPORT_BASE_DIR, str(prev_year), f"inventory_EOY_{prev_year}.csv")
        if os.path.exists(inv_path):
            try:
                df_inv = pd_read_csv_safe(inv_path)
                if not df_inv.empty and all(c in df_inv.columns for c in ["Location", "Asset", "Solde"]):
                    df_start = df_inv[["Location", "Asset", "Solde"]].copy()
                    # Standardize Location: 'Account: 0x...' -> 'Account: 0x... (Name)'
                    def std_loc(loc):
                        if str(loc).startswith("Account: "):
                             return f"Account: {standardize_address_string(loc.replace('Account: ', ''))}"
                        elif str(loc).startswith("Manual Position: "):
                             return f"Manual Position: {standardize_address_string(loc.replace('Manual Position: ', ''))}"
                        return loc
                    df_start["Location"] = df_start["Location"].apply(std_loc)
                    df_start = df_start.rename(columns={"Solde": "Amount"})
                    starting_balances.append(df_start)
                    found_inventory = True
                    start_scan_year = target_year_val
            except: pass

    if is_start_year:
        found_inventory = True # Treat as found (but empty) to avoid UI warnings
        start_scan_year = target_year_val
    elif not found_inventory:
        # If no inventory found or full history requested
        start_scan_year = start_recalc_year
        if not force_full_history and target_year_val > 2020:
             # This will trigger an alert in UI because found_inventory is False
             pass

    # 2. Load journals from start_scan_year to target_year_val
    processed_current_year_df = False
    for y in range(start_scan_year, target_year_val + 1):
        if y == target_year_val and isinstance(journal_or_year, pd.DataFrame):
            if journal_or_year.empty or "Date" not in journal_or_year.columns:
                continue
            df_y = journal_or_year.copy()
            # UNIFICATION CASE (Lowering 0x addresses)
            df_y = standardize_df_addresses(df_y)
            df_y["Date"] = pd.to_datetime(df_y["Date"], utc=True, errors="coerce")

            # --- ZÉRO SPAM ---
            df_y = apply_spam_filter(df_y, drop=True)

            journals_to_process.append(df_y[df_y["Date"] <= target_date])
            processed_current_year_df = True
        elif not (y == target_year_val and processed_current_year_df):
            path_j = os.path.join(EXPORT_BASE_DIR, str(y), f"qualified_journal_{y}.csv")
            if os.path.exists(path_j):
                try:
                    df_y = pd_read_csv_safe(path_j)
                    if not df_y.empty and "Date" in df_y.columns:
                        # UNIFICATION CASE
                        df_y = standardize_df_addresses(df_y)
                        df_y["Date"] = pd.to_datetime(df_y["Date"], utc=True, errors="coerce")

                        # --- ZÉRO SPAM ---
                        df_y = apply_spam_filter(df_y, drop=True)

                        journals_to_process.append(df_y[df_y["Date"] <= target_date])
                except: pass

        path_m = os.path.join(EXPORT_BASE_DIR, str(y), f"manual_positions_{y}.csv")
        if os.path.exists(path_m):
            try:
                tmp_m = pd_read_csv_safe(path_m)
                if not tmp_m.empty and "Date" in tmp_m.columns:
                    # --- UNIFICATION ---
                    tmp_m = standardize_df_addresses(tmp_m)
                    tmp_m["Date"] = pd.to_datetime(tmp_m["Date"], utc=True, errors="coerce")
                    manual_to_process.append(tmp_m[tmp_m["Date"] <= target_date])
            except: pass

    if not journals_to_process and not manual_to_process and not starting_balances:
        return pd.DataFrame(), 0.0

    df_j = pd.concat(journals_to_process) if journals_to_process else pd.DataFrame()
    df_m = pd.concat(manual_to_process) if manual_to_process else pd.DataFrame()

    # Filter Spam/Dup/EUR
    if not df_j.empty:
        # We exclude both Spams and any category containing 'Doublon'
        mask_exc = (df_j["Status"] == "Spam") | (df_j.get("Category", "").fillna("").str.contains("Doublon", case=False, na=False))
        df_j = df_j[~mask_exc & (df_j["Asset"] != "EUR")]
    if not df_m.empty:
        df_m = df_m[df_m["Asset"] != "EUR"]

    # 2. Pricing
    all_assets = set()
    if not df_j.empty: all_assets.update(df_j["Asset"].unique())
    if not df_m.empty: all_assets.update(df_m["Asset"].unique())

    # Optimization: pre-load cache for batch pricing
    price_cache = load_price_cache()
    asset_prices = {a: get_price_eur(a, target_date, cache=price_cache) for a in all_assets}

    details = []

    # Identify owned accounts from all sources
    owned_names = set()
    if not df_j.empty: owned_names.update(df_j["Account"].dropna().unique())
    if not df_m.empty: owned_names.update(df_m["Account"].dropna().unique())

    # Also add known owners from reference file
    owners_map = load_owner_accounts()
    owned_names.update(owners_map.values())

    owned_addrs = set(owners_map.keys())
    for n in owned_names:
        res = resolve_raw_addr(n).lower()
        if res.startswith("0x"): owned_addrs.add(res)

    # --- A. OWNED ACCOUNTS ---
    # Merge starting balances for Owned Accounts
    # Account format in inventory: "Account: Name"
    start_wallets = pd.DataFrame(columns=["Account", "Asset", "Amount"])
    if starting_balances:
        df_s = pd.concat(starting_balances)
        if not df_s.empty and all(c in df_s.columns for c in ["Location", "Amount"]):
            # Normalize amount to float
            df_s["Amount"] = pd.to_numeric(df_s["Amount"], errors="coerce").fillna(0.0)

            mask_w = df_s["Location"].str.startswith("Account:", na=False)
            start_wallets_df = df_s[mask_w].copy()
            # Standardize after stripping prefix
            start_wallets_df["Account"] = start_wallets_df["Location"].str.replace("Account: ", "", regex=False).apply(standardize_address_string)
            start_wallets = start_wallets_df.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

    if not df_j.empty or not start_wallets.empty:
        # Pre-YTD (from start_scan_year up to end of previous year)
        pre_bals = pd.DataFrame(columns=["Account", "Asset", "Amount"])
        if not df_j.empty and "Date" in df_j.columns:
            df_pre = df_j[df_j["Date"] < start_of_year]
            if not df_pre.empty:
                pre_bals = df_pre.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

        # Combine with starting balances from inventory
        if len(start_wallets) > 0:
            pre_bals = pd.concat([pre_bals, start_wallets]).groupby(["Account", "Asset"])["Amount"].sum().reset_index()

        ytd_stats = pd.DataFrame(columns=["Account", "Asset", "In", "Out"])
        if not df_j.empty and "Date" in df_j.columns:
            df_ytd = df_j[df_j["Date"] >= start_of_year]
            if not df_ytd.empty:
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
                    "Report": r["Reported"], "Entrées": r["In"],
                    "Sorties": r["Out"], # Preserve negative sign
                    "Solde": r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": r["Final_Bal"] * p,
                    "Is_Circuit": False, "Is_Position": False
                })

    # --- B. INTERNAL TRANSFER OFFSET LEGS (Receivables) ---
    start_ext = pd.DataFrame(columns=["Counterparty", "Asset", "Amount"])
    if starting_balances:
        df_s = pd.concat(starting_balances)
        if not df_s.empty and all(c in df_s.columns for c in ["Location", "Amount"]):
            mask_ext = (~df_s["Location"].str.startswith("Account:", na=False)) & (~df_s["Location"].str.startswith("Manual Position:", na=False))
            tmp_ext = df_s[mask_ext].groupby(["Location", "Asset"])["Amount"].sum().reset_index()
            tmp_ext = tmp_ext.rename(columns={"Location": "Counterparty"})
            # Note: inventory stores Receivables with positive 'Solde'.
            # We need to flip it back to match the leg logic (leg sum is negative of receivable)
            tmp_ext["Amount"] = -tmp_ext["Amount"]
            start_ext = tmp_ext

    if not df_j.empty or not start_ext.empty:
        ext_data = load_external_circuits()
        circuit_labels = ext_data.get("labels", {})
        circuit_addrs = set(circuit_labels.keys())

        df_ext = pd.DataFrame()
        if not df_j.empty:
            mask_int = (df_j["Category"] == "Transfert Interne")
            df_ext = df_j[mask_int].copy()
            df_ext["cp_low"] = df_ext["Counterparty"].apply(resolve_raw_addr)
            # Filter: Counterparty must not be an owned account name AND not an owned account address
            df_ext = df_ext[ (~df_ext["Counterparty"].isin(owned_names)) & (~df_ext["cp_low"].isin(owned_addrs)) ]

        ext_pre = pd.DataFrame(columns=["Counterparty", "Asset", "Amount"])
        if not df_ext.empty and "Date" in df_ext.columns:
            ext_pre = df_ext[df_ext["Date"] < start_of_year].groupby(["Counterparty", "Asset"])["Amount"].sum().reset_index()

        if len(start_ext) > 0:
            ext_pre = pd.concat([ext_pre, start_ext]).groupby(["Counterparty", "Asset"])["Amount"].sum().reset_index()

        ext_ytd = pd.DataFrame(columns=["Counterparty", "Asset", "In", "Out"])
        if not df_ext.empty and "Date" in df_ext.columns:
            ext_ytd = df_ext[df_ext["Date"] >= start_of_year].groupby(["Counterparty", "Asset"])["Amount"].agg([
                ('In', lambda s: s[s < 0].sum()), ('Out', lambda s: s[s > 0].sum())
            ]).reset_index()

        merged_ext = pd.merge(ext_pre, ext_ytd, on=["Counterparty", "Asset"], how="outer").fillna(0.0)
        merged_ext = merged_ext.rename(columns={"Amount": "Reported"})
        merged_ext["Final_Bal"] = merged_ext["Reported"] + merged_ext["In"] + merged_ext["Out"]

        for _, r in merged_ext.iterrows():
            if abs(r["Final_Bal"]) > 1e-8:
                raw_cp = resolve_raw_addr(r["Counterparty"])

                # LOGIC: If it's a known circuit, we label it but EXCLUDE from VGP details
                # If it's NOT a known circuit (likely a missing owner or position), we keep it as a receivable
                is_circuit = raw_cp in circuit_addrs
                label = circuit_labels.get(raw_cp, pos_labels.get(raw_cp, f"External/CEX: {r['Counterparty']}"))

                p = asset_prices.get(r["Asset"], 0.0)
                # For a receivable, journal outflow (neg) is asset entry (pos)
                # and journal inflow (pos) is asset exit (neg)
                val_eur = (-r["Final_Bal"]) * p

                is_position = raw_cp in pos_labels
                details.append({
                    "Location": label, "Asset": r["Asset"],
                    "Report": -r["Reported"],
                    "Entrées": abs(r["In"]), # Journal outflow is Receivable inflow
                    "Sorties": -abs(r["Out"]), # Journal inflow is Receivable outflow
                    "Solde": -r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": val_eur,
                    "Is_Circuit": is_circuit, # Meta field for filtering
                    "Is_Position": is_position
                })

    # --- C. MANUAL POSITIONS ---
    start_manual = pd.DataFrame(columns=["Account", "Asset", "Amount"])
    if starting_balances:
        df_s = pd.concat(starting_balances)
        if not df_s.empty and all(c in df_s.columns for c in ["Location", "Amount"]):
            # Amount is already normalized above
            mask_m = df_s["Location"].str.startswith("Manual Position:", na=False)
            start_manual_df = df_s[mask_m].copy()
            start_manual_df["Account"] = start_manual_df["Location"].str.replace("Manual Position: ", "", regex=False).apply(standardize_address_string)
            start_manual = start_manual_df.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

    if not df_m.empty or not start_manual.empty:
        m_pre = pd.DataFrame(columns=["Account", "Asset", "Amount"])
        if not df_m.empty and "Date" in df_m.columns:
            # UNIFICATION CASE (Lowering/resolving accounts)
            df_m = standardize_df_addresses(df_m)

            # Map Quantité to Amount for unified balance logic
            m_pre_df = df_m[df_m["Date"] < start_of_year].copy()
            # Robust mapping for manual positions
            q_col = "Quantité" if "Quantité" in m_pre_df.columns else "Amount" if "Amount" in m_pre_df.columns else None
            if q_col:
                m_pre_df["Amount"] = pd.to_numeric(m_pre_df[q_col], errors="coerce").fillna(0.0)
            else:
                m_pre_df["Amount"] = 0.0

            m_pre = m_pre_df.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

        if len(start_manual) > 0:
            m_pre = pd.concat([m_pre, start_manual]).groupby(["Account", "Asset"])["Amount"].sum().reset_index()

        m_ytd = pd.DataFrame(columns=["Account", "Asset", "In", "Out"])
        if not df_m.empty and "Date" in df_m.columns:
            # df_m already standardized above
            m_ytd_df = df_m[df_m["Date"] >= start_of_year].copy()
            q_col = "Quantité" if "Quantité" in m_ytd_df.columns else "Amount" if "Amount" in m_ytd_df.columns else None
            if q_col:
                m_ytd_df["Amount"] = pd.to_numeric(m_ytd_df[q_col], errors="coerce").fillna(0.0)
            else:
                m_ytd_df["Amount"] = 0.0

            m_ytd = m_ytd_df.groupby(["Account", "Asset"])["Amount"].agg([
                ('In', lambda s: s[s > 0].sum()), ('Out', lambda s: s[s < 0].sum())
            ]).reset_index()

        merged_m = pd.merge(m_pre, m_ytd, on=["Account", "Asset"], how="outer").fillna(0.0)
        # Use existing 'Amount' as 'Reported' for manual positions
        merged_m = merged_m.rename(columns={"Amount": "Reported"})
        merged_m["Final_Bal"] = merged_m["Reported"] + merged_m["In"] + merged_m["Out"]
        for _, r in merged_m.iterrows():
            if abs(r["Final_Bal"]) > 1e-8:
                p = asset_prices.get(r["Asset"], 0.0)
                details.append({
                    "Location": f"Manual Position: {r['Account']}", "Asset": r["Asset"],
                    "Report": r["Reported"], "Entrées": r["In"],
                    "Sorties": r["Out"], # Preserve sign
                    "Solde": r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": r["Final_Bal"] * p,
                    "Is_Circuit": False, "Is_Position": True
                })

    full_details = pd.DataFrame(details)

    if not full_details.empty:
        if "Is_Circuit" not in full_details.columns: full_details["Is_Circuit"] = False
        if "Is_Position" not in full_details.columns: full_details["Is_Position"] = False
        full_details["Is_Position"] = full_details["Is_Position"].fillna(False)

    # Calculate Total VGP: We EXCLUDE rows marked as 'Is_Circuit'
    if not full_details.empty:
        mask_vgp = (full_details["Is_Circuit"] != True)
        total_vgp = full_details[mask_vgp]["Valeur (EUR)"].sum()
    else:
        total_vgp = 0.0

    return full_details, total_vgp

def load_position_labels():
    """Loads and unifies protocol position labels."""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Handle both {addr: label} and {addr: {label: x, ...}}
                unified = {}
                for k, v in data.items():
                    label = v.get("label") if isinstance(v, dict) else v
                    unified[str(k).lower()] = label
                return unified
        except: return {}
    return {}

def save_position_labels(data):
    """Saves protocol position labels."""
    lower_data = {str(k).lower(): v for k, v in data.items()}
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(lower_data, f, indent=4)

def load_external_circuits():
    if os.path.exists(EXTERNAL_CIRCUITS_FILE):
        try:
            with open(EXTERNAL_CIRCUITS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # UNIFICATION
                data["labels"] = {str(k).lower(): v for k, v in data.get("labels", {}).items()}
                data["hidden"] = [str(x).lower() for x in data.get("hidden", [])]
                return data
        except: return {"labels": {}, "hidden": []}
    return {"labels": {}, "hidden": []}

def save_external_circuits(data):
    # UNIFICATION
    data["labels"] = {str(k).lower(): v for k, v in data.get("labels", {}).items()}
    data["hidden"] = [str(x).lower() for x in data.get("hidden", [])]
    with open(EXTERNAL_CIRCUITS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_owner_accounts():
    if os.path.exists(OWNERS_FILE):
        try:
            with open(OWNERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # UNIFICATION
                return {str(k).lower(): v for k, v in data.items()}
        except: return {}
    return {}

def save_owner_accounts(data):
    # UNIFICATION
    lower_data = {str(k).lower(): v for k, v in data.items()}
    with open(OWNERS_FILE, "w", encoding="utf-8") as f:
        json.dump(lower_data, f, indent=4)

def get_all_labels():
    """Returns a merged dictionary of all technical IDs and their friendly labels."""
    merged = load_owner_accounts()
    merged.update(load_position_labels())
    ext = load_external_circuits()
    merged.update(ext.get("labels", {}))
    return merged

def load_manual_notes():
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_manual_notes(notes_dict):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(notes_dict, f, indent=4)

def get_note_key(row):
    """Generates a stable key for a transaction row to associate a note."""
    # Ensure date handling (Force UTC for key consistency)
    raw_date = row.get("Date")
    if pd.isna(raw_date) or str(raw_date).lower() == "nat": date_str = "NoDate"
    else:
        try: date_str = pd.to_datetime(raw_date, utc=True).strftime("%Y%m%d_%H%M%S")
        except: date_str = str(raw_date)

    # Technical fields with aliases
    h = row.get("Tx Hash")
    if pd.isna(h) or str(h).lower() in ["nan", "none", ""]: h = ""
    else: h = str(h).strip()

    acc = row.get("Account")
    if acc is None: acc = row.get("Compte", "")
    acc = str(acc).lower().strip()
    if acc == "nan": acc = ""

    asset = row.get("Asset")
    if asset is None: asset = row.get("Asset Vendu", "")
    asset = str(asset).upper().strip()
    if asset == "NAN": asset = ""

    # Robust amount detection (handles 'Amount' or 'Solde' for snapshots or 'Quantité')
    amt_val = row.get("Amount")
    if amt_val is None or pd.isna(amt_val): amt_val = row.get("Solde")
    if amt_val is None or pd.isna(amt_val): amt_val = row.get("Quantité")
    if amt_val is None or pd.isna(amt_val): amt_val = 0.0

    # Force absolute amount for key to handle sign diffs between view/journal
    # We round to 6 decimals for the key to handle minor floating point diffs in UI
    amt_str = f"{abs(float(amt_val)):.6f}"
    return f"{date_str}_{acc}_{asset}_{amt_str}_{h}"

def auto_register_owner(addr_str):
    """Adds an address to owner_accounts.json if it looks like a hex address and is missing."""
    raw = resolve_raw_addr(addr_str)
    if not raw.startswith("0x") or len(raw) < 40:
        return False

    owners = load_owner_accounts()
    if raw not in owners:
        owners[raw] = f"Auto-Discovered ({raw[:6]}...)"
        save_owner_accounts(owners)
        return True
    return False

def get_owner_addresses(journal_df=None):
    """
    Extracts unique owner addresses (lower hex) from mappings and journals.
    """
    owners_map = load_owner_accounts()
    owners = set(owners_map.keys())
    if journal_df is not None and "Account" in journal_df.columns:
        for a in journal_df["Account"].dropna().unique():
            r = resolve_raw_addr(a)
            if r.startswith("0x"): owners.add(r)
    return owners

def get_owner_display_list(journal_df=None):
    """
    Returns a deduplicated list of formatted owner strings for UI selection.
    Guarantees that each unique identity (linked by owner_accounts.json) appears only once.
    Priority is given to Hex addresses as the primary identifier.
    """
    all_labels = get_all_labels() # addr -> label
    # Reverse map: label -> addr
    label_to_id = {str(v).lower(): k for k, v in all_labels.items() if str(v).lower() != "nan"}

    # 1. Collect all identifiers from all sources
    all_raw_ids = set(all_labels.keys())
    # Add labels that are values in the map (to handle if they appear in journals)
    all_raw_ids.update([str(v).strip() for v in all_labels.values() if str(v).lower() != "nan"])

    if journal_df is not None and "Account" in journal_df.columns:
        all_raw_ids.update([str(a).strip() for a in journal_df["Account"].dropna().unique()])

    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            p = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
            if os.path.exists(p):
                try:
                    df = pd_read_csv_safe(p)
                    # --- ZÉRO SPAM ---
                    df = apply_spam_filter(df, drop=True)
                    if "Account" in df.columns:
                        all_raw_ids.update([str(a).strip() for a in df["Account"].dropna().unique()])
                except: pass

    # 2. Unify identifiers into identities
    # identity_registry: normalized_primary_key -> {"ident": best_technical_id, "name": friendly_label}
    identity_registry = {}

    for raw_id in all_raw_ids:
        if not raw_id: continue
        low_id = raw_id.lower()

        # Determine the primary key for this identity
        if low_id.startswith("0x"):
            prim_key = low_id
        elif low_id in label_to_id:
            prim_key = label_to_id[low_id]
        else:
            prim_key = low_id # Orphan label

        name = all_labels.get(prim_key, "")

        if prim_key not in identity_registry:
            identity_registry[prim_key] = {"ident": raw_id, "name": name}
        else:
            # Upgrade primary ident if we find a hex for a label-only entry
            if raw_id.lower().startswith("0x") and not identity_registry[prim_key]["ident"].lower().startswith("0x"):
                identity_registry[prim_key]["ident"] = raw_id
            # Ensure name is captured
            if not identity_registry[prim_key]["name"] and name:
                identity_registry[prim_key]["name"] = name

    # 3. Final formatting
    results = []
    for k, data in identity_registry.items():
        results.append(format_owner_display(data["ident"], data["name"]))

    return sorted(list(set(results)))

def filter_df_by_owner_display(df, selected_displays):
    """Filters a DataFrame where 'Account' matches any selected formatted owner display."""
    if not selected_displays: return df

    all_labels = get_all_labels()
    label_to_id = {str(v).lower(): k for k, v in all_labels.items() if str(v).lower() != "nan"}

    # Map of all allowed raw identifiers
    allowed_ids = set()
    for disp in selected_displays:
        # Extract components from 'Address (Name)' or 'Name (Label)'
        if " (" in disp and disp.endswith(")"):
            p1 = disp.split(" (")[0].lower()
            p2 = disp.split(" (")[1][:-1].lower()
            allowed_ids.add(p1)
            allowed_ids.add(p2)
            # IMPORTANT: Also add the full string itself for exact matches in standardized dataframes
            allowed_ids.add(disp.lower())
        else:
            allowed_ids.add(disp.lower())

    def row_matches(acc):
        a = str(acc).lower().strip()
        # 1. Direct match with allowed IDs or the full display string
        if a in allowed_ids: return True

        # 2. Check if the input 'acc' is already standardized 'ID (Name)'
        raw_id_from_acc = resolve_raw_addr(a).lower()
        if raw_id_from_acc in allowed_ids: return True

        # 3. Check mapping links
        if raw_id_from_acc in all_labels and all_labels[raw_id_from_acc].lower() in allowed_ids: return True
        if raw_id_from_acc in label_to_id and label_to_id[raw_id_from_acc].lower() in allowed_ids: return True

        return False

    return df[df["Account"].apply(row_matches)]

def get_external_circuits_discovery(journal_df=None):
    """
    Discovers valid transient addresses (not owners, not positions) using RECURSIVE DISCOVERY RULE.
    Rule:
    1. Exclude Spams.
    2. Exclude already declared Owners/Positions.
    3. Collect accounts having Txs with Owners/Positions (Level 1).
    4. Collect accounts having Txs with Level N collected accounts (Level 2+).
    """
    owner_addrs = set(get_owner_addresses(journal_df))
    pos_labels = load_position_labels()
    pos_addrs = set(pos_labels.keys())

    # Build the interaction graph from all available journals
    # Graph format: {addr: {neighbor: {count, volume_usd, last_asset}}}
    adj = {}

    all_journals = []
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
            if os.path.exists(path):
                try: all_journals.append(pd_read_csv_safe(path))
                except: pass
    if journal_df is not None: all_journals.append(journal_df)

    for df in all_journals:
        if df.empty or "Status" not in df.columns: continue
        # Rule 1: Exclude Spams
        df_val = df[df["Status"] != "Spam"]
        for _, r in df_val.iterrows():
            acc = resolve_raw_addr(r.get("Account", ""))
            cp = resolve_raw_addr(r.get("Counterparty", ""))
            if not acc or not cp: continue

            vol = abs(float(r.get("Value ($)", 0.0)))
            asset = str(r.get("Asset", ""))

            for src, dst in [(acc, cp), (cp, acc)]:
                if src not in adj: adj[src] = {}
                if dst not in adj[src]: adj[src][dst] = {"count": 0, "volume_usd": 0.0, "last_asset": ""}
                adj[src][dst]["count"] += 1
                adj[src][dst]["volume_usd"] += vol
                adj[src][dst]["last_asset"] = asset

    # Recursive collection logic
    # Initial seeds: declared Owners and Positions
    seeds = owner_addrs.union(pos_addrs)
    collected = set()
    to_visit = list(seeds)
    visited = set()

    # We perform a BFS to discover the component connected to owners/positions
    while to_visit:
        curr = to_visit.pop(0)
        visited.add(curr)

        neighbors = adj.get(curr, {})
        for n in neighbors:
            # Rule 2: Exclude Declared Owners/Positions from the "Circuits" list itself
            if n not in seeds:
                if n not in collected:
                    collected.add(n)
                    # Rule 4: Recursive (add to visit queue to find neighbors of neighbors)
                    if n not in visited:
                        to_visit.append(n)

    # Filter out hidden/already labeled ones
    ext_data = load_external_circuits()
    labels = ext_data.get("labels", {})
    hidden = set(ext_data.get("hidden", []))

    # Aggregating stats for collected circuits
    final_list = []
    for addr in collected:
        if addr not in hidden:
            # Aggregate stats from all neighbors
            stats = {"count": 0, "volume_usd": 0.0, "last_asset": ""}
            for n, s in adj.get(addr, {}).items():
                stats["count"] += s["count"]
                stats["volume_usd"] += s["volume_usd"]
                stats["last_asset"] = s["last_asset"]

            final_list.append({
                "Address": addr,
                "Label": labels.get(addr, ""),
                "Tx Count": stats["count"],
                "Vol. USD": stats["volume_usd"],
                "Asset": stats["last_asset"]
            })

    return sorted(final_list, key=lambda x: x["Vol. USD"], reverse=True)

def get_known_accounts(include_mappings=True):
    """Aggregates account names from mapping file and all qualified journals."""
    known = set()

    # 1. From Designated Owners File (owner_accounts.json)
    if include_mappings and os.path.exists(OWNERS_FILE):
        try:
            with open(OWNERS_FILE, "r", encoding="utf-8") as f:
                owners = json.load(f)
                for val in owners.values():
                    known.add(val)
        except: pass

    # 2. From Protocol Mappings (position_labels.json)
    if include_mappings and os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                mappings = json.load(f)
                for val in mappings.values():
                    if isinstance(val, dict):
                        known.add(val.get("label", ""))
                    else:
                        known.add(val)
        except: pass

    # 3. From Journals (all years)
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

def load_spam_list():
    """Loads the global spam blacklist."""
    if os.path.exists(SPAM_FILE):
        try:
            with open(SPAM_FILE, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                return {str(x).lower() for x in data}
        except: return set()
    return set()

def save_spam_list(spam_set):
    """Saves the global spam blacklist."""
    with open(SPAM_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(spam_set)), f, indent=4)

def load_valid_assets():
    """Loads the whitelist of valid assets."""
    if os.path.exists(VALID_ASSETS_FILE):
        try:
            with open(VALID_ASSETS_FILE, "r", encoding="utf-8") as f:
                return {str(x).upper().strip() for x in json.load(f)}
        except: return set()
    return set()

def save_valid_assets(assets_set):
    """Saves the whitelist of valid assets."""
    with open(VALID_ASSETS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(assets_set)), f, indent=4)

def apply_spam_filter(df, drop=True):
    """
    Centralized spam filter. Identifies spams using the global blacklist.
    - Matches on 'Asset' (normalized) and 'Counterparty' (resolved address).
    - In 'Qualified' mode: looks at 'Status' column.
    - In 'Raw' mode: looks at 'Audit_Status' column.
    - WHITELIST PROTECTION: Whitelisted assets are NEVER considered spam.
    If drop=True: returns a dataframe EXCLUDING spams.
    If drop=False: returns the dataframe with 'Status' or 'Audit_Status' updated to 'Spam'.
    """
    if df is None or df.empty: return df

    spam_list = load_spam_list()
    valid_assets = load_valid_assets()
    if not spam_list: return df

    df = df.copy()

    # 1. Identify Target Column
    status_col = "Status" if "Status" in df.columns else "Audit_Status" if "Audit_Status" in df.columns else None

    def check_row_spam(row):
        # 0. WHITELIST PROTECTION: Never spam if whitelisted
        asset_raw = str(row.get("Asset", "")).upper().strip()
        if asset_raw in valid_assets: return False

        # 1. Check current status if exists
        if status_col and str(row.get(status_col)) == "Spam": return True

        # 2. Check Counterparty address
        cp_val = row.get("Counterparty", "")
        if cp_val and str(cp_val).lower() not in ["nan", "none", ""]:
            cp_raw = resolve_raw_addr(cp_val).lower()
            if cp_raw in spam_list: return True

        # 3. Check Asset name
        asset_low = str(row.get("Asset", "")).lower().strip()
        if asset_low and asset_low not in ["nan", "none", ""] and asset_low in spam_list:
            return True

        return False

    is_spam_mask = df.apply(check_row_spam, axis=1)

    if drop:
        # Also exclude duplicates if dropping
        if "Category" in df.columns:
            # Robust check for category containing 'Doublon'
            is_dup = df["Category"].fillna("").str.contains("Doublon", case=False, na=False)
            is_spam_mask |= is_dup
        return df[~is_spam_mask].reset_index(drop=True)
    else:
        if status_col:
            df.loc[is_spam_mask, status_col] = "Spam"
        return df

def validate_spam_exclusion(df):
    """Legacy wrapper: returns indices of leaked spams."""
    if df is None or df.empty: return []
    filtered = apply_spam_filter(df, drop=False)
    status_col = "Status" if "Status" in df.columns else "Audit_Status"

    # Find rows where we just changed the status to Spam but it wasn't Spam before
    leaked_mask = (filtered[status_col] == "Spam") & (df[status_col] != "Spam")
    return df.index[leaked_mask].tolist()

def detect_internal_transfers(df):
    """
    Identifies internal transfers between owned accounts.
    Returns the updated dataframe and a dictionary of counts.
    """
    if df.empty: return df, {"hash": 0, "account": 0}

    # Ensure addresses are standardized for detection
    df = standardize_df_addresses(df)

    count_h = 0
    count_acc = 0

    # 1. Detection by Tx Hash
    if "Tx Hash" in df.columns:
        # Standardize hashes
        df["Tx Hash"] = df["Tx Hash"].fillna("").astype(str).str.strip()
        hashes = df[df["Tx Hash"].duplicated(keep=False)]["Tx Hash"].unique()
        for h in hashes:
            if not h or len(h) < 10 or h.lower() in ["nan", "none", "0"]: continue
            mask = df["Tx Hash"] == h
            # If same hash appears twice in our journal, it's a transfer between two of our accounts.
            if len(df[mask]) >= 2:
                df.loc[mask, "Category"] = "Transfert Interne"
                df.loc[mask, "Status"] = "Valide"
                count_h += 1

    # 2. Detection by Owned Account/Counterparty
    # Robust Detection: prioritizes verified owners then discovery
    all_my_accounts = get_owner_addresses()
    # Also add display names from the current journal
    all_my_accounts.update([str(a).lower() for a in df["Account"].dropna().unique()])

    def is_internal(cp_str):
        raw = resolve_raw_addr(cp_str)
        # Check against both hex addresses and known labels (as fallback)
        return raw in all_my_accounts

    mask_internal = df["Counterparty"].fillna("").apply(is_internal)
    if mask_internal.any():
        # User requested automatic identification.
        df.loc[mask_internal, "Category"] = "Transfert Interne"
        df.loc[mask_internal, "Status"] = "Valide"
        count_acc = mask_internal.sum()

    return df, {"hash": count_h, "account": count_acc}

def find_reconciliation_matches(df, time_window_days=3, val_tolerance_pct=0.05):
    """
    Analyzes the journal to propose links between Orphan transactions.
    Supports Fiat-to-Crypto, Crypto-to-Crypto, and Fiat-to-Fiat.
    """
    if df.empty: return df, 0

    df = df.copy()
    # Unification
    df = standardize_df_addresses(df)
    if "Linked_ID" not in df.columns: df["Linked_ID"] = ""
    if "Link_Status" not in df.columns: df["Link_Status"] = ""

    # Filter for candidates: Status Valid or A verifier, and not confirmed linked
    mask_candidates = (df["Status"] != "Spam") & (df["Link_Status"] != "Confirmed")
    candidates = df[mask_candidates].copy()

    if candidates.empty: return df, 0

    count_proposed = 0
    import uuid

    # Sort by date to facilitate matching
    if "Date" not in candidates.columns: return df, 0
    candidates = candidates.sort_values("Date")

    # 1. Separate Potential Legs
    # Outbound: Bank exits, Crypto exits
    exits = candidates[candidates["Amount"] < 0].copy()
    # Inbound: Crypto entries, Bank entries
    entries = candidates[candidates["Amount"] > 0].copy()

    used_entry_indices = set()

    for idx_ex, row_ex in exits.iterrows():
        # Check if already has a proposed link from a previous pass
        if row_ex["Linked_ID"]: continue

        date_ex = row_ex["Date"]
        # Value in USD or EUR (absolute)
        val_ex = abs(float(row_ex.get("Value ($)", 0)))
        if val_ex == 0 and row_ex["Asset"] == "EUR": val_ex = abs(row_ex["Amount"]) # Assume 1:1 if EUR

        # Search window
        min_date = date_ex
        max_date = date_ex + pd.Timedelta(days=time_window_days)

        potential_entries = entries[
            (entries["Date"] >= min_date) &
            (entries["Date"] <= max_date) &
            (~entries.index.isin(used_entry_indices))
        ]

        for idx_en, row_en in potential_entries.iterrows():
            # Check Counterparty match? (User mentioned "enchainement de contreparties")
            # If Bank Exit CP matches Entry Account (or CP matches Account Label)
            cp_ex = resolve_raw_addr(row_ex["Counterparty"]).lower()
            acc_en = resolve_raw_addr(row_en["Account"]).lower()

            # Match if:
            # - Counterparty name matches Account name (fuzzy)
            # - OR values are very close
            val_en = abs(float(row_en.get("Value ($)", 0)))
            if val_en == 0 and row_en["Asset"] == "EUR": val_en = abs(row_en["Amount"])

            val_diff = abs(val_ex - val_en)
            val_match = False
            if val_ex > 0:
                 val_match = (val_diff / val_ex) <= val_tolerance_pct
            elif val_en == 0 and val_ex == 0:
                 val_match = True # Both zero value (e.g. unknown price)

            name_match = (cp_ex in acc_en or acc_en in cp_ex or cp_ex in str(row_en["Account"]).lower())

            if name_match and val_match:
                # Propose Link
                link_id = f"PROP-{uuid.uuid4().hex[:8]}"
                df.at[idx_ex, "Linked_ID"] = link_id
                df.at[idx_ex, "Link_Status"] = "Proposed"
                df.at[idx_en, "Linked_ID"] = link_id
                df.at[idx_en, "Link_Status"] = "Proposed"
                used_entry_indices.add(idx_en)
                count_proposed += 1
                break # Move to next exit

    return df, count_proposed

def load_clean_history(end_year, start_year=2020):
    """Loads consolidated clean journals from start_year to end_year."""
    all_dfs = []
    for y in range(start_year, end_year + 1):
        # Prefer CLEAN, fallback to qualified (which will be filtered anyway)
        p_clean = get_file_path(y, 'qualified_clean')
        if os.path.exists(p_clean):
            df = pd_read_csv_safe(p_clean)
        else:
            p_qual = get_file_path(y, 'qualified')
            if os.path.exists(p_qual):
                df = pd_read_csv_safe(p_qual)
                df = apply_spam_filter(df, drop=True)
            else:
                df = pd.DataFrame()

        if not df.empty:
             df = standardize_df_addresses(df)
             if 'Date' in df.columns:
                 df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')
             all_dfs.append(df)

    if not all_dfs: return pd.DataFrame()
    return pd.concat(all_dfs).sort_values("Date", ascending=False).reset_index(drop=True)

def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

def get_total_acquisition_value(target_year):
    """Sums all fiat purchases from all years up to target_year."""
    total = 0.0
    for y in range(2020, target_year + 1):
        path = get_file_path(y, 'fiat')
        if os.path.exists(path):
            try:
                df = pd_read_csv_safe(path)
                if not df.empty and "Type" in df.columns and "Montant EUR" in df.columns:
                    # Filter for 'Achat' types (Euros moving into Crypto)
                    mask = df['Type'].str.contains("Achat", case=False, na=False)
                    total += df[mask]['Montant EUR'].sum()
            except: pass
    return total

def calculate_fiscal_gains(cessions_df, initial_acq_price):
    """
    Calculates capital gains according to Art 150 VH bis.
    cessions_df: DataFrame with columns [Date, Prix de Cession (EUR), VGP (EUR)]
    initial_acq_price: Float
    Returns: DataFrame of results, final remaining acquisition price
    """
    if cessions_df.empty:
        return pd.DataFrame(), initial_acq_price

    results = []
    temp_acq = initial_acq_price

    # Sort chronologically as required by French law
    if "Date" not in cessions_df.columns: return pd.DataFrame(), initial_acq_price
    cessions_sorted = cessions_df.sort_values("Date", ascending=True)

    for idx, row in cessions_sorted.iterrows():
        pc = float(row.get('Prix de Cession (EUR)', 0))
        vgp = float(row.get('VGP (EUR)', 0))

        if vgp > 0:
            # Rule: Abatement ratio capped at 1.0
            ratio = min(1.0, pc / vgp)
            fraction_acq = temp_acq * ratio
            # Cannot abate more than remaining capital
            fraction_acq = min(temp_acq, fraction_acq)

            pv = pc - fraction_acq
            results.append({
                "Date": row['Date'],
                "Asset": row.get('Asset', 'Unknown'),
                "Prix Cession": pc,
                "VGP": vgp,
                "Abattement Acq": fraction_acq,
                "Plus-Value Brute": pv,
                "Capital Restant": temp_acq - fraction_acq
            })
            temp_acq = max(0.0, temp_acq - fraction_acq)
        else:
            # VGP <= 0 is an error or special case (should be handled/flagged before)
            pass

    return pd.DataFrame(results), temp_acq

def remove_row_from_csv(file_path, row_to_remove):
    """
    Removes a specific row from a CSV file using a matching quintuplet.
    """
    if not os.path.exists(file_path): return False
    try:
        df = pd_read_csv_safe(file_path)
        if df.empty: return False

        # We normalize the file for comparison
        # Find column mappings
        h_map = {c.lower().replace(" ", "").replace("_", ""): c for c in df.columns}

        mask = pd.Series([True] * len(df))

        # Quintuplet matching
        match_keys = {
            "Date": ["date"],
            "Account": ["account"],
            "Asset": ["asset", "tokensymbol"],
            "Amount": ["amount", "valueeth", "value", "quantity"],
            "Tx Hash": ["txhash", "hash"]
        }

        for k, alternates in match_keys.items():
            target_col = None
            for alt in alternates:
                if alt in h_map:
                    target_col = h_map[alt]
                    break

            if target_col:
                val = row_to_remove.get(k)
                if val is None and k == "Amount":
                    val = row_to_remove.get("Quantité") or row_to_remove.get("Montant")

                if k == "Date":
                    try:
                        d1 = pd.to_datetime(df[target_col], utc=True, errors='coerce')
                        d2 = pd.to_datetime(val, utc=True, errors='coerce')
                        mask &= (d1 == d2)
                    except: pass
                elif k == "Amount":
                    try:
                        v1 = pd.to_numeric(df[target_col], errors='coerce').fillna(0.0)
                        v2 = float(val)
                        # We try exact match, then absolute match as fallback (for legacy or unsigned files)
                        m_exact = (abs(v1 - v2) < 1e-8)
                        if not m_exact.any():
                             mask &= (abs(v1.abs() - abs(v2)) < 1e-8)
                        else:
                             mask &= m_exact
                    except: pass
                else:
                    mask &= (df[target_col].astype(str).str.lower().str.strip() == str(val).lower().strip())

        if mask.any():
            df_new = df[~mask]
            df_new.to_csv(file_path, index=False, encoding="utf-8-sig")
            return True
    except: pass
    return False

def inject_to_app0(rows_list, target_type, year):
    """
    Appends specific transactions to the app0 registries.
    target_type: 'Fiat' or 'Swap'
    """
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    os.makedirs(year_dir, exist_ok=True)

    if target_type == "Fiat":
        path = os.path.join(year_dir, f"manual_fiat_{year}.csv")
        # App0 Fiat Schema: Date, Account, Counterparty, Compte/Label, Plateforme, Montant EUR, Type, Asset, Quantité, Tx Hash, Imposable
        existing_df = pd_read_csv_safe(path) if os.path.exists(path) else pd.DataFrame()

        new_data = []
        for r in rows_list:
            dt_raw = pd.to_datetime(r.get("Date")).date() if r.get("Date") else ""
            # Default Counterparty to "banq fiat" as requested
            cp_val = r.get("Counterparty", "")
            if not cp_val or str(cp_val).lower() == "nan":
                cp_val = "banq fiat"

            new_data.append({
                "Date": dt_raw,
                "Account": r.get("Account", ""),
                "Counterparty": cp_val,
                "Compte/Label": r.get("Account", ""),
                "Plateforme": cp_val,
                "Montant EUR": 0.0, # TO BE FILLED BY USER IN APP0
                "Type": "Achat (Virement vers Crypto)" if r.get("Amount", 0) > 0 else "Vente (Retour vers Banque)",
                "Asset": r.get("Asset", ""),
                "Quantité": abs(float(r.get("Amount", 0))),
                "Tx Hash": r.get("Tx Hash", ""),
                "Imposable": r.get("Imposable", False)
            })

        updated_df = pd.concat([existing_df, pd.DataFrame(new_data)]).reset_index(drop=True)
        updated_df.to_csv(path, index=False, encoding="utf-8-sig")
        return len(new_data)

    elif target_type == "Swap":
        path = os.path.join(year_dir, f"manual_swaps_{year}.csv")
        # App0 Swaps Schema: Date, Account, Counterparty, Asset, Amount, Type, Tx Hash, Source Type, Imposable
        existing_df = pd_read_csv_safe(path) if os.path.exists(path) else pd.DataFrame()

        new_data = []
        for r in rows_list:
             dt_raw = pd.to_datetime(r.get("Date")).date() if r.get("Date") else ""
             amt = float(r.get("Amount", 0))
             new_data.append({
                 "Date": dt_raw,
                 "Account": r.get("Account", ""),
                 "Counterparty": r.get("Counterparty", ""),
                 "Asset": r.get("Asset", ""),
                 "Amount": amt,
                 "Type": "Swap In" if amt > 0 else "Swap Out",
                 "Tx Hash": r.get("Tx Hash", ""),
                 "Source Type": "Transfer from App2",
                 "Imposable": r.get("Imposable", False)
             })

        updated_df = pd.concat([existing_df, pd.DataFrame(new_data)]).reset_index(drop=True)
        updated_df.to_csv(path, index=False, encoding="utf-8-sig")
        return len(new_data)

    return 0

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

    # Use the standardized display list logic
    owner_displays = get_owner_display_list()
    st.write(f"Nombre d'identités propriétaires uniques : `{len(owner_displays)}`")

    if st.checkbox("Voir la liste ordonnée des comptes"):
        for disp in owner_displays:
            st.markdown(f"- {disp}")
