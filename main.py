import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time
import os
import json

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto Tracker Harvest Pro", layout="wide")

DB_FILE = "harvest_storage.csv"
LOG_FILE = "accounts_log.csv"
BLACKLIST_FILE = "spam_blacklist.json"

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
if 'labels' not in st.session_state:
    st.session_state.labels = {}
if 'global_api_key' not in st.session_state:
    st.session_state.global_api_key = ""

def save_data():
    st.session_state.transactions.to_csv(DB_FILE, index=False)
    if st.session_state.accounts_metadata:
        pd.DataFrame(st.session_state.accounts_metadata).T.to_csv(LOG_FILE)

    blacklist_data = {
        "spam_addresses": list(st.session_state.spam_addresses),
        "labels": st.session_state.labels,
        "global_api_key": st.session_state.global_api_key
    }
    with open(BLACKLIST_FILE, 'w') as f:
        json.dump(blacklist_data, f)

def load_data():
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            if not df.empty:
                df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')
                # Ensure all required columns are present
                for col in REQUIRED_COLS:
                    if col not in df.columns:
                        df[col] = None
                st.session_state.transactions = df[REQUIRED_COLS]
        except Exception as e:
            st.error(f"Erreur chargement transactions: {e}")

    if os.path.exists(LOG_FILE):
        try:
            log_df = pd.read_csv(LOG_FILE, index_col=0)
            st.session_state.accounts_metadata = log_df.to_dict('index')
        except: pass

    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, 'r') as f:
                data = json.load(f)
                st.session_state.spam_addresses = set(data.get("spam_addresses", []))
                st.session_state.labels = data.get("labels", {})
                st.session_state.global_api_key = data.get("global_api_key", "")
        except: pass

# Premier chargement
if st.session_state.transactions.empty and not st.session_state.get('loaded', False):
    load_data()
    st.session_state.loaded = True

# Sanity check: conversion systématique en datetime
if not st.session_state.transactions.empty:
    st.session_state.transactions['Date'] = pd.to_datetime(st.session_state.transactions['Date'], utc=True, errors='coerce')

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

def get_label_display(address):
    if not address or pd.isna(address) or str(address).lower() == "network fee" or str(address).lower() == "discovery balance":
        return "—"
    addr_clean = str(address).lower().strip()

    # Check if it's one of our accounts
    is_int = any(addr_clean == str(info.get('address')).lower() for info in st.session_state.accounts_metadata.values())

    alias = st.session_state.labels.get(addr_clean)

    if is_int: return f"🟢 [INT] {alias.upper() if alias else 'MON COMPTE'}"
    if alias: return f"🔵 [POS] {alias.upper()}"
    return f"⚪ [EXT] {addr_clean[:10]}..."

# --- MOTEUR DE RÉCOLTE ULTIME (V3.0) ---

def fetch_data(address, api_key, network):
    txs = []
    addr_low = address.lower()
    cfg = NETWORKS_CFG[network]

    report = st.expander(f"🚜 Récolte Massive en cours : {network}", expanded=True)
    status_text = report.empty()
    counts = {"Native": 0, "Tokens": 0, "Internal": 0, "Discovery": 0}

    # -- PHASE 1 : VOIE LIBRE (Deep Scan Blockscout) --
    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        endpoints = [
            ("transactions", "Native"),
            ("token-transfers", "Tokens"),
            ("internal-transactions", "Internal"),
            ("token-balances", "Discovery")
        ]

        for endpoint, label in endpoints:
            base_url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
            url = base_url
            for page in range(500): # Profondeur maximale (Jusqu'à 25000 txs par type)
                try:
                    status_text.text(f"⏳ Extraction {label} : Page {page+1}...")
                    res = requests.get(url, timeout=25)

                    if res.status_code == 404 and endpoint == "token-balances":
                        res = requests.get(f"{cfg['free_api']}/addresses/{address}/tokens", timeout=25)

                    if res.status_code != 200:
                        if res.status_code == 429:
                            status_text.warning("Rate limit API... attente 5s")
                            time.sleep(5)
                            continue
                        break

                    data = res.json()
                    # Détection flexible de la liste d'items (Blockscout v1/v2/Custom)
                    items = data.get("items") if isinstance(data, dict) else data if isinstance(data, list) else None
                    if items is None and isinstance(data, dict):
                        items = data.get("result")

                    if not isinstance(items, list) or not items: break

                    for t in items:
                        try:
                            if not isinstance(t, dict): continue

                            if label == "Discovery":
                                tok = t.get('token') or {}
                                asset = tok.get('symbol') or tok.get('name') or 'TOKEN'
                                dec = int(tok.get('decimals') or 18)
                                val_raw = t.get('value') or '0'
                                amount = float(val_raw) / 10**dec
                                if amount <= 0: continue
                                tx_id = f"DISC-{asset}-{address.lower()}"
                                dt = datetime.now()
                                direction = 1
                                cp = "Discovery Balance"
                            else:
                                tx_id = t.get('hash') or t.get('tx_hash')
                                if not tx_id: continue

                                # Détection Token ultra-robuste
                                if label == "Tokens" or "token" in t or "tokenSymbol" in t:
                                    tok = t.get('token') or {}
                                    asset = tok.get('symbol') or t.get('tokenSymbol') or tok.get('name') or 'TOKEN'
                                    dec = int(tok.get('decimals') or t.get('tokenDecimal') or 18)
                                    val_raw = t.get('value') or '0'
                                    amount = float(val_raw) / 10**dec
                                else:
                                    asset = cfg['native']
                                    amount = float(t.get('value') or '0') / 10**18

                                dt_str = t.get('timestamp') or t.get('timeStamp')
                                if dt_str and not str(dt_str).isdigit():
                                    dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
                                elif dt_str:
                                    dt = datetime.fromtimestamp(int(dt_str))
                                else:
                                    dt = datetime.now()

                                f_addr = (t.get('from') if isinstance(t.get('from'), str) else t.get('from', {}).get('hash', 'Unknown')).lower()
                                t_addr = (t.get('to') if isinstance(t.get('to'), str) else t.get('to', {}).get('hash', 'Unknown')).lower()
                                direction = 1 if t_addr == addr_low else -1
                                cp = f_addr if direction == 1 else t_addr

                            fee_val = (t.get('fee') or {}).get('value', '0') if isinstance(t.get('fee'), dict) else '0'
                            fee = float(fee_val) / 10**18

                            txs.append({
                                'Source': f'Blockscout ({label})', 'ID': tx_id, 'Date': dt,
                                'Account': address, 'Asset': str(asset).upper(), 'Type': 'Mvt',
                                'Amount': amount * direction, 'Fee': fee, 'Counterparty': cp, 'Network': network
                            })
                            counts[label] += 1
                        except: continue

                    next_p = data.get("next_page_params") if isinstance(data, dict) else None
                    if next_p:
                        q = "&".join([f"{k}={v}" for k, v in next_p.items()])
                        url = f"{base_url}?{q}"
                    else: break
                except: break

    # -- PHASE 2 : VOIE API (Etherscan/BscScan etc avec Pagination) --
    if api_key:
        api_endpoints = [
            ("txlist", "Native"), ("tokentx", "Tokens"),
            ("txlistinternal", "Internal"), ("erc721tx", "NFTs")
        ]
        for action, label in api_endpoints:
            try:
                status_text.text(f"⏳ Interrogation API {label} (Deep)...")
                start_block = 0
                for loop in range(10): # Récupération jusqu'à 100,000 transactions par type
                    url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock={start_block}&endblock=99999999&offset=10000&sort=asc&apikey={api_key}"
                    res = requests.get(url, timeout=20).json()

                    results = res.get("result", [])
                    if str(res.get("status")) != "1" or not isinstance(results, list) or not results:
                        break

                    for t in results:
                        try:
                            asset = t.get("tokenSymbol") or cfg["native"]
                            dec = int(t.get("tokenDecimal") or 18)
                            amt = float(t.get("value") or 0) / 10**dec

                            gas_price = int(t.get('gasPrice') or 0)
                            gas_used = int(t.get('gasUsed') or 0)
                            fee = (gas_used * gas_price) / 10**18

                            f_addr, t_addr = t.get('from', '').lower(), t.get('to', '').lower()
                            direction = 1 if t_addr == addr_low else -1

                            txs.append({
                                'Source': f'API ({label})', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timeStamp'])),
                                'Account': address, 'Asset': str(asset).upper(), 'Type': 'Mvt', 'Amount': amt * direction, 'Fee': fee,
                                'Counterparty': f_addr if direction == 1 else t_addr, 'Network': network
                            })
                            counts[label] += 1
                        except: continue

                    # Pagination par bloc
                    last_block = int(results[-1].get('blockNumber', 0))
                    if last_block <= start_block: break
                    start_block = last_block + 1
                    if len(results) < 10000: break
                    time.sleep(0.2) # Courtoisie API
            except: pass

    # -- PHASE 3 : TRAITEMENT & VALORISATION --
    status_text.empty()
    report.write(f"✅ Récolte finie : {counts['Native']} Natifs, {counts['Tokens']} Tokens, {counts['Discovery']} Balances")

    df = pd.DataFrame(txs)
    if not df.empty:
        # Dédoublonnage priorisant la richesse des données
        df = df.sort_values('Source', ascending=False).drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')

        with st.spinner("Synchronisation des cours..."):
            df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')
            df = df.dropna(subset=['Date', 'Asset'])

            # Agrégation optimisée des prix (On ne requête que les dates des mouvements réels)
            mouvements = df[['Asset', 'Date']].copy()
            mouvements['Day'] = mouvements['Date'].dt.date
            combos = mouvements[['Asset', 'Day']].drop_duplicates()

            prices_map = {}
            total_req = len(combos)
            if total_req > 0:
                pbar = st.progress(0)
                for idx, row in enumerate(combos.itertuples()):
                    prices_map[(row.Asset, row.Day)] = get_price_eur(row.Asset, row.Day)
                    # Respect du Rate Limit CoinGecko (1 requête par sec environ)
                    if total_req > 5: time.sleep(1.05)
                    pbar.progress((idx+1)/total_req)
                pbar.empty()

            df['Fiat_Value_EUR'] = df.apply(lambda r: float(r['Amount']) * prices_map.get((r['Asset'], r['Date'].date()), 0.0), axis=1)

        df['Is_Spam'] = df['Counterparty'].apply(lambda x: str(x).lower() in st.session_state.spam_addresses)
        df['Category'] = df['Asset'].apply(lambda a: 'DeFi' if any(x in a.lower() for x in ['lnd', 'steth', 'steur']) else 'Transfert')

    return df

# --- UI PRINCIPALE ---
st.sidebar.title("Jules Crypto Pro V4")

# Zone API Master (Style V90)
with st.sidebar.expander("🔑 Clé API Globale", expanded=not st.session_state.global_api_key):
    new_k = st.text_input("Clé (Etherscan/BSC...)", value=st.session_state.global_api_key, type="password")
    if st.button("Sauvegarder Clé"):
        st.session_state.global_api_key = new_k
        save_data()
        st.success("Clé enregistrée")

menu = st.sidebar.selectbox("Navigation", ["Harvest", "Consultation", "Frais & Fiscalité", "Settings"], key="main_nav")

if menu == "Harvest":
    st.header("🚜 Récolte Massive de Données")

    # Mise à jour globale (Style V90)
    if st.session_state.accounts_metadata:
        if st.button("🔄 TOUT METTRE À JOUR", use_container_width=True):
            prog = st.progress(0)
            items = list(st.session_state.accounts_metadata.items())
            for idx, (acc_key, info) in enumerate(items):
                # On tente d'extraire l'adresse du label "addr... (Network)"
                try:
                    # Dans V3, la clé était f"{addr[:10]}... ({net})"
                    # On va essayer de retrouver l'adresse et le réseau
                    # Pour être robuste, on stockera mieux les métadonnées plus tard
                    # Pour l'instant on fait au mieux avec les infos dispos
                    # On suppose que l'adresse complète est dans info si on l'a rajoutée
                    addr_to_sync = info.get('address')
                    net_to_sync = info.get('network')
                    if addr_to_sync and net_to_sync:
                        new_df = fetch_data(addr_to_sync, st.session_state.global_api_key, net_to_sync)
                        if not new_df.empty:
                            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df])
                            st.session_state.transactions = st.session_state.transactions.drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')
                except: pass
                prog.progress((idx + 1) / len(items))
            save_data()
            st.success("Mise à jour terminée")
            st.rerun()

    t1, t2 = st.tabs(["Exploration Automatique", "Saisie Manuelle"])

    with t1:
        with st.form("harvest_form"):
            col1, col2 = st.columns(2)
            addr = col1.text_input("Adresse Blockchain (0x...)")
            net = col2.selectbox("Réseau", list(NETWORKS_CFG.keys()))
            # Utilise la clé globale par défaut
            key = st.text_input(f"Clé API pour {net} (Optionnel)", value=st.session_state.global_api_key, type="password")
            label = st.text_input("Étiquette (Optionnel)")
            submit = st.form_submit_button("Lancer la récolte profonde")

    with t2:
        st.subheader("📝 Ajouter une transaction isolée")
        with st.form("manual_entry"):
            mc1, mc2, mc3 = st.columns(3)
            m_date = mc1.date_input("Date", datetime.now())
            m_asset = mc2.text_input("Asset (ex: USDC, 8LND)", "USDC")
            m_amt = mc3.number_input("Montant", value=0.0, format="%.6f")
            m_net = st.selectbox("Réseau", list(NETWORKS_CFG.keys()), key="m_net")
            m_cat = st.selectbox("Catégorie", ["Transfert", "Swap", "Achat Fiat"], index=0)
            m_submit = st.form_submit_button("Ajouter à l'historique")

            if m_submit:
                new_row = pd.DataFrame([{
                    'Source': '✍️ Manuel', 'ID': f"MAN-{int(time.time())}", 'Date': pd.to_datetime(m_date, utc=True),
                    'Account': 'Manual Wallet', 'Asset': str(m_asset).upper(), 'Type': 'Mvt',
                    'Amount': m_amt, 'Fee': 0.0, 'Fiat_Value_EUR': 0.0,
                    'Counterparty': 'User', 'Network': m_net, 'Is_Spam': False, 'Category': m_cat
                }])
                new_row['Fiat_Value_EUR'] = new_row.apply(lambda r: float(r['Amount']) * get_price_eur(r['Asset'], r['Date']), axis=1)
                st.session_state.transactions = pd.concat([st.session_state.transactions, new_row], ignore_index=True)
                st.success("Ajouté !")

    if submit and addr:
        new_df = fetch_data(addr, key, net)
        if not new_df.empty:
            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df])
            st.session_state.transactions = st.session_state.transactions.drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')
            st.session_state.transactions = st.session_state.transactions.sort_values('Date', ascending=False)

            acc_key = f"{addr[:10]}... ({net})"
            st.session_state.accounts_metadata[acc_key] = {
                "Count": len(new_df),
                "address": addr,
                "network": net,
                "label": label
            }
            if label:
                st.session_state.labels[addr.lower()] = label

            save_data()
            st.success(f"Récolte réussie : {len(new_df)} lignes.")

    if st.session_state.accounts_metadata:
        for acc, meta in list(st.session_state.accounts_metadata.items()):
            c1, c2 = st.columns([4, 1])
            c1.info(f"{acc} : {meta['Count']} transactions")
            if c2.button("Supprimer", key=f"del_{acc}"):
                del st.session_state.accounts_metadata[acc]; st.rerun()

elif menu == "Consultation":
    st.header("🔍 Consultation & Inventaire")
    show_spam = st.sidebar.checkbox("Afficher les transactions Spam", value=False)

    if not st.session_state.transactions.empty:
        # Filtrage strict pour l'inventaire
        clean_df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]
        inv = clean_df.groupby('Asset').agg({'Amount': 'sum'}).reset_index()
        inv = inv[inv['Amount'].abs() > 1e-9]

        if not inv.empty:
            st.subheader("📦 Position Actuelle (Hors Spam)")
            now = datetime.now()
            inv['p_eur'] = inv['Asset'].apply(lambda a: float(get_price_eur(str(a), now)))
            inv['val_eur'] = inv['Amount'] * inv['p_eur']
            inv = inv.sort_values('val_eur', ascending=False)
            cols = st.columns(min(len(inv), 4))
            for idx, row in inv.iterrows():
                with cols[idx % 4]: st.metric(row['Asset'], f"{row['Amount']:.4f}", f"{row['val_eur']:,.2f} €")

        st.divider()
        df_display = st.session_state.transactions.copy()
        df_display['Étiquette'] = df_display['Counterparty'].apply(get_label_display)

        # Masquage immédiat si l'option est décochée (Comportement automatique)
        if not show_spam:
            df_display = df_display[df_display['Is_Spam'] == False]

        # On libère aussi la liste des assets filtrables de tout spam
        available_assets = sorted(df_display['Asset'].unique())
        f_asset = st.multiselect("Filtrer Asset", options=available_assets)
        if f_asset: df_display = df_display[df_display['Asset'].isin(f_asset)]

        st.subheader("📝 Historique des Mouvements")

        # Style (V90)
        styled_df = df_display.sort_values('Date', ascending=False).style.apply(
            lambda r: ['background-color: #ffffcc' if r.Is_Spam else '' for _ in r], axis=1
        )

        edited = st.data_editor(
            styled_df,
            use_container_width=True,
            key="tx_ed",
            column_config={
                "Is_Spam": st.column_config.CheckboxColumn("SPAM"),
                "ID": None,
                "Fiat_Value_EUR": st.column_config.NumberColumn("Valeur EUR", format="%.2f €")
            },
            disabled=[c for c in df_display.columns if c not in ["Is_Spam", "Category"]]
        )
        if st.button("💾 Sauvegarder modifications"):
            for _, row in edited.iterrows():
                # Mise à jour de la ligne spécifique
                mask = (st.session_state.transactions['ID'] == row['ID']) & (st.session_state.transactions['Asset'] == row['Asset'])
                st.session_state.transactions.loc[mask, 'Is_Spam'] = row['Is_Spam']
                st.session_state.transactions.loc[mask, 'Category'] = row['Category']

                # Propagation du marquage Spam à l'adresse de contrepartie
                cp = str(row['Counterparty']).lower()
                if row['Is_Spam']:
                    st.session_state.spam_addresses.add(cp)
                    st.session_state.transactions.loc[st.session_state.transactions['Counterparty'].str.lower() == cp, 'Is_Spam'] = True
                else:
                    if cp in st.session_state.spam_addresses:
                        st.session_state.spam_addresses.remove(cp)
                        # On réactive les transactions si on retire le flag spam global
                        st.session_state.transactions.loc[st.session_state.transactions['Counterparty'].str.lower() == cp, 'Is_Spam'] = False
            save_data()
            st.success("Enregistré ! (Propagation appliquée)"); st.rerun()

elif menu == "Frais & Fiscalité":
    st.header("⚖️ Fiscalité (Art. 150 VH bis)")
    st.session_state.fiat_accounts = st.data_editor(st.session_state.fiat_accounts, num_rows="dynamic", use_container_width=True)
    clean_df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]
    if not clean_df.empty:
        # Valeur Globale Portefeuille
        inv = clean_df.groupby('Asset').agg({'Amount': 'sum'}).reset_index()
        vgp = sum([float(row['Amount']) * get_price_eur(str(row['Asset']), datetime.now()) for _, row in inv.iterrows()])
        st.metric("Valeur Globale Portefeuille (VGP)", f"{vgp:,.2f} €")
        prix_acq = st.number_input("Prix d'acquisition total (EUR)", value=0.0)
        prix_vent = st.number_input("Montant de la cession (EUR)", value=0.0)
        if prix_vent > 0 and vgp > 0:
            pv = prix_vent - (prix_acq * (prix_vent / vgp))
            st.success(f"Plus-value : {pv:,.2f} € | Impôt estimé (30%) : {pv*0.3:,.2f} €")

elif menu == "Settings":
    st.header("⚙️ Paramètres")

    with st.container(border=True):
        st.subheader("🏷️ Gestion des Labels")
        l_addr = st.text_input("Adresse Blockchain")
        l_name = st.text_input("Nom de l'étiquette")
        if st.button("Enregistrer Label"):
            if l_addr and l_name:
                st.session_state.labels[l_addr.lower().strip()] = l_name
                save_data()
                st.success("Label enregistré !")
                st.rerun()

    st.divider()
    if st.button("🗑️ Vider toute la base de données"):
        st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
        st.session_state.accounts_metadata = {}
        st.session_state.labels = {}
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        if os.path.exists(LOG_FILE): os.remove(LOG_FILE)
        if os.path.exists(BLACKLIST_FILE): os.remove(BLACKLIST_FILE)
        st.rerun()

st.sidebar.divider(); st.sidebar.caption("Jules AI Harvest Pro v4.0")
