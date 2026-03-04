import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto Tracker Harvest Pro", layout="wide")

# Configuration des Réseaux (Architecture demandée)
NETWORKS_CFG = {
    "Ethereum": {"host": "api.etherscan.io", "native": "ETH", "free_api": "https://api.ethplorer.io"},
    "Polygon": {"host": "api.polygonscan.com", "native": "POL"},
    "Arbitrum": {"host": "api.arbiscan.io", "native": "ETH"},
    "Base": {"host": "api.basescan.org", "native": "ETH", "free_api": "https://base.blockscout.com/api/v2"},
    "Optimism": {"host": "api-optimistic.etherscan.io", "native": "ETH", "free_api": "https://optimism.blockscout.com/api/v2"},
    "BSC": {"host": "api.bscscan.com", "native": "BNB", "free_api": "https://api.bscscan.com/api"}
}

# --- Initialisation de la Session ---
REQUIRED_COLS = ['Source', 'ID', 'Date', 'Account', 'Asset', 'Type', 'Amount', 'Fee', 'Fiat_Value_EUR', 'Counterparty', 'Network', 'Is_Spam', 'Category']

if 'transactions' not in st.session_state or not all(c in st.session_state.transactions.columns for c in REQUIRED_COLS):
    st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
if 'accounts_metadata' not in st.session_state:
    st.session_state.accounts_metadata = {}
if 'fiat_accounts' not in st.session_state:
    st.session_state.fiat_accounts = pd.DataFrame(columns=['Date', 'Label', 'Amount_EUR', 'Type'])
if 'spam_addresses' not in st.session_state:
    st.session_state.spam_addresses = set()

# --- Fonctions de Prix & Conversion ---

@st.cache_data(ttl=86400)
def get_eur_usd_rate(date_obj):
    """ Taux EUR/USD via Frankfurter (BCE) """
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
        res = requests.get(url, timeout=5).json()
        return res["rates"]["EUR"]
    except: return 0.92

@st.cache_data(ttl=3600)
def get_price_usd(asset, date_obj):
    """ Prix USD via CoinGecko ou DeFiLlama """
    cg_map = {
        "ETH": "ethereum", "BNB": "binancecoin", "POL": "polygon-ecosystem-token",
        "USDT": "tether", "USDC": "usd-coin", "DAI": "dai",
        "EURA": "ageur", "AGEUR": "ageur", "STEUR": "stasis-euro",
        "8LND": "8lnd", "BTC": "bitcoin", "WBTC": "wrapped-bitcoin",
        "ARB": "arbitrum", "OP": "optimism", "MATIC": "matic-network"
    }
    asset_id = cg_map.get(asset.upper(), asset.lower())
    d_str = date_obj.strftime("%d-%m-%Y")

    # Try CoinGecko
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{asset_id}/history?date={d_str}&localization=false"
        res = requests.get(url, timeout=5).json()
        if "market_data" in res: return res["market_data"]["current_price"]["usd"]
    except: pass

    # Try DeFiLlama
    try:
        ts = int(time.mktime(date_obj.timetuple()))
        url = f"https://coins.llama.fi/prices/historical/{ts}/coingecko:{asset_id}"
        res = requests.get(url, timeout=5).json()
        if "coins" in res and res["coins"]:
            return res["coins"][next(iter(res["coins"]))]["price"]
    except: pass

    # Stablecoins fallback
    if asset.upper() in ["USDT", "USDC", "DAI"]: return 1.0
    if asset.upper() in ["EURA", "AGEUR", "STEUR"]: return 1.08 # Approx conversion if USD

    return 0.0

def get_price_eur(asset, date_obj):
    usd = get_price_usd(asset, date_obj)
    if usd == 0: return 0.0
    return usd * get_eur_usd_rate(date_obj)

# --- MOTEUR D'EXPLORATION ROBUSTE ---

def fetch_data(address, api_key, network):
    txs = []
    addr_low = address.lower()
    cfg = NETWORKS_CFG[network]

    report = st.expander(f"📡 Rapport de récolte : {network} ({address[:8]}...)", expanded=True)
    status_text = report.empty()
    counts = {"Native": 0, "Tokens": 0, "Internal": 0}

    # 1. VOIE LIBRE (Blockscout v2 / Ethplorer)
    try:
        if network == "Ethereum" and "free_api" in cfg:
            status_text.text("⏳ Exploration Ethplorer (Ethereum)...")
            url = f"{cfg['free_api']}/getAddressTransactions/{address}?apiKey=freekey&limit=1000"
            data = requests.get(url, timeout=10).json()
            if isinstance(data, list):
                for t in data:
                    txs.append({
                        'Source': 'Ethplorer (Libre)', 'ID': t['hash'],
                        'Date': datetime.fromtimestamp(int(t['timestamp'])),
                        'Account': address, 'Asset': 'ETH', 'Type': 'Mvt',
                        'Amount': float(t.get('value', 0)), 'Fee': 0.0,
                        'Counterparty': t.get('from', 'Unknown'), 'Network': network
                    })
                    counts["Native"] += 1

        elif "free_api" in cfg and "blockscout" in cfg["free_api"]:
            for endpoint, label in [("transactions", "Native"), ("token-transfers", "Tokens"), ("internal-transactions", "Internal")]:
                url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
                for page in range(40): # Cap à 2000 txs par type
                    try:
                        status_text.text(f"⏳ Voie Libre ({label}) : Page {page+1}...")
                        res = requests.get(url, timeout=10)
                        if res.status_code != 200: break
                        data = res.json()
                        items = data.get("items", [])
                        if not items: break

                        for t in items:
                            try:
                                # Correction Hash (Blockscout utilise souvent tx_hash pour les tokens)
                                tx_id = t.get('hash') or t.get('tx_hash')
                                if not tx_id: continue

                                # Parsing Asset & Amount
                                if endpoint == "token-transfers":
                                    tok = t.get('token', {})
                                    asset = tok.get('symbol', 'TOKEN')
                                    dec = int(tok.get('decimals', 18))
                                    amount = int(t.get('value', 0)) / 10**dec
                                else:
                                    asset = cfg['native']
                                    amount = int(t.get('value', 0)) / 10**18

                                # Timestamp
                                dt_str = t.get('timestamp', '')
                                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00')) if dt_str else datetime.now()

                                # Fees
                                fee = int(t.get('fee', {}).get('value', 0)) / 10**18 if t.get('fee') else 0.0

                                # Counterparty logic (Qui est à l'autre bout ?)
                                f_addr = t.get('from', {}).get('hash', 'Unknown').lower()
                                t_addr = t.get('to', {}).get('hash', 'Unknown').lower()
                                cp = f_addr if t_addr == addr_low else t_addr

                                txs.append({
                                    'Source': f'Libre ({label})', 'ID': tx_id, 'Date': dt,
                                    'Account': address, 'Asset': asset, 'Type': 'Mvt',
                                    'Amount': amount, 'Fee': fee, 'Counterparty': cp, 'Network': network
                                })
                                counts[label] += 1
                            except: continue

                        if data.get("next_page_params"):
                            q = "&".join([f"{k}={v}" for k, v in data["next_page_params"].items()])
                            url = f"{cfg['free_api']}/addresses/{address}/{endpoint}?{q}"
                        else: break
                    except: break
    except Exception as e: report.warning(f"Note Libre: {e}")

    # 2. VOIE API (Etherscan/BscScan etc)
    if api_key:
        try:
            for action, label in [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]:
                status_text.text(f"⏳ Voie API ({label}) en cours...")
                url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock=0&endblock=99999999&offset=10000&sort=desc&apikey={api_key}"
                res = requests.get(url, timeout=15).json()
                if str(res.get("status")) == "1":
                    for t in res.get("result", []):
                        try:
                            asset = t.get("tokenSymbol", cfg["native"]) if action == "tokentx" else cfg["native"]
                            dec = int(t.get("tokenDecimal", 18)) if action == "tokentx" else 18
                            amt = int(t.get("value", 0)) / 10**dec
                            fee = (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 10**18

                            f_addr = t.get('from', '').lower()
                            t_addr = t.get('to', '').lower()
                            cp = f_addr if t_addr == addr_low else t_addr

                            txs.append({
                                'Source': f'API ({label})', 'ID': t['hash'],
                                'Date': datetime.fromtimestamp(int(t['timeStamp'])),
                                'Account': address, 'Asset': asset, 'Type': 'Mvt',
                                'Amount': amt, 'Fee': fee, 'Counterparty': cp, 'Network': network
                            })
                            counts[label] += 1
                        except: continue
        except Exception as e: report.error(f"Erreur API: {e}")

    status_text.empty()
    report.write(f"📊 **Total récolté :** {counts['Native']} Native, {counts['Tokens']} Tokens, {counts['Internal']} Internes")

    df = pd.DataFrame(txs)
    if not df.empty:
        # Nettoyage
        df = df.drop_duplicates(subset=['ID', 'Asset', 'Amount'])

        # Valorisation EUR
        with st.spinner("Calcul des valeurs historiques EUR..."):
            unique_combos = df[['Asset', 'Date']].copy()
            unique_combos['Date_Key'] = unique_combos['Date'].dt.date
            unique_combos = unique_combos[['Asset', 'Date_Key']].drop_duplicates()
            prices_map = {}
            total_p = len(unique_combos)
            if total_p > 0:
                pbar = st.progress(0)
                for i, (_, row) in enumerate(unique_combos.iterrows()):
                    prices_map[(row['Asset'], row['Date_Key'])] = get_price_eur(row['Asset'], row['Date_Key'])
                    if total_p > 5: time.sleep(1.05) # Rate limit respect
                    pbar.progress((i+1)/total_p)
                pbar.empty()
            df['Fiat_Value_EUR'] = df.apply(lambda r: r['Amount'] * prices_map.get((r['Asset'], r['Date'].date()), 0.0), axis=1)

        # Classification & Spam
        df['Is_Spam'] = df['Counterparty'].apply(lambda x: str(x).lower() in st.session_state.spam_addresses)
        def detect_cat(row):
            cp, ass = str(row['Counterparty']).lower(), str(row['Asset']).lower()
            if any(x in cp for x in ['swap', 'pool', 'staking', 'lending', 'uniswap', 'aave', 'pancake', '1inch', '8lnd']): return 'DeFi'
            if any(x in ass for x in ['lp', 'steth', 'steur', 'lnd']): return 'Yield/Lp'
            return 'Transfert'
        df['Category'] = df.apply(detect_cat, axis=1)

    return df

# --- UI PRINCIPALE ---
st.sidebar.title("Jules Crypto Pro")
menu = st.sidebar.selectbox("Navigation", ["Harvest", "Consultation", "Frais & Fiscalité", "Spam & Settings", "Export"], key="main_nav")

if menu == "Harvest":
    st.header("🚜 Récolte Massive de Données")
    with st.form("harvest_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        addr = col1.text_input("Adresse Blockchain (0x...)")
        net = col2.selectbox("Réseau", list(NETWORKS_CFG.keys()))
        key = st.text_input(f"Clé API pour {net} (Optionnel)", type="password")
        submit = st.form_submit_button("Lancer la récolte (Libre + API)")

    if submit and addr:
        new_df = fetch_data(addr, key, net)
        if not new_df.empty:
            # Fusion intelligente : on privilégie les nouvelles données tout en évitant les doublons stricts
            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df])
            st.session_state.transactions = st.session_state.transactions.drop_duplicates(subset=['ID', 'Asset', 'Amount'], keep='first')
            st.session_state.transactions = st.session_state.transactions.sort_values('Date', ascending=False)

            st.session_state.accounts_metadata[f"{addr[:10]}... ({net})"] = {"Count": len(new_df)}
            st.success(f"Récolte réussie : {len(new_df)} lignes ajoutées.")
        else:
            st.warning("Aucune donnée trouvée.")

    if st.session_state.accounts_metadata:
        st.subheader("Comptes actifs")
        for acc, meta in list(st.session_state.accounts_metadata.items()):
            c1, c2 = st.columns([4, 1])
            c1.info(f"{acc} : {meta['Count']} transactions")
            if c2.button("Supprimer", key=f"del_{acc}"):
                del st.session_state.accounts_metadata[acc]
                st.rerun()

elif menu == "Consultation":
    st.header("🔍 Consultation des actifs")
    if not st.session_state.transactions.empty:
        df_view = st.session_state.transactions.copy()

        # Résumé des Actifs
        st.subheader("📦 Inventaire des Actifs")
        clean_df = df_view[df_view['Is_Spam'] == False]
        # On estime grossièrement la balance
        inventory = clean_df.groupby('Asset').agg({'Amount': 'sum', 'Fiat_Value_EUR': 'sum'}).reset_index()
        inventory = inventory[inventory['Amount'] > 0]

        inv_cols = st.columns(min(len(inventory), 4) if not inventory.empty else 1)
        for idx, row in inventory.iterrows():
            with inv_cols[idx % 4]:
                st.metric(row['Asset'], f"{row['Amount']:.4f}", f"{row['Fiat_Value_EUR']:,.2f} €")

        st.divider()

        # Filtres rapides
        f_col1, f_col2, f_col3 = st.columns(3)
        show_spam = f_col1.checkbox("Afficher le Spam", value=False)
        selected_asset = f_col2.multiselect("Filtrer par Asset", options=sorted(df_view['Asset'].unique()))

        if not show_spam:
            df_view = df_view[df_view['Is_Spam'] == False]
        if selected_asset:
            df_view = df_view[df_view['Asset'].isin(selected_asset)]

        st.data_editor(
            df_view.sort_values('Date', ascending=False),
            use_container_width=True,
            column_config={
                "Fiat_Value_EUR": st.column_config.NumberColumn("Valeur EUR", format="%.2f €"),
                "Amount": st.column_config.NumberColumn("Quantité", format="%.6f"),
                "Fee": st.column_config.NumberColumn("Frais", format="%.8f"),
                "Is_Spam": st.column_config.CheckboxColumn("Spam")
            }
        )
    else:
        st.info("Lancez d'abord une récolte dans le menu 'Harvest'.")

elif menu == "Frais & Fiscalité":
    st.header("⚖️ Bilan Fiscal & Frais")

    st.subheader("🏦 Gestion des comptes Fiat (Banque)")
    st.session_state.fiat_accounts = st.data_editor(
        st.session_state.fiat_accounts,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Type": st.column_config.SelectboxColumn("Type", options=["Dépôt", "Retrait", "Vente Crypto"]),
            "Amount_EUR": st.column_config.NumberColumn("Montant EUR", format="%.2f €")
        }
    )

    st.divider()
    df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]

    if not df.empty:
        total_fees = df['Fee'].sum()
        total_val = df['Fiat_Value_EUR'].sum()

        st.metric("Total Frais (Native)", f"{total_fees:.4f}")
        st.metric("Valeur Totale Portefeuille (Estimée EUR)", f"{total_val:,.2f} €")

        st.divider()
        st.subheader("Simulateur Article 150 VH bis")
        prix_acq = st.number_input("Prix d'acquisition total (EUR)", value=0.0)
        prix_vent = st.number_input("Montant de la cession (EUR)", value=0.0)

        if prix_vent > 0 and total_val > 0:
            # PV = Prix de vente - (Prix d'acquisition * (Prix de vente / Valeur totale portefeuille))
            pv = prix_vent - (prix_acq * (prix_vent / total_val))
            st.write(f"**Plus-value imposable :** {pv:,.2f} €")
            st.write(f"**Impôt estimé (Flat Tax 30%) :** {pv * 0.3:,.2f} €")
    else:
        st.info("Données insuffisantes pour le bilan.")

elif menu == "Export":
    st.header("📥 Export des données")
    if not st.session_state.transactions.empty:
        csv = st.session_state.transactions.to_csv(index=False).encode('utf-8')
        st.download_button("Télécharger l'historique complet (CSV)", csv, "crypto_harvest_export.csv", "text/csv")

        st.subheader("Aperçu JSON (pour développeurs)")
        st.json(st.session_state.transactions.head(10).to_dict(orient='records'))
    else:
        st.info("Rien à exporter.")

elif menu == "Spam & Settings":
    st.header("⚙️ Paramètres & Spam")
    spam_input = st.text_area("Ajouter des adresses de Spam (une par ligne)")
    if st.button("Mettre à jour la liste noire"):
        new_spams = [s.strip().lower() for s in spam_input.split("\n") if s.strip()]
        st.session_state.spam_addresses.update(new_spams)
        # Marquer les transactions existantes
        if not st.session_state.transactions.empty:
            st.session_state.transactions['Is_Spam'] = st.session_state.transactions['Counterparty'].apply(lambda x: str(x).lower() in st.session_state.spam_addresses)
        st.success("Liste de spam mise à jour.")

    if st.button("Vider toute la base de données"):
        st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
        st.session_state.accounts_metadata = {}
        st.rerun()

st.sidebar.divider()
st.sidebar.caption("Jules AI Harvest Pro v2.1")
