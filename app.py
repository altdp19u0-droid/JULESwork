import os
import time
import json
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil import tz
from web3 import Web3
import shared_logic as sl

# --- Configuration & Initialization ---
if "is_hub" not in st.session_state:
    st.set_page_config(page_title="Jules Crypto Harvest Pro - Sanctuarisation V7", layout="wide")

st.title("🚜 Sanctuarisation des Données Blockchain (Harvest Pure)")

# Initialisation Session State
if "transactions" not in st.session_state: st.session_state.transactions = pd.DataFrame()
if "portfolio" not in st.session_state: st.session_state.portfolio = pd.DataFrame()
if "harvested_accounts" not in st.session_state: st.session_state.harvested_accounts = {} # {addr: {"tx": 0, "portfolio": 0}}
if "account_data_registry" not in st.session_state: st.session_state.account_data_registry = {} # {addr: {"portfolio": df, "transactions": df, "status": {}}}

# Configuration des Réseaux avec Etherscan V2 ChainIDs
# V2 UNIFIED ENDPOINT: https://api.etherscan.io/v2/api
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
        "chain_id": 1,
        "native": "ETH"
    },
    "Arbitrum": {
        "v1": "https://arbitrum.blockscout.com/api",
        "v2": "https://arbitrum.blockscout.com/api/v2",
        "api_host": "api.arbiscan.io",
        "chain_id": 42161,
        "native": "ETH"
    },
    "Base": {
        "v1": "https://base.blockscout.com/api",
        "v2": "https://base.blockscout.com/api/v2",
        "api_host": "api.basescan.org",
        "chain_id": 8453,
        "native": "ETH"
    },
    "Polygon": {
        "v1": "https://polygon.blockscout.com/api",
        "v2": "https://polygon.blockscout.com/api/v2",
        "api_host": "api.polygonscan.com",
        "chain_id": 137,
        "native": "POL"
    },
    "Optimism": {
        "v1": "https://optimism.blockscout.com/api",
        "v2": "https://optimism.blockscout.com/api/v2",
        "api_host": "api-optimistic.etherscan.io",
        "chain_id": 10,
        "native": "ETH"
    },
    "BSC": {
        "v1": "https://api.bscscan.com/api",
        "v2": "https://api.bscscan.com/api",
        "api_host": "api.bscscan.com",
        "chain_id": 56,
        "native": "BNB"
    }
}

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ Paramètres de Récolte")

    # Selection of known accounts or new address
    known_displays = sl.get_owner_display_list()
    addr_opts = ["-- Nouvelle Adresse --"] + known_displays
    selected_addr = st.selectbox("Sélectionner un compte", addr_opts)

    if selected_addr == "-- Nouvelle Adresse --":
        address = st.text_input("Entrer l'adresse (0x...)", "")
    else:
        address = sl.resolve_raw_addr(selected_addr)
        st.caption(f"Cible : `{address}`")

    chains = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=["Ethereum", "Polygon", "Arbitrum", "Base", "Optimism"])

    st.divider()
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state: st.session_state["_hub_target_year"] = datetime.now().year
    target_year = st.number_input("Année à sanctuariser", min_value=2015, max_value=2030, value=st.session_state["_hub_target_year"], key="_hub_target_year")
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=50000, value=2000, step=100, key="app_max_txs")

    st.divider()
    st.subheader("🔑 Clés API (Voie 2)")

    # Universal Key Input (V2 support)
    universal_key = st.text_input("Clé API Unique (Etherscan V2)", type="password", help="Cette clé sera utilisée pour tous les réseaux compatibles V2 si aucune clé spécifique n'est trouvée.")

    st.warning("💡 **Etherscan V2** : Avec une clé V2, la 'Clé Unique' permet de récolter Ethereum, Arbitrum, Base, Polygon et BSC sans créer de comptes séparés sur chaque explorateur.")

    api_keys_loaded = load_api_keys()
    # Merge: Specific keys from file take priority over universal key
    api_keys = {c: api_keys_loaded.get(c, universal_key) for c in CHAIN_APIS.keys()}

    if st.checkbox("Voir le détail des clés chargées"):
        for c, k in api_keys.items():
            st.caption(f"- {c} : {'✅ Chargée' if k else '❌ Manquante'}")

    st.divider()
    st.info("💡 **Conseil Multicomptes** : Récoltez et sanctuarisez vos adresses les unes après les autres. Le dossier final contiendra un fichier par compte.")

    st.divider()
    if st.button("🗑️ Réinitialiser l'Interface"):
        sl.clean_session_state()
        st.rerun()

    st.divider()
    sl.show_status()

# --- RAW V4 Standard (19 colonnes) ---
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- Way 2 API Helper ---
def fetch_etherscan_way2(chain_id, api_host, addr, api_key, year, max_items, native):
    """
    Fetches transactions using Etherscan API V2 unified endpoint with Smart Fallback to V1.
    Returns: (items_list, success_status)
    """
    items = []
    if not api_key: return [], "empty"

    final_status = "empty"
    endpoints = [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]

    # FORCING V2: On utilise systématiquement l'endpoint unifié si une clé est présente et chain_id connu
    v2_url = "https://api.etherscan.io/v2/api"
    v1_url = f"https://{api_host}/api"

    for action, label in endpoints:
        time.sleep(0.4)
        start_block = 0
        # On réinitialise l'url courante pour chaque type de récolte (Native/Tokens/Internal)
        # car un basculement V2->V1 peut être nécessaire pour l'un mais pas l'autre (rare mais possible)
        current_base_url = v2_url if chain_id else v1_url

        for loop in range(10):
            params = {
                "module": "account", "action": action, "address": addr,
                "startblock": start_block, "endblock": 99999999,
                "offset": 10000, "sort": "asc", "apikey": api_key
            }
            if current_base_url == v2_url: params["chainid"] = chain_id

            try:
                res = requests.get(current_base_url, params=params, timeout=25).json()
                res_status = str(res.get("status"))
                res_result = res.get("result")

                if res_status == "0":
                    msg = str(res_result).lower()

                    # --- SMART FALLBACK V2 -> V1 ---
                    # Si l'API V2 rejette la chaîne ou l'accès free
                    if current_base_url == v2_url and ("free api access is not supported" in msg or "not supported for this chain" in msg or "invalid chainid" in msg):
                        st.toast(f"🔄 Basculement V2 -> V1 pour {api_host}...")
                        current_base_url = v1_url
                        params.pop("chainid", None)
                        res = requests.get(current_base_url, params=params, timeout=25).json()
                        res_status = str(res.get("status"))
                        res_result = res.get("result")
                        msg = str(res_result).lower()

                    if any(x in msg for x in ["no transactions found", "no records found", "no internal transactions found", "no matching entries"]):
                        break
                    elif any(x in msg for x in ["rate limit", "max rate", "fast for us"]):
                        st.toast(f"⚠️ {api_host} : Rate limit, pause 5s...")
                        time.sleep(5)
                        res = requests.get(current_base_url, params=params, timeout=25).json()
                        if str(res.get("status")) != "0": res_result = res.get("result")
                        else: break
                    else:
                        # Erreur réelle (ex: API key invalide)
                        return items, str(res_result)

                if not isinstance(res_result, list) or not res_result:
                    break

                final_status = True
                for t in res_result:
                    try:
                        ts = int(t.get('timeStamp') or 0)
                        if not ts: continue
                        dt = datetime.fromtimestamp(ts, tz=tz.tzutc())
                        if dt.year == year:
                            items.append((t, label, dt))
                    except: continue

                last_block = int(res_result[-1].get('blockNumber', 0))
                if last_block <= start_block: break
                start_block = last_block + 1
                if len(res_result) < 10000: break
                time.sleep(0.4)
            except Exception as e:
                return items, f"Erreur: {str(e)}"

    return items[:max_items], final_status

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
    if isinstance(v, dict):
        return v.get("total") or v.get("value") or "0"
    return str(v or "0")

def fetch_portfolio_v2(api_v2, addr):
    url = f"{api_v2}/addresses/{addr}/token-balances"
    data = call_api(url)
    return data

# --- Main App Logic ---
harvest_btn = st.button("🚀 Lancer la Récolte Totale (Step 1 : Brutes)", width='stretch')

if st.session_state.harvested_accounts:
    st.subheader("🏦 Suivi de la Récolte Session")
    acc_data = []
    for a, v in st.session_state.harvested_accounts.items():
        disp = sl.resolve_owner_display(a)
        acc_data.append({"Compte": disp, "Txs": v["tx"], "Actifs": v["portfolio"]})
    st.dataframe(pd.DataFrame(acc_data), hide_index=True, width='stretch')

active_addr = address.lower().strip() if address.strip() else None

display_registry = st.session_state.account_data_registry.copy()
if active_addr and active_addr not in display_registry:
    display_registry[active_addr] = {
        "portfolio": pd.DataFrame(columns=RAW_V4_COLUMNS),
        "transactions": pd.DataFrame(columns=RAW_V4_COLUMNS),
        "status": {"blockscout": {}, "etherscan": {}}
    }

if display_registry:
    st.divider()
    st.header("📋 Tableaux de Collecte par Compte")

    for addr, data in display_registry.items():
        is_active = (addr == active_addr)
        disp_name = sl.resolve_owner_display(addr)
        with st.expander(f"👤 Compte : {disp_name} {'(Actif)' if is_active else ''}", expanded=is_active):
            api_status = data.get("status", {})
            bs_map = api_status.get("blockscout") or {}
            eth_map = api_status.get("etherscan") or {}

            if bs_map or eth_map:
                c1, c2 = st.columns(2)
                # BS summary
                bs_errors = [c for c, v in bs_map.items() if v is False]
                if bs_errors: c1.error(f"❌ Blockscout : Erreur sur {', '.join(bs_errors)}")
                elif any(v is True for v in bs_map.values()): c1.success("✅ Blockscout : Connecté")
                elif bs_map: c1.warning("ℹ️ Blockscout : Connecté (Vide)")

                # ETHerscan / API Scans summary
                eth_fails = {c: v for c, v in eth_map.items() if v is False or (isinstance(v, str) and v not in ["empty", "True"])}
                eth_success = [c for c, v in eth_map.items() if v is True]

                if eth_fails:
                    err_msgs = [f"**{c}** : {v}" if isinstance(v, str) else c for c, v in eth_fails.items()]
                    c2.error(f"❌ API Scans : Échec\n\n{chr(10).join(err_msgs)}")
                elif eth_success:
                    c2.success(f"✅ API Scans : Connecté ({', '.join(eth_success)})")
                elif eth_map:
                    c2.warning("ℹ️ API Scans : Connecté (Aucune donnée ou Clé absente)")
            else:
                st.info("💡 Cliquez sur 'Lancer la Récolte' pour interroger les APIs Blockscout et Etherscan pour ce compte.")

            # 1. PORTFOLIO
            st.markdown("#### 📦 Portfolio")
            df_p = data.get("portfolio", pd.DataFrame(columns=RAW_V4_COLUMNS))
            # Ensure columns order and presence
            df_p = df_p.reindex(columns=RAW_V4_COLUMNS).fillna("")
            st.dataframe(df_p, width='stretch', key=f"df_p_v14_{addr}")

            # 2. TRANSACTIONS
            df_t_all = data.get("transactions", pd.DataFrame(columns=RAW_V4_COLUMNS))
            # Critical: preserve all columns for filters and export
            df_t_all = df_t_all.reindex(columns=RAW_V4_COLUMNS).fillna("")

            df_native = pd.DataFrame(columns=RAW_V4_COLUMNS)
            df_tokens = pd.DataFrame(columns=RAW_V4_COLUMNS)

            if not df_t_all.empty:
                # Identification robuste des types
                t_low = df_t_all["Type"].astype(str).str.lower()
                mask_native = t_low.str.contains("native|internal") & ~t_low.str.contains("token")
                df_native = df_t_all[mask_native].copy()

                # Le reste va dans Tokens (Token, CEX_Mvt, etc.)
                df_tokens = df_t_all[~mask_native].copy()

            st.markdown(f"#### 📝 Transactions ({len(df_native)})")
            st.caption("Mouvements natifs (ETH, POL, BNB...) et transactions internes.")
            st.dataframe(df_native, width='stretch', key=f"df_native_v14_{addr}")

            # 3. TOKENS
            st.markdown(f"#### 🪙 Tokens ({len(df_tokens)})")
            st.caption("Transferts d'actifs ERC-20, Stables et mouvements de plateformes.")
            if df_tokens.empty and not df_t_all.empty:
                 st.info("Aucun transfert de token détecté dans ce journal.")
            st.dataframe(df_tokens, width='stretch', key=f"df_tokens_v14_{addr}")

if harvest_btn:
    raw_addr = sl.resolve_raw_addr(address)
    if not raw_addr or not Web3.is_address(raw_addr):
        st.error("❌ Adresse invalide.")
    else:
        addr_c = Web3.to_checksum_address(raw_addr).lower()
        st.info(f"🔍 Analyse de l'adresse : {addr_c}")

        global_raw_txs = []
        bs_chains_status = {}
        eth_chains_status = {}

        # 1. Portfolio
        st.subheader("📦 Portfolio (État Actuel - Blockscout)")
        portfolio_all = []
        for chain in chains:
            v2 = CHAIN_APIS[chain]["v2"]
            bs_chains_status[chain] = "empty"
            try:
                balances = fetch_portfolio_v2(v2, addr_c)
                if balances is not None:
                    if isinstance(balances, dict) and "items" in balances: balances = balances["items"]
                    if balances:
                        bs_chains_status[chain] = True
                        for b in balances:
                            token = b.get("token", {})
                            asset_sym = str(token.get("symbol", "NATIVE" if not token else "TOKEN")).upper().strip()
                            qty = float(b.get("value", 0)) / (10**int(token.get("decimals", 18) or 18))
                            portfolio_all.append({
                                "Date": datetime(target_year, 12, 31).isoformat(),
                                "Chain": chain, "Tx_Hash": f"PORT-{addr_c}-{asset_sym}",
                                "Type": "Portfolio", "Method": "Snapshot", "Account": addr_c,
                                "From": "Blockchain", "To": addr_c, "From_Label": "", "To_Label": "",
                                "Counterparty": "Blockchain Snapshot", "Asset": asset_sym, "Amount": qty,
                                "Fee_Asset": "", "Fee_Amount": 0.0, "Source_Way": "Way_1",
                                "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                            })
            except: bs_chains_status[chain] = False

        st.session_state.portfolio = pd.DataFrame(portfolio_all, columns=RAW_V4_COLUMNS)

        # 2. Transactions
        st.subheader("📝 Récolte Multivoie (Journal Brut)")
        pbar = st.progress(0)

        for idx, chain in enumerate(chains):
            st.write(f"🌐 Analyse de **{chain}**...")
            c_fb1, c_fb2 = st.columns(2)
            fb_native, fb_tokens = c_fb1.empty(), c_fb2.empty()
            chain_txs, chain_toks = [], []

            v2, v1 = CHAIN_APIS[chain]["v2"], CHAIN_APIS[chain]["v1"]
            api_host, native = CHAIN_APIS[chain]["api_host"], CHAIN_APIS[chain]["native"]
            api_key = api_keys.get(chain)
            cid = CHAIN_APIS[chain].get("chain_id")
            eth_chains_status[chain] = "empty" if not api_key else None

            # --- VOIE 1 ---
            raw_v1_txs = fetch_blockscout_v2(v2, addr_c, max_txs, target_year, "transactions")
            if not raw_v1_txs: raw_v1_txs = fetch_blockscout_v1_fallback(v1, addr_c, "txlist", max_txs, target_year)
            for t in raw_v1_txs:
                try:
                    if "timestamp" in t:
                        dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                        val = float(t.get("value", 0)) / 1e18
                        f_obj, t_obj = t.get("from") or {}, t.get("to") or {}
                        f_raw = str(f_obj.get("hash") if isinstance(f_obj, dict) else f_obj).lower().strip()
                        t_raw = str(t_obj.get("hash") if isinstance(t_obj, dict) else t_obj).lower().strip()
                        f_l = f_obj.get("name", "") if isinstance(f_obj, dict) else ""
                        t_l = t_obj.get("name", "") if isinstance(t_obj, dict) else ""
                        tx_h = str(t.get("hash")).lower().strip()
                        gas_u, gas_p, meth = int(t.get("gas_used") or 0), int(t.get("gas_price") or 0), t.get("method", "")
                    else:
                        dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                        val = float(t.get("value", 0)) / 1e18
                        f_raw, t_raw = str(t.get("from", "")).lower().strip(), str(t.get("to", "")).lower().strip()
                        f_l, t_l, tx_h, meth = "", "", str(t.get("hash")).lower().strip(), ""
                        gas_u, gas_p = int(t.get("gasUsed", 0)), int(t.get("gasPrice", 0))

                    v4_tx = {
                        "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Native",
                        "Method": meth, "Account": addr_c, "From": f_raw, "To": t_raw,
                        "From_Label": f_l, "To_Label": t_l, "Counterparty": t_raw if f_raw == addr_c else f_raw,
                        "Asset": native.upper().strip(), "Amount": val if t_raw == addr_c else -val,
                        "Fee_Asset": native.upper().strip(), "Fee_Amount": (gas_u * gas_p) / 1e18 if f_raw == addr_c else 0.0,
                        "Source_Way": "Way_1", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                    }
                    global_raw_txs.append(v4_tx); chain_txs.append(v4_tx)
                except: continue
            fb_native.caption(f"✅ {len(chain_txs)} Transactions Natives")

            raw_v1_toks = fetch_blockscout_v2(v2, addr_c, max_txs, target_year, "token-transfers")
            if not raw_v1_toks: raw_v1_toks = fetch_blockscout_v1_fallback(v1, addr_c, "tokentx", max_txs, target_year)
            for t in raw_v1_toks:
                try:
                    if "token" in t:
                        dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                        tok = t.get("token") or {}
                        asset = str(tok.get("symbol", "TOKEN")).upper().strip()
                        dec = int(tok.get("decimals") or 18)
                        val = float(extract_value(t.get("total") or t.get("value", "0"))) / (10**dec)
                        f_obj, t_obj = t.get("from") or {}, t.get("to") or {}
                        f_raw, t_raw = str(f_obj.get("hash") if isinstance(f_obj, dict) else f_obj).lower().strip(), str(t_obj.get("hash") if isinstance(t_obj, dict) else t_obj).lower().strip()
                        f_l, t_l = (f_obj.get("name", "") if isinstance(f_obj, dict) else ""), (t_obj.get("name", "") if isinstance(t_obj, dict) else "")
                        tx_h = str(t.get("tx_hash") or t.get("hash")).lower().strip()
                    else:
                        dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                        asset = str(t.get("tokenSymbol", "TOKEN")).upper().strip()
                        val = float(t.get("value", 0)) / (10**int(t.get("tokenDecimal") or 18))
                        f_raw, t_raw = str(t.get("from", "")).lower().strip(), str(t.get("to", "")).lower().strip()
                        f_l, t_l, tx_h = "", "", str(t.get("hash")).lower().strip()

                    v4_tok = {
                        "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Token",
                        "Method": "", "Account": addr_c, "From": f_raw, "To": t_raw,
                        "From_Label": f_l, "To_Label": t_l, "Counterparty": t_raw if f_raw == addr_c else f_raw,
                        "Asset": asset, "Amount": val if t_raw == addr_c else -val,
                        "Fee_Asset": "", "Fee_Amount": 0.0, "Source_Way": "Way_1",
                        "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                    }
                    global_raw_txs.append(v4_tok); chain_toks.append(v4_tok)
                except: continue
            fb_tokens.caption(f"✅ {len(chain_toks)} Transferts de Tokens")

            # --- VOIE 2 ---
            if api_key:
                st.write(f"🔎 Scan Way_2 pour **{chain}**...")
                items_v2, way2_res = fetch_etherscan_way2(cid, api_host, addr_c, api_key, target_year, max_txs, native)
                eth_chains_status[chain] = way2_res
                if items_v2:
                    for t, label, dt in items_v2:
                        tx_h = str(t.get("hash")).lower().strip()
                        f_r, t_r = str(t.get("from", "")).lower().strip(), str(t.get("to", "")).lower().strip()
                        amt = float(t.get("value", 0)) / (10**int(t.get("tokenDecimal", 18) or 18))
                        asset_v2 = str(t.get("tokenSymbol") or native).upper().strip()
                        global_raw_txs.append({
                            "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": label,
                            "Method": t.get("functionName", ""), "Account": addr_c, "From": f_r, "To": t_r,
                            "From_Label": "", "To_Label": "", "Counterparty": t_r if f_r == addr_c else f_r,
                            "Asset": asset_v2, "Amount": amt if t_r == addr_c else -amt,
                            "Fee_Asset": native.upper().strip() if f_r == addr_c else "",
                            "Fee_Amount": (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 1e18 if f_r == addr_c else 0.0,
                            "Source_Way": "Way_2", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                        })
            pbar.progress((idx + 1) / len(chains))

        # --- VOIE 3 & FUSION ---
        y_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        if os.path.exists(y_dir):
            for f in os.listdir(y_dir):
                if f.startswith("raw_") and f.endswith(".csv") and "portfolio" not in f:
                    try:
                        df_w3 = pd.read_csv(os.path.join(y_dir, f))
                        for _, r in df_w3.iterrows():
                            d_v = r.to_dict(); d_v["Source_Way"] = "Way_3"; global_raw_txs.append(d_v)
                    except: pass

        df_merged = pd.DataFrame(global_raw_txs, columns=RAW_V4_COLUMNS)
        if not df_merged.empty:
            df_merged["Date"] = pd.to_datetime(df_merged["Date"], utc=True, errors="coerce")
            df_merged = df_merged.dropna(subset=["Date", "Tx_Hash"])
            def consolidate_group(group):
                w3, w1, w2 = group[group["Source_Way"] == "Way_3"], group[group["Source_Way"] == "Way_1"], group[group["Source_Way"] == "Way_2"]
                res = w3.iloc[0].copy() if not w3.empty else w1.iloc[0].copy() if not w1.empty else w2.iloc[0].copy()
                if not w1.empty: res["From_Label"], res["To_Label"] = w1.iloc[0].get("From_Label", ""), w1.iloc[0].get("To_Label", "")
                if not w2.empty: res["Fee_Amount"], res["Method"] = w2.iloc[0].get("Fee_Amount", 0.0), w2.iloc[0].get("Method", "")
                res["Source_Way"] = "Way_" + "+".join(sorted(group["Source_Way"].unique())).replace("Way_", "")
                return res
            df_final = df_merged.groupby(["Tx_Hash", "Asset", "Account", "Chain"]).apply(consolidate_group).reset_index(drop=True)
            st.session_state.transactions = df_final.sort_values("Date", ascending=False)
            st.session_state.account_data_registry[addr_c] = {
                "portfolio": st.session_state.portfolio.copy(), "transactions": st.session_state.transactions.copy(),
                "status": {"blockscout": bs_chains_status, "etherscan": eth_chains_status}
            }
            if addr_c not in st.session_state.harvested_accounts: st.session_state.harvested_accounts[addr_c] = {"tx":0, "portfolio":0}
            st.session_state.harvested_accounts[addr_c].update({"tx": len(df_final), "portfolio": len(st.session_state.portfolio)})
        st.rerun()

if has_data := (not st.session_state.transactions.empty or not st.session_state.portfolio.empty):
    st.divider(); st.subheader("💾 Étape Finale : Sanctuariser")
    raw_addr_final = sl.resolve_raw_addr(address)
    if st.button(f"Enregistrer les fichiers bruts pour {raw_addr_final[:10]}... ({target_year})", width='stretch'):
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year)); os.makedirs(year_dir, exist_ok=True)
        prefix = f"{raw_addr_final.lower().strip()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        df_p_s, df_t_s = sl.standardize_df_addresses(st.session_state.portfolio), sl.standardize_df_addresses(st.session_state.transactions)
        if not df_p_s.empty: df_p_s.to_csv(os.path.join(year_dir, f"raw_portfolio_{prefix}.csv"), index=False, encoding="utf-8-sig")
        if not df_t_s.empty: df_t_s.to_csv(os.path.join(year_dir, f"raw_transactions_consolidated_{prefix}.csv"), index=False, encoding="utf-8-sig")
        st.balloons(); st.success(f"📂 Fichiers enregistrés dans : {year_dir}")

st.sidebar.divider(); sl.show_status(); st.sidebar.caption("Harvest Sanctuarisation v7.1")
