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

def get_file_path(year, category):
    """Centralized path resolution for all apps."""
    base = os.path.join(EXPORT_BASE_DIR, str(year))
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
    if category == 'inventory_eoy':
        return os.path.join(base, f"inventory_EOY_{year}.csv")
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
    ts_pattern = re.compile(r'_(\d{8}(?:_\d{6})?)$')

    for f_path in all_raw:
        f = os.path.basename(f_path)
        basename = f.replace(".csv", "")

        match = ts_pattern.search(basename)
        prefix = basename[:match.start()] if match else basename

        if prefix not in latest_map:
            latest_map[prefix] = f_path
        else:
            if f_path > latest_map[prefix]:
                latest_map[prefix] = f_path

    return list(latest_map.values())

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

def get_portfolio_snapshot(journal_or_year, target_date):
    """
    Factual Account-based calculation of VGP.
    journal_or_year: either a dataframe or a year (int) to load current year data.
    Uses inventory_EOY_{year-1}.csv as a starting point if available.
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
    target_year_val = target_date.year
    start_of_year = datetime(target_year_val, 1, 1, tzinfo=target_date.tzinfo)

    journals_to_process = []
    manual_to_process = []
    starting_balances = [] # List of DataFrames: [Location, Asset, Solde]

    # 1. Try to find the latest sanctuarized inventory before target_year_val
    found_inventory = False
    for y_inv in range(target_year_val - 1, 2019, -1):
        inv_path = os.path.join(EXPORT_BASE_DIR, str(y_inv), f"inventory_EOY_{y_inv}.csv")
        if os.path.exists(inv_path):
            try:
                df_inv = pd_read_csv_safe(inv_path)
                # Map EOY format to snapshot internal logic
                # EOY typically has: Location, Asset, Solde, ...
                if not df_inv.empty:
                    df_start = df_inv[["Location", "Asset", "Solde"]].copy()
                    df_start = df_start.rename(columns={"Solde": "Amount"})
                    starting_balances.append(df_start)
                    found_inventory = True
                    start_scan_year = y_inv + 1
                    break
            except: pass

    if not found_inventory:
        start_scan_year = 2020

    # 2. Load journals from start_scan_year to target_year_val
    for y in range(start_scan_year, target_year_val + 1):
        if y == target_year_val and isinstance(journal_or_year, pd.DataFrame):
            df_y = journal_or_year.copy()
            df_y["Date"] = pd.to_datetime(df_y["Date"], utc=True, errors="coerce")
            journals_to_process.append(df_y[df_y["Date"] <= target_date])
        else:
            path_j = os.path.join(EXPORT_BASE_DIR, str(y), f"qualified_journal_{y}.csv")
            if os.path.exists(path_j):
                try:
                    df_y = pd_read_csv_safe(path_j)
                    df_y["Date"] = pd.to_datetime(df_y["Date"], utc=True, errors="coerce")
                    journals_to_process.append(df_y[df_y["Date"] <= target_date])
                except: pass

        path_m = os.path.join(EXPORT_BASE_DIR, str(y), f"manual_positions_{y}.csv")
        if os.path.exists(path_m):
            try:
                tmp_m = pd_read_csv_safe(path_m)
                tmp_m["Date"] = pd.to_datetime(tmp_m["Date"], utc=True, errors="coerce")
                manual_to_process.append(tmp_m[tmp_m["Date"] <= target_date])
            except: pass

    if not journals_to_process and not manual_to_process and not starting_balances:
        return pd.DataFrame(), 0.0

    df_j = pd.concat(journals_to_process) if journals_to_process else pd.DataFrame()
    df_m = pd.concat(manual_to_process) if manual_to_process else pd.DataFrame()

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

    # Identify owned accounts by address if possible, otherwise by name
    owned_names = set(df_j["Account"].dropna().unique()) if not df_j.empty else set()
    owned_addrs = set()
    for n in owned_names:
        res = resolve_raw_addr(n)
        if res.startswith("0x"): owned_addrs.add(res)

    # --- A. OWNED ACCOUNTS ---
    # Merge starting balances for Owned Accounts
    # Account format in inventory: "Account: Name"
    start_wallets = []
    if starting_balances:
        df_s = pd.concat(starting_balances)
        mask_w = df_s["Location"].str.startswith("Account:", na=False)
        start_wallets_df = df_s[mask_w].copy()
        start_wallets_df["Account"] = start_wallets_df["Location"].str.replace("Account: ", "")
        start_wallets = start_wallets_df.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

    if not df_j.empty or len(start_wallets) > 0:
        # Pre-YTD (from start_scan_year up to end of previous year)
        df_pre = df_j[df_j["Date"] < start_of_year]
        pre_bals = df_pre.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

        # Combine with starting balances from inventory
        if len(start_wallets) > 0:
            pre_bals = pd.concat([pre_bals, start_wallets]).groupby(["Account", "Asset"])["Amount"].sum().reset_index()

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

    # --- B. INTERNAL TRANSFER OFFSET LEGS (Receivables) ---
    start_ext = []
    if starting_balances:
        df_s = pd.concat(starting_balances)
        mask_ext = (~df_s["Location"].str.startswith("Account:", na=False)) & (~df_s["Location"].str.startswith("Manual Position:", na=False))
        start_ext = df_s[mask_ext].groupby(["Location", "Asset"])["Amount"].sum().reset_index()
        start_ext = start_ext.rename(columns={"Location": "Counterparty"})
        # Note: inventory stores Receivables with positive 'Solde'.
        # We need to flip it back to match the leg logic (leg sum is negative of receivable)
        start_ext["Amount"] = -start_ext["Amount"]

    if not df_j.empty or len(start_ext) > 0:
        ext_data = load_external_circuits()
        circuit_labels = ext_data.get("labels", {})

        mask_int = (df_j["Category"] == "Transfert Interne")
        df_ext = df_j[mask_int].copy()
        df_ext["cp_low"] = df_ext["Counterparty"].apply(resolve_raw_addr)

        # We also filter out any address identified as a "Transient External Circuit"
        circuit_addrs = set(circuit_labels.keys())
        # Filter: Counterparty must not be an owned account name AND not an owned account address
        df_ext = df_ext[ (~df_ext["Counterparty"].isin(owned_names)) & (~df_ext["cp_low"].isin(owned_addrs)) ]

        ext_pre = df_ext[df_ext["Date"] < start_of_year].groupby(["Counterparty", "Asset"])["Amount"].sum().reset_index()
        if len(start_ext) > 0:
            ext_pre = pd.concat([ext_pre, start_ext]).groupby(["Counterparty", "Asset"])["Amount"].sum().reset_index()

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
                val_eur = (-r["Final_Bal"]) * p

                details.append({
                    "Location": label, "Asset": r["Asset"],
                    "Report": -r["Reported"], "Entrées": abs(r["In"]), "Sorties": abs(r["Out"]),
                    "Solde": -r["Final_Bal"], "Prix (EUR)": p, "Valeur (EUR)": val_eur,
                    "Is_Circuit": is_circuit # Meta field for filtering
                })

    # --- C. MANUAL POSITIONS ---
    start_manual = []
    if starting_balances:
        df_s = pd.concat(starting_balances)
        mask_m = df_s["Location"].str.startswith("Manual Position:", na=False)
        start_manual_df = df_s[mask_m].copy()
        start_manual_df["Account"] = start_manual_df["Location"].str.replace("Manual Position: ", "")
        start_manual = start_manual_df.groupby(["Account", "Asset"])["Amount"].sum().reset_index()

    if not df_m.empty or len(start_manual) > 0:
        m_pre = df_m[df_m["Date"] < start_of_year].groupby(["Account", "Asset"])["Quantité"].sum().reset_index()
        if len(start_manual) > 0:
            m_pre = pd.concat([m_pre, start_manual]).groupby(["Account", "Asset"])["Amount"].sum().reset_index()
            m_pre = m_pre.rename(columns={"Amount": "Quantité"})

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

    if not full_details.empty and "Is_Circuit" not in full_details.columns:
        full_details["Is_Circuit"] = False

    # Calculate Total VGP: We EXCLUDE rows marked as 'Is_Circuit'
    if not full_details.empty:
        mask_vgp = (full_details["Is_Circuit"] != True)
        total_vgp = full_details[mask_vgp]["Valeur (EUR)"].sum()
    else:
        total_vgp = 0.0

    return full_details, total_vgp

def load_external_circuits():
    if os.path.exists(EXTERNAL_CIRCUITS_FILE):
        try:
            with open(EXTERNAL_CIRCUITS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {"labels": {}, "hidden": []}
    return {"labels": {}, "hidden": []}

def save_external_circuits(data):
    with open(EXTERNAL_CIRCUITS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_owner_accounts():
    if os.path.exists(OWNERS_FILE):
        try:
            with open(OWNERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_owner_accounts(data):
    with open(OWNERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

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

def get_owner_addresses():
    """
    Extracts all raw addresses identified as 'owners'.
    Combines verified owners from mapping file and auto-detected ones from journals.
    """
    # 1. Verified Owners (Fixed)
    owners_map = load_owner_accounts()
    owners = set(owners_map.keys())

    # 2. Auto-Discovery from Journals
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
            if os.path.exists(path):
                try:
                    df = pd_read_csv_safe(path)
                    if "Account" in df.columns:
                        for a in df["Account"].dropna().unique():
                            resolved = resolve_raw_addr(a)
                            if resolved.startswith("0x"): owners.add(resolved)
                except: pass
    return owners

def get_external_circuits_discovery():
    """Discovers valid transient addresses (not owners, not positions)."""
    owner_addrs = get_owner_addresses()

    pos_labels = {}
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                mappings = json.load(f)
                for addr, val in mappings.items():
                    pos_labels[addr] = val.get("label") if isinstance(val, dict) else val
        except: pass
    pos_addrs = set(pos_labels.keys())

    circuits_info = {} # {addr: {count, volume_usd}}

    # Scan all journals
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"qualified_journal_{y}.csv")
            if os.path.exists(path):
                try:
                    df = pd_read_csv_safe(path)
                    if not df.empty and "Status" in df.columns:
                        # Exclude only Spams from discovery
                        df_val = df[df["Status"] != "Spam"]
                        for _, r in df_val.iterrows():
                            cp_raw = resolve_raw_addr(r.get("Counterparty", ""))
                            if cp_raw and cp_raw not in owner_addrs and cp_raw not in pos_addrs:
                                if cp_raw not in circuits_info:
                                    circuits_info[cp_raw] = {"count": 0, "volume_usd": 0.0, "last_asset": ""}
                                circuits_info[cp_raw]["count"] += 1
                                circuits_info[cp_raw]["volume_usd"] += abs(float(r.get("Value ($)", 0.0)))
                                circuits_info[cp_raw]["last_asset"] = str(r.get("Asset", ""))
                except: pass

    # Filter out hidden/already labeled ones
    ext_data = load_external_circuits()
    labels = ext_data.get("labels", {})
    hidden = set(ext_data.get("hidden", []))

    final_list = []
    for addr, stats in circuits_info.items():
        if addr not in hidden:
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

    # 1. From Mappings
    if include_mappings and os.path.exists(POSITIONS_FILE):
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

def detect_internal_transfers(df):
    """
    Identifies internal transfers between owned accounts.
    Returns the updated dataframe and a dictionary of counts.
    """
    if df.empty: return df, {"hash": 0, "account": 0}

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
    if "Linked_ID" not in df.columns: df["Linked_ID"] = ""
    if "Link_Status" not in df.columns: df["Link_Status"] = ""

    # Filter for candidates: Status Valid or A verifier, and not confirmed linked
    mask_candidates = (df["Status"] != "Spam") & (df["Link_Status"] != "Confirmed")
    candidates = df[mask_candidates].copy()

    if candidates.empty: return df, 0

    count_proposed = 0
    import uuid

    # Sort by date to facilitate matching
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
            new_data.append({
                "Date": dt_raw,
                "Account": r.get("Account", ""),
                "Counterparty": r.get("Counterparty", ""),
                "Compte/Label": r.get("Account", ""),
                "Plateforme": r.get("Counterparty", ""),
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

    known_accs = get_known_accounts()
    st.write(f"Nombre de comptes connus indexés : `{len(known_accs)}`")

    if st.checkbox("Voir la liste des comptes"):
        st.write(known_accs)
