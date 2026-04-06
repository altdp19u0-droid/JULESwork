import os
import streamlit as st
import pandas as pd
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Registre Fiat & Positions (app0)", layout="wide")
st.title("🏦 Registre Fiat, Plateformes & Positions (Step 0)")

EXPORT_BASE_DIR = "sanctuarisation"

# Initialisation Session State
if "fiat_journal" not in st.session_state:
    st.session_state.fiat_journal = pd.DataFrame(columns=["Date", "Compte/Label", "Plateforme", "Montant EUR", "Type", "Asset", "Quantité"])
if "positions_journal" not in st.session_state:
    st.session_state.positions_journal = pd.DataFrame(columns=["Date", "Type Position", "Protocole/Plateforme", "Asset", "Quantité", "Adresse/Contrat"])

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de traitement", min_value=2015, max_value=2030, value=2024)

    st.divider()
    if st.button("🗑️ Vider la saisie en cours"):
        st.session_state.fiat_journal = pd.DataFrame(columns=["Date", "Compte/Label", "Plateforme", "Montant EUR", "Type", "Asset", "Quantité"])
        st.session_state.positions_journal = pd.DataFrame(columns=["Date", "Type Position", "Protocole/Plateforme", "Asset", "Quantité", "Adresse/Contrat"])
        st.rerun()

# --- Tabs ---
t1, t2 = st.tabs(["💶 Mouvements Fiat (Banque <> Crypto)", "🔒 Positions, Vaults & Staking"])

with t1:
    st.subheader("📝 Saisie des flux monétaires")
    with st.form("fiat_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        f_date = c1.date_input("Date du virement", datetime.now())
        f_label = c2.text_input("Compte Bancaire / Label", placeholder="ex: Compte Courant Bourso")
        f_plat = c3.text_input("Plateforme / Exchange", placeholder="ex: Binance, Kraken")

        c4, c5, c6 = st.columns(3)
        f_amount = c4.number_input("Montant (EUR)", min_value=0.0, step=10.0)
        f_type = c5.selectbox("Nature du flux", ["Achat (Virement vers Crypto)", "Vente (Retour vers Banque)"])
        f_asset = c6.text_input("Asset concerné (Optionnel)", placeholder="ex: EUR, USDT, BTC")

        f_qty = st.number_input("Quantité d'Asset reçue/vendue (Optionnel)", min_value=0.0, format="%.8f")

        submit_fiat = st.form_submit_button("➕ Ajouter au journal")

        if submit_fiat:
            new_row = {
                "Date": f_date, "Compte/Label": f_label, "Plateforme": f_plat,
                "Montant EUR": f_amount, "Type": f_type, "Asset": f_asset.upper(), "Quantité": f_qty
            }
            st.session_state.fiat_journal = pd.concat([st.session_state.fiat_journal, pd.DataFrame([new_row])], ignore_index=True)
            st.success("Mouvement ajouté.")

    st.divider()
    st.dataframe(st.session_state.fiat_journal, use_container_width=True)

with t2:
    st.subheader("📝 Saisie des positions hors-portefeuille direct")
    with st.form("pos_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        p_date = c1.date_input("Date d'ouverture/maj", datetime.now())
        p_type = c2.selectbox("Type de position", ["Staking", "Vault (Compound/Aave)", "Lending", "CEX Balance", "Autre"])
        p_plat = c3.text_input("Protocole / Plateforme", placeholder="ex: Lido, Binance Earn")

        c4, c5 = st.columns(2)
        p_asset = c4.text_input("Asset", placeholder="ex: stETH, USDC")
        p_qty = c5.number_input("Quantité", min_value=0.0, format="%.8f")

        p_addr = st.text_input("Adresse Contrat / Memo", placeholder="0x... ou commentaire")

        submit_pos = st.form_submit_button("➕ Ajouter à la liste")

        if submit_pos:
            new_row = {
                "Date": p_date, "Type Position": p_type, "Protocole/Plateforme": p_plat,
                "Asset": p_asset.upper(), "Quantité": p_qty, "Adresse/Contrat": p_addr
            }
            st.session_state.positions_journal = pd.concat([st.session_state.positions_journal, pd.DataFrame([new_row])], ignore_index=True)
            st.success("Position enregistrée.")

    st.divider()
    st.dataframe(st.session_state.positions_journal, use_container_width=True)

# --- Sanctuarisation ---
has_data = not st.session_state.fiat_journal.empty or not st.session_state.positions_journal.empty

if has_data:
    st.divider()
    st.subheader("💾 Étape Finale : Sanctuariser les données manuelles")
    if st.button(f"Enregistrer le registre pour l'année {target_year}", use_container_width=True):
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if not st.session_state.fiat_journal.empty:
            st.session_state.fiat_journal.to_csv(os.path.join(year_dir, f"manual_fiat_{ts}.csv"), index=False)
        if not st.session_state.positions_journal.empty:
            st.session_state.positions_journal.to_csv(os.path.join(year_dir, f"manual_positions_{ts}.csv"), index=False)

        st.balloons()
        st.success(f"📂 Registres sauvegardés dans : {year_dir}")

st.sidebar.divider()
st.sidebar.caption("Registre Manuel v1.0 - app0")
