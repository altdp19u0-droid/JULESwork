import os
import time
import json
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil import tz
from web3 import Web3
from shared_logic import show_status

# --- Configuration & Initialization ---
st.set_page_config(page_title="Jules Crypto Harvest Pro - Sanctuarisation V7", layout="wide")
st.title("🚜 Sanctuarisation des Données Blockchain (Harvest Pure)")

# Initialisation Session State
if "transactions" not in st.session_state: st.session_state.transactions = pd.DataFrame()
if "portfolio" not in st.session_state: st.session_state.portfolio = pd.DataFrame()
if "harvested_accounts" not in st.session_state: st.session_state.harvested_accounts = {} # {addr: {"tx": 0, "portfolio": 0}}
if "account_data_registry" not in st.session_state: st.session_state.account_data_registry = {} # {addr: {"portfolio": df, "transactions": df, "status": {}}}

# Configuration des Réseaux avec Blockscout V1 et V2
def load_api_keys():
    if os.path.exists("api_keys.json"):
        with open("api_keys.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

CHAIN_APIS = {
    "Ethereum": {
        "v1": "https://eth.blockscout.com/api",
        "v2": "https://eth.blockscout.com/api/v2",
        "api_host": "api.etherscan.io",
        "native": "ETH"
    },
    "Arbitrum": {
        "v1": "https://arbitrum.blockscout.com/api",
        "v2": "https://arbitrum.blockscout.com/api/v2",
        "api_host": "api.arbiscan.io",
        "native": "ETH"
    },
    "Base": {
        "v1": "https://base.blockscout.com/api",
        "v2": "https://base.blockscout.com/api/v2",
        "api_host": "api.basescan.org",
        "native": "ETH"
    },
    "Polygon": {
        "v1": "https://polygon.blockscout.com/api",
        "v2": "https://polygon.blockscout.com/api/v2",
        "api_host": "api.polygonscan.com",
        "native": "POL"
    },
    "Optimism": {
        "v1": "https://optimism.blockscout.com/api",
        "v2": "https://optimism.blockscout.com/api/v2",
        "api_host": "api-optimistic.etherscan.io",
        "native": "ETH"
    },
    "BSC": {
        "v1": "https://api.bscscan.com/api",
        "v2": "https://api.bscscan.com/api",
        "api_host": "api.bscscan.com",
        "native": "BNB"
    }
}

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ Paramètres de Récolte")
    address = st.text_input("Adresse Blockchain (0x...)", "")
    chains = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=["Ethereum", "Polygon", "Arbitrum", "Base", "Optimism"])

    st.divider()
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state: st.session_state["_hub_target_year"] = datetime.now().year
    target_year = st.number_input("Année à sanctuariser", min_value=2015, max_value=2030, value=st.session_state["_hub_target_year"], key="_hub_target_year")
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=50000, value=2000, step=100, key="app_max_txs")

    st.divider()
    st.subheader("🔑 Clés API (Voie 2)")

    # Universal Key Input
    universal_key = st.text_input("Clé API Unique (Etherscan/BscScan...)", type="password", help="Cette clé sera utilisée pour tous les réseaux si aucune clé spécifique n'est trouvée.")

    api_keys_loaded = load_api_keys()
    # Merge: Specific keys from file take priority over universal key
    api_keys = {c: api_keys_loaded.get(c, universal_key) for c in CHAIN_APIS.keys()}

    st.info("💡 Les clés spécifiques dans `api_keys.json` restent prioritaires.")

    st.divider()
    st.info("💡 **Conseil Multicomptes** : Récoltez et sanctuarisez vos adresses les unes après les autres. Le dossier final contiendra un fichier par compte.")

    st.divider()
    if st.button("🗑️ Réinitialiser l'Interface"):
        from shared_logic import clean_session_state
        clean_session_state()
        st.rerun()

    st.divider()
    show_status()

# --- RAW V4 Standard (19 colonnes) ---
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- Way 2 API Helper ---
def fetch_etherscan_way2(api_host, addr, api_key, year, max_items, native):
    items = []
    if not api_key: return [], False # On garde list vide si pas de clé

    success = False
    endpoints = [
        ("txlist", "Native"), ("tokentx", "Tokens"),
        ("txlistinternal", "Internal")
    ]

    for action, label in endpoints:
        start_block = 0
        for loop in range(10): # Max 100,000 txs per type
            url = f"https://{api_host}/api?module=account&action={action}&address={addr}&startblock={start_block}&endblock=99999999&offset=10000&sort=asc&apikey={api_key}"
            try:
                res = requests.get(url, timeout=20).json()
                results = res.get("result", [])
                if str(res.get("status")) != "1" or not isinstance(results, list) or not results:
                    break

                if results: success = True
                for t in results:
                    dt = datetime.fromtimestamp(int(t['timeStamp']), tz=tz.tzutc())
                    if dt.year == year:
                        items.append((t, label, dt))
                    elif dt.year > year:
                         break

                # Pagination
                last_block = int(results[-1].get('blockNumber', 0))
                if last_block <= start_block: break
                start_block = last_block + 1
                if len(results) < 10000: break
                time.sleep(0.2)
            except: break

    return items[:max_items], success

# --- Shared Logic ---
def call_api(url, params=None):
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (i + 1)); continue
            r.raise_for_status()
            return r.json()
        except:
            time.sleep(1); continue
    return None

def fetch_blockscout_v2(api_v2, addr, max_items, year, endpoint):
    items = []
    url = f"{api_v2}/addresses/{addr}/{endpoint}"
    params = {}
    for page in range(50):
        data = call_api(url, params)
        if not data or "items" not in data: break

        for item in data["items"]:
            # Détection de la date (flexible V2)
            ts_str = item.get("timestamp") or item.get("block_timestamp")
            if not ts_str: continue
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.year == year:
                items.append(item)
            elif dt.year < year:
                return items[:max_items]

        if len(items) >= max_items or "next_page_params" not in data or not data["next_page_params"]:
            break
        params.update(data["next_page_params"])
        time.sleep(0.1)
    return items[:max_items]

def fetch_blockscout_v1_fallback(api_v1, addr, action, max_items, year):
    items = []
    page = 1
    while len(items) < max_items:
        params = {"module":"account","action":action,"address":addr,"page":page,"offset":100,"sort":"desc"}
        j = call_api(api_v1, params)
        if not j or not j.get("result"): break
        res = j["result"]
        if not isinstance(res, list): break

        for item in res:
            dt = datetime.fromtimestamp(int(item.get("timeStamp", 0)), tz=tz.tzutc())
            if dt.year == year:
                items.append(item)
            elif dt.year < year:
                return items[:max_items]

        if len(res) < 100: break
        page += 1
        time.sleep(0.1)
    return items[:max_items]

def extract_value(v):
    # Blockscout V2 peut renvoyer {'value': '123'} ou '123'
    if isinstance(v, dict):
        return v.get("total") or v.get("value") or "0"
    return str(v or "0")

def format_addr(addr_obj):
    if not isinstance(addr_obj, dict):
        return str(addr_obj or "").lower()
    h = str(addr_obj.get("hash", "")).lower()
    name = addr_obj.get("name")
    if name:
        return f"{name} ({h})"
    return h

def fetch_portfolio_v2(api_v2, addr):
    url = f"{api_v2}/addresses/{addr}/token-balances"
    data = call_api(url)
    return data # Can be None if failure

# --- Main App Logic ---
harvest_btn = st.button("🚀 Lancer la Récolte Totale (Step 1 : Brutes)", width='stretch')

# Liste des Comptes Collectés (Visible au-dessus de la récolte)
if st.session_state.harvested_accounts:
    st.subheader("🏦 Suivi de la Récolte Session")
    acc_df = pd.DataFrame([
        {"Compte": a, "Txs": v["tx"], "Actifs": v["portfolio"]}
        for a, v in st.session_state.harvested_accounts.items()
    ])
    st.dataframe(acc_df, hide_index=True, width='stretch')

# Affichage des 3 Tableaux Obligatoires (Par compte récolté)
# On inclut l'adresse actuellement saisie dès qu'elle est présente
active_addr = address.lower().strip() if address.strip() else None

display_registry = st.session_state.account_data_registry.copy()
if active_addr and active_addr not in display_registry:
    display_registry[active_addr] = {
        "portfolio": pd.DataFrame(columns=RAW_V4_COLUMNS),
        "transactions": pd.DataFrame(columns=RAW_V4_COLUMNS),
        "status": {"blockscout": None, "etherscan": None}
    }

if display_registry:
    st.divider()
    st.header("📋 Tableaux de Collecte par Compte")

    for addr, data in display_registry.items():
        is_active = (addr == active_addr)
        with st.expander(f"👤 Compte : {addr} {'(Actif)' if is_active else ''}", expanded=is_active):
            # Message d'état des APIs
            api_status = data.get("status", {})
            if any(v is not None for v in api_status.values()):
                c1, c2 = st.columns(2)
                bs_st = api_status.get("blockscout")
                eth_st = api_status.get("etherscan")

                if bs_st is True: c1.success("✅ Blockscout : Connecté")
                elif bs_st is False: c1.error("❌ Blockscout : Erreur d'accès / Serveur injoignable")
                elif bs_st == "empty": c1.warning("ℹ️ Blockscout : Connecté (Mais aucun actif trouvé)")

                if eth_st is True: c2.success("✅ Etherscan/API : Connecté")
                elif eth_st is False: c2.error("❌ Etherscan/API : Erreur d'accès ou Clé invalide")
                elif eth_st == "empty": c2.warning("ℹ️ Etherscan/API : Connecté (Mais aucun mouvement trouvé)")
            else:
                st.info("💡 Cliquez sur 'Lancer la Récolte' pour interroger les APIs Blockscout et Etherscan pour ce compte.")

            # 1. TABLEAU PORTFOLIO
            st.markdown("#### 📦 Portfolio")
            df_p = data.get("portfolio", pd.DataFrame(columns=RAW_V4_COLUMNS))
            st.dataframe(df_p, width='stretch', key=f"df_p_{addr}")
            if df_p.empty and api_status.get("blockscout") is None:
                st.caption("En attente de récolte...")

            # 2. TABLEAU TRANSACTIONS
            st.markdown("#### 📝 Transactions")
            df_t = data.get("transactions", pd.DataFrame(columns=RAW_V4_COLUMNS))
            df_native = pd.DataFrame(columns=RAW_V4_COLUMNS)
            if not df_t.empty:
                df_t["Type_UI"] = df_t["Type"].astype(str).str.lower().str.replace("s", "")
                mask_native = df_t["Type_UI"].isin(["native", "internal", "native/internal"])
                df_native = df_t[mask_native].drop(columns=["Type_UI"], errors="ignore")

            st.dataframe(df_native, width='stretch', key=f"df_n_{addr}")

            # 3. TABLEAU TOKENS
            st.markdown("#### 🪙 Tokens")
            df_tokens = pd.DataFrame(columns=RAW_V4_COLUMNS)
            if not df_t.empty:
                # Type_UI already created above if not empty
                mask_token = df_t["Type_UI"].isin(["token", "cex_mvt"])
                df_tokens = df_t[mask_token].drop(columns=["Type_UI"], errors="ignore")

            st.dataframe(df_tokens, width='stretch', key=f"df_t_{addr}")

if harvest_btn:
    if not address or not Web3.is_address(address):
        st.error("❌ Adresse invalide.")
    else:
        addr_c = Web3.to_checksum_address(address).lower()
        st.info(f"🔍 Analyse de l'adresse : {addr_c}")

        global_raw_txs = []
        bs_status_final = False # False=Error, True=Success, "empty"=Vide
        eth_status_final = bool(not any(api_keys.values())) # True si pas de clés (pas d'erreur)

        # 1. Harvest Portfolio (ÉTAT ACTUEL - VOIE 1)
        st.subheader("📦 Portfolio (État Actuel - Blockscout)")
        portfolio_all = []
        for chain in chains:
            v2 = CHAIN_APIS[chain]["v2"]
            try:
                balances = fetch_portfolio_v2(v2, addr_c)
                if balances is not None:
                    if bs_status_final is False: bs_status_final = "empty"
                    if isinstance(balances, dict) and "items" in balances: balances = balances["items"]
                    if balances:
                        bs_status_final = True
                        for b in balances:
                            token = b.get("token", {})
                            asset_sym = token.get("symbol", "NATIVE" if not token else "TOKEN")
                            qty = float(b.get("value", 0)) / (10**int(token.get("decimals", 18) or 18))
                            portfolio_all.append({
                                "Date": datetime(target_year, 12, 31).isoformat(),
                                "Chain": chain, "Tx_Hash": f"PORT-{addr_c}-{asset_sym}",
                                "Type": "Portfolio", "Method": "Snapshot", "Account": addr_c,
                                "From": "Blockchain", "To": addr_c, "From_Label": "", "To_Label": "",
                                "Counterparty": "Blockchain Snapshot", "Asset": asset_sym, "Amount": qty,
                                "Fee_Asset": "", "Fee_Amount": 0.0, "Source_Way": "Way_1",
                                "Audit_Status": "RAW", "Fee_Audit_Alert": ""
                            })
                else:
                    # technical error for this chain
                    pass
            except: pass

        st.session_state.portfolio = pd.DataFrame(portfolio_all, columns=RAW_V4_COLUMNS)

        # 2. MULTI-WAY HARVEST
        st.subheader("📝 Récolte Multivoie (Journal Brut)")
        pbar = st.progress(0)

        for idx, chain in enumerate(chains):
            st.write(f"🌐 Analyse de **{chain}**...")

            # Real-time feedback containers for current chain
            c_fb1, c_fb2 = st.columns(2)
            fb_native = c_fb1.empty()
            fb_tokens = c_fb2.empty()

            chain_txs = []
            chain_toks = []

            v2, v1 = CHAIN_APIS[chain]["v2"], CHAIN_APIS[chain]["v1"]
            api_host, native = CHAIN_APIS[chain]["api_host"], CHAIN_APIS[chain]["native"]
            api_key = api_keys.get(chain)

            # --- VOIE 1 : BLOCKSCOUT ---
            # Native
            raw_v1_txs = fetch_blockscout_v2(v2, addr_c, max_txs, target_year, "transactions")
            if not raw_v1_txs: raw_v1_txs = fetch_blockscout_v1_fallback(v1, addr_c, "txlist", max_txs, target_year)
            for t in raw_v1_txs:
                if "timestamp" in t: # V2
                    dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    val = float(t.get("value", 0)) / 1e18
                    f_raw, t_raw = t.get("from", {}).get("hash", "").lower(), t.get("to", {}).get("hash", "").lower()
                    f_l, t_l = t.get("from", {}).get("name", ""), t.get("to", {}).get("name", "")
                    tx_h = t.get("hash")
                    gas_u, gas_p = int(t.get("gas_used", 0)), int(t.get("gas_price", 0))
                    meth = t.get("method", "")
                else: # V1
                    dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                    val = float(t.get("value", 0)) / 1e18
                    f_raw, t_raw = t.get("from", "").lower(), t.get("to", "").lower()
                    f_l, t_l = "", ""
                    tx_h = t.get("hash")
                    gas_u, gas_p = int(t.get("gasUsed", 0)), int(t.get("gasPrice", 0))
                    meth = ""

                fee = (gas_u * gas_p) / 1e18
                v4_tx = {
                    "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Native",
                    "Method": meth, "Account": addr_c, "From": f_raw, "To": t_raw,
                    "From_Label": f_l, "To_Label": t_l,
                    "Counterparty": t_raw if f_raw == addr_c else f_raw,
                    "Asset": native, "Amount": val if t_raw == addr_c else -val,
                    "Fee_Asset": native, "Fee_Amount": fee if f_raw == addr_c else 0.0,
                    "Source_Way": "Way_1", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                }
                global_raw_txs.append(v4_tx)
                chain_txs.append(v4_tx)

            fb_native.caption(f"✅ {len(chain_txs)} Transactions Natives")

            # Tokens
            raw_v1_toks = fetch_blockscout_v2(v2, addr_c, max_txs, target_year, "token-transfers")
            if not raw_v1_toks: raw_v1_toks = fetch_blockscout_v1_fallback(v1, addr_c, "tokentx", max_txs, target_year)
            for t in raw_v1_toks:
                if "token" in t: # V2
                    dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    tok = t.get("token", {})
                    asset = tok.get("symbol", "TOKEN")
                    dec = int(tok.get("decimals") or 18)
                    val = float(extract_value(t.get("total") or t.get("value", "0"))) / (10**dec)
                    f_raw, t_raw = t.get("from", {}).get("hash", "").lower(), t.get("to", {}).get("hash", "").lower()
                    f_l, t_l = t.get("from", {}).get("name", ""), t.get("to", {}).get("name", "")
                    tx_h = t.get("tx_hash") or t.get("hash")
                else: # V1
                    dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                    asset = t.get("tokenSymbol", "TOKEN")
                    val = float(t.get("value", 0)) / (10**int(t.get("tokenDecimal") or 18))
                    f_raw, t_raw = t.get("from", "").lower(), t.get("to", "").lower()
                    f_l, t_l = "", ""
                    tx_h = t.get("hash")

                v4_tok = {
                    "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Token",
                    "Method": "", "Account": addr_c, "From": f_raw, "To": t_raw,
                    "From_Label": f_l, "To_Label": t_l,
                    "Counterparty": t_raw if f_raw == addr_c else f_raw,
                    "Asset": asset, "Amount": val if t_raw == addr_c else -val,
                    "Fee_Asset": "", "Fee_Amount": 0.0,
                    "Source_Way": "Way_1", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                }
                global_raw_txs.append(v4_tok)
                chain_toks.append(v4_tok)

            fb_tokens.caption(f"✅ {len(chain_toks)} Transferts de Tokens")

            # --- VOIE 2 : API SCANS ---
            if api_key:
                st.write(f"🔎 Scan Way_2 pour **{chain}**...")
                items_v2, way2_success = fetch_etherscan_way2(api_host, addr_c, api_key, target_year, max_txs, native)
                if way2_success:
                    if eth_status_final in [False, True]: eth_status_final = True
                    else: eth_status_final = True # Prioritize Success
                elif items_v2 == [] and way2_success is False:
                    # Error or no results? fetch_etherscan_way2 returns False if not status 1
                    pass

                if items_v2:
                    if eth_status_final is False: eth_status_final = True
                    for t, label, dt in items_v2:
                    tx_h = t.get("hash")
                    f_r, t_r = t.get("from", "").lower(), t.get("to", "").lower()
                    amt = float(t.get("value", 0)) / (10**int(t.get("tokenDecimal", 18) or 18))
                    fee_v2 = (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 1e18
                    asset_v2 = t.get("tokenSymbol") or native
                    global_raw_txs.append({
                        "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": label,
                        "Method": t.get("functionName", ""), "Account": addr_c, "From": f_r, "To": t_r,
                        "From_Label": "", "To_Label": "",
                        "Counterparty": t_r if f_r == addr_c else f_r,
                        "Asset": asset_v2, "Amount": amt if t_r == addr_c else -amt,
                        "Fee_Asset": native if f_r == addr_c else "",
                        "Fee_Amount": fee_v2 if f_r == addr_c else 0.0,
                        "Source_Way": "Way_2", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                    })
            pbar.progress((idx + 1) / len(chains))

        # --- VOIE 3 : IMPORTS ---
        st.write("📂 Détection imports RAW (Voie 3)...")
        y_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        if os.path.exists(y_dir):
            for f in os.listdir(y_dir):
                if f.startswith("raw_") and f.endswith(".csv") and "portfolio" not in f:
                    try:
                        df_way3 = pd.read_csv(os.path.join(y_dir, f))
                        for _, r in df_way3.iterrows():
                            d_v = r.to_dict(); d_v["Source_Way"] = "Way_3"; global_raw_txs.append(d_v)
                    except: pass

        # --- FUSION & DÉDOUBLONNAGE ---
        df_merged = pd.DataFrame(global_raw_txs, columns=RAW_V4_COLUMNS)
        if not df_merged.empty:
            df_merged["Date"] = pd.to_datetime(df_merged["Date"], utc=True, errors="coerce")
            df_merged = df_merged.dropna(subset=["Date", "Tx_Hash"])
            def consolidate_group(group):
                w1 = group[group["Source_Way"] == "Way_1"]
                w2 = group[group["Source_Way"] == "Way_2"]
                res = group.iloc[0].copy()
                if not w1.empty:
                    res["From_Label"] = w1.iloc[0].get("From_Label", ""); res["To_Label"] = w1.iloc[0].get("To_Label", "")
                if not w2.empty:
                    res["Fee_Amount"] = w2.iloc[0].get("Fee_Amount", 0.0); res["Method"] = w2.iloc[0].get("Method", "")
                    res["Source_Way"] = "Way_1+2" if not w1.empty else "Way_2"
                return res
            df_final = df_merged.groupby(["Tx_Hash", "Asset", "Account", "Chain"]).apply(consolidate_group).reset_index(drop=True)
            st.session_state.transactions = df_final.sort_values("Date", ascending=False)

            # Met à jour le suivi
            if addr_c not in st.session_state.harvested_accounts: st.session_state.harvested_accounts[addr_c] = {"tx":0, "portfolio":0}
            st.session_state.harvested_accounts[addr_c]["tx"] = len(st.session_state.transactions)
            st.session_state.harvested_accounts[addr_c]["portfolio"] = len(st.session_state.portfolio)

            # Enregistrement dans le registre par compte pour affichage permanent
            st.session_state.account_data_registry[addr_c] = {
                "portfolio": st.session_state.portfolio.copy(),
                "transactions": st.session_state.transactions.copy(),
                "status": {"blockscout": bs_status_final, "etherscan": eth_status_final}
            }

            # Summary stats
            ways_count = df_merged["Source_Way"].value_counts().to_dict()
            st.success("✅ Récolte Multivoie terminée.")
            st.info(f"📊 **Statistiques de Récolte :** Way_1: {ways_count.get('Way_1', 0)} | Way_2: {ways_count.get('Way_2', 0)} | Way_3: {ways_count.get('Way_3', 0)}")

        st.rerun()

# --- Sanctuarisation ---
# Affichage permanent si données présentes (pour éviter la disparition après récolte)
if has_data:
    st.divider()
    st.subheader("💾 Étape Finale : Sanctuariser")
    addr_short = address[:10] if address else "Unknown"
    if st.button(f"Enregistrer les fichiers bruts pour {addr_short}... ({target_year})", width='stretch'):
        from shared_logic import standardize_df_addresses
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Standardize addresses to lowercase hex before sanctuarization
        addr_standardized = address.lower().strip()
        prefix = f"{addr_standardized}_{ts}"

        df_port = standardize_df_addresses(st.session_state.portfolio)
        df_tx = standardize_df_addresses(st.session_state.transactions)

        if not df_port.empty:
            df_port.to_csv(os.path.join(year_dir, f"raw_portfolio_{prefix}.csv"), index=False, encoding="utf-8-sig")

        if not df_tx.empty:
            # Enregistrement du journal consolidé (Toutes voies confondues)
            df_tx.to_csv(os.path.join(year_dir, f"raw_transactions_consolidated_{prefix}.csv"), index=False, encoding="utf-8-sig")

        st.balloons()
        st.success(f"📂 Fichiers enregistrés dans : {year_dir}")

st.sidebar.divider()
st.sidebar.caption("Harvest Sanctuarisation v7.0")
