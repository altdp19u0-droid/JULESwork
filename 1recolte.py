import streamlit as st
import pandas as pd
import json
import os
import requests
import time
from datetime import datetime, timezone
from fpdf import FPDF
import io

# --- CONFIGURATION PAGE ---
st.set_page_config(page_title="1Recolte - Crypto Harvest Pro", layout="wide")

# --- MOTEUR DE PRIX (USD & EUR) ---
@st.cache_data(ttl=86400)
def get_eur_usd_rate(date_obj):
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
        res = requests.get(url, timeout=5).json()
        return res["rates"]["EUR"]
    except: return 0.92

@st.cache_data(ttl=86400)
def get_price_data(asset, date_obj):
    if not asset or not isinstance(asset, str): return 0.0, 0.0
    asset = asset.upper().strip()

    # Mapping basique pour CoinGecko
    cg_map = {
        "ETH": "ethereum", "BNB": "binancecoin", "POL": "polygon-ecosystem-token",
        "USDT": "tether", "USDC": "usd-coin", "DAI": "dai", "8LND": "8lnd",
        "ARB": "arbitrum", "OP": "optimism", "MATIC": "matic-network"
    }
    asset_id = cg_map.get(asset, asset.lower())
    d_str = date_obj.strftime("%d-%m-%Y")

    usd_price = 0.0
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{asset_id}/history?date={d_str}&localization=false"
        res = requests.get(url, timeout=5).json()
        if "market_data" in res:
            usd_price = float(res["market_data"]["current_price"]["usd"])
    except: pass

    if usd_price == 0:
        if asset in ["USDT", "USDC", "DAI"]: usd_price = 1.0
        elif asset in ["EURA", "AGEUR"]: usd_price = 1.08

    eur_rate = get_eur_usd_rate(date_obj)
    return usd_price, usd_price * eur_rate

# --- NAVIGATION ---
st.sidebar.title("1Recolte V4.0")
page = st.sidebar.radio("Navigation", ["PAGE 1 : Gestion des Comptes & Récolte", "PAGE 2 : Analyse & Journal Comptable"])

# --- CONSTANTES ---
DB_COLS = ["numéro", "source", "id", "date", "account", "counterparty", "asset", "type", "amount", "valeur $", "valeur €", "category", "network", "from/to"]
ACCOUNTS_FILE = "accounts_log.csv"
API_KEYS_FILE = "api_keys.json"
SPAM_FILE = "spam_blacklist.json"
HARVEST_FILE = "harvest_storage.csv"

# Configuration des Réseaux
NETWORKS_CFG = {
    "Ethereum": {"host": "api.etherscan.io", "native": "ETH", "free_api": "https://eth.blockscout.com/api/v2", "api_name": "Etherscan"},
    "Polygon": {"host": "api.polygonscan.com", "native": "POL", "free_api": "https://polygon.blockscout.com/api/v2", "api_name": "Polygonscan"},
    "BscScan": {"host": "api.bscscan.com", "native": "BNB", "free_api": "https://bsc.blockscout.com/api/v2", "api_name": "BscScan"},
    "Arbitrum": {"host": "api.arbiscan.io", "native": "ETH", "free_api": "https://arbitrum.blockscout.com/api/v2", "api_name": "Arbiscan"},
    "Base": {"host": "api.basescan.org", "native": "ETH", "free_api": "https://base.blockscout.com/api/v2", "api_name": "Basescan"},
    "Optimism": {"host": "api-optimistic.etherscan.io", "native": "ETH", "free_api": "https://optimism.blockscout.com/api/v2", "api_name": "Optimism Etherscan"}
}

# --- UTILS PERSISTENCE ---
def load_api_keys():
    if os.path.exists(API_KEYS_FILE):
        with open(API_KEYS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_api_keys(keys):
    with open(API_KEYS_FILE, 'w') as f:
        json.dump(keys, f, indent=4)

def load_accounts():
    cols = ["N°", "Réseau Blockchain", "Adresse", "Étiquette", "Tx", "Dernière transaction"]
    if os.path.exists(ACCOUNTS_FILE):
        df = pd.read_csv(ACCOUNTS_FILE)
        if "N°" not in df.columns:
            df.insert(0, "N°", range(1, len(df) + 1))
        return df
    return pd.DataFrame(columns=cols)

def save_accounts(df):
    df.to_csv(ACCOUNTS_FILE, index=False)

def load_spam_blacklist():
    if os.path.exists(SPAM_FILE):
        with open(SPAM_FILE, 'r') as f: return set(json.load(f))
    return set()

def save_spam_blacklist(blacklist):
    with open(SPAM_FILE, 'w') as f: json.dump(list(blacklist), f)

def load_harvest():
    if os.path.exists(HARVEST_FILE):
        try:
            df = pd.read_csv(HARVEST_FILE)
            df['date'] = pd.to_datetime(df['date'], utc=True, errors='coerce')
            return df.dropna(subset=['date'])
        except: return pd.DataFrame()
    return pd.DataFrame()

def save_harvest(df):
    if df is not None and not df.empty:
        df.to_csv(HARVEST_FILE, index=False)

@st.cache_data(show_spinner=False)
def load_annual_db(year):
    fname = f"DB_{year}.csv"
    if os.path.exists(fname):
        df = pd.read_csv(fname)
        # Gestion unifiée et robuste des dates
        df['date'] = pd.to_datetime(df['date'], utc=True, format='ISO8601', errors='coerce')
        if df['date'].isna().any():
            df['date'] = pd.to_datetime(df['date'], utc=True, errors='coerce')

        # Rétrocompatibilité : Assurer la présence des colonnes de valeur
        if 'valeur $' not in df.columns: df['valeur $'] = 0.0
        if 'valeur €' not in df.columns: df['valeur €'] = 0.0

        return df
    return pd.DataFrame(columns=DB_COLS)

# --- MOTEUR DE RÉCOLTE ---
def extract_amount(t, decimals=18):
    """Extraction robuste du montant depuis divers formats d'API (Blockscout/Etherscan)"""
    # On cherche 'value', 'amount' ou 'total'
    val_raw = t.get('value') or t.get('amount') or t.get('total') or 0

    # Blockscout V2 peut renvoyer un objet pour 'total' ou 'fee'
    if isinstance(val_raw, dict):
        val_raw = val_raw.get('value', 0)

    try:
        return float(val_raw) / 10**int(decimals)
    except (ValueError, TypeError):
        return 0.0

def fetch_harvest(address, network, api_key, since_date=None):
    txs = []
    addr_low = address.lower()

    limit_dt = None
    if since_date:
        limit_dt = datetime.combine(since_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    cfg = NETWORKS_CFG.get(network)
    if not cfg: return []

    status = st.status(f"🚜 Récolte en cours pour {network}...", expanded=True)

    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        status.write("📡 Interrogation Blockscout V2...")
        endpoints = [("transactions", "Native"), ("token-transfers", "Tokens"), ("internal-transactions", "Internal")]
        for endpoint, label in endpoints:
            url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
            for page in range(500):
                try:
                    res = requests.get(url, timeout=15).json()
                    items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
                    if items is None and isinstance(res, dict): items = res.get("result")
                    if not isinstance(items, list) or not items: break

                    stop_pagination = False
                    for t in items:
                        dt_str = t.get('timestamp') or t.get('timeStamp')
                        try:
                            dt = pd.to_datetime(dt_str, utc=True).to_pydatetime() if dt_str else datetime.now(timezone.utc)
                        except: dt = datetime.now(timezone.utc)

                        if limit_dt and dt < limit_dt:
                            stop_pagination = True; continue

                        asset = cfg['native']; dec = 18
                        if label == "Tokens" or "token" in t:
                            tok = t.get('token') or {}
                            asset = tok.get('symbol') or t.get('tokenSymbol') or 'TOKEN'
                            dec = int(tok.get('decimals') or t.get('tokenDecimal') or 18)

                        amount = extract_amount(t, dec)
                        f_addr = (t.get('from', {}).get('hash') if isinstance(t.get('from'), dict) else t.get('from', 'Unknown')).lower()
                        t_addr = (t.get('to', {}).get('hash') if isinstance(t.get('to'), dict) else t.get('to', 'Unknown')).lower()
                        direction = "IN" if t_addr == addr_low else "OUT"

                        p_usd, p_eur = get_price_data(asset, dt)
                        txs.append({
                            "source": f"Blockscout ({label})", "id": t.get('hash') or t.get('tx_hash'), "date": dt,
                            "account": address, "counterparty": f_addr if direction == "IN" else t_addr, "asset": asset,
                            "type": label, "amount": amount, "network": network, "from/to": direction,
                            "fee": float(t.get('fee', {}).get('value', 0)) / 10**18 if isinstance(t.get('fee'), dict) else 0,
                            "valeur $": amount * p_usd, "valeur €": amount * p_eur
                        })
                    if stop_pagination: break
                    next_params = res.get("next_page_params")
                    if not next_params: break
                    url = f"{cfg['free_api']}/addresses/{address}/{endpoint}?" + "&".join([f"{k}={v}" for k, v in next_params.items()])
                except: break

    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        status.write("🌐 Scan réseau (Discovery)...")
        try:
            url = f"{cfg['free_api']}/addresses/{address}/token-balances"
            res = requests.get(url, timeout=15).json()
            items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
            if isinstance(items, list):
                for t in items:
                    tok = t.get('token') or {}; asset = tok.get('symbol') or 'TOKEN'
                    dec = int(tok.get('decimals') or 18); val = extract_amount(t, dec)
                    if val > 0:
                        p_usd, p_eur = get_price_data(asset, datetime.now(timezone.utc))
                        txs.append({
                            "source": "Scan Réseau (Balance)", "id": f"BAL-{asset}-{address[:8]}", "date": datetime.now(timezone.utc),
                            "account": address, "counterparty": "Balance Discovery", "asset": asset,
                            "type": "Discovery", "amount": val, "network": network, "from/to": "IN", "fee": 0,
                            "valeur $": val * p_usd, "valeur €": val * p_eur
                        })
        except: pass

    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        status.write("🎨 Scan NFTs...")
        try:
            url = f"{cfg['free_api']}/addresses/{address}/nft"
            res = requests.get(url, timeout=15).json()
            items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
            if isinstance(items, list):
                for t in items:
                    tok = t.get('token') or {}; asset = tok.get('symbol') or tok.get('name') or 'NFT'
                    txs.append({
                        "source": "Blockscout (NFT)", "id": f"NFT-{asset}-{t.get('id')}", "date": datetime.now(timezone.utc),
                        "account": address, "counterparty": "NFT Discovery", "asset": asset,
                        "type": "NFT", "amount": 1.0, "network": network, "from/to": "IN", "fee": 0,
                        "valeur $": 0.0, "valeur €": 0.0
                    })
        except: pass

    if api_key:
        status.write(f"🔑 Interrogation API {cfg['api_name']}...")
        api_endpoints = [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]
        for action, label in api_endpoints:
            start_block = 0
            for loop in range(10):
                url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock={start_block}&endblock=99999999&offset=10000&sort=asc&apikey={api_key}"
                try:
                    res = requests.get(url, timeout=15).json()
                    results = res.get("result", [])
                    if not isinstance(results, list) or not results: break
                    stop_api = False
                    for t in results:
                        dt = datetime.fromtimestamp(int(t['timeStamp']), tz=timezone.utc)
                        if limit_dt and dt < limit_dt: stop_api = True; continue
                        asset = t.get("tokenSymbol", cfg["native"]); dec = int(t.get("tokenDecimal", 18))
                        amt = extract_amount(t, dec)
                        f_addr, t_addr = t.get('from', '').lower(), t.get('to', '').lower()
                        direction = "IN" if t_addr == addr_low else "OUT"
                        fee = (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 10**18 if 'gasPrice' in t else 0
                        p_usd, p_eur = get_price_data(asset, dt)
                        txs.append({
                            "source": f"API ({label})", "id": t['hash'], "date": dt,
                            "account": address, "counterparty": f_addr if direction == "IN" else t_addr,
                            "asset": asset, "type": label, "amount": amt, "network": network, "from/to": direction,
                            "fee": fee, "valeur $": amt * p_usd, "valeur €": amt * p_eur
                        })
                    if stop_api: break
                    start_block = int(results[-1].get('blockNumber', 0)) + 1
                    if len(results) < 10000: break
                except: break

    if not txs: status.update(label="❌ Aucune transaction trouvée", state="error")
    else: status.update(label=f"✅ Récolte terminée : {len(txs)} transactions trouvées", state="complete")
    return txs

# --- INITIALISATION ---
if 'spam_addresses' not in st.session_state: st.session_state.spam_addresses = load_spam_blacklist()
if 'api_keys' not in st.session_state: st.session_state.api_keys = load_api_keys()
if 'accounts' not in st.session_state: st.session_state.accounts = load_accounts()
if 'all_transactions' not in st.session_state: st.session_state.all_transactions = load_harvest()

# --- COMPOSANT JOURNAL (FRAGMENT) ---
@st.fragment
def journal_fragment(selected_year, db_file, initial_balance_fiat):
    annual_df = load_annual_db(selected_year)

    if st.button("🔄 Générer / Actualiser le Journal " + str(selected_year)):
        if 'all_transactions' in st.session_state and not st.session_state.all_transactions.empty:
            all_tx = st.session_state.all_transactions.copy()
            all_tx['date'] = pd.to_datetime(all_tx['date'], utc=True, format='ISO8601', errors='coerce')
            all_tx = all_tx.dropna(subset=['date'])
            year_tx = all_tx[all_tx['date'].dt.year == selected_year].copy()

            if not year_tx.empty:
                tx_hashes_with_tokens = year_tx[year_tx['type'].isin(['Tokens', 'NFT'])]['id'].unique()
                year_tx = year_tx[~((year_tx['type'] == 'Native') & (year_tx['amount'] == 0) & (year_tx['id'].isin(tx_hashes_with_tokens)))]
                journal_rows = []
                counter = 1
                for _, row in year_tx.iterrows():
                    signed_amount = row['amount'] if row['from/to'] == "IN" else -abs(row['amount'])
                    signed_usd = row['valeur $'] if row['from/to'] == "IN" else -abs(row['valeur $'])
                    signed_eur = row['valeur €'] if row['from/to'] == "IN" else -abs(row['valeur €'])
                    journal_rows.append({
                        "numéro": counter, "source": row['source'], "id": row['id'], "date": row['date'],
                        "account": row['account'], "counterparty": row['counterparty'], "asset": row['asset'],
                        "type": row['type'], "amount": signed_amount, "valeur $": signed_usd, "valeur €": signed_eur,
                        "category": "Transfert", "network": row['network'], "from/to": row['from/to']
                    })
                    counter += 1
                    if row.get('fee', 0) > 0:
                        native_asset = NETWORKS_CFG.get(row['network'], {}).get('native', 'ETH')
                        p_usd_fee, p_eur_fee = get_price_data(native_asset, row['date'])
                        journal_rows.append({
                            "numéro": counter, "source": row['source'], "id": row['id'], "date": row['date'],
                            "account": row['account'], "counterparty": "Network Fee", "asset": native_asset,
                            "type": "Fee", "amount": -row['fee'], "valeur $": -abs(row['fee'] * p_usd_fee),
                            "valeur €": -abs(row['fee'] * p_eur_fee), "category": "Frais", "network": row['network'], "from/to": "OUT"
                        })
                        counter += 1
                pd.DataFrame(journal_rows).to_csv(db_file, index=False)
                st.cache_data.clear(); st.success(f"Journal {selected_year} généré."); st.rerun()

    if not annual_df.empty:
        stats_df = annual_df[~annual_df['counterparty'].str.lower().isin(st.session_state.spam_addresses)]
        total_vol_fiat = stats_df[stats_df['type'] != 'Fee']['valeur €'].abs().sum()
        total_fees_fiat = stats_df[stats_df['type'] == 'Fee']['valeur €'].sum()
        final_balance_fiat = initial_balance_fiat + stats_df['valeur €'].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Solde Final Estimé", f"{final_balance_fiat:,.2f} €")
        c2.metric("Frais Totaux", f"{total_fees_fiat:,.2f} €")
        c3.metric("Volume Total", f"{total_vol_fiat:,.2f} €")
        st.divider()
        # Options
        col_opt1, col_opt2 = st.columns([1, 1])
        hide_spam = col_opt1.toggle("🚫 Masquer le spam", value=True, key=f"hide_spam_{selected_year}")

        # Traitement Spam réactif (AVANT le rendu)
        editor_key = f"editor_{selected_year}"
        edits = st.session_state.get(editor_key, {}).get("edited_rows", {})

        # On calcule Is_Spam pour tout le journal
        annual_df = annual_df.sort_values('date')
        annual_df['Is_Spam'] = annual_df['counterparty'].str.lower().isin(st.session_state.spam_addresses)

        # Si édition en cours, on applique à la liste noire et on recalcule
        if edits:
            # On a besoin d'une référence stable de ce qui était affiché lors de l'édition
            df_ref = annual_df[~annual_df['Is_Spam']] if hide_spam else annual_df
            for idx_str, changes in edits.items():
                if "Is_Spam" in changes:
                    idx = int(idx_str)
                    if idx < len(df_ref):
                        cp_addr = str(df_ref.iloc[idx]['counterparty']).lower()
                        if changes["Is_Spam"]: st.session_state.spam_addresses.add(cp_addr)
                        else: st.session_state.spam_addresses.discard(cp_addr)
            save_spam_blacklist(st.session_state.spam_addresses)
            annual_df['Is_Spam'] = annual_df['counterparty'].str.lower().isin(st.session_state.spam_addresses)

        df_to_show = annual_df[~annual_df['Is_Spam']].copy() if hide_spam else annual_df.copy()

        # Nettoyage et calcul du solde progressif
        df_to_show['valeur €'] = pd.to_numeric(df_to_show['valeur €'], errors='coerce').fillna(0.0)
        df_to_show['Solde Progressif (EUR)'] = initial_balance_fiat + df_to_show['valeur €'].cumsum()

        # Ordre des colonnes fixe pour éviter les sauts visuels
        cols_order = ["Is_Spam", "numéro", "date", "asset", "amount", "valeur €", "valeur $", "counterparty", "type", "network", "Solde Progressif (EUR)"]

        # Style : Jaune pour les suspects affichés (Is_Spam=True mais hide_spam=False)
        styled_df = df_to_show.style.apply(lambda row: ['background-color: #fff3cd']*len(row) if row['Is_Spam'] else ['']*len(row), axis=1)

        st.data_editor(
            styled_df,
            column_order=cols_order,
            use_container_width=True,
            height=600,
            column_config={
                "Is_Spam": st.column_config.CheckboxColumn("Spam", width="small"),
                "date": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm"),
                "amount": st.column_config.NumberColumn("Quantité", format="%.6f"),
                "valeur $": st.column_config.NumberColumn("Valeur $", format="%.2f $"),
                "valeur €": st.column_config.NumberColumn("Valeur €", format="%.2f €"),
                "Solde Progressif (EUR)": st.column_config.NumberColumn("Solde EUR", format="%.2f €")
            },
            key=editor_key,
            disabled=DB_COLS + ["Solde Progressif (EUR)"]
        )
        if edits and st.button("🔄 Confirmer & Recalculer", key=f"refresh_{selected_year}"): st.rerun()
        if st.button("📄 Générer Rapport PDF", key=f"pdf_{selected_year}"):
            pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 16)
            pdf.cell(190, 10, f"Journal Comptable {selected_year}", 0, 1, 'C')
            pdf.ln(10); pdf.set_fill_color(200, 220, 255); pdf.set_font("Arial", '', 10)
            headers = [("N°", 10), ("Date", 30), ("Asset", 30), ("Quantité", 30), ("Contrepartie", 90)]
            for h, w in headers: pdf.cell(w, 8, h, 1, 0, 'C', 1)
            pdf.ln()
            for _, row in df_to_show.head(2000).iterrows():
                pdf.cell(10, 8, str(row['numéro']), 1); pdf.cell(30, 8, str(row['date'].strftime('%Y-%m-%d')), 1); pdf.cell(30, 8, str(row['asset']), 1); pdf.cell(30, 8, f"{row['amount']:.4f}", 1); pdf.cell(90, 8, str(row['counterparty']).encode('latin-1', 'replace').decode('latin-1')[:40], 1, 1)
            st.download_button("⬇️ Télécharger PDF", pdf.output(), f"Rapport_{selected_year}.pdf", "application/pdf")
    else: st.info("Journal vide. Lancez une récolte puis actualisez.")

# --- ROUTAGE DES PAGES ---
if page == "PAGE 1 : Gestion des Comptes & Récolte":
    st.header("PAGE 1 : Gestion des Comptes & Récolte")
    st.subheader("📋 Tableau de Bord des Comptes")
    with st.container(border=True):
        column_config = {
            "N°": st.column_config.NumberColumn("N°", disabled=True),
            "Réseau Blockchain": st.column_config.SelectboxColumn("Réseau Blockchain", options=list(NETWORKS_CFG.keys()), required=True),
            "Adresse": st.column_config.TextColumn("Adresse (0x...)", required=True),
            "Tx": st.column_config.NumberColumn("Tx", disabled=True),
            "Dernière transaction": st.column_config.TextColumn("Dernière transaction", disabled=True)
        }
        edited_accounts = st.data_editor(st.session_state.accounts, num_rows="dynamic", use_container_width=True, key="accounts_editor", column_config=column_config)
        if st.button("💾 Sauvegarder les Comptes"):
            if not edited_accounts.empty:
                edited_accounts["N°"] = range(1, len(edited_accounts) + 1)
                edited_accounts["Tx"] = edited_accounts["Tx"].fillna(0); edited_accounts["Dernière transaction"] = edited_accounts["Dernière transaction"].fillna("N/A")
            st.session_state.accounts = edited_accounts; save_accounts(edited_accounts); st.success("Comptes sauvegardés !"); st.rerun()
    st.subheader("📖 Journal des Comptes"); st.dataframe(st.session_state.accounts, use_container_width=True)
    st.subheader("⚙️ Configuration API")
    with st.expander("Gérer les clés API"):
        api_names = ["Etherscan", "Polygonscan", "BscScan", "Arbiscan", "Basescan", "Optimism Etherscan"]
        new_keys = {}
        for name in api_names:
            current_val = st.session_state.api_keys.get(name, ""); new_keys[name] = st.text_input(f"Clé {name}", value=current_val, type="password", key=f"api_{name}")
        if st.button("💾 Sauvegarder les Clés API"): st.session_state.api_keys = new_keys; save_api_keys(new_keys); st.success("Clés API sauvegardées !")
    st.subheader("🚜 Moteur de Récolte 3 Voies")
    harvest_mode = st.radio("Mode de récolte", ["Complet", "Incrémental (depuis une date)"], horizontal=True)
    since_date = st.date_input("Récolter à partir du :", datetime.now().date()) if harvest_mode == "Incrémental (depuis une date)" else None
    col_harvest1, col_harvest2 = st.columns([2, 1])
    acc_list = st.session_state.accounts.apply(lambda r: f"{r['Adresse']} ({r['Réseau Blockchain']})", axis=1).tolist() if not st.session_state.accounts.empty else []
    selected_acc_full = col_harvest1.selectbox("Sélectionner un compte", options=acc_list)
    if col_harvest2.button("🚀 Lancer la récolte"):
        if st.session_state.get('accounts_editor', {}).get('edited_rows') or st.session_state.get('accounts_editor', {}).get('added_rows') or st.session_state.get('accounts_editor', {}).get('deleted_rows'): st.warning("⚠️ Sauvegardez vos modifications d'abord.")
        elif selected_acc_full:
            addr = selected_acc_full.split(" (")[0]; net = selected_acc_full.split(" (")[1].replace(")", "")
            row = st.session_state.accounts[(st.session_state.accounts["Adresse"] == addr) & (st.session_state.accounts["Réseau Blockchain"] == net)].iloc[0]
            api_key = st.session_state.api_keys.get(NETWORKS_CFG[net]["api_name"], "")
            raw_txs = fetch_harvest(addr, net, api_key, since_date=since_date)
            if raw_txs:
                new_df = pd.DataFrame(raw_txs); dup_subset = ['id', 'asset', 'amount', 'valeur $', 'valeur €', 'network', 'from/to']
                if 'all_transactions' not in st.session_state: st.session_state.all_transactions = pd.DataFrame()
                st.session_state.all_transactions = pd.concat([st.session_state.all_transactions, new_df]).drop_duplicates(subset=dup_subset)
                save_harvest(st.session_state.all_transactions)
                idx = st.session_state.accounts[(st.session_state.accounts["Adresse"] == addr) & (st.session_state.accounts["Réseau Blockchain"] == net)].index[0]
                st.session_state.accounts.at[idx, "Tx"] = len(new_df); st.session_state.accounts.at[idx, "Dernière transaction"] = new_df["date"].max().strftime("%Y-%m-%d %H:%M"); save_accounts(st.session_state.accounts); st.success(f"Récolte réussie : {len(new_df)} transactions importées !")
            else: st.warning("Aucun résultat.")
elif page == "PAGE 2 : Analyse & Journal Comptable":
    st.header("PAGE 2 : Analyse & Journal Comptable")
    available_years = list(range(2020, datetime.now(timezone.utc).year + 1))
    selected_year = st.sidebar.selectbox("Année", options=reversed(available_years), key="year_selector")
    initial_balance_fiat = 0.0
    for y in range(2020, selected_year):
        y_df = load_annual_db(y)
        if not y_df.empty: initial_balance_fiat += y_df['valeur €'].sum()
    st.sidebar.metric("Solde Initial (EUR)", f"{initial_balance_fiat:,.2f} €")

    with st.sidebar.expander("🛡️ Sécurité & Anti-Spam"):
        st.write(f"Adresses bloquées : **{len(st.session_state.spam_addresses)}**")
        if st.button("🗑️ Vider la liste noire"):
            st.session_state.spam_addresses = set()
            save_spam_blacklist(set())
            st.rerun()
        st.info("Le marquage d'une adresse comme spam dans le journal l'ajoute globalement à cette liste.")

    journal_fragment(selected_year, f"DB_{selected_year}.csv", initial_balance_fiat)
