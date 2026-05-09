import os
import time
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic

# --- Configuration ---
# st.set_page_config(page_title="Jules Crypto - Qualification (app2)", layout="wide")
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
    """Garantit que le DataFrame possède toutes les colonnes du schéma."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df_copy = df.copy()
    for c in COLUMNS:
        if c not in df_copy.columns:
            if c == "Imposable": df_copy[c] = False
            elif c in ["Amount", "Value ($)", "VGP (EUR)"]: df_copy[c] = 0.0
            else: df_copy[c] = ""
    if "VGP (EUR)" in df_copy.columns:
        df_copy["VGP (EUR)"] = pd.to_numeric(df_copy["VGP (EUR)"], errors='coerce').fillna(0.0)
    if "Imposable" in df_copy.columns:
        df_copy["Imposable"] = df_copy["Imposable"].apply(shared_logic.is_imposable_robust)
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
    """Associe les labels aux adresses de contrepartie."""
    if df.empty: return df
    labels = load_position_labels()
    ext_data = shared_logic.load_external_circuits()
    circ_labels = ext_data.get("labels", {})
    owners_map = shared_logic.load_owner_accounts()
    combined = {**circ_labels, **owners_map, **labels}
    def format_cp(cp):
        r = shared_logic.resolve_raw_addr(cp)
        return f"{combined[r]} ({r})" if r in combined else cp
    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    return df

# --- Engine ---
def merge_raw_data(year):
    yd = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(yd): return ensure_columns(pd.DataFrame())
    rows, sl = [], shared_logic.load_spam_list()

    # 1. Manual Registries
    for p, t in [(f"manual_fiat_{year}.csv", "Fiat"), (f"manual_swaps_{year}.csv", "Swap")]:
        fp = os.path.join(yd, p)
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            try:
                df = shared_logic.pd_read_csv_safe(fp)
                for _, r in df.iterrows():
                    if t == "Fiat":
                        me, qa, asset, ft = float(r.get("Montant EUR", 0)), float(r.get("Quantité", 0)), str(r.get("Asset", "EUR")).upper(), str(r.get("Type", ""))
                        rt = shared_logic.get_fiat_rate("USD", pd.to_datetime(r.get("Date"), utc=True))
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": "EUR", "Amount": me if "Vente" in ft else -me, "Value ($)": ((me if "Vente" in ft else -me)/rt) if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat", "Category": "Flux Fiat", "Status": "Valide", "Imposable": False})
                        if asset != "EUR" and asset != "NAN" and qa > 0:
                            rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))), "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))), "Asset": asset, "Amount": qa if "Achat" in ft else -qa, "Value ($)": me/rt if rt>0 else 0, "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Fiat-to-Crypto", "Category": "Achat" if "Achat" in ft else "Vente", "Status": "Valide", "Imposable": shared_logic.is_imposable_robust(r.get("Imposable"))})
                    else:
                        rows.append({"Date": r.get("Date"), "Account": str(r.get("Account", "")), "Counterparty": str(r.get("Counterparty", "")), "Asset": str(r.get("Asset", "")), "Amount": float(r.get("Amount", 0)), "Value ($)": 0, "Network": "Manual", "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Manual", "Category": "Swap", "Status": "Valide", "Imposable": shared_logic.is_imposable_robust(r.get("Imposable", False))})
            except: pass

    # 2. Blockchain
    for f_p in shared_logic.get_all_raw_files(year):
        fn = os.path.basename(f_p)
        src = shared_logic.extract_source_from_filename(fn); shared_logic.auto_register_owner(src)
        if os.path.getsize(f_p) == 0: continue
        try:
            df = shared_logic.pd_read_csv_safe(f_p)
            for _, r in df.iterrows():
                acc = str(r.get("Account", src)).lower()
                if fn.startswith("raw_transactions_"):
                    fa, cp = shared_logic.resolve_raw_addr(r.get("From", "")), str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = r.get("To", "") if fa == acc else r.get("From", "")
                    amt, asset = float(r.get("Value ETH", 0)), str(r.get("Chain", "ETH"))
                    if fa == acc: amt = -amt
                    st_ = "Spam" if (shared_logic.resolve_raw_addr(cp) in sl or asset.lower() in sl) else "A vérifier"
                    rows.append({"Date": r.get("Date"), "Account": acc, "Counterparty": cp, "Asset": asset, "Amount": amt, "Value ($)": float(r.get("Value ($)") or 0), "Network": asset, "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Native", "Category": "A vérifier", "Status": st_, "Imposable": shared_logic.is_imposable_robust(r.get("Imposable", False))})
                elif fn.startswith("raw_token_transfers_"):
                    fa, cp = shared_logic.resolve_raw_addr(r.get("From", "")), str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = str(r.get("To", "")) if fa == acc else str(r.get("From", ""))
                    amt, asset = float(r.get("Value", 0)), str(r.get("Token", ""))
                    if fa == acc: amt = -amt
                    st_ = "Spam" if (shared_logic.resolve_raw_addr(cp) in sl or asset.lower() in sl) else "A vérifier"
                    rows.append({"Date": r.get("Date"), "Account": acc, "Counterparty": cp, "Asset": asset, "Amount": amt, "Value ($)": float(r.get("Value ($)") or 0), "Network": str(r.get("Chain", "")), "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Token", "Category": "A vérifier", "Status": st_, "Imposable": shared_logic.is_imposable_robust(r.get("Imposable", False))})
                elif fn.startswith("raw_portfolio_"):
                    rows.append({"Date": datetime(year, 12, 31), "Account": acc, "Counterparty": "Blockchain Snapshot", "Asset": str(r.get("Asset", "UNKNOWN")), "Amount": float(r.get("Quantity", 0)), "Value ($)": float(r.get("Value ($)") or 0), "Network": str(r.get("Chain", "")), "Tx Hash": f"PORT-{src}-{r.get('Asset')}", "Source Type": "Portfolio", "Category": "Inventaire", "Status": "Valide", "Imposable": False})
        except: pass

    dff = ensure_columns(pd.DataFrame(rows))
    dff["Date"] = pd.to_datetime(dff["Date"], utc=True, errors="coerce")
    dff = shared_logic.standardize_df_addresses(dff)
    dff["_d"] = dff["Date"].dt.date
    dff = dff.sort_values("Date", ascending=False).drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account", "_d"], keep="first")
    return apply_position_labels(dff.drop(columns=["_d"]).reset_index(drop=True))

def sync_data(year):
    qp, ndf = shared_logic.get_file_path(year, 'qualified'), merge_raw_data(year); st.session_state.last_sync_time = time.time()
    if os.path.exists(qp) and os.path.getsize(qp) > 0:
        try:
            odf = ensure_columns(shared_logic.pd_read_csv_safe(qp)); odf = shared_logic.standardize_df_addresses(odf); odf["Date"] = pd.to_datetime(odf["Date"], utc=True, errors="coerce")
            if not ndf.empty:
                f_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]
                ndf["_d"], odf["_d"] = ndf["Date"].dt.date, odf["Date"].dt.date
                h_map = odf[odf["Tx Hash"] != ""].drop_duplicates("Tx Hash").set_index("Tx Hash")[f_cols].to_dict('index')
                m_map = odf[odf["Tx Hash"] == ""].drop_duplicates(["_d", "Account", "Asset"]).set_index(["_d", "Account", "Asset"])[f_cols].to_dict('index')
                def reap(r):
                    h, fm = str(r["Tx Hash"]), None
                    if h and h in h_map: fm = h_map[h]
                    elif (r["_d"], r["Account"], r["Asset"]) in m_map: fm = m_map[(r["_d"], r["Account"], r["Asset"])]
                    if fm:
                        for k in f_cols: r[k] = fm[k]
                        r["Imposable"] = shared_logic.is_imposable_robust(r["Imposable"]) or shared_logic.is_imposable_robust(fm["Imposable"])
                    else: r["Imposable"] = shared_logic.is_imposable_robust(r["Imposable"])
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
    target_year = st.number_input("Année fiscale", 2015, 2030, datetime.now().year, key="_hub_app2_year")
    if "journal_qualifie" not in st.session_state or st.session_state.get("last_year") != target_year:
        shared_logic.clean_session_state(preserve_keys=["last_year", "_hub_app2_year"])
        st.cache_data.clear(); sync_data(target_year); st.session_state.last_year = target_year
    st.button("🔄 Sync / Fusion", on_click=sync_data, args=(target_year,), width='stretch')

    if st.button("🛡️ Nettoyage Spam Auto", width='stretch'):
        if "journal_qualifie" in st.session_state:
            sl, df = shared_logic.load_spam_list(), st.session_state.journal_qualifie
            mask = df["Counterparty"].fillna("").str.lower().apply(shared_logic.resolve_raw_addr).isin(sl) | df["Asset"].fillna("").str.lower().isin(sl)
            df.loc[mask, "Status"] = "Spam"; st.rerun()

    st.divider(); st.header("📊 Filtres")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_f = st.session_state.journal_qualifie
        fa, fac = st.multiselect("Asset", options=shared_logic.get_safe_opts(df_f, "Asset")), st.multiselect("Account", options=shared_logic.get_owner_addresses(df_f))
        fst, fct = st.multiselect("Statut", options=shared_logic.get_safe_opts(df_f, "Status")), st.multiselect("Catégorie", options=shared_logic.get_safe_opts(df_f, "Category"))
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
                raw = shared_logic.resolve_raw_addr(reg_addr)
                if reg_type == "Compte Propriétaire":
                    om = shared_logic.load_owner_accounts(); om[raw] = reg_name; shared_logic.save_owner_accounts(om)
                elif reg_type == "Position (Protocole)":
                    pl = load_position_labels(); pl[raw] = reg_name; save_position_labels(pl)
                elif reg_type == "Circuit (Bridge/Swap)":
                    ec = shared_logic.load_external_circuits(); ec["labels"][raw] = reg_name; shared_logic.save_external_circuits(ec)
                elif reg_type == "Spam":
                    sl = shared_logic.load_spam_list(); sl.add(raw.lower()); shared_logic.save_spam_list(sl)
                st.success(f"Enregistré : {reg_name}")
                st.rerun()
            else:
                st.error("Veuillez saisir une adresse et un nom.")

    with st.expander("🛡️ Blacklist Spams", expanded=False):
        sl = shared_logic.load_spam_list(); st.write(f"Blacklist : **{len(sl)}**")
        if sl:
            df_sl = pd.DataFrame(sorted(list(sl)), columns=["Spam Name/Address"])
            ed_sl = st.data_editor(df_sl, num_rows="dynamic", width='stretch', key="ed_spam_sidebar")
            if st.button("💾 Sauver Blacklist", key="btn_save_sl_sidebar"):
                shared_logic.save_spam_list(set(ed_sl["Spam Name/Address"].dropna())); st.rerun()

            # Modification/Suppression Individuelle
            sa_sl = st.selectbox("Gérer un spam", options=[""]+sorted(list(sl)), key="sel_sl_mgr")
            if sa_sl:
                if st.button("🗑️ Supprimer du registre", key="btn_del_sl_sidebar"):
                    sl.remove(sa_sl); shared_logic.save_spam_list(sl); st.rerun()

    with st.expander("👥 Comptes Propriétaires", expanded=False):
        om = shared_logic.load_owner_accounts()
        if om:
            ed_om = st.data_editor(pd.DataFrame(list(om.items()), columns=["Address", "Label"]), num_rows="dynamic", width='stretch', key="ed_owners_sidebar")
            if st.button("💾 Sauver Liste Propriétaires", key="btn_save_om_sidebar"):
                shared_logic.save_owner_accounts({str(r["Address"]).lower(): r["Label"] for _, r in ed_om.iterrows()}); st.rerun()

            sa_om = st.selectbox("Gérer un compte", options=[""]+sorted(list(om.keys())), format_func=lambda x: f"{om[x]} ({x})" if x else "Sélectionner...", key="sel_om_mgr")
            if sa_om:
                ml_om = st.text_input("Nouveau Nom", value=om[sa_om], key="mod_lbl_acc_om")
                if st.button("💾 Appliquer modification", key="btn_mod_om_sidebar"):
                    om[sa_om]=ml_om.strip(); shared_logic.save_owner_accounts(om); st.rerun()
                if st.button("🗑️ Supprimer du registre", key="btn_del_om_sidebar"):
                    del om[sa_om]; shared_logic.save_owner_accounts(om); st.rerun()

    with st.expander("🌐 Circuits (Swaps/Bridges)", expanded=False):
        ec = shared_logic.load_external_circuits(); lb = ec.get("labels", {})
        if lb:
            ed_lb = st.data_editor(pd.DataFrame(list(lb.items()), columns=["Address", "Label"]), num_rows="dynamic", width='stretch', key="ed_circ_sidebar")
            if st.button("💾 Sauver Liste Circuits", key="btn_save_ec_sidebar"):
                ec["labels"] = {str(r["Address"]).lower(): r["Label"] for _, r in ed_lb.iterrows()}; shared_logic.save_external_circuits(ec); st.rerun()

            sa_ec = st.selectbox("Gérer un circuit", options=[""]+sorted(list(lb.keys())), format_func=lambda x: f"{lb[x]} ({x})" if x else "Sélectionner...", key="sel_ec_mgr")
            if sa_ec:
                ml_ec = st.text_input("Nouveau Nom", value=lb[sa_ec], key="mod_lbl_acc_ec")
                if st.button("💾 Appliquer modification", key="btn_mod_ec_sidebar"):
                    ec["labels"][sa_ec]=ml_ec.strip(); shared_logic.save_external_circuits(ec); st.rerun()
                if st.button("🗑️ Supprimer du registre", key="btn_del_ec_sidebar"):
                    del ec["labels"][sa_ec]; shared_logic.save_external_circuits(ec); st.rerun()

        circ_disc = shared_logic.get_external_circuits_discovery(st.session_state.get("journal_qualifie"))
        if circ_disc: st.write("**Dernières découvertes :**"); st.dataframe(pd.DataFrame(circ_disc), hide_index=True)

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
        if fac: dfd = dfd[dfd["Account"].isin(fac)]
        if fst: dfd = dfd[dfd["Status"].isin(fst)]
        if fct: dfd = dfd[dfd["Category"].isin(fct)]
        dfd = dfd.reset_index(drop=True)
        if "Sel." not in dfd.columns:
            dfd.insert(0, "Sel.", False)
        if st.button("🔍 Détecter Transferts Internes", width='stretch'):
            df, ct = shared_logic.detect_internal_transfers(st.session_state.journal_qualifie); st.session_state.journal_qualifie = df; st.rerun()
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
                count = shared_logic.inject_to_app0(selected, "Fiat", target_year)
                st.success(f"{count} lignes injectées vers le registre Fiat.")
            else: st.warning("Veuillez d'abord sélectionner des lignes via la colonne 'Sel.'.")

        if c2.button("🔄 Injecter vers Swaps (App 0)", width='stretch'):
            selected = edf[edf["Sel."]].drop(columns="Sel.").to_dict('records')
            if selected:
                count = shared_logic.inject_to_app0(selected, "Swap", target_year)
                st.success(f"{count} lignes injectées vers le registre Swaps.")
            else: st.warning("Veuillez d'abord sélectionner des lignes via la colonne 'Sel.'.")
        if st.button("💾 Sanctuariser", type="primary", width='stretch'):
            fj, ec = st.session_state.journal_qualifie, edf.drop(columns=["Sel."])
            if not (fa or fac or fst or fct): fj = ec
            else: fj.update(ec)
            fj = fj[fj["Category"] != "Doublon à ignorer"]; st.session_state.journal_qualifie = fj; fj.to_csv(shared_logic.get_file_path(target_year, 'qualified'), index=False, encoding="utf-8-sig"); st.balloons(); st.success("Sauvé.")

with t_r:
    st.subheader("🤝 Réconciliation des Maillons")
    if "journal_qualifie" in st.session_state:
        df_r = st.session_state.journal_qualifie

        c_r1, c_r2 = st.columns([1, 2])
        if c_r1.button("🚀 Lancer recherche auto", width='stretch'):
            df_upd, count = shared_logic.find_reconciliation_matches(df_r)
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

shared_logic.show_status()
