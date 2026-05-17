import os
import streamlit as st
import pandas as pd
from datetime import datetime
import unicodedata
import shared_logic as sl

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Registre Fiat & Positions (app0)", layout="wide")

st.title("🏦 Registre Fiat, Plateformes & Positions (Step 0)")

EXPORT_BASE_DIR = "sanctuarisation"

# Initialisation Session State
if "current_year" not in st.session_state:
    st.session_state.current_year = datetime.now().year

def load_manual_data(year):
    fiat_path = sl.get_file_path(year, 'fiat')
    pos_path = sl.get_file_path(year, 'positions')
    swap_path = sl.get_file_path(year, 'swaps')

    if fiat_path and os.path.exists(fiat_path):
        df = sl.pd_read_csv_safe(fiat_path)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date

        # migration schema & type safety
        text_cols = ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]
        for col in text_cols:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("").astype(str)

        # Legacy resolution for Account/Counterparty if they were missing but others existed
        if df["Account"].replace("", pd.NA).isnull().all() and "Compte/Label" in df.columns:
             df["Account"] = df["Compte/Label"].fillna("").astype(str)
        if df["Counterparty"].replace("", pd.NA).isnull().all() and "Plateforme" in df.columns:
             df["Counterparty"] = df["Plateforme"].fillna("").astype(str)

        if 'Imposable' not in df.columns:
            df['Imposable'] = False
        st.session_state.fiat_journal = df
    else:
        st.session_state.fiat_journal = pd.DataFrame(columns=["Date", "Account", "Counterparty", "Compte/Label", "Plateforme", "Montant EUR", "Type", "Asset", "Quantité", "Tx Hash", "Imposable"])
        for col in ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]:
            st.session_state.fiat_journal[col] = st.session_state.fiat_journal[col].astype(str)

    if os.path.exists(pos_path):
        df = sl.pd_read_csv_safe(pos_path)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date

        # migration schema & type safety
        text_cols = ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]
        for col in text_cols:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("").astype(str)

        # Legacy resolution
        if df["Account"].replace("", pd.NA).isnull().all() and "Adresse/Contrat" in df.columns:
            df["Account"] = df["Adresse/Contrat"].fillna("").astype(str)
        if df["Counterparty"].replace("", pd.NA).isnull().all() and "Protocole/Plateforme" in df.columns:
            df["Counterparty"] = df["Protocole/Plateforme"].fillna("").astype(str)

        st.session_state.positions_journal = df
    else:
        st.session_state.positions_journal = pd.DataFrame(columns=["Date", "Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Quantité", "Tx Hash"])
        for col in ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]:
            st.session_state.positions_journal[col] = st.session_state.positions_journal[col].astype(str)

    if os.path.exists(swap_path):
        df = sl.pd_read_csv_safe(swap_path)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date
        text_cols = ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]
        for col in text_cols:
            if col not in df.columns: df[col] = ""
            df[col] = df[col].fillna("").astype(str)
        if 'Imposable' not in df.columns:
            df['Imposable'] = False
        st.session_state.swaps_journal = df
    else:
        cols = ["Date", "Account", "Counterparty", "Asset", "Amount", "Type", "Tx Hash", "Source Type", "Imposable"]
        st.session_state.swaps_journal = pd.DataFrame(columns=cols)
        for col in ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]:
            st.session_state.swaps_journal[col] = st.session_state.swaps_journal[col].astype(str)
        st.session_state.swaps_journal["Imposable"] = st.session_state.swaps_journal["Imposable"].astype(bool)

if "fiat_journal" not in st.session_state:
    load_manual_data(st.session_state.current_year)

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")

    # Load Unified Processing Year
    g_conf = sl.load_global_config()
    default_year = g_conf.get("processing_year") or datetime.now().year

    target_year = st.number_input("Année de traitement", min_value=2015, max_value=2030, value=default_year, key="_hub_target_year")

    # Persist change if modified here too
    if target_year != g_conf.get("processing_year"):
        g_conf["processing_year"] = int(target_year)
        sl.save_global_config(g_conf)

    if target_year != st.session_state.get("current_year"):
        # _hub_ keys (including _hub_target_year) are auto-preserved by clean_session_state
        sl.clean_session_state(preserve_keys=["current_year"])
        st.session_state.current_year = target_year
        st.cache_data.clear()
        load_manual_data(target_year)
        st.rerun()

    st.divider()
    if st.button("🗑️ Vider la saisie en cours"):
        st.session_state.fiat_journal = pd.DataFrame(columns=["Date", "Account", "Counterparty", "Compte/Label", "Plateforme", "Montant EUR", "Type", "Asset", "Quantité", "Tx Hash", "Imposable"])
        for col in ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]:
            st.session_state.fiat_journal[col] = st.session_state.fiat_journal[col].astype(str)

        st.session_state.positions_journal = pd.DataFrame(columns=["Date", "Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Quantité", "Tx Hash"])
        for col in ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]:
            st.session_state.positions_journal[col] = st.session_state.positions_journal[col].astype(str)

        st.session_state.swaps_journal = pd.DataFrame(columns=["Date", "Account", "Counterparty", "Asset", "Amount", "Type", "Tx Hash", "Source Type", "Imposable"])
        for col in ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]:
            st.session_state.swaps_journal[col] = st.session_state.swaps_journal[col].astype(str)
        st.session_state.swaps_journal["Imposable"] = st.session_state.swaps_journal["Imposable"].astype(bool)

        st.toast("Saisie vidée (en session uniquement).")
        st.rerun()

    if st.button("🔄 Recharger depuis le disque"):
        load_manual_data(target_year)
        st.toast(f"Données de {target_year} rechargées.")
        st.rerun()

    st.divider()
    sl.show_status()

# --- Tabs ---
t1, t2, t3 = st.tabs(["💶 Mouvements Fiat", "🔒 Positions", "🔄 Échanges & Autovirements"])

@st.fragment
def fragment_fiat():
    st.subheader(f"📝 Saisie des flux monétaires ({target_year})")

    # --- PENDING LOAD LOGIC (Avoids StreamlitAPIException) ---
    if "fiat_pending_load" in st.session_state and st.session_state.fiat_pending_load is not None:
        row = st.session_state.fiat_pending_load
        st.session_state.fiat_date_input = row["Date"]
        st.session_state.fiat_amount_input = float(row["Montant EUR"])
        st.session_state.fiat_type_input = row["Type"]
        st.session_state.fiat_asset_input = row["Asset"]
        st.session_state.fiat_hash_input = row["Tx Hash"]
        st.session_state.fiat_qty_input = float(row["Quantité"])
        st.session_state.fiat_imp_checkbox = bool(row["Imposable"])

        known_displays = sl.get_owner_display_list()
        st.session_state.sel_fiat_label = row["Compte/Label"] if row["Compte/Label"] in known_displays else "(Nouveau / Autre...)"
        if row["Compte/Label"] not in known_displays: st.session_state.fiat_label_input = row["Compte/Label"]

        st.session_state.sel_fiat_plat = row["Plateforme"] if row["Plateforme"] in known_displays else "(Nouveau / Autre...)"
        if row["Plateforme"] not in known_displays: st.session_state.fiat_plat_input = row["Plateforme"]

        st.session_state.sel_fiat_addr = row["Account"] if row["Account"] in known_displays else "(Nouveau / Autre...)"
        if row["Account"] not in known_displays: st.session_state.fiat_addr_input = row["Account"]

        # Clear trigger
        st.session_state.fiat_pending_load = None

    # Mode Edition
    edit_idx = st.session_state.get("fiat_edit_idx", None)
    if edit_idx is not None:
        st.warning(f"📝 Mode Édition : Modification de la ligne {edit_idx}")
        if st.button("❌ Annuler l'édition"):
            st.session_state.fiat_edit_idx = None
            st.rerun()

    # Utilisation de colonnes hors formulaire pour la réactivité
    c1, c2, c3 = st.columns(3)
    default_date = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)
    f_date = c1.date_input("Date du virement", default_date, key="fiat_date_input")

    # Prop B: Dropdown with free text fallback
    known_displays = sl.get_owner_display_list()
    options_acc = ["(Nouveau / Autre...)"] + known_displays

    sel_label = c2.selectbox("Compte Bancaire (Connu)", options_acc, key="sel_fiat_label")
    if sel_label == "(Nouveau / Autre...)":
        f_label_raw = c2.text_input("Saisie nouveau compte", placeholder="ex: Compte Courant Bourso", key="fiat_label_input")
        f_label = sl.standardize_address_string(f_label_raw)
    else:
        f_label = sel_label

    sel_plat = c3.selectbox("Plateforme / Contrepartie (Connue)", options_acc, key="sel_fiat_plat")
    if sel_plat == "(Nouveau / Autre...)":
        f_plat_raw = c3.text_input("Saisie nouvelle plateforme", placeholder="ex: Binance, Kraken", key="fiat_plat_input")
        f_plat = sl.standardize_address_string(f_plat_raw)
    else:
        f_plat = sel_plat

    c4, c5, c6 = st.columns(3)
    f_amount = c4.number_input("Montant (EUR)", min_value=0.0, step=10.0, key="fiat_amount_input")
    def on_fiat_type_change():
        st.session_state["fiat_imp_checkbox"] = (st.session_state["fiat_type_input"] == "Vente (Retour vers Banque)")

    f_type = c5.selectbox("Nature du flux", [
        "Achat (Virement vers Crypto)",
        "Vente (Retour vers Banque)",
        "Virement interne (Fiat)",
        "Dépôt",
        "Retrait"
    ], key="fiat_type_input", on_change=on_fiat_type_change)
    f_asset = c6.text_input("Asset concerné (Optionnel)", placeholder="ex: EUR, USDT, BTC", key="fiat_asset_input")

    c_hash, c_addr_f, c_qty_f, c_imp = st.columns([1.5, 1.5, 1, 0.5])
    f_hash = c_hash.text_input("Tx Hash (Blockchain)", placeholder="0x...", key="fiat_hash_input")

    f_addr_sel = c_addr_f.selectbox("Compte / Adresse (Connu)", options_acc, key="sel_fiat_addr")
    f_addr_new = c_addr_f.text_input("Saisie nouveau compte/adresse", placeholder="0x... ou label", key="fiat_addr_input")
    f_addr = sl.standardize_address_string(f_addr_new if f_addr_sel == "(Nouveau / Autre...)" else f_addr_sel)

    f_qty = c_qty_f.number_input("Quantité Asset", min_value=0.0, format="%.8f", key="fiat_qty_input")

    # Automatisation de la coche imposable via session_state
    if "fiat_imp_checkbox" not in st.session_state:
        st.session_state["fiat_imp_checkbox"] = (f_type == "Vente (Retour vers Banque)")

    f_imposable = c_imp.checkbox("Imp.", key="fiat_imp_checkbox")

    btn_label = "💾 Enregistrer les modifications" if edit_idx is not None else "➕ Ajouter au journal"
    if st.button(btn_label, width='stretch', type="primary" if edit_idx is not None else "secondary"):
        if f_date.year != target_year:
            st.error(f"❌ La date doit impérativement être en {target_year}.")
        else:
            new_row = {
                "Date": f_date, "Account": f_addr if f_addr else f_label, "Counterparty": f_plat,
                "Compte/Label": f_label, "Plateforme": f_plat,
                "Montant EUR": f_amount, "Type": f_type, "Asset": f_asset.upper(),
                "Quantité": f_qty, "Tx Hash": f_hash, "Imposable": f_imposable
            }

            if edit_idx is not None:
                # Update existing row
                for k, v in new_row.items():
                    st.session_state.fiat_journal.at[edit_idx, k] = v
                st.session_state.fiat_edit_idx = None
                st.success("Mouvement mis à jour.")
            else:
                # Add new row
                st.session_state.fiat_journal = pd.concat([st.session_state.fiat_journal, pd.DataFrame([new_row])], ignore_index=True)
                st.success("Mouvement ajouté.")

            # Ensure types are maintained
            for col in ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]:
                st.session_state.fiat_journal[col] = st.session_state.fiat_journal[col].fillna("").astype(str)
            st.rerun()

    st.divider()
    st.subheader("📊 Contrôle & Observation (Journal en cours)")

    # Barre de tri dynamique
    df_fiat = st.session_state.fiat_journal.copy()
    if not df_fiat.empty:
        cs1, cs2 = st.columns([2, 1])
        sort_col_f = cs1.selectbox("Trier par", options=df_fiat.columns, index=list(df_fiat.columns).index("Date"), key="sort_col_fiat")
        sort_order_f = cs2.radio("Ordre", ["Décroissant", "Croissant"], key="sort_fiat_order", horizontal=True)
        df_fiat = df_fiat.sort_values(by=sort_col_f, ascending=(sort_order_f == "Croissant"))

    st.info("💡 Cliquez sur une ligne pour la charger dans l'espace de saisie haut. Les lignes en **jaune** proviennent d'un transfert externe et attendent une saisie de montant.")

    # Type safety: force string type for text columns to avoid Streamlit FLOAT mismatch crash
    for col in ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]:
        if col in df_fiat.columns:
            df_fiat[col] = df_fiat[col].fillna("").astype(str)

    if "Mod." not in df_fiat.columns:
        df_fiat.insert(0, "Mod.", False)

    # UI Highlight for rows with 0 amount (injected from app2)
    def style_fiat(row):
        if float(row.get("Montant EUR", 0)) == 0:
            return ['background-color: #ffffcc'] * len(row)
        return [''] * len(row)

    df_fiat = df_fiat.reset_index(drop=True)
    edited_df = st.data_editor(
        df_fiat.style.apply(style_fiat, axis=1),
        column_config={
            "Mod.": st.column_config.CheckboxColumn("Mod.", default=False),
            "Date": st.column_config.DateColumn("Date", required=True),
            "Account": st.column_config.TextColumn("Account"),
            "Counterparty": st.column_config.TextColumn("Counterparty"),
            "Compte/Label": st.column_config.TextColumn("Compte/Label"),
            "Plateforme": st.column_config.TextColumn("Plateforme"),
            "Asset": st.column_config.TextColumn("Asset"), # Force Text for symbols like BTC, ETH
            "Type": st.column_config.TextColumn("Type"),
            "Montant EUR": st.column_config.NumberColumn("Montant EUR", format="%.2f"),
            "Quantité": st.column_config.NumberColumn("Quantité", format="%.8f"),
            "Tx Hash": st.column_config.TextColumn("Tx Hash"),
            "Imposable": st.column_config.CheckboxColumn("Imposable"),
        },
        width='stretch',
        num_rows="dynamic",
        key="fiat_editor"
    )

    # Row Selection Logic via Checkbox
    selected_rows = edited_df[edited_df["Mod."] == True]
    if not selected_rows.empty:
        real_idx = selected_rows.index[0]
        cl1, cl2 = st.columns(2)
        if cl1.button(f"📥 Charger la ligne {real_idx}", key="btn_load_fiat"):
            st.session_state.fiat_edit_idx = real_idx
            st.session_state.fiat_pending_load = selected_rows.iloc[0]
            st.rerun()

        with cl2.popover("🗑️ Supprimer / Restaurer", width='stretch'):
            if st.button("⏪ Supprimer du Registre (Restaurer RAW)", help="Supprime la ligne de ce registre. Elle redeviendra visible dans App 2 (Qualification) si elle provenait d'une injection.", width='stretch'):
                st.session_state.fiat_journal = st.session_state.fiat_journal.drop(index=selected_rows.index)
                st.success("Ligne supprimée du registre.")
                time.sleep(1); st.rerun()

            if st.button("🔥 Éliminer DÉFINITIVEMENT du RAW", help="Supprime la transaction du fichier source original. Utile si la transaction est erronée dès la collecte.", width='stretch'):
                count_del = 0
                for _, s_row in selected_rows.iterrows():
                    # We need the source file but app0 might not have it in its schema
                    # Logic: Try to find match in app2 journal to get source file
                    src_f = s_row.get("Source_File")
                    if not src_f and "_hub_journal_qualifie" in st.session_state:
                         qj = st.session_state["_hub_journal_qualifie"]
                         # Match by quintuplet
                         q_amt = s_row.get("Quantité") or s_row.get("Amount") or 0.0
                         match = qj[ (qj["Asset"]==s_row["Asset"]) & (abs(qj["Amount"]-float(q_amt))<1e-6) & (qj["Tx Hash"]==s_row["Tx Hash"]) ]
                         if not match.empty: src_f = match.iloc[0].get("Source_File")

                    if src_f:
                        f_path = os.path.join(EXPORT_BASE_DIR, str(target_year), src_f)
                        if sl.remove_row_from_csv(f_path, s_row): count_del += 1

                st.session_state.fiat_journal = st.session_state.fiat_journal.drop(index=selected_rows.index)
                st.success(f"Ligne supprimée et éliminée de {count_del} fichiers RAW.")
                time.sleep(1); st.rerun()

    if not edited_df.drop(columns=["Mod."], errors="ignore").equals(df_fiat.drop(columns=["Mod."], errors="ignore")):
        st.session_state.fiat_journal = edited_df.drop(columns=["Mod."], errors="ignore")

@st.fragment
def fragment_pos():
    st.subheader(f"📝 Saisie des positions ({target_year})")

    # --- PENDING LOAD LOGIC ---
    if "pos_pending_load" in st.session_state and st.session_state.pos_pending_load is not None:
        row = st.session_state.pos_pending_load
        st.session_state.pos_date_input = row["Date"]
        st.session_state.pos_type_input = row["Type Position"]
        st.session_state.pos_asset_input = row["Asset"]
        st.session_state.pos_qty_input = abs(float(row["Quantité"]))
        st.session_state.pos_dir_input = "🔵 Dépôt (+)" if float(row["Quantité"]) >= 0 else "🔴 Sortie (-)"
        st.session_state.pos_hash_input = row["Tx Hash"]

        known_displays = sl.get_owner_display_list()
        st.session_state.sel_pos_plat = row["Protocole/Plateforme"] if row["Protocole/Plateforme"] in known_displays else "(Nouveau / Autre...)"
        if row["Protocole/Plateforme"] not in known_displays: st.session_state.input_pos_plat_new = row["Protocole/Plateforme"]

        st.session_state.sel_pos_addr = row["Account"] if row["Account"] in known_displays else "(Nouveau / Autre...)"
        if row["Account"] not in known_displays: st.session_state.input_pos_addr_new = row["Account"]

        st.session_state.pos_pending_load = None

    # Mode Edition
    edit_idx = st.session_state.get("pos_edit_idx", None)
    if edit_idx is not None:
        st.warning(f"📝 Mode Édition : Modification de la ligne {edit_idx}")
        if st.button("❌ Annuler l'édition", key="btn_cancel_pos"):
            st.session_state.pos_edit_idx = None
            st.rerun()

    c1, c2, c3 = st.columns(3)
    default_date_pos = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)
    p_date = c1.date_input("Date d'ouverture/maj", default_date_pos, key="pos_date_input")
    p_type = c2.selectbox("Type de position", ["Staking", "Vault (Compound/Aave)", "Lending", "CEX Balance", "Autre"], key="pos_type_input")

    known_displays = sl.get_owner_display_list()
    options_acc = ["(Nouveau / Autre...)"] + known_displays
    p_plat_sel = c3.selectbox("Plateforme / Protocole (Connu)", options_acc, key="sel_pos_plat")
    p_plat_new = c3.text_input("Saisie nouveau label", placeholder="ex: Lido, Binance Earn", key="input_pos_plat_new")
    p_plat = sl.standardize_address_string(p_plat_new if p_plat_sel == "(Nouveau / Autre...)" else p_plat_sel)

    c4, c5, c_dir = st.columns([1, 1, 1])
    p_asset = c4.text_input("Asset", placeholder="ex: stETH, USDC", key="pos_asset_input")
    p_qty = c5.number_input("Quantité", min_value=0.0, format="%.8f", key="pos_qty_input")
    p_direction = c_dir.radio("Sens", ["🔵 Dépôt (+)", "🔴 Sortie (-)"], horizontal=True, key="pos_dir_input")

    c_addr, c_hash_p = st.columns(2)
    p_addr_sel = c_addr.selectbox("Compte / Adresse (Connu)", options_acc, key="sel_pos_addr")
    p_addr_new = c_addr.text_input("Saisie nouveau compte/adresse", placeholder="0x... ou label", key="input_pos_addr_new")
    p_addr = sl.standardize_address_string(p_addr_new if p_addr_sel == "(Nouveau / Autre...)" else p_addr_sel)

    p_hash = c_hash_p.text_input("Tx Hash (Blockchain)", placeholder="0x...", key="pos_hash_input")

    btn_label = "💾 Enregistrer les modifications" if edit_idx is not None else "➕ Ajouter à la liste"
    if st.button(btn_label, width='stretch', type="primary" if edit_idx is not None else "secondary", key="btn_submit_pos"):
        if p_date.year != target_year:
            st.error(f"❌ La date doit impérativement être en {target_year}.")
        else:
            final_qty = p_qty if "Dépôt" in p_direction else -p_qty
            new_row = {
                "Date": p_date, "Account": p_addr, "Counterparty": p_plat,
                "Type Position": p_type, "Protocole/Plateforme": p_plat,
                "Asset": p_asset.upper(), "Quantité": final_qty,
                "Tx Hash": p_hash
            }

            if edit_idx is not None:
                for k, v in new_row.items():
                    st.session_state.positions_journal.at[edit_idx, k] = v
                st.session_state.pos_edit_idx = None
                st.success("Position mise à jour.")
            else:
                st.session_state.positions_journal = pd.concat([st.session_state.positions_journal, pd.DataFrame([new_row])], ignore_index=True)
                st.success("Position enregistrée.")

            for col in ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]:
                st.session_state.positions_journal[col] = st.session_state.positions_journal[col].fillna("").astype(str)
            st.rerun()

    st.divider()
    st.subheader("📊 Contrôle & Observation (Positions en cours)")

    # Barre de tri dynamique
    df_pos = st.session_state.positions_journal.copy()
    if not df_pos.empty:
        ps1, ps2 = st.columns([2, 1])
        sort_col_p = ps1.selectbox("Trier par", options=df_pos.columns, index=list(df_pos.columns).index("Date"), key="sort_col_pos")
        sort_order_p = ps2.radio("Ordre", ["Décroissant", "Croissant"], key="sort_pos_order", horizontal=True)
        df_pos = df_pos.sort_values(by=sort_col_p, ascending=(sort_order_p == "Croissant"))

    st.info("💡 Cliquez sur une ligne pour la charger dans l'espace de saisie haut.")

    # Type safety
    for col in ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]:
        if col in df_pos.columns:
            df_pos[col] = df_pos[col].fillna("").astype(str)

    if "Mod." not in df_pos.columns:
        df_pos.insert(0, "Mod.", False)

    edited_df = st.data_editor(
        df_pos,
        column_config={
            "Mod.": st.column_config.CheckboxColumn("Mod.", default=False),
            "Date": st.column_config.DateColumn("Date", required=True),
            "Account": st.column_config.TextColumn("Account"),
            "Counterparty": st.column_config.TextColumn("Counterparty"),
            "Type Position": st.column_config.TextColumn("Type Position"),
            "Protocole/Plateforme": st.column_config.TextColumn("Protocole/Plateforme"),
            "Asset": st.column_config.TextColumn("Asset"),
            "Quantité": st.column_config.NumberColumn("Quantité", format="%.8f"),
            "Tx Hash": st.column_config.TextColumn("Tx Hash"),
        },
        width='stretch',
        num_rows="dynamic",
        key="pos_editor"
    )

    # Row Selection Logic
    selected_rows = edited_df[edited_df["Mod."] == True]
    if not selected_rows.empty:
        real_idx = selected_rows.index[0]
        cl1, cl2 = st.columns(2)
        if cl1.button(f"📥 Charger la ligne {real_idx}", key="btn_load_pos"):
            st.session_state.pos_edit_idx = real_idx
            st.session_state.pos_pending_load = selected_rows.iloc[0]
            st.rerun()

        with cl2.popover("🗑️ Supprimer / Restaurer", width='stretch'):
            if st.button("⏪ Supprimer du Registre", width='stretch'):
                st.session_state.positions_journal = st.session_state.positions_journal.drop(index=selected_rows.index)
                st.success("Ligne supprimée.")
                time.sleep(1); st.rerun()

    if not edited_df.drop(columns=["Mod."], errors="ignore").equals(df_pos.drop(columns=["Mod."], errors="ignore")):
        st.session_state.positions_journal = edited_df.drop(columns=["Mod."], errors="ignore")

@st.fragment
def fragment_swaps():
    st.subheader(f"🔄 Saisie des Échanges et Transferts ({target_year})")

    # --- PENDING LOAD LOGIC ---
    if "swap_pending_load" in st.session_state and st.session_state.swap_pending_load is not None:
        row = st.session_state.swap_pending_load
        known_displays = sl.get_owner_display_list()
        if "Swap" in row["Type"]:
            st.session_state.swap_date_input = row["Date"]
            st.session_state.sel_swap_acc = row["Account"] if row["Account"] in known_displays else "(Nouveau / Autre...)"
            if row["Account"] not in known_displays: st.session_state.input_swap_acc_new = row["Account"]
            st.session_state.swap_hash_input = row["Tx Hash"]
            st.session_state.swap_imp_input = bool(row["Imposable"])
            if "Out" in row["Type"]:
                st.session_state.swap_asset_out_input = row["Asset"]
                st.session_state.swap_qty_out_input = abs(float(row["Amount"]))
            else:
                st.session_state.swap_asset_in_input = row["Asset"]
                st.session_state.swap_qty_in_input = abs(float(row["Amount"]))
        else:
            st.session_state.trans_date_input = row["Date"]
            st.session_state.trans_asset_input = row["Asset"]
            st.session_state.trans_qty_input = abs(float(row["Amount"]))
            st.session_state.trans_hash_input = row["Tx Hash"]
            st.session_state.trans_imp_input = bool(row["Imposable"])
            if "Out" in row["Type"]:
                st.session_state.sel_trans_src = row["Account"] if row["Account"] in known_displays else "(Nouveau / Autre...)"
                if row["Account"] not in known_displays: st.session_state.input_trans_src_new = row["Account"]
                st.session_state.sel_trans_dst = row["Counterparty"] if row["Counterparty"] in known_displays else "(Nouveau / Autre...)"
                if row["Counterparty"] not in known_displays: st.session_state.input_trans_dst_new = row["Counterparty"]
            else:
                st.session_state.sel_trans_dst = row["Account"] if row["Account"] in known_displays else "(Nouveau / Autre...)"
                if row["Account"] not in known_displays: st.session_state.input_trans_dst_new = row["Account"]
                st.session_state.sel_trans_src = row["Counterparty"] if row["Counterparty"] in known_displays else "(Nouveau / Autre...)"
                if row["Counterparty"] not in known_displays: st.session_state.input_trans_src_new = row["Counterparty"]

        st.session_state.swap_pending_load = None
    default_date = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)

    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.write("**🔁 Swap Crypto-to-Crypto**")
        s_date = st.date_input("Date du swap", default_date, key="swap_date_input")

        known_displays = sl.get_owner_display_list()
        options_acc = ["(Nouveau / Autre...)"] + known_displays

        s_acc_sel = st.selectbox("Compte (Connu)", options_acc, key="sel_swap_acc")
        s_acc_new = st.text_input("Saisie nouveau compte", placeholder="ex: Binance, Wallet A", key="input_swap_acc_new")
        s_acc = sl.standardize_address_string(s_acc_new if s_acc_sel == "(Nouveau / Autre...)" else s_acc_sel)

        c_s1, c_s2 = st.columns(2)
        s_asset_out = c_s1.text_input("Asset Vendu", placeholder="ex: BTC", key="swap_asset_out_input")
        s_qty_out = c_s2.number_input("Quantité Vendue", min_value=0.0, format="%.8f", key="swap_qty_out_input")
        c_s3, c_s4 = st.columns(2)
        s_asset_in = c_s3.text_input("Asset Reçu", placeholder="ex: USDC", key="swap_asset_in_input")
        s_qty_in = c_s4.number_input("Quantité Reçue", min_value=0.0, format="%.8f", key="swap_qty_in_input")
        s_hash = st.text_input("Tx Hash (Optionnel)", placeholder="0x...", key="swap_hash_input")
        s_imp = st.checkbox("Imposable", value=False, key="swap_imp_input")

        if st.button("➕ Ajouter le Swap", key="btn_add_swap"):
            if s_date.year != target_year:
                st.error("Année incorrecte.")
            else:
                row_out = {"Date": s_date, "Account": s_acc, "Counterparty": "Swap", "Asset": s_asset_out.upper(), "Amount": -s_qty_out, "Type": "Swap Out", "Tx Hash": s_hash, "Source Type": "Manual Swap", "Imposable": s_imp}
                row_in = {"Date": s_date, "Account": s_acc, "Counterparty": "Swap", "Asset": s_asset_in.upper(), "Amount": s_qty_in, "Type": "Swap In", "Tx Hash": s_hash, "Source Type": "Manual Swap", "Imposable": s_imp}
                st.session_state.swaps_journal = pd.concat([st.session_state.swaps_journal, pd.DataFrame([row_out, row_in])], ignore_index=True)
                st.success("Swap ajouté.")
                st.rerun()

    with col_s2:
        st.write("**🚚 Transfert Interne**")
        t_date = st.date_input("Date du transfert", default_date, key="trans_date_input")
        t_asset = st.text_input("Asset", placeholder="ex: ETH", key="trans_asset_input")
        t_qty = st.number_input("Quantité", min_value=0.0, format="%.8f", key="trans_qty_input")

        known_displays = sl.get_owner_display_list()
        options_acc = ["(Nouveau / Autre...)"] + known_displays

        c_t1, c_t2 = st.columns(2)
        t_src_sel = c_t1.selectbox("Compte Source (Connu)", options_acc, key="sel_trans_src")
        t_src_new = c_t1.text_input("Saisie nouveau source", placeholder="ex: Wallet A", key="input_trans_src_new")
        t_acc_src = sl.standardize_address_string(t_src_new if t_src_sel == "(Nouveau / Autre...)" else t_src_sel)

        t_dst_sel = c_t2.selectbox("Compte Destination (Connu)", options_acc, key="sel_trans_dst")
        t_dst_new = c_t2.text_input("Saisie nouveau dest.", placeholder="ex: Wallet B", key="input_trans_dst_new")
        t_acc_dst = sl.standardize_address_string(t_dst_new if t_dst_sel == "(Nouveau / Autre...)" else t_dst_sel)
        t_hash = st.text_input("Tx Hash (Optionnel)", placeholder="0x...", key="trans_hash_input")
        t_imp = st.checkbox("Imposable", value=False, key="trans_imp_input")

        if st.button("➕ Ajouter le Transfert", key="btn_add_trans"):
            if t_date.year != target_year:
                st.error("Année incorrecte.")
            else:
                row_src = {"Date": t_date, "Account": t_acc_src, "Counterparty": t_acc_dst, "Asset": t_asset.upper(), "Amount": -t_qty, "Type": "Transfert Interne Out", "Tx Hash": t_hash, "Source Type": "Manual Transfer", "Imposable": t_imp}
                row_dst = {"Date": t_date, "Account": t_acc_dst, "Counterparty": t_acc_src, "Asset": t_asset.upper(), "Amount": t_qty, "Type": "Transfert Interne In", "Tx Hash": t_hash, "Source Type": "Manual Transfer", "Imposable": t_imp}
                st.session_state.swaps_journal = pd.concat([st.session_state.swaps_journal, pd.DataFrame([row_src, row_dst])], ignore_index=True)
                st.success("Transfert ajouté.")
                st.rerun()

    st.divider()
    st.subheader("📊 Journal des Échanges & Autovirements")

    # Barre de tri dynamique
    df_swaps = st.session_state.swaps_journal.copy()
    if not df_swaps.empty:
        ss1, ss2 = st.columns([2, 1])
        sort_col_s = ss1.selectbox("Trier par", options=df_swaps.columns, index=list(df_swaps.columns).index("Date"), key="sort_col_swaps")
        sort_order_s = ss2.radio("Ordre", ["Décroissant", "Croissant"], key="sort_swap_order", horizontal=True)
        # Use existing sort_order_f if defined, otherwise default to Descending
        df_swaps = df_swaps.sort_values(by=sort_col_s, ascending=(sort_order_s == "Croissant"))

    for col in ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]:
        if col in df_swaps.columns:
            df_swaps[col] = df_swaps[col].fillna("").astype(str)

    st.info("💡 Cochez la colonne 'Mod.' pour charger une ligne dans le formulaire. Les lignes en **jaune** proviennent d'un transfert externe.")
    if "Mod." not in df_swaps.columns:
        df_swaps.insert(0, "Mod.", False)

    def style_swaps(row):
        if "Transfer from App2" in str(row.get("Source Type", "")):
            return ['background-color: #ffffcc'] * len(row)
        return [''] * len(row)

    df_swaps = df_swaps.reset_index(drop=True)
    edited_df = st.data_editor(
        df_swaps.style.apply(style_swaps, axis=1),
        column_config={
            "Mod.": st.column_config.CheckboxColumn("Mod.", default=False),
            "Date": st.column_config.DateColumn("Date", required=True),
            "Account": st.column_config.TextColumn("Compte"),
            "Counterparty": st.column_config.TextColumn("Contrepartie"),
            "Asset": st.column_config.TextColumn("Asset"),
            "Amount": st.column_config.NumberColumn("Montant", format="%.8f"),
            "Type": st.column_config.TextColumn("Type"),
            "Tx Hash": st.column_config.TextColumn("Tx Hash"),
            "Imposable": st.column_config.CheckboxColumn("Imp."),
        },
        width='stretch',
        num_rows="dynamic",
        key="swaps_editor"
    )

    # Row Selection Logic for Swaps/Transfers
    selected_rows = edited_df[edited_df["Mod."] == True]
    if not selected_rows.empty:
        real_idx = selected_rows.index[0]
        cl1, cl2 = st.columns(2)
        if cl1.button(f"📥 Charger la ligne {real_idx}", key="btn_load_swap"):
            st.session_state.swap_pending_load = selected_rows.iloc[0]
            st.rerun()

        with cl2.popover("🗑️ Supprimer / Restaurer", width='stretch'):
            if st.button("⏪ Supprimer du Registre", width='stretch'):
                st.session_state.swaps_journal = st.session_state.swaps_journal.drop(index=selected_rows.index)
                st.success("Ligne supprimée.")
                time.sleep(1); st.rerun()

    if not edited_df.drop(columns=["Mod."], errors="ignore").equals(df_swaps.drop(columns=["Mod."], errors="ignore")):
        st.session_state.swaps_journal = edited_df.drop(columns=["Mod."], errors="ignore")

with t1: fragment_fiat()
with t2: fragment_pos()
with t3: fragment_swaps()

# --- Sanctuarisation ---
# On affiche toujours la section de sauvegarde pour permettre d'écraser/effacer si besoin
st.divider()
st.subheader("💾 Étape Finale : Sanctuariser les données manuelles")
col_save1, col_save2 = st.columns([2, 1])

with col_save1:
    if st.button(f"💾 Sanctuariser & Mettre à jour le registre {target_year}", width='stretch', type="primary"):
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)

        fiat_path = sl.get_file_path(target_year, 'fiat')
        pos_path = sl.get_file_path(target_year, 'positions')
        swap_path = sl.get_file_path(target_year, 'swaps')

        # Forced Normalization before saving
        df_fiat = sl.standardize_df_addresses(st.session_state.fiat_journal)
        df_pos = sl.standardize_df_addresses(st.session_state.positions_journal)
        df_swaps = sl.standardize_df_addresses(st.session_state.swaps_journal)

        df_fiat.to_csv(fiat_path, index=False, encoding="utf-8-sig")
        df_pos.to_csv(pos_path, index=False, encoding="utf-8-sig")
        df_swaps.to_csv(swap_path, index=False, encoding="utf-8-sig")

        # Backups in Sanctuary
        s_dir = os.path.join(year_dir, "sanctuary"); os.makedirs(s_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        df_fiat.to_csv(os.path.join(s_dir, f"backup_fiat_{ts}.csv"), index=False, encoding="utf-8-sig")
        df_pos.to_csv(os.path.join(s_dir, f"backup_positions_{ts}.csv"), index=False, encoding="utf-8-sig")
        df_swaps.to_csv(os.path.join(s_dir, f"backup_swaps_{ts}.csv"), index=False, encoding="utf-8-sig")

        st.balloons()
        st.success(f"📂 Registres mis à jour et sauvegardés dans : {year_dir}")

with col_save2:
    st.caption("Note : La sanctuarisation écrase le fichier 'Master' de l'année et crée un backup horodaté.")

st.sidebar.divider()
st.sidebar.caption("Registre Manuel v1.0 - app0")
