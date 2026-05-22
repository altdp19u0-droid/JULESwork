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

    # Load Unified Processing Year from config for persistence
    g_conf = sl.load_global_config()
    # Use a specific key for appPropri to avoid being overwritten by Step 1/Step 2 defaults if they differ
    persisted_year = int(g_conf.get("appPropri_year") or g_conf.get("processing_year") or datetime.now().year)

    # Standardized hub key for persistence
    # We must ensure state is initialized to avoid value/key collision
    if "_hub_appPropri_year" not in st.session_state:
        st.session_state["_hub_appPropri_year"] = persisted_year

    target_year_input = st.number_input("Année de consultation", min_value=2015, max_value=2030, key="_hub_appPropri_year")
    target_year = int(target_year_input)

    # Persist change to global config immediately when detected
    if target_year != g_conf.get("appPropri_year"):
        g_conf["appPropri_year"] = target_year
        # Also update the shared processing year for suite consistency
        g_conf["processing_year"] = target_year
        sl.save_global_config(g_conf)

    # Year switch detection for session clearing
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
def ensure_dt(df):
    """Garantit que la colonne Date est de type datetime64[ns, UTC] pour éviter AttributeError .dt"""
    if df is None: return pd.DataFrame(columns=["Date"])
    df = df.copy()
    if "Date" not in df.columns:
        df["Date"] = pd.NaT
    df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
    if df.empty:
        return df
    return df.dropna(subset=["Date"])

@st.cache_data
def get_owner_history(year):
    """Loads consolidated clean history up to 'year' and filters for owner accounts + protocol positions."""
    owners_map = sl.load_owner_accounts()
    pos_map = sl.load_position_labels()

    # We include both personal wallets and identified protocol positions
    authorized_ids = set(list(owners_map.keys()) + list(pos_map.keys()))

    # GATEWAY ARCHITECTURE: Use consolidated clean history
    combined = sl.load_clean_history(year)

    if not combined.empty:
        # Resolve owner addresses for filtering
        combined["acc_raw"] = combined["Account"].apply(sl.resolve_raw_addr)
        # Check against both technical ID and label from standard resolution
        combined = combined[combined["acc_raw"].isin(authorized_ids) |
                            combined["Account"].isin(owners_map.values()) |
                            combined["Account"].isin(pos_map.values())]

        combined["Date"] = pd.to_datetime(combined["Date"], utc=True, errors="coerce")
        # --- CRITICAL FIX: Filter out rows with None dates ---
        combined = combined[combined["Date"].notna()]

        # Deduplication logic (similar to how history was merged before)
        combined["_day"] = combined["Date"].dt.date
        combined["_amt"] = combined["Amount"].astype(float).round(8)
        combined["_acc"] = combined["Account"].astype(str).str.lower()
        combined["_asset"] = combined["Asset"].astype(str).str.upper()

        # We assume Source_Way or Source Type exists
        src_col = "Source_Way" if "Source_Way" in combined.columns else "Source Type"
        if src_col in combined.columns:
            combined["_src_pri"] = combined[src_col].apply(lambda x: 0 if "Manual" not in str(x) else 1)
            combined = combined.sort_values("_src_pri").drop_duplicates(subset=["_day", "_acc", "_asset", "_amt"], keep="first")
            combined = combined.drop(columns=["_day", "_amt", "_acc", "_asset", "_src_pri"])

        if "acc_raw" in combined.columns:
            combined = combined.drop(columns=["acc_raw"])

        return combined.sort_values("Date", ascending=False).reset_index(drop=True)

    return pd.DataFrame()

@st.cache_data
def get_acquisition_history(year):
    """Loads all fiat acquisitions from CLEAN history from start_year to 'year'."""
    # EXCLUSIVITY RULE: Data must come from CLEAN history journal only
    df_h = sl.load_clean_history(year)
    if df_h.empty: return pd.DataFrame()

    # Filter for 'Achat' categories in the journal
    mask = df_h['Category'].fillna("").str.contains("Achat", case=False, na=False)
    df_acq = df_h[mask].copy()

    if df_acq.empty: return pd.DataFrame()

    df_acq["Date"] = pd.to_datetime(df_acq["Date"], utc=True, errors="coerce")
    df_acq = df_acq[df_acq["Date"].notna()]

    # Mapping to UI expected columns
    df_acq = df_acq.rename(columns={
        "Account": "Compte",
        "Counterparty": "Provenance",
        "Chain": "Blockchain"
    })

    # Value detection & Standard mapping - Safe handling of missing columns
    if "Montant EUR" in df_acq.columns:
        df_acq["Fiat Mobilisé (EUR)"] = pd.to_numeric(df_acq["Montant EUR"], errors="coerce")
    elif "Amount" in df_acq.columns:
        df_acq["Fiat Mobilisé (EUR)"] = pd.to_numeric(df_acq["Amount"], errors="coerce")
    else:
        df_acq["Fiat Mobilisé (EUR)"] = pd.Series([0.0] * len(df_acq))

    df_acq["Fiat Mobilisé (EUR)"] = df_acq["Fiat Mobilisé (EUR)"].fillna(0.0)

    # Standardize Quantité column (always refers to 'Amount' column of the journal)
    if "Amount" in df_acq.columns:
        df_acq["Quantité"] = pd.to_numeric(df_acq["Amount"], errors="coerce").fillna(0.0).abs()
    else:
        df_acq["Quantité"] = pd.Series([0.0] * len(df_acq))

    return df_acq.sort_values("Date", ascending=False).reset_index(drop=True)

@st.cache_data
def get_cessions_history(year):
    """Loads all imposable cessions from consolidated clean history up to 'year'."""
    # GATEWAY ARCHITECTURE: Use consolidated clean history
    combined = sl.load_clean_history(year)

    if not combined.empty:
        # Filter for cessions
        # RECOGNITION LOGIC: Consistent with app3.py
        def is_imposable_logic(r):
            # Imposable flag is the primary truth
            if sl.is_imposable_robust(r.get("Imposable")): return True
            # 'Vente' category is a strong secondary signal
            cat = str(r.get("Category", "")).lower()
            if "vente" in cat: return True
            return False

        combined["_is_imp"] = combined.apply(is_imposable_logic, axis=1)

        mask_cess = (combined["_is_imp"]) & (combined['Asset'] != 'EUR')

        cessions = combined[mask_cess].copy()

        if not cessions.empty:
            cessions["Date"] = pd.to_datetime(cessions["Date"], utc=True, errors="coerce")
            # --- CRITICAL FIX: Filter out rows with None dates ---
            cessions = cessions[cessions["Date"].notna()]

            cessions["_day"] = cessions["Date"].dt.date
            cessions["_amt"] = cessions["Amount"].astype(float).round(8)
            cessions["_acc"] = cessions["Account"].astype(str).str.lower()
            cessions["_asset"] = cessions["Asset"].astype(str).str.upper()

            # Drop duplicates
            src_col = "Source_Way" if "Source_Way" in cessions.columns else "Source Type"
            if src_col in cessions.columns:
                cessions["_src_pri"] = cessions[src_col].apply(lambda x: 0 if "Manual" not in str(x) else 1)
                cessions = cessions.sort_values("_src_pri").drop_duplicates(subset=["_day", "_acc", "_asset", "_amt"], keep="first")
                cessions = cessions.drop(columns=["_day", "_amt", "_acc", "_asset", "_src_pri"])

            # Final type safety
            # Check for column existence before numeric conversion
            for col in ["Prix de Cession (EUR)", "VGP (EUR)"]:
                if col in cessions.columns:
                    cessions[col] = pd.to_numeric(cessions[col], errors="coerce").fillna(0.0)
                else:
                    cessions[col] = 0.0

            return cessions.sort_values("Date", ascending=True).reset_index(drop=True)

    return pd.DataFrame()

@st.cache_data
def get_complementary_history(year):
    """Loads movements from manual positions and internal transfer receivables from clean history."""
    owners_map = sl.load_owner_accounts()
    owner_addrs = set(owners_map.keys())

    # GATEWAY ARCHITECTURE: Use consolidated clean history
    combined = sl.load_clean_history(year)

    all_txs = []
    if not combined.empty:
        combined["Date"] = pd.to_datetime(combined["Date"], utc=True, errors="coerce")
        combined = combined.dropna(subset=["Date"])

        # 1. Manual Positions
        mask_m = combined["Type"].fillna("").str.contains("Position", case=False, na=False)
        if mask_m.any():
            df_m = combined[mask_m].copy()
            df_m["Category"] = "Position Manuelle"
            all_txs.append(df_m)

        # 2. Receivables from Internal Transfers to unknown accounts
        mask_int = (combined["Category"] == "Transfert Interne")
        if "Counterparty" in combined.columns:
            combined["cp_raw"] = combined["Counterparty"].apply(sl.resolve_raw_addr)
            df_receivable = combined[mask_int & (~combined["cp_raw"].isin(owner_addrs))].copy()

            if not df_receivable.empty:
                # In VGP calculation, the receivable is the negative of the leg
                df_receivable["Amount"] = -df_receivable["Amount"]
                df_receivable["Account"] = df_receivable["Counterparty"]
                df_receivable["Category"] = "Créance (Transfert Interne Sortant)"
                all_txs.append(df_receivable)

    if not all_txs: return pd.DataFrame(columns=["Date", "Account", "Asset", "Amount"])
    res = pd.concat(all_txs).sort_values("Date", ascending=False).reset_index(drop=True)
    res["Date"] = pd.to_datetime(res["Date"], utc=True)
    return res

# --- Helpers for UI ---
def valuate_dataframe(df, cache, year=None):
    """Calculates Valeur EUR (Date) for a transaction dataframe."""
    if df.empty: return df
    df = df.copy()

    # Load certified journal prices for the year if provided
    journal_prices = {}
    if year:
        df_h = sl.load_clean_history(year)
        journal_prices = sl.get_journal_prices(df_h)

    # Optimization: Group by (Asset, Date) to minimize redundant price calls
    df["Date_Only"] = df["Date"].dt.date
    unique_pairs = df[["Asset", "Date_Only"]].drop_duplicates()

    prices_map = {}
    for _, r in unique_pairs.iterrows():
        ast = str(r["Asset"]).upper().strip()
        # 1. Try Journal Price (latest known)
        p_eur = journal_prices.get(ast, 0.0)
        # 2. Fallback to historical date lookup
        if p_eur == 0:
            p_eur = sl.get_price_eur(ast, r["Date_Only"], cache=cache)
        prices_map[(ast, r["Date_Only"])] = p_eur

    def valuate_row(row):
        p_eur = prices_map.get((str(row["Asset"]).upper().strip(), row["Date_Only"]), 0.0)
        # Force sign preservation
        return float(row["Amount"]) * p_eur

    df["Valeur EUR (Date)"] = df.apply(valuate_row, axis=1)
    return df

# --- Protocol Table Logic ---
def get_protocol_summary(year):
    """Calculates summary for protocol positions: In, Out, Balance, Value EUR."""
    pos_reg = sl.load_position_registry()
    pos_addrs = set(pos_reg.keys())

    # Use CLEAN history (up to consulting year)
    df_h = sl.load_clean_history(year)
    if df_h.empty: return pd.DataFrame()

    # --- PROTOCOL DETECTION LOGIC ---
    # We leverage the centralized portfolio snapshot to ensure consistency
    snapshot, _ = sl.get_portfolio_snapshot(year, datetime(year, 12, 31))

    if snapshot.empty: return pd.DataFrame()

    # Filter for Protocols (using raw address and label name matching)
    pos_ids = {str(k).lower().strip() for k in pos_reg.keys()}
    pos_names = {str(v.get("label", "")).lower().strip() for v in pos_reg.values()}

    snapshot["_raw_loc"] = snapshot["Location"].apply(sl.resolve_raw_addr).str.lower().str.strip()
    df_proto_snap = snapshot[snapshot["_raw_loc"].isin(pos_ids) | snapshot["_raw_loc"].isin(pos_names)].copy()

    if df_proto_snap.empty: return pd.DataFrame()

    # --- ASSET FILTERING (REGISTRY MATCH) ---
    def filter_assets(row):
        loc_str = str(row["Location"]).lower().strip()
        loc_raw = sl.resolve_raw_addr(loc_str).lower()

        # Extract label from "0x... (Label)"
        loc_label_extracted = ""
        if "(" in loc_str and ")" in loc_str:
            loc_label_extracted = loc_str.split("(")[1].replace(")", "").strip().lower()

        # Find entry in registry either by address or by label name
        entry = pos_reg.get(loc_raw)
        if not entry:
            # Fallback: check matching labels (Case insensitive and stripped)
            for k, v in pos_reg.items():
                lbl_reg = str(v.get("label", "")).lower().strip()
                if lbl_reg and (lbl_reg == loc_str or lbl_reg == loc_label_extracted or lbl_reg in loc_str):
                    entry = v
                    break

        if entry:
            allowed_assets = [str(a).upper().strip() for a in entry.get("assets", [])]
            # If no assets defined yet, we show all (fallback for newly added positions)
            if not allowed_assets: return True
            return str(row["Asset"]).upper().strip() in allowed_assets

        # If not found in registry at all, we don't display it here (strict UI)
        return False

    df_proto_snap = df_proto_snap[df_proto_snap.apply(filter_assets, axis=1)].copy()

    if df_proto_snap.empty: return pd.DataFrame()

    # Now we need In/Out cumulative details. We extract them from the CLEAN history.
    df_h["acc_raw"] = df_h["Account"].apply(sl.resolve_raw_addr).str.lower().str.strip()
    df_direct = df_h[df_h["acc_raw"].isin(pos_ids) | df_h["acc_raw"].isin(pos_names)].copy()

    df_h["cp_raw"] = df_h["Counterparty"].apply(sl.resolve_raw_addr).str.lower().str.strip()
    df_mirror = df_h[(df_h["Category"] == "Transfert Interne") &
                     (df_h["cp_raw"].isin(pos_ids) | df_h["cp_raw"].isin(pos_names))].copy()

    if not df_mirror.empty:
        df_mirror["Account"] = df_mirror["Counterparty"]
        df_mirror["Amount"] = -pd.to_numeric(df_mirror["Amount"], errors="coerce").fillna(0.0)
        df_full_proto = pd.concat([df_direct, df_mirror])
    else:
        df_full_proto = df_direct

    # Calculate cumulatives
    df_full_proto["In"] = df_full_proto["Amount"].apply(lambda x: x if x > 0 else 0.0)
    df_full_proto["Out"] = df_full_proto["Amount"].apply(lambda x: abs(x) if x < 0 else 0.0)
    df_full_proto["Compte"] = df_full_proto["Account"].apply(sl.resolve_owner_display)

    cumul = df_full_proto.groupby(["Compte", "Asset"]).agg({"In": "sum", "Out": "sum"}).reset_index()
    cumul = cumul.rename(columns={"In": "Quantité Entrée", "Out": "Quantité Sortie"})

    # Final Merge with Snapshot (which has the correct final balance and EUR value)
    df_proto_snap["Compte"] = df_proto_snap["Location"]
    # Outer join to ensure we see assets even if snapshot or cumul is missing one side
    # Snapshot now uses "Solde" instead of "Amount"
    res = pd.merge(df_proto_snap[["Compte", "Asset", "Solde", "Valeur (EUR)"]], cumul, on=["Compte", "Asset"], how="outer")

    res = res.rename(columns={"Solde": "Solde (Qté)", "Valeur (EUR)": "Valeur EUR", "Compte": "Compte (Protocol)"})
    res["Solde (Qté)"] = res["Solde (Qté)"].fillna(0.0)
    res["Valeur EUR"] = res["Valeur EUR"].fillna(0.0)

    return res

# --- Shared Constants ---
DISPLAY_COLS = ["Date", "Account", "Asset", "Quantité Entrée", "Quantité Sortie", "Valeur EUR (Date)", "Category", "Counterparty", "Notes"]

# --- Main App ---
history = get_owner_history(target_year)
comp_history = get_complementary_history(target_year)
acq_history = get_acquisition_history(target_year)

notes_db = sl.load_manual_notes()

def apply_notes(df):
    if df.empty: return df
    df = df.copy()
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

                # Valuation A: At the time of purchase (Fiat Mobilisé)
                # If Fiat Mobilisé (EUR) is missing or 0, we can try to derive it from VGP or Valeur $
                def get_fiat_mob(r):
                    val = float(r.get("Fiat Mobilisé (EUR)", 0))
                    if val == 0:
                        val = float(r.get("VGP (EUR)", 0)) or (float(r.get("Valeur $", 0)) * 0.92)
                    return val
                acq_history["Fiat Mobilisé (EUR)"] = acq_history.apply(get_fiat_mob, axis=1)

                # Valuation B: Current Value at 31/12
                eoy_date = datetime(target_year, 12, 31)

                # Fetch EOY prices for all assets in acq_history
                unique_assets = acq_history["Asset"].unique()
                eoy_prices = {}
                df_h_all = sl.load_clean_history(target_year)
                journal_prices_eoy = sl.get_journal_prices(df_h_all, target_date=eoy_date)

                for a in unique_assets:
                    ast = str(a).upper().strip()
                    p = journal_prices_eoy.get(ast, 0.0)
                    if p == 0:
                        p = sl.get_price_eur(ast, eoy_date, cache=global_cache)
                    eoy_prices[ast] = p

                amt_col = "Quantité" if "Quantité" in acq_history.columns else "Amount"
                acq_history["Valeur (EUR) au 31/12"] = acq_history.apply(
                    lambda r: float(r[amt_col]) * eoy_prices.get(str(r["Asset"]).upper().strip(), 0.0), axis=1
                )

                # UNIFICATION: Use central logic for metric display
                total_a = sl.get_total_acquisition_value(target_year)
                st.metric("Total Prix d'Acquisition (A)", f"{total_a:,.2f} €")

                # Table Display
                display_acq_cols = ["Date", "Fiat Mobilisé (EUR)", "Asset", "Quantité", "Valeur (EUR) au 31/12", "Compte", "Blockchain", "Notes"]
                hide_cols = [c for c in acq_history.columns if c not in display_acq_cols]

                col_cfg = {
                    "Fiat Mobilisé (EUR)": st.column_config.NumberColumn("Fiat mobilisé (EUR)", format="%.2f €", help="Montant dépensé au moment de l'acquisition."),
                    "Valeur (EUR) au 31/12": st.column_config.NumberColumn("Valeur (EUR) au 31/12", format="%.2f €", help="Valeur estimée au 31/12 de l'année de consultation."),
                    "Quantité": st.column_config.NumberColumn("Solde / Quantité", format="%.6f"),
                    "Asset": "Actif",
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
                            r_proxy["Tx Hash"] = acq_history.at[idx, "Tx_Hash"] if "Tx_Hash" in acq_history.columns else (acq_history.at[idx, "Tx Hash"] if "Tx Hash" in acq_history.columns else "")
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
                    "Chain": "Blockchain",
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
                    for idx, r in ed_cess.iterrows():
                        orig_h = cess_history.at[idx, "Tx_Hash"] if "Tx_Hash" in cess_history.columns else (cess_history.at[idx, "Tx Hash"] if "Tx Hash" in cess_history.columns else "")

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

elif history.empty and comp_history.empty and acq_history.empty:
    st.warning(f"Aucune donnée (historique, complémentaire ou acquisition) trouvée jusqu'en {target_year}.")
    st.info("💡 Vérifiez que vos comptes sont bien enregistrés dans la **Gestion des Comptes Propriétaires** (App 2).")
else:
    # 1. METRICS
    st.subheader("📊 Indicateurs Patrimoniaux")

    # --- NEW: PROTOCOL POSITIONS TABLE ---
    st.subheader(f"🏦 État des Lieux par Position Protocole (au 31/12/{target_year})")
    df_proto_sum = get_protocol_summary(target_year)
    if df_proto_sum.empty:
        st.info("Aucune position protocole qualifiée détectée.")
    else:
        # Applying notes to protocol summary for consistency
        df_proto_sum = apply_notes(df_proto_sum.rename(columns={"Compte (Protocol)": "Compte"}))

        # Adding dummy tech columns for key generator in apply_notes
        df_proto_sum["Tx Hash"] = "SNAPSHOT_PROTO"
        if "Amount" not in df_proto_sum.columns:
            df_proto_sum["Amount"] = df_proto_sum["Solde (Qté)"]

        ed_proto = st.data_editor(
            df_proto_sum,
            column_config={
                "Compte": "Protocole",
                "Quantité Entrée": st.column_config.NumberColumn(format="%.6f"),
                "Quantité Sortie": st.column_config.NumberColumn(format="%.6f"),
                "Solde (Qté)": st.column_config.NumberColumn(format="%.6f"),
                "Valeur EUR": st.column_config.NumberColumn(format="%.2f €"),
                "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="medium"),
                "Tx Hash": None, "Amount": None # Hide dummy cols
            },
            width='stretch',
            hide_index=True,
            key="proto_bal_editor"
        )

        if st.button("💾 Enregistrer les Notes (Balances Protocoles)", key="btn_save_notes_bal_proto"):
            new_notes = notes_db.copy()
            for _, r in ed_proto.iterrows():
                r_proxy = r.to_dict()
                r_proxy["Date"] = datetime(target_year, 12, 31)
                r_proxy["Account"] = r["Compte"]
                key = sl.get_note_key(r_proxy)
                if r["Notes"]: new_notes[key] = str(r["Notes"])
                elif key in new_notes: del new_notes[key]
            sl.save_manual_notes(new_notes)
            st.success("Notes enregistrées.")
            st.rerun()

        st.caption("Note: Les prix et valeurs sont basés sur les cours au 31/12 de l'année de consultation.")

    st.divider()

    # Cumulative Acquisition Price (A)
    total_acq = sl.get_total_acquisition_value(target_year)

    # Portfolio Value (VGP) at EOY
    eoy_date = datetime(target_year, 12, 31)
    snapshot_df, vgp_eoy = sl.get_portfolio_snapshot(target_year, eoy_date)

    c1, c2, c3 = st.columns(3)
    c1.metric("Prix d'Acquisition Total (A)", f"{total_acq:,.2f} €", help="Somme cumulée de vos apports fiat (Euros) dans l'écosystème crypto.")
    c2.metric(f"Valeur Patrimoniale (31/12/{target_year})", f"{vgp_eoy:,.2f} €", help="Valeur totale du portefeuille (VGP) à la fin de l'année.")

    perf_net = vgp_eoy - total_acq
    c3.metric("Performance Latente Globale", f"{perf_net:,.2f} €", delta=perf_net, delta_color="normal")

    # 2. TABLE 1: Transactions de l'année (Comptes Propriétaires)
    st.divider()
    st.subheader(f"📑 Mouvements des Comptes Propriétaires ({target_year})")

    global_cache = sl.load_price_cache()

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
            df_year = valuate_dataframe(df_year, global_cache, year=target_year)

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
                    r_proxy = r.to_dict()
                    if "Tx Hash" not in r_proxy or not r_proxy["Tx Hash"]:
                        r_proxy["Tx Hash"] = df_year.at[idx, "Tx_Hash"] if "Tx_Hash" in df_year.columns else (df_year.at[idx, "Tx Hash"] if "Tx Hash" in df_year.columns else "")

                    key = sl.get_note_key(r_proxy)
                    if r["Notes"]: new_notes[key] = str(r["Notes"])
                    elif key in new_notes: del new_notes[key]
                sl.save_manual_notes(new_notes)
                st.success("Notes enregistrées.")
                st.rerun()

    # 2b. TABLE 1b: Mouvements Complémentaires
    st.subheader(f"📑 Mouvements Complémentaires - Manuels & Créances ({target_year})")
    comp_history = ensure_dt(comp_history)

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
            df_year_comp = valuate_dataframe(df_year_comp, global_cache, year=target_year)

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
                        r_proxy["Tx Hash"] = df_year_comp.at[idx, "Tx_Hash"] if "Tx_Hash" in df_year_comp.columns else (df_year_comp.at[idx, "Tx Hash"] if "Tx Hash" in df_year_comp.columns else "")

                    key = sl.get_note_key(r_proxy)
                    if r["Notes"]: new_notes[key] = str(r["Notes"])
                    elif key in new_notes: del new_notes[key]
                sl.save_manual_notes(new_notes)
                st.success("Notes enregistrées.")
                st.rerun()

    # 3. TABLE 2: Balances par Compte
    st.divider()

    owners_map = sl.load_owner_accounts()
    owner_ids = set(owners_map.keys())
    pos_map = sl.load_position_labels()
    pos_ids = set(pos_map.keys())

    # Separate Wallets and Protocols from snapshot
    if not snapshot_df.empty:
        snapshot_df["_raw_acc"] = snapshot_df["Location"].apply(sl.resolve_raw_addr)
        # Ensure we have all columns expected
        for c in ["Solde", "Prix (EUR)", "Valeur (EUR)", "Is_Circuit"]:
            if c not in snapshot_df.columns: snapshot_df[c] = (False if c == "Is_Circuit" else 0.0)

        # Exclude External Circuits from standard wallets view
        snapshot_clean = snapshot_df[snapshot_df["Is_Circuit"] == False].copy()

        df_wallets = snapshot_clean[snapshot_clean["_raw_acc"].isin(owner_ids) |
                                 snapshot_clean["Location"].isin(owners_map.values())].copy()
        df_protocols_snap = snapshot_df[snapshot_df["_raw_acc"].isin(pos_ids) |
                                        snapshot_df["Location"].isin(pos_map.values())].copy()
    else:
        df_wallets = pd.DataFrame()
        df_protocols_snap = pd.DataFrame()

    st.subheader(f"🏦 État des Lieux par Compte Propriétaire (au 31/12/{target_year})")

    if df_wallets.empty:
        st.info("Aucun solde portefeuille à afficher.")
    else:
        df_balances = df_wallets.copy()
        df_balances["Compte"] = df_balances["Location"]

        display_bal_cols = ["Compte", "Asset", "Solde", "Prix (EUR)", "Valeur (EUR)", "Notes"]
        df_balances = apply_notes(df_balances)

        bal_with_tech = df_balances.copy()
        bal_with_tech["Tx Hash"] = "SNAPSHOT"
        if "Amount" not in bal_with_tech.columns and "Solde" in bal_with_tech.columns:
            bal_with_tech["Amount"] = bal_with_tech["Solde"]

        col_cfg_bal = {
            "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f"),
            "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
            "Solde": st.column_config.NumberColumn("Quantité Finale", format="%.6f"),
            "Notes": st.column_config.TextColumn("Notes (Saisie libre)", width="medium"),
        }
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
                r_proxy = r.to_dict()
                r_proxy["Date"] = datetime(target_year, 12, 31)
                r_proxy["Account"] = r["Compte"]
                key = sl.get_note_key(r_proxy)
                if r["Notes"]: new_notes[key] = str(r["Notes"])
                elif key in new_notes: del new_notes[key]
            sl.save_manual_notes(new_notes)
            st.success("Notes enregistrées.")
            st.rerun()

st.sidebar.divider()
st.sidebar.caption("Dashboard Patrimoine v1.0 - appPropri")
