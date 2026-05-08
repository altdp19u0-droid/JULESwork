import os
import time
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic

# --- Configuration ---
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

# --- Helpers ---
def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
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
    circ_labels = shared_logic.load_external_circuits().get("labels", {})
    owners_map = shared_logic.load_owner_accounts()
    combined = {**circ_labels, **owners_map, **labels}

    def format_cp(cp):
        raw = shared_logic.resolve_raw_addr(cp)
        if raw in combined:
            return f"{combined[raw]} ({raw})"
        return cp

    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    return df

# --- Engine ---
def merge_raw_data(year):
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir):
        return pd.DataFrame(columns=COLUMNS)

    all_rows = []
    spam_list = shared_logic.load_spam_list()

    # 1. Registres Manuels (app0)
    for registry_file, source_label in [(f"manual_fiat_{year}.csv", "Fiat"), (f"manual_swaps_{year}.csv", "Swap")]:
        path = os.path.join(year_dir, registry_file)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                df_registry = shared_logic.pd_read_csv_safe(path)
                for _, r in df_registry.iterrows():
                    if source_label == "Fiat":
                        m_eur = float(r.get("Montant EUR", 0))
                        qty = float(r.get("Quantité", 0))
                        asset = str(r.get("Asset", "EUR")).upper()
                        f_type = str(r.get("Type", ""))
                        dt = pd.to_datetime(r.get("Date"), utc=True)
                        rate = shared_logic.get_fiat_rate("USD", dt)

                        # Jambe EUR
                        all_rows.append({
                            "Date": r.get("Date"), "Account": str(r.get("Account", "Manual")),
                            "Counterparty": str(r.get("Counterparty", "Bank")), "Asset": "EUR",
                            "Amount": m_eur if "Vente" in f_type else -m_eur,
                            "Value ($)": (m_eur / rate) if rate > 0 else 0,
                            "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")),
                            "Source Type": "Fiat", "Category": "Flux Fiat", "Status": "Valide", "Imposable": False
                        })
                        # Jambe Crypto
                        if asset != "EUR" and asset != "NAN" and qty > 0:
                            all_rows.append({
                                "Date": r.get("Date"), "Account": str(r.get("Account", "Manual")),
                                "Counterparty": str(r.get("Counterparty", "Bank")), "Asset": asset,
                                "Amount": qty if "Achat" in f_type else -qty,
                                "Value ($)": (m_eur / rate) if rate > 0 else 0,
                                "Network": "Fiat", "Tx Hash": str(r.get("Tx Hash", "")),
                                "Source Type": "Fiat-to-Crypto", "Category": "Achat" if "Achat" in f_type else "Vente",
                                "Status": "Valide", "Imposable": shared_logic.is_imposable_robust(r.get("Imposable"))
                            })
                    else:
                        all_rows.append({
                            "Date": r.get("Date"), "Account": str(r.get("Account", "")),
                            "Counterparty": str(r.get("Counterparty", "")), "Asset": str(r.get("Asset", "")),
                            "Amount": float(r.get("Amount", 0)), "Value ($)": 0, "Network": "Manual",
                            "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Manual",
                            "Category": "Swap", "Status": "Valide", "Imposable": shared_logic.is_imposable_robust(r.get("Imposable", False))
                        })
            except: pass

    # 2. Données Blockchain (Harvest)
    for f_path in shared_logic.get_all_raw_files(year):
        filename = os.path.basename(f_path)
        source_acc = shared_logic.extract_source_from_filename(filename)
        shared_logic.auto_register_owner(source_acc)
        if os.path.getsize(f_path) == 0: continue
        try:
            df = shared_logic.pd_read_csv_safe(f_path)
            for _, r in df.iterrows():
                acc = str(r.get("Account", source_acc)).lower()
                if filename.startswith("raw_transactions_"):
                    f_addr = shared_logic.resolve_raw_addr(r.get("From", ""))
                    t_addr = str(r.get("To", "")).lower()
                    cp = str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = r.get("To", "") if f_addr == acc else r.get("From", "")
                    amt = float(r.get("Value ETH", 0))
                    if f_addr == acc: amt = -amt
                    asset = str(r.get("Chain", "ETH"))
                    status = "Spam" if (shared_logic.resolve_raw_addr(cp) in spam_list or asset.lower() in spam_list) else "A vérifier"
                    all_rows.append({
                        "Date": r.get("Date"), "Account": acc, "Counterparty": cp, "Asset": asset,
                        "Amount": amt, "Value ($)": float(r.get("Value ($)") or 0), "Network": asset,
                        "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Native",
                        "Category": "A vérifier", "Status": status, "Imposable": shared_logic.is_imposable_robust(r.get("Imposable", False))
                    })
                elif filename.startswith("raw_token_transfers_"):
                    f_addr = shared_logic.resolve_raw_addr(r.get("From", ""))
                    cp = str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = str(r.get("To", "")) if f_addr == acc else str(r.get("From", ""))
                    amt = float(r.get("Value", 0))
                    if f_addr == acc: amt = -amt
                    asset = str(r.get("Token", ""))
                    status = "Spam" if (shared_logic.resolve_raw_addr(cp) in spam_list or asset.lower() in spam_list) else "A vérifier"
                    all_rows.append({
                        "Date": r.get("Date"), "Account": acc, "Counterparty": cp, "Asset": asset,
                        "Amount": amt, "Value ($)": float(r.get("Value ($)") or 0), "Network": str(r.get("Chain", "")),
                        "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Token",
                        "Category": "A vérifier", "Status": status, "Imposable": shared_logic.is_imposable_robust(r.get("Imposable", False))
                    })
        except: pass

    df_final = pd.DataFrame(all_rows)
    if df_final.empty: return pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df_final.columns: df_final[c] = ""

    df_final["Date"] = pd.to_datetime(df_final["Date"], utc=True, errors="coerce")
    df_final = shared_logic.standardize_df_addresses(df_final)

    # Dédoublonnage et Priorisation
    df_final["_d"] = df_final["Date"].dt.date
    df_final = df_final.sort_values("Date", ascending=False).drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account", "_d"], keep="first")

    return apply_position_labels(df_final.drop(columns=["_d"]).reset_index(drop=True))

def sync_data(year):
    path_qual = shared_logic.get_file_path(year, 'qualified')
    new_df = merge_raw_data(year)
    st.session_state.last_sync_time = time.time()

    if os.path.exists(path_qual) and os.path.getsize(path_qual) > 0:
        try:
            old_df = shared_logic.pd_read_csv_safe(path_qual)
            old_df = shared_logic.standardize_df_addresses(old_df)
            old_df["Date"] = pd.to_datetime(old_df["Date"], utc=True, errors="coerce")

            f_cols = ["Category", "Status", "Imposable", "VGP (EUR)", "Linked_ID", "Link_Status"]
            for c in f_cols:
                if c not in old_df.columns: old_df[c] = "" if c not in ["Imposable", "VGP (EUR)"] else (False if c == "Imposable" else 0.0)

            if not new_df.empty:
                new_df["_d"] = new_df["Date"].dt.date
                old_df["_d"] = old_df["Date"].dt.date

                # Mapping des qualifications existantes
                hash_map = old_df[old_df["Tx Hash"] != ""].drop_duplicates("Tx Hash").set_index("Tx Hash")[f_cols].to_dict('index')
                manual_map = old_df[old_df["Tx Hash"] == ""].drop_duplicates(["_d", "Account", "Asset"]).set_index(["_d", "Account", "Asset"])[f_cols].to_dict('index')

                def reapply(row):
                    h, fm = str(row["Tx Hash"]), None
                    if h and h in hash_map: fm = hash_map[h]
                    elif (row["_d"], row["Account"], row["Asset"]) in manual_map: fm = manual_map[(row["_d"], row["Account"], row["Asset"])]

                    if fm:
                        for k in f_cols: row[k] = fm[k]
                        row["Imposable"] = shared_logic.is_imposable_robust(row["Imposable"]) or shared_logic.is_imposable_robust(fm["Imposable"])
                    return row

                new_df = new_df.apply(reapply, axis=1).drop(columns=["_d"])
                st.session_state.journal_qualifie = new_df
            else:
                st.session_state.journal_qualifie = old_df
        except:
            st.session_state.journal_qualifie = new_df
    else:
        st.session_state.journal_qualifie = new_df

# --- UI Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année fiscale", 2015, 2030, datetime.now().year, key="_hub_app2_year")

    if "journal_qualifie" not in st.session_state or st.session_state.get("last_year") != target_year:
        shared_logic.clean_session_state(preserve_keys=["last_year", "_hub_app2_year"])
        sync_data(target_year)
        st.session_state.last_year = target_year

    if st.button("🔄 Actualiser & Fusionner", width='stretch'):
        sync_data(target_year)
        st.success("Synchronisation effectuée.")

    st.divider()
    st.header("📊 Filtres")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_f = st.session_state.journal_qualifie
        f_asset = st.multiselect("Asset", options=sorted(df_f["Asset"].unique()))
        f_acc = st.multiselect("Compte (Account)", options=sorted(list(shared_logic.get_owner_addresses(df_f))))
        f_cat = st.multiselect("Catégorie", options=sorted(df_f["Category"].unique()))
        f_status = st.multiselect("Statut", options=sorted(df_f["Status"].unique()))

        if st.button("⚡ Appliquer les filtres"):
            st.rerun()

    st.divider()
    with st.expander("👥 Gestion des Comptes Propriétaires"):
        owners = shared_logic.load_owner_accounts()
        if owners:
            st.subheader("Modifier ou Supprimer")
            sel_acc = st.selectbox("Choisir un compte", options=[""] + sorted(list(owners.keys())), format_func=lambda x: f"{owners[x]} ({x})" if x else "Sélectionner...")
            if sel_acc:
                new_lbl = st.text_input("Label", value=owners[sel_acc])
                col_b1, col_b2 = st.columns(2)
                if col_b1.button("💾 Maj"):
                    owners[sel_acc] = new_lbl.strip()
                    shared_logic.save_owner_accounts(owners)
                    st.success("Mis à jour."); st.rerun()
                if col_b2.button("🗑️ Suppr"):
                    del owners[sel_acc]
                    shared_logic.save_owner_accounts(owners)
                    st.warning("Supprimé."); st.rerun()

        st.divider()
        st.subheader("Ajouter")
        n_addr = st.text_input("Adresse (0x...)")
        n_lbl = st.text_input("Label (Nom)")
        if st.button("➕ Ajouter aux Propriétaires"):
            if n_addr:
                curr = shared_logic.load_owner_accounts()
                curr[shared_logic.resolve_raw_addr(n_addr)] = n_lbl
                shared_logic.save_owner_accounts(curr)
                st.success("Ajouté."); st.rerun()

# --- Main App ---
tab_q, tab_r = st.tabs(["📋 Qualification", "🤝 Réconciliation"])

with tab_q:
    st.subheader(f"Journal de Qualification {target_year}")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_d = st.session_state.journal_qualifie.copy()

        # Application des filtres
        if f_asset: df_d = df_d[df_d["Asset"].isin(f_asset)]
        if f_acc: df_d = df_d[df_d["Account"].isin(f_acc)]
        if f_cat: df_d = df_d[df_d["Category"].isin(f_cat)]
        if f_status: df_d = df_d[df_d["Status"].isin(f_status)]

        # Initialisation colonnes techniques si absentes
        for c in COLUMNS:
            if c not in df_d.columns: df_d[c] = ""

        if "Sel." not in df_d.columns: df_d.insert(0, "Sel.", False)

        cats = sorted(list(set(["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Frais", "Récompense", "Spam"] + list(df_d["Category"].unique()))))

        edf = st.data_editor(
            df_d,
            column_config={
                "Sel.": st.column_config.CheckboxColumn("Sel."),
                "Category": st.column_config.SelectboxColumn("Catégorie", options=cats),
                "Status": st.column_config.SelectboxColumn("Statut", options=["A vérifier", "Valide", "Spam"]),
                "Imposable": st.column_config.CheckboxColumn("Imposable"),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Account": st.column_config.TextColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True)
            },
            width='stretch',
            key="qual_editor_v2"
        )

        col_act1, col_act2 = st.columns(2)
        if col_act1.button("💶 Transférer vers Fiat (App 0)"):
            sel = edf[edf["Sel."] == True]
            if not sel.empty:
                count = shared_logic.inject_to_app0(sel.drop(columns=["Sel."]).to_dict('records'), "Fiat", target_year)
                st.success(f"{count} lignes transférées vers le registre Fiat."); st.rerun()

        if col_act2.button("🔄 Transférer vers Swaps (App 0)"):
            sel = edf[edf["Sel."] == True]
            if not sel.empty:
                count = shared_logic.inject_to_app0(sel.drop(columns=["Sel."]).to_dict('records'), "Swap", target_year)
                st.success(f"{count} lignes transférées vers le registre Swaps."); st.rerun()

        if st.button("💾 Sanctuariser les qualifications", type="primary", width='stretch'):
            # Fusion des modifications dans le journal complet
            full_j = st.session_state.journal_qualifie
            edf_clean = edf.drop(columns=["Sel."])

            # Simple replace logic: map by index if no filter, or by hash/date if filtered
            # Pour la robustesse, on écrase les lignes correspondantes
            full_j.update(edf_clean)

            st.session_state.journal_qualifie = full_j
            path = shared_logic.get_file_path(target_year, 'qualified')
            full_j.to_csv(path, index=False, encoding="utf-8-sig")
            st.balloons(); st.success("Données sauvegardées.")

with tab_r:
    st.subheader("Maillons & Réconciliation")
    if "journal_qualifie" in st.session_state:
        df = st.session_state.journal_qualifie
        if st.button("🔍 Lancer la recherche automatique"):
            new_df, count = shared_logic.find_reconciliation_matches(df)
            st.session_state.journal_qualifie = new_df
            st.success(f"{count} maillons trouvés."); st.rerun()

        prop = df[df["Link_Status"] == "Proposed"]
        if not prop.empty:
            for lid, gp in prop.groupby("Linked_ID"):
                with st.container(border=True):
                    st.write(f"Lien proposé : `{lid}`")
                    if st.button(f"✅ Confirmer {lid}"):
                        df.loc[df["Linked_ID"] == lid, "Link_Status"] = "Confirmed"
                        st.session_state.journal_qualifie = df; st.rerun()
                    st.dataframe(gp[["Date", "Account", "Asset", "Amount"]], hide_index=True)
