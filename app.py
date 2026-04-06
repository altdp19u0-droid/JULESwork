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
from fpdf import FPDF

# --- Config & Initialization ---
st.set_page_config(page_title="Blockscout Annual Export Pro — Art. 150 VH bis", layout="wide")
st.title("🚜 Exporter Transactions & Fiscalité (Double Écriture & Art. 150 VH bis)")

CHAIN_APIS = {
    "Ethereum": {
        "v1": "https://blockscout.com/eth/mainnet/api/",
        "v2": "https://eth.blockscout.com/api/v2",
        "etherscan_host": "api.etherscan.io",
        "native": "ETH",
        "cg_platform": "ethereum"
    },
    "Arbitrum": {
        "v1": "https://blockscout.com/arb/mainnet/api/",
        "v2": "https://arbitrum.blockscout.com/api/v2",
        "etherscan_host": "api.arbiscan.io",
        "native": "ETH",
        "cg_platform": "arbitrum-one"
    },
    "Base": {
        "v1": "https://base.blockscout.com/api/",
        "v2": "https://base.blockscout.com/api/v2",
        "etherscan_host": "api.basescan.org",
        "native": "ETH",
        "cg_platform": "base"
    },
    "Polygon": {
        "v1": "https://polygon.blockscout.com/api/",
        "v2": "https://polygon.blockscout.com/api/v2",
        "etherscan_host": "api.polygonscan.com",
        "native": "POL",
        "cg_platform": "polygon-pos"
    },
    "Optimism": {
        "v1": "https://optimism.blockscout.com/api/",
        "v2": "https://optimism.blockscout.com/api/v2",
        "etherscan_host": "api-optimistic.etherscan.io",
        "native": "ETH",
        "cg_platform": "optimistic-ethereum"
    }
}

DEFAULT_PAGE_SIZE = 100
EXPORT_BASE_DIR = "exports"

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    address = st.text_input("Adresse Blockchain (0x...)", "")
    chains = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=list(CHAIN_APIS.keys()))
    etherscan_key = st.text_input("Clé API Etherscan V2 (Optionnel pour ABI)", type="password")

    st.divider()
    use_coingecko = st.checkbox("Activer CoinGecko (Prix Historiques)", value=True)
    use_historical_prices = st.checkbox("Prix au 31/12 (Snapshot Portfolio)", value=True)
    start_year = st.number_input("Année de départ", min_value=2015, max_value=2030, value=2024)
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=20000, value=1000, step=100)

    st.divider()
    prix_acq_total = st.number_input("Prix d'acquisition total (EUR)", value=0.0, step=100.0)
    montant_cession = st.number_input("Montant de la cession fiat (EUR)", value=0.0, step=100.0)

fetch_button = st.button("🚀 Lancer Récolte & Générer Exports", use_container_width=True)

# --- Clients ---
cg = CoinGeckoAPI() if use_coingecko else None
w3 = Web3()

# --- Helpers ---
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def save_csv_local(df, path):
    ensure_dir(os.path.dirname(path))
    df.to_csv(path, index=False, encoding="utf-8")

@st.cache_data(ttl=86400)
def call_api(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Erreur API ({url}): {e}")
        return None

def fetch_paginated_v1(api_base, addr, action, max_txs):
    items = []
    page = 1
    while len(items) < max_txs:
        params = {"module":"account","action":action,"address":addr,"page":page,"offset":DEFAULT_PAGE_SIZE,"sort":"asc"}
        j = call_api(api_base, params)
        if not j or not j.get("result"): break
        res = j["result"]
        if not isinstance(res, list): break
        items.extend(res)
        if len(res) < DEFAULT_PAGE_SIZE: break
        page += 1
        time.sleep(0.2)
    return items[:max_txs]

def fetch_blockscout_v2(api_v2, addr, max_txs):
    txs = []
    url = f"{api_v2}/addresses/{addr}/transactions"
    params = {"filter": "to | from"}
    for _ in range(20):
        data = call_api(url, params)
        if not data or "items" not in data: break
        txs.extend(data["items"])
        if len(txs) >= max_txs or "next_page_params" not in data or not data["next_page_params"]: break
        params.update(data["next_page_params"])
        time.sleep(0.2)
    return txs[:max_txs]

# --- Decoding logic ---
def fetch_contract_abi(contract, chain_label, api_key):
    host = CHAIN_APIS.get(chain_label, {}).get("etherscan_host")
    if not host or not api_key: return None
    url = f"https://{host}/api"
    params = {"module":"contract","action":"getabi","address":contract,"apikey":api_key}
    j = call_api(url, params)
    if j and j.get("status") == "1" and j.get("result"):
        try: return json.loads(j["result"])
        except: return None
    return None

def decode_input_with_abi(input_data, abi):
    if not input_data or input_data == "0x" or not abi: return ""
    try:
        method_id = input_data[:10]
        for entry in abi:
            if entry.get("type") != "function": continue
            sig = f"{entry['name']}({','.join([inp['type'] for inp in entry.get('inputs',[])])})"
            mid = w3.keccak(text=sig).hex()[:10]
            if mid == method_id:
                types = [inp['type'] for inp in entry.get('inputs',[])]
                data_hex = input_data[10:]
                if not data_hex: return f"{entry['name']}()"
                try:
                    decoded_params = decode(types, bytes.fromhex(data_hex))
                    return f"{entry['name']}({decoded_params})"
                except: return f"{entry['name']}()"
        return method_id
    except: return input_data[:10]

def decode_method_4byte(input_data):
    if not input_data or input_data == "0x": return "Transfer"
    sig = input_data[:10]
    try:
        r = requests.get(f"https://www.4byte.directory/api/v1/signatures/?hex_signature={sig}", timeout=5)
        if r.status_code == 200:
            res = r.json().get("results", [])
            if res: return res[0].get("text_signature")
    except: pass
    return sig

# --- Prices ---
@st.cache_data(ttl=86400)
def coingecko_price_on_date_coin(coin_id, date_obj):
    if not cg: return None
    try:
        time.sleep(1.2) # Rate limit
        d = date_obj.strftime("%d-%m-%Y")
        res = cg.get_coin_history_by_id(id=coin_id, date=d)
        return res.get("market_data", {}).get("current_price", {}).get("eur")
    except: return None

@st.cache_data(ttl=86400)
def coingecko_get_coin_id_by_contract(platform_id, contract_address):
    url = f"https://api.coingecko.com/api/v3/coins/{platform_id}/contract/{contract_address}"
    j = call_api(url)
    return j.get("id") if j else None

# --- Main Logic ---
if fetch_button:
    if not address or not w3.is_address(address):
        st.error("❌ Adresse invalide.")
    else:
        addr_c = w3.to_checksum_address(address)
        st.info(f"🔍 Analyse : {addr_c}")

        all_txs_raw = []
        all_tokens_raw = []
        abi_cache = {}

        # 1. Extraction des données
        progress = st.progress(0)
        for idx, chain in enumerate(chains):
            st.write(f"🌐 Récolte sur **{chain}**...")
            cfg = CHAIN_APIS[chain]

            # Natives (Prefer V2)
            txs_v2 = fetch_blockscout_v2(cfg["v2"], addr_c, max_txs)
            if txs_v2:
                for t in txs_v2:
                    t["_chain"] = chain
                    # Normalisation minimale pour la suite
                    t["timeStamp"] = int(datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp())
                    t["from"] = t.get("from", {}).get("hash", "")
                    t["to"] = t.get("to", {}).get("hash", "")
                    t["value_eth"] = float(t.get("value", 0)) / 1e18
                    t["fee_eth"] = (int(t.get("gas_used", 0)) * int(t.get("gas_price", 0))) / 1e18
                all_txs_raw.extend(txs_v2)
            else:
                txs_v1 = fetch_paginated_v1(cfg["v1"], addr_c, "txlist", max_txs)
                for t in txs_v1:
                    t["_chain"] = chain
                    t["timeStamp"] = int(t.get("timeStamp", 0))
                    t["value_eth"] = float(t.get("value", 0)) / 1e18
                    t["fee_eth"] = (int(t.get("gasUsed", 0)) * int(t.get("gasPrice", 0))) / 1e18
                all_txs_raw.extend(txs_v1)

            # Tokens
            toks = fetch_paginated_v1(cfg["v1"], addr_c, "tokentx", max_txs)
            for t in toks:
                t["_chain"] = chain
                t["timeStamp"] = int(t.get("timeStamp", 0))
                dec = int(t.get("tokenDecimal") or 18)
                t["quantity"] = float(t.get("value", 0)) / (10**dec)
            all_tokens_raw.extend(toks)

            progress.progress((idx + 1) / len(chains))

        if not all_txs_raw and not all_tokens_raw:
            st.warning("⚠️ Aucune donnée trouvée.")
        else:
            df_tx = pd.DataFrame(all_txs_raw)
            df_tk = pd.DataFrame(all_tokens_raw)

            # Processing Datetimes & Decodings
            if not df_tx.empty:
                df_tx["datetime"] = pd.to_datetime(df_tx["timeStamp"], unit="s", utc=True)
                df_tx["year"] = df_tx["datetime"].dt.year

                st.write("🔧 Décodage des méthodes (Etherscan V2 / 4Byte)...")
                methods = []
                for _, r in df_tx.iterrows():
                    inp = r.get("input", "0x")
                    to_a = (r.get("to") or "").lower()
                    decoded = ""
                    if etherscan_key and to_a:
                        ckey = f"{to_a}::{r['_chain']}"
                        if ckey not in abi_cache:
                            abi_cache[ckey] = fetch_contract_abi(to_a, r["_chain"], etherscan_key)
                        abi = abi_cache.get(ckey)
                        if abi: decoded = decode_input_with_abi(inp, abi)
                    if not decoded: decoded = decode_method_4byte(inp)
                    methods.append(decoded)
                df_tx["method"] = methods

            if not df_tk.empty:
                df_tk["datetime"] = pd.to_datetime(df_tk["timeStamp"], unit="s", utc=True)
                df_tk["year"] = df_tk["datetime"].dt.year

            # --- Accounting Engine (Double Entry) & Portfolio ---
            years = sorted(set(
                (df_tx["year"].unique().tolist() if not df_tx.empty else []) +
                (df_tk["year"].unique().tolist() if not df_tk.empty else [])
            ))
            years = [y for y in years if y >= start_year]

            portfolio_balances = {} # key -> qty
            vgp_total = 0.0

            for y in years:
                st.header(f"📅 Année {y}")
                txs_y = df_tx[df_tx["year"] == y] if not df_tx.empty else pd.DataFrame()
                tok_y = df_tk[df_tk["year"] == y] if not df_tk.empty else pd.DataFrame()

                rows_de = []

                # Process Tokens
                for _, r in tok_y.iterrows():
                    symbol = r.get("tokenSymbol", "TOKEN")
                    qty = r.get("quantity", 0)
                    direction = "IN" if r.get("to", "").lower() == addr_c.lower() else "OUT"
                    key = f"TOKEN::{symbol}::{r.get('contractAddress', '').lower()}::{r['_chain']}"

                    portfolio_balances[key] = portfolio_balances.get(key, 0.0) + (qty if direction == "IN" else -qty)

                    rows_de.append({
                        "Date": r["datetime"], "Chain": r["_chain"], "Hash": r.get("hash") or r.get("transactionHash"),
                        "Type": "Token Transfer", "Asset": symbol, "Amount": qty if direction == "IN" else -qty,
                        "Counterparty": r.get("from") if direction == "IN" else r.get("to"), "Method": "Transfer"
                    })

                # Process Native
                for _, r in txs_y.iterrows():
                    val = r.get("value_eth", 0.0)
                    fee = r.get("fee_eth", 0.0)
                    direction = "OUT" if r.get("from", "").lower() == addr_c.lower() else "IN"
                    chain = r["_chain"]
                    native = CHAIN_APIS[chain]["native"]
                    key = f"NATIVE::{native}::::{chain}"

                    portfolio_balances[key] = portfolio_balances.get(key, 0.0) + (val if direction == "IN" else -val)
                    if direction == "OUT":
                        portfolio_balances[key] -= fee # Fees on native asset

                    rows_de.append({
                        "Date": r["datetime"], "Chain": chain, "Hash": r.get("hash"),
                        "Type": "Native Movement", "Asset": native, "Amount": val if direction == "IN" else -val,
                        "Counterparty": r.get("to") if direction == "OUT" else r.get("from"), "Method": r.get("method")
                    })
                    if fee > 0 and direction == "OUT":
                        rows_de.append({
                            "Date": r["datetime"], "Chain": chain, "Hash": r.get("hash"),
                            "Type": "Gas Fee", "Asset": native, "Amount": -fee,
                            "Counterparty": "Network", "Method": r.get("method")
                        })

                df_de_y = pd.DataFrame(rows_de).sort_values("Date")
                st.subheader(f"Journal Double Écriture {y}")
                st.dataframe(df_de_y, use_container_width=True)

                # Snapshot EOY & Valuation
                st.subheader(f"Portfolio au 31/12/{y}")
                snapshot_rows = []
                for k, qty in portfolio_balances.items():
                    if abs(qty) < 1e-8: continue
                    parts = k.split("::")
                    asset, contract, chain = parts[1], parts[2], parts[3]

                    price = 0.0
                    if use_coingecko:
                        coin_id = ""
                        if parts[0] == "NATIVE":
                            mapping = {"ETH": "ethereum", "POL": "polygon-ecosystem-token", "BNB": "binancecoin"}
                            coin_id = mapping.get(asset, "ethereum")
                        else:
                            # Token identification by contract
                            platform = CHAIN_APIS.get(chain, {}).get("cg_platform", "ethereum")
                            coin_id = coingecko_get_coin_id_by_contract(platform, contract)

                        if coin_id:
                            price = coingecko_price_on_date_coin(coin_id, datetime(y, 12, 31).date() if use_historical_prices else datetime.now().date())

                    if not price and asset.upper() in ["USDC", "USDT", "DAI"]: price = 0.95
                    if not price and asset.upper() in ["EURA", "AGEUR"]: price = 1.0

                    val_eur = qty * (price or 0.0)
                    if y == years[-1]: vgp_total += val_eur

                    snapshot_rows.append({"Asset": asset, "Chain": chain, "Quantity": qty, "Price EUR": price, "Value EUR": val_eur})

                df_snap = pd.DataFrame(snapshot_rows)
                st.table(df_snap)

                # Exports
                out_dir = os.path.join(EXPORT_BASE_DIR, str(y))
                save_csv_local(df_de_y, os.path.join(out_dir, f"double_entry_{y}.csv"))
                save_csv_local(df_snap, os.path.join(out_dir, f"portfolio_snapshot_{y}.csv"))

            # --- Fiscalité Section ---
            st.divider()
            st.header("⚖️ Fiscalité France (Art. 150 VH bis)")
            st.metric("Valeur Globale Portefeuille (VGP) Actuelle", f"{vgp_total:,.2f} €")

            if montant_cession > 0:
                if vgp_total > 0:
                    ratio = montant_cession / vgp_total
                    quote_acq = prix_acq_total * ratio
                    plus_value = montant_cession - quote_acq
                    impot = max(0.0, plus_value * 0.30) if montant_cession > 305 else 0.0

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Plus-Value Brute", f"{plus_value:,.2f} €")
                    c2.metric("Quote-part Acquisition", f"{quote_acq:,.2f} €")
                    c3.metric("Impôt estimé (30%)", f"{impot:,.2f} €")

                    if st.button("📄 Télécharger Rapport PDF Fiscal"):
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.set_font("Arial", size=12)
                        pdf.cell(0, 10, "Rapport Fiscal Crypto - Art. 150 VH bis", ln=True, align='C')
                        pdf.ln(10)
                        pdf.cell(0, 10, f"Adresse : {addr_c}", ln=True)
                        pdf.cell(0, 10, f"VGP Totale : {vgp_total:,.2f} EUR", ln=True)
                        pdf.cell(0, 10, f"Prix d'acquisition total : {prix_acq_total:,.2f} EUR", ln=True)
                        pdf.cell(0, 10, f"Montant de la cession : {montant_cession:,.2f} EUR", ln=True)
                        pdf.cell(0, 10, f"Plus-Value : {plus_value:,.2f} EUR", ln=True)
                        pdf.cell(0, 10, f"Impot estimé : {impot:,.2f} EUR", ln=True)

                        pdf_path = os.path.join(EXPORT_BASE_DIR, "rapport_fiscal.pdf")
                        pdf.output(pdf_path)
                        with open(pdf_path, "rb") as f:
                            st.download_button("Cliquez pour télécharger le PDF", f, "rapport_fiscal.pdf")
                else:
                    st.error("VGP nulle, calcul impossible.")

            st.success(f"✅ Exports terminés. Les fichiers sont disponibles dans le dossier ./{EXPORT_BASE_DIR}/")

st.sidebar.divider()
st.sidebar.caption("Blockscout Annual Export Pro v5.0")
