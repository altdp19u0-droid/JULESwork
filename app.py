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

# --- Configuration & Initialization ---
st.set_page_config(page_title="Jules Crypto Harvest Pro V6 — Step-by-Step", layout="wide")
st.title("🚜 Récolte & Fiscalité Blockchain (Art. 150 VH bis)")

CHAIN_APIS = {
    "Ethereum": {"v1": "https://blockscout.com/eth/mainnet/api/", "v2": "https://eth.blockscout.com/api/v2", "etherscan_host": "api.etherscan.io", "native": "ETH", "cg_platform": "ethereum"},
    "Arbitrum": {"v1": "https://blockscout.com/arb/mainnet/api/", "v2": "https://arbitrum.blockscout.com/api/v2", "etherscan_host": "api.arbiscan.io", "native": "ETH", "cg_platform": "arbitrum-one"},
    "Base": {"v1": "https://base.blockscout.com/api/", "v2": "https://base.blockscout.com/api/v2", "etherscan_host": "api.basescan.org", "native": "ETH", "cg_platform": "base"},
    "Polygon": {"v1": "https://polygon.blockscout.com/api/", "v2": "https://polygon.blockscout.com/api/v2", "etherscan_host": "api.polygonscan.com", "native": "POL", "cg_platform": "polygon-pos"},
    "Optimism": {"v1": "https://optimism.blockscout.com/api/", "v2": "https://optimism.blockscout.com/api/v2", "etherscan_host": "api-optimistic.etherscan.io", "native": "ETH", "cg_platform": "optimistic-ethereum"}
}

if "raw_data" not in st.session_state:
    st.session_state.raw_data = pd.DataFrame()
if "valued_data" not in st.session_state:
    st.session_state.valued_data = pd.DataFrame()
if "portfolio_balances" not in st.session_state:
    st.session_state.portfolio_balances = {}

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    address = st.text_input("Adresse Blockchain (0x...)", "")
    chains = st.multiselect("Chaînes à sonder", list(CHAIN_APIS.keys()), default=list(CHAIN_APIS.keys()))
    etherscan_key = st.text_input("Clé API Etherscan V2 (Optionnel pour ABI)", type="password")

    st.divider()
    target_year = st.number_input("Année à traiter", min_value=2015, max_value=2030, value=2024)
    max_txs = st.number_input("Max transactions par chaîne", min_value=10, max_value=20000, value=1000, step=100)

    st.divider()
    st.subheader("💰 Fiscalité Art. 150 VH bis")
    prix_acq_total = st.number_input("Prix d'acquisition total (EUR)", value=0.0, step=100.0)
    montant_cession = st.number_input("Montant de la cession fiat (EUR)", value=0.0, step=100.0)

    st.divider()
    if st.button("🗑️ Vider la Mémoire Temporaire"):
        st.session_state.raw_data = pd.DataFrame()
        st.session_state.valued_data = pd.DataFrame()
        st.session_state.portfolio_balances = {}
        st.rerun()

# --- Clients ---
cg = CoinGeckoAPI()
w3 = Web3()

# --- Helpers API & Blockscout ---
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

def fetch_paginated_v1(api_base, addr, action, max_txs, year):
    items = []
    page = 1
    while len(items) < max_txs:
        params = {"module":"account","action":action,"address":addr,"page":page,"offset":100,"sort":"desc"}
        j = call_api(api_base, params)
        if not j or not j.get("result"): break
        res = j["result"]
        if not isinstance(res, list): break

        # Filtre année précoce
        for item in res:
            dt = datetime.fromtimestamp(int(item.get("timeStamp", 0)), tz=tz.tzutc())
            if dt.year == year:
                items.append(item)
            elif dt.year < year:
                return items[:max_txs] # Arrêt si on dépasse l'année (tri desc)

        if len(res) < 100: break
        page += 1
        time.sleep(0.2)
    return items[:max_txs]

def fetch_blockscout_v2(api_v2, addr, max_txs, year, endpoint="transactions"):
    items = []
    url = f"{api_v2}/addresses/{addr}/{endpoint}"
    params = {}
    for _ in range(50):
        data = call_api(url, params)
        if not data or "items" not in data: break

        for item in data["items"]:
            dt = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
            if dt.year == year:
                items.append(item)
            elif dt.year < year:
                return items[:max_txs]

        if len(items) >= max_txs or "next_page_params" not in data or not data["next_page_params"]: break
        params.update(data["next_page_params"])
        time.sleep(0.2)
    return items[:max_txs]

# --- Prices ---
@st.cache_data(ttl=86400)
def coingecko_price_on_date_coin(coin_id, date_obj):
    try:
        time.sleep(1.5)
        d = date_obj.strftime("%d-%m-%Y")
        res = cg.get_coin_history_by_id(id=coin_id, date=d)
        return res.get("market_data", {}).get("current_price", {}).get("eur")
    except: return None

@st.cache_data(ttl=3600)
def coingecko_get_spot_prices(platform_id, contract_addresses):
    if not contract_addresses: return {}
    addr_str = ",".join(contract_addresses[:50]) # Limite par appel
    url = f"https://api.coingecko.com/api/v3/simple/token_price/{platform_id}"
    params = {"contract_addresses": addr_str, "vs_currencies": "eur"}
    j = call_api(url, params=params)
    return {addr.lower(): data.get("eur") for addr, data in j.items()} if j else {}

@st.cache_data(ttl=86400)
def coingecko_get_coin_id_by_contract(platform_id, contract_address):
    if not contract_address or contract_address == "0x": return None
    url = f"https://api.coingecko.com/api/v3/coins/{platform_id}/contract/{contract_address}"
    try:
        time.sleep(1.5)
        r = requests.get(url, timeout=15)
        if r.status_code == 404: return "NOT_FOUND"
        r.raise_for_status()
        return r.json().get("id")
    except: return None

# --- UI & Steps ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("Step 1 : Récolte des Données Brutes")
    harvest_btn = st.button("🚜 Lancer la Récolte (Année " + str(target_year) + ")", use_container_width=True)

with col2:
    st.subheader("Step 2 : Valorisation EUR & Fiscalité")
    value_btn = st.button("💰 Lancer la Valorisation (CoinGecko)", use_container_width=True, disabled=st.session_state.raw_data.empty)

# --- Logic Step 1 ---
if harvest_btn:
    if not address or not w3.is_address(address):
        st.error("❌ Adresse invalide.")
    else:
        addr_c = w3.to_checksum_address(address)
        all_rows = []

        progress = st.progress(0)
        for idx, chain in enumerate(chains):
            st.write(f"🌐 Récolte sur **{chain}**...")
            cfg = CHAIN_APIS[chain]

            # Native Transactions (V2 preferred)
            txs = fetch_blockscout_v2(cfg["v2"], addr_c, max_txs, target_year, "transactions")
            if not txs: txs = fetch_paginated_v1(cfg["v1"], addr_c, "txlist", max_txs, target_year)

            for t in txs:
                try:
                    ts = int(t.get("timeStamp", 0)) if "timeStamp" in t else int(datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp())
                    dt = datetime.fromtimestamp(ts, tz=tz.tzutc())
                    val = float(t.get("value", 0)) / 1e18
                    gas_used = int(t.get("gas_used", t.get("gasUsed", 0)))
                    gas_price = int(t.get("gas_price", t.get("gasPrice", 0)))
                    fee = (gas_used * gas_price) / 1e18

                    f_addr = t.get("from", {}).get("hash", t.get("from", "")).lower()
                    direction = "OUT" if f_addr == addr_c.lower() else "IN"

                    all_rows.append({
                        "Date": dt, "Chain": chain, "Type": "Native", "Asset": cfg["native"],
                        "Amount": val if direction == "IN" else -val, "Fee": fee if direction == "OUT" else 0.0,
                        "Hash": t.get("hash"), "Contract": "", "Direction": direction
                    })
                except: continue

            # Token Transfers (V2 preferred)
            toks = fetch_blockscout_v2(cfg["v2"], addr_c, max_txs, target_year, "token-transfers")
            if not toks: toks = fetch_paginated_v1(cfg["v1"], addr_c, "tokentx", max_txs, target_year)

            for t in toks:
                try:
                    ts = int(t.get("timeStamp", 0)) if "timeStamp" in t else int(datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp())
                    dt = datetime.fromtimestamp(ts, tz=tz.tzutc())

                    if "token" in t: # V2 Format
                        tok = t.get("token", {})
                        symbol = tok.get("symbol", "TOKEN")
                        dec = int(tok.get("decimals") or 18)
                        amt = float(t.get("total", t.get("value", 0))) / (10**dec)
                        contract = tok.get("address", "").lower()
                        f_addr = t.get("from", {}).get("hash", "").lower()
                    else: # V1 Format
                        symbol = t.get("tokenSymbol", "TOKEN")
                        dec = int(t.get("tokenDecimal") or 18)
                        amt = float(t.get("value", 0)) / (10**dec)
                        contract = t.get("contractAddress", "").lower()
                        f_addr = t.get("from", "").lower()

                    direction = "OUT" if f_addr == addr_c.lower() else "IN"

                    all_rows.append({
                        "Date": dt, "Chain": chain, "Type": "Token", "Asset": symbol,
                        "Amount": amt if direction == "IN" else -amt, "Fee": 0.0,
                        "Hash": t.get("hash", t.get("transactionHash")), "Contract": contract, "Direction": direction
                    })
                except: continue

            progress.progress((idx + 1) / len(chains))

        st.session_state.raw_data = pd.DataFrame(all_rows).sort_values("Date", ascending=False)
        st.success(f"✅ Récolte terminée : {len(st.session_state.raw_data)} lignes mémorisées.")

# Affichage du contrôle brut
if not st.session_state.raw_data.empty:
    st.divider()
    st.subheader(f"🔍 Contrôle des données récoltées ({target_year})")
    st.dataframe(st.session_state.raw_data, use_container_width=True)

# --- Logic Step 2 ---
if value_btn and not st.session_state.raw_data.empty:
    df = st.session_state.raw_data.copy()
    st.write("💰 Début de la valorisation...")

    # 1. Calcul des balances finales pour la VGP
    balances = {}
    for _, r in df.iterrows():
        key = f"{r['Type']}::{r['Asset']}::{r['Contract']}::{r['Chain']}"
        balances[key] = balances.get(key, 0.0) + r["Amount"] - r["Fee"]

    st.session_state.portfolio_balances = balances

    # 2. Valorisation VGP
    portfolio_rows = []
    vgp_total = 0.0

    # Optimization: Batch spot fetch for tokens by chain
    with st.spinner("Récupération groupée des prix spot..."):
        for chain_name in chains:
            relevant_contracts = [k.split("::")[2] for k, q in balances.items() if k.startswith("Token") and k.endswith(chain_name) and abs(q) > 1e-8]
            if relevant_contracts:
                platform = CHAIN_APIS.get(chain_name, {}).get("cg_platform", "ethereum")
                coingecko_get_spot_prices(platform, relevant_contracts)

    progress = st.progress(0)
    for idx, (key, qty) in enumerate(balances.items()):
        if abs(qty) < 1e-8: continue
        parts = key.split("::")
        type_a, asset, contract, chain = parts[0], parts[1], parts[2], parts[3]

        price = 0.0
        # Batch spot fetch simulation ou direct
        if type_a == "Native":
            mapping = {"ETH": "ethereum", "POL": "polygon-ecosystem-token", "BNB": "binancecoin"}
            price = coingecko_price_on_date_coin(mapping.get(asset, "ethereum"), datetime.now().date())
        else:
            platform = CHAIN_APIS.get(chain, {}).get("cg_platform", "ethereum")
            # Try batch cache first
            spot_map = coingecko_get_spot_prices(platform, [contract])
            price = spot_map.get(contract.lower())

            if not price:
                coin_id = coingecko_get_coin_id_by_contract(platform, contract)
                if coin_id and coin_id != "NOT_FOUND":
                    price = coingecko_price_on_date_coin(coin_id, datetime.now().date())

        # Fallbacks
        if not price and any(x in asset.upper() for x in ["USDC", "USDT", "DAI"]): price = 0.95
        if not price and asset.upper() in ["EURA", "AGEUR"]: price = 1.0

        val_eur = qty * (price or 0.0)
        vgp_total += val_eur
        portfolio_rows.append({"Asset": asset, "Chain": chain, "Quantity": qty, "Price EUR": price, "Value EUR": val_eur})
        progress.progress((idx + 1) / len(balances))

    st.session_state.valued_portfolio = pd.DataFrame(portfolio_rows)
    st.session_state.vgp_total = vgp_total
    st.success(f"💰 Valorisation terminée. VGP : {vgp_total:,.2f} €")

    # --- Affichage Fiscalité ---
    st.divider()
    st.header("⚖️ Fiscalité Art. 150 VH bis")
    st.metric("VGP Finale", f"{vgp_total:,.2f} €")

    if montant_cession > 0 and vgp_total > 0:
        ratio = montant_cession / vgp_total
        quote_acq = prix_acq_total * ratio
        plus_value = montant_cession - quote_acq
        impot = max(0.0, plus_value * 0.30) if montant_cession > 305 else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Plus-Value Brute", f"{plus_value:,.2f} €")
        c2.metric("Quote-part Acquisition", f"{quote_acq:,.2f} €")
        c3.metric("Impôt estimé (30%)", f"{impot:,.2f} €")

        # --- Exports ---
        st.divider()
        st.subheader("📥 Exports")
        ec1, ec2 = st.columns(2)

        with ec1:
            csv_data = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Télécharger CSV (Journal)", csv_data, f"journal_{target_year}.csv", "text/csv")

        with ec2:
            if st.button("📄 Générer Rapport Fiscal PDF"):
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.cell(0, 10, f"Rapport Fiscal Crypto {target_year} - Art. 150 VH bis", ln=True, align='C')
                pdf.ln(10)
                pdf.cell(0, 10, f"Adresse : {address}", ln=True)
                pdf.cell(0, 10, f"VGP Totale : {vgp_total:,.2f} EUR", ln=True)
                pdf.cell(0, 10, f"Prix d'acquisition total : {prix_acq_total:,.2f} EUR", ln=True)
                pdf.cell(0, 10, f"Montant de la cession : {montant_cession:,.2f} EUR", ln=True)
                pdf.cell(0, 10, f"Plus-Value : {plus_value:,.2f} EUR", ln=True)
                pdf.cell(0, 10, f"Impot estimé (Flat Tax 30%) : {impot:,.2f} EUR", ln=True)

                pdf_data = pdf.output(dest='S').encode('latin-1')
                st.download_button("📥 Télécharger le PDF", pdf_data, f"rapport_fiscal_{target_year}.pdf")

st.sidebar.divider()
st.sidebar.caption("Jules AI Harvest Pro V6.0")
