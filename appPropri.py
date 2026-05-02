import os
import pandas as pd
import streamlit as st
from datetime import datetime
from shared_logic import (
    resolve_raw_addr, get_portfolio_snapshot, get_price_eur,
    pd_read_csv_safe, get_file_path, validate_spam_exclusion,
    load_owner_accounts, get_total_acquisition_value
)

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Propriété & Patrimoine (appPropri)", layout="wide")
st.title("👤 Propriété & Patrimoine (Dashboard)")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de consultation", min_value=2015, max_value=2030, value=datetime.now().year)

    st.divider()
    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    show_status()

# --- Logic: Loading and Filtering ---
@st.cache_data
def get_owner_history(year):
    """Loads all qualified journals up to 'year' and filters for owner accounts."""
    owners_map = load_owner_accounts()
    owner_addrs = set(owners_map.keys())

    all_txs = []
    for y in range(2020, year + 1):
        path = get_file_path(y, 'qualified')
        if os.path.exists(path):
            try:
                df = pd_read_csv_safe(path)
                if df.empty: continue

                # 1. Absolute Spam Exclusion
                leaked = validate_spam_exclusion(df)
                if leaked: df.loc[leaked, "Status"] = "Spam"
                df = df[df["Status"] != "Spam"].copy()

                # 2. Filter for Owners
                # Keep rows where 'Account' is a known owner address
                df["acc_raw"] = df["Account"].apply(resolve_raw_addr)
                df_owner = df[df["acc_raw"].isin(owner_addrs)].copy()

                if not df_owner.empty:
                    df_owner["Date"] = pd.to_datetime(df_owner["Date"], utc=True)
                    all_txs.append(df_owner)
            except: pass

    if not all_txs: return pd.DataFrame()
    return pd.concat(all_txs).sort_values("Date", ascending=False).reset_index(drop=True)

# --- Main App ---
history = get_owner_history(target_year)

if history.empty:
    st.warning(f"Aucune transaction trouvée pour les comptes propriétaires jusqu'en {target_year}.")
    st.info("💡 Vérifiez que vos comptes sont bien enregistrés dans la **Gestion des Comptes Propriétaires** (App 2).")
else:
    # 1. METRICS
    st.subheader("📊 Indicateurs Patrimoniaux")

    # Cumulative Acquisition Price (A)
    total_acq = get_total_acquisition_value(target_year)

    # Portfolio Value (VGP) at EOY
    eoy_date = datetime(target_year, 12, 31)
    # get_portfolio_snapshot handles historical carryover
    snapshot_df, vgp_eoy = get_portfolio_snapshot(target_year, eoy_date)

    c1, c2, c3 = st.columns(3)
    c1.metric("Prix d'Acquisition Total (A)", f"{total_acq:,.2f} €", help="Somme cumulée de vos apports fiat (Euros) dans l'écosystème crypto.")
    c2.metric(f"Valeur Patrimoniale (31/12/{target_year})", f"{vgp_eoy:,.2f} €", help="Valeur totale du portefeuille (VGP) à la fin de l'année.")

    perf_net = vgp_eoy - total_acq
    c3.metric("Performance Latente Globale", f"{perf_net:,.2f} €", delta=perf_net, delta_color="normal")

    # 2. TABLE 1: Transactions de l'année
    st.divider()
    st.subheader(f"📑 Mouvements des Comptes Propriétaires ({target_year})")

    # Filter for current year only
    mask_year = history["Date"].dt.year == target_year
    df_year = history[mask_year].copy()

    if df_year.empty:
        st.info(f"Aucun mouvement détecté spécifiquement en {target_year}.")
    else:
        # Valuation at transaction date
        with st.spinner("Calcul de la valeur des mouvements à date..."):
            from shared_logic import load_price_cache
            cache = load_price_cache()

            # Optimization: Group by (Asset, Date) to minimize redundant price calls
            # Use only date (not time) for historical price lookup to increase cache hits
            df_year["Date_Only"] = df_year["Date"].dt.date

            # Identify unique asset-date pairs
            unique_pairs = df_year[["Asset", "Date_Only"]].drop_duplicates()

            prices_map = {}
            for _, r in unique_pairs.iterrows():
                p_eur = get_price_eur(r["Asset"], r["Date_Only"], cache=cache)
                prices_map[(r["Asset"], r["Date_Only"])] = p_eur

            def valuate_row(row):
                p_eur = prices_map.get((row["Asset"], row["Date_Only"]), 0.0)
                return abs(float(row["Amount"])) * p_eur

            df_year["Valeur EUR (Date)"] = df_year.apply(valuate_row, axis=1)

            # Split In/Out for display
            df_year["Quantité Entrée"] = df_year["Amount"].apply(lambda x: x if x > 0 else 0.0)
            df_year["Quantité Sortie"] = df_year["Amount"].apply(lambda x: abs(x) if x < 0 else 0.0)

            display_cols = ["Date", "Account", "Asset", "Quantité Entrée", "Quantité Sortie", "Valeur EUR (Date)", "Category", "Counterparty"]
            st.dataframe(
                df_year[display_cols],
                column_config={
                    "Valeur EUR (Date)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €"),
                    "Quantité Entrée": st.column_config.NumberColumn(format="%.6f"),
                    "Quantité Sortie": st.column_config.NumberColumn(format="%.6f"),
                    "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")
                },
                use_container_width=True,
                hide_index=True
            )

    # 3. TABLE 2: Balances par Compte
    st.divider()
    st.subheader(f"🏦 État des Lieux par Compte (au 31/12/{target_year})")

    if snapshot_df.empty:
        st.info("Aucun solde à afficher.")
    else:
        # filter snapshot for Owners only (already handles circuits)
        # Snapshot returns Location as "Account: Name" or labels
        mask_owner = snapshot_df["Location"].str.startswith("Account:", na=False)
        df_balances = snapshot_df[mask_owner].copy()
        df_balances["Compte"] = df_balances["Location"].str.replace("Account: ", "")

        # Display
        display_bal_cols = ["Compte", "Asset", "Entrées", "Sorties", "Solde", "Prix (EUR)", "Valeur (EUR)"]
        st.dataframe(
            df_balances[display_bal_cols],
            column_config={
                "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €"),
                "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                "Solde": st.column_config.NumberColumn("Quantité Finale", format="%.6f"),
            },
            use_container_width=True,
            hide_index=True
        )

st.sidebar.divider()
st.sidebar.caption("Dashboard Patrimoine v1.0 - appPropri")
