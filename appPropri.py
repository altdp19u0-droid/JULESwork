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
        target_year = g_conf.get("appPropri_year") or g_conf.get("processing_year") or datetime.now().year
        st.session_state["_hub_target_year"] = target_year

    st.write(f"📅 Année active : **{target_year}**")

    # Target Date for Valuation (Calculateur à la demande)
    st.divider()
    st.subheader("📅 Calculateur VGP à la demande")
    val_date_type = st.radio("Cible de contrôle", ["Fin d'année (31/12)", "Date libre (Audit)"])

    if val_date_type == "Fin d'année (31/12)":
        target_date = datetime(target_year, 12, 31, 23, 59, 59)
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
    """Calculates VGP for all unique cession transactions found in the journal for the target year."""
    if df_j.empty: return pd.DataFrame()

    # Identify Cessions: STRICT Logic (Must be imposable AND in target year)
    mask_cess = df_j.apply(sl.is_cession_imposable_robust, axis=1) & (df_j["Date"].dt.year == year)
    cess_entries = df_j[mask_cess].sort_values("Date", ascending=False)

    # Add EOY
    # Ensure tz awareness for eoy_d if df_j is tz-aware
    tz = df_j["Date"].dt.tzinfo if not df_j.empty else None
    eoy_d = datetime(year, 12, 31, 23, 59, 59, tzinfo=tz)

    snap_res_eoy = sl.get_portfolio_snapshot(year, eoy_d, df_override=df_j)
    vgp_eoy = snap_res_eoy[1] if isinstance(snap_res_eoy, tuple) else 0.0

    summary_data = [{
        "Date": eoy_d.date(),
        "Asset": "---",
        "Quantité": 0.0,
        "Événement": "🏁 Bilan Fin d'année",
        "VGP (€)": vgp_eoy
    }]

    for _, row in cess_entries.iterrows():
        # VGP at the moment of cession
        snap_res = sl.get_portfolio_snapshot(year, row["Date"], df_override=df_j)
        vgp_val = snap_res[1] if isinstance(snap_res, tuple) else 0.0

        summary_data.append({
            "Date": row["Date"].date(),
            "Asset": row["Asset"],
            "Quantité": abs(row["Amount"]),
            "Événement": "📉 Cession Imposable",
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
        "Entrées": "Mvts Entrants", "Sorties": "Mvts Sortants",
        "Report": "Solde N-1 (Report)",
        "Prix (EUR)": "Prix (€)", "Valeur (EUR)": "Valeur (€)"
    })

    def clean_loc(loc):
        if loc.startswith("Account: "): return f"Portefeuille: {sl.resolve_owner_display(loc.replace('Account: ', ''))}"
        return f"Protocole: {loc}"
    res["Emplacement"] = res["Emplacement"].apply(clean_loc)

    # Calculation of QTD (Algebraic sum of movements)
    # The user defined QTD as "Quantité d’actifs en propriété = Entrées – sorties"
    # Which corresponds to 'Solde Actuel' in our snapshot.
    # We add PMP (Prix Moyen Pondéré) = Capital / QTD.
    # But for a specific asset, we need the local acquisition base.

    # Final ordering for requested view
    cols = ["Asset", "Emplacement", "Solde N-1 (Report)", "Mvts Entrants", "Mvts Sortants", "Solde Actuel", "Prix (€)", "Valeur (€)"]
    res = res[cols + [c for c in res.columns if c not in cols]]
    res = res.rename(columns={"Solde Actuel": "QTD (Quantité)"})
    return res

# --- Main Dashboard ---

t_dashboard, t_caisse, t_acq, t_audit = st.tabs([
    "📊 Dashboard VGP",
    "📅 Journal de Caisse Fiscal",
    "💰 Historique Acquisitions",
    "🕵️ Audit Cessions"
])

# GATEWAY: Consommer la totalité des mouvements qualifiés (FULL) pour l'audit et le calcul VGP
# On charge l'historique complet pour garantir que les soldes sont exacts
df_j = sl.load_clean_history(target_year)
if not df_j.empty:
    df_j["Imposable"] = df_j["Imposable"].apply(sl.is_imposable_robust)

with t_dashboard:
    # 0. SOMMAIRE DES CESSIONS & VGP (Calcul Automatique)
    st.subheader("📈 Sommaire des VGP Fiscales")
    st.info("Ce tableau récapitule la VGP à chaque date de cession imposable (Crypto -> Fiat) qualifiée dans l'Etape 2.")

    if not df_j.empty:
        with st.spinner("Calcul des VGP clés..."):
            df_sum = get_cessions_summary(target_year, df_j)
            if not df_sum.empty:
                st.dataframe(
                    df_sum,
                    column_config={"VGP (€)": st.column_config.NumberColumn(format="%.2f €")},
                    width='stretch', hide_index=True
                )
            else:
                st.info("Aucune cession imposable détectée pour l'année sélectionnée.")
    else:
        st.warning("Veuillez d'abord qualifier vos transactions dans l'étape 2.")

    st.divider()

    # 1. INVENTAIRE DE CONTRÔLE
    st.subheader(f"📦 Inventaire de Contrôle au {target_date.strftime('%d/%m/%Y')}")
    inventory = get_unified_inventory(target_year, target_date)
    notes_db = sl.load_manual_notes()

    if not inventory.empty:
        # Calculation of Capital Investi (A) - Now filtered for Valid Assets and date
        total_a, df_a_details = sl.get_total_acquisition_value(target_year, return_details=True, until_date=target_date)

        # Portfolio VGP (Market Value) - Per Art. 150 VH bis, excludes EUR.
        # But we must ensure it includes ALL property accounts (already handled by sl.get_portfolio_snapshot)
        mask_vgp = (inventory["Asset"].str.upper() != "EUR")
        total_vgp = inventory[mask_vgp]["Valeur (€)"].sum()

        # Global PMP = VGP / QTD (Weighted average of the whole portfolio)
        # However, summing QTD across different assets isn't always meaningful.
        # But we can provide the VGP/Capital ratio.

        c1, c2, c3 = st.columns(3)
        c1.metric("Valeur de Marché (VGP)", f"{total_vgp:,.2f} €", help="Valeur totale du portefeuille aux cours du jour (Art. 150 VH bis).")
        c2.metric("Capital Global Investi (A)", f"{total_a:,.2f} €", help="Cumul des Euros investis pour l'achat d'actifs numériques.")

        # Performance Indicators
        perf_abs = total_vgp - total_a
        pmp_global = total_a / total_vgp if total_vgp > 0 else 0.0
        c3.metric("Performance Latente", f"{perf_abs:,.2f} €", delta=f"{pmp_global:.2%}" if total_vgp > 0 else None, help="Delta entre Valeur de Marché et Capital Investi.")

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
                "QTD (Quantité)": st.column_config.NumberColumn("📦 QTD (Calculée)", format="%.6f", disabled=True),
                "Solde Corrigé": st.column_config.NumberColumn("🛠️ QTD Réelle", format="%.6f", help="Forcez le solde si le calcul automatique est incomplet."),
                "Prix (€)": st.column_config.NumberColumn(format="%.4f €"),
                "Valeur (€)": st.column_config.NumberColumn(format="%.2f €", disabled=True),
                "Commentaires": st.column_config.TextColumn("📝 Commentaire", width="medium"),
            },
            disabled=["Asset", "Emplacement", "Solde N-1 (Report)", "Mvts Entrants", "Mvts Sortants", "QTD (Quantité)", "Valeur (€)"],
            width='stretch', hide_index=True, key="unified_control_editor"
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

with t_caisse:
    st.subheader(f"📅 Journal de Caisse Fiscal ({target_year})")
    st.info("Suivi quotidien des flux valorisés par catégorie (Acquisitions, Cessions, Intérêts, Bonus).")

    if not df_j.empty:
        # Preparation of Daily Data
        df_c = df_j.copy()
        df_c["Date_Day"] = df_c["Date"].dt.date

        # 1. Acquisitions (Fiat/Way 3 marked as Acquisition)
        mask_acq = df_c["Category"].str.contains("Achat|Capital", case=False, na=False) | df_c.get("Acquisition", False)

        # 2. Cessions
        mask_cess = df_c.apply(sl.is_cession_imposable_robust, axis=1)

        # 3. Intérêts
        mask_int = df_c["Category"].str.contains("Intérêt|Revenu", case=False, na=False)

        # 4. Bonus
        mask_bon = df_c["Category"].str.contains("Bonus", case=False, na=False)

        # Helper for EUR valuation
        def get_eur_val(r):
            if "Prix de Cession (EUR)" in r and float(r["Prix de Cession (EUR)"]) > 0:
                return float(r["Prix de Cession (EUR)"])
            v_usd = float(r.get("Valeur $", 0.0))
            if v_usd > 0: return v_usd * sl.get_fiat_rate("USD", r["Date"])
            return abs(float(r["Amount"])) * sl.get_price_eur(r["Asset"], r["Date"])

        # Create Category Flags for grouping
        df_c["Val_EUR"] = df_c.apply(get_eur_val, axis=1)
        df_c["Cat_Type"] = "Autre"
        df_c.loc[mask_acq, "Cat_Type"] = "Acquisition"
        df_c.loc[mask_cess, "Cat_Type"] = "Cession"
        df_c.loc[mask_int, "Cat_Type"] = "Intérêt"
        df_c.loc[mask_bon, "Cat_Type"] = "Bonus"

        # Aggregate daily
        daily_agg = df_c[df_c["Cat_Type"] != "Autre"].groupby(["Date_Day", "Cat_Type"])["Val_EUR"].sum().unstack(fill_value=0.0).reset_index()

        # Ensure all columns exist
        for c in ["Acquisition", "Cession", "Intérêt", "Bonus"]:
            if c not in daily_agg.columns: daily_agg[c] = 0.0

        # Sort by date for cumulative calculations
        daily_agg = daily_agg.sort_values("Date_Day")

        # Daily VGP and QTD (Simulated by Snapshot at End of Day)
        # (This can be heavy, so we might want to optimize if performance is an issue)
        with st.spinner("Calcul des indicateurs quotidiens..."):
            daily_agg["VGP Globale"] = daily_agg["Date_Day"].apply(lambda d: sl.get_portfolio_snapshot(target_year, datetime.combine(d, datetime.max.time()), df_override=df_j)[1])

        # Cumulative Columns
        daily_agg["Cumul Acq."] = daily_agg["Acquisition"].cumsum()
        daily_agg["Cumul Cess."] = daily_agg["Cession"].cumsum()
        daily_agg["Cumul Int."] = daily_agg["Intérêt"].cumsum()
        daily_agg["Cumul Bon."] = daily_agg["Bonus"].cumsum()

        # Net Wealth Indicator (Acquisitions + Rewards - Consumed Capital Proxy)
        # Note: Capital A calculation is better handled by sl.calculate_fiscal_gains

        st.dataframe(
            daily_agg.sort_values("Date_Day", ascending=False),
            column_config={
                "Date_Day": "Date",
                "Acquisition": st.column_config.NumberColumn(format="%.2f €"),
                "Cession": st.column_config.NumberColumn(format="%.2f €"),
                "Intérêt": st.column_config.NumberColumn(format="%.2f €"),
                "Bonus": st.column_config.NumberColumn(format="%.2f €"),
                "VGP Globale": st.column_config.NumberColumn("VGP Marché", format="%.2f €"),
                "Cumul Acq.": st.column_config.NumberColumn("Σ Acq.", format="%.2f €"),
                "Cumul Cess.": st.column_config.NumberColumn("Σ Cess.", format="%.2f €"),
            },
            width='stretch', hide_index=True
        )

        csv_caisse = daily_agg.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("📥 Exporter Journal de Caisse (CSV)", data=csv_caisse, file_name=f"caisse_fiscale_{target_year}.csv", width='stretch')

        st.divider()
        st.subheader("📊 Bilan Annuel par Catégorie")

        # Yearly Totals
        ann_acq = daily_agg["Acquisition"].sum()
        ann_int = daily_agg["Intérêt"].sum()
        ann_bon = daily_agg["Bonus"].sum()
        ann_cess = daily_agg["Cession"].sum()

        # Calculate Report N-1 (Historical total before this year)
        hist_acq_before = sl.get_total_acquisition_value(target_year - 1)

        # Note: consumed capital needs the fiscal engine results if we want to be exact here
        # But we can show the "Gross Contribution" to Capital A for the year

        c_bil1, c_bil2, c_bil3, c_bil4 = st.columns(4)
        c_bil1.metric("Acquisitions (Fiat)", f"{ann_acq:,.2f} €")
        c_bil2.metric("Intérêts (Staking)", f"{ann_int:,.2f} €")
        c_bil3.metric("Bonus (Airdrops)", f"{ann_bon:,.2f} €")
        c_bil4.metric("Total Cessions", f"{ann_cess:,.2f} €")

        st.info(f"💡 **Note sur le Report :** Le Capital Global Investi (A) au 01/01/{target_year} était de **{hist_acq_before:,.2f} €**. "
                f"Les apports de cette année (Acq + Int + Bon = {ann_acq+ann_int+ann_bon:,.2f} €) s'y ajoutent pour former la base imposable dynamic.")

    else:
        st.warning("Aucune donnée qualifiée pour générer le journal de caisse.")

with t_acq:
    st.subheader("💵 Historique Détaillé des Acquisitions (Fiat)")
    st.info("Ce tableau affiche toutes les contributions fiat (Euros) reconnues comme prix d'acquisition.")

    total_a_tab, df_a_details_tab = sl.get_total_acquisition_value(target_year, return_details=True)

    if not df_a_details_tab.empty:
        # Standardize display
        df_disp_acq = df_a_details_tab.copy()

        # Cleanup columns for UI
        cols_to_show = ["Date", "Compte/Label", "Asset", "Quantité", "Montant EUR", "Tx Hash"]
        available_cols = [c for c in cols_to_show if c in df_disp_acq.columns]

        st.dataframe(
            df_disp_acq[available_cols].sort_values("Date", ascending=False),
            column_config={
                "Montant EUR": st.column_config.NumberColumn(format="%.2f €"),
                "Quantité": st.column_config.NumberColumn(format="%.6f"),
            },
            width='stretch', hide_index=True
        )
        st.metric("Total Capital Investi (A)", f"{total_a_tab:,.2f} €")
    else:
        st.warning("Aucune acquisition fiat détectée dans les registres manuels (App 0).")

with t_audit:
    st.subheader("🕵️ Audit des Cessions & Qualifications")
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
            width='stretch', hide_index=True, key="audit_cession_editor"
        )

        if st.button("💾 Sauvegarder les Qualifications (Audit)", type="primary"):
            # Update df_j with edits from edited_audit
            # We match on Tx Hash, Asset and Account
            j_full_path = sl.get_file_path(target_year, 'qualified_full')
            # Load full to preserve all years data if load_clean_history merged them
            df_save = sl.pd_read_csv_safe(j_full_path)
            if not df_save.empty:
                for idx, row in edited_audit.iterrows():
                    # Find corresponding row in df_save
                    mask = (df_save["Tx_Hash"] == row["Tx_Hash"]) & (df_save["Asset"] == row["Asset"]) & (df_save["Account"] == row["Account"])
                    if mask.any():
                        df_save.loc[mask, "Imposable"] = row["Imposable"]
                        df_save.loc[mask, "Category"] = row["Category"]

                df_save.to_csv(j_full_path, index=False, encoding="utf-8-sig")
                clean_path = sl.get_file_path(target_year, 'qualified_clean')
                sl.apply_spam_filter(df_save, drop=True).to_csv(clean_path, index=False, encoding="utf-8-sig")
                st.success("Journaux mis à jour.")
                st.rerun()

st.sidebar.divider()
st.sidebar.caption("Voie de Contrôle VGP v3.3 - appPropri")
