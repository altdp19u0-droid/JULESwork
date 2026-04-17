import os
import streamlit as st
import pandas as pd
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Registre Fiat & Positions (app0)", layout="wide")
st.title("🏦 Registre Fiat, Plateformes & Positions (Step 0)")

EXPORT_BASE_DIR = "sanctuarisation"

# Initialisation Session State
if "current_year" not in st.session_state:
    st.session_state.current_year = datetime.now().year

def load_manual_data(year):
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    fiat_path = os.path.join(year_dir, f"manual_fiat_{year}.csv")
    pos_path = os.path.join(year_dir, f"manual_positions_{year}.csv")
    swap_path = os.path.join(year_dir, f"manual_swaps_{year}.csv")

    if os.path.exists(fiat_path):
        df = pd.read_csv(fiat_path, encoding="utf-8-sig")
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
        df = pd.read_csv(pos_path, encoding="utf-8-sig")
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
        df = pd.read_csv(swap_path, encoding="utf-8-sig")
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date
        text_cols = ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]
        for col in text_cols:
            if col not in df.columns: df[col] = ""
            df[col] = df[col].fillna("").astype(str)
        st.session_state.swaps_journal = df
    else:
        cols = ["Date", "Account", "Counterparty", "Asset", "Amount", "Type", "Tx Hash", "Source Type"]
        st.session_state.swaps_journal = pd.DataFrame(columns=cols)
        for col in ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]:
            st.session_state.swaps_journal[col] = st.session_state.swaps_journal[col].astype(str)

if "fiat_journal" not in st.session_state:
    load_manual_data(st.session_state.current_year)

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de traitement", min_value=2015, max_value=2030, value=st.session_state.current_year)

    if target_year != st.session_state.current_year:
        st.session_state.current_year = target_year
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

        st.session_state.swaps_journal = pd.DataFrame(columns=["Date", "Account", "Counterparty", "Asset", "Amount", "Type", "Tx Hash", "Source Type"])
        for col in ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]:
            st.session_state.swaps_journal[col] = st.session_state.swaps_journal[col].astype(str)

        st.toast("Saisie vidée (en session uniquement).")
        st.rerun()

    if st.button("🔄 Recharger depuis le disque"):
        load_manual_data(target_year)
        st.toast(f"Données de {target_year} rechargées.")
        st.rerun()

# --- Tabs ---
t1, t2, t3 = st.tabs(["💶 Mouvements Fiat", "🔒 Positions", "🔄 Échanges & Autovirements"])

@st.fragment
def fragment_fiat():
    st.subheader(f"📝 Saisie des flux monétaires ({target_year})")

    # Utilisation de colonnes hors formulaire pour la réactivité
    c1, c2, c3 = st.columns(3)
    default_date = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)
    f_date = c1.date_input("Date du virement", default_date, key="fiat_date_input")
    f_label = c2.text_input("Compte Bancaire / Label", placeholder="ex: Compte Courant Bourso", key="fiat_label_input")
    f_plat = c3.text_input("Plateforme / Exchange", placeholder="ex: Binance, Kraken", key="fiat_plat_input")

    c4, c5, c6 = st.columns(3)
    f_amount = c4.number_input("Montant (EUR)", min_value=0.0, step=10.0, key="fiat_amount_input")
    def on_fiat_type_change():
        st.session_state["fiat_imp_checkbox"] = (st.session_state["fiat_type_input"] == "Vente (Retour vers Banque)")

    f_type = c5.selectbox("Nature du flux", [
        "Achat (Virement vers Crypto)",
        "Vente (Retour vers Banque)",
        "(Virement vers )",
        "(Retrait de)"
    ], key="fiat_type_input", on_change=on_fiat_type_change)
    f_asset = c6.text_input("Asset concerné (Optionnel)", placeholder="ex: EUR, USDT, BTC", key="fiat_asset_input")

    c_hash, c_addr_f, c_qty_f, c_imp = st.columns([1.5, 1.5, 1, 0.5])
    f_hash = c_hash.text_input("Tx Hash (Blockchain)", placeholder="0x...", key="fiat_hash_input")
    f_addr = c_addr_f.text_input("Adresse/Compte Blockchain", placeholder="0x...", key="fiat_addr_input")
    f_qty = c_qty_f.number_input("Quantité Asset", min_value=0.0, format="%.8f", key="fiat_qty_input")

    # Automatisation de la coche imposable via session_state
    if "fiat_imp_checkbox" not in st.session_state:
        st.session_state["fiat_imp_checkbox"] = (f_type == "Vente (Retour vers Banque)")

    f_imposable = c_imp.checkbox("Imp.", key="fiat_imp_checkbox")

    if st.button("➕ Ajouter au journal", use_container_width=True):
        if f_date.year != target_year:
            st.error(f"❌ La date doit impérativement être en {target_year}.")
        else:
            new_row = {
                "Date": f_date, "Account": f_addr if f_addr else f_label, "Counterparty": f_plat,
                "Compte/Label": f_label, "Plateforme": f_plat,
                "Montant EUR": f_amount, "Type": f_type, "Asset": f_asset.upper(),
                "Quantité": f_qty, "Tx Hash": f_hash, "Imposable": f_imposable
            }
            st.session_state.fiat_journal = pd.concat([st.session_state.fiat_journal, pd.DataFrame([new_row])], ignore_index=True)
            # Ensure types are maintained
            for col in ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]:
                st.session_state.fiat_journal[col] = st.session_state.fiat_journal[col].fillna("").astype(str)
            st.success("Mouvement ajouté.")
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

    st.info("💡 Vous pouvez modifier les cellules ou supprimer des lignes en les sélectionnant et en appuyant sur 'Suppr' (Delete).")

    # Type safety: force string type for text columns to avoid Streamlit FLOAT mismatch crash
    for col in ["Account", "Counterparty", "Compte/Label", "Plateforme", "Asset", "Type", "Tx Hash"]:
        if col in df_fiat.columns:
            df_fiat[col] = df_fiat[col].fillna("").astype(str)

    edited_df = st.data_editor(
        df_fiat,
        column_config={
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
        use_container_width=True,
        num_rows="dynamic",
        key="fiat_editor"
    )
    if not edited_df.equals(df_fiat):
        st.session_state.fiat_journal = edited_df

@st.fragment
def fragment_pos():
    st.subheader(f"📝 Saisie des positions ({target_year})")
    with st.form("pos_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        default_date_pos = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)
        p_date = c1.date_input("Date d'ouverture/maj", default_date_pos)
        p_type = c2.selectbox("Type de position", ["Staking", "Vault (Compound/Aave)", "Lending", "CEX Balance", "Autre"])
        p_plat = c3.text_input("Protocole / Plateforme", placeholder="ex: Lido, Binance Earn")

        c4, c5, c_dir = st.columns([1, 1, 1])
        p_asset = c4.text_input("Asset", placeholder="ex: stETH, USDC")
        p_qty = c5.number_input("Quantité", min_value=0.0, format="%.8f")
        p_direction = c_dir.radio("Sens", ["🔵 Dépôt (+)", "🔴 Sortie (-)"], horizontal=True)

        c_addr, c_hash_p = st.columns(2)
        p_addr = c_addr.text_input("Adresse Contrat / Memo", placeholder="0x... ou commentaire")
        p_hash = c_hash_p.text_input("Tx Hash (Blockchain)", placeholder="0x...")

        submit_pos = st.form_submit_button("➕ Ajouter à la liste")

        if submit_pos:
            if p_date.year != target_year:
                st.error(f"❌ La date doit impérativement être en {target_year}.")
            else:
                # Application du sens (Négatif pour sortie)
                final_qty = p_qty if "Dépôt" in p_direction else -p_qty

                new_row = {
                    "Date": p_date, "Account": p_addr, "Counterparty": p_plat,
                    "Type Position": p_type, "Protocole/Plateforme": p_plat,
                    "Asset": p_asset.upper(), "Quantité": final_qty,
                    "Tx Hash": p_hash
                }
                st.session_state.positions_journal = pd.concat([st.session_state.positions_journal, pd.DataFrame([new_row])], ignore_index=True)
                # Ensure types are maintained
                for col in ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]:
                    st.session_state.positions_journal[col] = st.session_state.positions_journal[col].fillna("").astype(str)
                st.success("Position enregistrée.")
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

    st.info("💡 Vous pouvez modifier les cellules ou supprimer des lignes en les sélectionnant et en appuyant sur 'Suppr' (Delete).")

    # Type safety
    for col in ["Account", "Counterparty", "Type Position", "Protocole/Plateforme", "Asset", "Tx Hash"]:
        if col in df_pos.columns:
            df_pos[col] = df_pos[col].fillna("").astype(str)

    edited_df = st.data_editor(
        df_pos,
        column_config={
            "Date": st.column_config.DateColumn("Date", required=True),
            "Account": st.column_config.TextColumn("Account"),
            "Counterparty": st.column_config.TextColumn("Counterparty"),
            "Type Position": st.column_config.TextColumn("Type Position"),
            "Protocole/Plateforme": st.column_config.TextColumn("Protocole/Plateforme"),
            "Asset": st.column_config.TextColumn("Asset"),
            "Quantité": st.column_config.NumberColumn("Quantité", format="%.8f"),
            "Tx Hash": st.column_config.TextColumn("Tx Hash"),
        },
        use_container_width=True,
        num_rows="dynamic",
        key="pos_editor"
    )
    if not edited_df.equals(df_pos):
        st.session_state.positions_journal = edited_df

@st.fragment
def fragment_swaps():
    st.subheader(f"🔄 Saisie des Échanges et Transferts ({target_year})")
    default_date = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)

    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.write("**🔁 Swap Crypto-to-Crypto**")
        with st.form("swap_form", clear_on_submit=True):
            s_date = st.date_input("Date du swap", default_date)
            s_acc = st.text_input("Compte (ex: Binance, Wallet A)", placeholder="Compte propriétaire")
            c_s1, c_s2 = st.columns(2)
            s_asset_out = c_s1.text_input("Asset Vendu", placeholder="ex: BTC")
            s_qty_out = c_s2.number_input("Quantité Vendue", min_value=0.0, format="%.8f")
            c_s3, c_s4 = st.columns(2)
            s_asset_in = c_s3.text_input("Asset Reçu", placeholder="ex: USDC")
            s_qty_in = c_s4.number_input("Quantité Reçue", min_value=0.0, format="%.8f")
            s_hash = st.text_input("Tx Hash (Optionnel)", placeholder="0x...")

            if st.form_submit_button("➕ Ajouter le Swap"):
                if s_date.year != target_year:
                    st.error("Année incorrecte.")
                else:
                    # Ligne Sortie
                    row_out = {"Date": s_date, "Account": s_acc, "Counterparty": "Swap", "Asset": s_asset_out.upper(), "Amount": -s_qty_out, "Type": "Swap Out", "Tx Hash": s_hash, "Source Type": "Manual Swap"}
                    # Ligne Entrée
                    row_in = {"Date": s_date, "Account": s_acc, "Counterparty": "Swap", "Asset": s_asset_in.upper(), "Amount": s_qty_in, "Type": "Swap In", "Tx Hash": s_hash, "Source Type": "Manual Swap"}
                    st.session_state.swaps_journal = pd.concat([st.session_state.swaps_journal, pd.DataFrame([row_out, row_in])], ignore_index=True)
                    st.success("Swap ajouté (2 lignes créées).")
                    st.rerun()

    with col_s2:
        st.write("**🚚 Transfert Interne**")
        with st.form("transfer_form", clear_on_submit=True):
            t_date = st.date_input("Date du transfert", default_date)
            t_asset = st.text_input("Asset", placeholder="ex: ETH")
            t_qty = st.number_input("Quantité", min_value=0.0, format="%.8f")
            c_t1, c_t2 = st.columns(2)
            t_acc_src = c_t1.text_input("Compte Source", placeholder="ex: Wallet A")
            t_acc_dst = c_t2.text_input("Compte Destination", placeholder="ex: Wallet B")
            t_hash = st.text_input("Tx Hash (Optionnel)", placeholder="0x...")

            if st.form_submit_button("➕ Ajouter le Transfert"):
                if t_date.year != target_year:
                    st.error("Année incorrecte.")
                else:
                    # Ligne Sortie Source
                    row_src = {"Date": t_date, "Account": t_acc_src, "Counterparty": t_acc_dst, "Asset": t_asset.upper(), "Amount": -t_qty, "Type": "Transfert Interne Out", "Tx Hash": t_hash, "Source Type": "Manual Transfer"}
                    # Ligne Entrée Destination
                    row_dst = {"Date": t_date, "Account": t_acc_dst, "Counterparty": t_acc_src, "Asset": t_asset.upper(), "Amount": t_qty, "Type": "Transfert Interne In", "Tx Hash": t_hash, "Source Type": "Manual Transfer"}
                    st.session_state.swaps_journal = pd.concat([st.session_state.swaps_journal, pd.DataFrame([row_src, row_dst])], ignore_index=True)
                    st.success("Transfert ajouté (2 lignes créées).")
                    st.rerun()

    st.divider()
    st.subheader("📊 Journal des Échanges & Autovirements")

    # Barre de tri dynamique
    df_swaps = st.session_state.swaps_journal.copy()
    if not df_swaps.empty:
        ss1, ss2 = st.columns([2, 1])
        sort_col_s = ss1.selectbox("Trier par", options=df_swaps.columns, index=list(df_swaps.columns).index("Date"), key="sort_col_swaps")
        sort_order_s = ss2.radio("Ordre", ["Décroissant", "Croissant"], key="sort_swap_order", horizontal=True)
        df_swaps = df_swaps.sort_values(by=sort_col_s, ascending=(sort_order_s == "Croissant"))

    for col in ["Account", "Counterparty", "Asset", "Type", "Tx Hash", "Source Type"]:
        if col in df_swaps.columns:
            df_swaps[col] = df_swaps[col].fillna("").astype(str)

    edited_df = st.data_editor(
        df_swaps,
        column_config={
            "Date": st.column_config.DateColumn("Date", required=True),
            "Account": st.column_config.TextColumn("Compte"),
            "Counterparty": st.column_config.TextColumn("Contrepartie"),
            "Asset": st.column_config.TextColumn("Asset"),
            "Amount": st.column_config.NumberColumn("Montant", format="%.8f"),
            "Type": st.column_config.TextColumn("Type"),
            "Tx Hash": st.column_config.TextColumn("Tx Hash"),
        },
        use_container_width=True,
        num_rows="dynamic",
        key="swaps_editor"
    )
    if not edited_df.equals(df_swaps):
        st.session_state.swaps_journal = edited_df

with t1: fragment_fiat()
with t2: fragment_pos()
with t3: fragment_swaps()

# --- Sanctuarisation ---
# On affiche toujours la section de sauvegarde pour permettre d'écraser/effacer si besoin
st.divider()
st.subheader("💾 Étape Finale : Sanctuariser les données manuelles")
col_save1, col_save2 = st.columns([2, 1])

with col_save1:
    if st.button(f"💾 Sanctuariser & Mettre à jour le registre {target_year}", use_container_width=True, type="primary"):
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)

        fiat_path = os.path.join(year_dir, f"manual_fiat_{target_year}.csv")
        pos_path = os.path.join(year_dir, f"manual_positions_{target_year}.csv")
        swap_path = os.path.join(year_dir, f"manual_swaps_{target_year}.csv")

        if not st.session_state.fiat_journal.empty: st.session_state.fiat_journal.to_csv(fiat_path, index=False, encoding="utf-8-sig")
        if not st.session_state.positions_journal.empty: st.session_state.positions_journal.to_csv(pos_path, index=False, encoding="utf-8-sig")
        if not st.session_state.swaps_journal.empty: st.session_state.swaps_journal.to_csv(swap_path, index=False, encoding="utf-8-sig")

        # Backups
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not st.session_state.fiat_journal.empty: st.session_state.fiat_journal.to_csv(os.path.join(year_dir, f"backup_fiat_{ts}.csv"), index=False, encoding="utf-8-sig")
        if not st.session_state.positions_journal.empty: st.session_state.positions_journal.to_csv(os.path.join(year_dir, f"backup_positions_{ts}.csv"), index=False, encoding="utf-8-sig")
        if not st.session_state.swaps_journal.empty: st.session_state.swaps_journal.to_csv(os.path.join(year_dir, f"backup_swaps_{ts}.csv"), index=False, encoding="utf-8-sig")

        st.balloons()
        st.success(f"📂 Registres mis à jour et sauvegardés dans : {year_dir}")

with col_save2:
    st.caption("Note : La sanctuarisation écrase le fichier 'Master' de l'année et crée un backup horodaté.")

st.sidebar.divider()
st.sidebar.caption("Registre Manuel v1.0 - app0")
