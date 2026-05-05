import os
import time
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import unicodedata
import shared_logic
from shared_logic import (
    resolve_raw_addr, get_portfolio_snapshot, get_price_eur,
    validate_spam_exclusion, load_spam_list, get_file_path,
    check_file_freshness, pd_read_csv_safe, standardize_df_addresses,
    is_imposable_robust, show_status, clean_session_state
)

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Calcul VGP Pro (app2VGP)", layout="wide")
st.title("🧮 Calculateur de VGP Historique (Version Pro)")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"
POSITIONS_FILE = "position_labels.json"

# --- Cache Engine ---
def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}



# --- Helpers ---

# --- UI sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année à traiter", min_value=2015, max_value=2030, value=datetime.now().year)

    # Year switch detection
    if "last_vgp_year" not in st.session_state:
        st.session_state.last_vgp_year = target_year

    if target_year != st.session_state.last_vgp_year:
        clean_session_state(preserve_keys=["last_vgp_year"])
        st.session_state.last_vgp_year = target_year
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.subheader("🔍 Critères de détection")
    use_imposable_col = st.checkbox("Basé sur 'Imposable'", value=True, help="Détecte les lignes marquées explicitement comme imposables dans l'App 2")
    use_category_vente = st.checkbox("Basé sur 'Vente'", value=True, help="Détecte les lignes dont la catégorie contient 'Vente'")

    st.divider()
    st.info("💡 **Mode Incrémental** : Le calcul ignore les lignes ayant déjà une VGP non nulle.")

    if st.button("🗑️ Vider le cache des prix"):
        if os.path.exists(PRICE_CACHE_FILE):
            os.remove(PRICE_CACHE_FILE)
            st.success("Cache effacé.")

    st.divider()
    if st.button("🔄 Forcer la recharge (Disque)", width='stretch', help="Relit les journaux qualifiés depuis le disque pour prendre en compte les modifs de l'App 2."):
        if "journal_active" in st.session_state: del st.session_state.journal_active
        if "active_path" in st.session_state: del st.session_state.active_path
        st.cache_data.clear()
        st.success("Données rechargées.")
        st.rerun()

    # Data Freshness Warning
    qual_path = get_file_path(target_year, 'qualified')
    if os.path.exists(qual_path):
        last_load = st.session_state.get("last_vgp_sync_time", 0)
        if check_file_freshness(qual_path, last_load):
            st.warning("⚠️ Journal qualifié mis à jour sur disque. Veuillez 'Recharger'.")

    st.divider()
    st.subheader("🛠️ Récupération d'Historique")
    force_full = st.checkbox("Recalculer tout l'historique", value=False, help="Ignore l'inventaire N-1 et recalcule depuis le début.")
    if force_full:
        start_year = st.number_input("Année de départ", 2015, 2030, 2020)
    else:
        start_year = 2020

    st.divider()
    show_status()

# --- Main logic ---
path = get_file_path(target_year, 'qualified')

if not os.path.exists(path):
    st.warning(f"📂 En attente de données : Le fichier '{os.path.basename(path)}' n'existe pas encore.")
    st.info("💡 Utilisez l'**App 2** pour synchroniser et sanctuariser vos premières données qualifiées.")
else:
    # --- Persistence Logic ---
    # We use session state to ensure UI updates after calculation
    if "journal_active" not in st.session_state or st.session_state.get("active_path") != path:
        journal = pd_read_csv_safe(path)
        # UNIFICATION
        journal = standardize_df_addresses(journal)
        journal["Date"] = pd.to_datetime(journal["Date"], utc=True, errors="coerce")

        # --- DOUBLE VÉRIFICATION SPAM À L'OUVERTURE ---
        leaked = validate_spam_exclusion(journal)
        if leaked:
            journal.loc[leaked, "Status"] = "Spam"
            st.toast(f"🛡️ Art 150 VH bis : {len(leaked)} lignes spams écartées automatiquement.")

        st.session_state.journal_active = journal
        st.session_state.active_path = path
        st.session_state.last_vgp_sync_time = time.time()

    journal = st.session_state.journal_active

    # Force numeric conversion & initialization
    for col in ["Amount", "Value ($)", "VGP (EUR)"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce").fillna(0.0)
        else:
            journal[col] = 0.0

    # Construction du masque de détection (Exclude manual duplicates and Spam)
    mask_valid = (journal["Status"] != "Spam") & (journal.get("Category", "") != "Doublon à ignorer")
    mask_imposable = (journal["Imposable"].apply(is_imposable_robust)) & mask_valid if use_imposable_col else pd.Series(False, index=journal.index)
    mask_category = (journal["Category"].fillna("").str.contains("Vente", case=False)) & mask_valid if use_category_vente else pd.Series(False, index=journal.index)

    mask_cessions = (mask_imposable | mask_category) & (journal["Asset"] != "EUR")
    cessions_all = journal[mask_cessions].copy()

    # --- Vérification d'Intégrité (Zéro Fallback) ---
    if not cessions_all.empty:
        # On vérifie si des cessions ont une VGP à 0
        missing_vgp_count = len(cessions_all[cessions_all["VGP (EUR)"] == 0])
        if missing_vgp_count > 0:
            st.error(f"🚨 **Attention :** {missing_vgp_count} cessions n'ont pas encore de VGP calculée ou validée. Les rapports fiscaux seront incomplets.")
            if st.button("🔍 Résoudre les prix manquants (AppPriceFix)", width='stretch'):
                st.info("Basculez sur l'onglet **AppPriceFix** dans le menu principal pour collecter les prix manquants.")

    if cessions_all.empty:
        st.warning("⚠️ Aucune cession imposable détectée avec les critères actuels.")
        with st.expander("👀 Diagnostic : Voir tout le journal (pour vérifier les colonnes 'Imposable' / 'Category')"):
            st.write("Vérifiez dans l'**App 2** que vos ventes sont bien marquées comme 'Imposable' ou 'Vente'.")
            st.dataframe(journal, width='stretch')
    else:
        # 1. État des lieux
        nb_total = len(cessions_all)
        # We consider missing if VGP is exactly 0.0 or NaN
        mask_manquant = (cessions_all["VGP (EUR)"].isna()) | (cessions_all["VGP (EUR)"] == 0)
        nb_manquant = len(cessions_all[mask_manquant])

        # Error check: negative VGP
        mask_error = cessions_all["VGP (EUR)"] < -1e-8
        nb_error = len(cessions_all[mask_error])

        st.subheader(f"📈 Suivi des VGP ({nb_total} cessions au total)")
        col1, col2, col3 = st.columns(3)
        col1.metric("Cessions identifiées", nb_total)

        # Real-time counter logic: we use the session state directly for the counter
        col2.metric("VGP à calculer", nb_manquant, delta=-nb_manquant, delta_color="inverse")

        col3.metric("VGP en erreur (Négatives)", nb_error, delta=nb_error, delta_color="normal" if nb_error == 0 else "inverse")

        # 2. Boutons d'action
        if nb_manquant > 0:
            with st.expander("🔍 Voir les cessions sans VGP"):
                st.write(cessions_all[mask_manquant][["Date", "Asset", "Amount"]])

            # Check for missing inventory N-1
            prev_year = target_year - 1
            inv_path = get_file_path(prev_year, 'inventory_eoy')
            if not os.path.exists(inv_path) and not force_full and target_year > 2020:
                st.error(f"🚨 **Inventaire manquant :** Le fichier `inventory_EOY_{prev_year}.csv` est introuvable.")
                st.warning("Le calcul de VGP ne sera pas exact sans point de départ sanctuarisé. Veuillez soit générer l'inventaire N-1, soit cocher 'Recalculer tout l'historique' dans la barre latérale.")

            if st.button("🚀 Lancer le calcul automatique (Incrémental)", type="primary", width='stretch'):
                pbar = st.progress(0)
                to_calc = cessions_all[cessions_all["VGP (EUR)"] <= 0]
                to_calc = to_calc.sort_values("Date", ascending=True)

                for idx, (i, row) in enumerate(to_calc.iterrows()):
                    _, vgp_val = get_portfolio_snapshot(journal, row["Date"], force_full_history=force_full, start_recalc_year=start_year)
                    journal.at[i, "VGP (EUR)"] = vgp_val
                    pbar.progress((idx + 1) / len(to_calc))

                st.session_state.journal_active = journal
                st.success("Calcul incrémental terminé.")
                st.rerun()

        # 3. Édition manuelle et Contrôle
        st.divider()
        st.subheader("📋 Liste des Cessions & Contrôle des VGP")
        st.info("Vous pouvez modifier directement les valeurs VGP dans le tableau ci-dessous.")

        # On affiche uniquement les cessions pour édition
        # Type safety pour editor
        display_cols = ["Date", "Account", "Asset", "Amount", "Value ($)", "VGP (EUR)", "Tx Hash"]
        edit_df = journal[mask_cessions][display_cols].copy()
        for c in ["Account", "Asset", "Tx Hash"]:
            edit_df[c] = edit_df[c].fillna("").astype(str)

        edited_cessions = st.data_editor(
            edit_df,
            column_config={
                "VGP (EUR)": st.column_config.NumberColumn("VGP (EUR)", format="%.2f", help="Valeur totale du portefeuille à cette date"),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
            },
            width='stretch',
            key="vgp_editor"
        )

        # Injection des modifs manuelles dans le journal principal
        if st.button("💾 Sanctuariser les VGP (Enregistrer sur disque)", width='stretch'):
            journal.loc[mask_cessions, "VGP (EUR)"] = edited_cessions["VGP (EUR)"].values
            journal.to_csv(path, index=False, encoding="utf-8-sig")
            st.success(f"Journal mis à jour avec les VGP dans {path}")
            st.balloons()

        # 4. Audit détaillé
        st.divider()
        st.subheader("🔍 Audit : Détail du Portefeuille à une Date")

        audit_options = sorted(list(cessions_all["Date"].unique()), reverse=True)
        eoy_date = datetime(target_year, 12, 31, tzinfo=audit_options[0].tzinfo if audit_options else None)
        audit_options = [eoy_date] + [d for d in audit_options if d != eoy_date]

        selected_date = st.selectbox("Choisir une date pour voir le détail", options=audit_options, format_func=lambda x: f"{x.strftime('%d/%m/%Y')} {'(🏁 Fin d’année)' if x == eoy_date else '(📈 Cession)'}")

        if selected_date:
            snapshot_df, total_val = get_portfolio_snapshot(journal, selected_date, force_full_history=force_full, start_recalc_year=start_year)
            if not snapshot_df.empty:
                st.write(f"Composition du portefeuille au **{selected_date}** :")

                # --- IDENTIFY CIRCUITS & UNLABELED ---
                circuits_df = snapshot_df[snapshot_df.get("Is_Circuit", False) == True]
                unlabeled = snapshot_df[snapshot_df["Location"].str.contains("External/CEX:", na=False)]

                if not circuits_df.empty:
                    st.info(f"ℹ️ **Circuits Externes :** {len(circuits_df)} circuits de traitement détectés (Swaps/Bridges). Leurs soldes sont exclus de la VGP fiscale.")

                if not unlabeled.empty:
                    st.warning(f"🚨 **Alerte :** {len(unlabeled)} comptes identifiés comme 'External/CEX' ont un solde non nul. "
                               "Ceci indique des transferts internes vers des comptes non récoltés (comptes propriétaires manquants).")

                    with st.expander("📋 Liste des comptes 'External/CEX' à mapper"):
                        cp_list = unlabeled["Location"].unique()
                        clean_list = [cp.replace("External/CEX: ", "").strip() for cp in cp_list]
                        st.code("\n".join(clean_list), language="text")
                        st.info("💡 Si ce sont des circuits de transit, labellez-les dans l'**App 2 (Circuits de Traitement)** pour les exclure.")

                # Highlight 0 prices
                zero_prices = snapshot_df[snapshot_df["Prix (EUR)"] == 0]
                if not zero_prices.empty:
                    st.warning(f"⚠️ {len(zero_prices)} actifs n'ont pas pu être valorisés automatiquement (Prix = 0).")

                # Interactive Editor for Audit
                # We show Is_Circuit to the user
                ed_snapshot = st.data_editor(
                    snapshot_df,
                    column_config={
                        "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                        "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                        "Solde": st.column_config.NumberColumn("Solde Final", format="%.6f", disabled=True),
                        "Report": st.column_config.NumberColumn("Report (Initial)", format="%.6f", disabled=True),
                        "Entrées": st.column_config.NumberColumn("Total Entrées", format="%.6f", disabled=True),
                        "Sorties": st.column_config.NumberColumn("Total Sorties", format="%.6f", disabled=True),
                        "Asset": st.column_config.TextColumn(disabled=True),
                        "Location": st.column_config.TextColumn(disabled=True),
                        "Is_Circuit": st.column_config.CheckboxColumn("Circuit?", disabled=True),
                    },
                    width='stretch',
                    key=f"audit_ed_{selected_date}"
                )

                # Recalculate Total with manual edits (Excluding circuits)
                ed_snapshot["Valeur (EUR)"] = ed_snapshot["Solde"] * ed_snapshot["Prix (EUR)"].fillna(0.0)
                mask_vgp_ed = (ed_snapshot["Is_Circuit"] != True)
                new_total = ed_snapshot[mask_vgp_ed]["Valeur (EUR)"].sum()
                st.metric("VGP Totale Corrigée (Excl. Circuits)", f"{new_total:,.2f} €")

                col_save_audit1, col_save_audit2 = st.columns(2)

                if col_save_audit1.button("💾 Enregistrer ces prix dans le cache"):
                    cache = shared_logic.load_price_cache()
                    d_str = selected_date.strftime("%d-%m-%Y")

                    # On identifie les prix modifiés par rapport au cache actuel
                    count = 0
                    for _, r in ed_snapshot.iterrows():
                        a_clean = unicodedata.normalize('NFKC', str(r["Asset"])).upper().strip()
                        p_val = float(r["Prix (EUR)"])
                        if p_val > 0:
                            cache[f"{a_clean}_{d_str}"] = p_val
                            count += 1

                    shared_logic.save_price_cache(cache)

                    # Sanctuarisation annuelle automatique pour pérennité
                    y = str(selected_date.year)
                    y_dir = os.path.join(EXPORT_BASE_DIR, y)
                    os.makedirs(y_dir, exist_ok=True)
                    ann_path = os.path.join(y_dir, f"verified_prices_{y}.json")

                    existing_ann = {}
                    if os.path.exists(ann_path):
                        try:
                            with open(ann_path, "r", encoding="utf-8") as f: existing_ann = json.load(f)
                        except: pass

                    # Update with new values
                    for _, r in ed_snapshot.iterrows():
                        a_clean = unicodedata.normalize('NFKC', str(r["Asset"])).upper().strip()
                        p_val = float(r["Prix (EUR)"])
                        if p_val > 0:
                            existing_ann[f"{a_clean}_{d_str}"] = p_val

                    with open(ann_path, "w", encoding="utf-8") as f:
                        json.dump(existing_ann, f, indent=4)

                    st.success(f"{count} prix enregistrés (Global & Annuel). Relancez le calcul pour rafraîchir.")

                if col_save_audit2.button("🛡️ Sanctuariser l'Inventaire", width='stretch'):
                    y_dir = os.path.join(EXPORT_BASE_DIR, str(selected_date.year))
                    os.makedirs(y_dir, exist_ok=True)

                    is_eoy = (selected_date.month == 12 and selected_date.day == 31)
                    if is_eoy:
                        inv_path = os.path.join(y_dir, f"inventory_EOY_{selected_date.year}.csv")
                        # Legacy support
                        legacy_path = os.path.join(y_dir, f"inventory_{selected_date.year}.csv")
                        ed_snapshot.to_csv(legacy_path, index=False, encoding="utf-8-sig")
                    else:
                        d_str = selected_date.strftime("%Y%m%d")
                        inv_path = os.path.join(y_dir, f"inventory_audit_{selected_date.year}_{d_str}.csv")

                    ed_snapshot.to_csv(inv_path, index=False, encoding="utf-8-sig")
                    st.success(f"Inventaire sanctuarisé : {os.path.basename(inv_path)}")
                    st.balloons()

            else:
                st.warning("Aucun historique trouvé pour cette date.")

st.sidebar.divider()
st.sidebar.caption("Calculateur VGP Pro v2.0 - app2VGP")
