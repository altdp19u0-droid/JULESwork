import os
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

    # Target Date for Valuation
    st.divider()
    st.subheader("📅 Date de Valorisation")
    val_date_type = st.radio("Type de date", ["Fin d'année (31/12)", "Date de Cession (Sur mesure)"])

    if val_date_type == "Fin d'année (31/12)":
        target_date = datetime(target_year, 12, 31)
    else:
        target_date = st.date_input("Choisir une date", datetime(target_year, 6, 30))
        target_date = datetime.combine(target_date, datetime.max.time())

    st.divider()
    if st.button("🔄 Actualiser les données", width='stretch'):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    sl.show_status()

# --- Logic: Unified Inventory Engine ---

@st.cache_data
def get_unified_inventory(year, t_date):
    """
    Calculates the unified inventory as requested:
    By Asset and Location (Wallet/Protocol).
    Includes Total In, Total Out, Balance, Price, Value.
    """
    # 1. Get Snapshot from Central Logic (handles all moves, including swaps and internal)
    # sl.get_portfolio_snapshot returns: Location, Asset, Solde, In, Out, Prix (EUR), Valeur (EUR), Is_Circuit
    snapshot, _ = sl.get_portfolio_snapshot(year, t_date)

    if snapshot.empty:
        return pd.DataFrame()

    # 2. Rename for the UI requirement
    # Requirement: Asset | Location | In | Out | Solde | Prix | Valeur
    res = snapshot.rename(columns={
        "Location": "Emplacement",
        "Solde": "Solde (QTD)",
        "In": "Total Entrées",
        "Out": "Total Sorties",
        "Prix (EUR)": "Prix (€)",
        "Valeur (EUR)": "Valeur (€)"
    })

    # 3. Clean Location names for display
    def clean_loc(loc):
        if loc.startswith("Account: "):
            return f"Portefeuille: {sl.resolve_owner_display(loc.replace('Account: ', ''))}"
        return f"Protocole: {loc}"

    res["Emplacement"] = res["Emplacement"].apply(clean_loc)

    return res

# --- Main Dashboard ---

# 1. LOAD DATA
inventory = get_unified_inventory(target_year, target_date)
notes_db = sl.load_manual_notes()

# 2. METRIC: TOTAL VGP
if not inventory.empty:
    # Per Art 150 VH bis, we exclude circuits and EUR from VGP
    mask_vgp = (inventory["Is_Circuit"] == False) & (inventory["Asset"].str.upper() != "EUR")
    total_vgp = inventory[mask_vgp]["Valeur (€)"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Valeur Globale (VGP) au {target_date.strftime('%d/%m/%Y')}", f"{total_vgp:,.2f} €")

    # Capital Investi (A)
    total_a = sl.get_total_acquisition_value(target_year)
    c2.metric("Capital Investi (A)", f"{total_a:,.2f} €")

    perf = total_vgp - total_a
    c3.metric("Performance Latente", f"{perf:,.2f} €", delta=f"{perf:,.2f} €")

st.divider()

# 3. TABLE DE CONTRÔLE UNIFIÉE
st.subheader("📋 Tableau de Contrôle des Soldes & VGP")
st.info("Ce tableau regroupe tous vos actifs par emplacement. Utilisez-le pour vérifier la cohérence de vos soldes (Entrées - Sorties).")

if inventory.empty:
    st.warning("Aucun mouvement détecté pour cette période. Vérifiez vos récoltes en Step 1 et Step 2.")
else:
    # Prepare for interactive editor
    # Add Notes/Comments
    def get_note(r):
        # We use a stable key for notes at target date + location + asset
        dt_s = target_date.strftime("%Y%m%d")
        loc = r["Emplacement"]
        ast = r["Asset"]
        return notes_db.get(f"NOTE_{dt_s}_{loc}_{ast}", "")

    inventory["Commentaires"] = inventory.apply(get_note, axis=1)

    # Add "Imposable" checkbox
    def get_imposable(r):
        dt_s = target_date.strftime("%Y%m%d")
        k = f"IMP_{dt_s}_{r['Emplacement']}_{r['Asset']}"
        # Default: True if not EUR, otherwise check saved preference
        if k in notes_db:
            return notes_db[k] == "True"
        return r["Asset"].upper() != "EUR"

    inventory["Imposable"] = inventory.apply(get_imposable, axis=1)

    # Column configuration
    col_config = {
        "Asset": st.column_config.TextColumn("🪙 Actif", disabled=True),
        "Emplacement": st.column_config.TextColumn("📍 Emplacement", disabled=True),
        "Total Entrées": st.column_config.NumberColumn("➕ Entrées", format="%.6f", disabled=True),
        "Total Sorties": st.column_config.NumberColumn("➖ Sorties", format="%.6f", disabled=True),
        "Solde (QTD)": st.column_config.NumberColumn("📦 Solde (QTD)", format="%.6f", disabled=True),
        "Prix (€)": st.column_config.NumberColumn("🏷️ Prix (€)", format="%.4f €"),
        "Valeur (€)": st.column_config.NumberColumn("💰 Valeur (€)", format="%.2f €", disabled=True),
        "Commentaires": st.column_config.TextColumn("📝 Commentaires", width="large"),
        "Imposable": st.column_config.CheckboxColumn("⚖️ Imp.", help="Cochez si cet actif doit être inclus dans la VGP fiscale."),
        "Is_Circuit": None, # Hide technical col
        "Report": None
    }

    # Display Editor
    edited_inv = st.data_editor(
        inventory,
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        key="unified_inventory_editor"
    )

    # RECALCULATION & SAVE
    col_s1, col_s2 = st.columns(2)

    if col_s1.button("💾 Enregistrer les Modifications", width='stretch'):
        # 1. Update Notes & Imposable Status
        new_notes = notes_db.copy()
        dt_s = target_date.strftime("%Y%m%d")
        for _, r in edited_inv.iterrows():
            # Comments
            k_note = f"NOTE_{dt_s}_{r['Emplacement']}_{r['Asset']}"
            if r["Commentaires"]:
                new_notes[k_note] = r["Commentaires"]
            elif k_note in new_notes:
                del new_notes[k_note]

            # Imposable Status
            k_imp = f"IMP_{dt_s}_{r['Emplacement']}_{r['Asset']}"
            new_notes[k_imp] = str(r["Imposable"])

        sl.save_manual_notes(new_notes)

        # 2. Update Price Cache if price was manually edited
        cache = sl.load_price_cache()
        d_str = target_date.strftime("%d-%m-%Y")
        count_p = 0
        for _, r in edited_inv.iterrows():
            p_val = float(r["Prix (€)"])
            if p_val > 0:
                cache[f"{r['Asset']}_{d_str}"] = p_val
                count_p += 1
        sl.save_price_cache(cache)

        st.success(f"Notes et {count_p} prix enregistrés.")
        st.rerun()

    # établir le total global en euros recalculated
    new_total_vgp = edited_inv[edited_inv["Imposable"] == True]["Valeur (€)"].sum()
    st.write(f"**VGP Totale Recalculée (Base Imposable cochée) :** `{new_total_vgp:,.2f} €`")

# --- Audit Path ---
st.divider()
with st.expander("🕵️ Détail des mouvements (Audit chronologique)"):
    st.write("Consultez l'historique complet pour vérifier un solde spécifique.")
    history = sl.load_clean_history(target_year)
    if history.empty:
        st.info("Aucun historique disponible.")
    else:
        f_asset = st.selectbox("Filtrer par actif", ["Tous"] + sorted(list(history["Asset"].unique())))
        df_audit = history.copy()
        if f_asset != "Tous":
            df_audit = df_audit[df_audit["Asset"] == f_asset]
        st.dataframe(df_audit.sort_values("Date", ascending=False), use_container_width=True)

st.sidebar.divider()
st.sidebar.caption("Voie de Contrôle VGP v2.0 - appPropri")
