import streamlit as st
import pandas as pd
import shared_logic as sl
import os
import json
from datetime import datetime

# --- CONFIGURATION & SCHEMA ---
QUALIFIED_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account", "From", "To",
    "From_Label", "To_Label", "Counterparty", "Asset", "Amount",
    "Fee_Asset", "Fee_Amount", "Source_Way", "Audit_Status", "Fee_Audit_Alert",
    "Source_Exchange_Rate", "VGP (EUR)", "Linked_ID", "Link_Status", "Category"
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
            for _, r in df_raw.iterrows():
                dt_val = r.get(d_c, f"{year}-12-31")
                rows.append({
                    "Date": pd.to_datetime(dt_val, utc=True),
                    "Chain": "Portfolio", "Tx_Hash": f"INIT_{fn}_{_}",
                    "Type": "Position", "Account": sl.standardize_address_string(r.get(acc_c, src)),
                    "Asset": str(r.get(ast_c, "UNKNOWN")), "Amount": float(r.get(amt_c, 0)),
                    "Source_Way": "Voie 3", "Audit_Status": "Valide"
                })
            continue

        # Cas général : Transactions
        d_c = discover_col(df_raw, ["date", "timestamp", "time", "blocktimestamp"])
        if not d_c: continue

        acc_c = discover_col(df_raw, ["account", "compte"])
        tx_c = discover_col(df_raw, ["txhash", "hash", "transaction"])
        ast_c = discover_col(df_raw, ["asset", "tokensymbol", "symbol", "token"])
        amt_c = discover_col(df_raw, ["amount", "valueeth", "value", "quantity", "montant"])
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
                    "From": sl.standardize_address_string(r.get(from_c, "")),
                    "To": sl.standardize_address_string(r.get(to_c, "")),
                    "Counterparty": str(r.get(cp_c, "")),
                    "Type": str(r.get(type_c, "Transfer")),
                    "Source_Way": "Blockchain", "Audit_Status": "A vérifier"
                })
            except: continue

    # 2. Source Manuelle (Flux Fiat)
    f_fiat = f"sanctuarisation/{year}/manual_fiat_{year}.csv"
    if os.path.exists(f_fiat):
        df_fiat = sl.pd_read_csv_safe(f_fiat)
        for _, r in df_fiat.iterrows():
            rows.append({
                "Date": pd.to_datetime(r.get("Date"), utc=True),
                "Chain": "Fiat", "Tx_Hash": str(r.get("Tx_Hash", "MANUAL")),
                "Account": str(r.get("Account", "banq fiat")),
                "Asset": str(r.get("Asset", "EUR")), "Amount": float(r.get("Amount", 0)),
                "Counterparty": str(r.get("Counterparty", "Banque")),
                "Type": "Fiat Move", "Source_Way": "Manuel", "Audit_Status": "Valide"
            })

    df = pd.DataFrame(rows)
    return ensure_columns(df)

def run_fidelity_engine(raw_df, existing_df):
    """Fusionne le RAW et l'existant en préservant les qualifications manuelles."""
    if existing_df.empty:
        return raw_df

    # On identifie les lignes par (Tx_Hash, Asset, Account)
    existing_df["_uid"] = existing_df["Tx_Hash"].astype(str) + "_" + existing_df["Asset"].astype(str) + "_" + existing_df["Account"].astype(str)
    raw_df["_uid"] = raw_df["Tx_Hash"].astype(str) + "_" + raw_df["Asset"].astype(str) + "_" + raw_df["Account"].astype(str)

    # Les colonnes à préserver (celles que l'utilisateur modifie)
    preservable = ["Audit_Status", "Category", "From_Label", "To_Label", "Counterparty", "VGP (EUR)", "Linked_ID", "Link_Status"]

    # Map de l'existant
    qualif_map = existing_df.set_index("_uid")[preservable].to_dict('index')

    def apply_fidelity(row):
        uid = row["_uid"]
        if uid in qualif_map:
            for col in preservable:
                # Priorité à l'existant si non vide
                val = qualif_map[uid].get(col)
                if pd.notna(val) and str(val).strip() != "":
                    row[col] = val
        return row

    res = raw_df.apply(apply_fidelity, axis=1)
    res = res.drop(columns=["_uid"])
    return ensure_columns(res)

def apply_auto_labels(df):
    """Applique les labels automatiques basés sur les registres."""
    spams = sl.load_spam_list()
    valides = sl.load_valid_assets()

    def label_row(r):
        # From/To Labels
        f_l = sl.resolve_raw_addr(r["From"])
        t_l = sl.resolve_raw_addr(r["To"])
        r["From_Label"] = f_l if f_l != r["From"] else r["From_Label"]
        r["To_Label"] = t_l if t_l != r["To"] else r["To_Label"]

        # Auto-Status
        if r["Asset"] in spams or r["Counterparty"] in spams:
            r["Audit_Status"] = "Spam"
        elif r["Asset"] in valides:
            if r["Audit_Status"] == "A vérifier":
                r["Audit_Status"] = "Valide"

        return r

    return df.apply(label_row, axis=1)

def main():
    st.set_page_config(page_title="Qualif V4", layout="wide")
    sl.show_status()

    year = st.sidebar.selectbox("Année", [2025, 2024], key="_hub_app2_year")

    # Chemin Journal
    j_path = f"sanctuarisation/{year}/qualif_journal_{year}.csv"
    j_full_path = f"sanctuarisation/{year}/qualif_journal_{year}_FULL.csv"

    # Chargement
    if "df_qualif" not in st.session_state:
        existing = sl.pd_read_csv_safe(j_full_path)
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
            new_spam = st.text_input("Ajouter Spam (Asset/CP)", key="new_spam")
            if st.button("Ajouter", key="btn_spam"):
                if new_spam:
                    spams.add(new_spam.lower())
                    sl.save_spam_list(spams)
                    st.rerun()
            st.write(sorted(list(spams)))

        with st.expander("✅ Whitelist Assets"):
            valides = sl.load_valid_assets()
            new_v = st.text_input("Asset Valide", key="new_val")
            if st.button("Valider", key="btn_val"):
                if new_v:
                    valides.add(new_v.upper())
                    sl.save_valid_assets(valides)
                    st.rerun()
            st.write(sorted(list(valides)))

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
            if st.button("Ajouter Propri\303\251taire"):
                if n_addr and n_lab:
                    owners[n_addr.lower()] = n_lab
                    sl.save_owner_accounts(owners)
                    st.rerun()

        with st.expander("📈 Positions Protocoles"):
            pos = sl.load_position_labels()
            for addr, label in list(pos.items()):
                cols = st.columns([3, 1])
                cols[0].text(f"{label}\n{addr[:10]}...")
                if cols[1].button("🗑️", key=f"del_pos_{addr}"):
                    del pos[addr]
                    sl.save_position_labels(pos)
                    st.rerun()
            n_p_addr = st.text_input("Adresse Position", key="n_pos_addr")
            n_p_lab = st.text_input("Label Position", key="n_pos_lab")
            if st.button("Ajouter Position"):
                if n_p_addr and n_p_lab:
                    pos[n_p_addr.lower()] = n_p_lab
                    sl.save_position_labels(pos)
                    st.rerun()

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
                    st.info("Aucun nouveau circuit d\303\251tect\303\251.")

    # --- MAIN UI ---
    tab1, tab2, tab3 = st.tabs(["📝 Qualification Journal", "🔍 Audit & Recovery", "📊 Statistiques"])

    with tab1:
        st.title(f"Qualification {year}")

        # Filtres
        f_cols = st.columns(4)
        f_status = f_cols[0].multiselect("Statut", ["A vérifier", "Valide", "Spam", "Ignoré"], default=["A vérifier", "Valide"])
        f_acc = f_cols[1].multiselect("Compte", sl.get_owner_display_list())

        view_df = df.copy()
        if f_status: view_df = view_df[view_df["Audit_Status"].isin(f_status)]
        if f_acc:
            acc_set = {sl.resolve_raw_addr(x) for x in f_acc}
            view_df = view_df[view_df["Account"].apply(sl.resolve_raw_addr).isin(acc_set)]

        # Editor
        edited_df = st.data_editor(
            view_df,
            column_config={
                "Audit_Status": st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam", "Ignoré"]),
                "Category": st.column_config.SelectboxColumn("Catégorie", options=["", "Revenu", "Dépense", "Transfert", "Swap", "Achat", "Vente"]),
            },
            disabled=["Date", "Chain", "Tx_Hash", "Account", "Asset", "Amount", "Source_Way"],
            num_rows="dynamic",
            use_container_width=True,
            key="qualif_editor"
        )

        if st.button("🐾 Sauvegarder Journal"):
            # Update local state
            st.session_state.df_qualif.update(edited_df)
            final_save = ensure_columns(st.session_state.df_qualif)
            # Full for Audit
            final_save.to_csv(j_full_path, index=False)
            # Clean (No Spams) for app3
            clean_save = final_save[final_save["Audit_Status"] != "Spam"]
            clean_save.to_csv(j_path, index=False)
            st.success("Journal synchronisé avec Sanctuarisation.")

        # --- INJECTION TOOLS ---
        st.divider()
        st.subheader("Outils d'injection")
        i_cols = st.columns(2)

        with i_cols[0]:
            st.info("Injecter une vente crypto vers le flux fiat (banq fiat).")
            with st.popover("Préparer Injection Fiat"):
                sel_row_idx = st.selectbox("Choisir transaction de vente",
                                       view_df[view_df["Amount"] != 0].index,
                                       format_func=lambda x: f"{view_df.loc[x, 'Date']} - {view_df.loc[x, 'Amount']} {view_df.loc[x, 'Asset']}")
                fiat_amt = st.number_input("Montant EUR reçu (Optionnel ici, à saisir dans Flux Fiat)", value=0.0)
                if st.button("Confirmer Injection Fiat"):
                    row = view_df.loc[sel_row_idx]
                    data = [{
                        "Date": row["Date"],
                        "Account": row["Account"],
                        "Counterparty": "banq fiat",
                        "Amount": row["Amount"],
                        "Asset": row["Asset"],
                        "Tx Hash": row["Tx_Hash"],
                        "Imposable": True
                    }]
                    sl.inject_to_app0(data, "Fiat", year)
                    st.success("Injecté vers Flux Fiat !")

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
        # Compare current journal with sanctuary backups
        raw_now = merge_raw_data(year)
        missing = raw_now[~raw_now["Tx_Hash"].isin(df["Tx_Hash"])]

        if not missing.empty:
            st.error(f"⚠️ {len(missing)} transactions présentes dans les RAW sont manquantes dans le journal !")
            st.dataframe(missing)
            if st.button("Récupérer les manquants"):
                st.session_state.df_qualif = pd.concat([df, missing]).drop_duplicates(subset=["Tx_Hash", "Asset", "Account"]).sort_values("Date", ascending=False)
                st.success("Intégration terminée. Pensez à sauvegarder.")
        else:
            st.success("Journal en phase avec les sources RAW.")

    with tab3:
        st.metric("Volume Qualifié", f"{len(df[df['Audit_Status']=='Valide'])} tx")
        st.metric("Spams Identifiés", f"{len(df[df['Audit_Status']=='Spam'])} tx")

if __name__ == "__main__":
    main()
