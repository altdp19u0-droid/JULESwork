# app.py
import os
import time
import json
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil import tz
from web3 import Web3
from pycoingecko import CoinGeckoAPI
from eth_abi import decode

st.set_page_config(page_title="Blockscout Annual Export — Cumulatif & Double Écriture", layout="wide")
st.title("Exporter transactions blockchain — Annuel cumulatif & double écriture")

# --- Config ---
CHAIN_APIS = {
    "Ethereum": "https://blockscout.com/eth/mainnet/api/",
    "Arbitrum": "https://blockscout.com/arb/mainnet/api/",
    "Base": "https://blockscout.com/base/mainnet/api/",
}
DEFAULT_PAGE_SIZE = 100
EXPORT_BASE_DIR = "exports"

# --- Inputs ---
address = st.text_input("Adresse (0x...)", "")
chains = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=list(CHAIN_APIS.keys()))
etherscan_key = st.text_input("Clé API Etherscan V2 (optionnel pour décodage avancé)", type="password")
use_coingecko = st.checkbox("Récupérer prix via CoinGecko (spot) et prix historiques par date (lent)", value=True)
use_historical_prices = st.checkbox("Utiliser prix historiques par date (CoinGecko)", value=True)
start_year = st.number_input("Année de départ (soldes initiaux 0 au 01/01)", min_value=1970, max_value=2100, value=2025)
max_txs = st.number_input("Nombre max de tx à récupérer par chaîne", min_value=10, max_value=20000, value=2000, step=10)
fetch_button = st.button("Récupérer et générer exports")

# --- Init clients ---
cg = CoinGeckoAPI() if use_coingecko else None
w3 = Web3()

# --- Helpers ---
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def save_csv_local(df, path):
    ensure_dir(os.path.dirname(path))
    df.to_csv(path, index=False, encoding="utf-8")

def call_blockscout(api_base, params):
    try:
        r = requests.get(api_base, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Erreur requête Blockscout: {e}")
        return None

def fetch_paginated(api_base, addr, action, max_txs, page_size=DEFAULT_PAGE_SIZE, sort="asc"):
    items = []
    page = 1
    while len(items) < max_txs:
        params = {"module":"account","action":action,"address":addr,"page":page,"offset":page_size,"sort":sort}
        j = call_blockscout(api_base, params)
        if not j:
            break
        res = j.get("result", [])
        if not res:
            break
        items.extend(res)
        if len(res) < page_size:
            break
        page += 1
        time.sleep(0.2)
    return items[:max_txs]

def human_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=tz.tzutc())
    except:
        return None

def detect_chains_with_activity(address, chains):
    active = []
    for c in chains:
        api = CHAIN_APIS[c]
        j = call_blockscout(api, {"module":"account","action":"txlist","address":address,"page":1,"offset":1,"sort":"desc"})
        if j and j.get("result"):
            active.append(c)
    return active

def decode_method_4byte(input_data):
    if not input_data or input_data == "0x":
        return ""
    sig = input_data[:10]
    try:
        r = requests.get(f"https://www.4byte.directory/api/v1/signatures/?hex_signature={sig}", timeout=10)
        r.raise_for_status()
        j = r.json()
        results = j.get("results", [])
        if results:
            return results[0].get("text_signature","")
    except:
        pass
    return sig

# Etherscan ABI fetch & decode input (basic)
def fetch_contract_abi_etherscan(contract, chain_label, api_key):
    # map chain_label to etherscan-ish API base
    api_map = {
        "Ethereum": "https://api.etherscan.io/api",
        "Arbitrum": "https://api.arbiscan.io/api",
        "Base": "https://api.base.blockscout.io/api"  # placeholder; Base/Etherscan may differ
    }
    base = api_map.get(chain_label)
    if not base:
        return None
    params = {"module":"contract","action":"getabi","address":contract,"apikey":api_key}
    try:
        r = requests.get(base, params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("status") == "1" and j.get("result"):
            return json.loads(j["result"])
    except:
        pass
    return None

def decode_input_with_abi(input_data, abi):
    if not input_data or input_data == "0x" or not abi:
        return ""
    try:
        # Simple approach: match method id to ABI entry
        method_id = input_data[:10]
        for entry in abi:
            if entry.get("type") != "function":
                continue
            sig = f"{entry['name']}({','.join([inp['type'] for inp in entry.get('inputs',[])])})"
            mid = Web3.keccak(text=sig).hex()[:10]
            if mid == method_id:
                # decode params
                types = [inp['type'] for inp in entry.get('inputs',[])]
                data_hex = input_data[10:]
                if data_hex.startswith('0x'):
                    data_hex = data_hex[2:]
                if not data_hex:
                    return entry['name'] + "()"
                try:
                    decoded = decode(types, bytes.fromhex(data_hex))
                    return f"{entry['name']}({decoded})"
                except:
                    return entry['name'] + "()"
        return method_id
    except:
        return input_data[:10]

def calc_fee_eth(tx):
    try:
        gas_used = int(tx.get("gasUsed") or tx.get("gas") or 0)
        gas_price = int(tx.get("gasPrice") or 0)
        fee_wei = gas_used * gas_price
        return w3.fromWei(fee_wei, "ether")
    except:
        return None

# CoinGecko helpers: get price at date (dd-mm-yyyy) for eth or token contract
def coingecko_price_on_date_token(contract_address, date_str, platform_id="ethereum"):
    try:
        res = cg.get_token_market_chart_range_by_id(id=platform_id, contract_address=contract_address, vs_currency="usd", from_timestamp=0, to_timestamp=int(time.time()))
        # fallback: CoinGecko doesn't provide a direct price-by-date for tokens via contract in pycoingecko; we will instead use /coins/{id}/history which requires coin id, not contract
    except:
        return None

def coingecko_price_on_date_coin(coin_id, date):
    # date: datetime.date
    try:
        d = date.strftime("%d-%m-%Y")
        res = cg.get_coin_history_by_id(id=coin_id, date=d)
        market = res.get("market_data", {})
        if market and market.get("current_price"):
            return market["current_price"].get("usd")
    except:
        pass
    return None

# --- Main processing ---
if fetch_button:
    if not address or not Web3.isAddress(address):
        st.error("Adresse invalide.")
    else:
        address = Web3.toChecksumAddress(address)
        st.info("Détection des chaînes avec activité...")
        active_chains = detect_chains_with_activity(address, chains)
        st.write("Chaînes actives détectées:", active_chains)

        all_txs = []
        all_token_transfers = []
        # Track ABI cache to minimize calls
        abi_cache = {}

        for chain in active_chains:
            api_base = CHAIN_APIS[chain]
            st.write(f"Récupération txs pour {chain}...")
            txs = fetch_paginated(api_base, address, "txlist", max_txs)
            st.write(f"{len(txs)} transactions récupérées sur {chain}")
            for tx in txs:
                tx["_chain"] = chain
            all_txs.extend(txs)

            st.write(f"Récupération token transfers pour {chain}...")
            toks = fetch_paginated(api_base, address, "tokentx", max_txs)
            st.write(f"{len(toks)} transferts tokens récupérés sur {chain}")
            for t in toks:
                t["_chain"] = chain
            all_token_transfers.extend(toks)

        if not all_txs and not all_token_transfers:
            st.warning("Aucune donnée récupérée.")
        else:
            df_tx = pd.json_normalize(all_txs) if all_txs else pd.DataFrame()
            df_tk = pd.json_normalize(all_token_transfers) if all_token_transfers else pd.DataFrame()

            if not df_tx.empty:
                for col in ["timeStamp","blockNumber","gas","gasPrice","nonce","gasUsed"]:
                    if col in df_tx.columns:
                        df_tx[col] = pd.to_numeric(df_tx[col], errors="coerce")
                df_tx["datetime"] = pd.to_datetime(df_tx["timeStamp"], unit="s", utc=True, errors="coerce")
                df_tx["year"] = df_tx["datetime"].dt.year
                df_tx["fee_eth"] = df_tx.apply(lambda r: calc_fee_eth(r), axis=1)
                df_tx["value_eth"] = pd.to_numeric(df_tx.get("value",0), errors="coerce")/1e18
                # Advanced decode using Etherscan ABI if key provided
                method_list = []
                for _, r in df_tx.iterrows():
                    input_data = r.get("input","")
                    contract = (r.get("to") or "").lower()
                    decoded = ""
                    if etherscan_key and contract:
                        cache_key = f"{contract}::{r['_chain']}"
                        if cache_key not in abi_cache:
                            abi = fetch_contract_abi_etherscan(contract, r["_chain"], etherscan_key)
                            abi_cache[cache_key] = abi
                            time.sleep(0.2)
                        abi = abi_cache.get(cache_key)
                        if abi:
                            decoded = decode_input_with_abi(input_data, abi)
                    if not decoded:
                        decoded = decode_method_4byte(input_data)
                    method_list.append(decoded)
                df_tx["method"] = method_list

            if not df_tk.empty:
                for col in ["timeStamp","value","tokenDecimal","blockNumber"]:
                    if col in df_tk.columns:
                        df_tk[col] = pd.to_numeric(df_tk[col], errors="coerce")
                df_tk["datetime"] = pd.to_datetime(df_tk["timeStamp"], unit="s", utc=True, errors="coerce")
                df_tk["year"] = df_tk["datetime"].dt.year
                df_tk["quantity"] = df_tk.apply(lambda r: (float(r.get("value") or 0) / (10**int(r.get("tokenDecimal") or 0))) if r.get("tokenDecimal") is not None else 0.0, axis=1)

            # Years set
            years = sorted(set(
                list(df_tx["year"].dropna().astype(int).unique() if not df_tx.empty else []) +
                list(df_tk["year"].dropna().astype(int).unique() if not df_tk.empty else []) +
                [start_year]
            ))
            years = [y for y in years if y >= start_year]
            years = sorted(years)

            portfolio_balances = {}
            yearly_exports = {}

            for y in years:
                txs_y = df_tx[df_tx["year"] == y] if not df_tx.empty else pd.DataFrame()
                tk_y = df_tk[df_tk["year"] == y] if not df_tk.empty else pd.DataFrame()

                txs_export_rows = []

                # Process token transfers
                if not tk_y.empty:
                    for _, r in tk_y.iterrows():
                        direction = "in" if r.get("to","").lower() == address.lower() else "out"
                        asset = r.get("tokenSymbol") or r.get("tokenName") or (r.get("contractAddress") or "").lower()
                        qty = r.get("quantity") or 0
                        key = f"TOKEN::{asset}::{r.get('contractAddress','')}"
                        portfolio_balances[key] = portfolio_balances.get(key, 0.0) + (qty if direction=="in" else -qty)
                        txs_export_rows.append({
                            "year": y,
                            "chain": r.get("_chain"),
                            "tx_hash": r.get("transactionHash"),
                            "type": "token_transfer",
                            "token": asset,
                            "token_id": r.get("tokenID",""),
                            "from": r.get("from"),
                            "to": r.get("to"),
                            "quantity": qty,
                            "fee_eth": None,
                            "method": ""
                        })

                # Process native txs
                if not txs_y.empty:
                    for _, r in txs_y.iterrows():
                        val_eth = float(r.get("value_eth") or 0.0)
                        fee_eth = float(r.get("fee_eth") or 0.0) if r.get("fee_eth") is not None else None
                        from_a = r.get("from")
                        to_a = r.get("to")
                        txhash = r.get("hash")
                        chain = r.get("_chain")
                        method = r.get("method","")
                        direction = None
                        if from_a and from_a.lower() == address.lower():
                            direction = "out"
                        elif to_a and to_a.lower() == address.lower():
                            direction = "in"
                        eth_key = f"NATIVE::ETH::{chain}"
                        if direction == "in":
                            portfolio_balances[eth_key] = portfolio_balances.get(eth_key, 0.0) + val_eth
                        elif direction == "out":
                            portfolio_balances[eth_key] = portfolio_balances.get(eth_key, 0.0) - val_eth
                        fee_recorded = None
                        if fee_eth and direction == "out":
                            portfolio_balances[eth_key] = portfolio_balances.get(eth_key, 0.0) - fee_eth
                            fee_recorded = fee_eth
                        txs_export_rows.append({
                            "year": y,
                            "chain": chain,
                            "tx_hash": txhash,
                            "type": "native_tx",
                            "method": method,
                            "block": r.get("blockNumber"),
                            "from": from_a,
                            "to": to_a,
                            "value_eth": val_eth,
                            "fee_eth": fee_recorded
                        })

                # Portfolio snapshot and valuation (historical prices if requested)
                portfolio_rows = []
                for k, qty in portfolio_balances.items():
                    parts = k.split("::")
                    if parts[0] == "TOKEN":
                        asset = parts[1]
                        contract = parts[2]
                        price = None
                        usd_value = None
                        if cg and use_historical_prices:
                            # attempt spot or historical at 31/12 of year
                            try:
                                date_for_price = datetime(y,12,31).date()
                                # CoinGecko requires coin id; token-by-contract historical is complex. Try spot fallback:
                                # Attempt to find coin id by contract via /coins/ethereum/contract/{contract}
                                url = f"https://api.coingecko.com/api/v3/coins/ethereum/contract/{contract}"
                                pr = requests.get(url, timeout=10)
                                if pr.status_code == 200:
                                    cid = pr.json().get("id")
                                    if cid:
                                        price = coingecko_price_on_date_coin(cid, date_for_price)
                            except:
                                price = None
                        elif cg:
                            # spot price via contract
                            try:
                                url = f"https://api.coingecko.com/api/v3/simple/token_price/ethereum?contract_addresses={contract}&vs_currencies=usd"
                                r = requests.get(url, timeout=10).json()
                                p = r.get(contract.lower(), {}).get("usd")
                                if p:
                                    price = p
                            except:
                                pass
                        usd_value = price*qty if price else None
                        portfolio_rows.append({
                            "year": y,
                            "chain": "",
                            "asset_type": "token",
                            "asset": asset,
                            "contract": contract,
                            "quantity": qty,
                            "price_usd": price,
                            "value_usd": usd_value
                        })
                    else:
                        asset = parts[1]
                        chain = parts[2] if len(parts)>2 else ""
                        price = None
                        usd_value = None
                        if cg:
                            try:
                                # ETH price historical
                                if use_historical_prices:
                                    price = coingecko_price_on_date_coin("ethereum", datetime(y,12,31).date())
                                else:
                                    p = cg.get_price(ids="ethereum", vs_currencies="usd")
                                    price = p.get("ethereum",{}).get("usd")
                            except:
                                pass
                        usd_value = price*qty if price else None
                        portfolio_rows.append({
                            "year": y,
                            "chain": chain,
                            "asset_type": "native",
                            "asset": asset,
                            "contract": "",
                            "quantity": qty,
                            "price_usd": price,
                            "value_usd": usd_value
                        })

                # Prepare dataframes and save locally + provide downloads
                txs_df_year = pd.DataFrame(txs_export_rows)
                portfolio_df_year = pd.DataFrame(portfolio_rows)
                token_raw_df = tk_y.copy() if not tk_y.empty else pd.DataFrame()
                txs_raw_selected = pd.DataFrame()
                if not df_tx.empty:
                    txs_raw_selected = txs_y[[
                        "hash","datetime","blockNumber","from","to","value_eth","fee_eth","_chain","method"
                    ]].rename(columns={"hash":"tx_hash","_chain":"chain"})

                yearly_exports[y] = {
                    "transactions_double_entry": txs_df_year,
                    "transactions_raw": txs_raw_selected,
                    "token_transfers_raw": token_raw_df,
                    "portfolio_snapshot_end_of_year": portfolio_df_year,
                    "balances_carry_forward": portfolio_balances.copy()
                }

                # Local save
                out_dir = os.path.join(EXPORT_BASE_DIR, str(y))
                ensure_dir(out_dir)
                if not txs_df_year.empty:
                    save_csv_local(txs_df_year, os.path.join(out_dir, f"transactions_double_entry_{y}.csv"))
                if not txs_raw_selected.empty:
                    save_csv_local(txs_raw_selected, os.path.join(out_dir, f"transactions_raw_{y}.csv"))
                if not token_raw_df.empty:
                    save_csv_local(token_raw_df, os.path.join(out_dir, f"token_transfers_{y}.csv"))
                if not portfolio_df_year.empty:
                    save_csv_local(portfolio_df_year, os.path.join(out_dir, f"portfolio_eoy_{y}.csv"))

                st.write(f"Année {y} — locaux sauvegardés dans {out_dir}")

            # UI: provide downloads and show small previews
            for y, data in yearly_exports.items():
                st.header(f"Export année {y}")
                df_de = data["transactions_double_entry"]
                if not df_de.empty:
                    st.download_button(f"Télécharger Transactions (Double Écriture) {y}", df_de.to_csv(index=False).encode("utf-8"), file_name=f"transactions_double_entry_{y}.csv", mime="text/csv")
                    st.dataframe(df_de.head(50))
                else:
                    st.write("Aucune transaction double-écriture pour cette année.")

                df_raw_tx = data["transactions_raw"]
                if not df_raw_tx.empty:
                    st.download_button(f"Télécharger Transactions raw {y}", df_raw_tx.to_csv(index=False).encode("utf-8"), file_name=f"transactions_raw_{y}.csv", mime="text/csv")

                df_tok = data["token_transfers_raw"]
                if not df_tok.empty:
                    st.download_button(f"Télécharger TokenTransfers raw {y}", df_tok.to_csv(index=False).encode("utf-8"), file_name=f"token_transfers_{y}.csv", mime="text/csv")
                    st.dataframe(df_tok.head(50))

                df_port = data["portfolio_snapshot_end_of_year"]
                if not df_port.empty:
                    st.download_button(f"Télécharger Portfolio EoY {y}", df_port.to_csv(index=False).encode("utf-8"), file_name=f"portfolio_eoy_{y}.csv", mime="text/csv")
                    st.dataframe(df_port.head(50))

            st.success(f"Exports générés et sauvegardés localement sous ./{EXPORT_BASE_DIR}/<année>/")
