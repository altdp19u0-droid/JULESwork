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
    st.set_page_config(page_title="Jules Crypto Harvest Pro - Sanctuarisation V7.8", layout="wide")

st.title("🚜 Sanctuarisation des Données Blockchain (Harvest Pure)")

# Configuration des Réseaux - ARCHITECTURE REST ETHERSCAN V2
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

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres de Récolte")

    # Load Unified Processing Year
    g_conf = sl.load_global_config()
    default_year = g_conf.get("processing_year") or datetime.now().year

    known_displays = sl.get_owner_display_list()
    addr_opts = ["-- Nouvelle Adresse --"] + known_displays
    selected_addr = st.selectbox("Sélectionner un compte", addr_opts)
    if selected_addr == "-- Nouvelle Adresse --": address = st.text_input("Adresse (0x...)", "")
    else:
        address = sl.resolve_raw_addr(selected_addr)
        st.caption(f"Cible : `{address}`")
    chains_to_scan = st.multiselect("Chaînes", list(CHAIN_APIS.keys()), default=["Ethereum", "Base", "Arbitrum"])
    st.divider()

    # Synchronized Hub Processing Year
    target_year = st.number_input("Année de traitement", min_value=2015, max_value=2030, key="_hub_target_year")

    # Persist change if modified here too
    if target_year != g_conf.get("processing_year"):
        g_conf["processing_year"] = int(target_year); sl.save_global_config(g_conf)

    max_txs = st.number_input("Max transactions", min_value=10, max_value=50000, value=2000, step=100, key="app_max_txs")
    st.divider()
    st.subheader("🔑 Clé API Etherscan V2")
    v2_api_key = st.text_input("Clé API Unique (V2)", type="password")
    st.divider()
    if st.button("🗑️ Réinitialiser"): sl.clean_session_state(); st.rerun()
    sl.show_status()

# --- RAW V4 Standard ---
RAW_V4_COLUMNS = [
    "Date", "Chain", "Tx_Hash", "Type", "Method", "Account",
    "From", "To", "From_Label", "To_Label", "Counterparty",
    "Asset", "Amount", "Valeur $", "USD prix asset reçu", "USD prix asset envoyé", "USD prix de fée asset",
    "Fee_Asset", "Fee_Amount",
    "Source_Way", "Audit_Status", "Fee_Audit_Alert", "Source_Exchange_Rate"
]

# --- API Helpers ---
def call_api(url, params=None):
    for i in range(2):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 429: time.sleep(5); continue
            return r.json()
        except: time.sleep(1); continue
    return None

def fetch_etherscan_v2_rest(domain, addr, api_key, year, max_items, native):
    items = []
    if not api_key: return [], "No API Key"
    endpoints = [("transactions", "Native"), ("erc20-transfers", "Tokens"), ("internal-transactions", "Internal")]
    final_status = "empty"
    for path, label in endpoints:
        time.sleep(0.4)
        url = f"{domain}/api/v2/accounts/{addr}/{path}"
        params = {"apikey": api_key, "page": 1, "offset": 100}
        try:
            res = call_api(url, params)
            if not res: continue

            # Etherscan V2 can return items at root, in result, or in result.items
            data_list = res.get("items")
            if not isinstance(data_list, list):
                res_obj = res.get("result")
                if isinstance(res_obj, list): data_list = res_obj
                elif isinstance(res_obj, dict): data_list = res_obj.get("items")

            if not isinstance(data_list, list):
                if res.get("status") == "0" and label == "Native": final_status = res.get("result")
                continue
            final_status = True
            for t in data_list:
                try:
                    ts = int(t.get('timeStamp') or t.get('timestamp') or 0)
                    dt = datetime.fromtimestamp(ts, tz=tz.utc)
                    if dt.year == year: items.append((t, label, dt))
                except: continue
        except Exception as e: return items, f"Error: {str(e)}"
    return items[:max_items], final_status

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
            if dt.year == year: items.append(item)
        if len(items) >= max_items or "next_page_params" not in data or not data["next_page_params"]: break
        params.update(data["next_page_params"])
        time.sleep(0.1)
    return items[:max_items]

# --- Harvest Loop ---
harvest_btn = st.button("🚀 Lancer la Récolte Totale (Step 1 : Brutes)", width='stretch')

if "harvest_data" not in st.session_state: st.session_state.harvest_data = {}

if harvest_btn:
    addr_c = Web3.to_checksum_address(address).lower() if address else None
    if not addr_c: st.error("❌ Adresse invalide."); st.stop()

    st.info(f"🔍 Récolte : {addr_c}")
    all_txs, all_port, chains_status = [], [], {}
    pbar = st.progress(0)

    for idx, chain in enumerate(chains_to_scan):
        st.write(f"🌐 Analyse de **{chain}**...")
        cfg, native = CHAIN_APIS[chain], CHAIN_APIS[chain]["native"]
        chains_status[chain] = {"bs": "pending", "eth": "pending"}
        c1, c2 = st.columns(2); f1, f2 = c1.empty(), c2.empty()

        # 1. Blockscout (Transactions)
        try:
            bs_nat = fetch_blockscout_v2(cfg["bs_v2"], addr_c, max_txs, target_year, "transactions")
            bs_int = fetch_blockscout_v2(cfg["bs_v2"], addr_c, max_txs, target_year, "internal-transactions")
            bs_tok = fetch_blockscout_v2(cfg["bs_v2"], addr_c, max_txs, target_year, "token-transfers")

            def create_raw_row():
                return {c: "" if "Label" in c or "Status" in c or "Alert" in c or "Hash" in c or "Asset" in c or "Type" in c or "Method" in c or "Chain" in c or "Way" in c or "Account" in c or "From" in c or "To" in c or "Counterparty" in c else 0.0 for c in RAW_V4_COLUMNS}

            for t in (bs_nat + bs_int):
                dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                h_val = t.get("hash") or t.get("tx_hash") or t.get("txHash") or t.get("transaction_hash")
                tx_h = str(h_val).lower().strip() if (h_val and str(h_val).lower() != "none") else "none"
                f_r, t_r = str(t.get("from", {}).get("hash", "")).lower().strip(), str(t.get("to", {}).get("hash", "")).lower().strip()
                val = float(t.get("value", 0)) / 1e18

                # EXTENSIVE USD VALUE DISCOVERY
                val_usd = float(t.get("value_usd") or t.get("total", {}).get("value_usd") or t.get("total_usd") or 0.0)
                unit_p = val_usd / val if val > 0 else 0.0

                row = create_raw_row()
                row.update({
                    "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Native" if "method" in t else "Internal", "Method": t.get("method", "Internal"), "Account": addr_c, "From": f_r, "To": t_r, "From_Label": t.get("from", {}).get("name", ""), "To_Label": t.get("to", {}).get("name", ""), "Counterparty": t_r if f_r == addr_c else f_r, "Asset": native, "Amount": val if t_r == addr_c else -val,
                    "Valeur $": val_usd,
                    "USD prix asset reçu": unit_p if t_r == addr_c else 0.0,
                    "USD prix asset envoyé": unit_p if f_r == addr_c else 0.0,
                    "Fee_Asset": native, "Fee_Amount": (int(t.get("gas_used", 0)) * int(t.get("gas_price", 0))) / 1e18 if f_r == addr_c else 0.0,
                    "Source_Way": "Way_1", "Audit_Status": "RAW", "Source_Exchange_Rate": unit_p
                })
                all_txs.append(row)

            for t in bs_tok:
                dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                tok = t.get("token") or {}
                asset, dec = str(tok.get("symbol", "TOKEN")).upper().strip(), int(tok.get("decimals") or 18)
                total_obj = t.get("total", {})
                val = float(total_obj.get("value") or t.get("value", 0)) / (10**dec)

                # EXTENSIVE USD VALUE DISCOVERY FOR TOKENS
                rate = float(tok.get("exchange_rate") or 0.0)
                val_usd = float(total_obj.get("value_usd") or t.get("total_usd") or t.get("value_usd") or (val * rate if rate > 0 else 0.0))
                unit_p = val_usd / val if val > 0 else rate

                h_val = t.get("tx_hash") or t.get("txHash") or t.get("hash") or t.get("transaction_hash")
                tx_h = str(h_val).lower().strip() if (h_val and str(h_val).lower() != "none") else "none"
                f_r, t_r = str(t.get("from", {}).get("hash", "")).lower().strip(), str(t.get("to", {}).get("hash", "")).lower().strip()

                row = create_raw_row()
                row.update({
                    "Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": "Token", "Method": "", "Account": addr_c, "From": f_r, "To": t_r, "From_Label": t.get("from", {}).get("name", ""), "To_Label": t.get("to", {}).get("name", ""), "Counterparty": t_r if f_r == addr_c else f_r, "Asset": asset, "Amount": val if t_r == addr_c else -val,
                    "Valeur $": val_usd,
                    "USD prix asset reçu": unit_p if t_r == addr_c else 0.0,
                    "USD prix asset envoyé": unit_p if f_r == addr_c else 0.0,
                    "Source_Way": "Way_1", "Audit_Status": "RAW", "Source_Exchange_Rate": unit_p
                })
                all_txs.append(row)
            chains_status[chain]["bs"] = True; f1.caption(f"✅ Way_1 (BS) : {len(bs_nat)+len(bs_int)+len(bs_tok)} lignes")
        except: chains_status[chain]["bs"] = False; f1.error("❌ Way_1 : Échec")

        # 2. Etherscan REST V2 (Transactions)
        if v2_api_key:
            res_v2, stat_v2 = fetch_etherscan_v2_rest(cfg["eth_domain"], addr_c, v2_api_key, target_year, max_txs, native)
            chains_status[chain]["eth"] = stat_v2
            if res_v2:
                for t, label, dt in res_v2:
                    h_val = t.get("hash") or t.get("txHash") or t.get("tx_hash") or t.get("transactionHash")
                    tx_h = str(h_val).lower().strip() if (h_val and str(h_val).lower() != "none") else "none"
                    f_r, t_r = str(t.get("from") or "").lower().strip(), str(t.get("to") or "").lower().strip()
                    amt = float(t.get("value", 0)) / (10**int(t.get("tokenDecimal", 18) or 18))
                    asset_v2 = str(t.get("tokenSymbol") or native).upper().strip()

                    row = create_raw_row()
                    row.update({"Date": dt.isoformat(), "Chain": chain, "Tx_Hash": tx_h, "Type": label, "Method": t.get("functionName", ""), "Account": addr_c, "From": f_r, "To": t_r, "Counterparty": t_r if f_r == addr_c else f_r, "Asset": asset_v2, "Amount": amt if t_r == addr_c else -amt, "Fee_Asset": native if f_r == addr_c else "", "Fee_Amount": (int(t.get('gasUsed', 0)) * int(t.get('gasPrice', 0))) / 1e18 if f_r == addr_c else 0.0, "Source_Way": "Way_2", "Audit_Status": "RAW"})
                    all_txs.append(row)
                f2.caption(f"✅ Way_2 (V2 REST) : {len(res_v2)} lignes")
            else: f2.caption(f"ℹ️ Way_2 : {stat_v2}")

        # 3. Portfolio Collection (Blockscout + Etherscan fallback)
        try:
            # 3a. Native Balance (Blockscout)
            addr_data = call_api(f"{cfg['bs_v2']}/addresses/{addr_c}")
            if addr_data and "coin_balance" in addr_data:
                nat_bal = float(addr_data["coin_balance"]) / 1e18
                if nat_bal > 0:
                    row = create_raw_row()
                    row.update({"Date": datetime(target_year,12,31).isoformat(), "Chain": chain, "Tx_Hash": f"PORT-{addr_c}-{native}-{chain}", "Type": "Portfolio", "Method": "Snapshot", "Account": addr_c, "From": "Blockchain", "To": addr_c, "Counterparty": "Snapshot", "Asset": native, "Amount": nat_bal, "Valeur $": float(addr_data.get("exchange_rate", 0.0)) * nat_bal, "Source_Way": "Way_1", "Audit_Status": "RAW"})
                    all_port.append(row)

            # 3b. Token Balances (Blockscout)
            p_tokens = call_api(f"{cfg['bs_v2']}/addresses/{addr_c}/token-balances")
            if p_tokens and isinstance(p_tokens, list):
                for b in p_tokens:
                    tok = b.get("token") or {}
                    sym, dec = str(tok.get("symbol", "TOKEN")).upper().strip(), int(tok.get("decimals", 18) or 18)
                    qty = float(b.get("value", 0)) / (10**dec)
                    if qty > 0:
                        val_usd = float(b.get("value_usd") or 0.0)
                        row = create_raw_row()
                        row.update({"Date": datetime(target_year,12,31).isoformat(), "Chain": chain, "Tx_Hash": f"PORT-{addr_c}-{sym}-{chain}", "Type": "Portfolio", "Method": "Snapshot", "Account": addr_c, "From": "Blockchain", "To": addr_c, "Counterparty": "Snapshot", "Asset": sym, "Amount": qty, "Valeur $": val_usd, "Source_Way": "Way_1", "Audit_Status": "RAW"})
                        all_port.append(row)
        except: pass
        pbar.progress((idx + 1) / len(chains_to_scan))

    # 4. Consolidation & Final Registry
    df_m = pd.DataFrame(all_txs, columns=RAW_V4_COLUMNS)
    if not df_m.empty:
        df_m["Date"] = pd.to_datetime(df_m["Date"], utc=True, errors="coerce")
        df_m = df_m.dropna(subset=["Date", "Tx_Hash"])

        # --- ZÉRO SPAM : Filtre de récolte ---
        df_m = sl.apply_spam_filter(df_m, drop=False)

        df_m["_amt_round"] = pd.to_numeric(df_m["Amount"], errors="coerce").round(8)
        df_m["_occ"] = df_m.groupby(["Tx_Hash", "Asset", "Chain", "_amt_round", "From", "To"]).cumcount()
        def cons(g):
            w1, w2 = g[g["Source_Way"]=="Way_1"], g[g["Source_Way"]=="Way_2"]
            res = w1.iloc[0].copy() if not w1.empty else w2.iloc[0].copy()
            if not w1.empty and not w2.empty:
                r2 = w2.iloc[0]
                # Combine data: Fee and Method from Way_2, Valuations from Way_1
                res["Fee_Amount"], res["Method"], res["Source_Way"] = r2["Fee_Amount"], r2["Method"], "Way_1+2"
                # If Way_2 has higher fidelity on some valuations (usually not for USD prices on Blockscout), update them here
            return res
        df_f = df_m.groupby(["Tx_Hash", "Asset", "Chain", "_amt_round", "From", "To", "_occ"], as_index=False).apply(cons).reset_index(drop=True)
        # Ensure all columns are present after consolidation
        for col in RAW_V4_COLUMNS:
            if col not in df_f.columns: df_f[col] = ""
        df_f = df_f[RAW_V4_COLUMNS]

        # Filter Portfolio spams too
        df_port = pd.DataFrame(all_port, columns=RAW_V4_COLUMNS)
        df_port = sl.apply_spam_filter(df_port, drop=False)

        st.session_state.harvest_data[addr_c] = {"port": df_port, "tx": df_f.sort_values("Date", ascending=False), "status": chains_status}
    else:
        st.session_state.harvest_data[addr_c] = {"port": pd.DataFrame(all_port, columns=RAW_V4_COLUMNS), "tx": pd.DataFrame(columns=RAW_V4_COLUMNS), "status": chains_status}
        if not all_port:
            st.warning("⚠️ Aucune donnée récoltée pour cette configuration (Année/Chaînes/Adresse).")
    st.rerun()

# --- UI Tables ---
if st.session_state.harvest_data:
    for addr, data in st.session_state.harvest_data.items():
        with st.expander(f"👤 Compte : {sl.resolve_owner_display(addr)}", expanded=True):
            st.write("🚦 **API Status :**")
            cols = st.columns(len(data["status"]))
            for i, (c, s) in enumerate(data["status"].items()):
                bs_ico = "✅" if s["bs"] is True else "❌"
                eth_ico = "✅" if s["eth"] is True else "❌" if isinstance(s["eth"], str) else "ℹ️"
                cols[i].caption(f"**{c}**\nBS: {bs_ico}\nETH: {eth_ico}")
                if isinstance(s["eth"], str) and s["eth"] not in ["True", "empty", "pending"]: cols[i].error(f"Error: {s['eth']}")

            # UI display filtering (Show all but highlight spams? No, user wants spams GONE)
            # Actually, in Harvest Step, it's better to show them as marked Spam
            # to let user know they were caught. But for final display, we follow the directive.

            show_spams = st.checkbox("Voir les lignes marquées 'Spam'", value=False, key=f"show_spam_{addr}")

            def get_ui_df(df_base):
                if show_spams: return df_base
                return df_base[df_base["Audit_Status"] != "Spam"]

            st.markdown("#### 📦 Portfolio")
            st.dataframe(get_ui_df(data["port"]), width='stretch', key=f"p_{addr}")

            df_t = data["tx"]
            mask_tok = (df_t["Type"].str.contains("Token")) | (~df_t["Asset"].isin(["ETH", "POL", "BNB", "AVAX"]))

            st.markdown(f"#### 📝 Transactions (Natives) ({len(get_ui_df(df_t[~mask_tok]))})")
            st.dataframe(get_ui_df(df_t[~mask_tok]), width='stretch', key=f"t_{addr}")

            st.markdown(f"#### 🪙 Tokens ({len(get_ui_df(df_t[mask_tok]))})")
            st.dataframe(get_ui_df(df_t[mask_tok]), width='stretch', key=f"k_{addr}")

            if st.button(f"💾 Sanctuariser {addr[:10]}...", key=f"s_{addr}"):
                y_dir = os.path.join(EXPORT_BASE_DIR, str(target_year)); os.makedirs(y_dir, exist_ok=True)
                s_dir = os.path.join(y_dir, "sanctuary"); os.makedirs(s_dir, exist_ok=True)
                prefix = f"{addr}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                # Use utf-8-sig for Windows/Excel compatibility and ensuring $ signs and symbols are preserved
                # 1. Working copy (latest raw for other apps)
                if not data["port"].empty: data["port"].to_csv(os.path.join(y_dir, f"raw_portfolio_{prefix}.csv"), index=False, encoding="utf-8-sig")
                if not df_t.empty: df_t.to_csv(os.path.join(y_dir, f"raw_transactions_consolidated_{prefix}.csv"), index=False, encoding="utf-8-sig")

                # 2. SANCTUARY copy (never modified, permanent archive)
                if not data["port"].empty: data["port"].to_csv(os.path.join(s_dir, f"raw_portfolio_{prefix}.csv"), index=False, encoding="utf-8-sig")
                if not df_t.empty: df_t.to_csv(os.path.join(s_dir, f"raw_transactions_consolidated_{prefix}.csv"), index=False, encoding="utf-8-sig")

                st.success(f"Récolte sanctuarisée ({prefix})")

st.sidebar.caption("Harvest v7.8 - Full Set")
