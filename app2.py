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
    "Category", "Status", "Imposable", "Linked_ID", "Link_Status", "VGP (EUR)"
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
def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                return {str(k).lower(): v for k, v in json.load(f).items()}
        except: return {}
    return {}

def save_position_labels(labels_dict):
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k).lower(): v for k, v in labels_dict.items()}, f, indent=4)

def apply_position_labels(df):
    """Associe les labels aux adresses de contrepartie selon le standard 'Identifier (Name)'."""
    if df.empty: return df
    df = df.copy()
    # Labels from positions
    labels = load_position_labels()
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
    rows, spam_list = [], sl.load_spam_list()

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
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": "EUR", "Amount": me if "Vente" in ft else -me, "Value ($)": ((me if "Vente" in ft else -me)/rt) if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat", "Category": "Flux Fiat", "Status": "Valide", "Imposable": False})
                        if asset != "EUR" and asset != "NAN" and qa > 0:
                            rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": asset, "Amount": qa if "Achat" in ft else -qa, "Value ($)": me/rt if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat-to-Crypto", "Category": "Achat" if "Achat" in ft else "Vente", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable"))})
                    else:
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", "")), "Counterparty": str(r.get("Counterparty", "")), "Asset": str(r.get("Asset", "")), "Amount": float(r.get("Amount", 0)), "Value ($)": 0, "Network": "Manual", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Manual", "Category": "Swap", "Status": "Valide", "Imposable": sl.is_imposable_robust(r.get("Imposable", False))})
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

                # Asset Status Logic: Whitelist (Valide) > Blacklist (Spam) > Default (A vérifier)
                if asset.upper().strip() in valid_assets:
                    st_ = "Valide"
                elif sl.resolve_raw_addr(cp) in spam_list or asset.lower() in spam_list:
                    st_ = "Spam"
                else:
                    st_ = "A vérifier"

                rows.append({
                    "Date": dt_val, "Account": acc, "Counterparty": cp, "Asset": asset, "Amount": amt,
                    "Value ($)": float(r.get("Value ($)") or r.get(h_map.get("value ($)")) or 0),
                    "Network": str(r.get("Chain") or r.get(h_map.get("chain"), asset)),
                    "Tx Hash": tx_h, "Source Type": str(r.get("Type") or "Blockchain"),
                    "Category": "A vérifier", "Status": st_, "Imposable": sl.is_imposable_robust(r.get("Imposable", False))
                })
        except: pass

    dff = ensure_columns(pd.DataFrame(rows))
    dff["Date"] = pd.to_datetime(dff["Date"], utc=True, errors="coerce")
    dff = sl.standardize_df_addresses(dff)
    dff["_d"] = dff["Date"].dt.date
    dff = dff.sort_values("Date", ascending=False).drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account", "_d"], keep="first")
    return apply_position_labels(dff.drop(columns=["_d"]).reset_index(drop=True))

def sync_data(year):
    qp, ndf = sl.get_file_path(year, 'qualified'), merge_raw_data(year); st.session_state.last_sync_time = time.time()
    if os.path.exists(qp) and os.path.getsize(qp) > 0:
        try:
            odf = ensure_columns(sl.pd_read_csv_safe(qp)); odf = sl.standardize_df_addresses(odf); odf["Date"] = pd.to_datetime(odf["Date"], utc=True, errors="coerce")
            if not ndf.empty:
                # Fidelity Engine: Preserve manual user overrides during sync
                f_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]
                ndf["_d"], odf["_d"] = ndf["Date"].dt.date, odf["Date"].dt.date
                h_map = odf[odf["Tx Hash"] != ""].drop_duplicates("Tx Hash").set_index("Tx Hash")[f_cols].to_dict('index')
                m_map = odf[odf["Tx Hash"] == ""].drop_duplicates(["_d", "Account", "Asset"]).set_index(["_d", "Account", "Asset"])[f_cols].to_dict('index')

                def reap(r):
                    h, fm = str(r["Tx Hash"]), None
                    if h and h in h_map: fm = h_map[h]
                    elif (r["_d"], r["Account"], r["Asset"]) in m_map:
                         # For manual/empty hash txs, we match by date/acc/asset
                         fm = m_map[(r["_d"], r["Account"], r["Asset"])]

                    if fm:
                        # Carry over manual qualifications
                        for k in f_cols:
                            # Only overwrite if the old value was meaningful (not default "A vérifier")
                            if k == "Category" and fm[k] != "A vérifier": r[k] = fm[k]
                            elif k == "Status" and fm[k] != "A vérifier": r[k] = fm[k]
                            elif k in ["VGP (EUR)", "Linked_ID", "Link_Status"]: r[k] = fm[k]

                        # Imposable flag preservation (OR logic: if either was imposable, it stays imposable)
                        r["Imposable"] = sl.is_imposable_robust(r["Imposable"]) or sl.is_imposable_robust(fm["Imposable"])
                    else:
                        r["Imposable"] = sl.is_imposable_robust(r["Imposable"])
                    return r
                res = ndf.apply(reap, axis=1).drop(columns=["_d"])
                nh, nk = set(res["Tx Hash"].unique()), set(zip(ndf["Date"].dt.date, ndf["Account"], ndf["Asset"]))
                only_o = odf[~odf.apply(lambda r: (r["Tx Hash"] != "" and r["Tx Hash"] in nh) or ((r["Date"].date(), r["Account"], r["Asset"]) in nk), axis=1)]
                st.session_state.journal_qualifie = ensure_columns(pd.concat([res, only_o]).sort_values("Date", ascending=False).reset_index(drop=True))
            else: st.session_state.journal_qualifie = odf
        except: st.session_state.journal_qualifie = ndf
    else: st.session_state.journal_qualifie = ndf

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres app2")
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state:
        st.session_state["_hub_target_year"] = datetime.now().year

    target_year = st.number_input("Année fiscale", 2015, 2030, key="_hub_target_year")
    if "journal_qualifie" not in st.session_state or st.session_state.get("last_year") != target_year:
        sl.clean_session_state(preserve_keys=["last_year"])
        st.cache_data.clear(); sync_data(target_year); st.session_state.last_year = target_year
    st.button("🔄 Sync / Fusion", on_click=sync_data, args=(target_year,), width='stretch')

    c_auto1, c_auto2 = st.columns(2)
    if c_auto1.button("🛡️ Spam Auto", width='stretch', help="Marque comme 'Spam' les assets/contreparties dans la Blacklist."):
        if "journal_qualifie" in st.session_state:
            s_list, df = sl.load_spam_list(), st.session_state.journal_qualifie
            v_list = sl.load_valid_assets()
            # On n'écrase pas si déjà marqué 'Valide' par la whitelist
            mask = (df["Counterparty"].fillna("").str.lower().apply(sl.resolve_raw_addr).isin(s_list) | df["Asset"].fillna("").str.lower().isin(s_list)) & (~df["Asset"].str.upper().isin(v_list))
            df.loc[mask, "Status"] = "Spam"; st.rerun()

    if c_auto2.button("✅ Valide Auto", width='stretch', help="Marque comme 'Valide' les assets dans la Whitelist."):
        if "journal_qualifie" in st.session_state:
            v_list, df = sl.load_valid_assets(), st.session_state.journal_qualifie
            mask = df["Asset"].fillna("").str.upper().isin(v_list)
            df.loc[mask, "Status"] = "Valide"; st.rerun()

    st.divider(); st.header("📊 Filtres")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_f = st.session_state.journal_qualifie
        fa = st.multiselect("Asset", options=sl.get_safe_opts(df_f, "Asset"))
        fac = st.multiselect("Account", options=sl.get_owner_display_list(df_f))
        fst, fct = st.multiselect("Statut", options=sl.get_safe_opts(df_f, "Status")), st.multiselect("Catégorie", options=sl.get_safe_opts(df_f, "Category"))
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
                sl.save_valid_assets(set(ed_vl["Valid Asset"].dropna().str.upper().strip())); st.rerun()

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
        pl = load_position_labels()
        if pl:
            ed_pl = st.data_editor(pd.DataFrame(list(pl.items()), columns=["Adresse", "Label"]), num_rows="dynamic", width='stretch', key="ed_prot_sidebar")
            if st.button("💾 Sauver Liste Positions", key="btn_save_pl_sidebar"):
                save_position_labels({str(r["Adresse"]).lower(): r["Label"] for _, r in ed_pl.iterrows()}); st.rerun()

            sa_pl = st.selectbox("Gérer une position", options=[""]+sorted(list(pl.keys())), format_func=lambda x: f"{pl[x]} ({x})" if x else "Sélectionner...", key="sel_pl_mgr")
            if sa_pl:
                ml_pl = st.text_input("Nouveau Nom", value=pl[sa_pl], key="mod_lbl_acc_pl")
                if st.button("💾 Appliquer modification", key="btn_mod_pl_sidebar"):
                    pl[sa_pl]=ml_pl.strip(); save_position_labels(pl); st.rerun()
                if st.button("🗑️ Supprimer du registre", key="btn_del_pl_sidebar"):
                    del pl[sa_pl]; save_position_labels(pl); st.rerun()

# --- Main App ---
t_q, t_r = st.tabs(["📋 Qualification", "🤝 Réconciliation"])

with t_q:
    st.subheader(f"Journal de Qualification {target_year}")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_full = st.session_state.journal_qualifie; df_full["_d"] = df_full["Date"].dt.date
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
                    st.session_state.journal_qualifie = df_full
                    st.success("Fusion terminée.")
                    st.rerun()

        dfd = st.session_state.journal_qualifie.copy()
        if fa: dfd = dfd[dfd["Asset"].isin(fa)]
        if fac: dfd = sl.filter_df_by_owner_display(dfd, fac)
        if fst: dfd = dfd[dfd["Status"].isin(fst)]
        if fct: dfd = dfd[dfd["Category"].isin(fct)]
        dfd = dfd.reset_index(drop=True)
        if "Sel." not in dfd.columns:
            dfd.insert(0, "Sel.", False)
        if st.button("🔍 Détecter Transferts Internes", width='stretch'):
            df, ct = sl.detect_internal_transfers(st.session_state.journal_qualifie); st.session_state.journal_qualifie = df; st.rerun()
        cats = sorted(list(set(["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense", "Frais", "Doublon à ignorer"] + list(dfd["Category"].unique()))))

        # Style logic for highlighting suspect duplicates
        if not real_s.empty:
            suspect_hashes = set(real_s["Tx Hash"].unique())
            def highlight_dups(row):
                return ['background-color: #ffcccc'] * len(row) if row["Tx Hash"] in suspect_hashes else [''] * len(row)
            df_styled = dfd.style.apply(highlight_dups, axis=1)
        else:
            df_styled = dfd

        edf = st.data_editor(df_styled, column_config={"Sel.":st.column_config.CheckboxColumn("Sel."),"Category":st.column_config.SelectboxColumn("Catégorie", options=cats),"Status":st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam"]),"Imposable":st.column_config.CheckboxColumn("Imposable"),"Date":st.column_config.DatetimeColumn(disabled=True),"Account":st.column_config.TextColumn(disabled=True),"Amount":st.column_config.NumberColumn(format="%.6f", disabled=True)}, width='stretch', key="qual_editor_v17")

        c1, c2 = st.columns(2)
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
        if st.button("💾 Sanctuariser", type="primary", width='stretch'):
            fj, ec = st.session_state.journal_qualifie, edf.drop(columns=["Sel."])
            if not (fa or fac or fst or fct): fj = ec
            else: fj.update(ec)
            fj = fj[fj["Category"] != "Doublon à ignorer"]; st.session_state.journal_qualifie = fj; fj.to_csv(sl.get_file_path(target_year, 'qualified'), index=False, encoding="utf-8-sig"); st.balloons(); st.success("Sauvé.")

with t_r:
    st.subheader("🤝 Réconciliation des Maillons")
    if "journal_qualifie" in st.session_state:
        df_r = st.session_state.journal_qualifie

        c_r1, c_r2 = st.columns([1, 2])
        if c_r1.button("🚀 Lancer recherche auto", width='stretch'):
            df_upd, count = sl.find_reconciliation_matches(df_r)
            st.session_state.journal_qualifie = df_upd
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
