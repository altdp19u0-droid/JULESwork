import streamlit as st
import pandas as pd
import shared_logic as sl
import os
import json
from datetime import datetime

# --- CONFIGURATION & SCHEMA ---
EXPORT_BASE_DIR = "sanctuarisation"

QUALIFIED_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account", "From", "To",
    "From_Label", "To_Label", "Counterparty", "Asset", "Amount",
    "Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset",
    "Fee_Asset", "Fee_Amount", "Source_Way", "Audit_Status", "Fee_Audit_Alert",
    "Source_Exchange_Rate", "VGP (EUR)", "Linked_ID", "Link_Status", "Category", "Imposable",
    "Source_File"
]

def ensure_columns(df):
    """Garantit le schéma V4 et la conversion stricte des dates en UTC."""
    if df is None or df.empty:
        return pd.DataFrame(columns=QUALIFIED_V4_COLUMNS)
    for col in QUALIFIED_V4_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # Nettoyage des dates : conversion forcée en UTC pour éviter TypeError lors des tris
    df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["VGP (EUR)"] = pd.to_numeric(df["VGP (EUR)"], errors="coerce").fillna(0.0)

    # New USD columns numeric conversion
    for usd_col in ["Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset"]:
        if usd_col in df.columns:
            df[usd_col] = pd.to_numeric(df[usd_col], errors="coerce").fillna(0.0)

    # Conversion stricte de Imposable en booléen pour l'éditeur Streamlit
    df["Imposable"] = df["Imposable"].apply(sl.is_imposable_robust)
    return df[QUALIFIED_V4_COLUMNS]

def discover_col(df, candidates):
    """Trouve une colonne dans un DataFrame à partir d'une liste de candidats (insensible à la casse)."""
    cols_map = {str(c).lower().strip().replace(" ","").replace("_","").replace("(","").replace(")",""): c for c in df.columns}
    for cand in candidates:
        norm_cand = cand.lower().strip().replace(" ","").replace("_","")
        if norm_cand in cols_map:
            return cols_map[norm_cand]
    return None

def merge_raw_data(year):
    """Fusionne toutes les sources RAW de l'année (Blockscout, Etherscan, Portfolio, Manuel)."""
    all_raw_files = sl.get_all_raw_files(year)
    rows = []

    # 1. Sources Blockchain (RAW_*)
    for f_p in all_raw_files:
        fn = os.path.basename(f_p)
        if fn.startswith("manual_") or fn.startswith("qualif_"): continue

        src = sl.extract_source_from_filename(fn)
        sl.auto_register_owner(src)
        df_raw = sl.pd_read_csv_safe(f_p)
        if df_raw.empty: continue

        # Cas spécifique : Snapshot Portfolio (souvent une seule ligne par asset au 31/12)
        if fn.startswith("raw_portfolio_"):
            d_c = discover_col(df_raw, ["date"])
            ast_c = discover_col(df_raw, ["asset", "symbol"])
            amt_c = discover_col(df_raw, ["amount", "quantity", "balance"])
            acc_c = discover_col(df_raw, ["account", "address"])

            # Valuations Discovery
            v_usd_c = discover_col(df_raw, ["valeur$", "valueusd", "totalusd", "usdvalue"])
            p_rec_c = discover_col(df_raw, ["usdprixassetreçu", "usdpriceofassetreceived", "usdprixreçu"])
            p_sent_c = discover_col(df_raw, ["usdprixassetenvoyé", "usdpriceofassetsent", "usdprixenvoyé"])
            p_fee_c = discover_col(df_raw, ["usdprixdeféeasset", "usdprixdefeeasset", "usdpriceoffeeasset", "usdprixfee"])

            for _, r in df_raw.iterrows():
                dt_val = r.get(d_c, f"{year}-12-31")
                rows.append({
                    "Date": pd.to_datetime(dt_val, utc=True),
                    "Chain": "Portfolio", "Tx_Hash": f"INIT_{fn}_{_}",
                    "Type": "Position", "Account": sl.standardize_address_string(r.get(acc_c, src)),
                    "Asset": str(r.get(ast_c, "UNKNOWN")), "Amount": float(r.get(amt_c, 0)),
                    "Valeur $": float(r.get(v_usd_c, 0.0)) if v_usd_c else 0.0,
                    "USD prix asset reçu": float(r.get(p_rec_c, 0.0)) if p_rec_c else 0.0,
                    "USD prix asset envoyé": float(r.get(p_sent_c, 0.0)) if p_sent_c else 0.0,
                    "USD prix de fée asset": float(r.get(p_fee_c, 0.0)) if p_fee_c else 0.0,
                    "Source_Way": "Voie 3", "Audit_Status": "Valide",
                    "Source_File": fn
                })
            continue

        # Cas général : Transactions
        d_c = discover_col(df_raw, ["date", "timestamp", "time", "blocktimestamp"])
        if not d_c: continue

        acc_c = discover_col(df_raw, ["account", "compte"])
        tx_c = discover_col(df_raw, ["txhash", "hash", "transaction"])
        ast_c = discover_col(df_raw, ["asset", "tokensymbol", "symbol", "token"])
        amt_c = discover_col(df_raw, ["amount", "valueeth", "value", "quantity", "montant"])

        # New USD Column Discovery
        v_usd_c = discover_col(df_raw, ["valeur$", "valueusd", "totalusd", "usdvalue"])
        p_rec_c = discover_col(df_raw, ["usdprixassetreçu", "usdpriceofassetreceived", "usdprixreçu"])
        p_sent_c = discover_col(df_raw, ["usdprixassetenvoyé", "usdpriceofassetsent", "usdprixenvoyé"])
        p_fee_c = discover_col(df_raw, ["usdprixdeféeasset", "usdprixdefeeasset", "usdpriceoffeeasset", "usdprixfee"])

        # Fee Asset/Amount Discovery
        f_ast_c = discover_col(df_raw, ["feeasset", "tokenfrais", "devisefrais"])
        f_amt_c = discover_col(df_raw, ["feeamount", "montantfrais", "valeurfrais", "fees"])

        from_c = discover_col(df_raw, ["from", "expediteur"])
        to_c = discover_col(df_raw, ["to", "destinataire"])
        cp_c = discover_col(df_raw, ["counterparty", "contrepartie"])
        net_c = discover_col(df_raw, ["chain", "network", "reseau"])
        type_c = discover_col(df_raw, ["type", "method"])

        for _, r in df_raw.iterrows():
            try:
                dt = pd.to_datetime(r.get(d_c), utc=True)
                if pd.isna(dt): continue

                amt_val = r.get(amt_c, 0)
                amt = float(amt_val) if pd.notna(amt_val) else 0.0

                acc = sl.standardize_address_string(r.get(acc_c, src))
                tx = str(r.get(tx_c, f"TX_{fn}_{_}"))
                ast = str(r.get(ast_c, "UNKNOWN"))

                rows.append({
                    "Date": dt, "Chain": str(r.get(net_c, "Unknown")), "Tx_Hash": tx,
                    "Account": acc, "Asset": ast, "Amount": amt,
                    "Valeur $": float(r.get(v_usd_c, 0.0)) if v_usd_c else 0.0,
                    "USD prix asset reçu": float(r.get(p_rec_c, 0.0)) if p_rec_c else 0.0,
                    "USD prix asset envoyé": float(r.get(p_sent_c, 0.0)) if p_sent_c else 0.0,
                    "USD prix de fée asset": float(r.get(p_fee_c, 0.0)) if p_fee_c else 0.0,
                    "Fee_Asset": str(r.get(f_ast_c, "")) if f_ast_c else "",
                    "Fee_Amount": float(r.get(f_amt_c, 0.0)) if f_amt_c else 0.0,
                    "From": sl.standardize_address_string(r.get(from_c, "")),
                    "To": sl.standardize_address_string(r.get(to_c, "")),
                    "Counterparty": str(r.get(cp_c, "")),
                    "Type": str(r.get(type_c, "Transfer")),
                    "Source_Way": "Blockchain", "Audit_Status": "A vérifier",
                    "Source_File": fn
                })
            except: continue

    # 2. Source Manuelle (Flux Fiat)
    f_fiat = sl.get_file_path(year, 'fiat')
    if f_fiat and os.path.exists(f_fiat):
        df_fiat = sl.pd_read_csv_safe(f_fiat)
        for _, r in df_fiat.iterrows():
            # Robust mapping for fiat rows from app0 (Montant EUR)
            amt_val = r.get("Montant EUR", r.get("Amount", 0))
            ast_val = str(r.get("Asset", "EUR")).upper().strip()
            if ast_val in ["", "NAN", "NONE"]: ast_val = "EUR"

            rows.append({
                "Date": pd.to_datetime(r.get("Date"), utc=True),
                "Chain": "Fiat", "Tx_Hash": str(r.get("Tx_Hash", "MANUAL_FIAT")),
                "Account": str(r.get("Account", "banq fiat")),
                "Asset": ast_val, "Amount": float(amt_val),
                "Counterparty": str(r.get("Counterparty", "Banque")),
                "Type": "Fiat Move", "Source_Way": "Manuel", "Audit_Status": "Valide",
                "Category": str(r.get("Type", "Achat")) # Propagate manual category
            })

    # 3. Source Manuelle (Positions Initiales / Snapshot)
    f_pos = sl.get_file_path(year, 'positions')
    if f_pos and os.path.exists(f_pos):
        df_pos = sl.pd_read_csv_safe(f_pos)

        # Discoveries for manual entries too
        v_usd_c = discover_col(df_pos, ["valeur$", "valueusd", "totalusd"])
        p_rec_c = discover_col(df_pos, ["usdprixassetreçu", "usdpriceofassetreceived"])

        for _, r in df_pos.iterrows():
            rows.append({
                "Date": pd.to_datetime(r.get("Date", f"{year}-01-01"), utc=True),
                "Chain": "Manual", "Tx_Hash": str(r.get("Tx_Hash", f"MANUAL_POS_{_}")),
                "Account": str(r.get("Account", "Portefeuille")),
                "Asset": str(r.get("Asset", "UNKNOWN")), "Amount": float(r.get("Amount", r.get("Quantité", 0))),
                "Valeur $": float(r.get(v_usd_c, 0.0)) if v_usd_c else 0.0,
                "USD prix asset reçu": float(r.get(p_rec_c, 0.0)) if p_rec_c else 0.0,
                "Type": "Position Manuelle", "Source_Way": "Manuel", "Audit_Status": "Valide",
                "Category": "Position Manuelle"
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        # Dédoublonnage global des sources RAW pour éviter l'accumulation des récoltes successives
        # On arrondit l'Amount pour éviter les micro-différences de flottants lors des imports
        df["_amt_round"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0).round(8)
        # Une transaction est identique si (Hash, Asset, Account, Amount, Date) concordent.
        # Comme sl.get_all_raw_files renvoie les fichiers triés par nom descendant,
        # keep="first" privilégie les fichiers avec les timestamps les plus récents.
        df = df.drop_duplicates(subset=["Tx_Hash", "Asset", "Account", "_amt_round", "Date"], keep="first")
        df = df.drop(columns=["_amt_round"])

    return ensure_columns(df)

def run_fidelity_engine(raw_df, existing_df):
    """Fusionne le RAW et l'existant en préservant les qualifications manuelles."""
    if existing_df.empty:
        return raw_df

    def generate_uid(row):
        # UID composite plus granulaire pour éviter les collisions (Hash, Asset, Account, Amount arrondi, Date brute)
        dt = str(row.get("Date", "NODATE"))
        h = str(row.get("Tx_Hash", "NOHASH"))
        ast = str(row.get("Asset", "NOAST"))
        acc = str(row.get("Account", "NOACC"))
        amt = f"{float(row.get('Amount', 0)):.8f}"
        return f"{h}_{ast}_{acc}_{amt}_{dt}"

    # On identifie les lignes
    existing_df["_uid"] = existing_df.apply(generate_uid, axis=1)
    raw_df["_uid"] = raw_df.apply(generate_uid, axis=1)

    # Les colonnes à préserver (celles que l'utilisateur modifie ou enrichies par récolte)
    preservable = [
        "Audit_Status", "Category", "From_Label", "To_Label", "Counterparty",
        "VGP (EUR)", "Linked_ID", "Link_Status", "Imposable",
        "Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset",
        "Fee_Asset", "Fee_Amount"
    ]

    # Dédoublonnage de l'existant sur l'UID pour éviter ValueError orient='index'
    # On garde le premier (le plus qualifié normalement)
    clean_existing = existing_df.drop_duplicates(subset=["_uid"], keep="first")

    # Map de l'existant
    qualif_map = clean_existing.set_index("_uid")[preservable].to_dict('index')

    def apply_fidelity(row):
        uid = row["_uid"]
        if uid in qualif_map:
            for col in preservable:
                val = qualif_map[uid].get(col)
                # Logic logic: Prioritize existing if not "empty"
                # For strings: not empty. For numbers: not 0.0 (unless it's VGP which might be 0)
                is_empty = False
                if pd.isna(val): is_empty = True
                elif isinstance(val, str) and val.strip() == "": is_empty = True
                elif isinstance(val, (int, float)) and val == 0.0 and col != "VGP (EUR)": is_empty = True

                if not is_empty:
                    row[col] = val
        return row

    res = raw_df.apply(apply_fidelity, axis=1)
    res = res.drop(columns=["_uid"])
    return ensure_columns(res)

def apply_auto_labels(df):
    """Applique les labels automatiques basés sur les registres."""
    spams = sl.load_spam_list()
    valides = sl.load_valid_assets()
    owners = sl.load_owner_accounts()
    pos_reg = sl.load_position_registry()

    owner_addrs = set(owners.keys())
    pos_addrs = set(pos_reg.keys())

    def label_row(r):
        # From/To Labels
        f_raw = sl.resolve_raw_addr(r["From"]).lower()
        t_raw = sl.resolve_raw_addr(r["To"]).lower()
        f_l = sl.resolve_raw_addr(r["From"])
        t_l = sl.resolve_raw_addr(r["To"])
        r["From_Label"] = f_l if f_l != r["From"] else r["From_Label"]
        r["To_Label"] = t_l if t_l != r["To"] else r["To_Label"]

        # Auto-Status
        asset_norm = str(r["Asset"]).lower().strip()
        asset_upper = str(r["Asset"]).upper().strip()
        cp_norm = sl.resolve_raw_addr(r["Counterparty"]).lower()

        is_spam = False
        if asset_norm in spams or cp_norm in spams:
            r["Audit_Status"] = "Spam"
            is_spam = True
        elif r["Asset"] in valides:
            if r["Audit_Status"] == "A vérifier":
                r["Audit_Status"] = "Valide"

        # Transfert Interne Automation (If not Spam)
        if not is_spam and r["Audit_Status"].lower() != "spam":
            # 1. Between Owners + Valid Asset
            if f_raw in owner_addrs and t_raw in owner_addrs:
                if asset_upper in valides:
                    r["Category"] = "Transfert Interne"

            # 2. Between Owner and Protocol Position + Registry Asset Match
            # Check From=Owner, To=Position
            elif f_raw in owner_addrs and t_raw in pos_addrs:
                if asset_upper in pos_reg[t_raw].get("assets", []):
                    r["Category"] = "Transfert Interne"

            # Check From=Position, To=Owner
            elif f_raw in pos_addrs and t_raw in owner_addrs:
                if asset_upper in pos_reg[f_raw].get("assets", []):
                    r["Category"] = "Transfert Interne"

        return r

    return df.apply(label_row, axis=1)

def main():
    st.set_page_config(page_title="Qualif V4", layout="wide")
    sl.show_status()

    year = st.sidebar.selectbox("Année", [2025, 2024], key="_hub_app2_year")

    # Persistent toggle for Spams
    g_conf = sl.load_global_config()
    show_spams_default = g_conf.get("app2_show_spams", False)
    show_spams = st.sidebar.toggle("Afficher les Spams", value=show_spams_default, key="app2_show_spams_toggle")

    if show_spams != show_spams_default:
        g_conf["app2_show_spams"] = show_spams
        sl.save_global_config(g_conf)

    # Chemin Journal (Gateway Clean Architecture)
    j_path = sl.get_file_path(year, 'qualified_clean')
    j_full_path = sl.get_file_path(year, 'qualified_full')

    # Chargement
    if "df_qualif" not in st.session_state:
        # Tentative de récupération depuis l'ancien nom si le nouveau n'existe pas
        if not os.path.exists(j_full_path):
            old_path = f"sanctuarisation/{year}/qualif_journal_{year}_FULL.csv"
            if os.path.exists(old_path):
                existing = sl.pd_read_csv_safe(old_path)
            else:
                old_path_2 = f"sanctuarisation/{year}/qualif_journal_{year}.csv"
                existing = sl.pd_read_csv_safe(old_path_2) if os.path.exists(old_path_2) else pd.DataFrame()
        else:
            existing = sl.pd_read_csv_safe(j_full_path)

        # Robustesse : s'assurer que l'existant a bien toutes les colonnes cibles avant le Fidelity Engine
        # On force ensure_columns même si vide pour avoir le schéma complet (prévient not in index)
        existing = ensure_columns(existing)

        raw = merge_raw_data(year)
        final = run_fidelity_engine(raw, existing)
        st.session_state.df_qualif = apply_auto_labels(final)

    df = st.session_state.df_qualif

    # --- SIDEBAR REGISTRIES ---
    with st.sidebar:
        if st.button("🔄 Rafraîchir & Ré-appliquer Labels"):
            del st.session_state["df_qualif"]
            st.rerun()

        st.subheader("Registres")

        with st.expander("🛑 Blacklist Spams"):
            spams = sl.load_spam_list()
            for s in sorted(list(spams)):
                sc = st.columns([4, 1])
                sc[0].text(s)
                if sc[1].button("🗑️", key=f"del_spam_{s}"):
                    spams.remove(s)
                    sl.save_spam_list(spams)
                    st.rerun()
            new_spam = st.text_input("Ajouter Spam (Asset/CP)", key="new_spam")
            if st.button("Ajouter", key="btn_spam"):
                if new_spam:
                    spams.add(new_spam.lower())
                    sl.save_spam_list(spams)
                    st.rerun()

        with st.expander("✅ Whitelist Assets"):
            valides = sl.load_valid_assets()
            for v in sorted(list(valides)):
                vc = st.columns([4, 1])
                vc[0].text(v)
                if vc[1].button("🗑️", key=f"del_val_{v}"):
                    valides.remove(v)
                    sl.save_valid_assets(valides)
                    st.rerun()
            new_v = st.text_input("Asset Valide", key="new_val")
            if st.button("Valider", key="btn_val"):
                if new_v:
                    valides.add(new_v.upper())
                    sl.save_valid_assets(valides)
                    st.rerun()

        with st.expander("🏦 Comptes Propriétaires"):
            owners = sl.load_owner_accounts()
            for addr, label in list(owners.items()):
                cols = st.columns([3, 1])
                cols[0].text(f"{label}\n{addr[:10]}...")
                if cols[1].button("🗑️", key=f"del_own_{addr}"):
                    del owners[addr]
                    sl.save_owner_accounts(owners)
                    st.rerun()
            n_addr = st.text_input("Adresse", key="n_own_addr")
            n_lab = st.text_input("Label", key="n_own_lab")
            if st.button("Ajouter Propriétaire"):
                if n_addr and n_lab:
                    owners[n_addr.lower()] = n_lab
                    sl.save_owner_accounts(owners)
                    st.rerun()

        with st.expander("📈 Positions Protocoles"):
            pos_reg = sl.load_position_registry()
            for addr, data in list(pos_reg.items()):
                cols = st.columns([3, 1])
                assets_str = ", ".join(data.get("assets", []))
                cols[0].text(f"{data['label']} ({assets_str})\n{addr[:10]}...")
                if cols[1].button("🗑️", key=f"del_pos_{addr}"):
                    del pos_reg[addr]
                    sl.save_position_labels(pos_reg)
                    st.rerun()
            n_p_addr = st.text_input("Adresse Position", key="n_pos_addr")
            n_p_lab = st.text_input("Label Position", key="n_pos_lab")
            n_p_assets = st.text_input("Assets (ex: ETH, USDC)", key="n_pos_assets", help="Saisie obligatoire pour confirmer la position.")
            if st.button("Ajouter Position"):
                if n_p_addr and n_p_lab and n_p_assets:
                    assets_list = [a.strip().upper() for a in n_p_assets.split(",") if a.strip()]
                    if assets_list:
                        pos_reg[n_p_addr.lower()] = {"label": n_p_lab, "assets": assets_list}
                        sl.save_position_labels(pos_reg)
                        st.rerun()
                    else:
                        st.error("Veuillez saisir au moins un asset valide.")
                elif not n_p_assets:
                    st.error("L'asset est obligatoire pour confirmer une position.")

        with st.expander("🌐 Circuits Externes"):
            ext = sl.load_external_circuits()
            for addr, label in list(ext.get("labels", {}).items()):
                cols = st.columns([3, 1])
                cols[0].text(f"{label}\n{addr[:10]}...")
                if cols[1].button("🗑️", key=f"del_ext_{addr}"):
                    del ext["labels"][addr]
                    sl.save_external_circuits(ext)
                    st.rerun()
            n_e_addr = st.text_input("Adresse Externe", key="n_ext_addr")
            n_e_lab = st.text_input("Label Externe", key="n_ext_lab")
            if st.button("Ajouter Externe"):
                if n_e_addr and n_e_lab:
                    ext["labels"][n_e_addr.lower()] = n_e_lab
                    sl.save_external_circuits(ext)
                    st.rerun()

            st.divider()
            st.write("Découverte de circuits :")
            if st.button("Lancer Discovery"):
                disc = sl.get_external_circuits_discovery(df)
                if disc:
                    st.table(pd.DataFrame(disc))
                else:
                    st.info("Aucun nouveau circuit détecté.")

    # --- MAIN UI ---
    tab1, tab2, tab3 = st.tabs(["📝 Qualification Journal", "🔍 Audit & Recovery", "📊 Statistiques"])

    with tab1:
        st.title(f"Qualification {year}")

        # Filtres
        with st.expander("🔍 Filtres avancés", expanded=True):
            f_cols1 = st.columns(3)
            f_status = f_cols1[0].multiselect("Statut", ["A vérifier", "Valide", "Spam", "Ignoré"], default=["A vérifier", "Valide"])
            f_acc = f_cols1[1].multiselect("Compte", sl.get_owner_display_list())
            f_asset = f_cols1[2].multiselect("Asset", sorted(list(df["Asset"].unique())))

            f_cols2 = st.columns(3)
            f_cp = f_cols2[0].multiselect("Contrepartie", sorted(list(df["Counterparty"].dropna().unique())))
            f_imp = f_cols2[1].selectbox("Imposable", ["Tous", "Oui", "Non"])

        # DATA VIEW GENERATION
        # We start from the full state to ensure index consistency
        full_df = st.session_state.df_qualif

        # APPLY SPAM VISIBILITY (Uses hardened sl.apply_spam_filter with reset_idx=False)
        if not show_spams:
            view_df = sl.apply_spam_filter(full_df, drop=True, reset_idx=False)
        else:
            view_df = full_df.copy()

        if f_status: view_df = view_df[view_df["Audit_Status"].isin(f_status)]
        if f_acc:
            acc_set = {sl.resolve_raw_addr(x) for x in f_acc}
            view_df = view_df[view_df["Account"].apply(sl.resolve_raw_addr).isin(acc_set)]
        if f_asset: view_df = view_df[view_df["Asset"].isin(f_asset)]
        if f_cp: view_df = view_df[view_df["Counterparty"].isin(f_cp)]
        if f_imp == "Oui": view_df = view_df[view_df["Imposable"].apply(sl.is_imposable_robust)]
        elif f_imp == "Non": view_df = view_df[~view_df["Imposable"].apply(sl.is_imposable_robust)]

        # Editor Configuration
        if "has_unsaved_changes" not in st.session_state:
            st.session_state.has_unsaved_changes = False

        # Add modification checkbox
        if "Mod." not in view_df.columns:
            view_df.insert(0, "Mod.", False)

        edited_df = st.data_editor(
            view_df,
            column_config={
                "Mod.": st.column_config.CheckboxColumn("Mod.", default=False),
                "Audit_Status": st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam", "Ignoré"]),
                "Category": st.column_config.SelectboxColumn("Catégorie", options=["", "Revenu", "Dépense", "Transfert", "Transfert Interne", "Swap", "Achat", "Vente"]),
                "Imposable": st.column_config.CheckboxColumn("Imposable"),
                "Valeur $": st.column_config.NumberColumn(format="$ %.2f"),
                "USD prix asset reçu": st.column_config.NumberColumn(format="$ %.4f"),
                "USD prix asset envoyé": st.column_config.NumberColumn(format="$ %.4f"),
                "USD prix de fée asset": st.column_config.NumberColumn(format="$ %.4f"),
            },
            disabled=[
                "Date", "Chain", "Tx_Hash", "Account", "Asset", "Amount", "Source_Way",
                "Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset",
                "Fee_Asset", "Fee_Amount"
            ],
            num_rows="fixed",
            width='stretch',
            key="qualif_editor"
        )

        # DETECTION AND INSTANT SYNC
        # If the user edited something, we update the global session state immediately
        # This ensures that actions like toggling spams or adding to blacklist don't revert edits.
        if not edited_df.equals(view_df):
            # Prioritize standard column sync but handle the 'Mod.' flag carefully
            # We don't want to reset 'Mod.' to False in the main state if it's currently selected
            st.session_state.df_qualif.update(edited_df)
            st.session_state.has_unsaved_changes = True

        save_label = "🚨 Sauvegarder Journal (Modifications en cours)" if st.session_state.has_unsaved_changes else "🐾 Sauvegarder Journal"
        btn_type = "primary" if st.session_state.has_unsaved_changes else "secondary"

        # ACTION BAR FOR SELECTED ROWS
        selected_rows = edited_df[edited_df["Mod."] == True]
        if not selected_rows.empty:
            st.markdown("---")
            st.subheader(f"🛠️ Gestion des {len(selected_rows)} lignes sélectionnées")
            act_cols = st.columns(3)

            with act_cols[0]:
                if st.button("⏪ Restaurer vers RAW", help="Retire les qualifications de ces lignes pour les remettre à l'état 'A vérifier'.", width='stretch'):
                    for idx in selected_rows.index:
                        st.session_state.df_qualif.loc[idx, "Audit_Status"] = "A vérifier"
                        st.session_state.df_qualif.loc[idx, "Category"] = ""
                        st.session_state.df_qualif.loc[idx, "Imposable"] = False
                    st.session_state.has_unsaved_changes = True
                    st.rerun()

            with act_cols[1]:
                with st.popover("🔥 Éliminer (RAW Racine)", width='stretch'):
                    st.error("Cette action supprimera la transaction des fichiers RAW de travail (racine de l'année).")
                    st.info("💡 Le dossier /sanctuary/ reste intact et permettra le rétablissement ultérieur via l'onglet Audit.")
                    if st.button("Confirmer l'élimination du pool actif"):
                        count_del = 0
                        for _, s_row in selected_rows.iterrows():
                            # Robust Source_File detection and cleaning
                            src_f = s_row.get("Source_File")
                            if pd.isna(src_f) or not isinstance(src_f, str) or src_f.strip() == "" or src_f.lower() == "nan":
                                continue

                            # PROTECTED: We ONLY target the root year directory, NEVER the sanctuary
                            f_path = os.path.join(EXPORT_BASE_DIR, str(year), src_f.strip())

                            if os.path.exists(f_path):
                                if sl.remove_row_from_csv(f_path, s_row):
                                    count_del += 1

                        st.session_state.df_qualif = st.session_state.df_qualif.drop(index=selected_rows.index)
                        st.session_state.has_unsaved_changes = True
                        st.success(f"{len(selected_rows)} lignes retirées du pool actif (Modifié dans {count_del} fichiers RAW).")
                        time.sleep(1); st.rerun()

        # CSS pour colorer le bouton en rouge si modifications
        if st.session_state.has_unsaved_changes:
            st.markdown("""
                <style>
                div.stButton > button:first-child {
                    background-color: #ff4b4b !important;
                    color: white !important;
                }
                </style>""", unsafe_allow_html=True)

        sc1, sc2 = st.columns([1, 1])

        with sc1:
            if st.button(save_label, type=btn_type, width='stretch'):
                # Prioritize edited values back into main state
                st.session_state.df_qualif.update(edited_df)
                final_save = ensure_columns(st.session_state.df_qualif)

                # Sauvegarde Physique
                os.makedirs(os.path.dirname(j_full_path), exist_ok=True)

                # 1. FULL for Audit (using utf-8-sig for compatibility)
                final_save.to_csv(j_full_path, index=False, encoding="utf-8-sig")

                # 2. CLEAN (No Spams, strictly real positions)
                # EXCLUSIVITY RULE: No Spam allowed in CLEAN journal.
                # We apply the filter with drop=True to strictly exclude qualified or blacklisted spams.
                clean_save = sl.apply_spam_filter(final_save, drop=True)
                clean_save.to_csv(j_path, index=False, encoding="utf-8-sig")

                st.session_state.has_unsaved_changes = False
                st.toast("✅ Sanctuarisation réussie !", icon="🟢")
                st.success("Journal synchronisé avec Sanctuarisation (Fichiers FULL et CLEAN à jour).")
                st.rerun()

        with sc2:
            st.download_button(
                label="📥 Exporter la vue actuelle (CSV)",
                data=edited_df.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"export_qualif_{year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                width='stretch'
            )

        # --- INJECTION TOOLS ---
        st.divider()
        st.subheader("Outils d'injection")
        i_cols = st.columns(2)

        with i_cols[0]:
            st.info("Injecter vers le flux fiat (banq fiat).")
            with st.popover("Préparer Injection Fiat"):
                inj_type = st.radio("Type d'injection", ["Vente (Crypto -> Banque)", "Achat (Banque -> Crypto)"], horizontal=True)

                # Filter for selection
                if "Vente" in inj_type:
                    valid_idx = view_df[view_df["Amount"] < 0].index
                    prompt = "Choisir jambe de sortie (Amount < 0)"
                else:
                    valid_idx = view_df[view_df["Amount"] > 0].index
                    prompt = "Choisir jambe d'entrée (Amount > 0)"

                sel_row_idx = st.selectbox(prompt, valid_idx,
                                       format_func=lambda x: f"{view_df.loc[x, 'Date']} - {view_df.loc[x, 'Amount']} {view_df.loc[x, 'Asset']}")

                if st.button("Confirmer Injection Fiat"):
                    row = view_df.loc[sel_row_idx]
                    op_type = "Vente" if "Vente" in inj_type else "Achat"
                    data = [{
                        "Date": row["Date"],
                        "Account": row["Account"],
                        "Counterparty": "banq fiat",
                        "Amount": row["Amount"],
                        "Asset": row["Asset"],
                        "Tx Hash": row["Tx_Hash"],
                        "Imposable": (op_type == "Vente")
                    }]
                    sl.inject_to_app0(data, "Fiat", year, op_type=op_type)
                    st.success(f"Injecté comme '{op_type}' vers Flux Fiat !")

        with i_cols[1]:
            st.info("Injecter vers le registre des Swaps & Internes.")
            with st.popover("Préparer Injection Swap"):
                sel_rows = st.multiselect("Choisir les jambes du Swap (In/Out)",
                                          view_df.index,
                                          format_func=lambda x: f"{view_df.loc[x, 'Date']} - {view_df.loc[x, 'Amount']} {view_df.loc[x, 'Asset']}")
                if st.button("Confirmer Injection Swap"):
                    data = []
                    for idx in sel_rows:
                        row = view_df.loc[idx]
                        data.append({
                            "Date": row["Date"],
                            "Account": row["Account"],
                            "Counterparty": row["Counterparty"],
                            "Amount": row["Amount"],
                            "Asset": row["Asset"],
                            "Tx Hash": row["Tx_Hash"],
                            "Imposable": True
                        })
                    sl.inject_to_app0(data, "Swaps", year)
                    st.success(f"{len(data)} jambes injectées !")

    with tab2:
        st.header("Audit & Recovery")

        # 1. SCAN GLOBAL (All RAW files including Sanctuary)
        raw_global = merge_raw_data(year)

        # 2. IDENTIFY MISSING
        # We use a robust identification (Hash, Asset, Account, Amount)
        def get_uid_set(df_target):
             if df_target.empty: return set()
             return set(df_target.apply(lambda r: f"{r['Tx_Hash']}_{r['Asset']}_{r['Account']}_{float(r['Amount']):.6f}", axis=1))

        journal_uids = get_uid_set(df)
        raw_global["_uid"] = raw_global.apply(lambda r: f"{r['Tx_Hash']}_{r['Asset']}_{r['Account']}_{float(r['Amount']):.6f}", axis=1)

        missing = raw_global[~raw_global["_uid"].isin(journal_uids)].copy()

        if not missing.empty:
            st.error(f"⚠️ {len(missing)} transactions présentes dans les archives (RAW/Sanctuary) sont manquantes dans votre journal !")

            # Distinguish between Root and Sanctuary
            missing["Origin"] = missing["Source_File"].apply(lambda f: "Sanctuary (Archive)" if "sanctuary" in str(sl.get_all_raw_files(year)) else "RAW Racine")

            st.dataframe(missing.drop(columns=["_uid"]), use_container_width=True)

            c_rec1, c_rec2 = st.columns(2)
            if c_rec1.button("♻️ Récupérer TOUT le manquant", type="primary", width='stretch'):
                st.session_state.df_qualif = pd.concat([df, missing.drop(columns=["_uid", "Origin"])]).sort_values("Date", ascending=False)
                st.session_state.has_unsaved_changes = True
                st.success("Toutes les lignes ont été réintégrées. N'oubliez pas de sauvegarder.")
                st.rerun()

            if c_rec2.button("🔙 Récupérer uniquement le Sanctuary", width='stretch'):
                from_sanctuary = missing[missing["Origin"] == "Sanctuary (Archive)"]
                if not from_sanctuary.empty:
                    st.session_state.df_qualif = pd.concat([df, from_sanctuary.drop(columns=["_uid", "Origin"])]).sort_values("Date", ascending=False)
                    st.session_state.has_unsaved_changes = True
                    st.success("Lignes du Sanctuary réintégrées.")
                    st.rerun()
                else:
                    st.info("Aucune ligne spécifique au Sanctuary à récupérer.")
        else:
            st.success("✅ Journal parfaitement en phase avec le Sanctuary et les sources RAW.")

    with tab3:
        stats_df = st.session_state.df_qualif
        c1, c2, c3 = st.columns(3)
        c1.metric("Volume Qualifié", f"{len(stats_df[stats_df['Audit_Status']=='Valide'])} tx")
        c2.metric("Spams Identifiés", f"{len(stats_df[stats_df['Audit_Status']=='Spam'])} tx")
        c3.metric("À vérifier", f"{len(stats_df[stats_df['Audit_Status']=='A vérifier'])} tx")

if __name__ == "__main__":
    main()
