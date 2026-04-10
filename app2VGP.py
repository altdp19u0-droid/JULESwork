import os
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Calcul VGP (app2VGP)", layout="wide")
st.title("🧮 Calculateur de VGP Historique")

EXPORT_BASE_DIR = "sanctuarisation"

# --- Helpers ---
def get_qualified_path(year):
    return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")

@st.cache_data(ttl=86400)
def get_price_eur(asset, date_obj):
    if asset in ["EUR", "EURA", "AGEUR"]: return 1.0
    if asset in ["USDC", "USDT", "DAI"]: return 0.92 # Approximation par défaut

    asset_map = {
        "ETH": "ethereum", "BTC": "bitcoin", "POL": "polygon-ecosystem-token",
        "BNB": "binancecoin", "ARB": "arbitrum", "OP": "optimism"
    }

    id = asset_map.get(asset, asset.lower())
    d_str = date_obj.strftime("%d-%m-%Y")
    url = f"https://api.coingecko.com/api/v3/coins/{id}/history?date={d_str}&localization=false"

    try:
        time.sleep(1.5) # Rate limit protection
        res = requests.get(url, timeout=10).json()
        return res["market_data"]["current_price"]["eur"]
    except:
        return 0.0

def calculate_vgp(journal, target_date):
    # Filtrage : tout sauf Spam et avant la date de cession
    df = journal[(journal["Status"] != "Spam") & (journal["Date"] <= target_date)]
    if df.empty: return 0.0

    # Calcul des balances
    balances = df.groupby("Asset")["Amount"].sum()
    balances = balances[balances.abs() > 1e-8]

    total_vgp = 0.0
    for asset, qty in balances.items():
        price = get_price_eur(asset, target_date)
        total_vgp += qty * price

    return total_vgp

# --- UI sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année à traiter", min_value=2015, max_value=2030, value=datetime.now().year)

# --- Main ---
path = get_qualified_path(target_year)
if not os.path.exists(path):
    st.error(f"Fichier introuvable : {path}")
    st.stop()

journal = pd.read_csv(path)
journal["Date"] = pd.to_datetime(journal["Date"], utc=True, errors="coerce")
# Force numeric
journal["Amount"] = pd.to_numeric(journal["Amount"], errors="coerce").fillna(0.0)

# Identification des cessions
cessions = journal[
    (journal["Imposable"] == True) |
    (journal["Category"].str.contains("Vente", case=False, na=False))
].copy()

if cessions.empty:
    st.info("Aucune cession imposable détectée dans le journal.")
else:
    st.subheader(f"📈 Calcul des VGP pour {len(cessions)} cessions détectées")
    st.write("Le calcul peut prendre du temps en raison des limites de l'API CoinGecko (1.5s par requête).")

    if st.button("🚀 Lancer le calcul automatique des VGP"):
        pbar = st.progress(0)
        results = []

        for idx, (i, row) in enumerate(cessions.iterrows()):
            vgp = calculate_vgp(journal, row["Date"])
            results.append({"index": i, "VGP (EUR)": vgp})
            pbar.progress((idx + 1) / len(cessions))

        # Mise à jour du journal principal
        df_vgp = pd.DataFrame(results).set_index("index")
        journal.loc[df_vgp.index, "VGP (EUR)"] = df_vgp["VGP (EUR)"]

        st.session_state.journal_with_vgp = journal
        st.success("Calcul terminé !")

    if "journal_with_vgp" in st.session_state:
        st.subheader("📊 Aperçu des résultats")
        st.dataframe(st.session_state.journal_with_vgp[st.session_state.journal_with_vgp["VGP (EUR)"].notnull()])

        if st.button("💾 Enregistrer les VGP dans le journal qualifié"):
            st.session_state.journal_with_vgp.to_csv(path, index=False)
            st.success("Données VGP sanctuarisées dans le journal qualifié.")
            st.balloons()

st.sidebar.divider()
st.sidebar.caption("Calculateur VGP v1.0 - app2VGP")
