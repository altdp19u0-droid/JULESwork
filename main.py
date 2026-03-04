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

if 'transactions' not in st.session_state:
    st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
if 'accounts_metadata' not in st.session_state:
    st.session_state.accounts_metadata = {}
if 'fiat_accounts' not in st.session_state:
    st.session_state.fiat_accounts = pd.DataFrame(columns=['Date', 'Label', 'Amount_EUR', 'Type'])
if 'spam_addresses' not in st.session_state:
    st.session_state.spam_addresses = set()

# --- Fonctions de Prix & Conversion (Triple Source) ---

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
    cg_map = {"ETH": "ethereum", "BNB": "binancecoin", "POL": "polygon-ecosystem-token", "USDT": "tether", "USDC": "usd-coin", "EURA": "eura", "STEUR": "stasis-euro", "8LND": "8lnd", "BTC": "bitcoin"}
    asset_id = cg_map.get(asset.upper(), asset.lower())
    d_str = date_obj.strftime("%d-%m-%Y")
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{asset_id}/history?date={d_str}&localization=false"
        res = requests.get(url, timeout=5).json()
        if "market_data" in res: return res["market_data"]["current_price"]["usd"]
    except: pass
    try:
        url = f"https://coins.llama.fi/prices/historical/{int(date_obj.timestamp())}/coingecko:{asset_id}"
        res = requests.get(url, timeout=5).json()
        if "coins" in res: return res["coins"][next(iter(res["coins"]))]["price"]
    except: pass
    return 1.0

def get_price_eur(asset, date_obj):
    return get_price_usd(asset, date_obj) * get_eur_usd_rate(date_obj)

# --- MOTEUR D'EXPLORATION MASSIVE ---

def fetch_data(address, api_key, network):
    txs = []
    addr_low = address.lower()
    cfg = NETWORKS_CFG[network]

    report = st.expander(f"📡 Rapport de récolte Blockchain : {network}", expanded=True)
    c_libre = {"Native": 0, "Tokens": 0, "Internal": 0}
    c_api = {"Native": 0, "Tokens": 0, "Internal": 0}

    # 1. VOIE LIBRE (Ethplorer / Blockscout)
    try:
        if network == "Ethereum" and "free_api" in cfg:
            url = f"{cfg['free_api']}/getAddressTransactions/{address}?apiKey=freekey&limit=1000"
            data = requests.get(url, timeout=10).json()
            if isinstance(data, list):
                c_libre["Native"] = len(data)
                for t in data:
                    txs.append({'Source': 'Ethplorer (Libre)', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timestamp'])), 'Account': address, 'Asset': 'ETH', 'Type': 'Mvt', 'Amount': float(t.get('value', 0)), 'Fee': 0.0, 'Counterparty': t['from'], 'Network': network})
        elif "free_api" in cfg and "blockscout" in cfg["free_api"]:
            # PAGINATION JUSQU'A 1000 TXs
            for sub in [("transactions", "Native"), ("token-transfers", "Tokens"), ("internal-transactions", "Internal")]:
                endpoint, label = sub
                url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
                for page in range(20):
                    try:
                        data = requests.get(url, timeout=10).json()
                        if "items" in data:
                            items = data["items"]
                            if not items: break
                            c_libre[label] += len(items)
                            for t in items:
                                # Parsing Tokens vs Native
                                if endpoint == "token-transfers":
                                    tok = t.get('token', {})
                                    asset = tok.get('symbol', 'TOKEN')
                                    dec = int(tok.get('decimals', 18))
                                    amount = int(t.get('value', 0)) / 10**dec
                                else:
                                    asset = cfg['native']
                                    amount = int(t.get('value', 0)) / 10**18
                                fee = int(t.get('fee', {}).get('value', 0)) / 10**18
                                dt = datetime.fromisoformat(t['timestamp'].replace('Z', '+00:00'))
                                txs.append({'Source': f'Blockscout ({label})', 'ID': t['hash'], 'Date': dt, 'Account': address, 'Asset': asset, 'Type': 'Mvt', 'Amount': amount, 'Fee': fee, 'Counterparty': t.get('from', {}).get('hash', 'Unknown'), 'Network': network})
                            if data.get("next_page_params"):
                                q = "&".join([f"{k}={v}" for k, v in data["next_page_params"].items()])
                                url = f"{cfg['free_api']}/addresses/{address}/{endpoint}?{q}"
                            else: break
                        else: break
                    except: break
    except Exception as e: report.warning(f"Note Libre: {e}")

    # 2. VOIE API
    if api_key:
        try:
            for act in [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]:
                action, label = act
                url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock=0&endblock=99999999&offset=10000&sort=desc&apikey={api_key}"
                res = requests.get(url, timeout=15).json()
                if str(res.get("status")) == "1":
                    results = res.get("result", [])
                    c_api[label] += len(results)
                    for t in results:
                        asset = t.get("tokenSymbol", cfg["native"]) if action == "tokentx" else cfg["native"]
                        dec = int(t.get("tokenDecimal", 18)) if action == "tokentx" else 18
                        amt = int(t.get("value", 0)) / 10**dec
                        fee = (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 10**18
                        txs.append({'Source': f'API ({label})', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timeStamp'])), 'Account': address, 'Asset': asset, 'Type': 'Mvt', 'Amount': amt, 'Fee': fee, 'Counterparty': t['from'] if t.get('to','').lower()==addr_low else t.get('to',''), 'Network': network})
                elif res.get("message") == "NOTOK":
                    report.error(f"❌ Erreur API {network} ({label}) : {res.get('result')}")
        except Exception as e: report.error(f"Erreur API: {e}")

    report.write(f"✅ **Voie Libre :** {c_libre['Native']} Native, {c_libre['Tokens']} Tokens, {c_libre['Internal']} Internes")
    report.write(f"✅ **Voie API :** {c_api['Native']} Native, {c_api['Tokens']} Tokens, {c_api['Internal']} Internes")

    df = pd.DataFrame(txs)
    if not df.empty:
        df = df.drop_duplicates(subset=['ID', 'Asset', 'Amount'])
        with st.spinner("Synchronisation des cours EUR historiques..."):
            unique_combos = df[['Asset', 'Date']].copy()
            unique_combos['Date_Key'] = unique_combos['Date'].dt.date
            unique_combos = unique_combos[['Asset', 'Date_Key']].drop_duplicates()
            prices_map = {}
            total_p = len(unique_combos)
            if total_p > 0:
                pbar = st.progress(0)
                for i, (_, row) in enumerate(unique_combos.iterrows()):
                    prices_map[(row['Asset'], row['Date_Key'])] = get_price_eur(row['Asset'], row['Date_Key'])
                    if total_p > 5: time.sleep(1.1)
                    pbar.progress((i+1)/total_p)
                pbar.empty()
            df['Fiat_Value_EUR'] = df.apply(lambda r: r['Amount'] * prices_map.get((r['Asset'], r['Date'].date()), 1.0), axis=1)

        df['Is_Spam'] = df['Counterparty'].apply(lambda x: x in st.session_state.spam_addresses)
        def detect_cat(row):
            cp, ass = str(row['Counterparty']).lower(), str(row['Asset']).lower()
            if any(x in cp for x in ['swap', 'pool', 'staking', 'lending', 'uniswap', 'aave', 'pancake', '1inch', '8lnd', 'compound']): return 'Position DeFi'
            if any(x in ass for x in ['steth', 'steur', 'lnd', 'lp']): return 'Position DeFi (Asset)'
            return 'Transfert Direct'
        df['Category'] = df.apply(detect_cat, axis=1)
    return df

# --- UI ---
st.sidebar.title("Bonjour !")
menu = st.sidebar.selectbox("Navigation", ["Dashboard", "Consultation & Spam", "Fiat & Fiscalité", "Export"])

if menu == "Dashboard":
    st.header("📋 Tableau de bord")
    col1, col2 = st.columns([3, 1])
    with col1:
        with st.form("add_acc"):
            c_a, c_n = st.columns(2)
            a_in = c_a.text_input("Adresse (0x...)"); n_in = c_n.selectbox("Réseau", list(NETWORKS_CFG.keys()))
            k_in = st.text_input(f"Clé API {n_in} (Optionnelle)", type="password")
            if st.form_submit_button("Lancer l'exploration massive"):
                if a_in:
                    df = fetch_data(a_in, k_in, n_in)
                    st.session_state.accounts_metadata[f"{a_in} ({n_in})"] = {"Txs": len(df), "Réseau": n_in}
                    st.session_state.transactions = pd.concat([st.session_state.transactions, df]).drop_duplicates(subset=['ID', 'Asset', 'Amount'])
                    st.success("Exploration terminée !")
    with col2:
        if st.button("🗑️ Réinitialiser"):
            st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
            st.session_state.accounts_metadata = {}; st.rerun()
    if st.session_state.accounts_metadata:
        for acc_id, meta in list(st.session_state.accounts_metadata.items()):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{acc_id}** | {meta['Txs']} transactions récoltées")
            if c2.button("Supprimer", key=acc_id): del st.session_state.accounts_metadata[acc_id]; st.rerun()

elif menu == "Consultation & Spam":
    st.header("🔍 Consultation & Analyse")
    if not st.session_state.transactions.empty:
        df = st.session_state.transactions.copy()
        df['Is_Spam'] = df['Counterparty'].apply(lambda x: x in st.session_state.spam_addresses)
        edited = st.data_editor(df, use_container_width=True, column_config={
            "Is_Spam": st.column_config.CheckboxColumn("Spam"),
            "Fiat_Value_EUR": st.column_config.NumberColumn("Valeur EUR", format="%.2f €"),
            "Fee": st.column_config.NumberColumn("Frais", format="%.8f")
        })
        for s in edited[edited['Is_Spam']==True]['Counterparty'].unique():
            if s not in st.session_state.spam_addresses: st.session_state.spam_addresses.add(s); st.rerun()
    else: st.info("Aucune donnée.")

elif menu == "Fiat & Fiscalité":
    st.header("⚖️ Fiscalité France")
    st.session_state.fiat_accounts = st.data_editor(st.session_state.fiat_accounts, num_rows="dynamic", use_container_width=True, column_config={"Type": st.column_config.SelectboxColumn("Type", options=["Dépôt", "Retrait", "Vente Crypto"])})
    investi = st.session_state.fiat_accounts[st.session_state.fiat_accounts['Type']=='Dépôt']['Amount_EUR'].sum()
    retire = st.session_state.fiat_accounts[st.session_state.fiat_accounts['Type']=='Retrait']['Amount_EUR'].sum()
    clean = st.session_state.transactions[~st.session_state.transactions['Counterparty'].isin(st.session_state.spam_addresses)]
    port_val = clean['Fiat_Value_EUR'].sum()
    col_m1, col_m2 = st.columns(2)
    col_m1.metric("Acquisition Nette", f"{investi - retire:,.2f} €")
    col_m2.metric("Valeur Portefeuille", f"{port_val:,.2f} €")
    cession = st.number_input("Montant cession (EUR)", 0.0)
    if cession > 0 and port_val > 0:
        pv = cession - ((investi-retire) * (cession / port_val))
        st.success(f"Plus-value : {pv:,.2f} € | Impôt estimé (30%) : {pv*0.3:,.2f} €")

elif menu == "Export":
    st.header("📥 Exports"); v = st.session_state.transactions[~st.session_state.transactions['Counterparty'].isin(st.session_state.spam_addresses)]
    st.download_button("Exporter Valides (CSV)", v.to_csv(index=False).encode('utf-8'), "historique_complet.csv")

st.divider(); st.caption("Jules AI Harvest Pro - Multi-Chain Ultimate - Windows 11")
