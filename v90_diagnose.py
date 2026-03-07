import streamlit as st
import pandas as pd
import requests
import time
import os
import json
from datetime import datetime

# --- 1. CONFIGURATION ---
NETWORKS = {
    "Ethereum": {"scan": "api.etherscan.io", "bs": "eth.blockscout.com/api", "native": "ETH"},
    "Polygon": {"scan": "api.polygonscan.com", "bs": "polygon.blockscout.com/api", "native": "POL"},
    "Arbitrum": {"scan": "api.arbiscan.io", "bs": "arbitrum.blockscout.com/api", "native": "ETH"},
    "Optimism": {"scan": "api-optimistic.etherscan.io", "bs": "optimism.blockscout.com/api", "native": "ETH"},
    "BSC": {"scan": "api.bscscan.com", "bs": "bsc.blockscout.com/api", "native": "BNB"},
    "Base": {"scan": "api.basescan.org", "bs": "base.blockscout.com/api", "native": "ETH"}
}
DB_FILE = "harvest_storage.csv"
LOG_FILE = "accounts_log.csv"
BLACKLIST_FILE = "spam_blacklist.json"

st.set_page_config(page_title="Jules Crypto Harvest V90 Pro", layout="wide")

# --- 2. PERSISTANCE & ÉTATS ---
if 'db' not in st.session_state:
    st.session_state.db = pd.DataFrame(columns=['ID', 'Date', 'Account', 'Counterparty', 'Asset', 'Amount', 'Type', 'Network', 'Is_Spam'])
if 'accounts_log' not in st.session_state:
    st.session_state.accounts_log = {}
if 'blacklist' not in st.session_state:
    st.session_state.blacklist = {"assets": [], "addresses": [], "labels": {}, "is_internal": []}
if 'global_api_key' not in st.session_state:
    st.session_state.global_api_key = ""

def save_data():
    st.session_state.db.to_csv(DB_FILE, index=False)
    if st.session_state.accounts_log:
        pd.DataFrame(st.session_state.accounts_log).T.to_csv(LOG_FILE)
    with open(BLACKLIST_FILE, 'w') as f:
        json.dump(st.session_state.blacklist, f)

def load_data():
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, 'r') as f:
                st.session_state.blacklist = json.load(f)
        except: pass

    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'], utc=True)
        st.session_state.db = df

    if os.path.exists(LOG_FILE):
        try:
            log_df = pd.read_csv(LOG_FILE, index_col=0)
            st.session_state.accounts_log = {str(k).lower().strip(): v for k, v in log_df.to_dict('index').items()}
        except: pass

load_data()

# --- 3. LOGIQUE MOTEUR (3 VOIES) ---
def run_v90_engine(address, network, api_key, spam_threshold=0.0):
    addr = address.strip().lower()
    cfg = NETWORKS[network]
    # Utilise la clé fournie ou la clé globale
    key = api_key if api_key else st.session_state.global_api_key
    if not key: key = "YourApiKeyToken"

    new_data = []
    # Priorité Blockscout (BS) en premier
    queries = [
        ("BS", f"https://{cfg['bs']}?module=account&action=tokentx&address={addr}"),
        ("SCAN_TOKENS", f"https://{cfg['scan']}/api?module=account&action=tokentx&address={addr}&apikey={key}"),
        ("SCAN_NATIF", f"https://{cfg['scan']}/api?module=account&action=txlist&address={addr}&apikey={key}")
    ]

    with st.status(f"🛰️ Récolte {network} : {addr[:10]}...", expanded=False) as status:
        for name, url in queries:
            try:
                time.sleep(0.3)
                r = requests.get(url, timeout=12).json()
                items = r.get("result", [])
                if not isinstance(items, list): continue

                # Limite à 1000 lignes par source pour la performance
                for t in items[:1000]:
                    tx_hash = t.get("hash")
                    f_addr, t_addr = t.get("from", "").lower().strip(), t.get("to", "").lower().strip()
                    is_in = t_addr == addr
                    cp = f_addr if is_in else t_addr

                    sym = (t.get("tokenSymbol") or cfg["native"]).upper()
                    dec = int(t.get("tokenDecimal") or 18)
                    val = float(t.get("value") or 0) / (10**dec)

                    if val > 0:
                        is_in_bl = (sym in st.session_state.blacklist["assets"]) or (cp in st.session_state.blacklist["addresses"])
                        new_data.append({
                            'ID': f"{tx_hash}_{sym}",
                            'Date': pd.to_datetime(int(t['timeStamp']), unit='s', utc=True),
                            'Account': addr, 'Counterparty': cp, 'Asset': sym,
                            'Amount': val if is_in else -val, 'Type': 'Mouvement',
                            'Network': network, 'Is_Spam': is_in_bl or (val < spam_threshold and name != "SCAN_NATIF")
                        })

                    # Gestion des frais (uniquement sur l'adresse source)
                    if f_addr == addr and 'gasPrice' in t:
                        fee = (int(t.get('gasPrice', 0)) * int(t.get('gasUsed', 0))) / 10**18
                        if fee > 0:
                            new_data.append({
                                'ID': f"{tx_hash}_FEE", 'Date': pd.to_datetime(int(t['timeStamp']), unit='s', utc=True),
                                'Account': addr, 'Counterparty': 'network fee', 'Asset': cfg["native"],
                                'Amount': -fee, 'Type': 'Frais Réseau', 'Network': network, 'Is_Spam': False
                            })
            except: continue
        status.update(label="✅ Terminé", state="complete")

    if new_data:
        df = pd.DataFrame(new_data)
        st.session_state.db = pd.concat([st.session_state.db, df]).drop_duplicates(subset=['ID']).reset_index(drop=True)
        st.session_state.accounts_log[addr] = {
            "Réseau": network, "Adresse": address,
            "Transactions": len(new_data),
            "Last_Sync": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }
        save_data()
        return True
    return False

def get_label_display(address):
    if not address or pd.isna(address) or str(address).lower() == "network fee": return "—"
    addr_clean = str(address).lower().strip()
    alias = st.session_state.blacklist.get("labels", {}).get(addr_clean)
    is_int = addr_clean in st.session_state.blacklist.get("is_internal", []) or addr_clean in st.session_state.accounts_log

    if is_int: return f"🟢 [INT] {alias.upper() if alias else 'COMPTE SOURCE'}"
    if alias: return f"🔵 [POS] {alias.upper()}"
    return f"⚪ [EXT] {addr_clean[:15]}..."

# --- 4. NAVIGATION ---
menu = st.sidebar.radio("Menu", ["🚜 Harvest", "🔍 Consultation", "⚖️ Fiscalité", "⚙️ Paramètres"])

# --- PAGE HARVEST ---
if menu == "🚜 Harvest":
    st.header("🚜 Récolte & Gestion")

    # Zone API Master
    with st.expander("🔑 Configuration Clé API Globale", expanded=not st.session_state.global_api_key):
        c_k1, c_k2 = st.columns([3, 1])
        new_k = c_k1.text_input("Clé API (Etherscan, BscScan...)", value=st.session_state.global_api_key, type="password")
        if c_k2.button("Sauvegarder", use_container_width=True):
            st.session_state.global_api_key = new_k
            st.success("Clé enregistrée")
        if c_k2.button("Effacer", use_container_width=True):
            st.session_state.global_api_key = ""
            st.rerun()

    # Ajout de compte
    with st.container(border=True):
        st.subheader("➕ Nouveau compte")
        c1, c2, c3 = st.columns([2, 1, 1])
        in_addr = c1.text_input("Adresse 0x...")
        in_net = c2.selectbox("Réseau", list(NETWORKS.keys()))
        in_label = c3.text_input("Étiquette")

        if st.button("LANCER LA RÉCOLTE", use_container_width=True, type="primary"):
            if in_addr:
                if in_label: st.session_state.blacklist["labels"][in_addr.lower().strip()] = in_label
                run_v90_engine(in_addr, in_net, st.session_state.global_api_key)
                st.rerun()

    # Journal & Mise à jour globale
    if st.session_state.accounts_log:
        st.divider()
        col_t, col_b = st.columns([3, 1])
        col_t.subheader("📜 Journal des Comptes")
        if col_b.button("🔄 TOUT METTRE À JOUR", use_container_width=True):
            prog = st.progress(0)
            items = list(st.session_state.accounts_log.items())
            for idx, (addr, info) in enumerate(items):
                run_v90_engine(addr, info['Réseau'], st.session_state.global_api_key)
                prog.progress((idx + 1) / len(items))
            st.success("Mise à jour terminée")
            st.rerun()

        for addr, info in st.session_state.accounts_log.items():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 3, 2, 1])
                c1.write(f"**{info['Réseau']}**")
                c2.code(info['Adresse'])
                c3.write(get_label_display(addr))
                if c4.button("🔄", key=f"sync_{addr}"):
                    run_v90_engine(addr, info['Réseau'], st.session_state.global_api_key)
                    st.rerun()

# --- PAGE CONSULTATION ---
elif menu == "🔍 Consultation":
    st.header("🔍 Consultation")
    if not st.session_state.db.empty:
        st.session_state.db['Étiquette'] = st.session_state.db['Counterparty'].apply(get_label_display)

        # Filtres
        with st.container(border=True):
            f1, f2, f3 = st.columns([1, 1, 2])
            show_spam = f1.toggle("Voir Spams (Jaune)", value=True)
            hide_fees = f2.toggle("Masquer Frais", value=False)
            all_tags = sorted(st.session_state.db['Étiquette'].unique())
            sel_tags = f3.multiselect("Filtrer Étiquettes", all_tags, default=all_tags)

        # Logique de vue
        view_df = st.session_state.db.copy()
        if not show_spam: view_df = view_df[view_df['Is_Spam'] == False]
        if hide_fees: view_df = view_df[view_df['Type'] != 'Frais Réseau']
        view_df = view_df[view_df['Étiquette'].isin(sel_tags)]
        view_df = view_df.sort_values('Date', ascending=False).reset_index(drop=True)

        st.session_state["current_ids"] = view_df['ID'].tolist()

        def sync_spam():
            edits = st.session_state["editor"].get("edited_rows", {})
            for row_idx, patch in edits.items():
                if "Is_Spam" in patch:
                    tid = st.session_state["current_ids"][int(row_idx)]
                    st.session_state.db.loc[st.session_state.db['ID'] == tid, 'Is_Spam'] = patch["Is_Spam"]
            save_data()

        # Affichage avec style
        st.data_editor(
            view_df.style.apply(lambda r: ['background-color: #ffffcc' if r.Is_Spam else '' for _ in r], axis=1),
            column_config={"Is_Spam": st.column_config.CheckboxColumn("SPAM"), "ID": None},
            disabled=[c for c in view_df.columns if c != "Is_Spam"],
            use_container_width=True, hide_index=True, on_change=sync_spam, key="editor"
        )

# --- PAGES SECONDAIRES (Fiscalité & Paramètres simplifiés) ---
elif menu == "⚖️ Fiscalité":
    st.header("⚖️ Fiscalité")
    clean_db = st.session_state.db[st.session_state.db['Is_Spam'] == False]
    if not clean_db.empty:
        st.subheader("Soldes par Asset")
        st.dataframe(clean_db.groupby('Asset')['Amount'].sum().reset_index(), use_container_width=True)

elif menu == "⚙️ Paramètres":
    st.header("⚙️ Paramètres Labels")
    l_addr = st.text_input("Adresse").lower().strip()
    l_name = st.text_input("Nom de l'étiquette")
    if st.button("Enregistrer Label"):
        st.session_state.blacklist["labels"][l_addr] = l_name
        save_data()
        st.rerun()
