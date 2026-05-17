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
POSITIONS_FILE = "position_labels.json"

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
    df.columns = [c.strip() for c in df.columns]

    df_copy = df.copy()
    for c in COLUMNS:
        if c not in df_copy.columns:
            # Case insensitive lookup for missing columns
            matches = [oc for oc in df_copy.columns if oc.lower() == c.lower()]
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

    # 4. Strict Date Cleaning
    if "Date" in df_copy.columns:
        df_copy["Date"] = pd.to_datetime(df_copy["Date"], utc=True, errors="coerce")
        # Remove rows without dates as they break fiscal logic
        df_copy = df_copy.dropna(subset=["Date"])

    return df_copy[COLUMNS]

# --- Helpers ---

def apply_position_labels(df):
    """Associe les labels aux adresses de contrepartie selon le standard 'Identifier (Name)'."""
    if df.empty: return df
    df = df.copy()
    # Labels from positions
    labels = sl.load_position_labels()
    # Labels from circuits
    ext_data = sl.load_external_circuits()
    circ_labels = ext_data.get("labels", {})
    # Labels from owners
    owners_map = sl.load_owner_accounts()

    combined = {**circ_labels, **owners_map, **labels}

    def format_cp(cp):
        r = sl.resolve_raw_addr(cp)
        if r in combined:
             return sl.format_owner_display(r, combined[r])
        return sl.standardize_address_string(cp)

    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    df["Account"] = df["Account"].apply(lambda x: sl.standardize_address_string(x))
    return df

# --- Engine ---
def merge_raw_data(year):
    yd = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(yd): return ensure_columns(pd.DataFrame())
    rows = []

    # 1. Manual Registries
    for p, t in [(f"manual_fiat_{year}.csv", "Fiat"), (f"manual_swaps_{year}.csv", "Swap")]:
        fp = os.path.join(yd, p)
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            try:
                df = sl.pd_read_csv_safe(fp)
                for _, r in df.iterrows():
                    if t == "Fiat":
                        me, qa, asset, ft = float(r.get("Montant EUR", 0)), float(r.get("Quantité", 0)), str(r.get("Asset", "EUR")).upper(), str(r.get("Type", ""))
                        rt = sl.get_fiat_rate("USD", pd.to_datetime(r.get("Date"), utc=True))
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": "EUR", "Amount": me if "Vente" in ft else -me, "Value ($)": ((me if "Vente" in ft else -me)/rt) if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat", "Category": "Flux Fiat", "Status": "Valide", "Imposable": False, "Source_File": p})
                        if asset != "EUR" and asset != "NAN" and qa > 0:
                            rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": asset, "Amount": qa if "Achat" in ft else -qa, "Value ($)": me/rt if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat-to-Crypto", "Category": "Achat" if "Achat" in ft else "Vente", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable")), "Source_File": p})
                    else:
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", "")), "Counterparty": str(r.get("Counterparty", "")), "Asset": str(r.get("Asset", "")), "Amount": float(r.get("Amount", 0)), "Value ($)": 0, "Network": "Manual", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Manual", "Category": "Swap", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable", False)), "Source_File": p})
            except: pass

    # 2. Blockchain
    valid_assets = sl.load_valid_assets()
    for f_p in sl.get_latest_raw_files(year):
        fn = os.path.basename(f_p)
        src = sl.extract_source_from_filename(fn); sl.auto_register_owner(src)
        if os.path.getsize(f_p) == 0: continue
        try:
            df_raw = sl.pd_read_csv_safe(f_p)
            # Normalization of headers to ensure 'Date' is found
            df_raw.columns = [c.strip() for c in df_raw.columns]
            h_map = {c.lower(): c for c in df_raw.columns}

            # Priority: use V4 columns if present, fallback to legacy
            for _, r in df_raw.iterrows():
                dt_val = r.get("Date") or r.get(h_map.get("date"))
                if pd.isna(dt_val) or str(dt_val).lower() in ["nan", "none", ""]: continue

                acc = str(r.get("Account") or r.get(h_map.get("account"), src)).lower()
                tx_h = str(r.get("Tx_Hash") or r.get("Tx Hash") or r.get(h_map.get("tx hash"), ""))
                asset = str(r.get("Asset") or r.get(h_map.get("asset")) or r.get(h_map.get("tokenSymbol")) or r.get(h_map.get("chain"), "ETH")).upper()
                amt = float(r.get("Amount") or r.get(h_map.get("amount")) or r.get(h_map.get("value eth")) or r.get(h_map.get("value")) or r.get(h_map.get("quantity"), 0))

                if fn.startswith("raw_portfolio_"):
                    rows.append({"Date": datetime(year, 12, 31), "Account": acc, "Counterparty": "Blockchain Snapshot", "Asset": asset, "Amount": amt, "Value ($)": float(r.get("Value ($)") or r.get(h_map.get("value ($)")) or 0), "Network": str(r.get("Chain") or r.get(h_map.get("chain"), "")), "Tx Hash": f"PORT-{src}-{asset}", "Source Type": "Portfolio", "Category": "Inventaire", "Status": "Valide", "Imposable": False})
                    continue

                fa = sl.resolve_raw_addr(r.get("From") or r.get(h_map.get("from"), ""))
                cp = str(r.get("Counterparty") or r.get(h_map.get("counterparty"), ""))
                if not cp or cp == "nan":
                    cp = r.get("To") or r.get(h_map.get("to"), "") if fa == acc else r.get("From") or r.get(h_map.get("from"), "")

                # If we are in a non-V4 file, sign might not be handled yet
                if "Amount" not in df_raw.columns and fa == acc:
                    amt = -amt

                # Asset Status Logic: Whitelist (Valide) > Default (A vérifier)
                # Spam is now handled by centralized apply_spam_filter at the end of merge
                if asset.upper().strip() in valid_assets:
                    st_ = "Valide"
                else:
                    st_ = "A vérifier"

                rows.append({
                    "Date": dt_val, "Account": acc, "Counterparty": cp, "Asset": asset, "Amount": amt,
                    "Value ($)": float(r.get("Value ($)") or r.get(h_map.get("value ($)")) or 0),
                    "Network": str(r.get("Chain") or r.get(h_map.get("chain"), asset)),
                    "Tx Hash": tx_h, "Source Type": str(r.get("Type") or "Blockchain"),
                    "Category": "A vérifier", "Status": st_, "Imposable": sl.is_imposable_robust(r.get("Imposable", False)),
                    "Source_File": fn
                })
        except: pass

    dff = ensure_columns(pd.DataFrame(rows))
    dff["Date"] = pd.to_datetime(dff["Date"], utc=True, errors="coerce")
    dff = sl.standardize_df_addresses(dff)

    # We NO LONGER drop duplicates here to allow the user to see and manage them (suspect duplicates) in the UI.
    # We only drop EXACT line-by-line duplicates that might come from redundant file imports.
    dff = dff.sort_values("Date", ascending=False).drop_duplicates().reset_index(drop=True)

    # --- ZÉRO SPAM : Filtre de qualification ---
    dff = sl.apply_spam_filter(dff, drop=False)

    return apply_position_labels(dff)

def sync_data(year):
    # Use persistent session keys for the Hub
    QUAL_KEY = "_hub_journal_qualifie"
    qp = sl.get_file_path(year, 'qualified')
    ndf = merge_raw_data(year)
    st.session_state.last_sync_time = time.time()

    # 1. Identify "Old" data for the Fidelity Engine
    # Priority: current session (if same year) > disk file
    odf = pd.DataFrame()
    if QUAL_KEY in st.session_state and not st.session_state[QUAL_KEY].empty:
        # Check if session data matches the target year
        if pd.to_datetime(st.session_state[QUAL_KEY]["Date"]).dt.year.iloc[0] == year:
            odf = st.session_state[QUAL_KEY]

    if odf.empty and os.path.exists(qp) and os.path.getsize(qp) > 0:
        odf = sl.pd_read_csv_safe(qp)

    if not odf.empty:
        try:
            odf = ensure_columns(odf)
            odf = sl.standardize_df_addresses(odf)
            odf["Date"] = pd.to_datetime(odf["Date"], utc=True, errors="coerce")

            if not ndf.empty:
                # Fidelity Engine: Preserve manual user overrides during sync
                f_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]
                ndf["_d"], odf["_d"] = ndf["Date"].dt.date, odf["Date"].dt.date

                # 1. Match by Tx Hash (Strongest link)
                h_map = odf[odf["Tx Hash"] != ""].drop_duplicates("Tx Hash").set_index("Tx Hash")[f_cols].to_dict('index')
                # 2. Match by Content (Fallback for manual/ledger/empty hash entries)
                m_map = odf[odf["Tx Hash"] == ""].drop_duplicates(["_d", "Account", "Asset", "Amount"]).set_index(["_d", "Account", "Asset", "Amount"])[f_cols].to_dict('index')

                def reap(r):
                    h, fm = str(r["Tx Hash"]), None
                    if h and h in h_map: fm = h_map[h]
                    elif (r["_d"], r["Account"], r["Asset"], r["Amount"]) in m_map:
                         fm = m_map[(r["_d"], r["Account"], r["Asset"], r["Amount"])]

                    if fm:
                        for k in f_cols:
                            if k == "Category" and fm[k] != "A vérifier": r[k] = fm[k]
                            elif k == "Status" and fm[k] != "A vérifier": r[k] = fm[k]
                            elif k in ["VGP (EUR)", "Linked_ID", "Link_Status"]: r[k] = fm[k]
                        r["Imposable"] = sl.is_imposable_robust(r["Imposable"]) or sl.is_imposable_robust(fm["Imposable"])
                    else:
                        r["Imposable"] = sl.is_imposable_robust(r["Imposable"])
                    return r

                res = ndf.apply(reap, axis=1).drop(columns=["_d"])

                # Identify entries in old journal that are NOT in new harvest (keep them)
                nh = set(res["Tx Hash"].unique())
                nk = set(zip(ndf["Date"].dt.date, ndf["Account"], ndf["Asset"], ndf["Amount"]))
                only_o = odf[~odf.apply(lambda r: (r["Tx Hash"] != "" and r["Tx Hash"] in nh) or ((r["Date"].date(), r["Account"], r["Asset"], r["Amount"]) in nk), axis=1)]

                final_df = ensure_columns(pd.concat([res, only_o]).sort_values("Date", ascending=False).reset_index(drop=True))
                st.session_state[QUAL_KEY] = final_df
            else:
                st.session_state[QUAL_KEY] = odf
        except Exception as e:
            st.error(f"Erreur Fidelity Engine : {e}")
            st.session_state[QUAL_KEY] = ndf
    else:
        st.session_state[QUAL_KEY] = ndf

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Configuration")

    # Global Config Management
    g_conf = sl.load_global_config()

    # 1. Année de Traitement d'Activité (Persistent selection)
    default_year = g_conf.get("processing_year") or datetime.now().year
    # Hub prefix is preserved for cross-module compatibility
    target_year = st.number_input("Année de traitement d'activité", 2015, 2030, value=default_year, key="_hub_target_year")

    # Save selection to global config if changed
    if target_year != g_conf.get("processing_year"):
        g_conf["processing_year"] = int(target_year)
        sl.save_global_config(g_conf)

    # 2. Année de Début d'Activité
    start_year_val = g_conf.get("start_year")
    start_year_input = st.text_input("Année de début d'activité", value=str(start_year_val) if start_year_val else "", placeholder="ex: 2021 (Vide = Date du jour)")

    if st.button("💾 Fixer l'année de début"):
        if start_year_input.strip():
            try:
                sy = int(start_year_input.strip())
                g_conf["start_year"] = sy
                sl.save_global_config(g_conf)
                st.success(f"Année de début fixée à {sy}")
                st.rerun()
            except: st.error("Année invalide.")
        else:
            g_conf["start_year"] = None
            sl.save_global_config(g_conf)
            st.success("Réglage effacé.")
            st.rerun()

    QUAL_KEY = "_hub_journal_qualifie"
    YEAR_KEY = "_hub_last_year_app2"

    if QUAL_KEY not in st.session_state or st.session_state.get(YEAR_KEY) != target_year:
        st.cache_data.clear()
        sync_data(target_year)
        st.session_state[YEAR_KEY] = target_year
    st.button("🔄 Sync / Fusion", on_click=sync_data, args=(target_year,), width='stretch')

    c_auto1, c_auto2 = st.columns(2)
    if c_auto1.button("🛡️ Spam Auto", width='stretch', help="Marque comme 'Spam' les assets/contreparties dans la Blacklist."):
        if QUAL_KEY in st.session_state:
            df = st.session_state[QUAL_KEY]
            df = sl.apply_spam_filter(df, drop=False)
            st.session_state[QUAL_KEY] = df
            st.rerun()

    if c_auto2.button("✅ Valide Auto", width='stretch', help="Marque comme 'Valide' les assets dans la Whitelist."):
        if QUAL_KEY in st.session_state:
            v_list, df = sl.load_valid_assets(), st.session_state[QUAL_KEY]
            mask = df["Asset"].fillna("").str.upper().isin(v_list)
            df.loc[mask, "Status"] = "Valide"; st.rerun()

    st.divider(); st.header("📊 Filtres")
    if QUAL_KEY in st.session_state and not st.session_state[QUAL_KEY].empty:
        # Options are discovered from the FULL journal to avoid missing options when filters are active
        df_full_opt = st.session_state[QUAL_KEY]
        fa = st.multiselect("Asset", options=sl.get_safe_opts(df_full_opt, "Asset"))
        fac = st.multiselect("Account", options=sl.get_owner_display_list(df_full_opt))
        fcp = st.multiselect("Counterparty", options=sl.get_safe_opts(df_full_opt, "Counterparty"))

        # Ensure 'Spam' is always an option in Status filter
        stat_opts = sorted(list(set(["Spam", "Valide", "A vérifier"] + sl.get_safe_opts(df_full_opt, "Status"))))
        fst = st.multiselect("Statut", options=stat_opts)

        show_spams = st.toggle("Afficher les Spams", value=False, help="Affiche les transactions marquées comme Spam.")

        # Ensure categories are discovered from full journal and handle possible non-string values
        cat_opts = sorted(list(set(["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense", "Frais", "Doublon à ignorer"] + [str(c) for c in df_full_opt["Category"].unique() if not pd.isna(c)])))
        fct = st.multiselect("Catégorie", options=cat_opts)

        if st.button("⚡ Appliquer"): st.rerun()

    st.divider(); st.header("⚙️ Référentiels")

    # --- Unified Registration Form ---
    with st.expander("➕ Enregistrement Unifié", expanded=True):
        st.caption("Ajouter une adresse ou un label au registre approprié.")
        reg_addr = st.text_input("Adresse / Hash", placeholder="0x... ou Label", key="reg_addr_input")
        reg_name = st.text_input("Nom / Label", placeholder="Nom de l'entité", key="reg_name_input")
        reg_type = st.selectbox("Type de registre", ["Compte Propriétaire", "Position (Protocole)", "Circuit (Bridge/Swap)", "Spam"], key="reg_type_select")

        if st.button("💾 Enregistrer dans le registre", width='stretch'):
            if reg_addr and reg_name:
                raw = sl.resolve_raw_addr(reg_addr)
                if reg_type == "Compte Propriétaire":
                    om = sl.load_owner_accounts(); om[raw] = reg_name; sl.save_owner_accounts(om)
                elif reg_type == "Position (Protocole)":
                    pl = load_position_labels(); pl[raw] = reg_name; save_position_labels(pl)
                elif reg_type == "Circuit (Bridge/Swap)":
                    ec = sl.load_external_circuits(); ec["labels"][raw] = reg_name; sl.save_external_circuits(ec)
                elif reg_type == "Spam":
                    s_list = sl.load_spam_list(); s_list.add(raw.lower()); sl.save_spam_list(s_list)
                st.success(f"Enregistré : {reg_name}")
                st.rerun()
            else:
                st.error("Veuillez saisir une adresse et un nom.")

    with st.expander("🛡️ Récupération & Sanctuaire", expanded=False):
        st.info("Restaurez un fichier brut depuis le sanctuaire vers votre espace de travail.")
        s_files = []
        s_dir = os.path.join(EXPORT_BASE_DIR, str(target_year), "sanctuary")
        if os.path.exists(s_dir):
            s_files = [f for f in os.listdir(s_dir) if f.endswith(".csv") or f.endswith(".json")]

        if not s_files:
            st.write("Aucun fichier dans le sanctuaire pour cette année.")
        else:
            file_to_restore = st.selectbox("Fichier à restaurer", sorted(s_files), key="sel_restore")
            if st.button("🔄 Restaurer", width='stretch', help="Restaure ce fichier dans l'espace de travail. S'il s'agit d'une récolte, elle deviendra la plus récente."):
                import shutil
                src_path = os.path.join(s_dir, file_to_restore)

                # Logic: To make a restored harvest the "latest", we give it a fresh timestamp
                if file_to_restore.startswith("raw_"):
                    # raw_transactions_consolidated_0x..._20230101_120000.csv
                    # We append _RESTORED_TS
                    ts_now = datetime.now().strftime('%Y%m%d_%H%M%S')
                    base_name = file_to_restore.replace(".csv", "")
                    target_name = f"{base_name}_RESTORED_{ts_now}.csv"
                elif "verified_prices" in file_to_restore:
                    target_name = f"verified_prices_{target_year}.json"
                else:
                    target_name = file_to_restore

                shutil.copy(src_path, os.path.join(EXPORT_BASE_DIR, str(target_year), target_name))
                st.success(f"Restauré : {target_name}")
                st.info("Utilisez le bouton 'Sync / Fusion' pour prendre en compte ce fichier.")
                st.rerun()

    with st.expander("🛡️ Blacklist Spams", expanded=False):
        s_list = sl.load_spam_list(); st.write(f"Blacklist : **{len(s_list)}**")
        if s_list:
            df_sl = pd.DataFrame(sorted(list(s_list)), columns=["Spam Name/Address"])
            ed_sl = st.data_editor(df_sl, num_rows="dynamic", width='stretch', key="ed_spam_sidebar")
            if st.button("💾 Sauver Blacklist", key="btn_save_sl_sidebar"):
                sl.save_spam_list(set(ed_sl["Spam Name/Address"].dropna())); st.rerun()

            # Modification/Suppression Individuelle
            sa_sl = st.selectbox("Gérer un spam", options=[""]+sorted(list(s_list)), key="sel_sl_mgr")
            if sa_sl:
                if st.button("🗑️ Supprimer du registre", key="btn_del_sl_sidebar"):
                    s_list.remove(sa_sl); sl.save_spam_list(s_list); st.rerun()

    with st.expander("👥 Comptes Propriétaires", expanded=False):
        om = sl.load_owner_accounts()
        if om:
            # Table logic remains technical (Address/Label) for storage integrity
            ed_om = st.data_editor(pd.DataFrame(list(om.items()), columns=["Address/Hash", "Nom/Label"]), num_rows="dynamic", width='stretch', key="ed_owners_sidebar")
            if st.button("💾 Sauver Liste Propriétaires", key="btn_save_om_sidebar"):
                sl.save_owner_accounts({str(r["Address/Hash"]).lower(): r["Nom/Label"] for _, r in ed_om.iterrows()}); st.rerun()

            sa_om = st.selectbox("Gérer un compte", options=[""]+sorted(list(om.keys())), format_func=lambda x: sl.resolve_owner_display(x) if x else "Sélectionner...", key="sel_om_mgr")
            if sa_om:
                ml_om = st.text_input("Nouveau Nom", value=om[sa_om], key="mod_lbl_acc_om")
                if st.button("💾 Appliquer modification", key="btn_mod_om_sidebar"):
                    om[sa_om]=ml_om.strip(); sl.save_owner_accounts(om); st.rerun()
                if st.button("🗑️ Supprimer du registre", key="btn_del_om_sidebar"):
                    del om[sa_om]; sl.save_owner_accounts(om); st.rerun()

    with st.expander("🌐 Circuits (Swaps/Bridges)", expanded=False):
        ec = sl.load_external_circuits(); lb = ec.get("labels", {})
        if lb:
            ed_lb = st.data_editor(pd.DataFrame(list(lb.items()), columns=["Address", "Label"]), num_rows="dynamic", width='stretch', key="ed_circ_sidebar")
            if st.button("💾 Sauver Liste Circuits", key="btn_save_ec_sidebar"):
                ec["labels"] = {str(r["Address"]).lower(): r["Label"] for _, r in ed_lb.iterrows()}; sl.save_external_circuits(ec); st.rerun()

            sa_ec = st.selectbox("Gérer un circuit", options=[""]+sorted(list(lb.keys())), format_func=lambda x: f"{lb[x]} ({x})" if x else "Sélectionner...", key="sel_ec_mgr")
            if sa_ec:
                ml_ec = st.text_input("Nouveau Nom", value=lb[sa_ec], key="mod_lbl_acc_ec")
                if st.button("💾 Appliquer modification", key="btn_mod_ec_sidebar"):
                    ec["labels"][sa_ec]=ml_ec.strip(); sl.save_external_circuits(ec); st.rerun()
                if st.button("🗑️ Supprimer du registre", key="btn_del_ec_sidebar"):
                    del ec["labels"][sa_ec]; sl.save_external_circuits(ec); st.rerun()

        circ_disc = sl.get_external_circuits_discovery(st.session_state.get("journal_qualifie"))
        if circ_disc: st.write("**Dernières découvertes :**"); st.dataframe(pd.DataFrame(circ_disc), hide_index=True)

    with st.expander("✅ Whitelist Assets", expanded=False):
        v_assets = sl.load_valid_assets(); st.write(f"Whitelist : **{len(v_assets)}**")
        if v_assets:
            df_vl = pd.DataFrame(sorted(list(v_assets)), columns=["Valid Asset"])
            ed_vl = st.data_editor(df_vl, num_rows="dynamic", width='stretch', key="ed_valid_sidebar")
            if st.button("💾 Sauver Whitelist", key="btn_save_vl_sidebar"):
                sl.save_valid_assets(set(ed_vl["Valid Asset"].dropna().str.upper().str.strip())); st.rerun()

            # Modification/Suppression Individuelle
            sa_vl = st.selectbox("Gérer un asset valide", options=[""]+sorted(list(v_assets)), key="sel_vl_mgr")
            if sa_vl:
                if st.button("🗑️ Supprimer de la whitelist", key="btn_del_vl_sidebar"):
                    v_assets.remove(sa_vl); sl.save_valid_assets(v_assets); st.rerun()
        else:
            new_v_asset = st.text_input("Ajouter un asset à valider", placeholder="ex: BTC, ETH", key="add_v_asset_sidebar")
            if st.button("➕ Ajouter à la whitelist", key="btn_add_vl_sidebar"):
                if new_v_asset:
                    v_assets.add(new_v_asset.upper().strip()); sl.save_valid_assets(v_assets); st.rerun()

    with st.expander("🏦 Positions (Protocoles)", expanded=False):
        pl = sl.load_position_labels()
        if pl:
            ed_pl = st.data_editor(pd.DataFrame(list(pl.items()), columns=["Adresse", "Label"]), num_rows="dynamic", width='stretch', key="ed_prot_sidebar")
            if st.button("💾 Sauver Liste Positions", key="btn_save_pl_sidebar"):
                sl.save_position_labels({str(r["Adresse"]).lower(): r["Label"] for _, r in ed_pl.iterrows()}); st.rerun()

            sa_pl = st.selectbox("Gérer une position", options=[""]+sorted(list(pl.keys())), format_func=lambda x: f"{pl[x]} ({x})" if x else "Sélectionner...", key="sel_pl_mgr")
            if sa_pl:
                ml_pl = st.text_input("Nouveau Nom", value=pl[sa_pl], key="mod_lbl_acc_pl")
                if st.button("💾 Appliquer modification", key="btn_mod_pl_sidebar"):
                    pl[sa_pl]=ml_pl.strip(); sl.save_position_labels(pl); st.rerun()
                if st.button("🗑️ Supprimer du registre", key="btn_del_pl_sidebar"):
                    del pl[sa_pl]; sl.save_position_labels(pl); st.rerun()

# --- Main App ---
t_q, t_r = st.tabs(["📋 Qualification", "🤝 Réconciliation"])
QUAL_KEY = "_hub_journal_qualifie"

with t_q:
    st.subheader(f"Journal de Qualification {target_year}")
    if QUAL_KEY in st.session_state and not st.session_state[QUAL_KEY].empty:
        df_full = st.session_state[QUAL_KEY]; df_full["_d"] = df_full["Date"].dt.date
        sd_mask = (df_full.get("Category") != "Doublon à ignorer") & (df_full.get("Category") != "Doublon (Fusionné)")
        dups = df_full[sd_mask][df_full[sd_mask].duplicated(subset=["Asset", "Amount", "Account", "_d"], keep=False)]
        real_s = dups.groupby(["Asset", "Amount", "Account", "_d"]).filter(lambda x: x["Tx Hash"].nunique() > 1) if not dups.empty else pd.DataFrame()

        if not real_s.empty:
            with st.expander(f"⚠️ {len(real_s.groupby(['Asset','Amount','Account','_d']))} Groupes de doublons suspects détectés", expanded=True):
                st.info("Ces lignes ont le même montant, asset, compte et date, mais des Hashs différents (souvent Harvesting vs Manuel).")
                st.dataframe(real_s[["Date", "Account", "Asset", "Amount", "Source Type", "Category", "Tx Hash"]].sort_values(["Date", "Asset", "Amount"]), hide_index=True)

                if st.button("🤝 Confirmer la Fusion Auto (Marquer comme Spams)", width='stretch', key="btn_merge_dups"):
                    for n, g in real_s.groupby(["Asset", "Amount", "Account", "_d"]):
                        # On garde la ligne la plus 'riche' (catégorisée ou venant d'une source prioritaire)
                        sorted_indices = g.sort_values(by=["Category", "Source Type"], ascending=[False, True]).index
                        # On marque tous les autres comme Doublon (Fusionné) et Spam
                        df_full.loc[sorted_indices[1:], "Category"] = "Doublon (Fusionné)"
                        df_full.loc[sorted_indices[1:], "Status"] = "Spam"
                    st.session_state[QUAL_KEY] = df_full
                    st.success("Fusion terminée.")
                    st.rerun()

        dfd = st.session_state[QUAL_KEY].copy()
        if not show_spams:
            dfd = dfd[dfd["Status"] != "Spam"]

        if fa: dfd = dfd[dfd["Asset"].isin(fa)]
        if fac: dfd = sl.filter_df_by_owner_display(dfd, fac)
        if fcp: dfd = dfd[dfd["Counterparty"].isin(fcp)]
        if fst: dfd = dfd[dfd["Status"].isin(fst)]
        if fct: dfd = dfd[dfd["Category"].isin(fct)]

        # We DO NOT reset index here to maintain link with st.session_state[QUAL_KEY]
        if "Sel." not in dfd.columns:
            dfd.insert(0, "Sel.", False)

        if st.button("🔍 Détecter Transferts Internes", width='stretch'):
            df, ct = sl.detect_internal_transfers(st.session_state[QUAL_KEY]); st.session_state[QUAL_KEY] = df; st.rerun()

        # Bug Fix: Ensure all items are strings and handle potential NaNs before sorting to avoid TypeError
        raw_cats = [str(c) for c in st.session_state[QUAL_KEY]["Category"].unique() if not pd.isna(c) and str(c).strip() != ""]
        cats = sorted(list(set(["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense", "Frais", "Doublon à ignorer"] + raw_cats)))

        # Style logic for highlighting suspect duplicates
        if not real_s.empty:
            suspect_hashes = set(real_s["Tx Hash"].unique())
            def highlight_dups(row):
                return ['background-color: #ffcccc'] * len(row) if row["Tx Hash"] in suspect_hashes else [''] * len(row)
            df_styled = dfd.style.apply(highlight_dups, axis=1)
        else:
            df_styled = dfd

        def on_editor_change():
            if "qual_editor_v17" in st.session_state:
                changes = st.session_state["qual_editor_v17"]
                main_j = st.session_state[QUAL_KEY]

                # Apply edits from the editor back to the full journal in session
                for idx_str, edited_row in changes.get("edited_rows", {}).items():
                    idx = int(idx_str)
                    if idx in main_j.index:
                        for col, val in edited_row.items():
                             if col == "Category": main_j.at[idx, "Category"] = val
                             elif col == "Status": main_j.at[idx, "Status"] = val
                             elif col == "Imposable": main_j.at[idx, "Imposable"] = sl.is_imposable_robust(val)
                             elif col == "VGP (EUR)": main_j.at[idx, "VGP (EUR)"] = float(val)
                             elif col == "Linked_ID": main_j.at[idx, "Linked_ID"] = val
                             elif col == "Link_Status": main_j.at[idx, "Link_Status"] = val

                st.session_state[QUAL_KEY] = main_j

        col_cfg_q = {
            "Sel.": st.column_config.CheckboxColumn("Sel."),
            "Category": st.column_config.SelectboxColumn("Catégorie", options=cats),
            "Status": st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam"]),
            "Imposable": st.column_config.CheckboxColumn("Imposable"),
            "Date": st.column_config.DatetimeColumn(disabled=True),
            "Account": st.column_config.TextColumn(disabled=True),
            "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
            "VGP (EUR)": st.column_config.NumberColumn("VGP (EUR)", format="%.2f"),
            "Value ($)": st.column_config.NumberColumn("Value ($)", format="%.2f", disabled=True),
            "Source Type": st.column_config.TextColumn("Source Type", disabled=True),
            "Network": st.column_config.TextColumn("Réseau", disabled=True),
            # Technical columns hidden
            "Source_File": None,
            "Linked_ID": None,
            "Link_Status": None,
            "_d": None
        }

        edf = st.data_editor(df_styled, column_config=col_cfg_q, width='stretch', key="qual_editor_v17", on_change=on_editor_change)

        c1, c2, c3 = st.columns(3)
        if c1.button("💶 Injecter vers Flux Fiat (App 0)", width='stretch'):
            selected = edf[edf["Sel."]].drop(columns="Sel.").to_dict('records')
            if selected:
                count = sl.inject_to_app0(selected, "Fiat", target_year)
                st.success(f"{count} lignes injectées vers le registre Fiat.")
            else: st.warning("Veuillez d'abord sélectionner des lignes via la colonne 'Sel.'.")

        if c2.button("🔄 Injecter vers Swaps (App 0)", width='stretch'):
            selected = edf[edf["Sel."]].drop(columns="Sel.").to_dict('records')
            if selected:
                count = sl.inject_to_app0(selected, "Swap", target_year)
                st.success(f"{count} lignes injectées vers le registre Swaps.")
            else: st.warning("Veuillez d'abord sélectionner des lignes via la colonne 'Sel.'.")

        with c3.popover("🗑️ Supprimer / Restaurer", width='stretch'):
            st.info("Agit sur les lignes sélectionnées (colonne 'Sel.').")
            if st.button("⏪ Restaurer vers État RAW", help="Supprime la modification dans le journal qualifié. La transaction redeviendra visible comme 'A vérifier' issue de la collecte originale.", width='stretch'):
                selected_indices = edf[edf["Sel."]].index
                if not selected_indices.empty:
                    st.session_state[QUAL_KEY] = st.session_state[QUAL_KEY].drop(index=selected_indices)
                    st.success(f"{len(selected_indices)} lignes restaurées vers l'état RAW.")
                    time.sleep(1); st.rerun()
                else: st.warning("Aucune sélection.")

            if st.button("🔥 Éliminer DÉFINITIVEMENT du RAW", help="Supprime la transaction du fichier source original (working raw). Elle ne réapparaîtra plus jamais lors des prochaines synchronisations (sauf restauration manuelle via le Sanctuaire).", width='stretch'):
                selected_rows = edf[edf["Sel."]].drop(columns="Sel.")
                if not selected_rows.empty:
                    count_del = 0
                    for _, s_row in selected_rows.iterrows():
                        src_f = s_row.get("Source_File")
                        if src_f:
                            f_path = os.path.join(EXPORT_BASE_DIR, str(target_year), src_f)
                            if sl.remove_row_from_csv(f_path, s_row):
                                count_del += 1
                    # Also remove from current session journal
                    st.session_state[QUAL_KEY] = st.session_state[QUAL_KEY].drop(index=selected_rows.index)
                    st.success(f"{count_del} lignes éliminées définitivement des fichiers RAW.")
                    time.sleep(1); st.rerun()
                else: st.warning("Aucune sélection.")

        if st.button("💾 Sanctuariser", type="primary", width='stretch'):
            # Source of truth is st.session_state[QUAL_KEY]
            # (already partially updated by on_editor_change)
            main_j = st.session_state[QUAL_KEY]

            # Final check from the latest state of the editor (edf)
            # to ensure everything is captured
            for idx, row in edf.iterrows():
                if idx in main_j.index:
                    main_j.at[idx, "Category"] = row["Category"]
                    main_j.at[idx, "Status"] = row["Status"]
                    main_j.at[idx, "Imposable"] = sl.is_imposable_robust(row["Imposable"])
                    if "VGP (EUR)" in row: main_j.at[idx, "VGP (EUR)"] = float(row["VGP (EUR)"])
                    if "Linked_ID" in row: main_j.at[idx, "Linked_ID"] = row["Linked_ID"]
                    if "Link_Status" in row: main_j.at[idx, "Link_Status"] = row["Link_Status"]

            # Global cleanups
            main_j = main_j[main_j["Category"] != "Doublon à ignorer"]

            # Zéro Spam reinforcement
            main_j = sl.apply_spam_filter(main_j, drop=False)

            # Final Persistence
            st.session_state[QUAL_KEY] = main_j
            main_j.to_csv(sl.get_file_path(target_year, 'qualified'), index=False, encoding="utf-8-sig")

            st.balloons()
            st.success(f"Sanctuarisation réussie : {len(main_j)} lignes enregistrées.")
            time.sleep(1)
            st.rerun()

with t_r:
    st.subheader("🤝 Réconciliation des Maillons")
    if QUAL_KEY in st.session_state:
        df_r = st.session_state[QUAL_KEY]

        c_r1, c_r2 = st.columns([1, 2])
        if c_r1.button("🚀 Lancer recherche auto", width='stretch'):
            df_upd, count = sl.find_reconciliation_matches(df_r)
            st.session_state[QUAL_KEY] = df_upd
            st.success(f"{count} maillons potentiels détectés.")
            st.rerun()

        # Summary
        if not df_r.empty and "Link_Status" in df_r.columns:
            n_prop = df_r[df_r["Link_Status"] == "Proposed"]["Linked_ID"].nunique()
            n_conf = df_r[df_r["Link_Status"] == "Confirmed"]["Linked_ID"].nunique()
            c_r2.info(f"📊 **Statut :** {n_prop} proposés, {n_conf} confirmés.")

        # Display Proposed Links
        prop_groups = df_r[df_r["Link_Status"] == "Proposed"].groupby("Linked_ID")
        if not prop_groups.groups:
            st.info("Aucune réconciliation en attente de confirmation.")
        else:
            for lid, gp in prop_groups:
                with st.container(border=True):
                    cols = st.columns([3, 1])
                    cols[0].write(f"🔗 **Maillon Suspect :** `{lid}`")
                    if cols[1].button(f"✅ Confirmer", key=f"conf_{lid}"):
                        df_r.loc[df_r["Linked_ID"] == lid, "Link_Status"] = "Confirmed"
                        st.session_state.journal_qualifie = df_r
                        st.rerun()
                    st.dataframe(gp[["Date", "Account", "Asset", "Amount", "Counterparty", "Source Type"]], hide_index=True)

        # Display Confirmed Links (Collapsible)
        conf_groups = df_r[df_r["Link_Status"] == "Confirmed"].groupby("Linked_ID")
        if conf_groups.groups:
            with st.expander("✅ Voir les maillons confirmés"):
                for lid, gp in conf_groups:
                    st.write(f"✔️ Maillon `{lid}`")
                    st.dataframe(gp[["Date", "Account", "Asset", "Amount", "Counterparty"]], hide_index=True)
                    if st.button(f"🗑️ Annuler confirmation", key=f"unconf_{lid}"):
                        df_r.loc[df_r["Linked_ID"] == lid, "Link_Status"] = ""
                        df_r.loc[df_r["Linked_ID"] == lid, "Linked_ID"] = ""
                        st.session_state.journal_qualifie = df_r
                        st.rerun()

sl.show_status()
