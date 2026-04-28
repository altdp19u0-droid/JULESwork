import os
import json
import pandas as pd
from datetime import datetime

EXPORT_BASE_DIR = "sanctuarisation"
POSITIONS_FILE = "position_labels.json"

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
