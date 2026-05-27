import os
import time
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic as sl

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Contrôle & VGP (appPropri)", layout="wide")

st.title("👤 Contrôle & Valeur Globale (VGP)")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")

    # Access Unified Processing Year from Hub
    target_year = st.session_state.get("_hub_target_year")
    if target_year is None:
        g_conf = sl.load_global_config()
        target_year = g_conf.get("processing_year") or datetime.now().year
        st.session_state["_hub_target_year"] = target_year

    st.write(f"📅 Année active : **{target_year}**")

    # Target Date for Valuation (Calculateur à la demande)
    st.divider()
    st.subheader("📅 Calculateur VGP à la demande")
    val_date_type = st.radio("Cible de contrôle", ["Fin d'année (31/12)", "Date libre (Audit)"])

    if val_date_type == "Fin d'année (31/12)":
        target_date = datetime(target_year, 12, 31)
    else:
        target_date = st.date_input("Saisir une date", datetime(target_year, 6, 30))
        target_date = datetime.combine(target_date, datetime.max.time())

    st.divider()
    if st.button("🔄 Actualiser les données", width='stretch'):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    sl.show_status()

# --- Logic: Core Engine ---

@st.cache_data
def get_cessions_summary(year, journal_df_json):
    """Calculates VGP for all unique cession dates found in the journal."""
    df_j = pd.read_json(journal_df_json)
    if df_j.empty: return pd.DataFrame()

    # Identify Cessions: Outflows, not EUR
    mask_cess = (df_j["Amount"] < 0) & (df_j["Asset"].str.upper() != "EUR")
    cess_dates = sorted(df_j[mask_cess]["Date"].dt.date.unique(), reverse=True)

    # Add EOY
    eoy_d = datetime(year, 12, 31).date()
    all_dates = sorted(list(set(list(cess_dates) + [eoy_d])), reverse=True)

    summary_data = []
    for d in all_dates:
        dt_obj = datetime.combine(d, datetime.max.time())
        # We pass df_j directly to avoid disk reload
        snap_res = sl.get_portfolio_snapshot(year, dt_obj, df_override=df_j)
        vgp_val = snap_res[1] if isinstance(snap_res, tuple) else 0.0

        summary_data.append({
            "Date": d,
            "Événement": "🏁 Fin d'année" if d == eoy_d else "📉 Cession",
            "VGP (€)": vgp_val
        })
    return pd.DataFrame(summary_data)

@st.cache_data
def get_unified_inventory(year, t_date):
    """Calculates inventory by Asset and Location (Wallet/Protocol)."""
    # ROBUST UNPACKING (Handles 2 or more return values)
    snap_res = sl.get_portfolio_snapshot(year, t_date)
    if isinstance(snap_res, tuple):
        snapshot = snap_res[0]
    else:
        snapshot = snap_res

    if snapshot.empty: return pd.DataFrame()
    res = snapshot.rename(columns={
        "Location": "Emplacement", "Solde": "Solde (QTD)",
        "In": "Total Entrées", "Out": "Total Sorties",
        "Prix (EUR)": "Prix (€)", "Valeur (EUR)": "Valeur (€)"
    })
    def clean_loc(loc):
        if loc.startswith("Account: "): return f"Portefeuille: {sl.resolve_owner_display(loc.replace('Account: ', ''))}"
        return f"Protocole: {loc}"
    res["Emplacement"] = res["Emplacement"].apply(clean_loc)
    return res

# --- Main Dashboard ---

# 0. SOMMAIRE DES CESSIONS & VGP (Calcul Automatique)
st.subheader("📈 Sommaire des Cessions & VGP")
st.info("Ce tableau liste toutes les sorties d'actifs (Cessions) et calcule la VGP à chaque date pour le rapport fiscal.")

# Load FULL journal for imposable status and cessions
j_full_path = sl.get_file_path(target_year, 'qualified_full')
if not os.path.exists(j_full_path):
    st.warning("Veuillez d'abord qualifier vos transactions dans l'étape 2.")
    df_j = pd.DataFrame()
else:
    # Optimized load
    df_j = sl.pd_read_csv_safe(j_full_path)
    df_j["Date"] = pd.to_datetime(df_j["Date"], utc=True)
    df_j["Imposable"] = df_j["Imposable"].apply(sl.is_imposable_robust)

if not df_j.empty:
    # Identify Cessions: Outflows, not EUR
    mask_cess = (df_j["Amount"] < 0) & (df_j["Asset"].str.upper() != "EUR")
    cessions = df_j[mask_cess].copy()

    if not cessions.empty:
        # Calculate VGP for each unique cession date (Optimized with Cache)
        with st.spinner("Calcul des VGP de cession..."):
            # We serialize to JSON for the cache key to avoid DataFrame hashing overhead
            # Use ISO format to avoid Pandas deprecation warning
            j_json = df_j.to_json(date_format='iso')
            df_sum = get_cessions_summary(target_year, j_json)

            # Map back to cessions for the editor
            vgp_map = df_sum.set_index("Date")["VGP (€)"].to_dict()
            cessions["VGP (€)"] = cessions["Date"].dt.date.map(vgp_map)

            # Map Comments from notes_db
            notes_db = sl.load_manual_notes()
            def get_tx_note(r): return notes_db.get(sl.get_note_key(r), "")
            cessions["Commentaire"] = cessions.apply(get_tx_note, axis=1)

            # Display the quick summary table
            st.dataframe(df_sum, column_config={"VGP (€)": st.column_config.NumberColumn(format="%.2f €")}, use_container_width=True, hide_index=True)

            st.divider()
            st.write("**Détail des qualifications :**")

            # Interactive Editor for Cessions
            ed_cess = st.data_editor(
                cessions.sort_values("Date", ascending=False),
                column_config={
                    "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm", disabled=True),
                    "Account": st.column_config.TextColumn("Compte", disabled=True),
                    "Asset": st.column_config.TextColumn("Actif", disabled=True),
                    "Amount": st.column_config.NumberColumn("Quantité", format="%.6f", disabled=True),
                    "Prix de Cession (EUR)": st.column_config.NumberColumn("Prix Cession (€)", format="%.2f €"),
                    "VGP (€)": st.column_config.NumberColumn("VGP à date (€)", format="%.2f €", disabled=True),
                    "Imposable": st.column_config.CheckboxColumn("⚖️ Imp.", help="Cochez pour qualifier cette cession en imposable."),
                    "Commentaire": st.column_config.TextColumn("📝 Commentaire", width="medium"),
                },
                disabled=["Date", "Chain", "Tx_Hash", "Type", "Method", "Account", "From", "To", "Asset", "Amount", "VGP (€)"],
                use_container_width=True,
                hide_index=True,
                key="cessions_vgp_editor"
            )

            if st.button("💾 Sauvegarder les Modifications (Cessions)", type="primary"):
                df_j.update(ed_cess)
                df_j.to_csv(j_full_path, index=False, encoding="utf-8-sig")
                clean_path = sl.get_file_path(target_year, 'qualified_clean')
                sl.apply_spam_filter(df_j, drop=True).to_csv(clean_path, index=False, encoding="utf-8-sig")

                new_notes = notes_db.copy()
                for _, r in ed_cess.iterrows():
                    key = sl.get_note_key(r)
                    if r["Commentaire"]: new_notes[key] = str(r["Commentaire"])
                    elif key in new_notes: del new_notes[key]
                sl.save_manual_notes(new_notes)

                st.success("Cessions et qualifications mises à jour.")
                st.rerun()
    else:
        st.info("Aucune cession détectée dans le journal.")

st.divider()

# 1. INVENTAIRE DÉTAILLÉ (Vue par actif par lieu)
st.subheader(f"📦 Inventaire détaillé au {target_date.strftime('%d/%m/%Y')}")
inventory = get_unified_inventory(target_year, target_date)
notes_db = sl.load_manual_notes()

if not inventory.empty:
    # Metric Summary
    mask_vgp = (inventory["Is_Circuit"] == False) & (inventory["Asset"].str.upper() != "EUR")
    total_vgp = inventory[mask_vgp]["Valeur (€)"].sum()
    total_a = sl.get_total_acquisition_value(target_year)

    c1, c2, c3 = st.columns(3)
    c1.metric("VGP Globale", f"{total_vgp:,.2f} €")
    c2.metric("Capital Investi (A)", f"{total_a:,.2f} €")
    c3.metric("Performance Latente", f"{total_vgp - total_a:,.2f} €")

    # Prep Manual Overrides
    def get_forced_bal(r):
        k = f"BAL_{target_date.strftime('%Y%m%d')}_{r['Emplacement']}_{r['Asset']}"
        return float(notes_db.get(k, r["Solde (QTD)"]))

    def get_row_note(r):
        k = f"NOTE_{target_date.strftime('%Y%m%d')}_{r['Emplacement']}_{r['Asset']}"
        return notes_db.get(k, "")

    inventory["Solde Corrigé"] = inventory.apply(get_forced_bal, axis=1)
    inventory["Commentaires"] = inventory.apply(get_row_note, axis=1)
    inventory["Valeur (€)"] = inventory["Solde Corrigé"] * inventory["Prix (€)"]

    ed_inv = st.data_editor(
        inventory,
        column_config={
            "Asset": st.column_config.TextColumn("🪙 Actif", disabled=True),
            "Emplacement": st.column_config.TextColumn("📍 Emplacement", disabled=True),
            "Solde (QTD)": st.column_config.NumberColumn("📦 Solde (Auto)", format="%.6f", disabled=True),
            "Solde Corrigé": st.column_config.NumberColumn("🛠️ Solde Réel", format="%.6f", help="Forcez le solde si besoin (Point 3)."),
            "Prix (€)": st.column_config.NumberColumn("🏷️ Prix (€)", format="%.4f €"),
            "Valeur (€)": st.column_config.NumberColumn("💰 Valeur (€)", format="%.2f €", disabled=True),
            "Commentaires": st.column_config.TextColumn("📝 Commentaire", width="medium"),
        },
        disabled=["Asset", "Emplacement", "Total Entrées", "Total Sorties", "Solde (QTD)", "Valeur (€)"],
        use_container_width=True, hide_index=True, key="unified_inv_editor"
    )

    if st.button("💾 Enregistrer l'Inventaire (Notes & Soldes)"):
        new_notes = notes_db.copy()
        dt_s = target_date.strftime("%Y%m%d")
        for _, r in ed_inv.iterrows():
            k_bal = f"BAL_{dt_s}_{r['Emplacement']}_{r['Asset']}"
            if float(r["Solde Corrigé"]) != float(r["Solde (QTD)"]): new_notes[k_bal] = str(r["Solde Corrigé"])
            elif k_bal in new_notes: del new_notes[k_bal]
            k_note = f"NOTE_{dt_s}_{r['Emplacement']}_{r['Asset']}"
            if r["Commentaires"]: new_notes[k_note] = r["Commentaires"]
            elif k_note in new_notes: del new_notes[k_note]
        sl.save_manual_notes(new_notes)
        st.success("Inventaire et soldes réels sauvegardés.")
        st.rerun()

# --- Audit Path ---
st.divider()
with st.expander("🕵️ Détail des mouvements & Qualification Imposable", expanded=False):
    st.write("Consultez l'historique et modifiez le statut **Imposable** directement ici.")

    j_full_path = sl.get_file_path(target_year, 'qualified_full')
    if not os.path.exists(j_full_path):
        st.warning("Journal FULL introuvable pour l'audit.")
        history_audit = sl.load_clean_history(target_year)
    else:
        history_audit = sl.pd_read_csv_safe(j_full_path)
        history_audit["Date"] = pd.to_datetime(history_audit["Date"], utc=True)
        history_audit["Imposable"] = history_audit["Imposable"].apply(sl.is_imposable_robust)

    if history_audit.empty:
        st.info("Aucun historique disponible.")
    else:
        f_asset_audit = st.selectbox("Filtrer par actif", ["Tous"] + sorted(list(history_audit["Asset"].unique())), key="audit_asset_filter")
        df_audit = history_audit.copy()
        if f_asset_audit != "Tous":
            df_audit = df_audit[df_audit["Asset"] == f_asset_audit]

        st.info("💡 Modifiez la colonne 'Imposable' puis cliquez sur 'Sauvegarder les Qualifications' pour mettre à jour les journaux.")

        edited_audit = st.data_editor(
            df_audit.sort_values("Date", ascending=False),
            column_config={
                "Imposable": st.column_config.CheckboxColumn("⚖️ Imposable", help="Cochez pour marquer cette transaction comme une cession imposable."),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(disabled=True),
                "Account": st.column_config.TextColumn(disabled=True),
                "Tx_Hash": st.column_config.TextColumn(disabled=True),
                "Category": st.column_config.SelectboxColumn("Catégorie", options=["", "Achat", "Vente", "Transfert", "Swap", "Revenu", "Dépense"]),
            },
            use_container_width=True,
            hide_index=True,
            key="audit_history_editor"
        )

        if st.button("💾 Sauvegarder les Qualifications", width='stretch', type="primary"):
            history_audit.update(edited_audit)
            history_audit.to_csv(j_full_path, index=False, encoding="utf-8-sig")
            clean_path = sl.get_file_path(target_year, 'qualified_clean')
            sl.apply_spam_filter(history_audit, drop=True).to_csv(clean_path, index=False, encoding="utf-8-sig")
            st.success("Journaux mis à jour (FULL & CLEAN).")
            st.rerun()

st.sidebar.divider()
st.sidebar.caption("Voie de Contrôle VGP v3.2 - appPropri")
