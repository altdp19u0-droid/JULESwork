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
def get_cessions_summary(year, df_j):
    """Calculates VGP for all unique cession dates found in the journal."""
    if df_j.empty: return pd.DataFrame()

    # Identify Cessions: STRICT Logic (Must be imposable)
    mask_cess = df_j.apply(sl.is_cession_imposable_robust, axis=1)
    cess_dates = sorted(df_j[mask_cess]["Date"].dt.date.unique(), reverse=True)

    # Add EOY
    eoy_d = datetime(year, 12, 31).date()
    all_dates = sorted(list(set(list(cess_dates) + [eoy_d])), reverse=True)

    summary_data = []
    for d in all_dates:
        dt_obj = datetime.combine(d, datetime.max.time())
        # Robust Unpacking (handles 2 return values)
        snap_res = sl.get_portfolio_snapshot(year, dt_obj, df_override=df_j)
        vgp_val = snap_res[1] if isinstance(snap_res, tuple) else 0.0

        summary_data.append({
            "Date": d,
            "Événement": "🏁 Fin d'année" if d == eoy_d else "📉 Cession Imposable",
            "VGP (€)": vgp_val
        })
    return pd.DataFrame(summary_data)

@st.cache_data
def get_unified_inventory(year, t_date):
    """Calculates inventory by Asset and Location (Wallet/Protocol)."""
    snap_res = sl.get_portfolio_snapshot(year, t_date)
    if isinstance(snap_res, tuple):
        snapshot = snap_res[0]
    else:
        snapshot = snap_res

    if snapshot.empty: return pd.DataFrame()

    res = snapshot.rename(columns={
        "Location": "Emplacement", "Solde": "Solde Actuel",
        "In": "Mvts Entrants", "Out": "Mvts Sortants",
        "Report": "Solde N-1 (Report)",
        "Prix (EUR)": "Prix (€)", "Valeur (EUR)": "Valeur (€)"
    })

    def clean_loc(loc):
        if loc.startswith("Account: "): return f"Portefeuille: {sl.resolve_owner_display(loc.replace('Account: ', ''))}"
        return f"Protocole: {loc}"
    res["Emplacement"] = res["Emplacement"].apply(clean_loc)

    # Final ordering for requested view
    cols = ["Asset", "Emplacement", "Solde N-1 (Report)", "Mvts Entrants", "Mvts Sortants", "Solde Actuel", "Prix (€)", "Valeur (€)"]
    return res[cols + [c for c in res.columns if c not in cols]]

# --- Main Dashboard ---

# 0. SOMMAIRE DES CESSIONS & VGP (Calcul Automatique)
st.subheader("📈 Sommaire des VGP Fiscales")
st.info("Ce tableau récapitule la VGP à chaque date de cession imposable (Crypto -> Fiat) qualifiée dans l'Etape 2.")

j_full_path = sl.get_file_path(target_year, 'qualified_full')
if not os.path.exists(j_full_path):
    st.warning("Veuillez d'abord qualifier vos transactions dans l'étape 2.")
    df_j = pd.DataFrame()
else:
    df_j = sl.pd_read_csv_safe(j_full_path)
    df_j["Date"] = pd.to_datetime(df_j["Date"], utc=True)
    df_j["Imposable"] = df_j["Imposable"].apply(sl.is_imposable_robust)

if not df_j.empty:
    with st.spinner("Calcul des VGP clés..."):
        df_sum = get_cessions_summary(target_year, df_j)
        if not df_sum.empty:
            st.dataframe(
                df_sum,
                column_config={"VGP (€)": st.column_config.NumberColumn(format="%.2f €")},
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Aucune cession imposable détectée pour l'année sélectionnée.")

st.divider()

# 1. INVENTAIRE DE CONTRÔLE
st.subheader(f"📦 Inventaire de Contrôle au {target_date.strftime('%d/%m/%Y')}")
inventory = get_unified_inventory(target_year, target_date)
notes_db = sl.load_manual_notes()

if not inventory.empty:
    # Calculation of Capital Investi (A) - Now filtered for Valid Assets
    total_a, df_a_details = sl.get_total_acquisition_value(target_year, return_details=True)

    # Portfolio VGP (excluding non-taxable assets like EUR)
    mask_vgp = (inventory["Asset"].str.upper() != "EUR")
    total_vgp = inventory[mask_vgp]["Valeur (€)"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("VGP Globale", f"{total_vgp:,.2f} €")
    c2.metric("Capital Investi (A)", f"{total_a:,.2f} €", help="Cumul des Euros consommés pour l'achat de jetons validés.")
    c3.metric("Performance Latente", f"{total_vgp - total_a:,.2f} €")

    st.write("**Détail des soldes par compte :**")

    # Support for manual balance correction
    def get_forced_bal(r):
        k = f"BAL_{target_date.strftime('%Y%m%d')}_{r['Emplacement']}_{r['Asset']}"
        return float(notes_db.get(k, r["Solde Actuel"]))

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
            "Emplacement": st.column_config.TextColumn("📍 Lieu", disabled=True),
            "Solde N-1 (Report)": st.column_config.NumberColumn(format="%.6f", disabled=True),
            "Mvts Entrants": st.column_config.NumberColumn(format="%.6f", disabled=True),
            "Mvts Sortants": st.column_config.NumberColumn(format="%.6f", disabled=True),
            "Solde Actuel": st.column_config.NumberColumn("📦 Solde (Calculé)", format="%.6f", disabled=True),
            "Solde Corrigé": st.column_config.NumberColumn("🛠️ Solde Réel", format="%.6f", help="Forcez le solde si le calcul automatique est incomplet."),
            "Prix (€)": st.column_config.NumberColumn(format="%.4f €"),
            "Valeur (€)": st.column_config.NumberColumn(format="%.2f €", disabled=True),
            "Commentaires": st.column_config.TextColumn("📝 Commentaire", width="medium"),
        },
        disabled=["Asset", "Emplacement", "Solde N-1 (Report)", "Mvts Entrants", "Mvts Sortants", "Solde Actuel", "Valeur (€)"],
        use_container_width=True, hide_index=True, key="unified_control_editor"
    )

    if st.button("💾 Enregistrer les Corrections & Notes"):
        new_notes = notes_db.copy()
        dt_s = target_date.strftime("%Y%m%d")
        for _, r in ed_inv.iterrows():
            k_bal = f"BAL_{dt_s}_{r['Emplacement']}_{r['Asset']}"
            if float(r["Solde Corrigé"]) != float(r["Solde Actuel"]): new_notes[k_bal] = str(r["Solde Corrigé"])
            elif k_bal in new_notes: del new_notes[k_bal]
            k_note = f"NOTE_{dt_s}_{r['Emplacement']}_{r['Asset']}"
            if r["Commentaires"]: new_notes[k_note] = r["Commentaires"]
            elif k_note in new_notes: del new_notes[k_note]
        sl.save_manual_notes(new_notes)
        st.success("Corrections sauvegardées.")
        st.rerun()

st.divider()

# --- Audit & History ---
with st.expander("🕵️ Audit des Cessions & Qualifications", expanded=False):
    st.write("Vérifiez ici le détail des transactions qualifiées comme cessions.")

    if not df_j.empty:
        # We only show outflows that are potentially cessions
        mask_out = (df_j["Amount"] < 0) & (df_j["Asset"].str.upper() != "EUR")
        df_audit = df_j[mask_out].copy()

        st.info("💡 Seules les lignes avec la case 'Imposable' cochée sont incluses dans le Sommaire VGP ci-dessus.")

        edited_audit = st.data_editor(
            df_audit.sort_values("Date", ascending=False),
            column_config={
                "Imposable": st.column_config.CheckboxColumn("⚖️ Imp.", help="Cochez pour traiter cette vente crypto->fiat fiscalement."),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(disabled=True),
                "Category": st.column_config.SelectboxColumn("Catégorie", options=["", "Achat", "Vente", "Transfert", "Swap"]),
            },
            use_container_width=True, hide_index=True, key="audit_cession_editor"
        )

        if st.button("💾 Sauvegarder les Qualifications (Audit)", type="primary"):
            df_j.update(edited_audit)
            df_j.to_csv(j_full_path, index=False, encoding="utf-8-sig")
            clean_path = sl.get_file_path(target_year, 'qualified_clean')
            sl.apply_spam_filter(df_j, drop=True).to_csv(clean_path, index=False, encoding="utf-8-sig")
            st.success("Journaux mis à jour.")
            st.rerun()

st.sidebar.divider()
st.sidebar.caption("Voie de Contrôle VGP v3.3 - appPropri")
