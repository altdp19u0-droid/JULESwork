import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto Tracker Harvest Pro", layout="wide")

# Configuration des Réseaux
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

# Sanity check: conversion systématique en datetime
if not st.session_state.transactions.empty:
    st.session_state.transactions['Date'] = pd.to_datetime(st.session_state.transactions['Date'], utc=True, errors='coerce')

if 'accounts_metadata' not in st.session_state:
    st.session_state.accounts_metadata = {}
if 'fiat_accounts' not in st.session_state:
    st.session_state.fiat_accounts = pd.DataFrame(columns=['Date', 'Label', 'Amount_EUR', 'Type'])
if 'spam_addresses' not in st.session_state:
    st.session_state.spam_addresses = set()

# --- Fonctions de Prix & Conversion ---

@st.cache_data(ttl=86400)
def get_eur_usd_rate(date_obj):
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
        res = requests.get(url, timeout=5).json()
        return res["rates"]["EUR"]
    except: return 0.92

@st.cache_data(ttl=3600)
def get_price_usd(asset, date_obj):
    # Sécurité absolue contre les NoneType ou valeurs non-str
    if asset is None or not isinstance(asset, str) or not asset.strip():
        return 0.0

    asset = asset.upper().strip()
    cg_map = {
        "ETH": "ethereum", "BNB": "binancecoin", "POL": "polygon-ecosystem-token",
        "USDT": "tether", "USDC": "usd-coin", "DAI": "dai",
        "EURA": "ageur", "AGEUR": "ageur", "STEUR": "stasis-euro",
        "8LND": "8lnd", "BTC": "bitcoin", "WBTC": "wrapped-bitcoin",
        "ARB": "arbitrum", "OP": "optimism", "MATIC": "matic-network"
    }
    asset_id = cg_map.get(asset, asset.lower())
    d_str = date_obj.strftime("%d-%m-%Y")

    try:
        url = f"https://api.coingecko.com/api/v3/coins/{asset_id}/history?date={d_str}&localization=false"
        res = requests.get(url, timeout=5).json()
        if "market_data" in res: return res["market_data"]["current_price"]["usd"]
    except: pass

    try:
        ts = int(time.mktime(date_obj.timetuple()))
        url = f"https://coins.llama.fi/prices/historical/{ts}/coingecko:{asset_id}"
        res = requests.get(url, timeout=5).json()
        if "coins" in res and res["coins"]:
            return res["coins"][next(iter(res["coins"]))]["price"]
    except: pass

    if asset in ["USDT", "USDC", "DAI"]: return 1.0
    if asset in ["EURA", "AGEUR", "STEUR"]: return 1.08
    return 0.0

def get_price_eur(asset, date_obj):
    usd = get_price_usd(asset, date_obj)
    if usd == 0: return 0.0
    return usd * get_eur_usd_rate(date_obj)

# --- MOTEUR D'EXPLORATION ROBUSTE (V2.4) ---

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
            status_text.text("⏳ Exploration Ethplorer...")
            url = f"{cfg['free_api']}/getAddressTransactions/{address}?apiKey=freekey&limit=1000"
            data = requests.get(url, timeout=10).json()
            if isinstance(data, list):
                for t in data:
                    txs.append({
                        'Source': 'Ethplorer', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timestamp'])),
                        'Account': address, 'Asset': 'ETH', 'Type': 'Mvt', 'Amount': float(t.get('value', 0)),
                        'Fee': 0.0, 'Counterparty': t.get('from', 'Unknown'), 'Network': network
                    })
                    counts["Native"] += 1

        elif "free_api" in cfg and "blockscout" in cfg["free_api"]:
            endpoints = [
                ("transactions", "Native"),
                ("token-transfers", "Tokens"),
                ("internal-transactions", "Internal"),
                ("token-balances", "Balances")
            ]
            for endpoint, label in endpoints:
                url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
                for page in range(40):
                    try:
                        status_text.text(f"⏳ Voie Libre ({label}) : Page {page+1}...")
                        res = requests.get(url, timeout=15)
                        if res.status_code == 404 and endpoint == "token-balances":
                            url = f"{cfg['free_api']}/addresses/{address}/tokens"
                            res = requests.get(url, timeout=15)

                        if res.status_code != 200: break

                        try:
                            data = res.json()
                        except: break

                        # Gérer liste vs dict
                        items = data if isinstance(data, list) else data.get("items", data.get("result", []))
                        if not items or not isinstance(items, list): break

                        for t in items:
                            try:
                                if not isinstance(t, dict): continue
                                tx_id = t.get('hash') or t.get('tx_hash')

                                if label == "Balances":
                                    tok = t.get('token') or {}
                                    asset_name = tok.get('symbol') or tok.get('name') or 'TOKEN'
                                    dec = int(tok.get('decimals') or 18)
                                    amount = float(t.get('value') or '0') / 10**dec
                                    if amount <= 0: continue
                                    tx_id = f"DISCOVERY-{asset_name}-{address[:8]}"
                                    dt = datetime.now()
                                    direction = 1
                                else:
                                    if not tx_id: continue
                                    if label == "Tokens":
                                        tok = t.get('token') or {}
                                        asset_name = tok.get('symbol') or tok.get('name') or 'TOKEN'
                                        dec = int(tok.get('decimals') or 18)
                                        amount = float(t.get('value') or '0') / 10**dec
                                    else:
                                        asset_name = cfg['native']
                                        amount = float(t.get('value') or '0') / 10**18

                                    dt_str = t.get('timestamp') or t.get('timeStamp')
                                    dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00')) if dt_str and not str(dt_str).isdigit() else datetime.fromtimestamp(int(dt_str)) if dt_str else datetime.now()

                                    f_raw = t.get('from')
                                    t_raw = t.get('to')
                                    f_addr = (f_raw.get('hash') if isinstance(f_raw, dict) else f_raw or 'Unknown').lower()
                                    t_addr = (t_raw.get('hash') if isinstance(t_raw, dict) else t_raw or 'Unknown').lower()
                                    direction = 1 if t_addr == addr_low else -1
                                    cp = f_addr if direction == 1 else t_addr

                                fee_val = (t.get('fee') or {}).get('value', '0') if isinstance(t.get('fee'), dict) else '0'
                                fee = float(fee_val) / 10**18

                                txs.append({
                                    'Source': f'Libre ({label})', 'ID': tx_id, 'Date': dt,
                                    'Account': address, 'Asset': str(asset_name).upper(), 'Type': 'Mvt',
                                    'Amount': amount * direction, 'Fee': fee, 'Counterparty': cp if label != "Balances" else "Wallet", 'Network': network
                                })
                                counts[label] += 1
                            except: continue

                        next_p = data.get("next_page_params") if isinstance(data, dict) else None
                        if next_p:
                            q = "&".join([f"{k}={v}" for k, v in next_p.items()])
                            url = f"{cfg['free_api']}/addresses/{address}/{endpoint}?{q}"
                        else: break
                    except: break
    except Exception as e: report.warning(f"Note Libre: {e}")

    # 2. VOIE API
    if api_key:
        try:
            for action, label in [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]:
                status_text.text(f"⏳ Voie API ({label})...")
                url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock=0&endblock=99999999&offset=10000&sort=desc&apikey={api_key}"
                res = requests.get(url, timeout=15).json()
                if str(res.get("status")) == "1":
                    for t in res.get("result", []):
                        try:
                            asset_name = t.get("tokenSymbol") or cfg["native"] if action == "tokentx" else cfg["native"]
                            dec = int(t.get("tokenDecimal") or 18) if action == "tokentx" else 18
                            amt = float(t.get("value") or 0) / 10**dec
                            fee = (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 10**18
                            f_addr, t_addr = t.get('from', '').lower(), t.get('to', '').lower()
                            direction = 1 if t_addr == addr_low else -1
                            txs.append({
                                'Source': f'API ({label})', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timeStamp'])),
                                'Account': address, 'Asset': str(asset_name).upper(), 'Type': 'Mvt', 'Amount': amt * direction, 'Fee': fee,
                                'Counterparty': f_addr if direction == 1 else t_addr, 'Network': network
                            })
                            counts[label] += 1
                        except: continue
        except Exception as e: report.error(f"Erreur API: {e}")

    status_text.empty()
    report.write(f"📊 **Total récolté :** {counts['Native']} Native, {counts['Tokens']} Tokens, {counts['Internal']} Internes")

    df = pd.DataFrame(txs)
    if not df.empty:
        df = df.sort_values('Source', ascending=False).drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')
        with st.spinner("Valorisation EUR..."):
            df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')
            df = df.dropna(subset=['Date', 'Asset'])
            unique_combos = df[['Asset', 'Date']].copy()
            unique_combos['Date_Key'] = unique_combos['Date'].dt.date
            unique_combos = unique_combos[['Asset', 'Date_Key']].drop_duplicates()
            prices_map = {}
            total_p = len(unique_combos)
            if total_p > 0:
                pbar = st.progress(0)
                for i, (_, row) in enumerate(unique_combos.iterrows()):
                    a_name = str(row['Asset']) if row['Asset'] else "TOKEN"
                    prices_map[(row['Asset'], row['Date_Key'])] = get_price_eur(a_name, row['Date_Key'])
                    if total_p > 5: time.sleep(1.05)
                    pbar.progress((i+1)/total_p)
                pbar.empty()
            df['Fiat_Value_EUR'] = df.apply(lambda r: float(r['Amount']) * prices_map.get((r['Asset'], r['Date'].date()), 0.0), axis=1)

        df['Is_Spam'] = df['Counterparty'].apply(lambda x: str(x).lower() in st.session_state.spam_addresses)
        def detect_cat(row):
            cp, ass = str(row['Counterparty']).lower(), str(row['Asset']).lower()
            if any(x in cp for x in ['swap', 'pool', 'staking', 'lending', 'uniswap', 'aave', 'pancake', '1inch', '8lnd']): return 'DeFi'
            return 'Transfert'
        df['Category'] = df.apply(detect_cat, axis=1)
    return df

# --- UI PRINCIPALE ---
st.sidebar.title("Jules Crypto Pro")
menu = st.sidebar.selectbox("Navigation", ["Harvest", "Consultation", "Frais & Fiscalité", "Spam & Settings", "Export"], key="main_nav")

if menu == "Harvest":
    st.header("🚜 Récolte Massive de Données")
    t1, t2 = st.tabs(["Exploration Automatique", "Saisie Manuelle"])

    with t1:
        with st.form("harvest_form"):
            col1, col2 = st.columns(2)
            addr = col1.text_input("Adresse Blockchain (0x...)")
            net = col2.selectbox("Réseau", list(NETWORKS_CFG.keys()))
            key = st.text_input(f"Clé API pour {net} (Optionnel)", type="password")
            submit = st.form_submit_button("Lancer la récolte (Libre + API)")

    with t2:
        st.subheader("📝 Ajouter une transaction isolée")
        with st.form("manual_entry"):
            mc1, mc2, mc3 = st.columns(3)
            m_date = mc1.date_input("Date", datetime.now())
            m_asset = mc2.text_input("Asset (ex: USDC, 8LND)", "USDC")
            m_amt = mc3.number_input("Montant (Positif=In, Négatif=Out)", value=0.0, format="%.6f")
            mc4, mc5 = st.columns(2)
            m_net = mc4.selectbox("Réseau", list(NETWORKS_CFG.keys()), key="m_net")
            m_cat = mc5.selectbox("Catégorie", ["Transfert", "Swap", "Staking", "Achat Fiat"], index=0)
            m_submit = st.form_submit_button("Ajouter à l'historique")

            if m_submit:
                m_id = f"MANUAL-{int(time.time())}"
                dt_manual = datetime.combine(m_date, datetime.min.time()).replace(tzinfo=None)
                new_row = pd.DataFrame([{
                    'Source': '✍️ Manuel', 'ID': m_id, 'Date': dt_manual,
                    'Account': 'Manual Wallet', 'Asset': str(m_asset).upper(), 'Type': 'Mvt',
                    'Amount': m_amt, 'Fee': 0.0, 'Fiat_Value_EUR': 0.0,
                    'Counterparty': 'User Input', 'Network': m_net, 'Is_Spam': False, 'Category': m_cat
                }])
                new_row['Date'] = pd.to_datetime(new_row['Date'], utc=True)
                new_row['Fiat_Value_EUR'] = new_row.apply(lambda r: float(r['Amount']) * get_price_eur(r['Asset'], r['Date']), axis=1)
                st.session_state.transactions = pd.concat([st.session_state.transactions, new_row], ignore_index=True)
                st.success(f"Transaction {m_asset} ajoutée !")

    if submit and addr:
        new_df = fetch_data(addr, key, net)
        if not new_df.empty:
            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df])
            st.session_state.transactions = st.session_state.transactions.drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')
            st.session_state.transactions = st.session_state.transactions.sort_values('Date', ascending=False)
            st.session_state.accounts_metadata[f"{addr[:10]}... ({net})"] = {"Count": len(new_df)}
            st.success(f"Récolte réussie : {len(new_df)} lignes ajoutées.")
        else: st.warning("Aucune donnée trouvée.")

    if st.session_state.accounts_metadata:
        st.subheader("Comptes actifs")
        for acc, meta in list(st.session_state.accounts_metadata.items()):
            c1, c2 = st.columns([4, 1])
            c1.info(f"{acc} : {meta['Count']} transactions")
            if c2.button("Supprimer", key=f"del_{acc}"):
                del st.session_state.accounts_metadata[acc]; st.rerun()

elif menu == "Consultation":
    st.header("🔍 Consultation des actifs")
    if not st.session_state.transactions.empty:
        st.subheader("📦 Inventaire des Actifs")
        clean_df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]
        inventory = clean_df.groupby('Asset').agg({'Amount': 'sum'}).reset_index()
        inventory = inventory[inventory['Amount'].abs() > 1e-9]
        if not inventory.empty:
            now = datetime.now()
            inventory['Amount'] = inventory['Amount'].astype(float)
            inventory['p_eur'] = inventory['Asset'].apply(lambda a: float(get_price_eur(str(a), now)))
            inventory['val_eur'] = inventory['Amount'] * inventory['p_eur']
            inventory = inventory.sort_values('val_eur', ascending=False)
            inv_cols = st.columns(min(len(inventory), 4))
            for idx, (i, row) in enumerate(inventory.iterrows()):
                with inv_cols[idx % 4]: st.metric(row['Asset'], f"{row['Amount']:.4f}", f"{row['val_eur']:,.2f} €")

        st.divider()
        df_display = st.session_state.transactions.copy()
        f_col1, f_col2 = st.columns(2)
        show_spam = f_col1.checkbox("Afficher le Spam", value=False)
        selected_asset = f_col2.multiselect("Filtrer par Asset", options=sorted(df_display['Asset'].unique()))
        if not show_spam: df_display = df_display[df_display['Is_Spam'] == False]
        if selected_asset: df_display = df_display[df_display['Asset'].isin(selected_asset)]
        edited_df = st.data_editor(df_display.sort_values('Date', ascending=False), use_container_width=True, key="tx_editor", column_config={"Is_Spam": st.column_config.CheckboxColumn("Spam"), "Category": st.column_config.SelectboxColumn("Catégorie", options=["Transfert", "Swap", "DeFi", "Lending", "Spam", "Achat Fiat"]), "Asset": st.column_config.TextColumn("Asset", disabled=True), "Amount": st.column_config.NumberColumn("Montant", disabled=True, format="%.6f")})
        if st.button("💾 Enregistrer les modifications", use_container_width=True):
            for _, row in edited_df.iterrows():
                mask = (st.session_state.transactions['ID'] == row['ID']) & (st.session_state.transactions['Asset'] == row['Asset']) & (st.session_state.transactions['Network'] == row['Network'])
                st.session_state.transactions.loc[mask, 'Is_Spam'] = row['Is_Spam']
                st.session_state.transactions.loc[mask, 'Category'] = row['Category']
            st.success("Modifications enregistrées !"); st.rerun()
    else: st.info("Lancez d'abord une récolte.")

elif menu == "Frais & Fiscalité":
    st.header("⚖️ Bilan Fiscal & Frais")
    st.subheader("🏦 Comptes Fiat & Apports")
    st.session_state.fiat_accounts = st.data_editor(st.session_state.fiat_accounts, num_rows="dynamic", use_container_width=True)
    st.divider()
    clean_df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]
    if not clean_df.empty:
        inventory = clean_df.groupby('Asset').agg({'Amount': 'sum'}).reset_index()
        inventory = inventory[inventory['Amount'].abs() > 1e-9]
        now = datetime.now(); vgp = 0.0
        for _, row in inventory.iterrows(): vgp += float(row['Amount']) * get_price_eur(str(row['Asset']), now)
        st.metric("Total Frais (Native)", f"{clean_df['Fee'].sum():.4f}")
        st.metric("Valeur Globale du Portefeuille (Actuelle)", f"{vgp:,.2f} €")
        st.subheader("⚖️ Simulateur Article 150 VH bis")
        col_f1, col_f2 = st.columns(2)
        depots = st.session_state.fiat_accounts[st.session_state.fiat_accounts['Type']=='Dépôt']['Amount_EUR'].sum()
        retraits = st.session_state.fiat_accounts[st.session_state.fiat_accounts['Type']=='Retrait']['Amount_EUR'].sum()
        prix_acq = col_f1.number_input("Prix d'acquisition total (EUR)", value=float(max(0, depots-retraits)))
        prix_vent = col_f2.number_input("Montant de la cession (Prix de vente EUR)", value=0.0)
        if prix_vent > 0 and vgp > 0:
            pv = prix_vent - (prix_acq * (prix_vent / vgp))
            st.success(f"**Plus-value imposable :** {pv:,.2f} €")
            st.info(f"**Impôt estimé (Flat Tax 30%) :** {pv * 0.3:,.2f} €")
    else: st.info("Aucune donnée blockchain valide.")

elif menu == "Export":
    st.header("📥 Export")
    if not st.session_state.transactions.empty:
        st.download_button("Télécharger CSV", st.session_state.transactions.to_csv(index=False).encode('utf-8'), "export.csv")
    else: st.info("Rien à exporter.")

elif menu == "Spam & Settings":
    st.header("⚙️ Settings")
    if st.button("Vider la base"):
        st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
        st.session_state.accounts_metadata = {}; st.rerun()

st.sidebar.divider(); st.sidebar.caption("Jules AI Harvest Pro v2.4")
