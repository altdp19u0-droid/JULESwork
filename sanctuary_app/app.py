"""
Application principale Streamlit : SANCTUARY APP
Sauvegarde, sanctuarisation, exploration et totalisation à 2 niveaux.
"""
import sys
import os
from pathlib import Path

# Invalidation du cache des bytecode (.pyc) sous Windows/Linux
sys.dont_write_bytecode = True

# Alignement du chemin d'importation Python (sys.path)
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

# S'assurer que APP_DIR et ROOT_DIR sont au début de sys.path sans inclure 'modules' directement
for p in [str(APP_DIR), str(ROOT_DIR)]:
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

import streamlit as st
import pandas as pd
from datetime import datetime, date

# Imports de modules unifiés
from modules.schema import REQUIRED_COLUMNS, enforce_sanctuary_schema
from modules.sanctuary_manager import (
    save_to_sanctuary,
    load_sanctuary_account,
    load_all_sanctuary_for_year,
    list_sanctuary_years,
    list_accounts_for_year
)
from modules.blockscout_collector import fetch_blockscout_data, BLOCKSCOUT_NETWORKS
from modules.csv_importer import map_csv_to_sanctuary
from modules.analytics_engine import filter_by_period, totalize_level_a, totalize_level_b

# Streamlit Page Config
st.set_page_config(page_title="Sanctuary App", layout="wide", page_icon="🛡️")

st.title("🛡️ Sanctuary App — Sauvegarde & Sanctuarisation")
st.caption("Application de collecte, sanctuarisation locale (Windows CSV UTF-8) et totalisation multi-comptes à 2 niveaux.")

# Sidebar Navigation
st.sidebar.title("Navigation")
menu = st.sidebar.radio(
    "Menu principal",
    ["🚜 Ingestion Blockchain (Blockscout)", "📥 Import CSV Externe", "🔍 Consultation & Sanctuarisation", "📊 Totalisation (2 Niveaux)"]
)

# --- MENU 1 : INGESTION BLOCKCHAIN (BLOCKSCOUT V2) ---
if menu == "🚜 Ingestion Blockchain (Blockscout)":
    st.header("🚜 Collecte Blockchain Ciblé par Année (100% Gratuit via Blockscout V2)")
    st.info("Extraction ciblée année par année pour optimiser la récolte sans re-traiter les années déjà sanctuarisées.")

    col1, col2, col3 = st.columns([2, 1, 1])
    address = col1.text_input("Adresse EVM (0x...)", placeholder="0x...")
    network = col2.selectbox("Réseau Blockchain", list(BLOCKSCOUT_NETWORKS.keys()))

    years_options = [2026, 2025, 2024, 2023, 2022, 2021, 2020]
    target_year = col3.selectbox("Année Fiscale à Récolter", options=years_options, index=1, key="harvest_target_year")

    account_label = st.text_input("Libellé / Nom du Compte pour la Sanctuarisation", value=f"{address[:8]}_{network}" if address else "")

    dispatch_mode = st.radio(
        "Mode de Sanctuarisation :",
        [
            f"🎯 Récolte CIBLÉE STRICTE : Récupérer uniquement l'Année Fiscale {target_year} -> sanctuary/{target_year}/{account_label}.csv",
            "📅 Ventilation globale multi-années (sanctuary/{ANNÉE_RÉELLE}/{compte}.csv)"
        ],
        index=0,
        key=f"dispatch_mode_{target_year}"
    )

    filter_strict_target_year = "CIBLÉE STRICTE" in dispatch_mode

    if st.button("🚀 Lancer la récolte ciblée Blockscout"):
        if not address or not address.startswith("0x"):
            st.error("Veuillez saisir une adresse EVM valide.")
        else:
            with st.spinner(f"Extraction rapide ciblée sur l'année {target_year} ({network})..."):
                target_yr = int(target_year) if filter_strict_target_year else None
                df_harvested = fetch_blockscout_data(address, network, target_year=target_yr, account_label=account_label)

            if filter_strict_target_year and not df_harvested.empty:
                df_harvested["_temp_yr"] = pd.to_datetime(df_harvested["Date de la transaction"], errors="coerce").dt.year
                df_harvested = df_harvested[df_harvested["_temp_yr"] == int(target_year)].drop(columns=["_temp_yr"])

            if df_harvested.empty:
                st.warning(f"Aucune transaction trouvée pour l'année {target_year} sur ce réseau." if filter_strict_target_year else "Aucune transaction trouvée pour cette adresse sur ce réseau.")
            else:
                st.success(f"✅ {len(df_harvested)} transactions récupérées avec succès pour l'année {target_year} !" if filter_strict_target_year else f"{len(df_harvested)} transactions récupérées avec succès !")
                st.dataframe(df_harvested, use_container_width=True)

                auto_disp = not filter_strict_target_year
                saved_paths = save_to_sanctuary(df_harvested, int(target_year), account_label, auto_dispatch_year=auto_disp)

                st.success("✅ Données sanctuarisées dans le(s) fichier(s) :")
                for p in saved_paths:
                    st.write(f"- `{p}`")


# --- MENU 2 : IMPORT CSV EXTERNE ---
elif menu == "📥 Import CSV Externe":
    st.header("📥 Importation et Mapping de Fichier CSV Externe")
    st.info("Importez un fichier CSV (Banque, Exchange, Wallet) et associez ses colonnes au schéma standard des 19 colonnes.")

    uploaded_file = st.file_uploader("Choisissez un fichier CSV", type=["csv"])

    if uploaded_file is not None:
        try:
            sample_df = pd.read_csv(uploaded_file, nrows=5)
            uploaded_file.seek(0)
            csv_cols = list(sample_df.columns)

            st.subheader("🔗 Assistant de Mapping des Colonnes")
            st.write("Associez chaque colonne requise à la colonne correspondante de votre fichier CSV :")

            col_mapping = {}
            m1, m2 = st.columns(2)

            for idx, req_col in enumerate(REQUIRED_COLUMNS):
                col_target = m1 if idx % 2 == 0 else m2
                default_match = req_col if req_col in csv_cols else None
                col_mapping[req_col] = col_target.selectbox(
                    f"Champ Sanctuary : **{req_col}**",
                    options=["-- Ignorer --"] + csv_cols,
                    index=csv_cols.index(default_match) + 1 if default_match in csv_cols else 0,
                    key=f"map_{req_col}"
                )

            # Nettoyage des ignorés
            active_mapping = {k: v for k, v in col_mapping.items() if v != "-- Ignorer --"}

            st.divider()
            ic1, ic2, ic3 = st.columns(3)
            default_net = ic1.selectbox("Réseau / Source", ["FIAT", "ETHEREUM", "BASE", "ARBITRUM", "BANQUE"], index=0)
            imp_year = ic2.selectbox("Année Fiscale Cible", options=[2026, 2025, 2024, 2023, 2022], index=1)
            imp_account = ic3.text_input("Nom du Compte Cible", value="Compte_Import_CSV")

            filter_imp_year = st.checkbox(f"Ne sanctuariser que les transactions de l'Année Cible ({imp_year})", value=True)

            if st.button("💾 Valider et Sanctuariser l'Importation"):
                df_mapped = map_csv_to_sanctuary(uploaded_file, active_mapping, default_network=default_net)
                if df_mapped.empty:
                    st.error("Erreur lors du traitement du fichier CSV.")
                else:
                    if filter_imp_year:
                        df_mapped["_temp_yr"] = pd.to_datetime(df_mapped["Date de la transaction"], errors="coerce").dt.year
                        df_mapped = df_mapped[df_mapped["_temp_yr"] == int(imp_year)].drop(columns=["_temp_yr"])

                    if df_mapped.empty:
                        st.warning(f"Aucune transaction trouvée dans le CSV pour l'année {imp_year}.")
                    else:
                        saved_paths = save_to_sanctuary(df_mapped, int(imp_year), imp_account, auto_dispatch_year=not filter_imp_year)
                        st.success(f"✅ {len(df_mapped)} lignes sanctuarisées avec succès !")
                        for p in saved_paths:
                            st.write(f"- `{p}`")
                        st.dataframe(df_mapped, use_container_width=True)
        except Exception as e:
            st.error(f"Erreur de lecture du fichier CSV : {e}")


# --- MENU 3 : CONSULTATION & SANCTUARISATION ---
elif menu == "🔍 Consultation & Sanctuarisation":
    st.header("🔍 Consultation de l'Arborescence Sanctuarisée")

    available_years = list_sanctuary_years()
    if not available_years:
        st.info("Aucun fichier sanctuarisé trouvé dans le dossier `sanctuary/`.")
    else:
        sel_year = st.selectbox("Sélectionner l'Année", available_years)
        accounts = list_accounts_for_year(sel_year)

        c1, c2 = st.columns([1, 3])
        view_mode = c1.radio("Mode d'affichage", ["Compte Spécifique", "Consolidation Globale Année"])

        if view_mode == "Compte Spécifique" and accounts:
            sel_acc = c1.selectbox("Sélectionner le Compte", accounts)
            df_view = load_sanctuary_account(sel_year, sel_acc)
            st.subheader(f"📄 Fichier : `sanctuary/{sel_year}/{sel_acc}.csv` ({len(df_view)} lignes)")
            st.dataframe(df_view, use_container_width=True)
        else:
            df_view = load_all_sanctuary_for_year(sel_year)
            st.subheader(f"🌐 Consolidation Globale {sel_year} ({len(df_view)} transactions réunies)")
            st.dataframe(df_view, use_container_width=True)


# --- MENU 4 : TOTALISATION À 2 NIVEAUX ---
elif menu == "📊 Totalisation (2 Niveaux)":
    st.header("📊 Totalisation des Transactions à Deux Niveaux")

    available_years = list_sanctuary_years()
    if not available_years:
        st.warning("Veuillez d'abord effectuer une récolte ou un import pour alimenter le sanctuaire.")
    else:
        # Filtre de Période Commun
        st.subheader("⚙️ 1. Configuration de la Période d'Analyse")
        p_col1, p_col2, p_col3, p_col4 = st.columns(4)

        p_type = p_col1.selectbox("Type de Période", ["Année", "Trimestre", "Mois", "Personnalisée"])
        p_year = p_col2.selectbox("Année Fiscale", available_years)

        p_quarter = None
        p_month = None
        p_start = None
        p_end = None

        if p_type == "Trimestre":
            p_quarter = p_col3.selectbox("Trimestre", ["Q1", "Q2", "Q3", "Q4"])
        elif p_type == "Mois":
            p_month = p_col3.selectbox("Mois", list(range(1, 13)), format_func=lambda x: f"Mois {x}")
        elif p_type == "Personnalisée":
            p_start = p_col3.date_input("Date Début", date(p_year, 1, 1))
            p_end = p_col4.date_input("Date Fin", date(p_year, 12, 31))

        df_year_all = load_all_sanctuary_for_year(p_year)
        df_filtered_global = filter_by_period(df_year_all, p_type, year=p_year, quarter=p_quarter, month=p_month, start_date=p_start, end_date=p_end)

        st.divider()

        tab_level_a, tab_level_b = st.tabs([
            "📌 Niveau A : Totalisation par Compte",
            "🌐 Niveau B : Totalisation Globale / Consolidée"
        ])

        # --- NIVEAU A : COMPTE INDIVIDUEL ---
        with tab_level_a:
            st.subheader("📌 Niveau A — Totalisation par Compte Individuel")
            accounts = list_accounts_for_year(p_year)

            if not accounts:
                st.info("Aucun compte trouvé.")
            else:
                sel_account_a = st.selectbox("Choisir le Compte à Analyser", accounts, key="sel_a")
                df_acc_raw = load_sanctuary_account(p_year, sel_account_a)
                df_acc_filtered = filter_by_period(df_acc_raw, p_type, year=p_year, quarter=p_quarter, month=p_month, start_date=p_start, end_date=p_end)

                tot_a = totalize_level_a(df_acc_filtered)

                m1, m2 = st.columns(2)
                m1.metric("Volume Total des Transactions", f"{tot_a['total_count']} TXs")
                m2.metric("Totalisation Valorisée (EUR)", f"{tot_a['total_eur']:,.2f} €")

                st.subheader("Ventilation par Devise d'Origine")
                st.dataframe(tot_a["by_currency"], use_container_width=True)

                st.subheader("Ventilation par Type de Transaction")
                st.dataframe(tot_a["by_type"], use_container_width=True)

        # --- NIVEAU B : GLOBALISATION MULTI-COMPTES ---
        with tab_level_b:
            st.subheader("🌐 Niveau B — Totalisation Globale Consolidée (Multi-Comptes)")

            tot_b = totalize_level_b(df_filtered_global)

            g1, g2 = st.columns(2)
            g1.metric("Volume Global Consolidé", f"{tot_b['total_count']} TXs")
            g2.metric("Valeur Globale Totalisée (EUR)", f"{tot_b['total_eur']:,.2f} €")

            b_col1, b_col2 = st.columns(2)
            with b_col1:
                st.subheader("Répartition par Compte Sanctuarisé")
                st.dataframe(tot_b["by_account"], use_container_width=True)

                st.subheader("Répartition par Réseau")
                st.dataframe(tot_b["by_network"], use_container_width=True)

            with b_col2:
                st.subheader("Répartition par Projet / Protocole")
                st.dataframe(tot_b["by_project"], use_container_width=True)

                st.subheader("Répartition par Type de Transaction")
                st.dataframe(tot_b["by_type"], use_container_width=True)
