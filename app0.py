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

    if os.path.exists(fiat_path):
        df = pd.read_csv(fiat_path)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date
        # migration schema: ajout Txn Hash et Adresse/Compte si manquants
        if "Txn Hash" not in df.columns:
            df["Txn Hash"] = ""
        if "Adresse/Compte" not in df.columns:
            df["Adresse/Compte"] = ""
        st.session_state.fiat_journal = df
    else:
        st.session_state.fiat_journal = pd.DataFrame(columns=["Date", "Compte/Label", "Plateforme", "Montant EUR", "Type", "Asset", "Quantité", "Txn Hash", "Adresse/Compte"])

    if os.path.exists(pos_path):
        df = pd.read_csv(pos_path)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date
        if "Txn Hash" not in df.columns:
            df["Txn Hash"] = ""
        st.session_state.positions_journal = df
    else:
        st.session_state.positions_journal = pd.DataFrame(columns=["Date", "Type Position", "Protocole/Plateforme", "Asset", "Quantité", "Adresse/Contrat", "Txn Hash"])

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
        st.session_state.fiat_journal = pd.DataFrame(columns=["Date", "Compte/Label", "Plateforme", "Montant EUR", "Type", "Asset", "Quantité", "Txn Hash", "Adresse/Compte"])
        st.session_state.positions_journal = pd.DataFrame(columns=["Date", "Type Position", "Protocole/Plateforme", "Asset", "Quantité", "Adresse/Contrat", "Txn Hash"])
        st.toast("Saisie vidée (en session uniquement).")
        st.rerun()

    if st.button("🔄 Recharger depuis le disque"):
        load_manual_data(target_year)
        st.toast(f"Données de {target_year} rechargées.")
        st.rerun()

# --- Tabs ---
t1, t2 = st.tabs(["💶 Mouvements Fiat (Banque <> Crypto)", "🔒 Positions, Vaults & Staking"])

with t1:
    st.subheader(f"📝 Saisie des flux monétaires ({target_year})")
    with st.form("fiat_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        # Default date to start of year if target_year is not current year
        default_date = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)
        f_date = c1.date_input("Date du virement", default_date)
        f_label = c2.text_input("Compte Bancaire / Label", placeholder="ex: Compte Courant Bourso")
        f_plat = c3.text_input("Plateforme / Exchange", placeholder="ex: Binance, Kraken")

        c4, c5, c6 = st.columns(3)
        f_amount = c4.number_input("Montant (EUR)", min_value=0.0, step=10.0)
        f_type = c5.selectbox("Nature du flux", [
            "Achat (Virement vers Crypto)",
            "Vente (Retour vers Banque)",
            "(Virement vers )",
            "(Retrait de)"
        ])
        f_asset = c6.text_input("Asset concerné (Optionnel)", placeholder="ex: EUR, USDT, BTC")

        c_hash, c_addr_f, c_qty_f = st.columns([1.5, 1.5, 1])
        f_hash = c_hash.text_input("Txn Hash (Blockchain)", placeholder="0x...")
        f_addr = c_addr_f.text_input("Adresse/Compte Blockchain", placeholder="0x...")
        f_qty = c_qty_f.number_input("Quantité Asset", min_value=0.0, format="%.8f")

        submit_fiat = st.form_submit_button("➕ Ajouter au journal")

        if submit_fiat:
            if f_date.year != target_year:
                st.error(f"❌ La date doit impérativement être en {target_year}.")
            else:
                new_row = {
                    "Date": f_date, "Compte/Label": f_label, "Plateforme": f_plat,
                    "Montant EUR": f_amount, "Type": f_type, "Asset": f_asset.upper(),
                    "Quantité": f_qty, "Txn Hash": f_hash, "Adresse/Compte": f_addr
                }
                st.session_state.fiat_journal = pd.concat([st.session_state.fiat_journal, pd.DataFrame([new_row])], ignore_index=True)
                st.success("Mouvement ajouté.")

    st.divider()
    st.subheader("📊 Contrôle & Observation (Journal en cours)")
    st.info("💡 Vous pouvez modifier les cellules ou supprimer des lignes en les sélectionnant et en appuyant sur 'Suppr' (Delete).")
    st.session_state.fiat_journal = st.data_editor(
        st.session_state.fiat_journal,
        use_container_width=True,
        num_rows="dynamic",
        key="fiat_editor"
    )

with t2:
    st.subheader(f"📝 Saisie des positions ({target_year})")
    with st.form("pos_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        default_date_pos = datetime.now() if target_year == datetime.now().year else datetime(target_year, 1, 1)
        p_date = c1.date_input("Date d'ouverture/maj", default_date_pos)
        p_type = c2.selectbox("Type de position", ["Staking", "Vault (Compound/Aave)", "Lending", "CEX Balance", "Autre"])
        p_plat = c3.text_input("Protocole / Plateforme", placeholder="ex: Lido, Binance Earn")

        c4, c5 = st.columns(2)
        p_asset = c4.text_input("Asset", placeholder="ex: stETH, USDC")
        p_qty = c5.number_input("Quantité", min_value=0.0, format="%.8f")

        c_addr, c_hash_p = st.columns(2)
        p_addr = c_addr.text_input("Adresse Contrat / Memo", placeholder="0x... ou commentaire")
        p_hash = c_hash_p.text_input("Txn Hash (Blockchain)", placeholder="0x...")

        submit_pos = st.form_submit_button("➕ Ajouter à la liste")

        if submit_pos:
            if p_date.year != target_year:
                st.error(f"❌ La date doit impérativement être en {target_year}.")
            else:
                new_row = {
                    "Date": p_date, "Type Position": p_type, "Protocole/Plateforme": p_plat,
                    "Asset": p_asset.upper(), "Quantité": p_qty, "Adresse/Contrat": p_addr,
                    "Txn Hash": p_hash
                }
                st.session_state.positions_journal = pd.concat([st.session_state.positions_journal, pd.DataFrame([new_row])], ignore_index=True)
                st.success("Position enregistrée.")

    st.divider()
    st.subheader("📊 Contrôle & Observation (Positions en cours)")
    st.info("💡 Vous pouvez modifier les cellules ou supprimer des lignes en les sélectionnant et en appuyant sur 'Suppr' (Delete).")
    st.session_state.positions_journal = st.data_editor(
        st.session_state.positions_journal,
        use_container_width=True,
        num_rows="dynamic",
        key="pos_editor"
    )

# --- Sanctuarisation ---
# On affiche toujours la section de sauvegarde pour permettre d'écraser/effacer si besoin
st.divider()
st.subheader("💾 Étape Finale : Sanctuariser les données manuelles")
col_save1, col_save2 = st.columns([2, 1])

with col_save1:
    if st.button(f"💾 Sanctuariser & Mettre à jour le registre {target_year}", use_container_width=True, type="primary"):
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)

        # Incremental approach: we save the current consolidated state
        # (which was loaded at start and modified in session)
        fiat_path = os.path.join(year_dir, f"manual_fiat_{target_year}.csv")
        pos_path = os.path.join(year_dir, f"manual_positions_{target_year}.csv")

        if not st.session_state.fiat_journal.empty:
            st.session_state.fiat_journal.to_csv(fiat_path, index=False)
        if not st.session_state.positions_journal.empty:
            st.session_state.positions_journal.to_csv(pos_path, index=False)

        # Also keep a timestamped backup for safety
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not st.session_state.fiat_journal.empty:
            st.session_state.fiat_journal.to_csv(os.path.join(year_dir, f"backup_fiat_{ts}.csv"), index=False)
        if not st.session_state.positions_journal.empty:
            st.session_state.positions_journal.to_csv(os.path.join(year_dir, f"backup_positions_{ts}.csv"), index=False)

        st.balloons()
        st.success(f"📂 Registres mis à jour et sauvegardés dans : {year_dir}")

with col_save2:
    st.caption("Note : La sanctuarisation écrase le fichier 'Master' de l'année et crée un backup horodaté.")

st.sidebar.divider()
st.sidebar.caption("Registre Manuel v1.0 - app0")
