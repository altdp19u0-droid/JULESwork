import os
import time
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic as sl

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Qualification (app2)", layout="wide")

st.title("⚖️ Qualification & Nettoyage (Step 2)")

EXPORT_BASE_DIR = "sanctuarisation"

# Schema Unifié (Ordre et colonnes garantis)
COLUMNS = [
    "Date", "Account", "Counterparty", "Asset", "Amount",
    "Value ($)", "Network", "Tx Hash", "Source Type",
    "Category", "Status", "Imposable", "Linked_ID", "Link_Status", "VGP (EUR)",
    "Source_File"
]

def ensure_columns(df):
    """Garantit que le DataFrame possède toutes les colonnes du schéma et nettoie les types."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)

    # 1. Normalize existing column names
    df.columns = [str(c).strip() for c in df.columns]

    df_copy = df.copy()
    for c in COLUMNS:
        if c not in df_copy.columns:
            # Case insensitive lookup
            matches = [oc for oc in df_copy.columns if str(oc).lower().replace(" ","").replace("_","") == c.lower().replace(" ","").replace("_","")]
            if matches:
                df_copy = df_copy.rename(columns={matches[0]: c})
            else:
                if c == "Imposable": df_copy[c] = False
                elif c in ["Amount", "Value ($)", "VGP (EUR)"]: df_copy[c] = 0.0
                else: df_copy[c] = ""

    # 2. Forced Numeric Conversion
    for c in ["Amount", "Value ($)", "VGP (EUR)"]:
        if c in df_copy.columns:
            df_copy[c] = pd.to_numeric(df_copy[c], errors='coerce').fillna(0.0)

    # 3. Robust Imposable detection
    if "Imposable" in df_copy.columns:
        df_copy["Imposable"] = df_copy["Imposable"].apply(sl.is_imposable_robust)

    # 4. Strict Date Cleaning (Fixes TypeError by ensuring all are Timestamps)
    if "Date" in df_copy.columns:
        df_copy["Date"] = pd.to_datetime(df_copy["Date"], utc=True, errors="coerce")
        df_copy = df_copy.dropna(subset=["Date"])

    return df_copy[COLUMNS]

# --- Helpers ---

def apply_position_labels(df):
    """Associe les labels aux adresses de contrepartie selon le standard 'Identifier (Name)'."""
    if df.empty: return df
    df = df.copy()
    mapping = sl.get_all_labels()

    def format_val(val):
        r = sl.resolve_raw_addr(val)
        if r in mapping:
             return sl.format_owner_display(r, mapping[r])
        return sl.standardize_address_string(val)

    if "Counterparty" in df.columns:
        df["Counterparty"] = df["Counterparty"].apply(format_val)
    if "Account" in df.columns:
        df["Account"] = df["Account"].apply(lambda x: sl.standardize_address_string(x))
    return df

# --- Engine ---
def merge_raw_data(year):
    yd = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(yd): return ensure_columns(pd.DataFrame())
    rows = []

    # 1. Manual Registries
    man_files = [f for f in os.listdir(yd) if ("manual_fiat" in f or "manual_swaps" in f) and f.endswith(".csv")]
    for p in man_files:
        fp = os.path.join(yd, p)
        try:
            df = sl.pd_read_csv_safe(fp)
            if df.empty: continue
            for _, r in df.iterrows():
                if "fiat" in p:
                    me, qa, asset, ft = float(r.get("Montant EUR", 0)), float(r.get("Quantité", 0)), str(r.get("Asset", "EUR")).upper(), str(r.get("Type", ""))
                    rt = sl.get_fiat_rate("USD", pd.to_datetime(r.get("Date"), utc=True))
                    rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": "EUR", "Amount": me if "Vente" in ft else -me, "Value ($)": ((me if "Vente" in ft else -me)/rt) if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat", "Category": "Flux Fiat", "Status": "Valide", "Imposable": False, "Source_File": p})
                    if asset != "EUR" and qa > 0:
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": asset, "Amount": qa if "Achat" in ft else -qa, "Value ($)": me/rt if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat-to-Crypto", "Category": "Achat" if "Achat" in ft else "Vente", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable")), "Source_File": p})
                else:
                    rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", "")), "Counterparty": str(r.get("Counterparty", "")), "Asset": str(r.get("Asset", "")), "Amount": float(r.get("Amount", 0)), "Value ($)": 0, "Network": "Manual", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Manual", "Category": "Swap", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable", False)), "Source_File": p})
        except: pass

    # 2. Blockchain
    valid_assets = sl.load_valid_assets()
    all_raw_files = sl.get_all_raw_files(year)
    for f_p in all_raw_files:
        fn = os.path.basename(f_p)
        src = sl.extract_source_from_filename(fn); sl.auto_register_owner(src)
        try:
            df_raw = sl.pd_read_csv_safe(f_p)
            if df_raw.empty: continue
            df_raw.columns = [str(c).strip() for c in df_raw.columns]
            h_map = {str(c).lower().replace(" ","").replace("_",""): c for c in df_raw.columns}

            for _, r in df_raw.iterrows():
                dt_val = r.get(h_map.get("date"))
                if pd.isna(dt_val) or str(dt_val).lower() in ["nan", "none", ""]: continue

                acc = str(r.get(h_map.get("account"), src)).lower()
                tx_h = str(r.get(h_map.get("txhash"), r.get(h_map.get("hash"), "")))
                asset = str(r.get(h_map.get("asset"), r.get(h_map.get("tokensymbol"), r.get(h_map.get("chain"), "ETH")))).upper()

                amt = r.get(h_map.get("amount"))
                if amt is None: amt = r.get(h_map.get("valueeth"))
                if amt is None: amt = r.get(h_map.get("value"))
                if amt is None: amt = r.get(h_map.get("quantity"), 0)
                amt = float(amt)

                if fn.startswith("raw_portfolio_"):
                    rows.append({"Date": datetime(year, 12, 31), "Account": acc, "Counterparty": "Blockchain Snapshot", "Asset": asset, "Amount": amt, "Value ($)": float(r.get(h_map.get("value($)"), 0)), "Network": str(r.get(h_map.get("chain"), asset)), "Tx Hash": f"PORT-{src}-{asset}", "Source Type": "Portfolio", "Category": "Inventaire", "Status": "Valide", "Imposable": False})
                    continue

                fa = sl.resolve_raw_addr(r.get(h_map.get("from"), ""))
                cp = str(r.get(h_map.get("counterparty"), ""))
                if not cp or cp == "nan":
                    cp = r.get(h_map.get("to"), "") if fa == acc else r.get(h_map.get("from"), "")

                if "amount" not in h_map and fa == acc: amt = -amt

                rows.append({
                    "Date": dt_val, "Account": acc, "Counterparty": cp, "Asset": asset, "Amount": amt,
                    "Value ($)": float(r.get(h_map.get("value($)"), 0)),
                    "Network": str(r.get(h_map.get("chain"), asset)),
                    "Tx Hash": tx_h, "Source Type": str(r.get(h_map.get("type"), "Blockchain")),
                    "Category": "A vérifier", "Status": "Valide" if asset in valid_assets else "A vérifier",
                    "Imposable": sl.is_imposable_robust(r.get(h_map.get("imposable"), False)),
                    "Source_File": fn
                })
        except: pass

    dff = ensure_columns(pd.DataFrame(rows))
    dff = sl.standardize_df_addresses(dff)
    dff = dff.sort_values("Date", ascending=False).drop_duplicates().reset_index(drop=True)
    dff = sl.apply_spam_filter(dff, drop=False)

    return dff

def sync_data(year):
    QUAL_KEY = "_hub_journal_qualifie"
    qp = sl.get_file_path(year, 'qualified')
    ndf = merge_raw_data(year)

    odf = pd.DataFrame()
    if QUAL_KEY in st.session_state and not st.session_state[QUAL_KEY].empty:
        # Filter for same year
        temp_odf = st.session_state[QUAL_KEY]
        if not temp_odf.empty:
            try:
                if pd.to_datetime(temp_odf["Date"]).dt.year.iloc[0] == year:
                    odf = temp_odf
            except: pass

    if odf.empty and os.path.exists(qp) and os.path.getsize(qp) > 0:
        odf = sl.pd_read_csv_safe(qp)

    if not odf.empty:
        odf = ensure_columns(odf)
        odf = sl.standardize_df_addresses(odf)

        f_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]
        ndf["_d"], odf["_d"] = ndf["Date"].dt.date, odf["Date"].dt.date

        h_map = odf[odf["Tx Hash"] != ""].drop_duplicates("Tx Hash").set_index("Tx Hash")[f_cols].to_dict('index')
        m_map = odf[odf["Tx Hash"] == ""].drop_duplicates(["_d", "Account", "Asset", "Amount"]).set_index(["_d", "Account", "Asset", "Amount"])[f_cols].to_dict('index')

        def reap(r):
            h, fm = str(r["Tx Hash"]), None
            if h and h in h_map: fm = h_map[h]
            elif (r["_d"], r["Account"], r["Asset"], r["Amount"]) in m_map:
                 fm = m_map[(r["_d"], r["Account"], r["Asset"], r["Amount"])]
            if fm:
                for k in f_cols:
                    if k in ["Category", "Status"] and str(fm[k]) != "A vérifier": r[k] = fm[k]
                    elif k == "Imposable": r[k] = sl.is_imposable_robust(fm[k])
                    else: r[k] = fm[k]
            return r

        res = ndf.apply(reap, axis=1)
        nh = set(res["Tx Hash"].unique()); nk = set(zip(ndf["_d"], ndf["Account"], ndf["Asset"], ndf["Amount"]))
        only_o = odf[~odf.apply(lambda r: (r["Tx Hash"] != "" and r["Tx Hash"] in nh) or ((r["_d"], r["Account"], r["Asset"], r["Amount"]) in nk), axis=1)]

        final_df = pd.concat([res, only_o]).drop(columns=["_d"])
        # Final ensure_columns to fix date types before sorting
        final_df = ensure_columns(final_df).sort_values("Date", ascending=False).reset_index(drop=True)
        st.session_state[QUAL_KEY] = final_df
    else:
        st.session_state[QUAL_KEY] = ndf

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Configuration")
    g_conf = sl.load_global_config()
    target_year = st.number_input("Année de traitement d'activité", 2015, 2030, value=int(g_conf.get("processing_year", 2025)), key="_hub_target_year")
    if target_year != g_conf.get("processing_year"):
        g_conf["processing_year"] = int(target_year); sl.save_global_config(g_conf); st.cache_data.clear()

    start_year_val = g_conf.get("start_year")
    start_year_input = st.text_input("Année de début d'activité", value=str(start_year_val) if start_year_val else "", placeholder="ex: 2025")
    if st.button("💾 Fixer l'année de début", width='stretch'):
        g_conf["start_year"] = int(start_year_input) if start_year_input.strip() else None
        sl.save_global_config(g_conf); st.success("Réglage enregistré."); st.rerun()

    QUAL_KEY = "_hub_journal_qualifie"
    if QUAL_KEY not in st.session_state or st.session_state.get("_hub_last_loaded_year") != target_year:
        sync_data(target_year); st.session_state["_hub_last_loaded_year"] = target_year

    st.button("🔄 Sync / Fusion", on_click=sync_data, args=(target_year,), width='stretch', type="primary")

    c_auto1, c_auto2 = st.columns(2)
    if c_auto1.button("🛡️ Spam Auto", width='stretch', help="Qualifie comme Spam selon la Blacklist."):
        st.session_state[QUAL_KEY] = sl.apply_spam_filter(st.session_state[QUAL_KEY], drop=False); st.rerun()
    if c_auto2.button("✅ Valide Auto", width='stretch', help="Qualifie comme Valide selon la Whitelist."):
        v_list = sl.load_valid_assets()
        st.session_state[QUAL_KEY].loc[st.session_state[QUAL_KEY]["Asset"].isin(v_list), "Status"] = "Valide"; st.rerun()

    st.divider(); st.header("📊 Filtres")
    if QUAL_KEY in st.session_state:
        df_f = st.session_state[QUAL_KEY]
        fa = st.multiselect("Asset", options=sl.get_safe_opts(df_f, "Asset"))
        fac = st.multiselect("Account", options=sl.get_owner_display_list(df_f))
        fst = st.multiselect("Statut", options=["A vérifier", "Valide", "Spam", "Injecté"])
        show_spams = st.toggle("Afficher les Spams", value=False)
        if st.button("⚡ Appliquer"): st.rerun()

    st.divider(); st.header("⚙️ Référentiels")
    # --- Unified Registration Form ---
    with st.expander("➕ Enregistrement Unifié", expanded=True):
        reg_addr = st.text_input("Adresse / Hash", placeholder="0x... ou Label", key="reg_addr_input")
        reg_name = st.text_input("Nom / Label", placeholder="Nom de l'entité", key="reg_name_input")
        reg_type = st.selectbox("Type", ["Compte Propriétaire", "Position (Protocole)", "Circuit (Bridge/Swap)", "Spam"], key="reg_type_select")
        if st.button("💾 Enregistrer", width='stretch'):
            if reg_addr and reg_name:
                raw = sl.resolve_raw_addr(reg_addr)
                if reg_type == "Compte Propriétaire": om = sl.load_owner_accounts(); om[raw] = reg_name; sl.save_owner_accounts(om)
                elif reg_type == "Position (Protocole)": pl = sl.load_position_labels(); pl[raw] = reg_name; sl.save_position_labels(pl)
                elif reg_type == "Circuit (Bridge/Swap)": ec = sl.load_external_circuits(); ec["labels"][raw] = reg_name; sl.save_external_circuits(ec)
                elif reg_type == "Spam": sl.save_spam_list(sl.load_spam_list() | {raw.lower()})
                st.success(f"Enregistré : {reg_name}"); st.rerun()

    with st.expander("🛡️ Blacklist Spams"):
        s_list = sl.load_spam_list()
        ed_sl = st.data_editor(pd.DataFrame(sorted(list(s_list)), columns=["Spam"]), num_rows="dynamic", width='stretch', key="ed_spam_sidebar")
        if st.button("💾 Sauver Spams"): sl.save_spam_list(set(ed_sl["Spam"].dropna())); st.rerun()

    with st.expander("👥 Comptes Propriétaires"):
        om = sl.load_owner_accounts()
        ed_om = st.data_editor(pd.DataFrame(list(om.items()), columns=["Addr", "Label"]), num_rows="dynamic", width='stretch', key="ed_owners_sidebar")
        if st.button("💾 Sauver Propriétaires"): sl.save_owner_accounts({str(r["Addr"]).lower(): r["Label"] for _, r in ed_om.iterrows()}); st.rerun()

    with st.expander("🌐 Circuits & Externes"):
        ec = sl.load_external_circuits(); lb = ec.get("labels", {})
        ed_lb = st.data_editor(pd.DataFrame(list(lb.items()), columns=["Addr", "Label"]), num_rows="dynamic", width='stretch', key="ed_circ_sidebar")
        if st.button("💾 Sauver Circuits"): ec["labels"] = {str(r["Addr"]).lower(): r["Label"] for _, r in ed_lb.iterrows()}; sl.save_external_circuits(ec); st.rerun()
        disc = sl.get_external_circuits_discovery(st.session_state.get(QUAL_KEY))
        if disc: st.write("**Découvertes :**"); st.dataframe(pd.DataFrame(disc), hide_index=True)

    with st.expander("✅ Whitelist Assets"):
        v_assets = sl.load_valid_assets()
        ed_vl = st.data_editor(pd.DataFrame(sorted(list(v_assets)), columns=["Asset Valid"]), num_rows="dynamic", width='stretch', key="ed_valid_sidebar")
        if st.button("💾 Sauver Whitelist"): sl.save_valid_assets(set(ed_vl["Asset Valid"].dropna().str.upper().str.strip())); st.rerun()

    with st.expander("🏦 Positions (Protocoles)"):
        pl = sl.load_position_labels()
        ed_pl = st.data_editor(pd.DataFrame(list(pl.items()), columns=["Addr", "Label"]), num_rows="dynamic", width='stretch', key="ed_prot_sidebar")
        if st.button("💾 Sauver Positions"): sl.save_position_labels({str(r["Addr"]).lower(): r["Label"] for _, r in ed_pl.iterrows()}); st.rerun()

# --- Main App ---
t_q, t_r, t_audit = st.tabs(["📋 Qualification", "🤝 Réconciliation", "🔍 Audit & Récupération"])

with t_q:
    st.subheader(f"Journal de Qualification {target_year}")
    if QUAL_KEY in st.session_state and not st.session_state[QUAL_KEY].empty:
        # Detect Suspect Duplicates
        df_full = st.session_state[QUAL_KEY]; df_full["_d"] = df_full["Date"].dt.date
        sd_mask = (df_full.get("Category") != "Doublon à ignorer") & (df_full.get("Category") != "Doublon (Fusionné)")
        dups = df_full[sd_mask][df_full[sd_mask].duplicated(subset=["Asset", "Amount", "Account", "_d"], keep=False)]
        real_s = dups.groupby(["Asset", "Amount", "Account", "_d"]).filter(lambda x: x["Tx Hash"].nunique() > 1) if not dups.empty else pd.DataFrame()

        if not real_s.empty:
            with st.expander(f"⚠️ {len(real_s.groupby(['Asset','Amount','Account','_d']))} Doublons suspects", expanded=True):
                st.dataframe(real_s[["Date", "Account", "Asset", "Amount", "Tx Hash"]], hide_index=True)
                if st.button("🤝 Fusion Auto", width='stretch'):
                    for n, g in real_s.groupby(["Asset", "Amount", "Account", "_d"]):
                        sorted_idx = g.sort_values(by=["Category", "Source Type"], ascending=[False, True]).index
                        df_full.loc[sorted_idx[1:], "Category"] = "Doublon (Fusionné)"
                        df_full.loc[sorted_idx[1:], "Status"] = "Spam"
                    st.session_state[QUAL_KEY] = df_full; st.success("Fusion terminée."); st.rerun()

        dfd = st.session_state[QUAL_KEY].copy()
        if not show_spams: dfd = dfd[dfd["Status"] != "Spam"]
        if fa: dfd = dfd[dfd["Asset"].isin(fa)]
        if fac: dfd = sl.filter_df_by_owner_display(dfd, fac)
        if fst: dfd = dfd[dfd["Status"].isin(fst)]

        if "Sel." not in dfd.columns: dfd.insert(0, "Sel.", False)
        if st.button("🔍 Détecter Transferts Internes", width='stretch'):
            df, _ = sl.detect_internal_transfers(st.session_state[QUAL_KEY]); st.session_state[QUAL_KEY] = df; st.rerun()

        cats = sorted(list(set(["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense", "Frais", "Doublon à ignorer"] + [str(c) for c in st.session_state[QUAL_KEY]["Category"].unique() if not pd.isna(c)])))

        def on_editor_change():
            if "qual_editor_v2" in st.session_state:
                main_j = st.session_state[QUAL_KEY]
                for idx_str, row in st.session_state["qual_editor_v2"].get("edited_rows", {}).items():
                    idx = int(idx_str)
                    if idx in main_j.index:
                        for col, val in row.items():
                             if col == "Imposable": val = sl.is_imposable_robust(val)
                             main_j.at[idx, col] = val
                st.session_state[QUAL_KEY] = main_j

        col_cfg = {
            "Sel.": st.column_config.CheckboxColumn("Sel."),
            "Category": st.column_config.SelectboxColumn("Catégorie", options=cats),
            "Status": st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam", "Injecté"]),
            "Imposable": st.column_config.CheckboxColumn("Imposable"),
            "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
            "Date": st.column_config.DatetimeColumn(disabled=True),
            "Source_File": None, "Linked_ID": None, "Link_Status": None, "_d": None
        }

        # Highlight suspect duplicates in table
        suspect_hashes = set(real_s["Tx Hash"].unique()) if not real_s.empty else set()
        def highlight_dups(row):
            return ['background-color: #ffcccc'] * len(row) if row["Tx Hash"] in suspect_hashes else [''] * len(row)

        edf = st.data_editor(dfd.style.apply(highlight_dups, axis=1), column_config=col_cfg, width='stretch', key="qual_editor_v2", on_change=on_editor_change)

        c1, c2, c3 = st.columns(3)
        if c1.button("💶 Injecter vers Flux Fiat", width='stretch'):
            sel = edf[edf["Sel."]]
            if not sel.empty:
                count = sl.inject_to_app0(sel.drop(columns="Sel.").to_dict('records'), "Fiat", target_year)
                st.session_state[QUAL_KEY].loc[sel.index, "Status"] = "Injecté"; st.success(f"{count} lignes injectées."); st.rerun()

        with c3.popover("🗑️ Supprimer / Restaurer", width='stretch'):
            if st.button("⏪ Restaurer vers État RAW", width='stretch'):
                sel_idx = edf[edf["Sel."]].index
                if not sel_idx.empty: st.session_state[QUAL_KEY].drop(index=sel_idx, inplace=True); st.rerun()
            if st.button("🔥 Éliminer DÉFINITIVEMENT du RAW", width='stretch'):
                sel_rows = edf[edf["Sel."]]
                for _, r in sel_rows.iterrows():
                    if r.get("Source_File"): sl.remove_row_from_csv(os.path.join(EXPORT_BASE_DIR, str(target_year), r["Source_File"]), r)
                st.session_state[QUAL_KEY].drop(index=sel_rows.index, inplace=True); st.rerun()

        if st.button("💾 Sanctuariser (Générer CLEAN)", type="primary", width='stretch'):
            st.session_state[QUAL_KEY].to_csv(sl.get_file_path(target_year, 'qualified'), index=False, encoding="utf-8-sig")
            clean_j = apply_position_labels(sl.apply_spam_filter(st.session_state[QUAL_KEY], drop=True))
            clean_j.to_csv(sl.get_file_path(target_year, 'qualified_clean'), index=False, encoding="utf-8-sig")
            st.balloons(); st.success("Sanctuarisation réussie !"); time.sleep(1); st.rerun()

with t_r:
    st.subheader("🤝 Réconciliation")
    if QUAL_KEY in st.session_state:
        df_r = st.session_state[QUAL_KEY]
        if st.button("🚀 Rechercher Maillons", width='stretch'):
            df_upd, count = sl.find_reconciliation_matches(df_r)
            st.session_state[QUAL_KEY] = df_upd; st.success(f"{count} maillons trouvés."); st.rerun()
        prop = df_r[df_r["Link_Status"] == "Proposed"].groupby("Linked_ID")
        for lid, gp in prop:
            with st.container(border=True):
                cols = st.columns([3, 1])
                cols[0].write(f"🔗 Maillon `{lid}`")
                if cols[1].button("✅ Confirmer", key=f"conf_{lid}"):
                    st.session_state[QUAL_KEY].loc[st.session_state[QUAL_KEY]["Linked_ID"] == lid, "Link_Status"] = "Confirmed"; st.rerun()
                st.dataframe(gp[["Date", "Account", "Asset", "Amount", "Counterparty"]], hide_index=True)

with t_audit:
    st.subheader("🔍 Audit & Récupération")
    if st.button("🚀 Analyse du Sanctuaire", width='stretch'):
        sanct = sl.get_sanctuary_transactions(target_year)
        if sanct.empty: st.warning("Sanctuaire vide.")
        else:
            def get_f(df):
                if df.empty: return pd.Series()
                d = pd.to_datetime(df["Date"], utc=True, errors='coerce').dt.strftime('%Y%m%d')
                acc = df["Account"].apply(sl.resolve_raw_addr).str.lower()
                h = df.get("Tx_Hash", df.get("Tx Hash", df.get("hash", ""))).astype(str).str.lower()
                return d + "_" + acc + "_" + h
            s_f = get_f(sanct); w_f = set(get_f(st.session_state[QUAL_KEY]))
            orphans = sanct[~s_f.isin(w_f)].copy()
            if orphans.empty: st.success("✅ Intégrité parfaite.")
            else:
                st.error(f"⚠️ {len(orphans)} orphelins.")
                if st.button("📥 Restaurer TOUT", type="primary", width='stretch'):
                    rows = []
                    for _, r in orphans.iterrows():
                        rows.append({"Date": r.get("Date"), "Account": r.get("Account"), "Asset": r.get("Asset", "ETH"), "Amount": float(r.get("Amount", r.get("value eth", 0))), "Counterparty": r.get("Counterparty", r.get("To", r.get("From", ""))), "Tx Hash": r.get("Tx Hash", r.get("hash", "")), "Source Type": "Restored", "Status": "A vérifier", "Category": "A vérifier", "Source_File": r.get("_orig_file", "Sanctuary")})
                    st.session_state[QUAL_KEY] = pd.concat([st.session_state[QUAL_KEY], ensure_columns(pd.DataFrame(rows))]).drop_duplicates().reset_index(drop=True)
                    st.rerun()
                st.dataframe(orphans, hide_index=True)

sl.show_status()
