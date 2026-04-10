import os
import time
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Calcul VGP Pro (app2VGP)", layout="wide")
st.title("🧮 Calculateur de VGP Historique (Version Pro)")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"

# --- Cache Engine ---
def load_price_cache():
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w") as f:
        json.dump(cache, f)

# --- Helpers ---
def get_qualified_path(year):
    return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")

def get_price_eur(asset, date_obj):
    asset = str(asset).upper()
    if asset in ["EUR", "EURA", "AGEUR"]: return 1.0
    if asset in ["USDC", "USDT", "DAI", "USDC.E"]: return 0.92 # Approximation par défaut

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = load_price_cache()
    cache_key = f"{asset}_{d_str}"

    # Priorité au cache persistant
    if cache_key in cache:
        return float(cache[cache_key])

    # Sinon API CoinGecko
    asset_map = {
        "ETH": "ethereum", "BTC": "bitcoin", "POL": "polygon-ecosystem-token",
        "BNB": "binancecoin", "ARB": "arbitrum", "OP": "optimism", "WETH": "ethereum"
    }

    cg_id = asset_map.get(asset, asset.lower())
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/history?date={d_str}&localization=false"

    try:
        time.sleep(1.5) # Protection API gratuite
        res = requests.get(url, timeout=10)
        if res.status_code == 429:
            st.warning("⚠️ Rate limit API atteint. Attente 10s...")
            time.sleep(10)
            return get_price_eur(asset, date_obj)

        data = res.json()
        price = float(data["market_data"]["current_price"]["eur"])

        # Sauvegarde au cache
        cache[cache_key] = price
        save_price_cache(cache)
        return price
    except:
        return 0.0

def get_portfolio_snapshot(journal, target_date):
    # Filtrage : tout sauf Spam, pas de EUR, et avant ou à la date de cession
    df = journal[
        (journal["Status"] != "Spam") &
        (journal["Asset"] != "EUR") &
        (journal["Date"] <= target_date)
    ]
    if df.empty: return pd.DataFrame()

    # Calcul des balances
    balances = df.groupby("Asset")["Amount"].sum()
    balances = balances[balances.abs() > 1e-8]

    details = []
    total_vgp = 0.0
    for asset, qty in balances.items():
        price = get_price_eur(asset, target_date)
        valeur = qty * price
        total_vgp += valeur
        details.append({
            "Asset": asset,
            "Quantité": qty,
            "Prix (EUR)": price,
            "Valeur (EUR)": valeur
        })

    return pd.DataFrame(details), total_vgp

def is_imposable_robust(val):
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI"]

# --- UI sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année à traiter", min_value=2015, max_value=2030, value=datetime.now().year)

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

# --- Main logic ---
path = get_qualified_path(target_year)

if not os.path.exists(path):
    st.warning(f"📂 En attente de données : Le fichier '{os.path.basename(path)}' n'existe pas encore.")
    st.info("💡 Utilisez l'**App 2** pour synchroniser et sanctuariser vos premières données qualifiées.")
else:
    # Chargement journal
    journal = pd.read_csv(path)
    journal["Date"] = pd.to_datetime(journal["Date"], utc=True, errors="coerce")
    # Force numeric conversion
    for col in ["Amount", "Value ($)", "VGP (EUR)"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce").fillna(0.0)
        else:
            journal[col] = 0.0

    # Construction du masque de détection
    mask_imposable = journal["Imposable"].apply(is_imposable_robust) if use_imposable_col else pd.Series(False, index=journal.index)
    mask_category = journal["Category"].fillna("").str.contains("Vente", case=False) if use_category_vente else pd.Series(False, index=journal.index)

    mask_cessions = (mask_imposable | mask_category) & (journal["Asset"] != "EUR")
    cessions_all = journal[mask_cessions].copy()

    if cessions_all.empty:
        st.warning("⚠️ Aucune cession imposable détectée avec les critères actuels.")
        with st.expander("👀 Diagnostic : Voir tout le journal (pour vérifier les colonnes 'Imposable' / 'Category')"):
            st.write("Vérifiez dans l'**App 2** que vos ventes sont bien marquées comme 'Imposable' ou 'Vente'.")
            st.dataframe(journal, use_container_width=True)
    else:
        # 1. État des lieux
        nb_total = len(cessions_all)
        nb_manquant = len(cessions_all[cessions_all["VGP (EUR)"] <= 0])

        st.subheader(f"📈 Suivi des VGP ({nb_total} cessions au total)")
        col1, col2 = st.columns(2)
        col1.metric("Cessions identifiées", nb_total)
        col2.metric("VGP à calculer", nb_manquant, delta=-nb_manquant, delta_color="inverse")

        # 2. Boutons d'action
        if nb_manquant > 0:
            if st.button("🚀 Lancer le calcul automatique (Incrémental)", type="primary", use_container_width=True):
                pbar = st.progress(0)
                # On ne calcule que pour les manquants
                to_calc = cessions_all[cessions_all["VGP (EUR)"] <= 0]

                for idx, (i, row) in enumerate(to_calc.iterrows()):
                    _, vgp_val = get_portfolio_snapshot(journal, row["Date"])
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
            use_container_width=True,
            key="vgp_editor"
        )

        # Injection des modifs manuelles dans le journal principal
        if st.button("💾 Sanctuariser les VGP (Enregistrer sur disque)", use_container_width=True):
            journal.loc[mask_cessions, "VGP (EUR)"] = edited_cessions["VGP (EUR)"].values
            journal.to_csv(path, index=False)
            st.success(f"Journal mis à jour avec les VGP dans {path}")
            st.balloons()

        # 4. Audit détaillé
        st.divider()
        st.subheader("🔍 Audit : Détail du Portefeuille à une Date")
        selected_date = st.selectbox("Choisir une date de cession pour voir le détail", options=sorted(cessions_all["Date"].unique(), reverse=True))

        if selected_date:
            snapshot_df, total_val = get_portfolio_snapshot(journal, selected_date)
            if not snapshot_df.empty:
                st.write(f"Composition du portefeuille au **{selected_date}** :")
                st.dataframe(snapshot_df, use_container_width=True)
                st.metric("VGP Totale Calculée", f"{total_val:,.2f} €")
            else:
                st.warning("Aucun historique trouvé pour cette date.")

st.sidebar.divider()
st.sidebar.caption("Calculateur VGP Pro v2.0 - app2VGP")
