import os
import time
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import unicodedata

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Calcul VGP Pro (app2VGP)", layout="wide")
st.title("🧮 Calculateur de VGP Historique (Version Pro)")

EXPORT_BASE_DIR = "sanctuarisation"
PRICE_CACHE_FILE = "historical_prices_cache.json"
POSITIONS_FILE = "position_labels.json"

# --- Cache Engine ---
def load_price_cache():
    """Loads prices from both global cache and all annual sanctuarised files."""
    combined = {}
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, "r", encoding="utf-8", errors="replace") as f:
                combined = json.load(f)
        except: pass

    # Merge with annual verified prices
    if os.path.exists(EXPORT_BASE_DIR):
        years = [y for y in os.listdir(EXPORT_BASE_DIR) if os.path.isdir(os.path.join(EXPORT_BASE_DIR, y))]
        for y in years:
            path = os.path.join(EXPORT_BASE_DIR, y, f"verified_prices_{y}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        combined.update(json.load(f))
                except: pass
    return combined

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

def resolve_raw_addr(addr_str):
    if "(" in str(addr_str) and ")" in str(addr_str):
        return str(addr_str).split("(")[-1].split(")")[0].strip().lower()
    return str(addr_str).strip().lower()

def save_price_cache(cache):
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

# --- Helpers ---
def pd_read_csv_safe(path):
    """Robust CSV reading for Windows with encoding fallbacks."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try:
            return pd.read_csv(path, encoding="latin-1")
        except:
            return pd.read_csv(path, encoding="utf-8", errors="replace")

def get_qualified_path(year):
    return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")

def get_fiat_rate(from_currency, date_obj):
    """Fetches official BCE exchange rates via Frankfurter API."""
    from_currency = from_currency.upper().strip()
    if from_currency == "EUR": return 1.0
    date_str = date_obj.strftime("%Y-%m-%d")
    try:
        url = f"https://api.frankfurter.app/{date_str}?from={from_currency}&to=EUR"
        res = requests.get(url, timeout=5).json()
        return float(res["rates"]["EUR"])
    except:
        return 0.0

def get_price_eur(asset, date_obj):
    # CRUCIAL: On normalise pour l'API tout en gardant l'original pour l'affichage UI
    nuance_map = {
        "\ua4f4": "U", "\ua4e2": "S", "\ua4d3": "D", "\ua4c1": "G", "\ua4c3": "H",
        "\u0421": "C", "\u0405": "S", "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T", "\u0425": "X",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u216d": "C", "\u2160": "I", "\u2164": "V", "\u2169": "X", "\u216c": "L", "\u216f": "M",
    }
    asset_clean = str(asset)
    for k, v in nuance_map.items():
        asset_clean = asset_clean.replace(k, v)
    asset_clean = unicodedata.normalize('NFKC', asset_clean).upper().strip()

    # 1. Stables & Direct Mappings (BCE Forex Data)
    if asset_clean in ["EUR", "EURA", "AGEUR", "STEUR", "EURC"]:
        return 1.0

    if asset_clean in ["USD", "USDC", "USDT", "DAI", "USDC.E", "STUSD", "SUSDS", "TWCOMPOUNDUSDC"]:
        return get_fiat_rate("USD", date_obj)

    if asset_clean == "ZCHF":
        return get_fiat_rate("CHF", date_obj)

    d_str = date_obj.strftime("%d-%m-%Y")
    cache = load_price_cache()
    cache_key = f"{asset_clean}_{d_str}"

    if cache_key in cache:
        return float(cache[cache_key])

    # 2. CoinGecko Mapping
    asset_map = {
        "ETH": "ethereum", "BTC": "bitcoin", "POL": "polygon-ecosystem-token",
        "BNB": "binancecoin", "ARB": "arbitrum", "OP": "optimism", "WETH": "ethereum",
        "SOL": "solana", "MATIC": "matic-network", "AVAX": "avalanche-2", "DOT": "polkadot",
        "LINK": "chainlink", "UNI": "uniswap", "AAVE": "aave", "DAI": "dai",
        "ZCHF": "cryptofranc", "BCH": "bitcoin-cash", "HBAR": "hedera-hashgraph",
        "TWT": "trust-wallet-token", "ME": "magic-eden", "ORDER": "orderly-network",
        "IP": "story-ip", "AUNT": "auntie-whale"
    }

    cg_id = asset_map.get(asset_clean, asset_clean.lower())
    url_cg = f"https://api.coingecko.com/api/v3/coins/{cg_id}/history?date={d_str}&localization=false"

    try:
        time.sleep(1.2)
        res = requests.get(url_cg, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "market_data" in data:
                price = float(data["market_data"]["current_price"]["eur"])
                cache[cache_key] = price
                save_price_cache(cache)
                return price
    except: pass

    # 3. Fallback DefiLlama
    try:
        ts = int(date_obj.timestamp())
        url_llama = f"https://coins.llama.fi/prices/historical/{ts}/coingecko:{cg_id}?searchWidth=12h"
        res = requests.get(url_llama, timeout=10)
        if res.status_code == 200:
            coins = res.json().get("coins", {})
            if coins:
                price_usd = float(next(iter(coins.values()))["price"])
                rate = get_fiat_rate("USD", date_obj)
                price = price_usd * rate
                cache[cache_key] = price
                save_price_cache(cache)
                return price
    except: pass

    return 0.0

def get_portfolio_snapshot(journal, target_date):
    # 1. Chargement des référentiels
    pos_labels = load_position_labels()
    protocol_addrs = set(pos_labels.keys())
    my_accounts = set(journal["Account"].dropna().unique())

    # NEW: Include Manual Positions from all years up to target_date
    manual_all = []
    target_year = target_date.year
    for y in range(2020, target_year + 1):
        p_path = os.path.join(EXPORT_BASE_DIR, str(y), f"manual_positions_{y}.csv")
        if os.path.exists(p_path):
            try:
                tmp_m = pd_read_csv_safe(p_path)
                tmp_m["Date"] = pd.to_datetime(tmp_m["Date"], utc=True, errors="coerce")
                # Filter by date
                manual_all.append(tmp_m[tmp_m["Date"] <= target_date])
            except: pass

    df_manual_cumul = pd.concat(manual_all) if manual_all else pd.DataFrame()

    # Pre-calculate mapping for audit display
    def get_location(cp_raw):
        if cp_raw in protocol_addrs:
            return pos_labels[cp_raw]
        return "Wallet"

    # 2. Filtrage de base (Exclude Spam and manual duplicates)
    df = journal[
        (journal["Status"] != "Spam") &
        (journal.get("Category", "") != "Doublon à ignorer") &
        (journal["Asset"] != "EUR") &
        (journal["Date"] <= target_date)
    ].copy()

    if df.empty: return pd.DataFrame(), 0.0

    # 3. Identification des flux internes (qui ne changent pas la VGP globale)
    # Un flux est interne si :
    # - La contrepartie est un de mes comptes OU un protocole identifié
    # AND
    # - La catégorie est 'Transfert Interne' ou 'A vérifier' (par défaut pour les flux techniques)
    def is_vgp_neutral(row):
        cp_raw = resolve_raw_addr(row["Counterparty"])
        cat = str(row["Category"])

        # Si c'est un transfert entre mes wallets ou vers un protocole
        if cp_raw in my_accounts or cp_raw in protocol_addrs:
            # On neutralise seulement si c'est marqué comme transfert/technique
            # On garde si c'est un Reward, Airdrop, Frais, etc.
            if cat in ["Transfert Interne", "A vérifier", ""]:
                return True
        return False

    df["is_neutral"] = df.apply(is_vgp_neutral, axis=1)

    # On ne garde que ce qui modifie la richesse globale (Wealth-changing events)
    df_wealth = df[~df["is_neutral"]]

    # Calcul des balances consolidées (Portefeuilles + Protocoles)
    balances = df_wealth.groupby("Asset")["Amount"].sum()
    balances = balances[balances.abs() > 1e-8]

    # 5. Detail breakdown for audit (Breakdown by Location)
    details = []
    total_vgp = 0.0

    # --- FIX: COLLECT ALL ASSETS FOR PRICING ---
    # We fetch prices for every asset present in the journal up to this date,
    # not just the ones in the consolidated balance, to ensure the Audit View
    # and Wallets show correct values.
    all_assets = set(df["Asset"].unique())
    asset_prices = {a: get_price_eur(a, target_date) for a in all_assets}

    # Breakdown Logic:
    # A. Balances in Wallets (Account-based)
    local_bals = df.groupby(["Account", "Asset"])["Amount"].sum().reset_index()
    for _, row in local_bals.iterrows():
        if abs(row["Amount"]) > 1e-8:
            p = asset_prices.get(row["Asset"], 0.0)
            details.append({
                "Location": f"Wallet: {row['Account']}",
                "Asset": row["Asset"],
                "Quantité": row["Amount"],
                "Prix (EUR)": p,
                "Valeur (EUR)": row["Amount"] * p
            })

    # B. Balances in Protocols (Label-based)
    for addr, label in pos_labels.items():
        mask_prot = df["Counterparty"].fillna("").apply(resolve_raw_addr) == addr
        if mask_prot.any():
            prot_bals = df[mask_prot].groupby("Asset")["Amount"].sum().reset_index()
            for _, row in prot_bals.iterrows():
                if abs(row["Amount"]) > 1e-8:
                    p = asset_prices.get(row["Asset"], 0.0)
                    details.append({
                        "Location": f"Protocol: {label}",
                        "Asset": row["Asset"],
                        "Quantité": -row["Amount"], # Inverted
                        "Prix (EUR)": p,
                        "Valeur (EUR)": (-row["Amount"]) * p
                    })

    # C. Balances in Manual Positions (Off-chain/CEX)
    if not df_manual_cumul.empty:
        # Aggregate by asset
        man_bals = df_manual_cumul.groupby("Asset")["Quantité"].sum().reset_index()
        for _, row in man_bals.iterrows():
            if abs(row["Quantité"]) > 1e-8:
                p = get_price_eur(row["Asset"], target_date)
                details.append({
                    "Location": "Manual (Off-chain/CEX)",
                    "Asset": row["Asset"],
                    "Quantité": row["Quantité"],
                    "Prix (EUR)": p,
                    "Valeur (EUR)": row["Quantité"] * p
                })

    # Global VGP for return (Sum of all details)
    full_details = pd.DataFrame(details)
    if not full_details.empty:
        total_vgp = full_details["Valeur (EUR)"].sum()

    return full_details, total_vgp

def is_imposable_robust(val):
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI"]

# --- UI sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année à traiter", min_value=2015, max_value=2030, value=datetime.now().year)

    st.divider()
    st.subheader("🔍 Critères de détection")
    use_imposable_col = st.checkbox("Basé sur 'Imposable'", value=True, help="Détecte les lignes marquées explicitement comme imposables dans l'App 2")
    use_category_vente = st.checkbox("Basé sur 'Vente'", value=True, help="Détecte les lignes dont la catégorie contient 'Vente'")

    st.divider()
    st.info("💡 **Mode Incrémental** : Le calcul ignore les lignes ayant déjà une VGP non nulle.")

    if st.button("🗑️ Vider le cache des prix"):
        if os.path.exists(PRICE_CACHE_FILE):
            os.remove(PRICE_CACHE_FILE)
            st.success("Cache effacé.")

# --- Main logic ---
path = get_qualified_path(target_year)

if not os.path.exists(path):
    st.warning(f"📂 En attente de données : Le fichier '{os.path.basename(path)}' n'existe pas encore.")
    st.info("💡 Utilisez l'**App 2** pour synchroniser et sanctuariser vos premières données qualifiées.")
else:
    # --- Persistence Logic ---
    # We use session state to ensure UI updates after calculation
    if "journal_active" not in st.session_state or st.session_state.get("active_path") != path:
        journal = pd_read_csv_safe(path)
        journal["Date"] = pd.to_datetime(journal["Date"], utc=True, errors="coerce")
        st.session_state.journal_active = journal
        st.session_state.active_path = path

    journal = st.session_state.journal_active

    # Force numeric conversion & initialization
    for col in ["Amount", "Value ($)", "VGP (EUR)"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce").fillna(0.0)
        else:
            journal[col] = 0.0

    # --- Vérification d'Intégrité (Zéro Fallback) ---
    mask_cessions_check = (journal["Imposable"].apply(is_imposable_robust) | journal["Category"].fillna("").str.contains("Vente", case=False)) & (journal["Asset"] != "EUR") & (journal["Status"] != "Spam")
    if mask_cessions_check.any():
        # On vérifie si des cessions ont une VGP à 0
        # Maintenant sûr car la colonne est initialisée juste au-dessus
        missing_vgp_count = len(journal[mask_cessions_check & (journal["VGP (EUR)"] == 0)])
        if missing_vgp_count > 0:
            st.error(f"🚨 **Attention :** {missing_vgp_count} cessions n'ont pas encore de VGP calculée ou validée. Les rapports fiscaux seront incomplets.")
            if st.button("🔍 Résoudre les prix manquants (AppPriceFix)", use_container_width=True):
                st.info("Basculez sur l'onglet **AppPriceFix** dans le menu principal pour collecter les prix manquants.")

    # Construction du masque de détection (Exclude manual duplicates and Spam)
    mask_valid = (journal["Status"] != "Spam") & (journal.get("Category", "") != "Doublon à ignorer")
    mask_imposable = (journal["Imposable"].apply(is_imposable_robust)) & mask_valid if use_imposable_col else pd.Series(False, index=journal.index)
    mask_category = (journal["Category"].fillna("").str.contains("Vente", case=False)) & mask_valid if use_category_vente else pd.Series(False, index=journal.index)

    mask_cessions = (mask_imposable | mask_category) & (journal["Asset"] != "EUR")
    cessions_all = journal[mask_cessions].copy()

    if cessions_all.empty:
        st.warning("⚠️ Aucune cession imposable détectée avec les critères actuels.")
        with st.expander("👀 Diagnostic : Voir tout le journal (pour vérifier les colonnes 'Imposable' / 'Category')"):
            st.write("Vérifiez dans l'**App 2** que vos ventes sont bien marquées comme 'Imposable' ou 'Vente'.")
            st.dataframe(journal, use_container_width=True)
    else:
        # 1. État des lieux
        nb_total = len(cessions_all)
        # We consider missing if VGP is exactly 0.0 or NaN
        mask_manquant = (cessions_all["VGP (EUR)"].isna()) | (cessions_all["VGP (EUR)"] == 0)
        nb_manquant = len(cessions_all[mask_manquant])

        st.subheader(f"📈 Suivi des VGP ({nb_total} cessions au total)")
        col1, col2 = st.columns(2)
        col1.metric("Cessions identifiées", nb_total)

        # Real-time counter logic: we use the session state directly for the counter
        col2.metric("VGP à calculer", nb_manquant, delta=-nb_manquant, delta_color="inverse")

        # 2. Boutons d'action
        if nb_manquant > 0:
            with st.expander("🔍 Voir les cessions sans VGP"):
                st.write(cessions_all[mask_manquant][["Date", "Asset", "Amount"]])

            if st.button("🚀 Lancer le calcul automatique (Incrémental)", type="primary", use_container_width=True):
                pbar = st.progress(0)
                # On ne calcule que pour les manquants
                to_calc = cessions_all[cessions_all["VGP (EUR)"] <= 0]

                for idx, (i, row) in enumerate(to_calc.iterrows()):
                    _, vgp_val = get_portfolio_snapshot(journal, row["Date"])
                    journal.at[i, "VGP (EUR)"] = vgp_val
                    pbar.progress((idx + 1) / len(to_calc))

                st.session_state.journal_active = journal
                st.success("Calcul incrémental terminé.")
                st.rerun()

        # 3. Édition manuelle et Contrôle
        st.divider()
        st.subheader("📋 Liste des Cessions & Contrôle des VGP")
        st.info("Vous pouvez modifier directement les valeurs VGP dans le tableau ci-dessous.")

        # On affiche uniquement les cessions pour édition
        # Type safety pour editor
        display_cols = ["Date", "Account", "Asset", "Amount", "Value ($)", "VGP (EUR)", "Tx Hash"]
        edit_df = journal[mask_cessions][display_cols].copy()
        for c in ["Account", "Asset", "Tx Hash"]:
            edit_df[c] = edit_df[c].fillna("").astype(str)

        edited_cessions = st.data_editor(
            edit_df,
            column_config={
                "VGP (EUR)": st.column_config.NumberColumn("VGP (EUR)", format="%.2f", help="Valeur totale du portefeuille à cette date"),
                "Date": st.column_config.DatetimeColumn(disabled=True),
                "Amount": st.column_config.NumberColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
            },
            use_container_width=True,
            key="vgp_editor"
        )

        # Injection des modifs manuelles dans le journal principal
        if st.button("💾 Sanctuariser les VGP (Enregistrer sur disque)", use_container_width=True):
            journal.loc[mask_cessions, "VGP (EUR)"] = edited_cessions["VGP (EUR)"].values
            journal.to_csv(path, index=False, encoding="utf-8-sig")
            st.success(f"Journal mis à jour avec les VGP dans {path}")
            st.balloons()

        # 4. Audit détaillé
        st.divider()
        st.subheader("🔍 Audit : Détail du Portefeuille à une Date")
        selected_date = st.selectbox("Choisir une date de cession pour voir le détail", options=sorted(cessions_all["Date"].unique(), reverse=True))

        if selected_date:
            snapshot_df, total_val = get_portfolio_snapshot(journal, selected_date)
            if not snapshot_df.empty:
                st.write(f"Composition du portefeuille au **{selected_date}** :")

                # Highlight 0 prices
                zero_prices = snapshot_df[snapshot_df["Prix (EUR)"] == 0]
                if not zero_prices.empty:
                    st.warning(f"⚠️ {len(zero_prices)} actifs n'ont pas pu être valorisés automatiquement (Prix = 0).")

                # Interactive Editor for Audit
                ed_snapshot = st.data_editor(
                    snapshot_df,
                    column_config={
                        "Prix (EUR)": st.column_config.NumberColumn("Prix (EUR)", format="%.4f €"),
                        "Valeur (EUR)": st.column_config.NumberColumn("Valeur (EUR)", format="%.2f €", disabled=True),
                        "Quantité": st.column_config.NumberColumn(format="%.6f", disabled=True),
                        "Asset": st.column_config.TextColumn(disabled=True),
                        "Location": st.column_config.TextColumn(disabled=True),
                    },
                    use_container_width=True,
                    key=f"audit_ed_{selected_date}"
                )

                # Recalculate Total with manual edits
                ed_snapshot["Valeur (EUR)"] = ed_snapshot["Quantité"] * ed_snapshot["Prix (EUR)"].fillna(0.0)
                new_total = ed_snapshot["Valeur (EUR)"].sum()
                st.metric("VGP Totale Corrigée", f"{new_total:,.2f} €")

                if st.button("💾 Enregistrer ces prix dans le cache"):
                    cache = load_price_cache()
                    d_str = selected_date.strftime("%d-%m-%Y")
                    count = 0
                    for _, r in ed_snapshot.iterrows():
                        a_clean = unicodedata.normalize('NFKC', str(r["Asset"])).upper().strip()
                        cache[f"{a_clean}_{d_str}"] = float(r["Prix (EUR)"])
                        count += 1
                    save_price_cache(cache)
                    st.success(f"{count} prix enregistrés. Relancez le calcul global pour appliquer.")

            else:
                st.warning("Aucun historique trouvé pour cette date.")

st.sidebar.divider()
st.sidebar.caption("Calculateur VGP Pro v2.0 - app2VGP")
