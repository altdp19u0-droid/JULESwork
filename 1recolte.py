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

# --- MOTEUR DE RÉCOLTE ---
def fetch_harvest(address, network, api_key):
    txs = []
    addr_low = address.lower()
    cfg = NETWORKS_CFG.get(network)
    if not cfg: return []

    status = st.status(f"🚜 Récolte en cours pour {network}...", expanded=True)

    # 1. VOIE LIBRE (Blockscout API v2)
    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        status.write("📡 Interrogation Blockscout V2...")
        endpoints = [("transactions", "Native"), ("token-transfers", "Tokens"), ("internal-transactions", "Internal")]
        for endpoint, label in endpoints:
            url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
            for page in range(500): # Capacité de 25 000 transactions (50 items par page)
                try:
                    res = requests.get(url, timeout=15).json()
                    # Détection flexible Blockscout v1/v2
                    items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
                    if items is None and isinstance(res, dict):
                        items = res.get("result")

                    if not isinstance(items, list) or not items: break
                    for t in items:
                        tx_id = t.get('hash') or t.get('tx_hash')
                        dt_str = t.get('timestamp') or t.get('timeStamp')
                        try:
                            dt = pd.to_datetime(dt_str, utc=True).to_pydatetime() if dt_str else datetime.now(timezone.utc)
                        except:
                            dt = datetime.now(timezone.utc)

                        asset = cfg['native']
                        amount = float(t.get('value', 0)) / 10**18
                        if label == "Tokens" or "token" in t:
                            tok = t.get('token') or {}
                            asset = tok.get('symbol') or t.get('tokenSymbol') or 'TOKEN'
                            dec = int(tok.get('decimals') or t.get('tokenDecimal') or 18)
                            amount = float(t.get('value', 0)) / 10**dec

                        f_addr = (t.get('from', {}).get('hash') if isinstance(t.get('from'), dict) else t.get('from', 'Unknown')).lower()
                        t_addr = (t.get('to', {}).get('hash') if isinstance(t.get('to'), dict) else t.get('to', 'Unknown')).lower()
                        direction = "IN" if t_addr == addr_low else "OUT"
                        cp = f_addr if direction == "IN" else t_addr

                        p_usd, p_eur = get_price_data(asset, dt)
                        txs.append({
                            "source": f"Blockscout ({label})", "id": tx_id, "date": dt,
                            "account": address, "counterparty": cp, "asset": asset,
                            "type": label, "amount": amount, "network": network, "from/to": direction,
                            "fee": float(t.get('fee', {}).get('value', 0)) / 10**18 if isinstance(t.get('fee'), dict) else 0,
                            "valeur $": amount * p_usd,
                            "valeur €": amount * p_eur
                        })

                    next_params = res.get("next_page_params")
                    if not next_params: break
                    url = f"{cfg['free_api']}/addresses/{address}/{endpoint}?" + "&".join([f"{k}={v}" for k, v in next_params.items()])
                except Exception as e:
                    status.write(f"⚠️ Erreur Blockscout {label}: {e}")
                    break

    # 2. VOIE SCAN RÉSEAU (Discovery via Balances)
    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        status.write("🌐 Scan réseau (Discovery)...")
        try:
            url = f"{cfg['free_api']}/addresses/{address}/token-balances"
            res = requests.get(url, timeout=15).json()
            items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
            if isinstance(items, list):
                for t in items:
                    tok = t.get('token') or {}
                    asset = tok.get('symbol') or 'TOKEN'
                    dec = int(tok.get('decimals') or 18)
                    # Extraction robuste de la valeur
                    val_raw = t.get('value') or t.get('amount') or 0
                    val = float(val_raw) / 10**dec
                    if val > 0:
                        p_usd, p_eur = get_price_data(asset, datetime.now(timezone.utc))
                        txs.append({
                            "source": "Scan Réseau (Balance)", "id": f"BAL-{asset}-{address[:8]}", "date": datetime.now(timezone.utc),
                            "account": address, "counterparty": "Balance Discovery", "asset": asset,
                            "type": "Discovery", "amount": val, "network": network, "from/to": "IN", "fee": 0,
                            "valeur $": val * p_usd,
                            "valeur €": val * p_eur
                        })
        except: pass

    # 3. VOIE NFT (Blockscout V2 ERC-721/1155)
    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        status.write("🎨 Scan NFTs (ERC-721/1155)...")
        try:
            url = f"{cfg['free_api']}/addresses/{address}/nft"
            res = requests.get(url, timeout=15).json()
            items = res.get("items") if isinstance(res, dict) else res if isinstance(res, list) else None
            if isinstance(items, list):
                for t in items:
                    tok = t.get('token') or {}
                    asset = tok.get('symbol') or tok.get('name') or 'NFT'
                    txs.append({
                        "source": "Blockscout (NFT)", "id": f"NFT-{asset}-{t.get('id')}", "date": datetime.now(timezone.utc),
                        "account": address, "counterparty": "NFT Discovery", "asset": asset,
                        "type": "NFT", "amount": 1.0, "network": network, "from/to": "IN", "fee": 0,
                        "valeur $": 0.0, "valeur €": 0.0 # On ne valorise pas les NFTs par défaut
                    })
        except: pass

    # 4. VOIE API CLÉS (Etherscan clones)
    if api_key:
        status.write(f"🔑 Interrogation API {cfg['api_name']}...")
        api_endpoints = [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]
        for action, label in api_endpoints:
            start_block = 0
            for loop in range(10): # Pagination jusqu'à 100 000 transactions
                url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock={start_block}&endblock=99999999&offset=10000&sort=asc&apikey={api_key}"
                try:
                    res = requests.get(url, timeout=15).json()
                    results = res.get("result", [])
                    if not isinstance(results, list) or not results: break
                    for t in results:
                        asset = t.get("tokenSymbol", cfg["native"])
                        dec = int(t.get("tokenDecimal", 18))
                        amt = float(t.get("value", 0)) / 10**dec

                        f_addr, t_addr = t.get('from', '').lower(), t.get('to', '').lower()
                        direction = "IN" if t_addr == addr_low else "OUT"

                        fee = (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 10**18 if 'gasPrice' in t else 0

                        p_usd, p_eur = get_price_data(asset, datetime.fromtimestamp(int(t['timeStamp']), tz=timezone.utc))
                        txs.append({
                            "source": f"API ({label})", "id": t['hash'], "date": datetime.fromtimestamp(int(t['timeStamp']), tz=timezone.utc),
                            "account": address, "counterparty": f_addr if direction == "IN" else t_addr,
                            "asset": asset, "type": label, "amount": amt, "network": network, "from/to": direction,
                            "fee": fee,
                            "valeur $": amt * p_usd,
                            "valeur €": amt * p_eur
                        })
                    last_block = int(results[-1].get('blockNumber', 0))
                    if len(results) < 10000: break
                    start_block = last_block + 1
                except Exception as e:
                    status.write(f"⚠️ Erreur API {label}: {e}")
                    break

    if not txs:
        status.update(label="❌ Aucune transaction trouvée", state="error")
    else:
        status.update(label=f"✅ Récolte terminée : {len(txs)} transactions trouvées", state="complete")
    return txs

# --- INITIALISATION ---
if 'spam_addresses' not in st.session_state:
    st.session_state.spam_addresses = set()

if 'api_keys' not in st.session_state:
    st.session_state.api_keys = load_api_keys()

if 'accounts' not in st.session_state:
    st.session_state.accounts = load_accounts()

if page == "PAGE 1 : Gestion des Comptes & Récolte":
    st.header("PAGE 1 : Gestion des Comptes & Récolte")

    # Section : Gestion des Comptes (CRUD)
    st.subheader("📋 Tableau de Bord des Comptes")
    with st.container(border=True):
        # Configuration des colonnes pour la saisie
        column_config = {
            "N°": st.column_config.NumberColumn("N°", disabled=True),
            "Réseau Blockchain": st.column_config.SelectboxColumn(
                "Réseau Blockchain",
                options=list(NETWORKS_CFG.keys()),
                required=True
            ),
            "Adresse": st.column_config.TextColumn("Adresse (0x...)", required=True),
            "Tx": st.column_config.NumberColumn("Tx", disabled=True),
            "Dernière transaction": st.column_config.TextColumn("Dernière transaction", disabled=True)
        }

        edited_accounts = st.data_editor(
            st.session_state.accounts,
            num_rows="dynamic",
            use_container_width=True,
            key="accounts_editor",
            column_config=column_config
        )

        if st.button("💾 Sauvegarder les Comptes"):
            # Auto-numérotation des lignes
            if not edited_accounts.empty:
                edited_accounts["N°"] = range(1, len(edited_accounts) + 1)
                # Valeurs par défaut pour les nouvelles lignes
                edited_accounts["Tx"] = edited_accounts["Tx"].fillna(0)
                edited_accounts["Dernière transaction"] = edited_accounts["Dernière transaction"].fillna("N/A")

            st.session_state.accounts = edited_accounts
            save_accounts(edited_accounts)
            st.success("Comptes sauvegardés avec succès !")
            st.rerun()

    # Section : Journal des Comptes
    st.subheader("📖 Journal des Comptes")
    st.dataframe(st.session_state.accounts, use_container_width=True)

    # Section : Configuration API
    st.subheader("⚙️ Configuration API")
    with st.expander("Gérer les clés API (Etherscan, Blockscout, etc.)"):
        api_names = ["Etherscan", "Polygonscan", "BscScan", "Arbiscan", "Basescan", "Optimism Etherscan"]
        new_keys = {}
        for name in api_names:
            current_val = st.session_state.api_keys.get(name, "")
            new_keys[name] = st.text_input(f"Clé {name}", value=current_val, type="password", key=f"api_{name}")

        if st.button("💾 Sauvegarder les Clés API"):
            st.session_state.api_keys = new_keys
            save_api_keys(new_keys)
            st.success("Clés API sauvegardées !")

    # Section : Moteur de Récolte
    st.subheader("🚜 Moteur de Récolte 3 Voies")
    col_harvest1, col_harvest2 = st.columns([2, 1])

    # Trouver le réseau associé à l'adresse sélectionnée
    if not st.session_state.accounts.empty:
        acc_list = st.session_state.accounts.apply(lambda r: f"{r['Adresse']} ({r['Réseau Blockchain']})", axis=1).tolist()
    else:
        acc_list = []

    selected_acc_full = col_harvest1.selectbox("Sélectionner un compte à récolter", options=acc_list)

    if col_harvest2.button("🚀 Lancer la récolte"):
        if st.session_state.get('accounts_editor', {}).get('edited_rows') or \
           st.session_state.get('accounts_editor', {}).get('added_rows') or \
           st.session_state.get('accounts_editor', {}).get('deleted_rows'):
            st.warning("⚠️ Vous avez des modifications non enregistrées dans le Tableau de Bord des Comptes. Veuillez cliquer sur 'Sauvegarder les Comptes' avant de lancer la récolte.")
        elif selected_acc_full:
            # Extraire l'adresse et le réseau
            addr_to_harvest = selected_acc_full.split(" (")[0]
            net_to_harvest = selected_acc_full.split(" (")[1].replace(")", "")

            row = st.session_state.accounts[(st.session_state.accounts["Adresse"] == addr_to_harvest) &
                                            (st.session_state.accounts["Réseau Blockchain"] == net_to_harvest)].iloc[0]
            net = row["Réseau Blockchain"]
            cfg = NETWORKS_CFG.get(net, {})
            api_key = st.session_state.api_keys.get(cfg.get("api_name"), "")

            raw_txs = fetch_harvest(addr_to_harvest, net, api_key)
            if raw_txs:
                new_df = pd.DataFrame(raw_txs)
                # Dédoublonnage robuste incluant le montant et la direction
                # pour gérer les multi-transferts de même actif dans une transaction
                dup_subset = ['id', 'asset', 'amount', 'valeur $', 'valeur €', 'network', 'from/to']
                new_df = new_df.drop_duplicates(subset=dup_subset)

                # Injection dans la session (global)
                if 'all_transactions' not in st.session_state:
                    st.session_state.all_transactions = pd.DataFrame()

                st.session_state.all_transactions = pd.concat([st.session_state.all_transactions, new_df]).drop_duplicates(subset=dup_subset)

                # Mise à jour des métadonnées du compte
                idx = st.session_state.accounts[(st.session_state.accounts["Adresse"] == addr_to_harvest) &
                                                (st.session_state.accounts["Réseau Blockchain"] == net_to_harvest)].index[0]
                st.session_state.accounts.at[idx, "Tx"] = len(new_df)
                st.session_state.accounts.at[idx, "Dernière transaction"] = new_df["date"].max().strftime("%Y-%m-%d %H:%M")
                save_accounts(st.session_state.accounts)

                st.success(f"Récolte réussie : {len(new_df)} transactions importées !")
            else:
                st.warning("La récolte n'a retourné aucun résultat. Assurez-vous que l'adresse est correcte et active sur ce réseau.")
        else:
            st.warning("Veuillez sélectionner ou ajouter une adresse d'abord.")

elif page == "PAGE 2 : Analyse & Journal Comptable":
    st.header("PAGE 2 : Analyse & Journal Comptable")

    # 1. Sélection de l'année
    available_years = range(2020, datetime.now().year + 1)
    selected_year = st.sidebar.selectbox("Sélectionner l'année", options=reversed(available_years))

    db_file = f"DB_{selected_year}.csv"

    # 2. Chargement des données annuelles avec @st.cache_data
    @st.cache_data(show_spinner=False)
    def load_annual_db(year):
        fname = f"DB_{year}.csv"
        if os.path.exists(fname):
            df = pd.read_csv(fname)
            # Utilisation de format='mixed' pour plus de robustesse sur les formats stockés
            df['date'] = pd.to_datetime(df['date'], utc=True, format='ISO8601', errors='coerce')
            if df['date'].isna().any():
                df['date'] = pd.to_datetime(df['date'], utc=True, errors='coerce')

            # Rétrocompatibilité : Assurer la présence des nouvelles colonnes de valeur
            if 'valeur $' not in df.columns: df['valeur $'] = 0.0
            if 'valeur €' not in df.columns: df['valeur €'] = 0.0

            return df
        return pd.DataFrame(columns=DB_COLS)

    annual_df = load_annual_db(selected_year)

    # 3. Calcul du Solde Initial (Continuité Cumulative en EUR)
    initial_balance_fiat = 0.0
    for y in range(2020, selected_year):
        y_df = load_annual_db(y)
        if not y_df.empty:
            initial_balance_fiat += y_df['valeur €'].sum()

    st.sidebar.metric("Solde Initial (EUR)", f"{initial_balance_fiat:,.2f} €")

    # 4. Double Écriture & Traitement
    if st.button("🔄 Générer / Actualiser le Journal " + str(selected_year)):
        if 'all_transactions' in st.session_state and not st.session_state.all_transactions.empty:
            all_tx = st.session_state.all_transactions.copy()
            # Utilisation de format='mixed' pour gérer les différents formats de date
            all_tx['date'] = pd.to_datetime(all_tx['date'], utc=True, format='ISO8601', errors='coerce')

            # Filtrer par année (en s'assurant que l'année est accessible)
            all_tx = all_tx.dropna(subset=['date'])
            year_tx = all_tx[all_tx['date'].dt.year == selected_year].copy()

            if not year_tx.empty:
                journal_rows = []
                counter = 1
                for _, row in year_tx.iterrows():
                    # Correction Signe : Négatif si OUT
                    signed_amount = row['amount'] if row['from/to'] == "IN" else -abs(row['amount'])

                    # Correction Signe Fiat
                    signed_usd = row['valeur $'] if row['from/to'] == "IN" else -abs(row['valeur $'])
                    signed_eur = row['valeur €'] if row['from/to'] == "IN" else -abs(row['valeur €'])

                    # Ligne 1 : L'Asset (Mouvement principal)
                    journal_rows.append({
                        "numéro": counter, "source": row['source'], "id": row['id'],
                        "date": row['date'], "account": row['account'],
                        "counterparty": row['counterparty'], "asset": row['asset'],
                        "type": row['type'], "amount": signed_amount,
                        "valeur $": signed_usd,
                        "valeur €": signed_eur,
                        "category": "Transfert", "network": row['network'],
                        "from/to": row['from/to']
                    })
                    counter += 1

                    # Ligne 2 : Les Fees (Frais)
                    if row.get('fee', 0) > 0:
                        native_asset = NETWORKS_CFG.get(row['network'], {}).get('native', 'ETH')
                        p_usd_fee, p_eur_fee = get_price_data(native_asset, row['date'])
                        fee_usd = -abs(row['fee'] * p_usd_fee)
                        fee_eur = -abs(row['fee'] * p_eur_fee)
                        # Les frais sont toujours une sortie (OUT)
                        journal_rows.append({
                            "numéro": counter, "source": row['source'], "id": row['id'],
                            "date": row['date'], "account": row['account'],
                            "counterparty": "Network Fee", "asset": native_asset,
                            "type": "Fee", "amount": -row['fee'],
                            "valeur $": fee_usd,
                            "valeur €": fee_eur,
                            "category": "Frais", "network": row['network'],
                            "from/to": "OUT"
                        })
                        counter += 1

                annual_df = pd.DataFrame(journal_rows)
                annual_df.to_csv(db_file, index=False)
                st.cache_data.clear()
                st.success(f"Journal {selected_year} généré avec {len(annual_df)} lignes.")
                st.rerun()
            else:
                st.warning(f"Aucune transaction trouvée pour l'année {selected_year} dans la récolte.")
        else:
            st.warning("Aucune donnée récoltée. Allez en Page 1 pour lancer une récolte.")

    # 5. Affichage du Journal
    st.subheader(f"📅 Journal Comptable {selected_year}")

    # Statistiques (st.metric en EUR)
    if not annual_df.empty:
        # Filtrer le spam pour les stats
        stats_df = annual_df[annual_df['counterparty'].str.lower().apply(lambda x: x not in st.session_state.spam_addresses)]
        total_vol_fiat = stats_df[stats_df['type'] != 'Fee']['valeur €'].abs().sum()
        total_fees_fiat = stats_df[stats_df['type'] == 'Fee']['valeur €'].sum()
        final_balance_fiat = initial_balance_fiat + stats_df['valeur €'].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Solde Final Estimé", f"{final_balance_fiat:,.2f} €")
        c2.metric("Frais Totaux", f"{total_fees_fiat:,.2f} €")
        c3.metric("Volume Total", f"{total_vol_fiat:,.2f} €")
        st.divider()

    # Toggle Anti-Spam
    hide_spam = st.sidebar.toggle("🚫 Masquer le spam", value=True)

    if not annual_df.empty:
        # Suivi du solde avec .cumsum()
        annual_df = annual_df.sort_values('date')

        # Traitement immédiat des éditions de spam (Réactivité maximale)
        editor_key = f"journal_editor_{selected_year}"
        edits = st.session_state.get(editor_key, {}).get("edited_rows", {})

        # On calcule Is_Spam basé sur la liste noire actuelle
        annual_df['Is_Spam'] = annual_df['counterparty'].str.lower().isin(st.session_state.spam_addresses)

        # Si l'utilisateur vient de cocher/décocher, on met à jour la liste noire AVANT l'affichage
        if edits:
            # Pour accéder aux adresses, on a besoin du DF tel qu'il était affiché au tour précédent
            # On utilise une copie temporaire pour la détection
            df_ref = annual_df.copy()
            if hide_spam:
                df_ref = df_ref[df_ref['Is_Spam'] == False]

            for idx_str, changes in edits.items():
                if "Is_Spam" in changes:
                    idx = int(idx_str)
                    if idx < len(df_ref):
                        cp_addr = str(df_ref.iloc[idx]['counterparty']).lower()
                        if changes["Is_Spam"]:
                            st.session_state.spam_addresses.add(cp_addr)
                        else:
                            st.session_state.spam_addresses.discard(cp_addr)
            # On recalcule Is_Spam après mise à jour pour le rendu actuel
            annual_df['Is_Spam'] = annual_df['counterparty'].str.lower().isin(st.session_state.spam_addresses)

        # Filtrage si toggle activé
        df_to_show = annual_df.copy()
        if hide_spam:
            df_to_show = df_to_show[df_to_show['Is_Spam'] == False]

        # Solde Progressif en EUR
        df_to_show['Solde Progressif (EUR)'] = initial_balance_fiat + df_to_show['valeur €'].cumsum()

        # Style pour le surlignage jaune des suspects
        def highlight_spam_rows(row):
            cp = str(row['counterparty']).lower()
            if cp in st.session_state.spam_addresses:
                return ['background-color: #ffff99'] * len(row)
            return [''] * len(row)

        # Utilisation de st.data_editor
        column_config_journal = {
            "Is_Spam": st.column_config.CheckboxColumn("Spam", help="Cochez pour marquer l'adresse comme SPAM"),
            "numéro": st.column_config.NumberColumn("N°", disabled=True),
            "date": st.column_config.DatetimeColumn("Date", disabled=True),
            "amount": st.column_config.NumberColumn("Quantité", format="%.8f", disabled=True),
            "valeur $": st.column_config.NumberColumn("Valeur $", format="%.2f $", disabled=True),
            "valeur €": st.column_config.NumberColumn("Valeur €", format="%.2f €", disabled=True),
            "Solde Progressif (EUR)": st.column_config.NumberColumn("Solde EUR", format="%.2f €", disabled=True)
        }

        # Le bouton reste utile pour forcer un recalcul propre des soldes si nécessaire
        if edits and st.button("🔄 Confirmer & Recalculer les Soldes"):
            st.rerun()

        st.data_editor(
            df_to_show.style.apply(highlight_spam_rows, axis=1),
            use_container_width=True,
            column_config=column_config_journal,
            key=editor_key
        )

        # Action : Marquer comme spam
        st.divider()
        col_s1, col_s2 = st.columns([2, 1])
        addr_spam = col_s1.text_input("Marquer une adresse comme SPAM", placeholder="0x...")
        if col_s2.button("🧹 Nettoyer l'historique"):
            if addr_spam:
                st.session_state.spam_addresses.add(addr_spam.lower())
                st.success(f"Adresse {addr_spam} ajoutée au filtre spam. Relancez la génération du journal pour appliquer.")
                st.rerun()

        # Action : Export PDF
        st.divider()
        if st.button("📄 Générer Rapport PDF"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(190, 10, f"Journal Comptable {selected_year}", 0, 1, 'C')
            pdf.set_font("Arial", '', 10)
            pdf.ln(10)

            # Entêtes
            pdf.set_fill_color(200, 220, 255)
            pdf.cell(10, 8, "N°", 1, 0, 'C', 1)
            pdf.cell(30, 8, "Date", 1, 0, 'C', 1)
            pdf.cell(30, 8, "Asset", 1, 0, 'C', 1)
            pdf.cell(30, 8, "Montant", 1, 0, 'C', 1)
            pdf.cell(90, 8, "Contrepartie", 1, 1, 'C', 1)

            # Lignes
            for idx, row in df_to_show.head(2000).iterrows():
                pdf.cell(10, 8, str(row['numéro']), 1)
                pdf.cell(30, 8, str(row['date'].strftime('%Y-%m-%d')), 1)
                pdf.cell(30, 8, str(row['asset']), 1)
                pdf.cell(30, 8, f"{row['amount']:.4f}", 1)
                # Nettoyage des caractères non-compatibles Latin-1
                cp_safe = str(row['counterparty']).encode('latin-1', 'replace').decode('latin-1')
                pdf.cell(90, 8, cp_safe[:40], 1, 1)

            pdf_bytes = pdf.output()
            st.download_button(label="⬇️ Télécharger le Rapport PDF", data=pdf_bytes, file_name=f"Rapport_{selected_year}.pdf", mime="application/pdf")

    else:
        st.info("Le journal pour cette année est vide. Cliquez sur le bouton ci-dessus pour le générer si vous avez récolté des données.")
