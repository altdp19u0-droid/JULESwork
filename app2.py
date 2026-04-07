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

# Schema Unifié
COLUMNS = [
    "Date", "Account", "Counterparty", "Asset", "Amount",
    "Value ($)", "Network", "Tx Hash", "Source Type",
    "Category", "Status", "Imposable"
]

# --- Helpers ---
def load_spam_list():
    if os.path.exists(SPAM_FILE):
        with open(SPAM_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_spam_list(spam_set):
    with open(SPAM_FILE, "w") as f:
        json.dump(list(spam_set), f)

def get_qualified_path(year):
    return os.path.join(EXPORT_BASE_DIR, str(year), f"qualified_journal_{year}.csv")

# --- Engine: Merging & Cleaning ---
def merge_raw_data(year):
    year_dir = os.path.join(EXPORT_BASE_DIR, str(year))
    if not os.path.exists(year_dir):
        return pd.DataFrame(columns=COLUMNS)

    all_rows = []
    spam_list = load_spam_list()

    # 1. Load Manual Fiat (app0)
    fiat_path = os.path.join(year_dir, f"manual_fiat_{year}.csv")
    if os.path.exists(fiat_path) and os.path.getsize(fiat_path) > 0:
        try:
            df_fiat = pd.read_csv(fiat_path)
        except Exception:
            df_fiat = pd.DataFrame()

        for _, r in df_fiat.iterrows():
            all_rows.append({
                "Date": r.get("Date"),
                "Account": r.get("Account", r.get("Compte/Label", "Manual")),
                "Counterparty": r.get("Counterparty", r.get("Plateforme", "Bank")),
                "Asset": r.get("Asset", "EUR"),
                "Amount": float(r.get("Montant EUR", 0.0)) if "Vente" in str(r.get("Type")) else -float(r.get("Montant EUR", 0.0)),
                "Value ($)": 0.0, # Will be handled by app3 or based on EUR rate
                "Network": "Fiat",
                "Tx Hash": r.get("Tx Hash", ""),
                "Source Type": "Fiat",
                "Category": "Achat" if "Achat" in str(r.get("Type")) else "Vente",
                "Status": "Valide",
                "Imposable": False
            })

    # 2. Load Blockchain Txs (app.py)
    files = os.listdir(year_dir)
    for f in files:
        f_path = os.path.join(year_dir, f)

        # Extraction de l'adresse du propriétaire depuis le nom du fichier si possible
        # Format attendu : raw_transactions_0xAddress_Timestamp.csv
        file_addr = ""
        parts = f.split("_")
        for p in parts:
            if p.startswith("0x") and len(p) >= 40:
                file_addr = p.lower()
                break

        if f.startswith("raw_transactions_") and os.path.getsize(f_path) > 0:
            try:
                df = pd.read_csv(f_path)
            except Exception:
                continue
            for _, r in df.iterrows():
                f_addr = str(r.get("From", "")).lower()
                t_addr = str(r.get("To", "")).lower()

                # Priorité : Colonne Account > Adresse du fichier > Placeholder
                acc_low = str(r.get("Account", "")).lower()
                if not acc_low or acc_low == "nan" or acc_low == "0x...":
                    acc_low = file_addr if file_addr else "unknown_account"

                # Priorité : Colonne Counterparty > Calcul
                cp = str(r.get("Counterparty", "")).lower()
                if not cp or cp == "nan":
                    cp = t_addr if f_addr == acc_low else f_addr

                amount = float(r.get("Value ETH", 0.0))
                # Direction relative
                if f_addr == acc_low:
                    amount = -amount

                status = "Spam" if cp in spam_list else "A vérifier"
                all_rows.append({
                    "Date": r.get("Date"),
                    "Account": acc_low,
                    "Counterparty": cp,
                    "Asset": r.get("Chain", "ETH"), # Simplified native asset detection
                    "Amount": amount,
                    "Value ($)": float(r.get("Value ($)") or 0.0),
                    "Network": r.get("Chain"),
                    "Tx Hash": r.get("Tx Hash"),
                    "Source Type": "Native",
                    "Category": "Transfert Interne" if "Discovery" in str(r.get("Type")) else "A vérifier",
                    "Status": status,
                    "Imposable": False
                })

        if f.startswith("raw_token_transfers_") and os.path.getsize(f_path) > 0:
            try:
                df = pd.read_csv(f_path)
            except Exception:
                continue
            for _, r in df.iterrows():
                f_addr = str(r.get("From", "")).lower()
                t_addr = str(r.get("To", "")).lower()

                # Résolution Account
                acc_low = str(r.get("Account", "")).lower()
                if not acc_low or acc_low == "nan" or acc_low == "0x...":
                    acc_low = file_addr if file_addr else "unknown_account"

                # Priorité : Colonne Counterparty > Calcul
                cp = str(r.get("Counterparty", "")).lower()
                if not cp or cp == "nan":
                    cp = t_addr if f_addr == acc_low else f_addr

                amount = float(r.get("Value", 0.0))
                # Direction relative
                if f_addr == acc_low:
                    amount = -amount

                status = "Spam" if cp in spam_list else "A vérifier"

                all_rows.append({
                    "Date": r.get("Date"),
                    "Account": acc_low,
                    "Counterparty": cp,
                    "Asset": r.get("Token"),
                    "Amount": amount,
                    "Value ($)": float(r.get("Value ($)") or 0.0),
                    "Network": r.get("Chain"),
                    "Tx Hash": r.get("Tx Hash"),
                    "Source Type": "Token",
                    "Category": "A vérifier",
                    "Status": status,
                    "Imposable": False
                })

    df_final = pd.DataFrame(all_rows)
    if not df_final.empty:
        df_final["Date"] = pd.to_datetime(df_final["Date"], utc=True, errors="coerce", format="ISO8601")
        # Deduplication massive sur Hash + Asset + Amount (pour éviter doublons IN/OUT d'un même scan)
        df_final = df_final.drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account"], keep="first")

    return df_final

# --- Logic ---
def sync_data(year):
    qual_path = get_qualified_path(year)
    new_df = merge_raw_data(year)

    if os.path.exists(qual_path) and os.path.getsize(qual_path) > 0:
        try:
            old_df = pd.read_csv(qual_path)
            old_df["Date"] = pd.to_datetime(old_df["Date"], utc=True, errors="coerce", format="ISO8601")
        except Exception:
            old_df = pd.DataFrame(columns=COLUMNS)
        # On fusionne en gardant les modifs manuelles de l'existant
        combined = pd.concat([new_df, old_df]).drop_duplicates(subset=["Tx Hash", "Asset", "Amount", "Account"], keep="last")
        if not combined.empty and "Date" in combined.columns:
            st.session_state.journal_qualifie = combined.sort_values("Date", ascending=False)
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

    st.divider()
    if st.button("🔄 Actualiser & Fusionner les Brutes"):
        sync_data(target_year)
        st.success("Fusion terminée.")

    if st.button("🛡️ Nettoyer les Spams (Auto)"):
        if "journal_qualifie" in st.session_state:
            spam_list = load_spam_list()
            df = st.session_state.journal_qualifie
            df.loc[df["Counterparty"].str.lower().isin(spam_list), "Status"] = "Spam"
            st.session_state.journal_qualifie = df
            st.rerun()

# --- Main App ---
if "journal_qualifie" not in st.session_state or st.session_state.get("last_year") != target_year:
    sync_data(target_year)
    st.session_state.last_year = target_year

st.subheader(f"📋 Journal de Qualification {target_year}")
if st.session_state.journal_qualifie.empty:
    st.warning("Aucune donnée trouvée. Utilisez 'Actualiser & Fusionner' dans le sidebar.")
else:
    # 1. Barre d'outils (Détection Doublons / Virements Internes)
    col_t1, col_t2, col_save = st.columns([1, 1, 1])

    if col_t1.button("🔍 Détecter Transferts Internes"):
        df = st.session_state.journal_qualifie
        # Logique: même Hash, même Asset, Montants opposés (ou proches)
        # Pour les transferts internes, le Hash est le même.
        hashes = df[df["Tx Hash"].duplicated(keep=False)]["Tx Hash"].unique()
        count = 0
        for h in hashes:
            if not h or len(str(h)) < 10: continue
            mask = df["Tx Hash"] == h
            if len(df[mask]) >= 2:
                df.loc[mask, "Category"] = "Transfert Interne"
                df.loc[mask, "Status"] = "Valide"
                count += 1
        st.session_state.journal_qualifie = df
        st.success(f"{count} transferts identifiés.")

    # 2. Data Editor
    categories = ["A vérifier", "Achat", "Vente", "Swap", "Transfert Interne", "Récompense Staking", "Airdrop", "Frais", "Perte/Vol", "Autre"]
    statuses = ["A vérifier", "Valide", "Spam"]

    edited_df = st.data_editor(
        st.session_state.journal_qualifie,
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

    # 3. Save Logic
    if st.button(f"💾 Sanctuariser la Sélection {target_year}", type="primary", use_container_width=True):
        st.session_state.journal_qualifie = edited_df
        year_dir = os.path.join(EXPORT_BASE_DIR, str(target_year))
        os.makedirs(year_dir, exist_ok=True)

        # Sauvegarde Global Spam
        spam_list = load_spam_list()
        new_spams = edited_df[edited_df["Status"] == "Spam"]["Counterparty"].dropna().unique()
        for s in new_spams:
            if str(s).startswith("0x"): spam_list.add(str(s).lower())
        save_spam_list(spam_list)

        # Sauvegarde Journal
        edited_df.to_csv(get_qualified_path(target_year), index=False)
        st.balloons()
        st.success(f"Journal qualifié enregistré dans {year_dir}")

st.sidebar.divider()
st.sidebar.caption("Qualification v1.0 - app2")
