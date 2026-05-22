import os
import json
import time
import re
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

# --- Configuration Management ---

def load_global_config():
    """Loads global settings like activity start year and current processing year."""
    defaults = {
        "start_year": 2025, # Default for test reality
        "processing_year": datetime.now().year
    }
    if os.path.exists(GLOBAL_CONFIG_FILE):
        try:
            with open(GLOBAL_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("start_year"): data["start_year"] = int(data["start_year"])
                if data.get("processing_year"): data["processing_year"] = int(data["processing_year"])
                return {**defaults, **data}
        except: pass
    return defaults

def save_global_config(config):
    with open(GLOBAL_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def clean_session_state(preserve_keys=[]):
    hub_keys = [k for k in st.session_state.keys() if k.startswith("_hub_")]
    to_keep = set(preserve_keys + hub_keys)
    for k in list(st.session_state.keys()):
        if k not in to_keep:
            del st.session_state[k]

# --- Address & Identity Unification ---

def resolve_raw_addr(addr_str):
    """Extracts the pure technical identifier (hex address or label) from a display string."""
    if not addr_str or pd.isna(addr_str): return ""
    s = str(addr_str).strip().lower()
    match = re.search(r'0x[a-f0-9]{40,}', s)
    if match: return match.group(0)
    if "(" in s and ")" in s: return s.split("(")[0].strip()
    return s

def standardize_address_string(addr_str):
    """Enforces the absolute standard: 'Identifier (Name)'."""
    if not addr_str or str(addr_str).lower() in ["nan", "none", ""]: return ""
    s = str(addr_str).strip()
    raw = resolve_raw_addr(s).lower()
    mapping = get_all_labels()
    if raw in mapping: return format_owner_display(raw, mapping[raw])

    label_to_addr = {str(v).lower(): k for k, v in mapping.items() if str(v).lower() != "nan"}
    if raw in label_to_addr:
        addr = label_to_addr[raw]
        return format_owner_display(addr, mapping[addr])

    name = ""
    if "(" in s and ")" in s:
        parts = s.split("(")
        p1, p2 = parts[0].strip(), parts[1].replace(")", "").strip()
        if p1.lower().startswith("0x"): raw, name = p1.lower(), p2
        elif p2.lower().startswith("0x"): raw, name = p2.lower(), p1
        else: raw, name = p1, p2
    return format_owner_display(raw, name)

def resolve_owner_display(addr):
    raw = resolve_raw_addr(addr).lower()
    mapping = get_all_labels()
    if raw in mapping: return format_owner_display(raw, mapping[raw])
    return addr

def standardize_df_addresses(df):
    if df.empty: return df
    df = df.copy()
    for col in ["Account", "Counterparty", "From", "To"]:
        if col in df.columns:
            df[col] = df[col].apply(standardize_address_string)
    return df

def format_owner_display(identifier, name):
    ident = str(identifier).strip()
    nm = str(name).strip() if name and str(name).lower() != "nan" else ""
    if not nm or nm == ident: return ident
    return f"{ident} ({nm})"

# --- Data Ingestion ---

def pd_read_csv_safe(path):
    """Reads a CSV with multiple encoding fallbacks and safe whitespace stripping."""
    df = None
    try: df = pd.read_csv(path, encoding="utf-8-sig")
    except:
        try: df = pd.read_csv(path, encoding="latin-1")
        except:
            try: df = pd.read_csv(path, encoding="utf-8", errors="replace")
            except: return pd.DataFrame()
    if df is not None:
        df.columns = [str(c).strip() for c in df.columns]
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    return df

def is_imposable_robust(val):
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI", "YES", "OUI"]

def get_safe_opts(df, col):
    if df is None or df.empty or col not in df.columns: return []
    return sorted([str(x) for x in df[col].dropna().unique()])

def get_file_path(year, category):
    base = os.path.join(EXPORT_BASE_DIR, str(year))
    # Standardised naming convention for CLEAN Gateway
    if category == 'qualified': return os.path.join(base, f"qualified_journal_CLEAN_{year}.csv")
    if category == 'qualified_clean': return os.path.join(base, f"qualified_journal_CLEAN_{year}.csv")
    if category == 'qualified_full': return os.path.join(base, f"qualified_journal_FULL_{year}.csv")
    if category == 'fiat': return os.path.join(base, f"manual_fiat_{year}.csv")
    if category == 'swaps': return os.path.join(base, f"manual_swaps_{year}.csv")
    if category == 'positions': return os.path.join(base, f"manual_positions_{year}.csv")
    if category == 'prices': return os.path.join(base, f"eoy_prices_{year}.json")
    if category == 'verified_prices': return os.path.join(base, f"verified_prices_{year}.json")
    if category == 'inventory_eoy': return os.path.join(base, f"inventory_EOY_{year}.csv")
    return None

def get_all_raw_files(year):
    """Collects all raw files from the year directory AND its sanctuary subfolder."""
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir): return []

    all_paths = []
    # 1. Root year dir
    files = [f for f in os.listdir(year_dir) if f.endswith(".csv") and f.startswith("raw_")]
    all_paths.extend([os.path.join(year_dir, f) for f in files])

    # 2. Sanctuary subfolder
    sanctuary_dir = os.path.join(year_dir, "sanctuary")
    if os.path.exists(sanctuary_dir):
        s_files = [f for f in os.listdir(sanctuary_dir) if f.endswith(".csv") and f.startswith("raw_")]
        all_paths.extend([os.path.join(sanctuary_dir, f) for f in s_files])

    return sorted(list(set(all_paths)), reverse=True)

def extract_source_from_filename(filename):
    basename = os.path.basename(filename).replace(".csv", "")
    ts_pattern = re.compile(r'_(\d{8}(?:_\d{6})?)$')
    match = ts_pattern.search(basename)
    prefix_full = basename[:match.start()] if match else basename
    for t in ["raw_portfolio_", "raw_transactions_", "raw_token_transfers_"]:
        if prefix_full.startswith(t): return prefix_full.replace(t, "")
    return prefix_full

def check_file_freshness(filepath, last_load):
    if not os.path.exists(filepath): return False
    mtime = os.path.getmtime(filepath)
    return mtime > last_load

def load_clean_history(year):
    """GATEWAY: Loads all clean journals from start_year up to year. BLIND TRUST in CLEAN file."""
    config = load_global_config()
    start = int(config.get("start_year", 2025))
    all_dfs = []
    for y in range(start, year + 1):
        p = get_file_path(y, 'qualified_clean')
        if os.path.exists(p):
            df = pd_read_csv_safe(p)
            if not df.empty:
                # CRITICAL: Ensure Date is datetime for all downstream apps
                if "Date" in df.columns:
                    df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
                    df = df.dropna(subset=["Date"])
                all_dfs.append(df)

    if not all_dfs:
        # Return empty df with schema and correct types to avoid .dt crashes
        empty_df = pd.DataFrame(columns=["Date", "Asset", "Amount", "Account", "Audit_Status", "Category", "Imposable", "Counterparty"])
        empty_df["Date"] = pd.to_datetime([])
        return empty_df

    # Blind trust: app2.py is the gatekeeper.
    # But we apply a safety spam filter just in case app2.py leaked something.
    res = pd.concat(all_dfs, ignore_index=True)
    res = apply_spam_filter(res, drop=True)

    # Final safety: force Date type even if filtering made it empty
    if "Date" in res.columns:
        res["Date"] = pd.to_datetime(res["Date"], utc=True, errors="coerce")

    return res

# --- Registry Management ---

def load_owner_accounts():
    if os.path.exists(OWNERS_FILE):
        try:
            with open(OWNERS_FILE, "r", encoding="utf-8") as f: return {str(k).lower(): v for k, v in json.load(f).items()}
        except: return {}
    return {}

def save_owner_accounts(data):
    with open(OWNERS_FILE, "w", encoding="utf-8") as f: json.dump({str(k).lower(): v for k, v in data.items()}, f, indent=4)

def load_position_labels():
    """Returns a simple mapping {address: label} for display and lookup."""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {str(k).lower(): (v.get("label") if isinstance(v, dict) else v) for k, v in data.items()}
        except: return {}
    return {}

def load_position_registry():
    """Returns the full position objects {address: {'label': name, 'assets': [A1, ...]}}."""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                res = {}
                for k, v in data.items():
                    addr = str(k).lower()
                    if isinstance(v, dict):
                        res[addr] = {
                            "label": v.get("label", ""),
                            "assets": [str(a).upper().strip() for a in v.get("assets", [])]
                        }
                    else:
                        res[addr] = {"label": str(v), "assets": []}
                return res
        except: return {}
    return {}

def save_position_labels(data):
    """Saves position data. Handles both simple {addr: label} and complex {addr: {label, assets}}."""
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k).lower(): v for k, v in data.items()}, f, indent=4)

def load_external_circuits():
    if os.path.exists(EXTERNAL_CIRCUITS_FILE):
        try:
            with open(EXTERNAL_CIRCUITS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["labels"] = {str(k).lower(): v for k, v in data.get("labels", {}).items()}
                data["hidden"] = [str(x).lower() for x in data.get("hidden", [])]
                return data
        except: pass
    return {"labels": {}, "hidden": []}

def save_external_circuits(data):
    with open(EXTERNAL_CIRCUITS_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)

def load_spam_list():
    if os.path.exists(SPAM_FILE):
        try:
            with open(SPAM_FILE, "r", encoding="utf-8") as f: return {str(x).lower() for x in json.load(f)}
        except: pass
    return set()

def save_spam_list(spam_set):
    with open(SPAM_FILE, "w", encoding="utf-8") as f: json.dump(sorted(list(spam_set)), f, indent=4)

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4)

def load_valid_assets():
    if os.path.exists(VALID_ASSETS_FILE):
        try:
            with open(VALID_ASSETS_FILE, "r", encoding="utf-8") as f: return {str(x).upper().strip() for x in json.load(f)}
        except: pass
    return set()

def save_valid_assets(assets_set):
    with open(VALID_ASSETS_FILE, "w", encoding="utf-8") as f: json.dump(sorted(list(assets_set)), f, indent=4)

def load_manual_notes():
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def save_manual_notes(notes):
    with open(NOTES_FILE, "w", encoding="utf-8") as f: json.dump(notes, f, indent=4)

def get_note_key(row):
    """Generates a stable UID for transaction notes."""
    dt = pd.to_datetime(row.get("Date")).strftime("%Y%m%d%H%M%S") if row.get("Date") else "NODATE"
    h = str(row.get("Tx Hash", row.get("Tx_Hash", "NOHASH"))).strip()
    ast = str(row.get("Asset", "NOAST")).strip().upper()
    acc = resolve_raw_addr(row.get("Account", "NOACC")).lower()
    return f"{dt}_{h}_{ast}_{acc}"

def get_all_labels():
    m = load_owner_accounts(); m.update(load_position_labels()); m.update(load_external_circuits().get("labels", {}))
    return m

def get_owner_addresses(df=None):
    ids = set(load_owner_accounts().keys())
    ids.update(load_position_labels().keys())
    if df is not None and "Account" in df.columns:
        for a in df["Account"].dropna().unique():
            r = resolve_raw_addr(a)
            if r.startswith("0x"): ids.add(r)
    return ids

def get_owner_display_list(df=None):
    labels = get_all_labels()
    ids = set(load_owner_accounts().keys())
    if df is not None and "Account" in df.columns:
        for a in df["Account"].dropna().unique(): ids.add(resolve_raw_addr(a))
    res = []
    for i in ids:
        if i: res.append(format_owner_display(i, labels.get(i.lower(), "")))
    return sorted(list(set(res)))

# --- Spam & Transfers ---

def apply_spam_filter(df, drop=True, reset_idx=True):
    """Strictly identifies and optionally removes spams based on Audit_Status and Blacklist."""
    if df is None or df.empty: return df
    spams = load_spam_list(); valides = load_valid_assets(); df = df.copy()

    # Identification of the status column
    status_col = "Audit_Status" if "Audit_Status" in df.columns else ("Status" if "Status" in df.columns else None)

    def is_row_spam(r):
        # 1. Check explicit status FIRST (Highest Priority: Manual Qualification)
        if status_col:
            st_val = str(r.get(status_col, "")).strip().lower()
            if st_val == "spam": return True
            if st_val == "valide": return False # Manual validation overrides blacklist

        # 2. Check Blacklist (Asset or Counterparty) - High Priority
        asset = str(r.get("Asset", "")).upper().strip()
        if asset.lower() in spams: return True

        cp = str(r.get("Counterparty", "")).strip().lower()
        if cp and cp not in ["nan", "none"]:
            if cp in spams: return True
            cp_raw = resolve_raw_addr(cp).lower()
            if cp_raw in spams: return True
            # Partial match for "Label (Addr)" or "Addr (Label)"
            if "(" in cp:
                parts = cp.replace(")", "").split("(")
                for p in parts:
                    if p.strip().lower() in spams: return True

        # 3. Check Whitelist (Protection for valid assets if not explicitly spammed or blacklisted)
        if asset in valides: return False

        # Default behavior: not automatically a spam unless caught above
        return False

    mask = df.apply(is_row_spam, axis=1)

    if drop:
        res = df[~mask]
        return res.reset_index(drop=True) if reset_idx else res

    if status_col:
        df.loc[mask, status_col] = "Spam"
    return df

def validate_spam_exclusion(df):
    """Returns indices of rows identified as spam."""
    if df.empty: return []
    spams = load_spam_list(); valides = load_valid_assets()
    def is_spam(r):
        ast = str(r.get("Asset", "")).upper().strip()
        if ast in valides: return False
        cp = resolve_raw_addr(r.get("Counterparty", "")).lower()
        return cp in spams or ast.lower() in spams
    return df[df.apply(is_spam, axis=1)].index.tolist()

# --- Fiscal & Pricing ---

def get_fiat_rate(from_currency, date_obj):
    if str(from_currency).upper() == "EUR": return 1.0
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from={from_currency}&to=EUR"
        res = requests.get(url, timeout=5).json()
        return float(res["rates"]["EUR"])
    except: return 0.0

def load_price_cache():
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def get_coingecko_id(asset):
    """Maps common assets to CoinGecko IDs."""
    mapping = {
        "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana",
        "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
        "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap", "LTC": "litecoin",
        "BCH": "bitcoin-cash", "XLM": "stellar", "NEAR": "near", "ATOM": "cosmos",
        "OP": "optimism", "ARB": "arbitrum", "FTM": "fantom", "EGLD": "elrond-erd-2",
        "CRO": "crypto-com-chain", "AAVE": "aave", "SNX": "havven", "GRT": "the-graph",
        "SAND": "the-sandbox", "MANA": "decentraland", "CHZ": "chiliz", "CRV": "curve-dao-token",
        "MKR": "maker", "RUNE": "thorchain", "GALA": "gala", "STX": "blockstack",
        "RNDR": "render-token", "INJ": "injective-protocol", "IMX": "immutable-x",
        "FET": "fetch-ai", "FIL": "filecoin", "HBAR": "hedera-hashgraph", "HNT": "helium",
        "ROSE": "oasis-network", "KAVA": "kava", "MINA": "mina-protocol", "CAKE": "pancakeswap-token",
        "WBNB": "binancecoin", "WETH": "ethereum", "WBTC": "bitcoin", "WAVAX": "avalanche-2",
        "EUR": "euro", "USD": "united-states-dollar"
    }
    return mapping.get(str(asset).upper().strip())

def get_price_eur(asset, date_obj, cache=None):
    """Fetches historical price in EUR with multi-source fallback (Cache -> CG -> Fiat)."""
    if not isinstance(date_obj, datetime):
        # Ensure it's a datetime object for strftime and tz handling
        date_obj = datetime.combine(date_obj, datetime.min.time())

    # Standardize to naive UTC for consistency in cache keys
    if date_obj.tzinfo is not None:
        date_obj = date_obj.astimezone(None).replace(tzinfo=None)

    asset_clean = str(asset).upper().strip()
    if asset_clean in ["EUR", "EURA", "AGEUR", "EURT", "EURC"]: return 1.0

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = cache if cache is not None else load_price_cache()
    cache_key = f"{asset_clean}_{d_str}"

    # 1. Cache Priority
    if cache_key in cache: return float(cache[cache_key])

    # 2. Stablecoin Fast-Path (USD Peg)
    usd_pegs = ["USD", "USDC", "USDT", "DAI", "BUSD", "PYUSD", "FRAX", "LUSD", "GUSD", "TUSD", "USDD"]
    if asset_clean in usd_pegs:
        rate = get_fiat_rate("USD", date_obj)
        if rate > 0:
            cache[cache_key] = rate
            save_price_cache(cache)
            return rate

    # Stablecoin Fast-Path (EUR Peg)
    eur_pegs = ["EUR", "EURA", "AGEUR", "EURT", "EURC", "EURCV", "EURE"]
    if asset_clean in eur_pegs:
        cache[cache_key] = 1.0
        save_price_cache(cache)
        return 1.0

    # 3. External Lookup: CoinGecko
    cg_id = get_coingecko_id(asset_clean)
    if cg_id:
        try:
            # CoinGecko Historical API: /coins/{id}/history?date=dd-mm-yyyy
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/history?date={d_str}&localization=false"
            res = requests.get(url, timeout=10).json()
            if "market_data" in res and "current_price" in res["market_data"]:
                price_eur = float(res["market_data"]["current_price"].get("eur", 0))
                if price_eur > 0:
                    cache[cache_key] = price_eur
                    save_price_cache(cache)
                    return price_eur
        except Exception as e:
            # Silence errors in background lookup to avoid UI crashes
            pass

    return 0.0

def get_total_acquisition_value(year):
    """Calculates cumulative sum of all fiat acquisitions (Amount EUR) from CLEAN history up to year."""
    # EXCLUSIVITY: All modules must use this exact same function for total consistency.
    df_h = load_clean_history(year)
    if df_h.empty: return 0.0

    # Filter for 'Achat' categories in the journal
    # Use fillna to avoid mask issues with NaN categories
    mask_cat = df_h['Category'].fillna("").str.contains("Achat", case=False, na=False)
    df_acq = df_h[mask_cat].copy()

    if df_acq.empty: return 0.0

    def get_row_acq_val(r):
        # 1. Primary: If Asset is EUR, Amount is the value
        ast = str(r.get("Asset", "")).upper().strip()
        amt = abs(pd.to_numeric(r.get("Amount"), errors='coerce') or 0.0)

        if ast == "EUR":
            return amt

        # 2. Fallback for unspecified assets from fiat sources
        if ast in ["", "NAN", "NONE", "UNKNOWN", "TOKEN"]:
            way = str(r.get("Source_Way", "")).lower()
            chain = str(r.get("Chain", "")).lower()
            acc = str(r.get("Account", "")).lower()
            if "fiat" in way or "fiat" in chain or "bank" in acc or "banq" in acc:
                return amt

        # 3. If it's a crypto purchase, acquisition cost is in VGP (EUR) or Valeur $
        vgp = abs(pd.to_numeric(r.get("VGP (EUR)"), errors='coerce') or 0.0)
        if vgp > 0: return vgp

        v_usd = abs(pd.to_numeric(r.get("Valeur $"), errors='coerce') or 0.0)
        if v_usd > 0: return v_usd * 0.92 # Default rate if unknown

        return 0.0

    return df_acq.apply(get_row_acq_val, axis=1).sum()

def calculate_fiscal_gains(cessions_df, total_acq_price):
    """Applies Art 150 VH bis gain formula: Gain = P_vente - (P_acq_total * (P_vente / VGP))."""
    if cessions_df.empty: return pd.DataFrame(), 0.0
    df = cessions_df.copy()

    # Required columns for display/logic
    p_vent_col = "Prix de Cession (EUR)" if "Prix de Cession (EUR)" in df.columns else "VGP (EUR)"
    vgp_col = "VGP (EUR)"

    df["Plus-Value Brute"] = 0.0
    df["Abattement Acq"] = 0.0

    current_acq_base = float(total_acq_price)

    for idx, row in df.iterrows():
        p_vent = float(row.get(p_vent_col, 0.0))
        vgp = float(row.get(vgp_col, 0.0))

        if vgp > 0:
            fraction = p_vent / vgp
            abattement = current_acq_base * fraction
            gain = p_vent - abattement

            df.at[idx, "Plus-Value Brute"] = gain
            df.at[idx, "Abattement Acq"] = abattement

            # Update base (Art 150 VH bis: acquisition price is reduced by the fraction used)
            current_acq_base -= abattement

    return df, current_acq_base

def get_journal_prices(df_h, target_date=None):
    """Extracts the most recent prices in EUR from the journal, prioritizing Position rows at target_date."""
    if df_h.empty: return {}

    # We sort by date descending to get the latest known price
    df = df_h.sort_values("Date", ascending=False)

    if target_date:
        target_date = pd.to_datetime(target_date, utc=True)
        # Priority A: Snapshot/Position entries at EXACT target date
        mask_snap = (df["Date"].dt.date == target_date.date()) & (df["Type"].fillna("").str.contains("Position", case=False))
        # Priority B: Any entry at EXACT target date
        mask_exact = (df["Date"].dt.date == target_date.date())
        # Priority C: Rest of history
        df_priority_a = df[mask_snap]
        df_priority_b = df[mask_exact & ~mask_snap]
        df_rest = df[~mask_exact]
        df_scan = pd.concat([df_priority_a, df_priority_b, df_rest])
    else:
        df_scan = df

    prices = {}
    last_dt = df["Date"].max()
    eur_usd = get_fiat_rate("USD", last_dt) or 0.92

    for _, r in df_scan.iterrows():
        ast = str(r["Asset"]).upper().strip()
        if ast in prices or ast == "EUR": continue

        amt = abs(float(r.get("Amount", 0)))

        # Hierarchy Level 1: Harvested USD price (high precision)
        p_usd = float(r.get("USD prix asset reçu", 0)) or float(r.get("USD prix asset envoyé", 0))

        # Hierarchy Level 2: VGP (EUR) / Amount (Already in EUR, certifiable)
        p_eur = 0.0
        if float(r.get("VGP (EUR)", 0)) > 0 and amt > 1e-12:
            p_eur = abs(float(r.get("VGP (EUR)")) / amt)

        # Hierarchy Level 3: Valeur $ / Amount
        v_usd = float(r.get("Valeur $", 0))
        if p_eur == 0 and p_usd == 0 and v_usd > 0 and amt > 1e-12:
            p_usd = v_usd / amt

        if p_eur == 0 and p_usd > 0:
            # Refresh rate for the specific date of the entry if possible, else use last_dt
            row_dt = r["Date"]
            rate = get_fiat_rate("USD", row_dt) or eur_usd
            p_eur = p_usd * rate

        if p_eur > 0:
            prices[ast] = p_eur

    return prices

def get_portfolio_snapshot(year, target_date, df_override=None):
    """Calculates balances and total VGP, ensuring consistency with Journal valuations."""
    target_date = pd.to_datetime(target_date, utc=True)

    if df_override is not None:
        df_j = df_override.copy()
    else:
        df_j = load_clean_history(year)

    if df_j.empty: return pd.DataFrame(), 0.0

    df_j["Date"] = pd.to_datetime(df_j["Date"], utc=True)
    df_j = df_j[df_j["Date"] <= target_date]
    df_j = apply_spam_filter(df_j, drop=True)

    # 1. Base Legs (Account)
    df_direct = df_j.copy()

    # 2. Protocol Mirroring (Receivables)
    pos_labels = load_position_labels()
    pos_ids = {str(k).lower().strip() for k in pos_labels.keys()}
    pos_names = {str(v).lower().strip() for v in pos_labels.values()}
    owner_accounts = set(load_owner_accounts().keys())

    df_j["cp_raw"] = df_j["Counterparty"].apply(resolve_raw_addr).str.lower().str.strip()

    # We mirror Internal Transfers to Protocols that are NOT already in the 'Account' list
    # to avoid double counting if the protocol is also harvested as an account.
    df_mirror = df_j[(df_j["Category"] == "Transfert Interne") &
                     (df_j["cp_raw"].isin(pos_ids) | df_j["Counterparty"].str.lower().isin(pos_names))].copy()

    if not df_mirror.empty:
        # Check which protocols are NOT already accounts in the history
        active_accounts = set(df_j["Account"].apply(resolve_raw_addr).str.lower().unique())
        df_mirror["cp_acc_raw"] = df_mirror["cp_raw"]

        # Mirror only if the target is NOT an owner account and NOT already harvested as an account
        mask_mirror = (~df_mirror["cp_acc_raw"].isin(owner_accounts)) & (~df_mirror["cp_acc_raw"].isin(active_accounts))
        df_to_mirror = df_mirror[mask_mirror].copy()

        if not df_to_mirror.empty:
            df_to_mirror["Account"] = df_to_mirror["Counterparty"]
            df_to_mirror["Amount"] = -df_to_mirror["Amount"]
            df_final = pd.concat([df_direct, df_to_mirror])
        else:
            df_final = df_direct
    else:
        df_final = df_direct

    df_final["Location"] = df_final["Account"].apply(standardize_address_string)

    # Calculate detailed snapshot
    df_final["In"] = df_final["Amount"].apply(lambda x: x if x > 0 else 0.0)
    df_final["Out"] = df_final["Amount"].apply(lambda x: abs(x) if x < 0 else 0.0)

    res = df_final.groupby(["Location", "Asset"]).agg({
        "Amount": "sum",
        "In": "sum",
        "Out": "sum"
    }).reset_index()
    res = res.rename(columns={"Amount": "Solde", "In": "Entrées", "Out": "Sorties"})
    res["Report"] = 0.0 # Placeholder for EOY carry-over if needed

    res = res[res["Solde"].abs() > 1e-10]

    # Identification of External Circuits (Exclusion from VGP)
    ext_circuits = load_external_circuits()
    ext_ids = {str(k).lower().strip() for k in ext_circuits.get("labels", {}).keys()}
    ext_names = {str(v).lower().strip() for v in ext_circuits.get("labels", {}).values()}

    def check_is_circuit(loc):
        raw = resolve_raw_addr(loc).lower().strip()
        if raw in ext_ids: return True
        if "(" in loc and ")" in loc:
            lbl = loc.split("(")[1].replace(")", "").strip().lower()
            if lbl in ext_names: return True
        return False

    res["Is_Circuit"] = res["Location"].apply(check_is_circuit)

    # Valuations: Journal Prices First, then Fallback
    journal_prices = get_journal_prices(df_j, target_date=target_date)
    cache = load_price_cache()

    def get_smart_price(asset):
        ast = str(asset).upper().strip()
        if ast in journal_prices: return journal_prices[ast]
        return get_price_eur(ast, target_date, cache)

    res["Prix (EUR)"] = res["Asset"].apply(get_smart_price)
    res["Valeur (EUR)"] = res["Solde"] * res["Prix (EUR)"]

    # VGP Calculation: Net sum of ALL values EXCLUDING External Circuits
    total_vgp = res[res["Is_Circuit"] == False]["Valeur (EUR)"].sum()

    return res, total_vgp

def get_price_from_journal(asset, target_date, df_h=None, year=None):
    """Searches for a certified price in the Step 2 Journal for a given asset and date."""
    if df_h is None and year:
        df_h = load_clean_history(year)

    if df_h is None or df_h.empty: return 0.0

    asset = str(asset).upper().strip()
    target_date = pd.to_datetime(target_date, utc=True).date()

    # 1. Look for matching Asset and Date
    mask = (df_h["Asset"].str.upper() == asset) & (df_h["Date"].dt.date == target_date)
    matches = df_h[mask].copy()

    if matches.empty: return 0.0

    # Prioritize:
    # 1. Highest VGP (EUR) / Amount ratio (most certified)
    # 2. USD prices
    # 3. Valeur $

    best_p_eur = 0.0
    eur_usd = get_fiat_rate("USD", datetime.combine(target_date, datetime.min.time())) or 0.92

    for _, r in matches.iterrows():
        amt = abs(float(r.get("Amount", 0)))
        if amt < 1e-12: continue

        # Method A: VGP (already in EUR)
        p_vgp = float(r.get("VGP (EUR)", 0)) / amt
        if p_vgp > best_p_eur: best_p_eur = p_vgp

        # Method B: USD dedicated columns
        p_usd = float(r.get("USD prix asset reçu", 0)) or float(r.get("USD prix asset envoyé", 0))
        if p_usd > 0:
            p_eur = p_usd * eur_usd
            if p_eur > best_p_eur: best_p_eur = p_eur

        # Method C: Valeur $
        v_usd = float(r.get("Valeur $", 0))
        if v_usd > 0:
            p_eur = (v_usd / amt) * eur_usd
            if p_eur > best_p_eur: best_p_eur = p_eur

    return best_p_eur

# --- Hub Integration ---

def inject_to_app0(data_list, target, year):
    """Injects transactions to App0 registries."""
    path = get_file_path(year, 'fiat' if target == "Fiat" else 'swaps')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exist = pd_read_csv_safe(path) if os.path.exists(path) else pd.DataFrame()

    new_rows = []
    for r in data_list:
        dt = pd.to_datetime(r.get("Date")).date() if r.get("Date") else ""
        if target == "Fiat":
            new_rows.append({
                "Date": dt, "Account": r.get("Account"), "Counterparty": "banq fiat",
                "Montant EUR": 0.0, "Type": "Vente", "Asset": r.get("Asset"),
                "Quantité": abs(float(r.get("Amount", 0))), "Tx Hash": r.get("Tx Hash"), "Imposable": True
            })
        else:
            new_rows.append({
                "Date": dt, "Account": r.get("Account"), "Counterparty": r.get("Counterparty"),
                "Asset": r.get("Asset"), "Amount": float(r.get("Amount", 0)),
                "Type": "Swap Out" if float(r.get("Amount", 0)) < 0 else "Swap In",
                "Tx Hash": r.get("Tx Hash"), "Source Type": "Injected", "Imposable": True
            })

    updated = pd.concat([exist, pd.DataFrame(new_rows)]).reset_index(drop=True)
    updated.to_csv(path, index=False, encoding="utf-8-sig")
    return len(new_rows)

def get_external_circuits_discovery(df):
    if df is None or df.empty: return []
    owners = get_owner_addresses(df); res = []
    for _, r in df.iterrows():
        cp = resolve_raw_addr(r.get("Counterparty", "")).lower()
        if cp and cp not in owners:
            res.append({"Address": cp, "Amount": abs(float(r.get("Amount", 0))), "Asset": r.get("Asset")})
    if not res: return []
    return pd.DataFrame(res).groupby("Address").agg({"Amount": "sum", "Asset": "count"}).rename(columns={"Asset": "Count"}).reset_index().to_dict('records')

def auto_register_owner(addr):
    raw = resolve_raw_addr(addr)
    if raw.startswith("0x") and len(raw) > 30:
        o = load_owner_accounts()
        if raw not in o: o[raw] = f"Auto ({raw[:6]})"; save_owner_accounts(o)

def cleanup_working_files(year):
    """Deletes old raw_*.csv files in the year root dir, keeping only the 2 most recent unique dates."""
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir): return 0

    # 1. Collect all raw files in the root year dir only (NOT in sanctuary/)
    files = [f for f in os.listdir(year_dir) if f.endswith(".csv") and f.startswith("raw_")]
    if not files: return 0

    # 2. Extract unique dates from filenames (format: _YYYYMMDD)
    date_pattern = re.compile(r'_(\d{8})(_\d{6})?\.csv$')

    file_dates = []
    for f in files:
        match = date_pattern.search(f)
        if match:
            file_dates.append((f, match.group(1))) # (filename, date_str)

    if not file_dates: return 0

    # 3. Identify unique dates sorted descending
    unique_dates = sorted(list(set(d for f, d in file_dates)), reverse=True)
    dates_to_keep = set(unique_dates[:2])

    # 4. Delete files not in the keep list
    deleted_count = 0
    for f, d in file_dates:
        if d not in dates_to_keep:
            try:
                os.remove(os.path.join(year_dir, f))
                deleted_count += 1
            except: pass

    return deleted_count

def show_status():
    st.sidebar.success("✅ Système Opérationnel")
