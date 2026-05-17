import os
import pandas as pd
import streamlit as st
from datetime import datetime
import shared_logic as sl

# --- Configuration ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto - Propriétaires (appPropri)", layout="wide")

st.title("👤 Propriété & Patrimoine (Dashboard)")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state:
        st.session_state["_hub_target_year"] = datetime.now().year

    target_year = st.number_input("Année de consultation", min_value=2015, max_value=2030, key="_hub_target_year")

    # Year switch detection
    if "last_propri_year" not in st.session_state:
        st.session_state.last_propri_year = target_year

    if target_year != st.session_state.get("last_propri_year"):
        sl.clean_session_state(preserve_keys=["last_propri_year"])
        st.session_state.last_propri_year = target_year
        st.cache_data.clear()
        st.rerun()

    st.divider()
    nav_mode = st.radio("Navigation", ["📊 Dashboard", "⚖️ Détails Fiscaux (A & Cessions)"], key="propri_nav_v3")

    st.divider()
    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    sl.show_status()

# --- Logic: Loading and Filtering ---
@st.cache_data
def get_owner_history(year):
    """Loads consolidated clean history up to 'year' and filters for owner accounts."""
    owners_map = sl.load_owner_accounts()
    owner_addrs = set(owners_map.keys())

    # GATEWAY ARCHITECTURE: Use consolidated clean history
    combined = sl.load_clean_history(year)

    if not combined.empty:
        # Resolve owner addresses for filtering
        combined["acc_raw"] = combined["Account"].apply(sl.resolve_raw_addr)
        # Check against both technical ID and label from standard resolution
        combined = combined[combined["acc_raw"].isin(owner_addrs) | combined["Account"].isin(owners_map.values())]

            combined["Date"] = pd.to_datetime(combined["Date"], utc=True, errors="coerce")
            # --- CRITICAL FIX: Filter out rows with None dates ---
            combined = combined[combined["Date"].notna()]

            combined["_day"] = combined["Date"].dt.date
            combined["_amt"] = combined["Amount"].astype(float).round(8)
            combined["_acc"] = combined["Account"].astype(str).str.lower()
            combined["_asset"] = combined["Asset"].astype(str).str.upper()

            combined["_src_pri"] = combined["Source Type"].apply(lambda x: 0 if "Manual" not in str(x) else 1)
            combined = combined.sort_values("_src_pri").drop_duplicates(subset=["_day", "_acc", "_asset", "_amt"], keep="first")
            combined = combined.drop(columns=["_day", "_amt", "_acc", "_asset", "_src_pri", "acc_raw"])
            all_txs.append(combined)

    if not all_txs: return pd.DataFrame()
    return pd.concat(all_txs).sort_values("Date", ascending=False).reset_index(drop=True)

@st.cache_data
def get_acquisition_history(year):
    """Loads all fiat acquisitions from 2020 to 'year'."""
    all_acq = []
    for y in range(2020, year + 1):
        path = sl.get_file_path(y, 'fiat')
        if os.path.exists(path):
            try:
                df = sl.pd_read_csv_safe(path)
                if df.empty or "Date" not in df.columns or "Type" not in df.columns: continue

                # Filter for 'Achat' types (Euros moving into Crypto)
                mask = df['Type'].str.contains("Achat", case=False, na=False)
                df_acq = df[mask].copy()

                if not df_acq.empty:
                    df_acq["Date"] = pd.to_datetime(df_acq["Date"], utc=True, errors="coerce")
                    # --- CRITICAL FIX: Filter out rows with None dates ---
                    df_acq = df_acq[df_acq["Date"].notna()]
                    # Map to requested structure
                    df_acq = df_acq.rename(columns={
                        "Montant EUR": "Fiat Mobilisé (EUR)",
                        "Compte/Label": "Compte",
                        "Plateforme": "Provenance"
                    })
                    # Add requested 'Blockchain' column (default to 'Fiat/CEX')
                    if "Network" not in df_acq.columns:
                        df_acq["Blockchain"] = "Fiat/CEX"
                    else:
                        df_acq["Blockchain"] = df_acq["Network"]

                    all_acq.append(df_acq)
            except: pass

    if not all_acq: return pd.DataFrame()
    return pd.concat(all_acq).sort_values("Date", ascending=False).reset_index(drop=True)

@st.cache_data
def get_cessions_history(year):
    """Loads all imposable cessions from consolidated clean history up to 'year'."""
    # GATEWAY ARCHITECTURE: Use consolidated clean history
    combined = sl.load_clean_history(year)

    if not combined.empty:
        # Filter for cessions
        mask_cess = (combined['Imposable'].apply(sl.is_imposable_robust) |
                     combined['Category'].fillna("").str.contains("Vente", case=False)) & (combined['Asset'] != 'EUR')
        combined = combined[mask_cess].copy()

            combined["Date"] = pd.to_datetime(combined["Date"], utc=True, errors="coerce")
            # --- CRITICAL FIX: Filter out rows with None dates ---
            combined = combined[combined["Date"].notna()]

            combined["_day"] = combined["Date"].dt.date
            combined["_amt"] = combined["Amount"].astype(float).round(8)
            combined["_acc"] = combined["Account"].astype(str).str.lower()
            combined["_asset"] = combined["Asset"].astype(str).str.upper()

            # Drop duplicates keeping the one from qualified journal if possible
            # We sort such that df_q rows (which usually have more metadata) are first
            combined["_src_pri"] = combined["Source Type"].apply(lambda x: 0 if x not in ["Manual Fiat", "Manual Swap"] else 1)
            combined = combined.sort_values("_src_pri").drop_duplicates(subset=["_day", "_acc", "_asset", "_amt"], keep="first")
            combined = combined.drop(columns=["_day", "_amt", "_acc", "_asset", "_src_pri"])
            all_cessions.append(combined)

    if not all_cessions: return pd.DataFrame()
    res = pd.concat(all_cessions)
    # Final type safety
    res["Prix de Cession (EUR)"] = pd.to_numeric(res.get("Prix de Cession (EUR)", 0.0), errors="coerce").fillna(0.0)
    res["VGP (EUR)"] = pd.to_numeric(res.get("VGP (EUR)", 0.0), errors="coerce").fillna(0.0)
    return res.sort_values("Date", ascending=True).reset_index(drop=True)

@st.cache_data
def get_complementary_history(year):
    """Loads movements from manual positions and internal transfer receivables from clean history."""
    owners_map = sl.load_owner_accounts()
    owner_addrs = set(owners_map.keys())

    # GATEWAY ARCHITECTURE: Use consolidated clean history
    combined = sl.load_clean_history(year)

    all_txs = []
    if not combined.empty:
        # 1. Manual Positions (Source Type check)
        mask_m = combined["Source Type"].fillna("").str.contains("Manual Position", case=False, na=False)
        if mask_m.any():
            df_m = combined[mask_m].copy()
            df_m["Category"] = "Position Manuelle"
            all_txs.append(df_m)

        # 2. Receivables from Internal Transfers to unknown accounts
        mask_int = (combined["Category"] == "Transfert Interne")
        combined["cp_raw"] = combined["Counterparty"].apply(sl.resolve_raw_addr)
        df_receivable = combined[mask_int & (~combined["cp_raw"].isin(owner_addrs))].copy()

        if not df_receivable.empty:
            # In VGP calculation, the receivable is the negative of the leg
            df_receivable["Amount"] = -df_receivable["Amount"]
            df_receivable["Account"] = df_receivable["Counterparty"]
            df_receivable["Category"] = "Créance (Transfert Interne Sortant)"
            all_txs.append(df_receivable)

    if not all_txs: return pd.DataFrame()
    res = pd.concat(all_txs).sort_values("Date", ascending=False).reset_index(drop=True)
    return res

# --- Helpers for UI ---
def valuate_dataframe(df, cache):
    """Calculates Valeur EUR (Date) for a transaction dataframe."""
    if df.empty: return df
    df = df.copy()
    # Optimization: Group by (Asset, Date) to minimize redundant price calls
    df["Date_Only"] = df["Date"].dt.date
    unique_pairs = df[["Asset", "Date_Only"]].drop_duplicates()

    prices_map = {}
    for _, r in unique_pairs.iterrows():
        p_eur = sl.get_price_eur(r["Asset"], r["Date_Only"], cache=cache)
        prices_map[(r["Asset"], r["Date_Only"])] = p_eur

    def valuate_row(row):
        p_eur = prices_map.get((row["Asset"], row["Date_Only"]), 0.0)
        # Force sign preservation
        return float(row["Amount"]) * p_eur

    df["Valeur EUR (Date)"] = df.apply(valuate_row, axis=1)
    return df

# --- Shared Constants ---
DISPLAY_COLS = ["Date", "Account", "Asset", "Quantité Entrée", "Quantité Sortie", "Valeur EUR (Date)", "Category", "Counterparty", "Notes"]

# --- Main App ---
history = get_owner_history(target_year)
comp_history = get_complementary_history(target_year)
acq_history = get_acquisition_history(target_year)

notes_db = sl.load_manual_notes()

def apply_notes(df):
    if df.empty: return df
    df["Notes"] = df.apply(lambda r: notes_db.get(sl.get_note_key(r), ""), axis=1)
    return df

if nav_mode == "⚖️ Détails Fiscaux (A & Cessions)":
    st.subheader("⚖️ Détails des Opérations Fiscales (Art 150 VH bis)")

    t_acq, t_cess = st.tabs(["💰 Détail Acquisition (A)", "📈 Détail Cessions Imposables"])

    global_cache = sl.load_price_cache()

    with t_acq:
        if acq_history.empty:
            st.info("Aucun mouvement d'acquisition fiat détecté.")
        else:
            with st.spinner("Valorisation des acquisitions..."):
                acq_history = apply_notes(acq_history)
                acq_history["Date_Only"] = acq_history["Date"].dt.date
                unique_pairs = acq_history[["Asset", "Date_Only"]].drop_duplicates()

                prices_map = {}
                for _, r in unique_pairs.iterrows():
                    prices_map[(r["Asset"], r["Date_Only"])] = sl.get_price_eur(r["Asset"], r["Date_Only"], cache=global_cache)

                acq_history["Valeur EUR (Date)"] = acq_history.apply(
                    lambda r: float(r["Quantité"]) * prices_map.get((r["Asset"], r["Date_Only"]), 0.0), axis=1
                )

                total_a = acq_history["Fiat Mobilisé (EUR)"].sum()
                st.metric("Total Prix d'Acquisition (A)", f"{total_a:,.2f} €")

                # We pass the full dataframe to preserve hidden columns (Account, Tx Hash, Amount) for the key generator
                # But we hide them via column_config
                display_acq_cols = ["Date", "Fiat Mobilisé (EUR)", "Asset", "Quantité", "Valeur EUR (Date)", "Compte", "Blockchain", "Notes"]
                hide_cols = [c for c in acq_history.columns if c not in display_acq_cols]

                col_cfg = {
                    "Fiat Mobilisé (EUR)": st.column_config.NumberColumn(format="%.2f €"),
                    "Valeur EUR (Date)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €"),
                    "Quantité": st.column_config.NumberColumn(format="%.6f"),
                    "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="large"),
                    "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY", disabled=True),
                }
                for c in hide_cols: col_cfg[c] = None # Hide technical columns

                ed_acq = st.data_editor(
                    acq_history,
                    column_config=col_cfg,
                    width='stretch',
                    hide_index=True,
                    key="acq_history_editor"
                )

                if st.button("💾 Enregistrer les Notes (Acquisitions)", key="btn_save_notes_acq"):
                    new_notes = notes_db.copy()
                    for idx, r in ed_acq.iterrows():
                        r_proxy = r.to_dict()
                        if "Tx Hash" not in r_proxy or not r_proxy["Tx Hash"]:
                            r_proxy["Tx Hash"] = acq_history.at[idx, "Tx Hash"] if "Tx Hash" in acq_history.columns else ""
                        key = sl.get_note_key(r_proxy)
                        if r["Notes"]: new_notes[key] = str(r["Notes"])
                        elif key in new_notes: del new_notes[key]
                    sl.save_manual_notes(new_notes)
                    st.success("Notes enregistrées.")
                    st.rerun()

    with t_cess:
        cess_history = get_cessions_history(target_year)
        if cess_history.empty:
            st.info("Aucune cession imposable détectée.")
        else:
            with st.spinner("Calcul des plus-values unitaires..."):
                # VALORIZATION: ensure 'Prix de Cession (EUR)' is filled if missing (0.0)
                # This fixes the issue of zero results in calculation
                mask_no_price = (cess_history["Prix de Cession (EUR)"].fillna(0.0) == 0.0)
                if mask_no_price.any():
                    for idx, row in cess_history[mask_no_price].iterrows():
                        p_eur = sl.get_price_eur(row["Asset"], row["Date"], cache=global_cache)
                        cess_history.at[idx, "Prix de Cession (EUR)"] = abs(float(row["Amount"])) * p_eur

                cess_history = apply_notes(cess_history)
                total_acq_price = sl.get_total_acquisition_value(target_year)

                # Perform unit gain calculation
                df_results, _ = sl.calculate_fiscal_gains(cess_history, total_acq_price)

                # Warning if VGP is missing (prevents calculation)
                vgp_missing = (cess_history["VGP (EUR)"].fillna(0.0) == 0.0)
                if vgp_missing.any():
                    st.warning(f"⚠️ {vgp_missing.sum()} cession(s) n'ont pas de VGP calculée (App 2 VGP), le gain restera à 0.00.")

                # Initialize columns to avoid KeyError
                cess_history["Abattement"] = 0.0
                cess_history["Gain/Perte"] = 0.0

                # Merge results back for display
                if not df_results.empty:
                    # We merge on Date and Asset for matching
                    df_results = df_results.rename(columns={"Abattement Acq": "Abattement", "Plus-Value Brute": "Gain/Perte"})

                    # Robust Merge: use seconds-floored dates to avoid precision mismatch
                    df_results["_match_dt"] = pd.to_datetime(df_results["Date"], utc=True).dt.floor('s')
                    cess_history["_match_dt"] = pd.to_datetime(cess_history["Date"], utc=True).dt.floor('s')

                    # Merge logic: include Asset to handle multi-trades at same timestamp
                    cess_merged = pd.merge(
                        cess_history.drop(columns=["Abattement", "Gain/Perte"]),
                        df_results[["_match_dt", "Asset", "Abattement", "Gain/Perte"]],
                        on=["_match_dt", "Asset"],
                        how="left"
                    )
                    cess_history = cess_merged.drop(columns=["_match_dt"])

                # Final Fillna
                cess_history["Abattement"] = cess_history["Abattement"].fillna(0.0)
                cess_history["Gain/Perte"] = cess_history["Gain/Perte"].fillna(0.0)

                cess_history = cess_history.rename(columns={
                    "Prix de Cession (EUR)": "Montant EUR retrouvés",
                    "Asset": "Asset Vendu",
                    "Amount": "Quantité",
                    "Account": "Compte",
                    "Network": "Blockchain",
                    "Gain/Perte": "Valeur gain/perte"
                })
                # Re-sign quantity for display
                cess_history["Quantité"] = cess_history["Quantité"].apply(lambda x: abs(x))

                display_cess_cols = ["Date", "Montant EUR retrouvés", "Asset Vendu", "Quantité", "Valeur gain/perte", "VGP (EUR)", "Compte", "Blockchain", "Notes"]
                hide_cols_cess = [c for c in cess_history.columns if c not in display_cess_cols]

                col_cfg_cess = {
                    "Montant EUR retrouvés": st.column_config.NumberColumn(format="%.2f €"),
                    "Valeur gain/perte": st.column_config.NumberColumn(format="%.2f €"),
                    "VGP (EUR)": st.column_config.NumberColumn("VGP de Cession", format="%.2f €"),
                    "Quantité": st.column_config.NumberColumn(format="%.6f"),
                    "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="large"),
                    "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY", disabled=True),
                }
                for c in hide_cols_cess: col_cfg_cess[c] = None

                ed_cess = st.data_editor(
                    cess_history,
                    column_config=col_cfg_cess,
                    width='stretch',
                    hide_index=True,
                    key="cess_history_editor"
                )

                if st.button("💾 Enregistrer les Notes (Cessions)", key="btn_save_notes_cess"):
                    new_notes = notes_db.copy()
                    # We must use original technical columns for key generator
                    # Cessions are negative in journal
                    for idx, r in ed_cess.iterrows():
                        # Recover original Tx Hash if present in technical df
                        orig_h = cess_history.at[idx, "Tx Hash"] if "Tx Hash" in cess_history.columns else ""

                        proxy = {
                            "Date": r["Date"], "Account": r["Compte"], "Asset": r["Asset Vendu"],
                            "Amount": -abs(float(r["Quantité"])), "Tx Hash": orig_h
                        }
                        key = sl.get_note_key(proxy)
                        if r["Notes"]: new_notes[key] = str(r["Notes"])
                        elif key in new_notes: del new_notes[key]
                    sl.save_manual_notes(new_notes)
                    st.success("Notes enregistrées.")
                    st.rerun()

elif history.empty and comp_history.empty:
    st.warning(f"Aucune transaction trouvée pour les comptes propriétaires jusqu'en {target_year}.")
    st.info("💡 Vérifiez que vos comptes sont bien enregistrés dans la **Gestion des Comptes Propriétaires** (App 2).")
else:
    # 1. METRICS
    st.subheader("📊 Indicateurs Patrimoniaux")

    # Cumulative Acquisition Price (A)
    total_acq = sl.get_total_acquisition_value(target_year)

    # Portfolio Value (VGP) at EOY
    eoy_date = datetime(target_year, 12, 31)
    # get_portfolio_snapshot handles historical carryover
    snapshot_df, vgp_eoy = sl.get_portfolio_snapshot(target_year, eoy_date)

    c1, c2, c3 = st.columns(3)
    c1.metric("Prix d'Acquisition Total (A)", f"{total_acq:,.2f} €", help="Somme cumulée de vos apports fiat (Euros) dans l'écosystème crypto.")
    c2.metric(f"Valeur Patrimoniale (31/12/{target_year})", f"{vgp_eoy:,.2f} €", help="Valeur totale du portefeuille (VGP) à la fin de l'année.")

    perf_net = vgp_eoy - total_acq
    c3.metric("Performance Latente Globale", f"{perf_net:,.2f} €", delta=perf_net, delta_color="normal")

    # Sign Helper
    def signed_format(val):
        if pd.isna(val): return "0.00"
        return f"{val:,.2f} €" if val >= 0 else f"- {abs(val):,.2f} €"

    # 2. TABLE 1: Transactions de l'année (Comptes Propriétaires)
    st.divider()
    st.subheader(f"📑 Mouvements des Comptes Propriétaires ({target_year})")

    global_cache = sl.load_price_cache()

    # Filter for current year only
    if not history.empty:
        mask_year = history["Date"].dt.year == target_year
        df_year = history[mask_year].copy()
    else:
        df_year = pd.DataFrame()

    if df_year.empty:
        st.info(f"Aucun mouvement détecté pour les comptes propriétaires en {target_year}.")
    else:
        with st.spinner("Calcul de la valeur des mouvements propriétaires..."):
            df_year = apply_notes(df_year)
            df_year = valuate_dataframe(df_year, global_cache)

            df_year["Quantité Entrée"] = df_year["Amount"].apply(lambda x: x if x > 0 else 0.0)
            df_year["Quantité Sortie"] = df_year["Amount"].apply(lambda x: x if x < 0 else 0.0)

            hide_cols_mvt = [c for c in df_year.columns if c not in DISPLAY_COLS]
            col_cfg_mvt = {
                "Valeur EUR (Date)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f"),
                "Quantité Entrée": st.column_config.NumberColumn(format="%.6f"),
                "Quantité Sortie": st.column_config.NumberColumn(format="%.6f"),
                "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="medium"),
                "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm", disabled=True),
            }
            for c in hide_cols_mvt: col_cfg_mvt[c] = None

            ed_year = st.data_editor(
                df_year,
                column_config=col_cfg_mvt,
                width='stretch',
                hide_index=True,
                key="owner_mvt_editor"
            )

            if st.button("💾 Enregistrer les Notes (Mouvements Propriétaires)", key="btn_save_notes_owners"):
                new_notes = notes_db.copy()
                for idx, r in ed_year.iterrows():
                    # Preserve original row technical data
                    r_proxy = r.to_dict()
                    if "Tx Hash" not in r_proxy or not r_proxy["Tx Hash"]:
                        r_proxy["Tx Hash"] = df_year.at[idx, "Tx Hash"] if "Tx Hash" in df_year.columns else ""

                    key = sl.get_note_key(r_proxy)
                    if r["Notes"]: new_notes[key] = str(r["Notes"])
                    elif key in new_notes: del new_notes[key]
                sl.save_manual_notes(new_notes)
                st.success("Notes enregistrées.")
                st.rerun()

    # 2b. TABLE 1b: Mouvements Complémentaires (Positions Manuelles & Créances)
    st.subheader(f"📑 Mouvements Complémentaires - Manuels & Créances ({target_year})")
    if not comp_history.empty and "Date" in comp_history.columns:
        mask_year_comp = comp_history["Date"].dt.year == target_year
        df_year_comp = comp_history[mask_year_comp].copy()
    else:
        df_year_comp = pd.DataFrame()

    if df_year_comp.empty:
        st.info(f"Aucun mouvement complémentaire détecté en {target_year}.")
    else:
        with st.spinner("Calcul de la valeur des mouvements complémentaires..."):
            df_year_comp = apply_notes(df_year_comp)
            df_year_comp = valuate_dataframe(df_year_comp, global_cache)

            df_year_comp["Quantité Entrée"] = df_year_comp["Amount"].apply(lambda x: x if x > 0 else 0.0)
            df_year_comp["Quantité Sortie"] = df_year_comp["Amount"].apply(lambda x: x if x < 0 else 0.0)

            hide_cols_comp = [c for c in df_year_comp.columns if c not in DISPLAY_COLS]
            col_cfg_comp = {
                "Valeur EUR (Date)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f"),
                "Quantité Entrée": st.column_config.NumberColumn(format="%.6f"),
                "Quantité Sortie": st.column_config.NumberColumn(format="%.6f"),
                "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="medium"),
                "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm", disabled=True),
            }
            for c in hide_cols_comp: col_cfg_comp[c] = None

            ed_comp = st.data_editor(
                df_year_comp,
                column_config=col_cfg_comp,
                width='stretch',
                hide_index=True,
                key="comp_mvt_editor"
            )

            if st.button("💾 Enregistrer les Notes (Mouvements Complémentaires)", key="btn_save_notes_comp"):
                new_notes = notes_db.copy()
                for idx, r in ed_comp.iterrows():
                    r_proxy = r.to_dict()
                    if "Tx Hash" not in r_proxy or not r_proxy["Tx Hash"]:
                        r_proxy["Tx Hash"] = df_year_comp.at[idx, "Tx Hash"] if "Tx Hash" in df_year_comp.columns else ""

                    key = sl.get_note_key(r_proxy)
                    if r["Notes"]: new_notes[key] = str(r["Notes"])
                    elif key in new_notes: del new_notes[key]
                sl.save_manual_notes(new_notes)
                st.success("Notes enregistrées.")
                st.rerun()

    # 3. TABLE 2: Balances par Compte
    st.divider()
    st.subheader(f"🏦 État des Lieux par Compte Propriétaire (au 31/12/{target_year})")

    if snapshot_df.empty:
        st.info("Aucun solde à afficher.")
    else:
        # 1. Filter snapshot for Owners
        mask_owner = snapshot_df["Location"].str.startswith("Account:", na=False)
        df_balances = snapshot_df[mask_owner].copy()
        def map_owner_bal(loc):
            addr = loc.replace("Account: ", "")
            return sl.resolve_owner_display(addr)
        df_balances["Compte"] = df_balances["Location"].apply(map_owner_bal)

        display_bal_cols = ["Compte", "Asset", "Entrées", "Sorties", "Solde", "Prix (EUR)", "Valeur (EUR)", "Notes"]
        df_balances = apply_notes(df_balances)

        # We need technical columns for note persistence (Location -> Account, Solde -> Amount)
        # We use a technical copy with hidden columns
        bal_with_tech = df_balances.copy()
        bal_with_tech["Tx Hash"] = "SNAPSHOT"

        col_cfg_bal = {
            "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f"),
            "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
            "Solde": st.column_config.NumberColumn("Quantité Finale", format="%.6f"),
            "Entrées": st.column_config.NumberColumn(format="%.6f"),
            "Sorties": st.column_config.NumberColumn(format="%.6f"),
            "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="medium"),
        }
        # Hide technical columns that are not in display_bal_cols
        for c in bal_with_tech.columns:
            if c not in display_bal_cols:
                col_cfg_bal[c] = None

        ed_bal = st.data_editor(
            bal_with_tech,
            column_config=col_cfg_bal,
            width='stretch',
            hide_index=True,
            key="owner_bal_editor"
        )

        if st.button("💾 Enregistrer les Notes (Balances Propriétaires)", key="btn_save_notes_bal_owners"):
            new_notes = notes_db.copy()
            for _, r in ed_bal.iterrows():
                # We use fixed date for snapshots
                r_proxy = r.to_dict()
                r_proxy["Date"] = datetime(target_year, 12, 31)
                key = sl.get_note_key(r_proxy)
                if r["Notes"]: new_notes[key] = str(r["Notes"])
                elif key in new_notes: del new_notes[key]
            sl.save_manual_notes(new_notes)
            st.success("Notes enregistrées.")
            st.rerun()

        # 3b. TABLE 2b: Balances Complémentaires (Manuelles & Créances)
        st.subheader(f"🏦 Positions Complémentaires - Manuelles & Créances (au 31/12/{target_year})")

        # Filter for non-owners (Manual Positions and Receivables)
        # Receivables in snapshot usually have labels like "External/CEX: ..." or derived from position_labels
        # Manual Positions start with "Manual Position:"
        # So complementary balances = (Everything except Account:) AND Is_Circuit != True
        mask_comp_bal = (~mask_owner) & (snapshot_df["Is_Circuit"] != True)

        df_comp_bal = snapshot_df[mask_comp_bal].copy()
        # Ensure model matches exactly by using 'Compte' as column name
        df_comp_bal["Compte"] = df_comp_bal["Location"].str.replace("Manual Position: ", "")

        if df_comp_bal.empty:
            st.info("Aucune position complémentaire détectée.")
        else:
            df_comp_bal = apply_notes(df_comp_bal)

            comp_bal_tech = df_comp_bal.copy()
            comp_bal_tech["Tx Hash"] = "SNAPSHOT"

            col_cfg_comp_bal = {
                "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f"),
                "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                "Solde": st.column_config.NumberColumn("Quantité Finale", format="%.6f"),
                "Entrées": st.column_config.NumberColumn(format="%.6f"),
                "Sorties": st.column_config.NumberColumn(format="%.6f"),
                "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="medium"),
            }
            for c in comp_bal_tech.columns:
                if c not in display_bal_cols:
                    col_cfg_comp_bal[c] = None

            ed_comp_bal = st.data_editor(
                comp_bal_tech,
                column_config=col_cfg_comp_bal,
                width='stretch',
                hide_index=True,
                key="comp_bal_editor"
            )

            if st.button("💾 Enregistrer les Notes (Balances Complémentaires)", key="btn_save_notes_bal_comp"):
                new_notes = notes_db.copy()
                for _, r in ed_comp_bal.iterrows():
                    r_proxy = r.to_dict()
                    r_proxy["Date"] = datetime(target_year, 12, 31)
                    key = sl.get_note_key(r_proxy)
                    if r["Notes"]: new_notes[key] = str(r["Notes"])
                    elif key in new_notes: del new_notes[key]
                sl.save_manual_notes(new_notes)
                st.success("Notes enregistrées.")
                st.rerun()

st.sidebar.divider()
st.sidebar.caption("Dashboard Patrimoine v1.0 - appPropri")
