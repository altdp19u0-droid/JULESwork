import os
import time
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic as sl

# --- CONFIGURATION & INITIALIZATION ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Qualification (app2)", layout="wide")

st.title("⚖️ Qualification & Nettoyage (Step 2)")

EXPORT_BASE_DIR = "sanctuarisation"

# Standard Schema for the Qualification Journal (V4 aligned)
COLUMNS = [
    "Date", "Account", "Counterparty", "Asset", "Amount",
    "Value ($)", "Network", "Tx Hash", "Source Type",
    "Category", "Status", "Imposable", "Linked_ID", "Link_Status", "VGP (EUR)",
    "Source_File"
]

def ensure_v4_columns(df):
    """Ensures the DataFrame follows the standard schema and types."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)

    df = df.copy()
    # Normalize headers
    df.columns = [str(c).strip() for c in df.columns]

    for col in COLUMNS:
        if col not in df.columns:
            # Case-insensitive match attempt
            matches = [c for c in df.columns if str(c).lower().replace(" ","").replace("_","") == col.lower().replace(" ","").replace("_","")]
            if matches:
                df = df.rename(columns={matches[0]: col})
            else:
                if col == "Imposable": df[col] = False
                elif col in ["Amount", "Value ($)", "VGP (EUR)"]: df[col] = 0.0
                else: df[col] = ""

    # Force types
    for c in ["Amount", "Value ($)", "VGP (EUR)"]:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

    df["Imposable"] = df["Imposable"].apply(sl.is_imposable_robust)

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
        df = df.dropna(subset=["Date"])

    return df[COLUMNS]

# --- CORE ENGINE ---

def get_robust_fingerprint(df):
    """Generates a high-fidelity key for transaction matching across varied schemas."""
    if df.empty: return pd.Series()

    # Header mapping per dataframe to handle inconsistencies
    h_map = {str(c).lower().replace(" ","").replace("_",""): c for c in df.columns}

    def get_val(r, candidates, default=""):
        for c in candidates:
            if c in h_map:
                v = r.get(h_map[c])
                return str(v).strip() if v is not None and not pd.isna(v) else default
        return str(default)

    def get_amt(r):
        # We look for amount or equivalents
        candidates = ["amount", "valueeth", "value", "quantity", "montant"]
        for c in candidates:
            if c in h_map:
                v = r.get(h_map[c])
                if v is not None and not pd.isna(v):
                    try: return abs(float(v))
                    except: pass
        return 0.0

    d = pd.to_datetime(df.apply(lambda r: get_val(r, ["date"]), axis=1), utc=True, errors="coerce").dt.strftime("%Y%m%d")
    acc = df.apply(lambda r: get_val(r, ["account", "compte"]), axis=1).apply(sl.resolve_raw_addr).str.lower()
    amt = df.apply(get_amt, axis=1).round(6).astype(str)
    ast = df.apply(lambda r: get_val(r, ["asset", "tokensymbol", "symbol", "chain"], "ETH"), axis=1).str.upper()
    h = df.apply(lambda r: get_val(r, ["txhash", "hash", "transactionhash"]), axis=1).str.lower()

    return d + "_" + acc + "_" + ast + "_" + amt + "_" + h

def merge_raw_sources(year):
    """Aggregation engine for all raw data sources (Manual & Blockchain)."""
    rows = []

    # 1. Manual Registries (Fiat & Swaps)
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if os.path.exists(year_dir):
        manual_files = [f for f in os.listdir(year_dir) if f.startswith("manual_") and f.endswith(".csv")]
        for fn in manual_files:
            path = os.path.join(year_dir, fn)
            try:
                df_m = sl.pd_read_csv_safe(path)
                if df_m.empty: continue

                # App0 Fiat mapping
                if "fiat" in fn:
                    for _, r in df_m.iterrows():
                        me = float(r.get("Montant EUR", 0))
                        qa = float(r.get("Quantité", 0))
                        asset = str(r.get("Asset", "EUR")).upper()
                        f_type = str(r.get("Type", ""))
                        rt = sl.get_fiat_rate("USD", pd.to_datetime(r.get("Date"), utc=True))

                        # Leg 1: Cash flow
                        rows.append({
                            "Date": r.get("Date"), "Account": r.get("Account", "Manual"), "Counterparty": r.get("Counterparty", "Bank"),
                            "Asset": "EUR", "Amount": me if "Vente" in f_type else -me,
                            "Value ($)": ((me if "Vente" in f_type else -me)/rt) if rt>0 else 0,
                            "Network": "Fiat", "Tx Hash": r.get("Tx Hash", ""), "Source Type": "Fiat",
                            "Category": "Flux Fiat", "Status": "Valide", "Imposable": False, "Source_File": fn
                        })
                        # Leg 2: Crypto flow
                        if asset != "EUR" and qa > 0:
                            rows.append({
                                "Date": r.get("Date"), "Account": r.get("Account", "Manual"), "Counterparty": r.get("Counterparty", "Bank"),
                                "Asset": asset, "Amount": qa if "Achat" in f_type else -qa,
                                "Value ($)": (me/rt) if rt>0 else 0,
                                "Network": "Fiat", "Tx Hash": r.get("Tx Hash", ""), "Source Type": "Fiat-to-Crypto",
                                "Category": "Achat" if "Achat" in f_type else "Vente", "Status": "Valide",
                                "Imposable": sl.is_imposable_robust(r.get("Imposable")), "Source_File": fn
                            })
                # App0 Swaps mapping
                elif "swaps" in fn:
                    for _, r in df_m.iterrows():
                        rows.append({
                            "Date": r.get("Date"), "Account": r.get("Account", ""), "Counterparty": r.get("Counterparty", ""),
                            "Asset": r.get("Asset", ""), "Amount": float(r.get("Amount", 0)), "Value ($)": 0,
                            "Network": "Manual", "Tx Hash": r.get("Tx Hash", ""), "Source Type": "Manual Swap",
                            "Category": "Swap", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable")), "Source_File": fn
                        })
            except: pass

    # 2. Blockchain Harvests (Voies 1, 2, 3)
    raw_files = sl.get_all_raw_files(year)
    valid_assets = sl.load_valid_assets()

    for path in raw_files:
        fn = os.path.basename(path)
        src = sl.extract_source_from_filename(fn)
        sl.auto_register_owner(src)

        try:
            df = sl.pd_read_csv_safe(path)
            if df.empty: continue

            # Discovery logic within the loop for each file
            h_map = {str(c).lower().replace(" ","").replace("_",""): c for c in df.columns}

            for _, r in df.iterrows():
                d_val = r.get(h_map.get("date"))
                if pd.isna(d_val) or str(d_val).lower() in ["nan", "none", ""]: continue

                acc = str(r.get(h_map.get("account"), src)).lower()
                tx_h = str(r.get(h_map.get("txhash"), r.get(h_map.get("hash"), "")))
                asset = str(r.get(h_map.get("asset"), r.get(h_map.get("tokensymbol"), r.get(h_map.get("chain"), "ETH")))).upper()

                # Amount
                amt = r.get(h_map.get("amount"))
                if amt is None: amt = r.get(h_map.get("valueeth"))
                if amt is None: amt = r.get(h_map.get("value"))
                if amt is None: amt = r.get(h_map.get("quantity"))
                amt = float(amt) if amt is not None else 0.0

                if "amount" not in h_map:
                    fr = str(r.get(h_map.get("from"), "")).lower()
                    if fr == acc: amt = -amt

                cp = str(r.get(h_map.get("counterparty"), ""))
                if not cp or cp == "nan":
                    fr = str(r.get(h_map.get("from"), "")).lower()
                    cp = r.get(h_map.get("to")) if fr == acc else r.get(h_map.get("from"))

                rows.append({
                    "Date": d_val, "Account": acc, "Counterparty": cp, "Asset": asset, "Amount": amt,
                    "Value ($)": float(r.get(h_map.get("value($)"), 0)),
                    "Network": str(r.get(h_map.get("chain"), asset)), "Tx Hash": tx_h,
                    "Source Type": str(r.get(h_map.get("type"), "Blockchain")),
                    "Category": "A vérifier", "Status": "Valide" if asset in valid_assets else "A vérifier",
                    "Imposable": sl.is_imposable_robust(r.get(h_map.get("imposable"), False)),
                    "Source_File": fn
                })
        except: pass

    res_df = ensure_v4_columns(pd.DataFrame(rows))
    res_df = sl.standardize_df_addresses(res_df)
    res_df = res_df.sort_values("Date", ascending=False).drop_duplicates().reset_index(drop=True)
    res_df = sl.apply_spam_filter(res_df, drop=False)

    return res_df

def run_fidelity_engine(new_df, old_df):
    """Preserves user qualifications using fingerprints."""
    if old_df.empty: return new_df

    f_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]

    new_df["_f"] = get_robust_fingerprint(new_df)
    old_df["_f"] = get_robust_fingerprint(old_df)

    # Map from Fingerprint to Edits
    edit_map = old_df.drop_duplicates("_f").set_index("_f")[f_cols].to_dict('index')

    def apply_edits(row):
        f = row["_f"]
        if f in edit_map:
            m = edit_map[f]
            for k in f_cols:
                if k in ["Category", "Status"]:
                    if str(m[k]) != "A vérifier": row[k] = m[k]
                elif k == "Imposable": row[k] = sl.is_imposable_robust(m[k])
                else: row[k] = m[k]
        return row

    merged = new_df.apply(apply_edits, axis=1)

    # Keep historical items from old journal not present in new harvest
    new_f_set = set(merged["_f"])
    only_old = old_df[~old_df["_f"].isin(new_f_set)]

    final = pd.concat([merged, only_old]).sort_values("Date", ascending=False).drop(columns=["_f"]).reset_index(drop=True)
    return ensure_v4_columns(final)

def sync_session(year):
    QUAL_KEY = "_hub_journal_qualifie"
    disk_path = sl.get_file_path(year, 'qualified')
    harvest_df = merge_raw_sources(year)

    old_df = pd.DataFrame()
    if QUAL_KEY in st.session_state and not st.session_state[QUAL_KEY].empty:
        # Year check
        if pd.to_datetime(st.session_state[QUAL_KEY]["Date"].iloc[0]).year == year:
            old_df = st.session_state[QUAL_KEY]

    if old_df.empty and os.path.exists(disk_path):
        old_df = sl.pd_read_csv_safe(disk_path)

    st.session_state[QUAL_KEY] = run_fidelity_engine(harvest_df, old_df)
    st.session_state["_hub_last_loaded_year"] = year

# --- SIDEBAR ---

with st.sidebar:
    st.header("⚙️ Configuration")
    conf = sl.load_global_config()

    cur_year = st.number_input("Année de traitement", 2015, 2030, value=int(conf.get("processing_year", 2025)), key="_hub_app2_year")
    if cur_year != conf.get("processing_year"):
        conf["processing_year"] = int(cur_year)
        sl.save_global_config(conf)
        st.cache_data.clear()

    start_year_input = st.text_input("Année de début d'activité", value=str(conf.get("start_year", "")), placeholder="ex: 2025")
    if st.button("💾 Enregistrer Début", width='stretch'):
        conf["start_year"] = int(start_year_input) if start_year_input.strip() else None
        sl.save_global_config(conf)
        st.success("Config enregistrée."); st.rerun()

    st.divider()
    QUAL_KEY = "_hub_journal_qualifie"
    if QUAL_KEY not in st.session_state or st.session_state.get("_hub_last_loaded_year") != cur_year:
        sync_session(cur_year)

    st.button("🔄 Sync / Fusion (Harvest)", on_click=sync_session, args=(cur_year,), width='stretch', type="primary")

    st.header("📊 Filtres")
    if QUAL_KEY in st.session_state:
        df_f = st.session_state[QUAL_KEY]
        f_assets = st.multiselect("Assets", options=sl.get_safe_opts(df_f, "Asset"))
        f_accs = st.multiselect("Comptes", options=sl.get_owner_display_list(df_f))
        f_status = st.multiselect("Statuts", options=["A vérifier", "Valide", "Spam"])
        show_spams = st.toggle("Afficher les Spams", value=False)
        if st.button("⚡ Appliquer Filtres"): st.rerun()

    st.divider()
    with st.expander("👥 Registres"):
        owners = sl.load_owner_accounts()
        new_acc = st.text_input("Ajouter Compte (0x...)", key="sidebar_add_acc")
        new_lbl = st.text_input("Label", key="sidebar_add_lbl")
        if st.button("➕ Ajouter"):
            if new_acc: owners[new_acc.lower()] = new_lbl; sl.save_owner_accounts(owners); st.rerun()
        st.dataframe(pd.DataFrame(list(owners.items()), columns=["Addr", "Label"]), hide_index=True)

# --- MAIN UI ---

t_qual, t_reconc, t_audit = st.tabs(["📋 Qualification", "🤝 Réconciliation", "🔍 Audit & Restauration"])

with t_qual:
    st.subheader(f"Journal {cur_year}")
    if QUAL_KEY in st.session_state:
        df_v = st.session_state[QUAL_KEY].copy()
        if not show_spams: df_v = df_v[df_v["Status"] != "Spam"]
        if f_assets: df_v = df_v[df_v["Asset"].isin(f_assets)]
        if f_accs: df_v = sl.filter_df_by_owner_display(df_v, f_accs)
        if f_status: df_v = df_v[df_v["Status"].isin(f_status)]

        if st.button("🔍 Auto-détection Transferts Internes", width='stretch'):
            df_upd, _ = sl.detect_internal_transfers(st.session_state[QUAL_KEY])
            st.session_state[QUAL_KEY] = df_upd; st.rerun()

        if "Sel." not in df_v.columns: df_v.insert(0, "Sel.", False)
        cat_list = sorted(list(set(["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense", "Frais", "Doublon à ignorer"] + [str(c) for c in st.session_state[QUAL_KEY]["Category"].unique() if not pd.isna(c)])))

        col_cfg = {
            "Sel.": st.column_config.CheckboxColumn("Sel."),
            "Category": st.column_config.SelectboxColumn("Catégorie", options=cat_list),
            "Status": st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam"]),
            "Imposable": st.column_config.CheckboxColumn("Imposable"),
            "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
            "Date": st.column_config.DatetimeColumn(disabled=True),
            "Source_File": None, "Linked_ID": None, "Link_Status": None
        }

        def on_edit():
            if "main_editor" in st.session_state:
                for idx_str, row in st.session_state.main_editor.get("edited_rows", {}).items():
                    idx = int(idx_str)
                    if idx in st.session_state[QUAL_KEY].index:
                        for col, val in row.items():
                            if col == "Imposable": val = sl.is_imposable_robust(val)
                            st.session_state[QUAL_KEY].at[idx, col] = val

        st.data_editor(df_v, column_config=col_cfg, key="main_editor", on_change=on_edit, width='stretch')

        c1, c2, c3 = st.columns(3)
        if c1.button("💶 Vers Flux Fiat (App 0)", width='stretch'):
            sel = df_v[df_v["Sel."]]
            if not sel.empty:
                count = sl.inject_to_app0(sel.drop(columns="Sel.").to_dict('records'), "Fiat", cur_year)
                st.session_state[QUAL_KEY].loc[sel.index, "Status"] = "Injecté"; st.success(f"{count} lignes injectées."); st.rerun()

        if c3.button("💾 Sanctuariser (Générer Journal)", width='stretch', type="primary"):
            st.session_state[QUAL_KEY].to_csv(sl.get_file_path(cur_year, 'qualified'), index=False, encoding="utf-8-sig")
            clean_df = sl.apply_spam_filter(st.session_state[QUAL_KEY], drop=True)
            mapping = sl.get_all_labels()
            def resolve(x):
                r = sl.resolve_raw_addr(x)
                return sl.format_owner_display(r, mapping[r]) if r in mapping else x
            clean_df["Account"] = clean_df["Account"].apply(resolve)
            clean_df["Counterparty"] = clean_df["Counterparty"].apply(resolve)
            clean_df.to_csv(sl.get_file_path(cur_year, 'qualified_clean'), index=False, encoding="utf-8-sig")
            st.balloons(); st.success("Sanctuarisation réussie.")

with t_audit:
    st.subheader("🔍 Audit & Restauration")
    if st.button("🚀 Comparer avec le Sanctuaire", width='stretch'):
        sanct_df = sl.get_sanctuary_transactions(cur_year)
        if sanct_df.empty: st.warning("Dossier sanctuary vide.")
        else:
            work_df = st.session_state.get(QUAL_KEY, pd.DataFrame())
            work_keys = set(get_robust_fingerprint(work_df))
            sanct_df["_f"] = get_robust_fingerprint(sanct_df)
            orphans = sanct_df[~sanct_df["_f"].isin(work_keys)].copy()

            if orphans.empty: st.success("✅ Intégrité parfaite.")
            else:
                st.error(f"⚠️ {len(orphans)} orphelins détectés.")
                if st.button("📥 Restaurer TOUT", type="primary", width='stretch'):
                    rows = []
                    for _, r in orphans.iterrows():
                        # Discovery maps for the row itself
                        m = {str(c).lower().replace(" ","").replace("_",""): c for c in r.index}
                        def gv(keys, default=""):
                            for k in keys:
                                if k in m: return str(r[m[k]])
                            return default
                        def ga():
                            for k in ["amount", "valueeth", "value", "quantity"]:
                                if k in m:
                                    try: return float(r[m[k]])
                                    except: pass
                            return 0.0
                        rows.append({
                            "Date": gv(["date"]), "Account": gv(["account"]), "Asset": gv(["asset", "tokensymbol"], "ETH").upper(),
                            "Amount": ga(), "Counterparty": gv(["counterparty", "to", "from"]),
                            "Tx Hash": gv(["txhash", "hash"]), "Network": gv(["chain"], "Blockchain"),
                            "Source Type": "Restored", "Category": "A vérifier", "Status": "A vérifier",
                            "Source_File": r.get("_orig_file", "Sanctuary")
                        })
                    new_data = ensure_v4_columns(pd.DataFrame(rows))
                    st.session_state[QUAL_KEY] = pd.concat([st.session_state[QUAL_KEY], new_data]).drop_duplicates(subset=["Date", "Account", "Asset", "Amount", "Tx Hash"]).reset_index(drop=True)
                    st.success("Restauration effectuée."); st.rerun()
                st.dataframe(orphans.drop(columns=["_f"]), hide_index=True)

sl.show_status()
