import os
import time
import json
import pandas as pd
import streamlit as st
from datetime import datetime

# --- Configuration ---
st.set_page_config(page_title="Jules Crypto - Qualification (app2)", layout="wide")
st.title("⚖️ Qualification & Nettoyage (Step 2)")

EXPORT_BASE_DIR = "sanctuarisation"
SPAM_FILE = "spam_blacklist.json"
POSITIONS_FILE = "position_labels.json"

# Schema Unifié
COLUMNS = [
    "Date", "Account", "Counterparty", "Asset", "Amount",
    "Value ($)", "Network", "Tx Hash", "Source Type",
    "Category", "Status", "Imposable"
]

# --- Helpers ---
def is_imposable_robust(val):
    """Robust boolean detection for various CSV formats."""
    if pd.isna(val): return False
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI", "YES", "OUI"]

def resolve_raw_addr(addr_str):
    if "(" in str(addr_str) and ")" in str(addr_str):
        # Extract content between parentheses
        return str(addr_str).split("(")[-1].split(")")[0].strip().lower()
    return str(addr_str).strip().lower()

def load_spam_list():
    if os.path.exists(SPAM_FILE):
        try:
            with open(SPAM_FILE, "r", encoding="utf-8", errors="replace") as f:
                return set(json.load(f))
        except: return set()
    return set()

def save_spam_list(spam_set):
    with open(SPAM_FILE, "w", encoding="utf-8") as f:
        json.dump(list(spam_set), f)

def load_position_labels():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)
        except: return {}
    return {}

def save_position_labels(labels_dict):
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(labels_dict, f, indent=4)

def get_qualified_path(year):
    return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")

# --- Engine: Merging & Cleaning ---
def apply_position_labels(df):
    """Remplace l'adresse Counterparty par 'Label (0x...)' si un mapping existe."""
    if df.empty: return df
    labels = load_position_labels()
    if not labels: return df

    def format_cp(cp_str):
        raw = resolve_raw_addr(cp_str)
        if raw in labels:
            return f"{labels[raw]} ({raw})"
        return cp_str

    df["Counterparty"] = df["Counterparty"].apply(format_cp)
    return df

def pd_read_csv_safe(path):
    """Robust CSV reading for Windows with encoding fallbacks."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except:
        try:
            return pd.read_csv(path, encoding="latin-1")
        except:
            return pd.read_csv(path, encoding="utf-8", errors="replace")

def merge_raw_data(year):
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir):
        return pd.DataFrame(columns=COLUMNS)

    all_rows = []
    spam_list = load_spam_list()

    # 1. Load Manual Registry (app0)
    # 1a. Fiat
    fiat_path = os.path.join(year_dir, f"manual_fiat_{year}.csv")
    if os.path.exists(fiat_path) and os.path.getsize(fiat_path) > 0:
        try:
            df_fiat = pd_read_csv_safe(fiat_path)
            for _, r in df_fiat.iterrows():
                m_eur = float(r.get("Montant EUR", 0.0))
                qty_asset = float(r.get("Quantité", 0.0))
                asset_name = str(r.get("Asset", "EUR")).upper()
                f_type = str(r.get("Type", ""))

                # Leg EUR (never imposable)
                all_rows.append({
                    "Date": r.get("Date"),
                    "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))),
                    "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))),
                    "Asset": "EUR",
                    "Amount": m_eur if "Vente" in f_type else -m_eur,
                    "Value ($)": (m_eur if "Vente" in f_type else -m_eur) / 0.92,
                    "Network": "Fiat",
                    "Tx Hash": str(r.get("Tx Hash", "")),
                    "Source Type": "Fiat",
                    "Category": "Vente (Fiat)" if "Vente" in f_type else ("Achat (Fiat)" if "Achat" in f_type else "Mouvement Fiat"),
                    "Status": "Valide",
                    "Imposable": False
                })

                # Leg Crypto
                if asset_name != "EUR" and asset_name != "NAN" and qty_asset > 0:
                    is_imp = is_imposable_robust(r.get("Imposable"))
                    all_rows.append({
                        "Date": r.get("Date"),
                        "Account": str(r.get("Account", r.get("Compte/Label", "Manual"))),
                        "Counterparty": str(r.get("Counterparty", r.get("Plateforme", "Bank"))),
                        "Asset": asset_name,
                        "Amount": qty_asset if "Achat" in f_type else -qty_asset,
                        "Value ($)": m_eur / 0.92,
                        "Network": "Fiat",
                        "Tx Hash": str(r.get("Tx Hash", "")),
                        "Source Type": "Fiat-to-Crypto",
                        "Category": "Achat" if "Achat" in f_type else "Vente",
                        "Status": "Valide",
                        "Imposable": is_imp
                    })
        except Exception: pass

    # 1b. Manual Swaps & Transfers
    swap_path = os.path.join(year_dir, f"manual_swaps_{year}.csv")
    if os.path.exists(swap_path) and os.path.getsize(swap_path) > 0:
        try:
            df_swap = pd_read_csv_safe(swap_path)
            for _, r in df_swap.iterrows():
                is_imp = is_imposable_robust(r.get("Imposable", False))
                all_rows.append({
                    "Date": r.get("Date"),
                    "Account": str(r.get("Account", "")),
                    "Counterparty": str(r.get("Counterparty", "")),
                    "Asset": str(r.get("Asset", "")),
                    "Amount": float(r.get("Amount", 0.0)),
                    "Value ($)": 0.0,
                    "Network": "Manual",
                    "Tx Hash": str(r.get("Tx Hash", "")),
                    "Source Type": "Manual",
                    "Category": "Transfert Interne" if "Transfert" in str(r.get("Type")) else "Swap",
                    "Status": "Valide",
                    "Imposable": is_imp
                })
        except Exception: pass

    # 2. Load Blockchain Txs (app.py)
    files = os.listdir(year_dir)
    for f in files:
        f_path = os.path.join(year_dir, f)
        file_addr = ""
        parts = f.split("_")
        for p in parts:
            if p.startswith("0x") and len(p) >= 40:
                file_addr = p.lower()
                break

        if f.startswith("raw_transactions_") and os.path.getsize(f_path) > 0:
            try:
                df = pd_read_csv_safe(f_path)
                for _, r in df.iterrows():
                    f_addr_full = str(r.get("From", ""))
                    t_addr_full = str(r.get("To", ""))
                    f_addr = resolve_raw_addr(f_addr_full)
                    acc_low = str(r.get("Account", "")).lower()
                    if not acc_low or acc_low in ["nan", "0x..."]: acc_low = file_addr if file_addr else "unknown"

                    cp = str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = t_addr_full if f_addr == acc_low else f_addr_full

                    amount = float(r.get("Value ETH", 0.0))
                    if f_addr == acc_low: amount = -amount

                    status = "Spam" if (resolve_raw_addr(cp) in spam_list or str(r.get("Chain", "")).lower() in spam_list) else "A vérifier"
                    all_rows.append({
                        "Date": r.get("Date"), "Account": acc_low, "Counterparty": cp, "Asset": r.get("Chain", "ETH"),
                        "Amount": amount, "Value ($)": float(r.get("Value ($)") or 0.0), "Network": r.get("Chain"),
                        "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Native",
                        "Category": "Transfert Interne" if "Discovery" in str(r.get("Type")) else "A vérifier",
                        "Status": status, "Imposable": is_imposable_robust(r.get("Imposable", False))
                    })
            except Exception: pass

        if f.startswith("raw_token_transfers_") and os.path.getsize(f_path) > 0:
            try:
                df = pd_read_csv_safe(f_path)
                for _, r in df.iterrows():
                    f_addr_full = str(r.get("From", ""))
                    f_addr = resolve_raw_addr(f_addr_full)
                    acc_low = str(r.get("Account", "")).lower()
                    if not acc_low or acc_low in ["nan", "0x..."]: acc_low = file_addr if file_addr else "unknown"

                    cp = str(r.get("Counterparty", ""))
                    if not cp or cp == "nan": cp = str(r.get("To", "")) if f_addr == acc_low else f_addr_full

                    amount = float(r.get("Value", 0.0))
                    if f_addr == acc_low: amount = -amount

                    status = "Spam" if (resolve_raw_addr(cp) in spam_list or str(r.get("Token", "")).lower() in spam_list) else "A vérifier"
                    all_rows.append({
                        "Date": r.get("Date"), "Account": acc_low, "Counterparty": cp, "Asset": r.get("Token"),
                        "Amount": amount, "Value ($)": float(r.get("Value ($)") or 0.0), "Network": r.get("Chain"),
                        "Tx Hash": str(r.get("Tx Hash", "")), "Source Type": "Token",
                        "Category": r.get("Category", "A vérifier"), "Status": status, "Imposable": is_imposable_robust(r.get("Imposable", False))
                    })
            except Exception: pass

    df_final = pd.DataFrame(all_rows)
    if not df_final.empty:
        df_final["Date"] = pd.to_datetime(df_final["Date"], utc=True, errors="coerce", format="ISO8601")

        # --- SMART DEDUPLICATION ---
        manual_mask = df_final["Source Type"].isin(["Fiat", "Fiat-to-Crypto", "Manual", "Manual Swap", "Manual Transfer"])
        df_manual = df_final[manual_mask].copy()
        df_harvested = df_final[~manual_mask].copy()

        if not df_manual.empty and not df_harvested.empty:
            # Normalize for matching
            df_harvested["_acc"] = df_harvested["Account"].astype(str).str.lower()
            df_harvested["_asset"] = df_harvested["Asset"].astype(str).str.upper()
            df_harvested["_day"] = df_harvested["Date"].dt.date
            df_harvested["_amt"] = df_harvested["Amount"].abs().round(8)

            harvest_ref = df_harvested.drop_duplicates(subset=["_day", "_asset", "_amt", "_acc"])

            def find_match(row):
                tx_h = str(row.get("Tx Hash", ""))
                if tx_h and not tx_h.startswith(("BLP-", "NVL-", "OUT-", "IN-", "FEE-")) and tx_h != "nan":
                    return row

                day = pd.to_datetime(row["Date"]).date()
                amt = abs(float(row["Amount"]))
                asset = str(row["Asset"]).upper()
                acc = str(row["Account"]).lower()

                matches = harvest_ref[(harvest_ref["_day"] == day) & (harvest_ref["_asset"] == asset) &
                                      (harvest_ref["_amt"] == round(amt, 8)) & (harvest_ref["_acc"] == acc)]

                if not matches.empty:
                    m = matches.iloc[0]
                    row["Tx Hash"] = m["Tx Hash"]
                    row["Date"] = m["Date"]
                    if pd.isna(row.get("Value ($)")) or row.get("Value ($)") == 0: row["Value ($)"] = m.get("Value ($)", 0.0)
                    if pd.isna(row.get("Network")) or row["Network"] == "Fiat": row["Network"] = m.get("Network", "Fiat")
                return row

            df_manual = df_manual.apply(find_match, axis=1)
            df_harvested = df_harvested.drop(columns=["_acc", "_asset", "_day", "_amt"])
            df_final = pd.concat([df_manual, df_harvested])

        # Priority Deduplication
        df_final["_pri"] = df_final["Source Type"].apply(lambda x: 0 if x in ["Native", "Token"] else 1)
        df_final["_d"] = df_final["Date"].dt.date
        df_final = df_final.sort_values(["Date", "_pri"], ascending=[False, False])
        df_final = df_final.drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account", "_d"], keep="first")
        df_final = df_final.drop(columns=["_pri", "_d"])
        df_final = apply_position_labels(df_final)

    return df_final

# --- Logic ---
def sync_data(year):
    qual_path = get_qualified_path(year)
    new_df = merge_raw_data(year)

    if os.path.exists(qual_path) and os.path.getsize(qual_path) > 0:
        try:
            old_df = pd_read_csv_safe(qual_path)
            old_df["Date"] = pd.to_datetime(old_df["Date"], utc=True, errors="coerce", format="ISO8601")

            # --- AUTO-REPAIR : Nettoyage des lignes Fiat corrompues (v1 legacy) ---
            # Si Source Type est 'Fiat' mais Asset n'est pas 'EUR', c'est une erreur de transposition ancienne.
            if not old_df.empty and "Source Type" in old_df.columns:
                corrupted_mask = (old_df["Source Type"] == "Fiat") & (old_df["Asset"] != "EUR")
                if corrupted_mask.any():
                    old_df = old_df[~corrupted_mask]
                    st.info(f"🔧 {corrupted_mask.sum()} lignes Fiat corrompues nettoyées du journal historique.")

            # Force numeric
            for col in ["Amount", "Value ($)"]:
                if col in old_df.columns:
                    old_df[col] = pd.to_numeric(old_df[col], errors='coerce').fillna(0.0)
        except Exception:
            old_df = pd.DataFrame(columns=COLUMNS)

        # Fusion : On privilégie old_df (données déjà qualifiées) sur new_df (données brutes).
        # On utilise keep="first" avec old_df en premier pour ne pas écraser le travail de qualification
        # déjà effectué par l'utilisateur.
        # Dédoublonnage incluant Amount pour éviter de fusionner des transactions différentes sans hash.
        combined = pd.concat([old_df, new_df]).drop_duplicates(subset=["Tx Hash", "Asset", "Account", "Amount"], keep="first")

        if not combined.empty and "Date" in combined.columns:
            combined = combined.sort_values("Date", ascending=False)
            # Re-appliquer les labels si de nouveaux mappings ont été créés
            combined = apply_position_labels(combined)
            st.session_state.journal_qualifie = combined
        else:
            st.session_state.journal_qualifie = combined
    else:
        if not new_df.empty and "Date" in new_df.columns:
            st.session_state.journal_qualifie = new_df.sort_values("Date", ascending=False)
        else:
            st.session_state.journal_qualifie = new_df

# --- UI Sidebar ---
with st.sidebar:
    st.header("⚙️ Paramètres")
    target_year = st.number_input("Année de traitement", min_value=2015, max_value=2030, value=datetime.now().year)

    # Initialisation data si nécessaire
    if "journal_qualifie" not in st.session_state or st.session_state.get("last_year") != target_year:
        sync_data(target_year)
        st.session_state.last_year = target_year

    if st.button("🏷️ Appliquer les Labels de Protocoles", use_container_width=True):
        if "journal_qualifie" in st.session_state:
            st.session_state.journal_qualifie = apply_position_labels(st.session_state.journal_qualifie)
            st.success("Labels appliqués au journal en mémoire.")
            st.rerun()

    st.divider()
    if st.button("🔄 Actualiser & Fusionner les Brutes", use_container_width=True):
        sync_data(target_year)
        st.success("Fusion terminée.")

    if st.button("🚨 Réinitialiser depuis les Brutes", use_container_width=True, help="ATTENTION : Écrase tout le travail de qualification effectué pour repartir du journal brut."):
        new_df = merge_raw_data(target_year)
        if not new_df.empty:
            st.session_state.journal_qualifie = new_df.sort_values("Date", ascending=False)
            st.warning("Journal réinitialisé. N'oubliez pas de Sanctuariser pour enregistrer sur disque.")
            st.rerun()

    if st.button("🛡️ Nettoyer les Spams (Auto)", use_container_width=True):
        if "journal_qualifie" in st.session_state:
            spam_list = load_spam_list()
            df = st.session_state.journal_qualifie
            # Nettoyage par adresse (Contrepartie) OU par nom d'Asset
            mask_cp = df["Counterparty"].fillna("").str.lower().apply(resolve_raw_addr).isin(spam_list)
            mask_asset = df["Asset"].fillna("").str.lower().isin(spam_list)
            df.loc[mask_cp | mask_asset, "Status"] = "Spam"
            st.session_state.journal_qualifie = df
            st.rerun()

    st.divider()
    st.header("📊 Filtres & Regroupement")
    if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
        df_for_filters = st.session_state.journal_qualifie

        # Filtres Multiples
        # On force en string et on retire les nan/None pour éviter le TypeError dans sorted()
        def get_safe_options(df, col):
            return sorted([str(x) for x in df[col].dropna().unique()])

        f_asset = st.multiselect("Filtrer par Asset", options=get_safe_options(df_for_filters, "Asset"))
        f_acc = st.multiselect("Filtrer par Compte (Account)", options=get_safe_options(df_for_filters, "Account"))
        f_status = st.multiselect("Filtrer par Statut", options=get_safe_options(df_for_filters, "Status"), default=[])

        f_cp_search = st.text_input("Filtrer par Counterparty (0x...)", "")

        st.divider()
        st.header("🔃 Tri du Journal")
        sort_cols = list(df_for_filters.columns)
        default_sort = sort_cols.index("Date") if "Date" in sort_cols else 0
        sort_by = st.selectbox("Trier par", sort_cols, index=default_sort)
        sort_order = st.radio("Sens du tri", ["Décroissant (Z-A)", "Croissant (A-Z)"], index=0)

        if st.button("⚡ Appliquer Filtres & Tri"):
            # Le tri est appliqué à la session state
            df = st.session_state.journal_qualifie
            df = df.sort_values(by=sort_by, ascending=(sort_order == "Croissant (A-Z)"))
            st.session_state.journal_qualifie = df
            # Les filtres seront appliqués à l'affichage (voir Main App)
            st.rerun()

    with st.expander("🛡️ Anti-Spam & Actions de Masse"):
        spam_list = load_spam_list()
        st.write(f"Total Blacklist : **{len(spam_list)}**")

        if "journal_qualifie" in st.session_state and not st.session_state.journal_qualifie.empty:
            df = st.session_state.journal_qualifie

            # --- 1. SELECTION ---
            st.subheader("📦 Sélection")
            assets_to_mvt = st.multiselect("Assets concernés", options=sorted([str(x) for x in df["Asset"].dropna().unique()]))
            cp_to_mvt = st.multiselect("Contreparties (adresses)", options=sorted([str(x) for x in df["Counterparty"].dropna().unique()]))

            # --- 2. ACTION ---
            st.subheader("⚡ Action")
            target_status = st.selectbox("Nouveau Statut", ["À vérifier", "Valide", "Spam"])

            if st.button("🚀 Appliquer à la sélection"):
                if not assets_to_mvt and not cp_to_mvt:
                    st.warning("Choisissez au moins un asset ou une adresse.")
                else:
                    # Préparation des listes
                    sel_low = [x.lower() for x in (assets_to_mvt + cp_to_mvt)]

                    # Mise à jour de la Blacklist
                    if target_status == "Spam":
                        for item in sel_low:
                            if item: spam_list.add(item)
                    else:
                        for item in sel_low:
                            if item in spam_list: spam_list.remove(item)
                    save_spam_list(spam_list)

                    # Mise à jour du Journal en mémoire
                    mask_asset = df["Asset"].fillna("").str.lower().isin(sel_low)
                    mask_cp = df["Counterparty"].fillna("").str.lower().apply(resolve_raw_addr).isin(sel_low)
                    df.loc[mask_asset | mask_cp, "Status"] = target_status

                    st.success(f"Action effectuée sur la sélection. Journal et Blacklist mis à jour.")
                    st.rerun()

        # --- 3. GESTION INDIVIDUELLE ---
        st.divider()
        st.subheader("🔎 Gestion Blacklist Globale")
        new_spam = st.text_input("Ajout direct (nom ou 0x...)", placeholder="ex: ELON", key="input_new_spam")
        if st.button("🚫 Bannir définitivement"):
            if new_spam:
                spam_list.add(new_spam.strip().lower())
                save_spam_list(spam_list)
                st.success(f"'{new_spam}' ajouté.")
                st.rerun()

        if spam_list:
            to_remove = st.multiselect("Retirer manuellement", options=sorted(list(spam_list)))
            if st.button("✅ Supprimer de la liste noire"):
                for item in to_remove: spam_list.remove(item)
                save_spam_list(spam_list)
                st.rerun()

    with st.expander("🏦 Mapping des Protocoles (Positions)"):
        pos_labels = load_position_labels()
        st.write(f"Protocoles identifiés : **{len(pos_labels)}**")

        st.info("Associez une adresse à un nom de protocole (ex: Staking ETH, Compound Vault) pour l'inclure dans la VGP.")

        new_addr = st.text_input("Adresse du contrat/vault", placeholder="0x...")
        new_label = st.text_input("Nom du protocole / Label", placeholder="ex: Staking Lido")

        if st.button("➕ Ajouter la Position"):
            if new_addr and new_label:
                addr_clean = resolve_raw_addr(new_addr)
                pos_labels[addr_clean] = new_label
                save_position_labels(pos_labels)
                st.success(f"Position '{new_label}' enregistrée.")
                st.rerun()

        if pos_labels:
            st.divider()
            # Table simple pour voir/supprimer
            pos_df = pd.DataFrame(list(pos_labels.items()), columns=["Adresse", "Label"])
            st.dataframe(pos_df, use_container_width=True, hide_index=True)

            to_del = st.selectbox("Supprimer une position", [""] + sorted(list(pos_labels.keys())))
            if to_del and st.button("🗑️ Supprimer"):
                del pos_labels[to_del]
                save_position_labels(pos_labels)
                st.rerun()

# --- Main App ---
@st.fragment
def main_journal_fragment():
    st.subheader(f"📋 Journal de Qualification {target_year}")
    if "journal_qualifie" not in st.session_state or st.session_state.journal_qualifie.empty:
        st.warning("Aucune donnée trouvée. Utilisez 'Actualiser & Fusionner' dans le sidebar.")
        return

    # Application des filtres d'affichage (sans modifier la session state)
    df_display = st.session_state.journal_qualifie.copy()

    if f_asset:
        df_display = df_display[df_display["Asset"].isin(f_asset)]
    if f_acc:
        df_display = df_display[df_display["Account"].isin(f_acc)]
    if f_status:
        df_display = df_display[df_display["Status"].isin(f_status)]
    if f_cp_search:
        df_display = df_display[df_display["Counterparty"].astype(str).str.contains(f_cp_search, case=False, na=False)]

    # 1. Barre d'outils
    col_t1, col_t2, col_save = st.columns([1.5, 0.5, 1])

    if col_t1.button("🔍 Détecter Transferts Internes", use_container_width=True):
        df = st.session_state.journal_qualifie

        # 1. Detection by Tx Hash (existing)
        hashes = df[df["Tx Hash"].duplicated(keep=False)]["Tx Hash"].unique()
        count_h = 0
        for h in hashes:
            if not h or len(str(h)) < 10: continue
            mask = df["Tx Hash"] == h
            if len(df[mask]) >= 2:
                df.loc[mask, "Category"] = "Transfert Interne"
                df.loc[mask, "Status"] = "Valide"
                count_h += 1

        # 2. Detection by Owned Account/Counterparty (Cross-Account)
        my_accounts = set(df["Account"].astype(str).str.lower().unique())
        count_ca = 0

        def is_internal(cp_str):
            raw = resolve_raw_addr(cp_str)
            return raw in my_accounts

        mask_internal = df["Counterparty"].fillna("").apply(is_internal)
        if mask_internal.any():
            df.loc[mask_internal, "Category"] = "Transfert Interne"
            df.loc[mask_internal, "Status"] = "Valide"
            count_ca = mask_internal.sum()

        st.session_state.journal_qualifie = df
        st.success(f"Transferts identifiés : {count_h} par Hash, {count_ca} par Compte Propriétaire.")
        st.rerun()

    # 2. Data Editor
    categories = ["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense Staking", "Airdrop", "Frais", "Perte/Vol", "Autre"]
    statuses = ["A vérifier", "Valide", "Spam"]

    # Type safety
    for col in ["Account", "Counterparty", "Asset", "Tx Hash", "Source Type", "Category", "Status"]:
        if col in st.session_state.journal_qualifie.columns:
            st.session_state.journal_qualifie[col] = st.session_state.journal_qualifie[col].fillna("").astype(str)

    edited_df = st.data_editor(
        df_display,
        column_config={
            "Category": st.column_config.SelectboxColumn("Catégorie", options=categories, required=True),
            "Status": st.column_config.SelectboxColumn("Statut", options=statuses, required=True),
            "Imposable": st.column_config.CheckboxColumn("Imposable ?"),
            "Date": st.column_config.DatetimeColumn(disabled=True),
            "Account": st.column_config.TextColumn(disabled=True),
            "Tx Hash": st.column_config.TextColumn(disabled=True),
            "Amount": st.column_config.NumberColumn(format="%.6f", disabled=True),
        },
        use_container_width=True,
        num_rows="dynamic",
        key="qual_editor"
    )

    # Sync back from editor to session state immediately?
    # Streamlit fragments handle this well. We sync only on explicit save button.

    # 3. Save Logic
    if st.button(f"💾 Sanctuariser la Sélection {target_year}", type="primary", use_container_width=True):
        # On fusionne les modifications du data_editor (filtré) dans la session_state (complète)
        # Pour simplifier, si on est en mode filtré, on prévient l'utilisateur
        if f_asset or f_acc or f_status:
            st.warning("⚠️ Attention: Vous êtes en mode filtré. Seules les lignes visibles seront mises à jour dans la session state.")

        # Mise à jour de la session state avec les lignes éditées
        full_df = st.session_state.journal_qualifie.copy()
        # On utilise le Tx Hash + Asset + Amount + Account comme clé de fusion
        # (C'est notre subset de dédoublonnage)
        # On remplace les lignes de full_df par celles de edited_df
        # Pour faire simple ici, on écrase tout le journal par edited_df si non filtré
        if not (f_asset or f_acc or f_status):
            st.session_state.journal_qualifie = edited_df
        else:
            # Fusion complexe si filtré : on retire les anciennes lignes filtrées et on ajoute les nouvelles
            mask_filtered = pd.Series(True, index=full_df.index)
            if f_asset: mask_filtered &= full_df["Asset"].isin(f_asset)
            if f_acc: mask_filtered &= full_df["Account"].isin(f_acc)
            if f_status: mask_filtered &= full_df["Status"].isin(f_status)

            non_filtered_df = full_df[~mask_filtered]
            st.session_state.journal_qualifie = pd.concat([non_filtered_df, edited_df]).sort_values("Date", ascending=False)

        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)

        # SUPPRESSION de la propagation automatique asset/adresse vers la blacklist globale.
        # Seul un bannissement via la Sidebar est définitif pour le futur.

        st.session_state.journal_qualifie.to_csv(get_qualified_path(target_year), index=False, encoding="utf-8-sig")
        st.balloons()
        st.success(f"Journal qualifié enregistré dans {year_dir}")

main_journal_fragment()

st.sidebar.divider()
st.sidebar.caption("Qualification v1.0 - app2")
