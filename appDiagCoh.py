import os
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import unicodedata
from shared_logic import resolve_raw_addr, pd_read_csv_safe

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Diagnostic & Cohérence (appDiagCoh)", layout="wide")
st.title("🕵️ Diagnostic & Contrôle de Cohérence")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"
POSITIONS_FILE = "position_labels.json"

# --- Helpers ---

def normalize_asset(asset):
    # Consistently use same logic as shared_logic (could also move it to shared_logic)
    nuance_map = {
        "\ua4f4": "U", "\ua4e2": "S", "\ua4d3": "D", "\ua4c1": "G", "\ua4c3": "H",
        "\u0421": "C", "\u0405": "S", "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T", "\u0425": "X",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u216d": "C", "\u2160": "I", "\u2164": "V", "\u2169": "X", "\u216c": "L", "\u216f": "M",
    }
    s = str(asset)
    for k, v in nuance_map.items(): s = s.replace(k, v)
    return unicodedata.normalize('NFKC', s).upper().strip()

def load_all_history():
    """Aggregates all qualified journals and manual positions from 2020."""
    journals = []
    manuals = []

    current_year = datetime.now().year
    for y in range(2020, current_year + 1):
        # Qualified Journal
        path_j = os.path.join(EXPORT_BASE_DIR, str(y), f"qualified_journal_{y}.csv")
        if os.path.exists(path_j):
            df = pd_read_csv_safe(path_j)
            if not df.empty:
                df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
                # Filter spam/doubles
                df = df[(df["Status"] != "Spam") & (df.get("Category", "") != "Doublon à ignorer")]
                journals.append(df)

        # Manual Positions (End of year snapshots)
        path_m = os.path.join(EXPORT_BASE_DIR, str(y), f"manual_positions_{y}.csv")
        if os.path.exists(path_m):
            df_m = pd_read_csv_safe(path_m)
            if not df_m.empty:
                df_m["Date"] = pd.to_datetime(df_m["Date"], utc=True, errors="coerce")
                manuals.append(df_m)

    return pd.concat(journals) if journals else pd.DataFrame(), pd.concat(manuals) if manuals else pd.DataFrame()

# --- Engine ---
def is_imposable_robust(val):
    if pd.isna(val): return False
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI", "YES", "OUI"]

def compute_running_balances(df_j, df_m):
    if df_j.empty and df_m.empty: return pd.DataFrame()

    # 1. Prepare Rows
    rows = []

    # Journal Movements
    if not df_j.empty:
        for _, r in df_j.iterrows():
            is_cession = is_imposable_robust(r.get("Imposable")) or "Vente" in str(r.get("Category", ""))
            rows.append({
                "Date": r["Date"], "Account": str(r["Account"]), "Asset": normalize_asset(r["Asset"]),
                "Amount": float(r["Amount"]), "Type": "Movement", "Category": r.get("Category", "A vérifier"),
                "Counterparty": r.get("Counterparty", ""), "Source": "Journal",
                "Is_Cession": is_cession
            })

            # Handle Internal Transfer Offset Leg if it's not an owned account
            if r.get("Category") == "Transfert Interne":
                cp_raw = resolve_raw_addr(r["Counterparty"])
                owned_accs = set(df_j["Account"].dropna().unique())
                if cp_raw not in owned_accs:
                    # It's a receivable (asset for us held at CP)
                    rows.append({
                        "Date": r["Date"], "Account": f"External/CEX: {r['Counterparty']}", "Asset": normalize_asset(r["Asset"]),
                        "Amount": -float(r["Amount"]), "Type": "Offset Receivable", "Category": "Transfert Interne",
                        "Counterparty": r["Account"], "Source": "Internal Leg", "Is_Cession": False
                    })

    # Manual Entries
    if not df_m.empty:
        for _, r in df_m.iterrows():
            rows.append({
                "Date": r["Date"], "Account": str(r["Account"]), "Asset": normalize_asset(r["Asset"]),
                "Amount": float(r["Quantité"]), "Type": "Manual Position", "Category": "Stock Initial/Snapshot",
                "Counterparty": "Manual", "Source": "Manual", "Is_Cession": False
            })

    full_history = pd.DataFrame(rows).sort_values("Date")

    # 2. Compute per Asset/Account
    full_history["Running_Bal"] = full_history.groupby(["Account", "Asset"])["Amount"].cumsum()

    return full_history

# --- Main Logic ---
with st.sidebar:
    st.header("⚙️ Contrôle")
    if st.button("🔄 Actualiser le Diagnostic", width='stretch', type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.info("💡 Cet outil analyse la cohérence mathématique de vos flux. Un solde négatif indique une donnée manquante ou erronée.")

    st.divider()
    show_status()

# Load Data
df_j, df_m = load_all_history()
history = compute_running_balances(df_j, df_m)

if history.empty:
    st.warning("Aucune donnée qualifiée trouvée. Assurez-vous d'avoir des journaux sanctuarisés dans le dossier 'sanctuarisation'.")
else:
    # --- Tab 1: Dashboard des Anomalies ---
    tab_dash, tab_tracer = st.tabs(["📊 Tableau de Bord des Anomalies", "🧪 Traceur de Flux"])

    with tab_dash:
        st.subheader("⚠️ Points de Rupture & Cessions Exclues")
        st.info("Les cessions listées ici ont un solde négatif au moment de l'opération. L'App 3 les exclut du calcul fiscal car leur VGP est incohérente.")

        # Detect where running bal < 0 (with a small epsilon for float precision)
        # Focus on Cessions first as they block App 3
        cessions_neg = history[(history["Running_Bal"] < -1e-8) & (history.get("Is_Cession", False))].copy()

        if not cessions_neg.empty:
            st.error(f"🚨 {len(cessions_neg)} cessions critiques détectées (Solde Négatif).")
            st.dataframe(
                cessions_neg[["Date", "Account", "Asset", "Amount", "Running_Bal", "Category"]],
                column_config={
                    "Running_Bal": st.column_config.NumberColumn("Solde Négatif", format="%.6f"),
                    "Amount": st.column_config.NumberColumn("Quantité Cédée", format="%.6f"),
                },
                width='stretch',
                hide_index=True
            )
            st.divider()

        st.subheader("📋 Liste des Ruptures (Premier Échec par Actif)")
        anomalies = history[history["Running_Bal"] < -1e-8].copy()

        if anomalies.empty:
            st.success("✨ Aucune rupture de solde détectée. Vos flux sont cohérents !")
        else:
            # Aggregate to show first occurrence per Asset/Account
            first_anomalies = anomalies.groupby(["Account", "Asset"]).first().reset_index()

            st.error(f"Attention : {len(first_anomalies)} comptes présentent des soldes négatifs.")

            st.dataframe(
                first_anomalies[["Account", "Asset", "Date", "Amount", "Running_Bal", "Category"]],
                column_config={
                    "Date": st.column_config.DatetimeColumn("Date de Rupture"),
                    "Running_Bal": st.column_config.NumberColumn("Solde au moment T", format="%.6f"),
                    "Amount": st.column_config.NumberColumn("Mouvement", format="%.6f"),
                },
                width='stretch',
                hide_index=True
            )

            st.divider()
            st.subheader("🛠️ Aide au Diagnostic")
            sel_ano = st.selectbox("Sélectionnez une anomalie pour analyser la cause",
                                   options=range(len(first_anomalies)),
                                   format_func=lambda x: f"{first_anomalies.iloc[x]['Asset']} sur {first_anomalies.iloc[x]['Account']}")

            if sel_ano is not None:
                ano_row = first_anomalies.iloc[sel_ano]
                asset = ano_row["Asset"]
                acc = ano_row["Account"]

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Analyse de l'anomalie sur {asset} :**")
                    if "Transfert" in str(ano_row["Category"]):
                        st.info(f"👉 **Scénario Probable : Transfert Orphelin.**\n\nVous avez déclaré un transfert de {asset} vers ce compte, mais l'entrée de fonds n'est pas précédée d'un achat ou d'un autre transfert entrant. Vérifiez si vous n'avez pas oublié de récolter le wallet source.")
                    elif "Manual" in str(ano_row["Source"]):
                        st.info(f"👉 **Scénario Probable : Stock Initial Incomplet.**\n\nLa position manuelle déclarée pour {asset} est inférieure aux sorties réelles. Vérifiez vos inventaires passés.")
                    else:
                        st.info(f"👉 **Scénario Probable : Achat ou Récompense manquante.**\n\nUne sortie de {asset} est détectée alors que le solde est nul. Avez-vous oublié de saisir un achat Fiat ou une récompense de staking ?")

                with col2:
                    st.markdown("**Actions Recommandées :**")
                    st.write(f"1. Ouvrez l'**App 2** pour l'année {ano_row['Date'].year}.")
                    st.write(f"2. Cherchez l'actif **{asset}** sur le compte **{acc}**.")
                    st.write("3. Vérifiez si toutes les entrées sont bien marquées 'Valide'.")
                    st.write("4. Si c'est un actif ancien, ajoutez une position initiale dans l'**App 0**.")

    with tab_tracer:
        st.subheader("🧪 Investigation Chronologique")
        st.write("Visualisez l'évolution précise du solde pour comprendre où se situe la faille.")

        all_accs = sorted(history["Account"].unique())
        sel_acc = st.selectbox("Choisir un compte", all_accs)

        relevant_assets = sorted(history[history["Account"] == sel_acc]["Asset"].unique())
        sel_asset = st.selectbox("Choisir un actif", relevant_assets)

        if sel_acc and sel_asset:
            tracer_df = history[(history["Account"] == sel_acc) & (history["Asset"] == sel_asset)].copy()

            # Styling for negative balances
            def style_negative(row):
                return ['background-color: #ffcccc' if row.Running_Bal < -1e-8 else '' for _ in row]

            st.dataframe(
                tracer_df[["Date", "Amount", "Running_Bal", "Category", "Counterparty", "Source"]].style.apply(style_negative, axis=1),
                column_config={
                    "Running_Bal": st.column_config.NumberColumn("Solde Progressif", format="%.8f"),
                    "Amount": st.column_config.NumberColumn("Quantité", format="%.8f"),
                    "Date": st.column_config.DatetimeColumn("Date"),
                },
                width='stretch'
            )

            # Mini chart
            st.area_chart(tracer_df, x="Date", y="Running_Bal")

st.sidebar.divider()
st.sidebar.caption("Diagnostic & Cohérence v1.0 - appDiagCoh")
