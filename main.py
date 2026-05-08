import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time
import importlib
import os
from shared_logic import get_price_eur, get_fiat_rate, show_status

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto Hub - Navigation", layout="wide")

# Configuration des Réseaux (Architecture demandée)
NETWORKS_CFG = {
    "Ethereum": {"host": "api.etherscan.io", "native": "ETH", "free_api": "https://api.ethplorer.io"},
    "Polygon": {"host": "api.polygonscan.com", "native": "POL"},
    "Arbitrum": {"host": "api.arbiscan.io", "native": "ETH"},
    "Base": {"host": "api.basescan.org", "native": "ETH", "free_api": "https://base.blockscout.com/api/v2"},
    "Optimism": {"host": "api-optimistic.etherscan.io", "native": "ETH", "free_api": "https://optimism.blockscout.com/api/v2"},
    "BSC": {"host": "api.bscscan.com", "native": "BNB", "free_api": "https://api.bscscan.com/api"}
}

# --- Status Indicator ---
def show_status():
    st.sidebar.success("✅ Système Opérationnel")
    st.sidebar.caption(f"Logique Partagée : OK")

# --- Initialisation de la Session ---
REQUIRED_COLS = ['Source', 'ID', 'Date', 'Account', 'Asset', 'Type', 'Amount', 'Fee', 'Fiat_Value_EUR', 'Counterparty', 'Network', 'Is_Spam', 'Category']

if 'transactions' not in st.session_state or not all(c in st.session_state.transactions.columns for c in REQUIRED_COLS):
    st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)

# Sanity check: conversion systématique en datetime
if not st.session_state.transactions.empty:
    st.session_state.transactions['Date'] = pd.to_datetime(st.session_state.transactions['Date'], utc=True, errors='coerce')

if 'accounts_metadata' not in st.session_state:
    st.session_state.accounts_metadata = {}
if 'fiat_accounts' not in st.session_state:
    st.session_state.fiat_accounts = pd.DataFrame(columns=['Date', 'Label', 'Amount_EUR', 'Type'])
if 'spam_addresses' not in st.session_state:
    st.session_state.spam_addresses = set()


# --- MOTEUR DE RÉCOLTE ULTIME (V3.0) ---

def fetch_data(address, api_key, network):
    txs = []
    addr_low = address.lower()
    cfg = NETWORKS_CFG[network]

    report = st.expander(f"🚜 Récolte Massive en cours : {network}", expanded=True)
    status_text = report.empty()
    counts = {"Native": 0, "Tokens": 0, "Internal": 0, "Discovery": 0}

    # -- PHASE 1 : VOIE LIBRE (Deep Scan Blockscout) --
    if "free_api" in cfg and "blockscout" in cfg["free_api"]:
        endpoints = [
            ("transactions", "Native"),
            ("token-transfers", "Tokens"),
            ("internal-transactions", "Internal"),
            ("token-balances", "Discovery")
        ]

        for endpoint, label in endpoints:
            base_url = f"{cfg['free_api']}/addresses/{address}/{endpoint}"
            url = base_url
            for page in range(500): # Profondeur maximale (Jusqu'à 25000 txs par type)
                try:
                    status_text.text(f"⏳ Extraction {label} : Page {page+1}...")
                    res = requests.get(url, timeout=25)

                    if res.status_code == 404 and endpoint == "token-balances":
                        res = requests.get(f"{cfg['free_api']}/addresses/{address}/tokens", timeout=25)

                    if res.status_code != 200:
                        if res.status_code == 429:
                            status_text.warning("Rate limit API... attente 5s")
                            time.sleep(5)
                            continue
                        break

                    data = res.json()
                    # Détection flexible de la liste d'items (Blockscout v1/v2/Custom)
                    items = data.get("items") if isinstance(data, dict) else data if isinstance(data, list) else None
                    if items is None and isinstance(data, dict):
                        items = data.get("result")

                    if not isinstance(items, list) or not items: break

                    for t in items:
                        try:
                            if not isinstance(t, dict): continue

                            if label == "Discovery":
                                tok = t.get('token') or {}
                                asset = tok.get('symbol') or tok.get('name') or 'TOKEN'
                                dec = int(tok.get('decimals') or 18)
                                val_raw = t.get('value') or '0'
                                amount = float(val_raw) / 10**dec
                                if amount <= 0: continue
                                tx_id = f"DISC-{asset}-{address.lower()}"
                                dt = datetime.now()
                                direction = 1
                                cp = "Discovery Balance"
                            else:
                                tx_id = t.get('hash') or t.get('tx_hash')
                                if not tx_id: continue

                                # Détection Token ultra-robuste
                                if label == "Tokens" or "token" in t or "tokenSymbol" in t:
                                    tok = t.get('token') or {}
                                    asset = tok.get('symbol') or t.get('tokenSymbol') or tok.get('name') or 'TOKEN'
                                    dec = int(tok.get('decimals') or t.get('tokenDecimal') or 18)
                                    val_raw = t.get('value') or '0'
                                    amount = float(val_raw) / 10**dec
                                else:
                                    asset = cfg['native']
                                    amount = float(t.get('value') or '0') / 10**18

                                dt_str = t.get('timestamp') or t.get('timeStamp')
                                if dt_str and not str(dt_str).isdigit():
                                    dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
                                elif dt_str:
                                    dt = datetime.fromtimestamp(int(dt_str))
                                else:
                                    dt = datetime.now()

                                f_addr = (t.get('from') if isinstance(t.get('from'), str) else t.get('from', {}).get('hash', 'Unknown')).lower()
                                t_addr = (t.get('to') if isinstance(t.get('to'), str) else t.get('to', {}).get('hash', 'Unknown')).lower()
                                direction = 1 if t_addr == addr_low else -1
                                cp = f_addr if direction == 1 else t_addr

                            fee_val = (t.get('fee') or {}).get('value', '0') if isinstance(t.get('fee'), dict) else '0'
                            fee = float(fee_val) / 10**18

                            txs.append({
                                'Source': f'Blockscout ({label})', 'ID': tx_id, 'Date': dt,
                                'Account': address, 'Asset': str(asset).upper(), 'Type': 'Mvt',
                                'Amount': amount * direction, 'Fee': fee, 'Counterparty': cp, 'Network': network
                            })
                            counts[label] += 1
                        except: continue

                    next_p = data.get("next_page_params") if isinstance(data, dict) else None
                    if next_p:
                        q = "&".join([f"{k}={v}" for k, v in next_p.items()])
                        url = f"{base_url}?{q}"
                    else: break
                except: break

    # -- PHASE 2 : VOIE API (Etherscan/BscScan etc avec Pagination) --
    if api_key:
        api_endpoints = [
            ("txlist", "Native"), ("tokentx", "Tokens"),
            ("txlistinternal", "Internal"), ("erc721tx", "NFTs")
        ]
        for action, label in api_endpoints:
            try:
                status_text.text(f"⏳ Interrogation API {label} (Deep)...")
                start_block = 0
                for loop in range(10): # Récupération jusqu'à 100,000 transactions par type
                    url = f"https://{cfg['host']}/api?module=account&action={action}&address={address}&startblock={start_block}&endblock=99999999&offset=10000&sort=asc&apikey={api_key}"
                    res = requests.get(url, timeout=20).json()

                    results = res.get("result", [])
                    if str(res.get("status")) != "1" or not isinstance(results, list) or not results:
                        break

                    for t in results:
                        try:
                            asset = t.get("tokenSymbol") or cfg["native"]
                            dec = int(t.get("tokenDecimal") or 18)
                            amt = float(t.get("value") or 0) / 10**dec

                            gas_price = int(t.get('gasPrice') or 0)
                            gas_used = int(t.get('gasUsed') or 0)
                            fee = (gas_used * gas_price) / 10**18

                            f_addr, t_addr = t.get('from', '').lower(), t.get('to', '').lower()
                            direction = 1 if t_addr == addr_low else -1

                            txs.append({
                                'Source': f'API ({label})', 'ID': t['hash'], 'Date': datetime.fromtimestamp(int(t['timeStamp'])),
                                'Account': address, 'Asset': str(asset).upper(), 'Type': 'Mvt', 'Amount': amt * direction, 'Fee': fee,
                                'Counterparty': f_addr if direction == 1 else t_addr, 'Network': network
                            })
                            counts[label] += 1
                        except: continue

                    # Pagination par bloc
                    last_block = int(results[-1].get('blockNumber', 0))
                    if last_block <= start_block: break
                    start_block = last_block + 1
                    if len(results) < 10000: break
                    time.sleep(0.2) # Courtoisie API
            except: pass

    # -- PHASE 3 : TRAITEMENT & VALORISATION --
    status_text.empty()
    report.write(f"✅ Récolte finie : {counts['Native']} Natifs, {counts['Tokens']} Tokens, {counts['Discovery']} Balances")

    df = pd.DataFrame(txs)
    if not df.empty:
        # Dédoublonnage priorisant la richesse des données
        df = df.sort_values('Source', ascending=False).drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')

        with st.spinner("Synchronisation des cours..."):
            df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')
            df = df.dropna(subset=['Date', 'Asset'])

            # Agrégation optimisée des prix (On ne requête que les dates des mouvements réels)
            mouvements = df[['Asset', 'Date']].copy()
            mouvements['Day'] = mouvements['Date'].dt.date
            combos = mouvements[['Asset', 'Day']].drop_duplicates()

            prices_map = {}
            total_req = len(combos)
            if total_req > 0:
                pbar = st.progress(0)
                for idx, row in enumerate(combos.itertuples()):
                    prices_map[(row.Asset, row.Day)] = get_price_eur(row.Asset, row.Day)
                    # Respect du Rate Limit CoinGecko (1 requête par sec environ)
                    if total_req > 5: time.sleep(1.05)
                    pbar.progress((idx+1)/total_req)
                pbar.empty()

            df['Fiat_Value_EUR'] = df.apply(lambda r: float(r['Amount']) * prices_map.get((r['Asset'], r['Date'].date()), 0.0), axis=1)

        df['Is_Spam'] = df['Counterparty'].apply(lambda x: str(x).lower() in st.session_state.spam_addresses)
        df['Category'] = df['Asset'].apply(lambda a: 'DeFi' if any(x in a.lower() for x in ['lnd', 'steth', 'steur']) else 'Transfert')

    return df

# --- UI PRINCIPALE: Navigation Hub ---
menu_options = {
    "🏠 Accueil": "home",
    "🚜 Step 1: Harvest (app)": "app",
    "🏦 Step 0: Registre Manuel (app0)": "app0",
    "⚖️ Step 2: Qualification (app2)": "app2",
    "🧮 Step 3a: Calcul VGP (app2VGP)": "app2VGP",
    "👤 Step 3b: Dashboard Patrimoine (appPropri)": "appPropri",
    "🏛️ Step 3c: Fiscalité (app3)": "app3",
    "🕵️ Step 4: Diagnostic (appDiagCoh)": "appDiagCoh",
    "🔍 Fix: Collecteur Prix (appPriceFix)": "appPriceFix",
    "🧪 Live Harvest Pro (main)": "live_harvest"
}

# Ensure the navigation state is initialized
if "_hub_current_menu" not in st.session_state:
    st.session_state["_hub_current_menu"] = "home"

# Render Navigation Hub at the TOP of the sidebar
st.sidebar.title("💎 Jules Crypto Hub")

# Create a mapping for finding the index
menu_labels = list(menu_options.keys())
menu_values = list(menu_options.values())
default_index = menu_values.index(st.session_state["_hub_current_menu"]) if st.session_state["_hub_current_menu"] in menu_values else 0

menu_selection = st.sidebar.selectbox(
    "🚀 Navigation",
    options=menu_labels,
    index=default_index,
    key="_hub_nav_selectbox_v13" # Versioned key for robustness
)

# Update the state immediately
st.session_state["_hub_current_menu"] = menu_options[menu_selection]
menu = st.session_state["_hub_current_menu"]

# Auto-discovery of owner accounts
def get_discovered_accounts():
    discovered = set()
    if not st.session_state.transactions.empty:
        discovered.update(st.session_state.transactions['Account'].dropna().unique())
    from shared_logic import get_known_accounts
    discovered.update(get_known_accounts(include_mappings=False))
    return sorted([str(x) for x in discovered if str(x).strip()])

with st.sidebar:
    st.divider()
    st.subheader("🏦 Comptes Propriétaires")
    discovered_accs = get_discovered_accounts()
    if discovered_accs:
        for acc in discovered_accs:
            st.sidebar.caption(f"• {acc}")
    else:
        st.sidebar.info("Aucun compte détecté.")

    new_acc = st.text_input("Ajouter un compte manuel", placeholder="ex: 0x... ou Label")
    if st.button("➕ Ajouter"):
        if new_acc:
            # We don't have a dedicated accounts list in session,
            # but adding a dummy transaction or using metadata could work.
            # For now, we'll use metadata to store manually added labels
            st.session_state.accounts_metadata[new_acc] = {"Count": 0, "Manual": True}
            st.rerun()

# --- Routing Logic ---
if menu == "home":
    st.header("Bienvenue dans votre Hub Crypto Jules")
    st.write("Sélectionnez un module dans la barre latérale pour commencer votre traitement fiscal.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("### 🚜 Étape 1 : Récolte\nCollectez vos données on-chain via Blockscout et Etherscan.")
    with c2:
        st.info("### ⚖️ Étape 2 : Qualification\nNettoyez les spams et qualifiez vos mouvements.")
    with c3:
        st.info("### 🏛️ Étape 3 : Fiscalité\nCalculez votre VGP et générez votre rapport fiscal.")

elif menu == "live_harvest":
    st.header("🚜 Récolte Massive de Données (Live)")
    t1, t2, t3, t4, t5 = st.tabs(["Récolte deep", "Consultation", "Fiscalité", "Saisie Manuelle", "Settings"])

    with t1:
        with st.form("harvest_form"):
            col1, col2 = st.columns(2)
            addr = col1.text_input("Adresse Blockchain (0x...)")
            net = col2.selectbox("Réseau", list(NETWORKS_CFG.keys()))
            key = st.text_input(f"Clé API pour {net} (Optionnel)", type="password")
            submit = st.form_submit_button("Lancer la récolte profonde")

        if submit and addr:
            new_df = fetch_data(addr, key, net)
            if not new_df.empty:
                st.session_state.transactions = pd.concat([st.session_state.transactions, new_df])
                st.session_state.transactions = st.session_state.transactions.drop_duplicates(subset=['ID', 'Asset', 'Network'], keep='first')
                st.session_state.transactions = st.session_state.transactions.sort_values('Date', ascending=False)
                st.session_state.accounts_metadata[f"{addr[:10]}... ({net})"] = {"Count": len(new_df)}
                st.success(f"Récolte réussie : {len(new_df)} lignes.")

        if st.session_state.accounts_metadata:
            st.subheader("📋 Gestion des Comptes")
            for acc, meta in list(st.session_state.accounts_metadata.items()):
                c1, c2 = st.columns([4, 1])
                msg = f"{acc} : {meta.get('Count', 0)} transactions"
                if meta.get("Manual"): msg += " (Manuel)"
                c1.info(msg)
                if c2.button("Supprimer", key=f"del_{acc}"):
                    del st.session_state.accounts_metadata[acc]; st.rerun()

    with t4:
        st.subheader("📝 Ajouter une transaction isolée")
        with st.form("manual_entry"):
            mc1, mc2, mc3 = st.columns(3)
            m_date = mc1.date_input("Date", datetime.now())
            m_asset = mc2.text_input("Asset (ex: USDC, 8LND)", "USDC")
            m_amt = mc3.number_input("Montant", value=0.0, format="%.6f")
            m_net = st.selectbox("Réseau", list(NETWORKS_CFG.keys()), key="m_net")
            m_cat = st.selectbox("Catégorie", ["Transfert", "Swap", "Achat Fiat"], index=0)
            m_submit = st.form_submit_button("Ajouter à l'historique")

            if m_submit:
                new_row = pd.DataFrame([{
                    'Source': '✍️ Manuel', 'ID': f"MAN-{int(time.time())}", 'Date': pd.to_datetime(m_date, utc=True),
                    'Account': 'Manual Wallet', 'Asset': str(m_asset).upper(), 'Type': 'Mvt',
                    'Amount': m_amt, 'Fee': 0.0, 'Fiat_Value_EUR': 0.0,
                    'Counterparty': 'User', 'Network': m_net, 'Is_Spam': False, 'Category': m_cat
                }])
                new_row['Fiat_Value_EUR'] = new_row.apply(lambda r: float(r['Amount']) * get_price_eur(r['Asset'], r['Date']), axis=1)
                st.session_state.transactions = pd.concat([st.session_state.transactions, new_row], ignore_index=True)
                st.success("Ajouté !")

    with t2:
        st.header("🔍 Consultation & Inventaire")
        show_spam_live = st.checkbox("Afficher les transactions Spam", value=False, key="chk_show_spam_live")

        if not st.session_state.transactions.empty:
            # Filtrage strict pour l'inventaire
            clean_df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]
            inv = clean_df.groupby('Asset').agg({'Amount': 'sum'}).reset_index()
            inv = inv[inv['Amount'].abs() > 1e-9]

            if not inv.empty:
                st.subheader("📦 Position Actuelle (Hors Spam)")
                now = datetime.now()
                inv['p_eur'] = inv['Asset'].apply(lambda a: float(get_price_eur(str(a), now)))
                inv['val_eur'] = inv['Amount'] * inv['p_eur']
                inv = inv.sort_values('val_eur', ascending=False)
                cols = st.columns(min(len(inv), 4))
                for idx, row in inv.iterrows():
                    with cols[idx % 4]: st.metric(row['Asset'], f"{row['Amount']:.4f}", f"{row['val_eur']:,.2f} €")

            st.divider()
            df_display = st.session_state.transactions.copy()
            # Masquage immédiat si l'option est décochée (Comportement automatique)
            if not show_spam_live:
                df_display = df_display[df_display['Is_Spam'] == False]

            # On libère aussi la liste des assets filtrables de tout spam
            available_assets = sorted(df_display['Asset'].unique())
            f_asset_live = st.multiselect("Filtrer Asset", options=available_assets, key="f_asset_live")
            if f_asset_live: df_display = df_display[df_display['Asset'].isin(f_asset_live)]

            st.subheader("📝 Historique des Mouvements")
            edited = st.data_editor(df_display.sort_values('Date', ascending=False), width='stretch', key="tx_ed_live")
            if st.button("💾 Sauvegarder modifications", key="btn_save_live"):
                for _, row in edited.iterrows():
                    # Mise à jour de la ligne spécifique
                    mask = (st.session_state.transactions['ID'] == row['ID']) & (st.session_state.transactions['Asset'] == row['Asset'])
                    st.session_state.transactions.loc[mask, 'Is_Spam'] = row['Is_Spam']
                    st.session_state.transactions.loc[mask, 'Category'] = row['Category']

                    # Propagation du marquage Spam à l'adresse de contrepartie
                    cp = str(row['Counterparty']).lower()
                    if row['Is_Spam']:
                        st.session_state.spam_addresses.add(cp)
                        st.session_state.transactions.loc[st.session_state.transactions['Counterparty'].str.lower() == cp, 'Is_Spam'] = True
                    else:
                        if cp in st.session_state.spam_addresses:
                            st.session_state.spam_addresses.remove(cp)
                            # On réactive les transactions si on retire le flag spam global
                            st.session_state.transactions.loc[st.session_state.transactions['Counterparty'].str.lower() == cp, 'Is_Spam'] = False
                st.success("Enregistré ! (Propagation appliquée)"); st.rerun()

    with t3:
        st.header("⚖️ Fiscalité (Art. 150 VH bis)")
        st.session_state.fiat_accounts = st.data_editor(st.session_state.fiat_accounts, num_rows="dynamic", width='stretch', key="ed_fiat_live")
        clean_df = st.session_state.transactions[st.session_state.transactions['Is_Spam'] == False]
        if not clean_df.empty:
            # Valeur Globale Portefeuille
            inv = clean_df.groupby('Asset').agg({'Amount': 'sum'}).reset_index()
            vgp = sum([float(row['Amount']) * get_price_eur(str(row['Asset']), datetime.now()) for _, row in inv.iterrows()])
            st.metric("Valeur Globale Portefeuille (VGP)", f"{vgp:,.2f} €")
            prix_acq = st.number_input("Prix d'acquisition total (EUR)", value=0.0, key="prix_acq_live")
            prix_vent = st.number_input("Montant de la cession (EUR)", value=0.0, key="prix_vent_live")
            if prix_vent > 0 and vgp > 0:
                pv = prix_vent - (prix_acq * (prix_vent / vgp))
                st.success(f"Plus-value : {pv:,.2f} € | Impôt estimé (30%) : {pv*0.3:,.2f} €")

    with t5:
        if st.button("🗑️ Vider toute la base de données", key="btn_clear_live"):
            st.session_state.transactions = pd.DataFrame(columns=REQUIRED_COLS)
            st.session_state.accounts_metadata = {}; st.rerun()

# --- Integrated Module Loading ---
elif menu in ["app", "app0", "app2", "app2VGP", "appPropri", "app3", "appDiagCoh", "appPriceFix"]:
    module_name = menu
    try:
        # We dynamicallly import and run the module's main logic
        # Note: most apps run on import because of their structure
        # To avoid re-importing identical UI, we can use run_module pattern
        st.info(f"Chargement du module `{module_name}.py`...")

        # Method: Execution of the script content in the current context
        # This keeps the sidebar and session state unified
        with open(f"{module_name}.py", "r", encoding="utf-8") as f:
            code = f.read()
            # We strip the set_page_config call if present to avoid Streamlit error
            code = code.replace("st.set_page_config", "# st.set_page_config")
            exec(code, globals())

    except Exception as e:
        st.error(f"Erreur lors du chargement du module {module_name} : {e}")
        st.exception(e)

st.sidebar.divider(); show_status()
st.sidebar.divider(); st.sidebar.caption("Jules Crypto Hub v1.0")
