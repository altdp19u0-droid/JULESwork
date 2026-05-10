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
if "tokens" not in st.session_state: st.session_state.tokens = pd.DataFrame()
if "portfolio" not in st.session_state: st.session_state.portfolio = pd.DataFrame()

# Configuration des Réseaux avec Blockscout V1 et V2
def load_api_keys():
    if os.path.exists("api_keys.json"):
        with open("api_keys.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

CHAIN_APIS = {
    "Ethereum": {
        "v1": "https://blockscout.com/eth/mainnet/api/",
        "v2": "https://eth.blockscout.com/api/v2",
        "native": "ETH"
    },
    "Arbitrum": {
        "v1": "https://blockscout.com/arb/mainnet/api/",
        "v2": "https://arbitrum.blockscout.com/api/v2",
        "native": "ETH"
    },
    "Base": {
        "v1": "https://base.blockscout.com/api/",
        "v2": "https://base.blockscout.com/api/v2",
        "native": "ETH"
    },
    "Polygon": {
        "v1": "https://polygon.blockscout.com/api/",
        "v2": "https://polygon.blockscout.com/api/v2",
        "native": "POL"
    },
    "Optimism": {
        "v1": "https://optimism.blockscout.com/api/",
        "v2": "https://optimism.blockscout.com/api/v2",
        "native": "ETH"
    }
}

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ Paramètres de Récolte")
    address = st.text_input("Adresse Blockchain (0x...)", "")
    chains = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=list(CHAIN_APIS.keys()))

    st.divider()
    # Unified Hub Year
    if "_hub_target_year" not in st.session_state: st.session_state["_hub_target_year"] = datetime.now().year
    target_year = st.number_input("Année à sanctuariser", min_value=2015, max_value=2030, value=st.session_state["_hub_target_year"], key="_hub_target_year")
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=50000, value=2000, step=100, key="app_max_txs")

    st.divider()
    st.info("💡 **Conseil Multicomptes** : Récoltez et sanctuarisez vos adresses les unes après les autres. Le dossier final contiendra un fichier par compte.")

    st.divider()
    if st.button("🗑️ Réinitialiser l'Interface"):
        from shared_logic import clean_session_state
        clean_session_state()
        st.rerun()

    st.divider()
    show_status()

# --- RAW V4 Standard ---
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert"
]

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
    return data if data else []

# --- Main App Logic ---
harvest_btn = st.button("🚀 Lancer la Récolte Totale (Step 1 : Brutes)", width='stretch')

# Détection de présence de données pour l'affichage permanent
has_data = not st.session_state.transactions.empty or not st.session_state.tokens.empty

# Affichage des données mémorisées (en dehors du bloc bouton pour persistance)
if has_data:
    st.subheader("📦 Portfolio (Dernière Récolte)")
    st.dataframe(st.session_state.portfolio, width='stretch')

    st.subheader(f"📝 Transactions (Dernière Récolte)")
    st.dataframe(st.session_state.transactions, width='stretch')

    st.subheader(f"🪙 Token Transfers (Dernière Récolte)")
    st.dataframe(st.session_state.tokens, width='stretch')

if harvest_btn:
    if not address or not Web3.is_address(address):
        st.error("❌ Adresse invalide.")
    else:
        addr_c = Web3.to_checksum_address(address)
        st.info(f"🔍 Analyse de l'adresse : {addr_c}")

        # 1. Harvest Portfolio (Balances Actuelles)
        st.subheader("📦 Portfolio (État Actuel - Blockscout)")
        portfolio_all = []
        for chain in chains:
            v2 = CHAIN_APIS[chain]["v2"]
            balances = fetch_portfolio_v2(v2, addr_c)
            if isinstance(balances, dict) and "items" in balances:
                balances = balances["items"]

            for b in balances:
                token = b.get("token", {})
                asset_sym = token.get("symbol", "NATIVE" if not token else "TOKEN")
                qty = float(b.get("value", 0)) / (10**int(token.get("decimals", 18) or 18))

                # Mapping to RAW V4 Schema
                portfolio_all.append({
                    "Date": datetime(target_year, 12, 31).isoformat(),
                    "Chain": chain,
                    "Tx_Hash": f"PORT-{addr_c.lower()}-{asset_sym}",
                    "Type": "Portfolio",
                    "Method": "Snapshot",
                    "Account": addr_c.lower(),
                    "From": "Blockchain",
                    "To": addr_c.lower(),
                    "From_Label": "",
                    "To_Label": "",
                    "Counterparty": "Blockchain Snapshot",
                    "Asset": asset_sym,
                    "Amount": qty,
                    "Fee_Asset": "",
                    "Fee_Amount": 0.0,
                    "Source_Way": "Way_1",
                    "Audit_Status": "RAW",
                    "Fee_Audit_Alert": ""
                })
        df_portfolio = pd.DataFrame(portfolio_all, columns=RAW_V4_COLUMNS)
        st.dataframe(df_portfolio, width='stretch')
        st.session_state.portfolio = df_portfolio

        # 2. Harvest Transactions (Natives/Internes)
        st.subheader("📝 Transactions (Journal Brut)")
        tx_all = []
        progress_tx = st.progress(0)
        for idx, chain in enumerate(chains):
            st.write(f"🌐 Transactions sur **{chain}**...")
            v2 = CHAIN_APIS[chain]["v2"]
            v1 = CHAIN_APIS[chain]["v1"]
            native = CHAIN_APIS[chain]["native"]

            # Txs via V2
            raw_txs = fetch_blockscout_v2(v2, addr_c, max_txs, target_year, "transactions")
            if not raw_txs: raw_txs = fetch_blockscout_v1_fallback(v1, addr_c, "txlist", max_txs, target_year)

            for t in raw_txs:
                if "timestamp" in t: # V2
                    dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    val = float(t.get("value", 0)) / 1e18
                    gas_used = int(t.get("gas_used", 0))
                    gas_price = int(t.get("gas_price", 0))
                    f_raw = t.get("from", {}).get("hash", "").lower()
                    t_raw = t.get("to", {}).get("hash", "").lower()
                    f_addr = format_addr(t.get("from"))
                    t_addr = format_addr(t.get("to"))
                    method = t.get("method", "")
                    block = t.get("block", "")
                    tx_hash = t.get("hash")
                else: # V1
                    dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                    val = float(t.get("value", 0)) / 1e18
                    gas_used = int(t.get("gasUsed", 0))
                    gas_price = int(t.get("gasPrice", 0))
                    f_addr = t.get("from", "").lower()
                    t_addr = t.get("to", "").lower()
                    f_raw, t_raw = f_addr, t_addr
                    method = "" # V1 API basique n'a pas method facilement
                    block = t.get("blockNumber", "")
                    tx_hash = t.get("hash")

                fee = (gas_used * gas_price) / 1e18
                # Extraction USD native V2 via historic_exchange_rate
                rate_usd = float(t.get("historic_exchange_rate") or 0.0)
                val_usd = val * rate_usd if rate_usd > 0 else float(t.get("value_in_usd") or 0.0)
                fee_usd = fee * rate_usd if rate_usd > 0 else 0.0

                # Mapping to RAW V4 Schema
                tx_all.append({
                    "Date": dt.isoformat(),
                    "Chain": chain,
                    "Tx_Hash": tx_hash,
                    "Type": "Native",
                    "Method": method,
                    "Account": addr_c.lower(),
                    "From": f_addr,
                    "To": t_addr,
                    "From_Label": "",
                    "To_Label": "",
                    "Counterparty": t_addr if f_raw == addr_c.lower() else f_addr,
                    "Asset": native,
                    "Amount": val,
                    "Fee_Asset": native,
                    "Fee_Amount": fee if f_raw == addr_c.lower() else 0.0,
                    "Source_Way": "Way_1",
                    "Audit_Status": "RAW",
                    "Fee_Audit_Alert": ""
                })
            progress_tx.progress((idx + 1) / len(chains))

        df_tx = pd.DataFrame(tx_all, columns=RAW_V4_COLUMNS)
        if not df_tx.empty:
            df_tx = df_tx.sort_values("Date", ascending=False)
        st.dataframe(df_tx, width='stretch')
        st.session_state.transactions = df_tx

        # 3. Harvest Token Transfers
        st.subheader("🪙 Token Transfers (ERC-20/721/1155)")
        tok_all = []
        progress_tok = st.progress(0)
        for idx, chain in enumerate(chains):
            st.write(f"🌐 Transferts sur **{chain}**...")
            v2 = CHAIN_APIS[chain]["v2"]
            v1 = CHAIN_APIS[chain]["v1"]

            raw_toks = fetch_blockscout_v2(v2, addr_c, max_txs, target_year, "token-transfers")
            if not raw_toks: raw_toks = fetch_blockscout_v1_fallback(v1, addr_c, "tokentx", max_txs, target_year)

            for t in raw_toks:
                if "token" in t: # V2
                    dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    tok = t.get("token", {})
                    asset = tok.get("symbol", "TOKEN")
                    tok_id = t.get("token_id", "")
                    dec = int(tok.get("decimals") or 18)
                    raw_val = extract_value(t.get("total") or t.get("value", "0"))
                    val = float(raw_val) / (10**dec)
                    f_raw = t.get("from", {}).get("hash", "").lower()
                    t_raw = t.get("to", {}).get("hash", "").lower()
                    f_addr = format_addr(t.get("from"))
                    t_addr = format_addr(t.get("to"))
                    tx_hash = t.get("tx_hash") or t.get("hash") or t.get("transaction_hash")
                else: # V1
                    dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                    asset = t.get("tokenSymbol", "TOKEN")
                    tok_id = t.get("tokenID", "")
                    dec = int(t.get("tokenDecimal") or 18)
                    val = float(t.get("value", 0)) / (10**dec)
                    f_addr = t.get("from", "").lower()
                    t_addr = t.get("to", "").lower()
                    f_raw, t_raw = f_addr, t_addr
                    tx_hash = t.get("hash")

                # Extraction USD tokens V2 (Step 2: improved rate calculation)
                val_usd = float(t.get("value_in_usd") or 0.0)
                rate_usd = float(t.get("token", {}).get("exchange_rate") or 0.0)
                if rate_usd == 0 and val_usd > 0 and val > 0:
                    rate_usd = val_usd / val

                # Mapping to RAW V4 Schema
                tok_all.append({
                    "Date": dt.isoformat(),
                    "Chain": chain,
                    "Tx_Hash": tx_hash,
                    "Type": "Token",
                    "Method": "",
                    "Account": addr_c.lower(),
                    "From": f_addr,
                    "To": t_addr,
                    "From_Label": "",
                    "To_Label": "",
                    "Counterparty": t_addr if f_raw == addr_c.lower() else f_addr,
                    "Asset": asset,
                    "Amount": float(val),
                    "Fee_Asset": "", # Often not directly available in token transfer event
                    "Fee_Amount": 0.0,
                    "Source_Way": "Way_1",
                    "Audit_Status": "RAW",
                    "Fee_Audit_Alert": ""
                })
            progress_tok.progress((idx + 1) / len(chains))

        df_tok = pd.DataFrame(tok_all, columns=RAW_V4_COLUMNS)
        if not df_tok.empty:
            df_tok = df_tok.sort_values("Date", ascending=False)
        st.dataframe(df_tok, width='stretch')
        st.session_state.tokens = df_tok

        st.success(f"✅ Récolte terminée pour l'année {target_year} !")
        st.rerun() # Force re-execution to show the Sanctuarize button immediately

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
        df_tok = standardize_df_addresses(st.session_state.tokens)

        df_port.to_csv(os.path.join(year_dir, f"raw_portfolio_{prefix}.csv"), index=False, encoding="utf-8-sig")
        df_tx.to_csv(os.path.join(year_dir, f"raw_transactions_{prefix}.csv"), index=False, encoding="utf-8-sig")
        df_tok.to_csv(os.path.join(year_dir, f"raw_token_transfers_{prefix}.csv"), index=False, encoding="utf-8-sig")

        st.balloons()
        st.success(f"📂 Fichiers enregistrés dans : {year_dir}")

st.sidebar.divider()
st.sidebar.caption("Harvest Sanctuarisation v7.0")
