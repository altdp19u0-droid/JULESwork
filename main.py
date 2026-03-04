import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto Tracker Harvest Pro", layout="wide")

# Configuration des Réseaux et Explorateurs
NETWORKS_CFG = {
    "Ethereum": {"host": "api.etherscan.io", "native": "ETH", "free_reader": "Ethplorer", "free_api": "https://api.ethplorer.io"},
    "Base": {"host": "api.basescan.org", "native": "ETH", "free_reader": "Blockscout", "free_api": "https://base.blockscout.com/api/v2"},
    "Arbitrum": {"host": "api.arbiscan.io", "native": "ETH", "free_reader": "Blockscout", "free_api": "https://arbitrum.blockscout.com/api/v2"},
    "BSC": {"host": "api.bscscan.com", "native": "BNB", "free_reader": "BscScan", "free_api": "https://api.bscscan.com/api"},
    "Polygon": {"host": "api.polygonscan.com", "native": "POL", "free_reader": "Blockscout", "free_api": "https://polygon.blockscout.com/api/v2"},
    "Optimism": {"host": "api-optimistic.etherscan.io", "native": "ETH", "free_reader": "Blockscout", "free_api": "https://optimism.blockscout.com/api/v2"}
}

# --- Initialisation Session ---
REQUIRED_COLS = ['Source', 'ID', 'Date', 'Account', 'Asset', 'Type', 'Amount', 'Fee', 'Fiat_Value_EUR', 'Counterparty', 'Network', 'Is_Spam', 'Category']
if 'transactions' not in st.session_state: st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
if 'accounts_metadata' not in st.session_state: st.session_state.accounts_metadata = {}
if 'fiat_accounts' not in st.session_state: st.session_state.fiat_accounts = pd.DataFrame(columns=['Date', 'Label', 'Amount_EUR', 'Type'])
if 'spam_addresses' not in st.session_state: st.session_state.spam_addresses = set()

# --- Fonctions de Prix ---
@st.cache_data(ttl=3600)
def get_price(asset, date_obj):
    try:
        cg_map = {"ETH": "ethereum", "BNB": "binancecoin", "POL": "polygon-ecosystem-token", "USDT": "tether", "USDC": "usd-coin", "EURA": "eura", "STEUR": "stasis-euro", "8LND": "8lnd", "BTC": "bitcoin"}
        asset_id = cg_map.get(asset.upper(), asset.lower())
        d_str = date_obj.strftime("%d-%m-%Y")
        res = requests.get(f"https://api.coingecko.com/api/v3/coins/{asset_id}/history?date={d_str}&localization=false", timeout=5).json()
        if "market_data" in res: return res["market_data"]["current_price"]["eur"]
        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={asset_id}&vs_currencies=eur", timeout=5).json()
        return res.get(asset_id, {}).get("eur", 1.0)
    except: return 1.0

# --- MOTEUR D'EXPLORATION ---
def fetch_data(address, api_key, network):
    txs = []
    addr_low = address.lower()
    cfg = NETWORKS_CFG[network]
    counts = {"free": 0, "api": 0}
    status = st.empty()

    # 1. VOIE LIBRE (Blockscout / Ethplorer)
    try:
        if network == "Ethereum":
            url = f"{cfg['free_api']}/getAddressTransactions/{address}?apiKey=freekey&limit=500"
            data = requests.get(url, timeout=10).json()
            if isinstance(data, list):
                counts["free"] += len(data)
                for t in data:
                    txs.append({'Source': 'Libre (Ethplorer)', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timestamp'])), 'Account': address, 'Asset': 'ETH', 'Type': 'Mvt', 'Amount': float(t.get('value', 0)), 'Fee': 0.0, 'Counterparty': t['from'], 'Network': network})
        elif "blockscout" in cfg['free_api']:
            # Blockscout API v2 - Native + Tokens ERC20 + Internal
            for sub in ["transactions", "token-transfers", "internal-transactions"]:
                url = f"{cfg['free_api']}/addresses/{address}/{sub}"
                # Augmentation à 40 pages pour viser ~1000+ transactions (Blockscout v2 renvoie souvent 25-50 items/page)
                for page in range(40):
                    try:
                        data = requests.get(url, timeout=10).json()
                        if "items" in data:
                            items = data["items"]
                            if not items: break
                            counts["free"] += len(items)
                            for t in items:
                                # Détection fine de l'asset
                                tok = t.get('token', {}) if sub == "token-transfers" else {}
                                asset = tok.get('symbol', cfg['native'])
                                dec = int(tok.get('decimals', 18))

                                # Date
                                dt_str = t.get('timestamp')
                                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00')) if dt_str else datetime.now()

                                # Montant et Frais
                                val = int(t.get('value', 0)) / 10**dec
                                fee_val = int(t.get('fee', {}).get('value', 0)) / 10**18

                                txs.append({
                                    'Source': f'Libre ({sub})', 'ID': t['hash'], 'Date': dt,
                                    'Account': address, 'Asset': asset, 'Type': 'Mvt',
                                    'Amount': val, 'Fee': fee_val,
                                    'Counterparty': t.get('from', {}).get('hash', 'Unknown'),
                                    'Network': network
                                })

                            # Pagination Blockscout v2
                            if data.get("next_page_params"):
                                p = data["next_page_params"]
                                q = "&".join([f"{k}={v}" for k, v in p.items()])
                                url = f"{cfg['free_api']}/addresses/{address}/{sub}?{q}"
                            else: break
                        else: break
                    except: break
    except Exception as e:
        # Remplacement de st.debug inexistant par un avertissement discret
        st.write(f"ℹ️ Info Libre {network}: {e}")

    # 2. VOIE API (Multi-Assets)
    if api_key:
        try:
            for action in ["txlist", "tokentx", "txlistinternal"]:
                url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock=0&endblock=99999999&offset=10000&sort=desc&apikey={api_key}"
                res = requests.get(url, timeout=15).json()
                if str(res.get("status")) == "1":
                    results = res.get("result", [])
                    counts["api"] += len(results)
                    for t in results:
                        asset = t.get("tokenSymbol", cfg["native"]) if action == "tokentx" else cfg["native"]
                        dec = int(t.get("tokenDecimal", 18)) if action == "tokentx" else 18
                        gas_u = int(t.get('gasUsed', 0)); gas_p = int(t.get('gasPrice', 0))
                        txs.append({
                            'Source': f'API ({action})', 'ID': t['hash'],
                            'Date': datetime.fromtimestamp(int(t['timeStamp'])),
                            'Account': address, 'Asset': asset,
                            'Type': 'Réception' if t.get('to','').lower()==addr_low else 'Envoi',
                            'Amount': int(t["value"])/10**dec, 'Fee': (gas_u * gas_p)/10**18,
                            'Counterparty': t['from'] if t.get('to','').lower()==addr_low else t.get('to',''),
                            'Network': network
                        })
        except Exception as e:
            st.write(f"ℹ️ Info API {network}: {e}")

    status.info(f"📊 Récolte {network} : {counts['free']} (Libre) | {counts['api']} (API)")
    df = pd.DataFrame(txs)
    if not df.empty:
        df = df.drop_duplicates(subset=['ID', 'Asset'])
        # Optimisation des prix : on groupe par jour et asset pour limiter les appels API
        with st.spinner("Récupération optimisée des prix historiques..."):
            unique_assets_dates = df[['Asset', 'Date']].copy()
            unique_assets_dates['Date_Key'] = unique_assets_dates['Date'].dt.date
            unique_combos = unique_assets_dates[['Asset', 'Date_Key']].drop_duplicates()

            prices_map = {}
            progress_text = "Calcul des cours..."
            my_bar = st.progress(0, text=progress_text)
            total = len(unique_combos)

            for i, (_, row) in enumerate(unique_combos.iterrows()):
                key = (row['Asset'], row['Date_Key'])
                prices_map[key] = get_price(row['Asset'], row['Date_Key'])
                # Respect du rate limit CoinGecko Free (env 1 call/sec recommandé)
                if total > 5:
                    time.sleep(1.1)
                my_bar.progress((i + 1) / total, text=f"Calcul des cours ({i+1}/{total})...")
            my_bar.empty()

            df['Fiat_Value_EUR'] = df.apply(lambda r: r['Amount'] * prices_map.get((r['Asset'], r['Date'].date()), 1.0), axis=1)
        df['Is_Spam'] = df['Counterparty'].apply(lambda x: x in st.session_state.spam_addresses)
        def detect_cat(row):
            cp, ass = str(row['Counterparty']).lower(), str(row['Asset']).lower()
            if any(x in cp for x in ['swap', 'pool', 'staking', 'lending', 'uniswap']): return 'Position DeFi'
            if any(x in ass for x in ['steth', 'steur', 'lnd', 'savings']): return 'Position DeFi (Asset)'
            return 'Transfert Direct'
        df['Category'] = df.apply(detect_cat, axis=1)
    return df

# --- UI Sidebar ---
st.sidebar.title("Bonjour !")
menu = st.sidebar.selectbox("Navigation", ["Dashboard", "Consultation & Analyse", "Fiat & Fiscalité", "Export"])

if menu == "Dashboard":
    st.header("📋 Tableau de bord")
    col_d1, col_d2 = st.columns([3, 1])
    with col_d1:
        with st.form("add"):
            c1, c2 = st.columns(2)
            addr_in = c1.text_input("Adresse (0x...)"); net_in = c2.selectbox("Réseau", list(NETWORKS_CFG.keys()))
            key_in = st.text_input(f"Clé API {net_in}", type="password")
            if st.form_submit_button("Lancer l'exploration"):
                if addr_in:
                    df = fetch_data(addr_in, key_in, net_in)
                    st.session_state.accounts_metadata[f"{addr_in} ({net_in})"] = {"Txs": len(df), "Réseau": net_in}
                    st.session_state.transactions = pd.concat([st.session_state.transactions, df]).drop_duplicates(subset=['ID', 'Asset'])
                    st.success("Exploration terminée !")
    with col_d2:
        if st.button("🗑️ Réinitialiser tout"):
            st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
            st.session_state.accounts_metadata = {}; st.rerun()

    if st.session_state.accounts_metadata:
        for acc_id, meta in list(st.session_state.accounts_metadata.items()):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{acc_id}** | {meta['Txs']} transactions récoltées")
            if c2.button("Supprimer", key=acc_id):
                del st.session_state.accounts_metadata[acc_id]
                st.session_state.transactions = st.session_state.transactions[st.session_state.transactions['Account'] != acc_id.split(' ')[0]]
                st.rerun()

elif menu == "Consultation & Analyse":
    st.header("🔍 Consultation")
    if not st.session_state.transactions.empty:
        df = st.session_state.transactions.copy()
        # Filtres
        c1, c2, c3 = st.columns(3)
        f_net = c1.multiselect("Réseaux", df['Network'].unique())
        f_asset = c2.multiselect("Assets", df['Asset'].unique())
        if f_net: df = df[df['Network'].isin(f_net)]
        if f_asset: df = df[df['Asset'].isin(f_asset)]

        df['Is_Spam'] = df['Counterparty'].apply(lambda x: x in st.session_state.spam_addresses)
        edited = st.data_editor(df, use_container_width=True, column_config={"Is_Spam": st.column_config.CheckboxColumn("Spam"), "Fiat_Value_EUR": st.column_config.NumberColumn("Valeur EUR", format="%.2f €"), "Fee": st.column_config.NumberColumn("Frais", format="%.8f")})
        for s in edited[edited['Is_Spam']==True]['Counterparty'].unique():
            if s not in st.session_state.spam_addresses: st.session_state.spam_addresses.add(s); st.rerun()
    else: st.info("Aucune donnée.")

elif menu == "Fiat & Fiscalité":
    st.header("⚖️ Fiat & Fiscalité France")
    st.session_state.fiat_accounts = st.data_editor(st.session_state.fiat_accounts, num_rows="dynamic", use_container_width=True, column_config={"Type": st.column_config.SelectboxColumn("Type", options=["Dépôt", "Retrait", "Vente Crypto"])})
    investi = st.session_state.fiat_accounts[st.session_state.fiat_accounts['Type']=='Dépôt']['Amount_EUR'].sum()
    retire = st.session_state.fiat_accounts[st.session_state.fiat_accounts['Type']=='Retrait']['Amount_EUR'].sum()
    clean = st.session_state.transactions[~st.session_state.transactions['Counterparty'].isin(st.session_state.spam_addresses)]
    port_val = clean['Fiat_Value_EUR'].sum()
    c1, c2 = st.columns(2)
    c1.metric("Prix d'acquisition Net", f"{investi - retire:,.2f} €")
    c2.metric("Valeur Portefeuille (Historique)", f"{port_val:,.2f} €")
    cession = st.number_input("Simulation de cession", 0.0)
    if cession > 0 and port_val > 0:
        pv = cession - ((investi-retire) * (cession / port_val))
        st.success(f"Plus-value : {pv:,.2f} € | Impôt estimé (30%) : {pv*0.3:,.2f} €")

elif menu == "Export":
    st.header("📥 Exports"); v = st.session_state.transactions[~st.session_state.transactions['Counterparty'].isin(st.session_state.spam_addresses)]
    st.download_button("Exporter Valides", v.to_csv(index=False).encode('utf-8'), "mon_historique.csv")

st.divider(); st.caption("Jules AI Ultimate Pro - Windows 11")
