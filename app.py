import os
import time
import json
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil import tz
from web3 import Web3

# --- Configuration & Initialization ---
st.set_page_config(page_title="Jules Crypto Harvest Pro - Sanctuarisation V7", layout="wide")
st.title("🚜 Sanctuarisation des Données Blockchain (Harvest Pure)")

# Configuration des Réseaux avec Blockscout V1 et V2
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
    target_year = st.number_input("Année à sanctuariser", min_value=2015, max_value=2030, value=2024)
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=50000, value=2000, step=100)

    st.divider()
    st.info("💡 **Conseil Multicomptes** : Récoltez et sanctuarisez vos adresses les unes après les autres. Le dossier final contiendra un fichier par compte.")

    st.divider()
    if st.button("🗑️ Réinitialiser l'Interface"):
        st.session_state.clear()
        st.rerun()

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

def fetch_portfolio_v2(api_v2, addr):
    url = f"{api_v2}/addresses/{addr}/token-balances"
    data = call_api(url)
    return data if data else []

# --- Main App Logic ---
w3 = Web3()
harvest_btn = st.button("🚀 Lancer la Récolte Totale (Step 1 : Brutes)", use_container_width=True)

if harvest_btn:
    if not address or not w3.is_address(address):
        st.error("❌ Adresse invalide.")
    else:
        addr_c = w3.to_checksum_address(address)
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
                portfolio_all.append({
                    "Chain": chain,
                    "Asset": token.get("symbol", "NATIVE" if not token else "TOKEN"),
                    "Quantity": float(b.get("value", 0)) / (10**int(token.get("decimals", 18) or 18)),
                    "Price ($)": b.get("token_price"),
                    "Value ($)": b.get("value_in_usd"), # Blockscout donne souvent USD
                    "Contract": token.get("address")
                })
        df_portfolio = pd.DataFrame(portfolio_all)
        st.dataframe(df_portfolio, use_container_width=True)
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
                    f_addr = t.get("from", {}).get("hash", "").lower()
                    t_addr = t.get("to", {}).get("hash", "").lower()
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
                    method = "" # V1 API basique n'a pas method facilement
                    block = t.get("blockNumber", "")
                    tx_hash = t.get("hash")

                fee = (gas_used * gas_price) / 1e18
                # Extraction USD native V2 via historic_exchange_rate
                rate_usd = float(t.get("historic_exchange_rate") or 0.0)
                val_usd = val * rate_usd if rate_usd > 0 else (t.get("value_in_usd") or 0.0)
                fee_usd = fee * rate_usd if rate_usd > 0 else 0.0

                tx_all.append({
                    "Date": dt, "Chain": chain, "Txn hash": tx_hash, "Type": "Native/Internal",
                    "Method": method, "Block": block, "From": f_addr, "To": t_addr,
                    "Value ETH": val, "Value ($)": val_usd, "Rate ($)": rate_usd,
                    "Fee ETH": fee if f_addr == addr_c.lower() else 0.0,
                    "Fee ($)": fee_usd if f_addr == addr_c.lower() else 0.0
                })
            progress_tx.progress((idx + 1) / len(chains))

        df_tx = pd.DataFrame(tx_all)
        if not df_tx.empty:
            df_tx = df_tx.sort_values("Date", ascending=False)
        st.dataframe(df_tx, use_container_width=True)
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
                    f_addr = t.get("from", {}).get("hash", "").lower()
                    t_addr = t.get("to", {}).get("hash", "").lower()
                    tx_hash = t.get("tx_hash")
                else: # V1
                    dt = datetime.fromtimestamp(int(t.get("timeStamp", 0)), tz=tz.tzutc())
                    asset = t.get("tokenSymbol", "TOKEN")
                    tok_id = t.get("tokenID", "")
                    dec = int(t.get("tokenDecimal") or 18)
                    val = float(t.get("value", 0)) / (10**dec)
                    f_addr = t.get("from", "").lower()
                    t_addr = t.get("to", "").lower()
                    tx_hash = t.get("hash")

                # Extraction USD tokens V2
                val_usd = t.get("value_in_usd") or 0.0
                # Parfois Blockscout V2 met le cours dans le token
                rate_usd = float(t.get("token", {}).get("exchange_rate") or 0.0)

                tok_all.append({
                    "Date": dt, "Chain": chain, "Token": asset, "Token ID": tok_id,
                    "Txn hash": tx_hash, "From": f_addr, "To": t_addr, "Value": val,
                    "Value ($)": val_usd, "Rate ($)": rate_usd
                })
            progress_tok.progress((idx + 1) / len(chains))

        df_tok = pd.DataFrame(tok_all)
        if not df_tok.empty:
            df_tok = df_tok.sort_values("Date", ascending=False)
        st.dataframe(df_tok, use_container_width=True)
        st.session_state.tokens = df_tok

        st.success(f"✅ Récolte terminée pour l'année {target_year} !")

# --- Sanctuarisation ---
if "transactions" in st.session_state and not st.session_state.transactions.empty:
    st.divider()
    st.subheader("💾 Étape Finale : Sanctuariser")
    addr_short = address[:10] if address else "Unknown"
    if st.button(f"Enregistrer les fichiers bruts pour {addr_short}... ({target_year})", use_container_width=True):
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{addr_short}_{ts}"

        st.session_state.portfolio.to_csv(os.path.join(year_dir, f"raw_portfolio_{prefix}.csv"), index=False)
        st.session_state.transactions.to_csv(os.path.join(year_dir, f"raw_transactions_{prefix}.csv"), index=False)
        st.session_state.tokens.to_csv(os.path.join(year_dir, f"raw_token_transfers_{prefix}.csv"), index=False)

        st.balloons()
        st.success(f"📂 Fichiers enregistrés dans : {year_dir}")

st.sidebar.divider()
st.sidebar.caption("Harvest Sanctuarisation v7.0")
