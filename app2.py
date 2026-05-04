import os
import time
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
from shared_logic import (
    resolve_raw_addr, get_fiat_rate,
    load_external_circuits, save_external_circuits, get_external_circuits_discovery,
    pd_read_csv_safe, detect_internal_transfers,
    load_owner_accounts, save_owner_accounts, get_owner_addresses,
    get_all_raw_files, check_file_freshness,
    find_reconciliation_matches, get_file_path,
    extract_source_from_filename, validate_spam_exclusion,
    load_spam_list, standardize_df_addresses, is_imposable_robust,
    show_status
)

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Qualification (app2)", layout="wide")
st.title("⚖️ Qualification & Nettoyage (Step 2)")

EXPORT_BASE_DIR = "sanctuarisation"
SPAM_FILE = "spam_blacklist.json"
POSITIONS_FILE = "position_labels.json"

# Schema Unifié
COLUMNS = [
    "Date", "Account", "Counterparty", "Asset", "Amount",
    "Value ($)", "Network", "Tx Hash", "Source Type",
    "Category", "Status", "Imposable", "Linked_ID", "Link_Status"
]

# --- Helpers ---
def save_spam_list(spam_set):
    with open(SPAM_FILE, "w", encoding="utf-8") as f:
        json.dump(list(spam_set), f)

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                return {str(k).lower(): v for k, v in data.items()}
        except: return {}
    return {}

def save_position_labels(labels_dict):
    lower_data = {str(k).lower(): v for k, v in labels_dict.items()}
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(lower_data, f, indent=4)

# --- Engine: Merging & Cleaning ---
def apply_position_labels(df):
    """Remplace l'adresse Counterparty par 'Label (0x...)' si un mapping existe."""
    if df.empty: return df

    # 1. Load Standard Positions
    labels = load_position_labels()

    # 2. Load External Circuits Labels
    ext_data = load_external_circuits()
    circ_labels = ext_data.get("labels", {})

    # 3. Load Owner Accounts
    owners_map = load_owner_accounts()

    # Merge all for display (Positions > Owners > Circuits)
    combined_labels = {**circ_labels, **owners_map, **labels}

    if not combined_labels: return df

    def format_cp(cp_str):
        raw = resolve_raw_addr(cp_str)
        if raw in combined_labels:
            return f"{combined_labels[raw]} ({raw})"
        return cp_str

    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    return df

def merge_raw_data(year):
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir):
        return pd.DataFrame(columns=COLUMNS)

    all_rows = []
    spam_list = load_spam_list()

    # 1. Load Manual Registry (app0)
    # 1a. Fiat
    fiat_path = os.path.join(year_dir, f"manual_fiat_{year}.csv")
    if os.path.exists(fiat_path) and os.path.getsize(fiat_path) > 0:
        try:
            df_fiat = pd_read_csv_safe(fiat_path)
            for _, r in df_fiat.iterrows():
                m_eur = float(r.get("Montant EUR", 0.0))
                qty_asset = float(r.get("Quantité", 0.0))
                asset_name = str(r.get("Asset", "EUR")).upper()
                f_type = str(r.get("Type", ""))

                dt_obj = pd.to_datetime(r.get("Date"), utc=True)
                rate_usd_eur = get_fiat_rate("USD", dt_obj)

                # Leg EUR (never imposable)
                all_rows.append({
                    "Date": r.get("Date"),
                    "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))),
                    "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))),
                    "Asset": "EUR",
                    "Amount": m_eur if "Vente" in f_type else -m_eur,
                    "Value ($)": ((m_eur if "Vente" in f_type else -m_eur) / rate_usd_eur) if rate_usd_eur > 0 else 0.0,
                    "Network": "Fiat",
                    "Tx Hash": str(r.get("Tx Hash", "")),
                    "Source Type": "Fiat",
                    "Category": "Vente (Fiat)" if "Vente" in f_type else ("Achat (Fiat)" if "Achat" in f_type else "Mouvement Fiat"),
                    "Status": "Valide",
                    "Imposable": False
                })

                # Leg Crypto
                if asset_name != "EUR" and asset_name != "NAN" and qty_asset > 0:
                    is_imp = is_imposable_robust(r.get("Imposable"))
                    all_rows.append({
                        "Date": r.get("Date"),
                        "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))),
                        "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))),
                        "Asset": asset_name,
                        "Amount": qty_asset if "Achat" in f_type else -qty_asset,
                        "Value ($)": (m_eur / rate_usd_eur) if rate_usd_eur > 0 else 0.0,
                        "Network": "Fiat",
                        "Tx Hash": str(r.get("Tx Hash", "")),
                        "Source Type": "Fiat-to-Crypto",
                        "Category": "Achat" if "Achat" in f_type else "Vente",
                        "Status": "Valide",
                        "Imposable": is_imp
                    })
        except Exception: pass

    # 1b. Manual Swaps & Transfers
    swap_path = os.path.join(year_dir, f"manual_swaps_{year}.csv")
    if os.path.exists(swap_path) and os.path.getsize(swap_path) > 0:
        try:
            df_swap = pd_read_csv_safe(swap_path)
            for _, r in df_swap.iterrows():
                is_imp = is_imposable_robust(r.get("Imposable", False))
                all_rows.append({
                    "Date": r.get("Date"),
                    "Account": str(r.get("Account", "")),
                    "Counterparty": str(r.get("Counterparty", "")),
                    "Asset": str(r.get("Asset", "")),
                    "Amount": float(r.get("Amount", 0.0)),
                    "Value ($)": 0.0,
                    "Network": "Manual",
                    "Tx Hash": str(r.get("Tx Hash", "")),
                    "Source Type": "Manual",
                    "Category": "Transfert Interne" if "Transfert" in str(r.get("Type")) else "Swap",
                    "Status": "Valide",
                    "Imposable": is_imp
                })
        except Exception: pass

    # 2. Load Blockchain Txs (app.py and specialized importers) - LOAD ALL FILES
    # Loading all files ensures a "complet de traitement".
    # Sorting ensures latest versions are processed first.
    all_files = get_all_raw_files(year)

    for f_path in all_files:
        f = os.path.basename(f_path)
        file_source = extract_source_from_filename(f)

        # --- AUTO-REGISTER OWNER ---
        # If the file source is a hex address, make sure it's in our owners list
        from shared_logic import auto_register_owner
        auto_register_owner(file_source)

        if f.startswith("raw_transactions_") and os.path.getsize(f_path) > 0:
            try:
                df = pd_read_csv_safe(f_path)
                for _, r in df.iterrows():
                    f_addr_full = str(r.get("From", ""))
                    t_addr_full = str(r.get("To", ""))
                    f_addr = resolve_raw_addr(f_addr_full)
                    acc_low = str(r.get("Account", "")).lower()
                    if not acc_low or acc_low in ["nan", "0x..."]: acc_low = file_source

                    cp = str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = t_addr_full if f_addr == acc_low else f_addr_full

                    amount = float(r.get("Value ETH", 0.0))
                    if f_addr == acc_low: amount = -amount

                    is_blacklisted = (resolve_raw_addr(cp) in spam_list or str(r.get("Chain", "")).lower() in spam_list)
                    asset_name = str(r.get("Chain", "")).strip()
                    is_dust_empty = (asset_name == "" and abs(amount) < 1e-15)

                    status = "Spam" if (is_blacklisted or is_dust_empty) else "A vérifier"
                    all_rows.append({
                        "Date": r.get("Date"), "Account": acc_low, "Counterparty": cp, "Asset": r.get("Chain", "ETH"),
                        "Amount": amount, "Value ($)": float(r.get("Value ($)") or 0.0), "Network": r.get("Chain"),
                        "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Native",
                        "Category": "Transfert Interne" if "Discovery" in str(r.get("Type")) else "A vérifier",
                        "Status": status, "Imposable": is_imposable_robust(r.get("Imposable", False))
                    })
            except Exception: pass

        elif f.startswith("raw_token_transfers_") and os.path.getsize(f_path) > 0:
            try:
                df = pd_read_csv_safe(f_path)
                for _, r in df.iterrows():
                    f_addr_full = str(r.get("From", ""))
                    f_addr = resolve_raw_addr(f_addr_full)
                    acc_low = str(r.get("Account", "")).lower()
                    if not acc_low or acc_low in ["nan", "0x..."]: acc_low = file_source

                    cp = str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = str(r.get("To", "")) if f_addr == acc_low else f_addr_full

                    amount = float(r.get("Value", 0.0))
                    if f_addr == acc_low: amount = -amount

                    is_blacklisted = (resolve_raw_addr(cp) in spam_list or str(r.get("Token", "")).lower() in spam_list)
                    asset_name = str(r.get("Token", "")).strip()
                    is_dust_empty = (asset_name == "" and abs(amount) < 1e-15)

                    status = "Spam" if (is_blacklisted or is_dust_empty) else "A vérifier"
                    all_rows.append({
                        "Date": r.get("Date"), "Account": acc_low, "Counterparty": cp, "Asset": r.get("Token"),
                        "Amount": amount, "Value ($)": float(r.get("Value ($)") or 0.0), "Network": r.get("Chain"),
                        "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Token",
                        "Category": r.get("Category", "A vérifier"), "Status": status, "Imposable": is_imposable_robust(r.get("Imposable", False))
                    })
            except Exception: pass

        elif f.startswith("raw_portfolio_") and os.path.getsize(f_path) > 0:
            try:
                df = pd_read_csv_safe(f_path)
                for _, r in df.iterrows():
                    acc_low = str(r.get("Account", "")).lower()
                    if not acc_low or acc_low in ["nan", "0x..."]: acc_low = file_source

                    asset = str(r.get("Asset", "UNKNOWN"))
                    amount = float(r.get("Quantity", 0.0))

                    # Portfolio rows are treated as 'Audit Balance' (snapshot at a point in time)
                    # We use the current target year and EOY as a dummy date for these records
                    # but they will be handled by the VGP logic
                    all_rows.append({
                        "Date": datetime(year, 12, 31), # Dummy EOY date for portfolio harvest
                        "Account": acc_low, "Counterparty": "Blockchain Snapshot", "Asset": asset,
                        "Amount": amount, "Value ($)": float(r.get("Value ($)") or 0.0), "Network": str(r.get("Chain", "")),
                        "Tx Hash": f"PORT-{file_source}-{asset}", "Source Type": "Portfolio",
                        "Category": "Inventaire", "Status": "Valide", "Imposable": False
                    })
            except Exception: pass

    df_final = pd.DataFrame(all_rows)
    if df_final.empty:
        df_final = pd.DataFrame(columns=COLUMNS)

    if not df_final.empty:
        # Ensure all required columns exist
        for col in COLUMNS:
            if col not in df_final.columns:
                df_final[col] = ""

        df_final["Date"] = pd.to_datetime(df_final["Date"], utc=True, errors="coerce", format="ISO8601")

        # Unified hash normalization
        def norm_hash(h):
            s = str(h).strip().lower()
            if s in ["nan", "none", "", "0"]: return ""
            return str(h).strip()
        df_final["Tx Hash"] = df_final["Tx Hash"].apply(norm_hash)

        # --- SMART DEDUPLICATION ---
        # 1. Identify Manual or Synthetic entries
        def is_synthetic(h):
            return any(str(h).startswith(p) for p in ["BLP-", "NVL-", "OUT-", "IN-", "FEE-"])

        manual_types = ["Fiat", "Fiat-to-Crypto", "Manual", "Manual Swap", "Manual Transfer"]
        manual_mask = df_final["Source Type"].isin(manual_types) | df_final["Tx Hash"].apply(is_synthetic) | (df_final["Tx Hash"] == "")

        df_manual = df_final[manual_mask].copy()
        df_harvested = df_final[~manual_mask].copy()

        if not df_manual.empty and not df_harvested.empty:
            # Normalize harvested for matching
            df_harvested["_acc"] = df_harvested["Account"].astype(str).str.lower()
            df_harvested["_asset"] = df_harvested["Asset"].astype(str).str.upper()
            df_harvested["_day"] = df_harvested["Date"].dt.date
            df_harvested["_amt"] = df_harvested["Amount"].abs().round(8)

            # Reference map of real blockchain transactions
            harvest_ref = df_harvested.drop_duplicates(subset=["_day", "_asset", "_amt", "_acc"])

            def find_match(row):
                # If it already has a real hash, skip
                h = str(row.get("Tx Hash", ""))
                if h and not is_synthetic(h):
                    return row

                day = pd.to_datetime(row["Date"]).date()
                amt = abs(float(row["Amount"]))
                asset = str(row.get("Asset", "")).upper()
                acc = str(row.get("Account", "")).lower()

                matches = harvest_ref[(harvest_ref["_day"] == day) & (harvest_ref["_asset"] == asset) &
                                      (harvest_ref["_amt"] == round(amt, 8)) & (harvest_ref["_acc"] == acc)]

                if not matches.empty:
                    m = matches.iloc[0]
                    row["Tx Hash"] = m["Tx Hash"]
                    row["Date"] = m["Date"]
                    # Inherit missing data
                    if pd.isna(row.get("Value ($)")) or row.get("Value ($)") == 0:
                         row["Value ($)"] = m.get("Value ($)", 0.0)
                    if pd.isna(row.get("Network")) or row.get("Network") == "Fiat":
                         row["Network"] = m.get("Network", "Fiat")
                return row

            df_manual = df_manual.apply(find_match, axis=1)
            df_harvested = df_harvested.drop(columns=["_acc", "_asset", "_day", "_amt"])
            df_final = pd.concat([df_manual, df_harvested])

        # Priority Deduplication
        # If hashes match (real or synthetic), we prioritize rows with user-defined semantic context
        df_final["_pri"] = df_final["Source Type"].apply(lambda x: 1 if x in manual_types else 0)
        df_final["_d"] = df_final["Date"].dt.date
        df_final = df_final.sort_values(["Date", "_pri"], ascending=[False, False])

        # 1. Standard Deduplication (Exact Hash match)
        # Find duplicates to flag them before dropping
        dups_mask = df_final.duplicated(subset=["Tx Hash", "Asset", "Amount", "Account", "_d"], keep=False)
        if dups_mask.any():
             # We can't easily "flag" and then drop without losing info.
             # Better: we keep first but we might want to alert the user.
             pass
        df_final = df_final.drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account", "_d"], keep="first")

        # 2. Legacy/Synthetic Collapse (Same transaction, different synthetic hash format)
        # We only apply this to rows that are considered synthetic or manual
        is_synth = df_final["Tx Hash"].apply(is_synthetic) | (df_final["Tx Hash"] == "")
        df_real = df_final[~is_synth]
        df_synth = df_final[is_synth]

        # For synthetic/manual ones, we ignore the hash in the uniqueness check to catch formatting changes
        if not df_synth.empty:
            df_synth = df_synth.drop_duplicates(subset=["Asset", "Amount", "Account", "_d"], keep="first")

        df_final = pd.concat([df_real, df_synth]).sort_values("Date", ascending=False).reset_index(drop=True)
        df_final = df_final.drop(columns=["_pri", "_d"])
        # UNIFICATION
        df_final = standardize_df_addresses(df_final)
        df_final = apply_position_labels(df_final)

    return df_final

# --- Logic ---
def sync_data(year):
    qual_path = get_file_path(year, 'qualified')
    # new_df is the source of truth for existence and values
    new_df = merge_raw_data(year)

    # Track load timestamp
    st.session_state.last_sync_time = time.time()

    # Unified normalization for hashes
    def norm_hash(h):
        s = str(h).strip()
        if s.lower() in ["nan", "none", "", "0"]: return ""
        return s

    if os.path.exists(qual_path) and os.path.getsize(qual_path) > 0:
        try:
            old_df = pd_read_csv_safe(qual_path)
            # UNIFICATION
            old_df = standardize_df_addresses(old_df)
            old_df["Date"] = pd.to_datetime(old_df["Date"], utc=True, errors="coerce", format="ISO8601")
            if "Tx Hash" in old_df.columns:
                old_df["Tx Hash"] = old_df["Tx Hash"].apply(norm_hash)

            # Ensure all Fidelity columns exist in old_df to avoid KeyError
            fidelity_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]
            for col in fidelity_cols:
                if col not in old_df.columns:
                    old_df[col] = "" if col not in ["Imposable", "VGP (EUR)"] else (False if col == "Imposable" else 0.0)

            # Force numeric
            for col in ["Amount", "Value ($)", "VGP (EUR)"]:
                if col in old_df.columns:
                    old_df[col] = pd.to_numeric(old_df[col], errors='coerce').fillna(0.0)
        except Exception:
            old_df = pd.DataFrame(columns=COLUMNS)

        if not new_df.empty:
            new_df["Tx Hash"] = new_df["Tx Hash"].apply(norm_hash)
            new_df["_d"] = new_df["Date"].dt.date

            # --- FIDELITY ENGINE: Re-apply qualifications and Links from old_df to new_df ---
            if not old_df.empty:
                # 1. Map by Exact Hash (Strongest)
                # We extract mapping tables from old_df
                hash_map = old_df[old_df["Tx Hash"] != ""].drop_duplicates("Tx Hash").set_index("Tx Hash")[fidelity_cols].to_dict('index')

                # 2. Map by (Date, Account, Asset) for manual entries or synthetic
                old_df["_d"] = old_df["Date"].dt.date
                manual_map = old_df[old_df["Tx Hash"] == ""].drop_duplicates(["_d", "Account", "Asset"]).set_index(["_d", "Account", "Asset"])[fidelity_cols].to_dict('index')

                def reapply(row):
                    h = row["Tx Hash"]
                    found_m = None
                    if h and h in hash_map:
                        found_m = hash_map[h]
                    else:
                        key = (row["_d"], row["Account"], row["Asset"])
                        if key in manual_map:
                            found_m = manual_map[key]

                    if found_m:
                        row["Category"], row["Status"] = found_m["Category"], found_m["Status"]
                        # Fidelity: Keep imposable=True if either new_df (raw app0) OR old_df (qualifier) has it.
                        row["Imposable"] = is_imposable_robust(row["Imposable"]) or is_imposable_robust(found_m["Imposable"])
                        row["VGP (EUR)"] = found_m["VGP (EUR)"]
                        row["Linked_ID"], row["Link_Status"] = found_m.get("Linked_ID", ""), found_m.get("Link_Status", "")
                    else:
                        # Ensure Imposable is boolean for new rows
                        row["Imposable"] = is_imposable_robust(row["Imposable"])
                    return row

                new_df = new_df.apply(reapply, axis=1)

            # Preserve rows that are ONLY in old_df (added manually in app2)
            # A row is considered "Only in old_df" if its hash AND its (Date, Account, Asset) are not in new_df
            if not old_df.empty:
                new_hashes = set(new_df["Tx Hash"].unique())
                new_keys = set(zip(new_df["_d"], new_df["Account"], new_df["Asset"]))

                def is_new(r):
                    if r["Tx Hash"] != "" and r["Tx Hash"] in new_hashes: return True
                    if (r["_d"], r["Account"], r["Asset"]) in new_keys: return True
                    return False

                only_old = old_df[~old_df.apply(is_new, axis=1)]
                if not only_old.empty:
                    new_df = pd.concat([new_df, only_old]).reset_index(drop=True)

            new_df = new_df.drop(columns=["_d"]).sort_values("Date", ascending=False).reset_index(drop=True)
            new_df = apply_position_labels(new_df)
            st.session_state.journal_qualifie = new_df
        else:
            st.session_state.journal_qualifie = old_df
    else:
        if not new_df.empty:
            st.session_state.journal_qualifie = new_df.sort_values("Date", ascending=False)
        else:
            st.session_state.journal_qualifie = pd.DataFrame(columns=COLUMNS)

# --- UI Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de traitement", min_value=2015, max_value=2030, value=datetime.now().year)

    # Initialisation data si nécessaire
    if "journal_qualifie" not in st.session_state or st.session_state.get("last_year") != target_year:
        # Full Reset on Year Switch
        for k in list(st.session_state.keys()):
            if k not in ["last_year"]: del st.session_state[k]
        st.cache_data.clear()
        sync_data(target_year)
        st.session_state.last_year = target_year

    if st.button("🏷️ Appliquer les Labels de Protocoles", width='stretch'):
        if "journal_qualifie" in st.session_state:
            st.session_state.journal_qualifie = apply_position_labels(st.session_state.journal_qualifie)
            st.success("Labels appliqués au journal en mémoire.")
            st.rerun()

    st.divider()
    if st.button("🔄 Actualiser & Fusionner les Brutes", width='stretch'):
        sync_data(target_year)
        st.success("Fusion terminée.")

    # Data Freshness Warning
    year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
    if os.path.exists(year_dir):
        files_to_check = [
            os.path.join(year_dir, f"manual_fiat_{target_year}.csv"),
            os.path.join(year_dir, f"manual_swaps_{target_year}.csv")
        ] + get_all_raw_files(target_year)

        last_load = st.session_state.get("last_sync_time", 0)
        is_stale = any(check_file_freshness(f, last_load) for f in files_to_check)

        if is_stale:
            st.warning("⚠️ Données sur disque plus récentes. Veuillez 'Actualiser'.")

    if st.button("🚨 Réinitialiser depuis les Brutes", width='stretch', help="ATTENTION : Écrase tout le travail de qualification effectué pour repartir du journal brut."):
        new_df = merge_raw_data(target_year)
        if not new_df.empty:
            st.session_state.journal_qualifie = new_df.sort_values("Date", ascending=False)
            st.warning("Journal réinitialisé. N'oubliez pas de Sanctuariser pour enregistrer sur disque.")
            st.rerun()

    if st.button("🛡️ Nettoyer les Spams (Auto)", width='stretch'):
        if "journal_qualifie" in st.session_state:
            spam_list = load_spam_list()
            df = st.session_state.journal_qualifie
            # Nettoyage par adresse (Contrepartie) OU par nom d'Asset
            mask_cp = df["Counterparty"].fillna("").str.lower().apply(resolve_raw_addr).isin(spam_list)
            mask_asset = df["Asset"].fillna("").str.lower().isin(spam_list)
            df.loc[mask_cp | mask_asset, "Status"] = "Spam"
            st.session_state.journal_qualifie = df
            st.rerun()

    st.divider()
    st.header("📊 Filtres & Regroupement")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_for_filters = st.session_state.journal_qualifie

        # Filtres Multiples
        # On force en string et on retire les nan/None pour éviter le TypeError dans sorted()
        def get_safe_options(df, col):
            return sorted([str(x) for x in df[col].dropna().unique()])

        f_asset = st.multiselect("Filtrer par Asset", options=get_safe_options(df_for_filters, "Asset"))
        f_acc = st.multiselect("Filtrer par Compte (Account)", options=get_safe_options(df_for_filters, "Account"))
        f_status = st.multiselect("Filtrer par Statut", options=get_safe_options(df_for_filters, "Status"), default=[])
        f_cat = st.multiselect("Filtrer par Catégorie", options=get_safe_options(df_for_filters, "Category"), default=[])

        # Filtre Imposable avec labels lisibles
        f_imp_options = {"Oui": True, "Non": False}
        f_imp_sel = st.multiselect("Filtrer par Imposable", options=list(f_imp_options.keys()))
        f_imp = [f_imp_options[x] for x in f_imp_sel]

        f_orphan = st.checkbox("Afficher uniquement les Orphelins (Sans Maillon)")

        f_cp_search = st.text_input("Filtrer par Counterparty (0x...)", "")

        st.divider()
        st.header("🔃 Tri du Journal")
        sort_cols = list(df_for_filters.columns)
        default_sort = sort_cols.index("Date") if "Date" in sort_cols else 0
        sort_by = st.selectbox("Trier par", sort_cols, index=default_sort)
        sort_order = st.radio("Sens du tri", ["Décroissant (Z-A)", "Croissant (A-Z)"], index=0)

        if st.button("⚡ Appliquer Filtres & Tri"):
            # Le tri est appliqué à la session state
            df = st.session_state.journal_qualifie
            df = df.sort_values(by=sort_by, ascending=(sort_order == "Croissant (A-Z)"))
            st.session_state.journal_qualifie = df
            # Les filtres seront appliqués à l'affichage (voir Main App)
            st.rerun()

    with st.expander("🛡️ Anti-Spam & Actions de Masse"):
        spam_list = load_spam_list()
        st.write(f"Total Blacklist : **{len(spam_list)}**")

        if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
            df = st.session_state.journal_qualifie

            # --- 1. SELECTION ---
            st.subheader("📦 Sélection")
            assets_to_mvt = st.multiselect("Assets concernés", options=sorted([str(x) for x in df["Asset"].dropna().unique()]))
            cp_to_mvt = st.multiselect("Contreparties (adresses)", options=sorted([str(x) for x in df["Counterparty"].dropna().unique()]))

            # --- 2. ACTION ---
            st.subheader("⚡ Action")
            target_status = st.selectbox("Nouveau Statut", ["À vérifier", "Valide", "Spam"])

            if st.button("🚀 Appliquer à la sélection"):
                if not assets_to_mvt and not cp_to_mvt:
                    st.warning("Choisissez au moins un asset ou une adresse.")
                else:
                    # Préparation des listes
                    sel_low = [x.lower() for x in (assets_to_mvt + cp_to_mvt)]

                    # Mise à jour de la Blacklist
                    if target_status == "Spam":
                        for item in sel_low:
                            if item: spam_list.add(item)
                    else:
                        for item in sel_low:
                            if item in spam_list: spam_list.remove(item)
                    save_spam_list(spam_list)

                    # Mise à jour du Journal en mémoire
                    mask_asset = df["Asset"].fillna("").str.lower().isin(sel_low)
                    mask_cp = df["Counterparty"].fillna("").str.lower().apply(resolve_raw_addr).isin(sel_low)
                    df.loc[mask_asset | mask_cp, "Status"] = target_status

                    st.success(f"Action effectuée sur la sélection. Journal et Blacklist mis à jour.")
                    st.rerun()

        # --- 3. GESTION INDIVIDUELLE ---
        st.divider()
        st.subheader("🔎 Gestion Blacklist Globale")
        new_spam = st.text_input("Ajout direct (nom ou 0x...)", placeholder="ex: ELON", key="input_new_spam")
        if st.button("🚫 Bannir définitivement"):
            if new_spam:
                spam_list.add(new_spam.strip().lower())
                save_spam_list(spam_list)
                st.success(f"'{new_spam}' ajouté.")
                st.rerun()

        if spam_list:
            to_remove = st.multiselect("Retirer manuellement", options=sorted(list(spam_list)))
            if st.button("✅ Supprimer de la liste noire"):
                for item in to_remove: spam_list.remove(item)
                save_spam_list(spam_list)
                st.rerun()

    with st.expander("👥 Gestion des Comptes Propriétaires"):
        from shared_logic import load_owner_accounts, save_owner_accounts, get_owner_addresses

        st.info("Définissez et fixez la liste de vos comptes propriétaires pour renforcer la détection des transferts internes.")

        journal_active = st.session_state.get("journal_qualifie")
        owner_mappings = load_owner_accounts()
        all_detected = get_owner_addresses(journal_active) # Contains both mapped and journal-found

        # Table for management
        owner_data = []
        for addr in sorted(list(all_detected)):
            owner_data.append({
                "Address": addr,
                "Label": owner_mappings.get(addr, ""),
                "Verified": addr in owner_mappings
            })

        df_owners = pd.DataFrame(owner_data)
        ed_owners = st.data_editor(
            df_owners,
            column_config={
                "Address": st.column_config.TextColumn(disabled=True),
                "Label": st.column_config.TextColumn("Nom / Label"),
                "Verified": st.column_config.CheckboxColumn("Fixer comme Propriétaire"),
            },
            width='stretch',
            key="owners_editor",
            hide_index=True
        )

        if st.button("💾 Enregistrer les Comptes Propriétaires", width='stretch'):
            new_map = {}
            for _, r in ed_owners.iterrows():
                if r["Verified"]:
                    new_map[r["Address"]] = str(r["Label"]).strip()
            save_owner_accounts(new_map)
            st.success("Configuration des comptes propriétaires mise à jour.")
            st.rerun()

        st.divider()
        st.subheader("➕ Ajouter un compte manuellement")
        c_add1, c_add2 = st.columns([2, 1])
        new_owner_addr = c_add1.text_input("Adresse (0x...)", key="new_owner_addr")
        new_owner_label = c_add2.text_input("Label", key="new_owner_label")
        if st.button("➕ Ajouter aux Propriétaires"):
            if new_owner_addr:
                addr_clean = resolve_raw_addr(new_owner_addr)
                curr_map = load_owner_accounts()
                curr_map[addr_clean] = new_owner_label
                save_owner_accounts(curr_map)
                st.success(f"Compte {addr_clean} ajouté.")
                st.rerun()

    with st.expander("🌐 Circuits de Traitement (Swaps/Bridges/External)"):
        from shared_logic import get_external_circuits_discovery, load_external_circuits, save_external_circuits

        st.info("Détectez et étiquetez les comptes tiers utilisés pour les swaps ou bridges. Ces comptes sont exclus de la VGP par défaut.")

        journal_active = st.session_state.get("journal_qualifie")
        circuits = get_external_circuits_discovery(journal_active)

        t_discovery, t_manage = st.tabs(["🔎 Discovery (Auto)", "⚙️ Gérer les Circuits Indexés"])

        with t_discovery:
            if not circuits:
                st.info("Aucun nouveau circuit externe détecté dans les transactions selon la règle récursive.")
            else:
                st.subheader("🔗 Comptes qualifiés par propagation")
                st.caption("Cette liste inclut les comptes en lien direct ou indirect avec vos comptes propriétaires/positions.")

                df_circuits = pd.DataFrame(circuits)

                # Action logic for labels
                ed_circuits = st.data_editor(
                    df_circuits,
                    column_config={
                        "Address": st.column_config.TextColumn(disabled=True),
                        "Label": st.column_config.TextColumn("Label / Nom", help="ex: Bridge Arbitrum, 1inch Swap"),
                        "Vol. USD": st.column_config.NumberColumn(format="$ %.2f", disabled=True),
                        "Tx Count": st.column_config.NumberColumn(disabled=True),
                        "Asset": st.column_config.TextColumn(disabled=True),
                    },
                    width='stretch',
                    key="circuits_editor"
                )

                c_save1, c_save2 = st.columns(2)
                if c_save1.button("💾 Enregistrer les Labels de Circuits", width='stretch'):
                    ext_data = load_external_circuits()
                    new_labels = ext_data.get("labels", {})
                    for _, r in ed_circuits.iterrows():
                        if str(r["Label"]).strip():
                            new_labels[r["Address"]] = str(r["Label"]).strip()
                    ext_data["labels"] = new_labels
                    save_external_circuits(ext_data)
                    st.success("Labels de circuits enregistrés.")
                    st.rerun()

                st.divider()
                st.subheader("🛠️ Actions sur les adresses détectées")

                addr_target = st.selectbox("Choisir une adresse pour action", options=[""] + [c["Address"] for c in circuits])

                if addr_target:
                    curr_info = next((c for c in circuits if c["Address"] == addr_target), {})
                    curr_label = curr_info.get("Label", "")

                    c_act1, c_act2, c_act3 = st.columns(3)

                    if c_act1.button("👤 Promouvoir en PROPRIÉTAIRE", width='stretch'):
                        owners = load_owner_accounts()
                        owners[addr_target] = curr_label if curr_label else f"Owner ({addr_target[:6]})"
                        save_owner_accounts(owners)
                        st.success(f"Adresse {addr_target} ajoutée aux comptes propriétaires.")
                        st.rerun()

                    if c_act2.button("🏦 Promouvoir en POSITION", width='stretch'):
                        pos = load_position_labels()
                        pos[addr_target] = curr_label if curr_label else f"Position ({addr_target[:6]})"
                        save_position_labels(pos)
                        st.success(f"Adresse {addr_target} ajoutée au mapping des protocoles.")
                        st.rerun()

                    if c_act3.button("🗑️ Supprimer de la liste (Cacher)", width='stretch'):
                        ext_data = load_external_circuits()
                        if "hidden" not in ext_data: ext_data["hidden"] = []
                        ext_data["hidden"].append(addr_target)
                        save_external_circuits(ext_data)
                        st.success(f"Adresse {addr_target} retirée de la découverte.")
                        st.rerun()

        with t_manage:
            ext_data = load_external_circuits()
            labels = ext_data.get("labels", {})
            hidden = ext_data.get("hidden", [])

            if not labels and not hidden:
                st.write("Aucun circuit enregistré.")
            else:
                st.subheader("Labels existants")
                if labels:
                    df_labels = pd.DataFrame(list(labels.items()), columns=["Address", "Label"])
                    ed_labels = st.data_editor(df_labels, width='stretch', key="ed_labels_mgmt")
                    if st.button("💾 Mettre à jour les Labels"):
                        new_map = {r["Address"]: r["Label"] for _, r in ed_labels.iterrows()}
                        ext_data["labels"] = new_map
                        save_external_circuits(ext_data)
                        st.success("Labels mis à jour.")
                        st.rerun()

                if hidden:
                    st.subheader("Adresses cachées")
                    to_unhide = st.multiselect("Retirer des adresses cachées", options=hidden)
                    if st.button("🔓 Réafficher les adresses sélectionnées"):
                        ext_data["hidden"] = [h for h in hidden if h not in to_unhide]
                        save_external_circuits(ext_data)
                        st.rerun()

            st.divider()
            st.subheader("➕ Ajouter manuellement un circuit")
            c_man1, c_act_m = st.columns([3, 1])
            new_circ_addr = c_man1.text_input("Adresse du circuit (0x...)", key="new_circ_addr")
            if c_act_m.button("➕ Ajouter au Circuits"):
                if new_circ_addr:
                    addr_clean = resolve_raw_addr(new_circ_addr)
                    ext_data = load_external_circuits()
                    ext_data["labels"][addr_clean] = "Manual Circuit"
                    save_external_circuits(ext_data)
                    st.success(f"Circuit {addr_clean} ajouté.")
                    st.rerun()

        if st.button("🧹 Réinitialiser les Circuits (Vider labels & cachés)"):
            save_external_circuits({"labels": {}, "hidden": []})
            st.rerun()

    with st.expander("🏦 Mapping des Protocoles (Positions)"):
        pos_labels = load_position_labels()
        st.write(f"Protocoles identifiés : **{len(pos_labels)}**")

        st.info("Associez une adresse à un nom de protocole (ex: Staking ETH, Compound Vault) pour l'inclure dans la VGP.")

        new_addr = st.text_input("Adresse du contrat/vault", placeholder="0x...")
        new_label = st.text_input("Nom du protocole / Label", placeholder="ex: Staking Lido")

        if st.button("➕ Ajouter la Position"):
            if new_addr and new_label:
                addr_clean = resolve_raw_addr(new_addr)
                pos_labels[addr_clean] = new_label
                save_position_labels(pos_labels)
                st.success(f"Position '{new_label}' enregistrée.")
                st.rerun()

        if pos_labels:
            st.divider()
            # Table simple pour voir/supprimer
            pos_df = pd.DataFrame(list(pos_labels.items()), columns=["Adresse", "Label"])
            st.dataframe(pos_df, width='stretch', hide_index=True)

            to_del = st.selectbox("Supprimer une position", [""] + sorted(list(pos_labels.keys())))
            if to_del and st.button("🗑️ Supprimer"):
                del pos_labels[to_del]
                save_position_labels(pos_labels)
                st.rerun()

# --- Reconciliation Tab ---
def reconciliation_dashboard():
    st.subheader("🤝 Réconciliation & Maillons de Transaction")
    if "journal_qualifie" not in st.session_state or st.session_state.journal_qualifie.empty:
        st.warning("Aucune donnée disponible.")
        return

    df = st.session_state.journal_qualifie

    col1, col2 = st.columns(2)

    with col1:
        st.write("**🔍 Détection de Maillons**")
        win = st.number_input("Fenêtre de recherche (jours)", 1, 15, 3)
        tol = st.slider("Tolérance de valeur (%)", 0.0, 0.20, 0.05)

        if st.button("🚀 Lancer la recherche automatique", width='stretch'):
            df_new, count = find_reconciliation_matches(df, time_window_days=win, val_tolerance_pct=tol)
            st.session_state.journal_qualifie = df_new
            st.success(f"Détection terminée : {count} nouveaux maillons proposés.")
            st.rerun()

    with col2:
        st.write("**⚙️ Actions de Masse**")
        if st.button("✅ Confirmer TOUS les maillons proposés", width='stretch'):
            df.loc[df["Link_Status"] == "Proposed", "Link_Status"] = "Confirmed"
            st.session_state.journal_qualifie = df
            st.success("Tous les maillons proposés ont été confirmés.")
            st.rerun()

        if st.button("🗑️ Effacer les maillons NON confirmés", width='stretch'):
            df.loc[df["Link_Status"] == "Proposed", "Linked_ID"] = ""
            df.loc[df["Link_Status"] == "Proposed", "Link_Status"] = ""
            st.session_state.journal_qualifie = df
            st.rerun()

    st.divider()

    # Dashboard View
    t_prop, t_orphans = st.tabs(["💡 Liaisons Proposées", "👻 Mouvements Orphelins"])

    with t_prop:
        proposed = df[df["Link_Status"] == "Proposed"]
        if proposed.empty:
            st.info("Aucune liaison proposée à valider.")
        else:
            # We display by pairs (grouped by Linked_ID)
            for lid, group in proposed.groupby("Linked_ID"):
                with st.container(border=True):
                    c_g1, c_g2 = st.columns([4, 1])
                    c_g1.write(f"Maillon : `{lid}`")
                    if c_g2.button("✅ Confirmer", key=f"conf_{lid}"):
                        df.loc[df["Linked_ID"] == lid, "Link_Status"] = "Confirmed"
                        st.session_state.journal_qualifie = df
                        st.rerun()

                    st.dataframe(group[["Date", "Account", "Counterparty", "Asset", "Amount", "Value ($)", "Source Type"]], hide_index=True)

    with t_orphans:
        st.info("Ces transactions n'ont pas de liaison identifiée. Elles représentent des flux d'entrée/sortie isolés.")
        orphans = df[(df["Linked_ID"] == "") & (df["Status"] != "Spam")]
        st.dataframe(orphans[["Date", "Account", "Counterparty", "Asset", "Amount", "Value ($)", "Category"]], width='stretch')

# --- Main App ---
@st.fragment
def main_journal_fragment():
    st.subheader(f"📋 Journal de Qualification {target_year}")
    if "journal_qualifie" not in st.session_state or st.session_state.journal_qualifie.empty:
        st.warning("Aucune donnée trouvée. Utilisez 'Actualiser & Fusionner' dans le sidebar.")
        return

    # Application des filtres d'affichage (sans modifier la session state)
    df_display = st.session_state.journal_qualifie.copy()

    if f_asset:
        df_display = df_display[df_display["Asset"].isin(f_asset)]
    if f_acc:
        df_display = df_display[df_display["Account"].isin(f_acc)]
    if f_status:
        df_display = df_display[df_display["Status"].isin(f_status)]
    if f_cat:
        df_display = df_display[df_display["Category"].isin(f_cat)]
    if f_imp_sel:
        df_display = df_display[df_display["Imposable"].isin(f_imp)]
    if f_orphan:
        df_display = df_display[df_display["Linked_ID"] == ""]
    if f_cp_search:
        df_display = df_display[df_display["Counterparty"].astype(str).str.contains(f_cp_search, case=False, na=False)]

    # ENSURE UNIQUE INDEX for Styler compatibility
    df_display = df_display.reset_index(drop=True)

    # 1. Barre d'outils
    col_t1, col_t2, col_save = st.columns([1.5, 0.5, 1])


    # Show suspicious duplicates count
    suspect_indices = []
    if not df_display.empty:
        df_display["_d"] = df_display["Date"].dt.date
        # Detection of potential duplicates (same day, same asset, same amount, same account but DIFFERENT hash)
        mask_not_ign = (df_display.get("Category", "") != "Doublon à ignorer") & (df_display.get("Category", "") != "Doublon (Fusionné)")
        suspect_dups = df_display[mask_not_ign].copy()

        dups_bool = suspect_dups.duplicated(subset=["Asset", "Amount", "Account", "_d"], keep=False)
        real_suspects = suspect_dups[dups_bool].groupby(["Asset", "Amount", "Account", "_d"]).filter(lambda x: x["Tx Hash"].nunique() > 1)

        if not real_suspects.empty:
            count_suspects = len(real_suspects.groupby(["Asset", "Amount", "Account", "_d"]))
            st.warning(f"⚠️ {count_suspects} groupes de suspicions de doublons détectés (Hashes différents pour mêmes caractéristiques).")
            suspect_indices = real_suspects.index.tolist()

            with st.expander("🔍 Voir et Fusionner les Doublons Suspects"):
                st.dataframe(real_suspects[["Date", "Account", "Asset", "Amount", "Tx Hash", "Source Type", "Category"]], width='stretch')

                if st.button("🤝 Fusionner Automatiquement (Gardé: le plus qualifié/récent)", width='stretch', key="btn_merge_dups"):
                    full_journal = st.session_state.journal_qualifie
                    full_journal["_d"] = full_journal["Date"].dt.date

                    for name, group in real_suspects.groupby(["Asset", "Amount", "Account", "_d"]):
                        mask_group = (full_journal["Asset"] == name[0]) & \
                                     (full_journal["Amount"] == name[1]) & \
                                     (full_journal["Account"] == name[2]) & \
                                     (full_journal["_d"] == name[3])

                        indices = full_journal[mask_group].index
                        if len(indices) > 1:
                            # Prioritize: 1. Manual source 2. Already qualified 3. Most recent
                            sorted_indices = full_journal.loc[indices].sort_values(
                                by=["Category", "Source Type"], ascending=[False, True]
                            ).index
                            full_journal.loc[sorted_indices[1:], "Category"] = "Doublon (Fusionné)"
                            full_journal.loc[sorted_indices[1:], "Status"] = "Spam"

                    st.session_state.journal_qualifie = full_journal
                    st.success("Fusion terminée.")
                    st.rerun()

    if col_t1.button("🔍 Détecter Transferts Internes", width='stretch', key="btn_detect_internal"):
        df = st.session_state.journal_qualifie
        df, counts = detect_internal_transfers(df)
        st.session_state.journal_qualifie = df
        st.success(f"Transferts identifiés : {counts['hash']} par Hash, {counts['account']} par Compte Propriétaire.")
        st.rerun()

    # 2. Data Editor
    # Dynamically build categories from current session state + standard defaults
    standard_cats = ["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense Staking", "Airdrop", "Frais", "Perte/Vol", "Autre", "Doublon à ignorer", "Doublon (Fusionné)"]
    if "journal_qualifie" in st.session_state:
        found_cats = st.session_state.journal_qualifie["Category"].dropna().unique().tolist()
        categories = sorted(list(set(standard_cats + [str(c) for c in found_cats if str(c).strip()])))
    else:
        categories = standard_cats

    statuses = ["A vérifier", "Valide", "Spam"]

    # Type safety
    for col in ["Account", "Counterparty", "Asset", "Tx Hash", "Source Type", "Category", "Status"]:
        if col in st.session_state.journal_qualifie.columns:
            st.session_state.journal_qualifie[col] = st.session_state.journal_qualifie[col].fillna("").astype(str)

    # Add Selection column
    if "Sel." not in df_display.columns:
        df_display.insert(0, "Sel.", False)

    # Add highlighting for suspects and links
    def style_journal(row):
        styles = [''] * len(row)
        # Duplicate suspect (Yellow)
        if row.name in suspect_indices:
            styles = ['background-color: #ffffcc'] * len(row)
        # Proposed Link (Rose Pale)
        elif str(row.get("Link_Status")) == "Proposed":
            styles = ['background-color: #ffe6f2'] * len(row)
        # Confirmed Link (Light Blue/Cyan)
        elif str(row.get("Link_Status")) == "Confirmed":
             styles = ['background-color: #e6ffff'] * len(row)
        return styles

    edited_df = st.data_editor(
        df_display.style.apply(style_journal, axis=1),
        column_config={
            "Sel.": st.column_config.CheckboxColumn("Sel."),
            "Category": st.column_config.SelectboxColumn("Catégorie", options=categories, required=True),
            "Status": st.column_config.SelectboxColumn("Statut", options=statuses, required=True),
            "Imposable": st.column_config.CheckboxColumn("Imposable ?"),
            "Date": st.column_config.DatetimeColumn(disabled=True),
            "Account": st.column_config.TextColumn(disabled=True),
            "Tx Hash": st.column_config.TextColumn(disabled=True),
            "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
        },
        width='stretch',
        num_rows="dynamic",
        key="qual_editor"
    )

    # 3. Transfer Logic (After definition)
    with st.expander("📤 Transférer vers Registre Manuel (App 0)"):
        st.info("Sélectionnez des lignes dans le journal cochant la colonne 'Sel.', puis choisissez la destination.")
        c_dest1, c_dest2 = st.columns(2)
        if c_dest1.button("💶 Transférer comme Flux Fiat", width='stretch', key="btn_transfer_fiat"):
             selected = edited_df[edited_df["Sel."] == True]
             if not selected.empty:
                 from shared_logic import inject_to_app0
                 # We drop the helper 'Sel.' column before injecting
                 clean_selected = selected.drop(columns=["Sel."])
                 count = inject_to_app0(clean_selected.to_dict('records'), "Fiat", target_year)
                 st.success(f"✅ {count} mouvements injectés dans le Registre Fiat (App 0).")
             else:
                 st.warning("Aucune ligne sélectionnée (Cochez 'Sel.').")

        if c_dest2.button("🔄 Transférer comme Échange/Swap", width='stretch', key="btn_transfer_swap"):
             selected = edited_df[edited_df["Sel."] == True]
             if not selected.empty:
                 from shared_logic import inject_to_app0
                 clean_selected = selected.drop(columns=["Sel."])
                 count = inject_to_app0(clean_selected.to_dict('records'), "Swap", target_year)
                 st.success(f"✅ {count} mouvements injectés dans le Registre Swaps (App 0).")
             else:
                 st.warning("Aucune ligne sélectionnée (Cochez 'Sel.').")

    # 4. Save Logic
    if st.button(f"💾 Sanctuariser la Sélection {target_year}", type="primary", width='stretch'):
        # Remove selection column before saving
        if "Sel." in edited_df.columns:
            edited_df = edited_df.drop(columns=["Sel."])
        # On fusionne les modifications du data_editor (filtré) dans la session_state (complète)
        # Pour simplifier, si on est en mode filtré, on prévient l'utilisateur
        if f_asset or f_acc or f_status or f_cat or f_imp_sel:
            st.warning("⚠️ Attention: Vous êtes en mode filtré. Seules les lignes visibles seront mises à jour dans la session state.")

        # Mise à jour de la session state avec les lignes éditées
        full_df = st.session_state.journal_qualifie.copy()
        # On utilise le Tx Hash + Asset + Amount + Account comme clé de fusion
        # (C'est notre subset de dédoublonnage)
        # On remplace les lignes de full_df par celles de edited_df
        # Pour faire simple ici, on écrase tout le journal par edited_df si non filtré
        if not (f_asset or f_acc or f_status or f_cat or f_imp_sel):
            new_journal = edited_df
        else:
            # Fusion complexe si filtré : on retire les anciennes lignes filtrées et on ajoute les nouvelles
            mask_filtered = pd.Series(True, index=full_df.index)
            if f_asset: mask_filtered &= full_df["Asset"].isin(f_asset)
            if f_acc: mask_filtered &= full_df["Account"].isin(f_acc)
            if f_status: mask_filtered &= full_df["Status"].isin(f_status)
            if f_cat: mask_filtered &= full_df["Category"].isin(f_cat)
            if f_imp_sel: mask_filtered &= full_df["Imposable"].isin(f_imp)

            non_filtered_df = full_df[~mask_filtered]
            new_journal = pd.concat([non_filtered_df, edited_df]).sort_values("Date", ascending=False).reset_index(drop=True)

        # --- DOUBLE VÉRIFICATION SPAM AVANT SAUVEGARDE ---
        if not new_journal.empty:
            leaked_indices = validate_spam_exclusion(new_journal)
            if leaked_indices:
                st.warning(f"⚠️ {len(leaked_indices)} transactions correspondent à la Blacklist mais ne sont pas marquées 'Spam'.")
                if st.checkbox("Appliquer l'exclusion Spam sur ces lignes avant de sauvegarder ?", value=True, key="chk_apply_spam_save"):
                    new_journal.loc[leaked_indices, "Status"] = "Spam"
                    st.info("Statut mis à jour en 'Spam'.")

        # Nettoyage automatique des Doublons marqués manuellement
        if not new_journal.empty and "Category" in new_journal.columns:
            count_dup = (new_journal["Category"] == "Doublon à ignorer").sum()
            count_fusion = (new_journal["Category"] == "Doublon (Fusionné)").sum()
            if count_dup > 0 or count_fusion > 0:
                # We remove 'Doublon à ignorer' but keep 'Doublon (Fusionné)' as Spam records?
                # User requested "non prise en compte de la ligne".
                # Marking as Spam and Category Doublon is good for audit trail.
                # If they really want them gone:
                new_journal = new_journal[new_journal["Category"] != "Doublon à ignorer"]
                st.info(f"🗑️ {count_dup} doublons manuels supprimés avant sauvegarde.")

        st.session_state.journal_qualifie = new_journal
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)

        # SUPPRESSION de la propagation automatique asset/adresse vers la blacklist globale.
        # Seul un bannissement via la Sidebar est définitif pour le futur.

        st.session_state.journal_qualifie.to_csv(get_file_path(target_year, 'qualified'), index=False, encoding="utf-8-sig")
        st.balloons()
        st.success(f"Journal qualifié enregistré dans {year_dir}")

tab_qual, tab_reconcile = st.tabs(["📋 Journal de Qualification", "🤝 Réconciliation"])

if __name__ == "__main__":
    with tab_qual:
        main_journal_fragment()

    with tab_reconcile:
        reconciliation_dashboard()

    st.sidebar.divider()
    st.sidebar.caption("Qualification v1.0 - app2")
