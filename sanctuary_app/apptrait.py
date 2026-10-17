"""
Application Streamlit : apptrait.py
Application complémentaire de qualification de légitimité, filtrage anti-spam et valorisation des soldes.
"""
import sys
import os
from pathlib import Path

# Desactivation des bytecodes .pyc
sys.dont_write_bytecode = True

# Résolution des chemins de packages
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

for path_obj in [ROOT_DIR, APP_DIR]:
    p_str = str(path_obj)
    if p_str in sys.path:
        sys.path.remove(p_str)
    sys.path.insert(0, p_str)

import streamlit as st
import pandas as pd
from datetime import datetime, date

# Imports de modules
try:
    from sanctuary_app.modules.trait_manager import (
        sync_sanctuary_to_trait_legit,
        load_all_trait_legit,
        load_legit_config,
        save_legit_config,
        calculate_token_balances,
        evaluate_balances_at_date,
        DEFAULT_WHITELIST
    )
    from sanctuary_app.modules.analytics_engine import filter_by_period
except ImportError:
    from modules.trait_manager import (
        sync_sanctuary_to_trait_legit,
        load_all_trait_legit,
        load_legit_config,
        save_legit_config,
        calculate_token_balances,
        evaluate_balances_at_date,
        DEFAULT_WHITELIST
    )
    from modules.analytics_engine import filter_by_period

# Configuration Page Streamlit
st.set_page_config(page_title="AppTrait — Qualification & Légitimité", layout="wide", page_icon="🛡️")

st.title("🛡️ AppTrait — Qualification de Légitimité & Valorisation")
st.caption("Application complémentaire : Isolation dans `trait_legit/`, filtrage anti-spam et valorisation des soldes à date choisie.")

SANCTUARY_DIR = ROOT_DIR / "sanctuary"
TRAIT_DIR = ROOT_DIR / "trait_legit"

# Sidebar Navigation
st.sidebar.title("Navigation AppTrait")
menu = st.sidebar.radio(
    "Menu principal",
    [
        "📂 1. Duplication & Synchronisation",
        "🛡️ 2. Centre de Qualification & Anti-Spam",
        "📊 3. Soldes par Portefeuille & Période",
        "💶 4. Valorisation du Patrimoine à Date Choisie"
    ]
)

# Configuration globale Anti-Spam dans Sidebar
st.sidebar.divider()
st.sidebar.subheader("⚙️ Filtre Anti-Spam Global")
exclude_spam_global = st.sidebar.checkbox("Exclure le Spam & Suspects (Actif)", value=True, help="Lorsque cette case est cochée, toutes les consultations, calculs et valorisations ignorent les éléments qualifiés de Spam ou Suspects.")

# --- MENU 1 : DUPLICATION & SYNCHRONISATION ---
if menu == "📂 1. Duplication & Synchronisation":
    st.header("📂 Duplication Sécurisée du Sanctuaire vers `trait_legit/`")
    st.info(
        "Afin de garantir l'inviolabilité absolue des données brutes sanctuarisées (`sanctuary/`), "
        "`apptrait.py` duplique et travaille exclusivement dans le dossier dédié `trait_legit/`."
    )

    col1, col2 = st.columns(2)
    col1.metric("Dossier Source Sanctuaire", str(SANCTUARY_DIR.name))
    col2.metric("Dossier de Travail Qualifié", str(TRAIT_DIR.name))

    st.divider()
    if st.button("🚀 Lancer la Synchronisation & Duplication (Sanctuary -> Trait Legit)"):
        with st.spinner("Duplication et qualification automatique en cours..."):
            saved = sync_sanctuary_to_trait_legit(SANCTUARY_DIR, TRAIT_DIR)

        if not saved:
            st.warning("Aucun fichier à dupliquer trouvé dans `sanctuary/`.")
        else:
            st.success(f"✅ {len(saved)} fichier(s) dupliqué(s) et qualifié(s) dans `trait_legit/` avec succès !")
            for p in saved:
                st.write(f"- `{p}`")

    st.divider()
    st.subheader("📄 Aperçu du Dossier `trait_legit/`")
    df_preview = load_all_trait_legit(TRAIT_DIR, exclude_spam=False)
    if df_preview.empty:
        st.info("Le dossier `trait_legit/` est vide. Veuillez lancer une synchronisation.")
    else:
        st.write(f"**Total enregistrements dans `trait_legit/`** : {len(df_preview)} lignes")
        st.dataframe(df_preview, use_container_width=True)


# --- MENU 2 : CENTRE DE QUALIFICATION & ANTI-SPAM ---
elif menu == "🛡️ 2. Centre de Qualification & Anti-Spam":
    st.header("🛡️ Centre de Qualification & Gestion de la Légitimité")

    config = load_legit_config(TRAIT_DIR)

    tab_wl, tab_audit = st.tabs([
        "⚙️ Gestion Whitelist & Blacklist",
        "🔍 Audit Interactif & Surcharges Manuel"
    ])

    # TAB 1 : WHITELIST / BLACKLIST
    with tab_wl:
        st.subheader("📋 Listes de Référence Globales")
        col_w, col_b = st.columns(2)

        with col_w:
            st.write("### 🟢 Liste Blanche (Whitelist Tokens)")
            wl_text = st.text_area("Tokens Valides (séparés par une virgule)", value=", ".join(config.get("whitelist", DEFAULT_WHITELIST)))
            if st.button("💾 Enregistrer & Appliquer la Whitelist"):
                new_wl = [t.strip().upper() for t in wl_text.split(",") if t.strip()]
                config["whitelist"] = new_wl
                save_legit_config(TRAIT_DIR, config)
                saved = sync_sanctuary_to_trait_legit(SANCTUARY_DIR, TRAIT_DIR, force_requalify=True)
                st.success(f"✅ Whitelist enregistrée et appliquée à {len(saved)} fichier(s) qualifié(s) !")

        with col_b:
            st.write("### 🔴 Liste Noire (Blacklist / Banni)")
            bl_text = st.text_area("Tokens / Projets Bannis (séparés par une virgule)", value=", ".join(config.get("blacklist", [])))
            if st.button("💾 Enregistrer & Appliquer la Blacklist"):
                new_bl = [t.strip().upper() for t in bl_text.split(",") if t.strip()]
                config["blacklist"] = new_bl
                save_legit_config(TRAIT_DIR, config)
                saved = sync_sanctuary_to_trait_legit(SANCTUARY_DIR, TRAIT_DIR, force_requalify=True)
                st.success(f"✅ Blacklist enregistrée et appliquée à {len(saved)} fichier(s) qualifié(s) !")

    # TAB 2 : AUDIT INTERACTIF
    with tab_audit:
        st.subheader("🔍 Audit du Journal des Transactions")
        df_all = load_all_trait_legit(TRAIT_DIR, exclude_spam=False)

        if df_all.empty:
            st.warning("Aucune donnée dans `trait_legit/`. Veuillez lancer la synchronisation au Menu 1.")
        else:
            filter_status = st.radio("Afficher :", ["Tous", "Valides Uniquement", "Spams / Suspects Uniquement"], horizontal=True)

            if filter_status == "Valides Uniquement":
                df_view = df_all[df_all["Statut_Legitimite"] == "Valide"]
            elif filter_status == "Spams / Suspects Uniquement":
                df_view = df_all[df_all["Statut_Legitimite"] == "Spam / Suspect"]
            else:
                df_view = df_all

            st.dataframe(df_view, use_container_width=True)

            st.divider()
            st.subheader("✍️ Surcharge Manuelle d'un Token ou d'une Transaction")
            c1, c2, c3 = st.columns(3)

            override_key = c1.text_input("Symbole Token OU Hash Transaction 0x...", placeholder="ex: ARB ou 0x123...")
            override_action = c2.selectbox("Action Manuelle", ["Marquer comme VALIDE (Autoriser)", "Marquer comme SPAM (Bannir)"])

            if c3.button("⚡ Appliquer la Surcharge"):
                if not override_key:
                    st.error("Veuillez saisir un symbole de token ou un hash.")
                else:
                    target_key = override_key.strip()
                    is_val = "VALIDE" in override_action
                    config["manual_overrides"][target_key] = is_val
                    save_legit_config(TRAIT_DIR, config)

                    # Re-qualification instantanée
                    sync_sanctuary_to_trait_legit(SANCTUARY_DIR, TRAIT_DIR)
                    st.success(f"✅ Surcharge enregistrée pour '{target_key}' ! Le statut a été mis à jour dans `trait_legit/`.")


# --- MENU 3 : SOLDES PAR PORTEFEUILLE & PÉRIODE ---
elif menu == "📊 3. Soldes par Portefeuille & Période":
    st.header("📊 Totalisation des Soldes Nets par Portefeuille & par Période")

    df_full = load_all_trait_legit(TRAIT_DIR, exclude_spam=exclude_spam_global)

    if df_full.empty:
        st.warning("Aucune transaction disponible dans `trait_legit/`.")
    else:
        st.subheader("⚙️ Configuration de la Période")
        p1, p2, p3, p4 = st.columns(4)

        p_type = p1.selectbox("Type de Période", ["Toutes les années", "Année Fiscale", "Trimestre", "Mois", "Personnalisée"])

        p_year = None
        p_quarter = None
        p_month = None
        p_start = None
        p_end = None

        if p_type == "Année Fiscale":
            p_year = p2.selectbox("Année Fiscale", options=[2026, 2025, 2024, 2023, 2022], index=1)
        elif p_type == "Trimestre":
            p_year = p2.selectbox("Année Fiscale", options=[2026, 2025, 2024, 2023, 2022], index=1)
            p_quarter = p3.selectbox("Trimestre", ["Q1", "Q2", "Q3", "Q4"])
        elif p_type == "Mois":
            p_year = p2.selectbox("Année Fiscale", options=[2026, 2025, 2024, 2023, 2022], index=1)
            p_month = p3.selectbox("Mois", list(range(1, 13)))
        elif p_type == "Personnalisée":
            p2.text_input("Année Fiscale", value="🚫 Neutralisée (Multi-années)", disabled=True)
            p_start = p3.date_input("Date Début", date(2020, 1, 1))
            p_end = p4.date_input("Date Fin", date(2026, 12, 31))

        df_filtered = filter_by_period(
            df_full,
            period_type="Année" if p_type == "Année Fiscale" else p_type,
            year=p_year,
            quarter=p_quarter,
            month=p_month,
            start_date=p_start,
            end_date=p_end
        )

        st.divider()
        st.subheader(f"📊 Tableau des Soldes Nets ({'Anti-Spam Actif' if exclude_spam_global else 'Inclus Tout'})")

        df_balances = calculate_token_balances(df_filtered)
        st.dataframe(df_balances, use_container_width=True)


# --- MENU 4 : VALORISATION DU PATRIMOINE À DATE CHOISIE ---
elif menu == "💶 4. Valorisation du Patrimoine à Date Choisie":
    st.header("💶 Valorisation Ré-évaluée du Patrimoine Qualifié en Euros")
    st.info(
        "Ce module calcule le solde net qualifié de vos jetons et ré-évalue l'intégralité du portefeuille "
        "au cours exact de la **Date d'Évaluation ($T_{eval}$)** choisie (taux officiel BCE + cours crypto au jour $T_{eval}$)."
    )

    df_full = load_all_trait_legit(TRAIT_DIR, exclude_spam=exclude_spam_global)

    if df_full.empty:
        st.warning("Aucune transaction disponible dans `trait_legit/`.")
    else:
        v_col1, v_col2 = st.columns([1, 2])
        eval_date = v_col1.date_input("Date d'Évaluation (T_eval)", value=date.today())

        # Calcul des soldes nets qualifiés arrêtés à eval_date
        df_until_date = filter_by_period(df_full, period_type="Personnalisée", start_date=date(2015, 1, 1), end_date=eval_date)
        df_balances = calculate_token_balances(df_until_date)

        if st.button("🚀 Calculer la Valorisation en Euros au " + eval_date.strftime("%d/%m/%Y")):
            with st.spinner("Récupération des cours BCE et DefiLlama pour la date sélectionnée..."):
                df_val = evaluate_balances_at_date(df_balances, eval_date)

            total_patrimoine_eur = df_val["Valeur_Totale_EUR"].sum()

            m1, m2 = st.columns(2)
            m1.metric(f"Date de Consultation (T_eval)", eval_date.strftime("%d/%m/%Y"))
            m2.metric("Valeur Totale du Patrimoine Qualifié (EUR)", f"{total_patrimoine_eur:,.2f} €")

            st.divider()
            st.subheader(f"📋 Détail de Valorisation par Portefeuille et Token (au {eval_date.strftime('%d/%m/%Y')})")
            st.dataframe(df_val, use_container_width=True)
