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
    st.set_page_config(page_title="Jules Crypto Harvest Pro - Sanctuarisation V7.5", layout="wide")

st.title("🚜 Sanctuarisation des Données Blockchain (Harvest Pure)")

# Initialisation Session State
if "transactions" not in st.session_state: st.session_state.transactions = pd.DataFrame()
if "portfolio" not in st.session_state: st.session_state.portfolio = pd.DataFrame()
if "harvested_accounts" not in st.session_state: st.session_state.harvested_accounts = {}
if "account_data_registry" not in st.session_state: st.session_state.account_data_registry = {}

# Configuration des Réseaux - ARCHITECTURE MULTI-DOMAINES ETHERSCAN V2
CHAIN_APIS = {
    "Ethereum": {
        "bs_v2": "https://eth.blockscout.com/api/v2",
        "eth_domain": "https://api.etherscan.io",
        "native": "ETH"
    },
    "Base": {
        "bs_v2": "https://base.blockscout.com/api/v2",
        "eth_domain": "https://api.basescan.org",
        "native": "ETH"
    },
    "Arbitrum": {
        "bs_v2": "https://arbitrum.blockscout.com/api/v2",
        "eth_domain": "https://api.arbiscan.io",
        "native": "ETH"
    },
    "Optimism": {
        "bs_v2": "https://optimism.blockscout.com/api/v2",
        "eth_domain": "https://api-optimistic.etherscan.io",
        "native": "ETH"
    },
    "BSC": {
        "bs_v2": "https://api.bscscan.com/api",
        "eth_domain": "https://api.bscscan.com",
        "native": "BNB"
    },
    "Polygon": {
        "bs_v2": "https://polygon.blockscout.com/api/v2",
        "eth_domain": "https://api.polygonscan.com",
        "native": "POL"
    },
    "Avalanche": {
        "bs_v2": "https://api.routescan.io/v2/network/mainnet/evm/43114/etherscan/api",
        "eth_domain": "https://api.snowtrace.io",
        "native": "AVAX"
    }
}

EXPORT_BASE_DIR = "sanctuarisation"

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ Paramètres de Récolte")
    known_displays = sl.get_owner_display_list()
    addr_opts = ["-- Nouvelle Adresse --"] + known_displays
    selected_addr = st.selectbox("Sélectionner un compte", addr_opts)

    if selected_addr == "-- Nouvelle Adresse --":
        address = st.text_input("Entrer l'adresse (0x...)", "")
    else:
        address = sl.resolve_raw_addr(selected_addr)
        st.caption(f"Cible : `{address}`")

    chains_to_scan = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=["Ethereum", "Base", "Arbitrum"])

    st.divider()
    if "_hub_target_year" not in st.session_state:
        st.session_state["_hub_target_year"] = datetime.now().year

    target_year = st.number_input("Année à sanctuariser", min_value=2015, max_value=2030, key="_hub_target_year")
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=50000, value=2000, step=100, key="app_max_txs")

    st.divider()
    st.subheader("🔑 Clé API Etherscan V2")
    v2_api_key = st.text_input("Clé API Unique (V2)", type="password", help="Une seule clé gratuite Etherscan V2 pour tous les domaines.")

    st.divider()
    if st.button("🗑️ Réinitialiser l'Interface"):
        sl.clean_session_state()
        st.rerun()

    st.divider()
    sl.show_status()

# --- RAW V4 Standard ---
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- API Helpers ---
def call_api(url, params=None):
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429: time.sleep(2 * (i + 1)); continue
            r.raise_for_status()
            return r.json()
        except: time.sleep(1); continue
    return None

def fetch_etherscan_v2_domain(domain, addr, api_key, year, max_items, native):
    items = []
    if not api_key: return [], "No API Key"
    url = f"{domain}/api"
    endpoints = [("txlist", "Native"), ("tokentx", "Tokens"), ("txlistinternal", "Internal")]
    final_success = "empty"

    for action, label in endpoints:
        time.sleep(0.4)
        params = {"module": "account", "action": action, "address": addr, "startblock": 0, "endblock": 99999999, "offset": 10000, "sort": "asc", "apikey": api_key}
        try:
            res = call_api(url, params)
            if not res: continue
            res_status, res_result = str(res.get("status")), res.get("result")
            if res_status == "0":
                msg = str(res_result).lower()
                if any(x in msg for x in ["no transactions found", "no records found"]): continue
                return items, str(res_result)
            if not isinstance(res_result, list): continue
            final_success = True
            for t in res_result:
                try:
                    ts = int(t.get('timeStamp') or 0)
                    dt = datetime.fromtimestamp(ts, tz=tz.utc)
                    if dt.year == year: items.append((t, label, dt))
                except: continue
        except Exception as e: return items, f"Error: {str(e)}"
    return items[:max_items], final_success

def fetch_blockscout_v2(api_v2, addr, max_items, year, endpoint):
    items = []
    url = f"{api_v2}/addresses/{addr}/{endpoint}"
    params = {}
    for page in range(100):
        data = call_api(url, params)
        if not data or "items" not in data: break
        for item in data["items"]:
            ts_str = item.get("timestamp") or item.get("block_timestamp")
            if not ts_str: continue
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.year == year: items.append(item)
        if len(items) >= max_items or "next_page_params" not in data or not data["next_page_params"]: break
        params.update(data["next_page_params"])
        time.sleep(0.1)
    return items[:max_items]

def fetch_portfolio_v2(api_v2, addr):
    url = f"{api_v2}/addresses/{addr}/token-balances"
    return call_api(url)

# --- Harvest Loop ---
harvest_btn = st.button("🚀 Lancer la Récolte Totale (Step 1 : Brutes)", width='stretch')
active_addr = address.lower().strip() if address.strip() else None

if harvest_btn:
    if not active_addr or not Web3.is_address(active_addr): st.error("❌ Adresse invalide.")
    else:
        addr_c = Web3.to_checksum_address(active_addr).lower()
        st.info(f"🔍 Récolte : {addr_c}")
        global_raw_txs, portfolio_all, chains_status = [], [], {}
        pbar = st.progress(0)

        for idx, chain in enumerate(chains_to_scan):
            st.write(f"🌐 Analyse de **{chain}**...")
            config, native = CHAIN_APIS[chain], CHAIN_APIS[chain]["native"]
            chains_status[chain] = {"bs": "pending", "eth": "pending", "vol": 0}

            c_f1, c_f2 = st.columns(2)
            f_w1, f_w2 = c_f1.empty(), c_f2.empty()

            # 1. Way 1: Blockscout
            try:
                # 1a. Natives
                raw_bs_native = fetch_blockscout_v2(config["bs_v2"], addr_c, max_txs, target_year, "transactions")
                # 1b. Internals
                raw_bs_int = fetch_blockscout_v2(config["bs_v2"], addr_c, max_txs, target_year, "internal-transactions")
                # 1c. Tokens
                raw_bs_toks = fetch_blockscout_v2(config["bs_v2"], addr_c, max_txs, target_year, "token-transfers")

                # Processing Natives/Internals
                for t in (raw_bs_native + raw_bs_int):
                    dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    tx_h, f_r, t_r = str(t.get("hash") or t.get("tx_hash")).lower().strip(), str(t.get("from", {}).get("hash", "")).lower().strip(), str(t.get("to", {}).get("hash", "")).lower().strip()
                    val = float(t.get("value", 0)) / 1e18
                    global_raw_txs.append({
                        "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Native" if "method" in t else "Internal",
                        "Method": t.get("method", "Internal"), "Account": addr_c,
                        "From": f_r, "To": t_r, "From_Label": t.get("from", {}).get("name", ""), "To_Label": t.get("to", {}).get("name", ""),
                        "Counterparty": t_r if f_r == addr_c else f_r, "Asset": native, "Amount": val if t_r == addr_c else -val,
                        "Fee_Asset": native, "Fee_Amount": (int(t.get("gas_used", 0)) * int(t.get("gas_price", 0))) / 1e18 if f_r == addr_c else 0.0,
                        "Source_Way": "Way_1", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                    })

                # Processing Tokens
                for t in raw_bs_toks:
                    dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    tok = t.get("token") or {}
                    asset, dec = str(tok.get("symbol", "TOKEN")).upper().strip(), int(tok.get("decimals") or 18)
                    val = float(t.get("total", {}).get("value") or t.get("value", 0)) / (10**dec)
                    f_r, t_r = str(t.get("from", {}).get("hash", "")).lower().strip(), str(t.get("to", {}).get("hash", "")).lower().strip()
                    global_raw_txs.append({
                        "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": str(t.get("tx_hash")).lower().strip(), "Type": "Token", "Method": "", "Account": addr_c,
                        "From": f_r, "To": t_r, "From_Label": t.get("from", {}).get("name", ""), "To_Label": t.get("to", {}).get("name", ""),
                        "Counterparty": t_r if f_r == addr_c else f_r, "Asset": asset, "Amount": val if t_r == addr_c else -val,
                        "Fee_Asset": "", "Fee_Amount": 0.0, "Source_Way": "Way_1",
                        "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                    })
                chains_status[chain]["bs"] = True
                f_w1.caption(f"✅ Way_1 (Blockscout) : {len(raw_bs_native) + len(raw_bs_int) + len(raw_bs_toks)} lignes")
            except Exception as e:
                chains_status[chain]["bs"] = f"Error: {str(e)}"
                f_w1.error(f"❌ Way_1 : Échec")

            # 2. Way 2: Etherscan V2
            if v2_api_key:
                res_v2, status_v2 = fetch_etherscan_v2_domain(config["eth_domain"], addr_c, v2_api_key, target_year, max_txs, native)
                chains_status[chain]["eth"] = status_v2
                if res_v2:
                    for t, label, dt in res_v2:
                        tx_h, f_r, t_r = str(t.get("hash")).lower().strip(), str(t.get("from", "")).lower().strip(), str(t.get("to", "")).lower().strip()
                        amt = float(t.get("value", 0)) / (10**int(t.get("tokenDecimal", 18) or 18))
                        asset_v2 = str(t.get("tokenSymbol") or native).upper().strip()
                        global_raw_txs.append({
                            "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": label, "Method": t.get("functionName", ""), "Account": addr_c,
                            "From": f_r, "To": t_r, "From_Label": "", "To_Label": "", "Counterparty": t_r if f_r == addr_c else f_r,
                            "Asset": asset_v2, "Amount": amt if t_r == addr_c else -amt, "Fee_Asset": native if f_r == addr_c else "",
                            "Fee_Amount": (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 1e18 if f_r == addr_c else 0.0,
                            "Source_Way": "Way_2", "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                        })
                    f_w2.caption(f"✅ Way_2 (Etherscan) : {len(res_v2)} lignes")
                else:
                    f_w2.caption(f"ℹ️ Way_2 : Vide ou Erreur ({status_v2})")

            # 3. Portfolio
            try:
                balances = fetch_portfolio_v2(config["bs_v2"], addr_c)
                if balances and "items" in balances:
                    for b in balances["items"]:
                        tok = b.get("token") or {}
                        asset_sym, dec = str(tok.get("symbol", native)).upper().strip(), int(tok.get("decimals", 18) or 18)
                        qty = float(b.get("value", 0)) / (10**dec)
                        portfolio_all.append({
                            "Date": datetime(target_year, 12, 31).isoformat(), "Chain": chain, "Tx_Hash": f"PORT-{addr_c}-{asset_sym}",
                            "Type": "Portfolio", "Method": "Snapshot", "Account": addr_c, "From": "Blockchain", "To": addr_c,
                            "From_Label": "", "To_Label": "", "Counterparty": "Blockchain Snapshot", "Asset": asset_sym, "Amount": qty,
                            "Fee_Asset": "", "Fee_Amount": 0.0, "Source_Way": "Way_1",
                            "Audit_Status": "RAW", "Fee_Audit_Alert": "", "Source_Exchange_Rate": 0.0
                        })
            except: pass

            pbar.progress((idx + 1) / len(chains_to_scan))

        # 4. Way 3 (Local) & Consolidation
        y_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        if os.path.exists(y_dir):
            for f in os.listdir(y_dir):
                if f.startswith("raw_") and f.endswith(".csv") and "portfolio" not in f:
                    try:
                        df_w3 = pd.read_csv(os.path.join(y_dir, f))
                        for _, r in df_w3.iterrows():
                            d_v = r.to_dict(); d_v["Source_Way"] = "Way_3"; global_raw_txs.append(d_v)
                    except: pass

        df_m = pd.DataFrame(global_raw_txs, columns=RAW_V4_COLUMNS)
        if not df_m.empty:
            df_m["Date"] = pd.to_datetime(df_m["Date"], utc=True, errors="coerce")
            df_m = df_m.dropna(subset=["Date", "Tx_Hash"])
            df_m["_amt_round"] = pd.to_numeric(df_m["Amount"], errors="coerce").round(8)
            # Occ index must NOT include Source_Way to allow Way_1 and Way_2 to match
            df_m["_occ"] = df_m.groupby(["Tx_Hash", "Asset", "Chain", "_amt_round", "From", "To"]).cumcount()

            def consolidate_group(group):
                w3, w1, w2 = group[group["Source_Way"]=="Way_3"], group[group["Source_Way"]=="Way_1"], group[group["Source_Way"]=="Way_2"]
                res = w3.iloc[0].copy() if not w3.empty else w1.iloc[0].copy() if not w1.empty else w2.iloc[0].copy()
                if not w1.empty and not w2.empty:
                    res["Fee_Amount"], res["Method"], res["Source_Way"] = w2.iloc[0]["Fee_Amount"], w2.iloc[0]["Method"], "Way_1+2"
                return res
            keys = ["Tx_Hash", "Asset", "Chain", "_amt_round", "From", "To", "_occ"]
            df_f = df_m.groupby(keys, as_index=False).apply(consolidate_group).reset_index(drop=True)
            st.session_state.transactions = df_f.sort_values("Date", ascending=False).drop(columns=["_amt_round", "_occ"], errors="ignore")
            st.session_state.portfolio = pd.DataFrame(portfolio_all, columns=RAW_V4_COLUMNS)
            st.session_state.account_data_registry[addr_c] = {"portfolio": st.session_state.portfolio.copy(), "transactions": st.session_state.transactions.copy(), "status": chains_status}
        st.rerun()

# --- UI Tables ---
if display_registry := st.session_state.account_data_registry:
    for addr, data in display_registry.items():
        with st.expander(f"👤 Compte : {sl.resolve_owner_display(addr)}", expanded=True):
            status = data.get("status", {})
            st.write("🚦 **Status des APIs :**")
            cols = st.columns(len(status))
            for i, (c, s) in enumerate(status.items()):
                bs_ico = "✅" if s["bs"] is True else "❌" if isinstance(s["bs"], str) else "ℹ️"
                eth_ico = "✅" if s["eth"] is True else "❌" if isinstance(s["eth"], str) else "ℹ️"
                cols[i].caption(f"**{c}**\nBS: {bs_ico}\nETH: {eth_ico}")

            st.markdown("#### 📦 Portfolio")
            st.dataframe(data.get("portfolio", pd.DataFrame()), width='stretch', key=f"port_{addr}")

            df_t = data.get("transactions", pd.DataFrame())
            if not df_t.empty:
                mask_tok = (df_t["Type"].str.contains("Token")) | (~df_t["Asset"].isin(["ETH", "POL", "BNB", "AVAX"]))
                st.markdown("#### 📝 Transactions (Natives)")
                st.dataframe(df_t[~mask_tok], width='stretch', key=f"tx_{addr}")
                st.markdown("#### 🪙 Tokens")
                st.dataframe(df_t[mask_tok], width='stretch', key=f"tok_{addr}")

            if st.button(f"💾 Sanctuariser {addr[:10]}...", key=f"save_{addr}"):
                y_dir = os.path.join(EXPORT_BASE_DIR, str(target_year)); os.makedirs(y_dir, exist_ok=True)
                prefix = f"{addr}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                if not data["portfolio"].empty: data["portfolio"].to_csv(os.path.join(year_dir, f"raw_portfolio_{prefix}.csv"), index=False, encoding="utf-8-sig")
                if not df_t.empty: df_t.to_csv(os.path.join(year_dir, f"raw_transactions_consolidated_{prefix}.csv"), index=False, encoding="utf-8-sig")
                st.success("Sanctuarisé.")

sl.show_status(); st.sidebar.caption("Harvest V2 Multi-Domain v7.5")
