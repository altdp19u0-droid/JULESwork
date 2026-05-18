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
        "start_year": None,
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
    owners = load_owner_accounts()
    if raw in owners: return format_owner_display(raw, owners[raw])
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
    if category == 'qualified': return os.path.join(base, f"qualif_journal_{year}.csv")
    if category == 'qualified_full': return os.path.join(base, f"qualif_journal_{year}_FULL.csv")
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
    """GATEWAY: Loads all clean journals from start_year up to year."""
    config = load_global_config()
    start = config.get("start_year") or 2020
    all_dfs = []
    for y in range(start, year + 1):
        p = get_file_path(y, 'qualified')
        if os.path.exists(p):
            df = pd_read_csv_safe(p)
            if not df.empty: all_dfs.append(df)
    if not all_dfs: return pd.DataFrame()
    return pd.concat(all_dfs).reset_index(drop=True)

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
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {str(k).lower(): (v.get("label") if isinstance(v, dict) else v) for k, v in data.items()}
        except: return {}
    return {}

def save_position_labels(data):
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f: json.dump({str(k).lower(): v for k, v in data.items()}, f, indent=4)

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

def apply_spam_filter(df, drop=True):
    if df is None or df.empty: return df
    spams = load_spam_list(); valides = load_valid_assets(); df = df.copy()
    status_col = "Audit_Status" if "Audit_Status" in df.columns else "Status"
    def is_spam(r):
        asset = str(r.get("Asset", "")).upper().strip()
        if asset in valides: return False
        if status_col in r and str(r.get(status_col)) == "Spam": return True
        cp = resolve_raw_addr(r.get("Counterparty", "")).lower()
        if cp in spams or asset.lower() in spams: return True
        return False
    mask = df.apply(is_spam, axis=1)
    if drop:
        return df[~mask].reset_index(drop=True)
    if status_col in df.columns: df.loc[mask, status_col] = "Spam"
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

def get_price_eur(asset, date_obj, cache=None):
    if not isinstance(date_obj, datetime):
        date_obj = datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=None)
    asset_clean = str(asset).upper().strip()
    if asset_clean in ["EUR", "EURA", "AGEUR"]: return 1.0
    if asset_clean in ["USD", "USDC", "USDT", "DAI"]: return get_fiat_rate("USD", date_obj)

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = cache if cache is not None else load_price_cache()
    if f"{asset_clean}_{d_str}" in cache: return float(cache[f"{asset_clean}_{d_str}"])
    return 0.0

def get_total_acquisition_value(year):
    """Calculates cumulative sum of all fiat acquisitions (Amount EUR) up to year."""
    config = load_global_config()
    start = config.get("start_year") or 2020
    total = 0.0
    for y in range(start, year + 1):
        p = get_file_path(y, 'fiat')
        if os.path.exists(p):
            df = pd_read_csv_safe(p)
            if not df.empty and "Type" in df.columns:
                mask = df["Type"].str.contains("Achat", case=False, na=False)
                amt_col = "Montant EUR" if "Montant EUR" in df.columns else "Amount"
                if amt_col in df.columns:
                    total += pd.to_numeric(df[mask][amt_col], errors="coerce").fillna(0.0).sum()
    return total

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

def get_portfolio_snapshot(year, target_date):
    """Calculates balances and total VGP."""
    target_date = pd.to_datetime(target_date, utc=True)
    df_j = load_clean_history(year)
    if df_j.empty: return pd.DataFrame(), 0.0

    df_j["Date"] = pd.to_datetime(df_j["Date"], utc=True)
    df_j = df_j[df_j["Date"] <= target_date]
    df_j = apply_spam_filter(df_j, drop=True)

    df_j["Location"] = df_j["Account"].apply(standardize_address_string)
    res = df_j.groupby(["Location", "Asset"])["Amount"].sum().reset_index()
    res = res[res["Amount"].abs() > 1e-8]

    cache = load_price_cache()
    res["Prix (EUR)"] = res["Asset"].apply(lambda a: get_price_eur(a, target_date, cache))
    res["Valeur (EUR)"] = res["Amount"] * res["Prix (EUR)"]

    return res, res["Valeur (EUR)"].sum()

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

def show_status():
    st.sidebar.success("✅ Système Opérationnel")
