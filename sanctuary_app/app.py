"""
Application principale Streamlit : SANCTUARY APP
Sauvegarde, sanctuarisation, exploration et totalisation à 2 niveaux.
"""
import sys
import os
from pathlib import Path

# Desactivation des bytecodes .pyc
sys.dont_write_bytecode = True

# Résolution des chemins de packages
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

# Ajout dynamique de ROOT_DIR et APP_DIR à sys.path sans collision
for path_obj in [ROOT_DIR, APP_DIR]:
    p_str = str(path_obj)
    if p_str in sys.path:
        sys.path.remove(p_str)
    sys.path.insert(0, p_str)

import streamlit as st
import pandas as pd
from datetime import datetime, date

# Imports de modules unifiés
try:
    from sanctuary_app.modules.schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, smart_parse_dates
    from sanctuary_app.modules.sanctuary_manager import (
        save_to_sanctuary,
        load_sanctuary_account,
        load_all_sanctuary_for_year,
        load_all_sanctuary_all_years,
        load_account_all_years,
        list_sanctuary_years,
        list_accounts_for_year,
        list_all_accounts_all_years
    )
    from sanctuary_app.modules.blockscout_collector import fetch_blockscout_data, BLOCKSCOUT_NETWORKS
    from sanctuary_app.modules.csv_importer import (
        map_csv_to_sanctuary,
        detect_csv_source,
        save_custom_csv_signature,
        get_effective_column_mapping,
        save_platform_column_mapping
    )
    from sanctuary_app.modules.analytics_engine import filter_by_period, totalize_level_a, totalize_level_b
except ImportError:
    from modules.schema import REQUIRED_COLUMNS, enforce_sanctuary_schema, smart_parse_dates
    from modules.sanctuary_manager import (
        save_to_sanctuary,
        load_sanctuary_account,
        load_all_sanctuary_for_year,
        load_all_sanctuary_all_years,
        load_account_all_years,
        list_sanctuary_years,
        list_accounts_for_year,
        list_all_accounts_all_years
    )
    from modules.blockscout_collector import fetch_blockscout_data, BLOCKSCOUT_NETWORKS
    from modules.csv_importer import (
        map_csv_to_sanctuary,
        detect_csv_source,
        save_custom_csv_signature,
        get_effective_column_mapping,
        save_platform_column_mapping
    )
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

    filter_strict_target_year = "CIBLÉE STRICTE" in dispatch_mode or "STRICTE" in dispatch_mode or "Récolte CIBLÉE" in dispatch_mode

    if st.button("🚀 Lancer la récolte ciblée Blockscout"):
        if not address or not address.startswith("0x"):
            st.error("Veuillez saisir une adresse EVM valide.")
        else:
            target_yr_param = int(target_year) if filter_strict_target_year else None
            with st.spinner(f"Extraction rapide ciblée sur l'année {target_year} ({network})..."):
                df_harvested = fetch_blockscout_data(address, network, target_year=target_yr_param, account_label=account_label)

            if filter_strict_target_year and not df_harvested.empty:
                df_harvested["_temp_yr"] = smart_parse_dates(df_harvested["Date de la transaction"]).dt.year
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
    st.info("Importez un fichier CSV (Reconnaissance automatique de la plateforme BLEAP, NEVERLESS, 8LENDS, etc. par signature d'en-tête).")

    uploaded_file = st.file_uploader("Choisissez un fichier CSV", type=["csv"])

    if uploaded_file is not None:
        try:
            try:
                sample_df = pd.read_csv(uploaded_file, nrows=5, sep=None, engine="python")
            except Exception:
                uploaded_file.seek(0)
                sample_df = pd.read_csv(uploaded_file, nrows=5, encoding="latin1", sep=";")

            uploaded_file.seek(0)
            csv_cols = list(sample_df.columns)

            # Reconnaissance automatique de la source du CSV par signature
            detected_source = detect_csv_source(csv_cols, filename=uploaded_file.name)

            net_options = [
                "BLEAP", "NEVERLESS", "8LENDS", "KRAKEN", "BANQUE", "FIAT",
                "ETHEREUM", "BASE", "ARBITRUM", "EXCHANGE", "LENDING", "AUTRE"
            ]

            default_index = 0
            if detected_source and detected_source in net_options:
                default_index = net_options.index(detected_source)
                st.success(f"✨ **Plateforme reconnue automatiquement par signature de colonnes : `{detected_source}` !**")

            # --- ÉTAPE DE CONFIRMATION ET NOMMAGE DU FICHIER / COMPTE ---
            st.divider()
            st.subheader("✏️ Confirmation & Nommage du Compte / Fichier Sanctuarisé")
            st.caption("Confirmez ou personnalisez le nom du fichier CSV qui sera créé dans l'arborescence `sanctuary/{ANNÉE}/`.")

            ic1, ic2, ic3 = st.columns(3)
            default_net = ic1.selectbox("Réseau / Source de la plateforme", net_options, index=default_index)
            if default_net == "AUTRE":
                custom_net = st.text_input("Spécifier le nom du Réseau / Source", value="CUSTOM_SOURCE")
                if custom_net.strip():
                    default_net = custom_net.strip().upper()

            imp_year = ic2.selectbox("Année Fiscale Cible de Référence", options=[2026, 2025, 2024, 2023, 2022], index=1)

            # Suggestion dynamique du nom du fichier sanctuarisé basée sur la plateforme et le nom du fichier d'origine
            clean_stem = Path(uploaded_file.name).stem.replace(" ", "_")
            suggested_acc_name = f"{default_net}_{clean_stem}"

            imp_account = ic3.text_input(
                "Nom personnalisé du Compte / Fichier CSV Cible",
                value=suggested_acc_name,
                help="Ce nom définira le fichier sanctuarisé `sanctuary/{ANNÉE}/{Nom_Du_Compte}.csv`"
            )

            st.info(f"📁 **Aperçu du chemin de sanctuarisation :** `sanctuary/{imp_year}/{imp_account}.csv`")

            st.divider()
            st.subheader(f"🔗 Assistant de Mapping & Importateur Dédié : **{default_net}**")
            st.write("Associez si besoin les colonnes requises à la colonne correspondante de votre fichier CSV :")

            # Dictionnaire d'alias pour la pré-sélection intelligente des colonnes CSV
            COLUMN_ALIASES = {
                "Date de la transaction": ["date", "timestamp", "time", "date/time", "date utc", "created_at"],
                "Type de transaction": ["type", "transaction type", "operation", "action", "kind"],
                "ID du projet": ["id du projet", "project id", "project", "projet"],
                "Nom du projet": ["nom du projet", "project name", "description", "details"],
                "APR %": ["apr %", "apr", "yield", "rate"],
                "Montant d'origine": ["montant d'origine", "amount sent", "amount", "montant", "sent amount", "quantity", "valeur"],
                "Devise d'origine": ["devise d'origine", "asset sent", "currency sent", "asset", "currency", "symbol", "coin"],
                "Montant du relevé": ["montant du relevé", "amount received", "received amount", "statement amount", "eur amount"],
                "Devise du relevé": ["devise du relevé", "asset received", "currency received", "received asset"],
                "Paire FX": ["paire fx", "fx pair", "pair"],
                "Taux de change appliqué": ["taux de change appliqué", "exchange rate", "rate", "fx rate"],
                "Date du taux de change appliqué": ["date du taux de change appliqué", "fx date", "rate date"],
                "Source du taux de change": ["source du taux de change", "rate source", "fx source"],
                "Statut de la transaction": ["statut de la transaction", "status", "statut", "state"],
                "Réseau": ["réseau", "network", "chain", "blockchain"],
                "Hash de la transaction blockchain": ["hash de la transaction blockchain", "blockchain transaction hash", "tx hash", "hash", "transaction id / hash", "transaction hash", "tx_hash", "txid"],
                "Notes": ["notes", "description", "notes/details", "details", "memo", "comment", "remarque"],
                "Nom et numéro [Banque fiat ou compte] d'origine": ["blockchain address", "from", "source address", "account from", "adresse origine"],
                "Nom et numéro [Banque fiat ou compte] de destination": ["destination address", "to", "target address", "account to", "adresse destination"]
            }

            # Chargement de la grille de mapping mémorisée / par défaut pour cette plateforme
            learned_mapping = get_effective_column_mapping(default_net, csv_cols)
            if learned_mapping:
                st.info(f"💡 **Grille de récolte Mémorisée pour `{default_net}`** appliquée automatiquement ({len(learned_mapping)} champs associés) !")

            col_mapping = {}
            m1, m2 = st.columns(2)

            for idx, req_col in enumerate(REQUIRED_COLUMNS):
                col_target = m1 if idx % 2 == 0 else m2

                # 1. Vérification si un mapping mémorisé existe pour ce champ
                default_match = learned_mapping.get(req_col)

                # 2. Sinon, recherche par alias
                if not default_match:
                    if req_col in csv_cols:
                        default_match = req_col
                    else:
                        aliases = COLUMN_ALIASES.get(req_col, [])
                        for c in csv_cols:
                            c_clean = str(c).strip().lower()
                            if c_clean in aliases or any(alias == c_clean for alias in aliases):
                                default_match = c
                                break

                col_mapping[req_col] = col_target.selectbox(
                    f"Champ Sanctuary : **{req_col}**",
                    options=["-- Ignorer --"] + csv_cols,
                    index=csv_cols.index(default_match) + 1 if default_match and default_match in csv_cols else 0,
                    key=f"map_{default_net}_{req_col}"
                )

            # Nettoyage des ignorés
            active_mapping = {k: v for k, v in col_mapping.items() if v != "-- Ignorer --"}

            st.divider()
            filter_imp_year = st.checkbox(f"Ne sanctuariser que les transactions de l'Année Cible ({imp_year})", value=True)

            # Mémorisation automatique de l'empreinte et de la grille de récolte pour la prochaine fois
            if default_net and csv_cols:
                save_custom_csv_signature(default_net, csv_cols)
                if active_mapping:
                    save_platform_column_mapping(default_net, active_mapping)

            if st.button("💾 Valider et Sanctuariser l'Importation"):
                df_mapped = map_csv_to_sanctuary(uploaded_file, active_mapping, default_network=default_net)
                if df_mapped.empty:
                    st.error("Erreur lors du traitement du fichier CSV.")
                else:
                    if filter_imp_year:
                        df_mapped["_temp_yr"] = smart_parse_dates(df_mapped["Date de la transaction"]).dt.year
                        df_mapped = df_mapped[df_mapped["_temp_yr"] == int(imp_year)].drop(columns=["_temp_yr"])

                    if df_mapped.empty:
                        st.warning(f"Aucune transaction trouvée dans le CSV pour l'année {imp_year}.")
                    else:
                        # Si filter_imp_year=True, on force l'enregistrement exact dans sanctuary/{imp_year}/{imp_account}.csv
                        auto_disp_csv = not filter_imp_year
                        saved_paths = save_to_sanctuary(df_mapped, int(imp_year), imp_account, auto_dispatch_year=auto_disp_csv)
                        st.success(f"✅ {len(df_mapped)} transactions sanctuarisées au total sur {len(saved_paths)} dossier(s) d'année !")
                        for p in saved_paths:
                            if p.exists():
                                try:
                                    cnt_df = pd.read_csv(p, encoding="utf-8-sig")
                                    st.write(f"- `{p}` ({len(cnt_df)} transactions sanctuarisées)")
                                except Exception:
                                    st.write(f"- `{p}`")
                            else:
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
        year_options_view = ["🌐 Toutes les années (Multi-années)"] + available_years
        sel_year = st.selectbox("Sélectionner l'Année", year_options_view)

        if sel_year == "🌐 Toutes les années (Multi-années)":
            accounts = list_all_accounts_all_years()
        else:
            accounts = list_accounts_for_year(int(sel_year))

        c1, c2 = st.columns([1, 3])
        view_mode = c1.radio("Mode d'affichage", ["Compte Spécifique", "Consolidation Globale"])

        if view_mode == "Compte Spécifique" and accounts:
            sel_acc = c1.selectbox("Sélectionner le Compte", accounts)
            if sel_year == "🌐 Toutes les années (Multi-années)":
                df_view = load_account_all_years(sel_acc)
                st.subheader(f"📄 Historique multi-années : `{sel_acc}` ({len(df_view)} lignes)")
            else:
                df_view = load_sanctuary_account(int(sel_year), sel_acc)
                st.subheader(f"📄 Fichier : `sanctuary/{sel_year}/{sel_acc}.csv` ({len(df_view)} lignes)")
            st.dataframe(df_view, use_container_width=True)
        else:
            if sel_year == "🌐 Toutes les années (Multi-années)":
                df_view = load_all_sanctuary_all_years()
                st.subheader(f"🌐 Consolidation Globale Multi-Années ({len(df_view)} transactions réunies)")
            else:
                df_view = load_all_sanctuary_for_year(int(sel_year))
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

        is_custom_period = p_type == "Personnalisée"

        p_quarter = None
        p_month = None
        p_start = None
        p_end = None

        if is_custom_period:
            p_col2.text_input(
                "Année Fiscale",
                value="🚫 Neutralisée (Multi-années)",
                disabled=True,
                help="En mode Période Personnalisée, l'année fiscale est neutralisée pour analyser l'intégralité des transactions sur la plage choisie."
            )
            p_year_selected = "🌐 Toutes les années (Multi-années)"
            is_all_years = True
            ref_yr = None

            min_yr = available_years[-1] if available_years else 2020
            max_yr = available_years[0] if available_years else 2026
            p_start = p_col3.date_input("Date Début", date(min_yr, 1, 1))
            p_end = p_col4.date_input("Date Fin", date(max_yr, 12, 31))

            st.success(
                f"✅ **Validation Période Personnalisée Multi-Années** : Traitement actif du **{p_start.strftime('%d/%m/%Y')}** au **{p_end.strftime('%d/%m/%Y')}** sur l'intégralité du sanctuaire."
            )
        else:
            year_filter_options = ["🌐 Toutes les années (Multi-années)"] + available_years
            p_year_selected = p_col2.selectbox("Année Fiscale de référence", year_filter_options, index=1 if len(year_filter_options) > 1 else 0)

            is_all_years = "Toutes les années" in str(p_year_selected)

            if p_type == "Trimestre":
                p_quarter = p_col3.selectbox("Trimestre", ["Q1", "Q2", "Q3", "Q4"])
            elif p_type == "Mois":
                p_month = p_col3.selectbox("Mois", list(range(1, 13)), format_func=lambda x: f"Mois {x}")

        if is_all_years:
            df_year_all = load_all_sanctuary_all_years()
            ref_yr = None
        else:
            ref_yr = int(p_year_selected)
            df_year_all = load_all_sanctuary_for_year(ref_yr)

        df_filtered_global = filter_by_period(df_year_all, p_type, year=ref_yr, quarter=p_quarter, month=p_month, start_date=p_start, end_date=p_end)

        st.divider()

        tab_level_a, tab_level_b = st.tabs([
            "📌 Niveau A : Totalisation par Compte",
            "🌐 Niveau B : Totalisation Globale / Consolidée"
        ])

        # --- NIVEAU A : COMPTE INDIVIDUEL ---
        with tab_level_a:
            st.subheader("📌 Niveau A — Totalisation par Compte Individuel")

            if is_all_years:
                accounts = list_all_accounts_all_years()
            else:
                accounts = list_accounts_for_year(ref_yr)

            if not accounts:
                st.info("Aucun compte trouvé pour cette sélection.")
            else:
                sel_account_a = st.selectbox("Choisir le Compte à Analyser", accounts, key="sel_a")

                if is_all_years:
                    df_acc_raw = load_account_all_years(sel_account_a)
                else:
                    df_acc_raw = load_sanctuary_account(ref_yr, sel_account_a)

                df_acc_filtered = filter_by_period(df_acc_raw, p_type, year=ref_yr, quarter=p_quarter, month=p_month, start_date=p_start, end_date=p_end)

                tot_a = totalize_level_a(df_acc_filtered)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Capital Net Apporté (EUR)", f"{tot_a['net_capital_eur']:,.2f} €", help="Dépôts / Rendements (- Retraits)")
                m2.metric("Dépôts & Rendements (EUR)", f"{tot_a['deposits_eur']:,.2f} €")
                m3.metric("Retraits de Capital (EUR)", f"{tot_a['withdrawals_eur']:,.2f} €")
                m4.metric("Volume Interne de Trades (EUR)", f"{tot_a['trades_eur']:,.2f} €", help="Volume d'échanges/swaps internes neutralisé sur le capital")

                st.subheader("Ventilation par Devise d'Origine")
                st.dataframe(tot_a["by_currency"], use_container_width=True)

                st.subheader("Ventilation par Type de Transaction")
                st.dataframe(tot_a["by_type"], use_container_width=True)

        # --- NIVEAU B : GLOBALISATION MULTI-COMPTES ---
        with tab_level_b:
            st.subheader("🌐 Niveau B — Totalisation Globale Consolidée (Multi-Comptes)")

            tot_b = totalize_level_b(df_filtered_global)

            g1, g2, g3, g4 = st.columns(4)
            g1.metric("Capital Net Apporté Consolidé (EUR)", f"{tot_b['net_capital_eur']:,.2f} €")
            g2.metric("Total Dépôts & Rendements (EUR)", f"{tot_b['deposits_eur']:,.2f} €")
            g3.metric("Total Retraits (EUR)", f"{tot_b['withdrawals_eur']:,.2f} €")
            g4.metric("Volume Consolidé des Trades (EUR)", f"{tot_b['trades_eur']:,.2f} €")

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
