"""
Module de qualification de légitimité, filtrage anti-spam et valorisation des soldes pour apptrait.py.
Gère la duplication sécurisée de sanctuary/ vers trait_legit/ sans altérer le sanctuaire brut.
"""
import os
import json
import re
import unicodedata
from pathlib import Path
import pandas as pd
from datetime import datetime, date

from .schema import REQUIRED_COLUMNS, enforce_sanctuary_schema
from .fx_collector import get_ecb_eur_rate, get_crypto_usd_price_defillama

TRAIT_COLUMNS = [
    "Statut_Legitimite",
    "Motif_Legitimite",
    "Masque_Traitement"
]

DEFAULT_WHITELIST = [
    "ETH", "WETH", "USDC", "USDT", "DAI", "EUR", "EURA", "EURS", "WBTC", "BTC",
    "ARB", "UNI", "LINK", "AAVE", "BNB", "MATIC", "OP", "SOL", "STETH", "RETH"
]

SPAM_PATTERNS = [
    r"http[s]?://",
    r"t\.me/",
    r"\.com\b", r"\.io\b", r"\.net\b", r"\.xyz\b", r"\.org\b", r"\.site\b", r"\.top\b", r"\.win\b",
    r"claim", r"airdrop", r"visit", r"free", r"bonus", r"voucher", r"reward", r"gift"
]

def get_legit_config_path(trait_dir: Path) -> Path:
    return trait_dir / "legitimacy_config.json"

def load_legit_config(trait_dir: Path) -> dict:
    config_path = get_legit_config_path(trait_dir)
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "whitelist": DEFAULT_WHITELIST.copy(),
        "blacklist": [],
        "manual_overrides": {} # Key: Tx_Hash or Asset -> True/False
    }

def save_legit_config(trait_dir: Path, config: dict):
    trait_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_legit_config_path(trait_dir)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def is_homoglyph_scam(text: str) -> bool:
    """Détecte les caractères Unicode non-ASCII (homoglyphes cyrilliques/lisu/arméniens)."""
    if not text or not isinstance(text, str):
        return False
    return any(ord(c) > 127 for c in text)

def normalize_token_symbol(text: str) -> str:
    """Normalise et nettoie un symbole de jeton (NFKC)."""
    if not text or not isinstance(text, str):
        return ""
    norm = unicodedata.normalize("NFKC", str(text))
    return norm.replace("\xa0", " ").strip().upper()

def is_spam_symbol(symbol: str) -> bool:
    if not symbol or not isinstance(symbol, str):
        return False
    sym_lower = symbol.lower().strip()
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, sym_lower):
            return True
    return False

def qualify_dataframe(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Applique la qualification automatique et manuelle sur un DataFrame.
    Ajoute ou met à jour : Statut_Legitimite, Motif_Legitimite, Masque_Traitement.
    """
    if df is None or df.empty:
        df_out = enforce_sanctuary_schema(None)
        for col in TRAIT_COLUMNS:
            df_out[col] = []
        return df_out

    res_df = df.copy()

    for col in TRAIT_COLUMNS:
        if col not in res_df.columns:
            if col == "Masque_Traitement":
                res_df[col] = True
            elif col == "Statut_Legitimite":
                res_df[col] = "Valide"
            else:
                res_df[col] = "Validation Auto"

    raw_wl = config.get("whitelist", DEFAULT_WHITELIST)
    raw_bl = config.get("blacklist", [])

    whitelist = [normalize_token_symbol(w) for w in raw_wl if w]
    # On isole la blacklist ASCII propre (sans homoglyphes) pour éviter qu'une entrée comme ꓴꓢƊС ne pollue l'USDC ASCII
    blacklist_ascii = [normalize_token_symbol(b) for b in raw_bl if b and not is_homoglyph_scam(b)]
    blacklist_raw = [str(b).strip().upper() for b in raw_bl if b]
    manual_overrides = config.get("manual_overrides", {})

    statuts = []
    motifs = []
    masques = []

    for idx, row in res_df.iterrows():
        tx_hash = str(row.get("Hash de la transaction blockchain", "")).replace("\xa0", " ").strip()
        asset_raw = str(row.get("Devise d'origine", "")).replace("\xa0", " ").strip().upper()
        asset_norm = normalize_token_symbol(asset_raw)
        project_raw = str(row.get("Nom du projet", "")).replace("\xa0", " ").strip()
        project_norm = normalize_token_symbol(project_raw)

        # 1. Verification surcharge manuelle par Hash
        if tx_hash and tx_hash in manual_overrides:
            is_valid = manual_overrides[tx_hash]
            statuts.append("Valide" if is_valid else "Spam / Suspect")
            motifs.append("Surcharge Manuelle Utilisateur")
            masques.append(bool(is_valid))
            continue

        # 2. Verification surcharge manuelle par Asset
        if asset_norm in manual_overrides or asset_raw in manual_overrides:
            is_valid = manual_overrides.get(asset_norm, manual_overrides.get(asset_raw))
            statuts.append("Valide" if is_valid else "Spam / Suspect")
            motifs.append(f"Surcharge Asset {asset_norm}")
            masques.append(bool(is_valid))
            continue

        # 3. DÉTECTION SPAM HOMOGLYPHE (Ex: ꓴꓢƊС / UЅDС faux token)
        if is_homoglyph_scam(asset_raw):
            statuts.append("Spam / Suspect")
            motifs.append("Faux Token (Homoglyphe Scam)")
            masques.append(False)
            continue

        # 4. PRIORITÉ ABSOLUE : Verification Whitelist (Token Authentique)
        if whitelist and len(whitelist) > 0:
            if asset_norm in whitelist:
                statuts.append("Valide")
                motifs.append("Token Whitelisted")
                masques.append(True)
                continue
            else:
                statuts.append("Spam / Suspect")
                motifs.append("Non Whitelisted")
                masques.append(False)
                continue

        # 5. Verification Blacklist (si aucune Whitelist restrictive n'est active)
        is_blacklisted = asset_norm in blacklist_ascii or asset_raw in blacklist_raw or project_norm in blacklist_ascii
        if not is_blacklisted and project_norm:
            proj_words = [w.strip() for w in re.split(r"[\s,_\-\/]+", project_norm) if w.strip()]
            is_blacklisted = any(b in proj_words for b in blacklist_ascii if b)

        if is_blacklisted:
            statuts.append("Spam / Suspect")
            motifs.append("Actif/Projet Blacklisté")
            masques.append(False)
            continue

        # 6. Détection heuristique Spam (URLs, Mots-clés)
        if is_spam_symbol(asset_raw) or is_spam_symbol(project_raw):
            statuts.append("Spam / Suspect")
            motifs.append("Pattern Spam / URL Décelé")
            masques.append(False)
            continue

        # 6. Défaut
        statuts.append("Valide")
        motifs.append("Validation Standard")
        masques.append(True)

    res_df["Devise d'origine"] = res_df["Devise d'origine"].astype(str).str.replace("\xa0", " ").str.strip().str.upper()
    res_df["Statut_Legitimite"] = statuts
    res_df["Motif_Legitimite"] = motifs
    res_df["Masque_Traitement"] = masques

    return res_df

def sync_sanctuary_to_trait_legit(sanctuary_dir: Path, trait_dir: Path, force_requalify: bool = False) -> list:
    """
    Duplique l'arborescence sanctuary/ vers trait_legit/ en appliquant les qualifications.
    Ne modifie JAMAIS sanctuary/.
    """
    saved_files = []
    if not sanctuary_dir.exists():
        return saved_files

    trait_dir.mkdir(parents=True, exist_ok=True)
    config = load_legit_config(trait_dir)

    for root, dirs, files in os.walk(sanctuary_dir):
        for file in files:
            if file.endswith(".csv"):
                src_path = Path(root) / file
                rel_path = src_path.relative_to(sanctuary_dir)
                dest_path = trait_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    df_src = pd.read_csv(src_path, encoding="utf-8-sig")
                except Exception:
                    try:
                        df_src = pd.read_csv(src_path, encoding="latin1", sep=";")
                    except Exception:
                        continue

                df_src = enforce_sanctuary_schema(df_src)

                # Si dest_path existe déjà et pas force_requalify, charger pour préserver les statuts édités
                if dest_path.exists() and not force_requalify:
                    try:
                        df_existing = pd.read_csv(dest_path, encoding="utf-8-sig")
                        if "Hash de la transaction blockchain" in df_existing.columns and "Statut_Legitimite" in df_existing.columns:
                            existing_map = df_existing.set_index("Hash de la transaction blockchain")[["Statut_Legitimite", "Motif_Legitimite", "Masque_Traitement"]].to_dict(orient="index")

                            def apply_existing(row):
                                h = str(row.get("Hash de la transaction blockchain", "")).strip()
                                if h in existing_map:
                                    row["Statut_Legitimite"] = existing_map[h]["Statut_Legitimite"]
                                    row["Motif_Legitimite"] = existing_map[h]["Motif_Legitimite"]
                                    row["Masque_Traitement"] = existing_map[h]["Masque_Traitement"]
                                return row

                            df_src = df_src.apply(apply_existing, axis=1)
                    except Exception:
                        pass

                df_qualified = qualify_dataframe(df_src, config)
                df_qualified.to_csv(dest_path, index=False, encoding="utf-8-sig")
                saved_files.append(str(dest_path))

    return saved_files

def load_all_trait_legit(trait_dir: Path, year: int = None, account: str = None, exclude_spam: bool = True) -> pd.DataFrame:
    """
    Charge l'ensemble des fichiers qualifiés depuis trait_legit/.
    Si exclude_spam est True, ne renvoie que les lignes dont Masque_Traitement == True.
    """
    if not trait_dir.exists():
        return enforce_sanctuary_schema(None)

    dfs = []
    for root, dirs, files in os.walk(trait_dir):
        for file in files:
            if file.endswith(".csv"):
                file_path = Path(root) / file

                # Filtre par année si spécifié
                if year and str(year) not in file_path.parts:
                    continue

                # Filtre par compte si spécifié
                if account and account.lower() not in file.lower():
                    continue

                try:
                    df = pd.read_csv(file_path, encoding="utf-8-sig")

                    # Attribution automatique du compte d'origine depuis le nom du fichier
                    acc_name = file_path.stem
                    df["Compte_Sanctuaire"] = acc_name

                    dfs.append(df)
                except Exception:
                    continue

    if not dfs:
        return enforce_sanctuary_schema(None)

    full_df = pd.concat(dfs, ignore_index=True)

    if exclude_spam and "Masque_Traitement" in full_df.columns:
        full_df = full_df[full_df["Masque_Traitement"].astype(str).str.lower().isin(["true", "1"])]

    return full_df

def calculate_token_balances(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule le solde net de chaque token par portefeuille/compte.
    Prend en compte les opérations de Trade/Swap double-actif (ex: NEVERLESS EUR -> EURC)
    ainsi que les spécificités 8LENDS sans interférence.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["Portefeuille", "Token", "Total_Entrees", "Total_Sorties", "Solde_Net", "Nombre_TX"])

    acc_series = df["Compte_Sanctuaire"] if "Compte_Sanctuaire" in df.columns else None
    res_df = enforce_sanctuary_schema(df)

    if acc_series is not None:
        res_df["Compte_Sanctuaire"] = acc_series.values

    movements = []

    for idx, row in res_df.iterrows():
        acc = str(row.get("Compte_Sanctuaire", "") or row.get("Nom du projet", "") or row.get("Réseau", "") or "Portefeuille_Inconnu").strip()
        proj = str(row.get("Nom du projet", "")).lower()
        acc_lower = acc.lower()

        tx_type = str(row.get("Type de transaction", "")).strip().lower()
        notes = str(row.get("Notes", "")).strip().lower()

        token_orig = str(row.get("Devise d'origine", "") or "").upper().strip()
        token_stmt = str(row.get("Devise du relevé", "") or "").upper().strip()

        amt_orig = abs(float(row.get("Montant d'origine", 0.0) or 0.0))
        amt_stmt = abs(float(row.get("Montant du relevé", 0.0) or 0.0))

        is_8lends = "8lends" in acc_lower or "8lends" in proj

        # 1. Traitement préservé pour 8LENDS
        if is_8lends:
            token = token_orig or token_stmt or "EUR"
            amt = amt_orig or amt_stmt
            if "retrait" in tx_type or "withdrawal" in tx_type:
                movements.append({"Portefeuille": acc, "Token": token, "Entree": 0.0, "Sortie": amt})
            elif "dépôt" in tx_type or "deposit" in tx_type or "investissement" in tx_type:
                movements.append({"Portefeuille": acc, "Token": token, "Entree": amt, "Sortie": 0.0})
            elif any(k in tx_type for k in ["remboursement", "restitution", "intérêt", "intérêts", "récompense", "parrainage"]):
                movements.append({"Portefeuille": acc, "Token": token, "Entree": 0.0, "Sortie": 0.0})
            else:
                movements.append({"Portefeuille": acc, "Token": token, "Entree": amt, "Sortie": 0.0})
            continue

        # 2. Traitement pour NEVERLESS et portefeuilles généraux
        is_trade_or_swap = "trade" in tx_type or "swap" in tx_type or "conversion" in notes

        # CAS A : Trade / Swap / Transfert interne de valeur
        if is_trade_or_swap:
            # Transfert de même actif (ex: USDC Prime -> USDC Stratégies) : neutre net sur l'actif
            if token_orig and token_stmt and token_orig == token_stmt:
                if amt_orig > 0 or amt_stmt > 0:
                    amt_tr = amt_orig if amt_orig > 0 else amt_stmt
                    movements.append({"Portefeuille": acc, "Token": token_orig, "Entree": amt_tr, "Sortie": amt_tr})
            else:
                # Échange d'actifs différents (ex: EUR -> EURC ou USDC -> BTC)
                if amt_orig > 0 and token_orig:
                    movements.append({"Portefeuille": acc, "Token": token_orig, "Entree": 0.0, "Sortie": amt_orig})
                if amt_stmt > 0 and token_stmt:
                    movements.append({"Portefeuille": acc, "Token": token_stmt, "Entree": amt_stmt, "Sortie": 0.0})
            continue

        # CAS B : Flux externe ou mouvements de coffre/relevé (Dépôt, Retrait, Earn, Top Up, Off-Ramp)
        raw_amt_orig = float(row.get("Montant d'origine", 0.0) or 0.0)
        raw_amt_stmt = float(row.get("Montant du relevé", 0.0) or 0.0)
        raw_amt = raw_amt_orig if raw_amt_orig != 0.0 else raw_amt_stmt

        is_earn_vault = "earn" in tx_type or "earn" in notes
        is_interest = "interest" in notes or "prime" in notes or "strategies interest" in notes or "interest" in tx_type
        outflow_types = ["retrait", "withdrawal", "fee", "out", "pay", "send", "transfer_out", "off-ramp", "sell"]
        inflow_types = ["dépôt", "deposit", "in", "buy", "receive", "revenue", "staking", "claim", "top up"]

        token = token_orig if token_orig and token_orig != "EUR" else (token_stmt or "EUR")
        if token in ["USD", "USDC", "USDT"]:
            token = "USDC" if token in ["USD", "USDC"] else token

        # Traitement spécifique Bleap : Séparation explicite Bleap Wallet vs Bleap Earn Vault
        is_bleap = "bleap" in acc_lower or "bleap" in proj
        if is_bleap and is_earn_vault and not is_interest:
            wallet_acc = "Bleap Wallet"
            earn_acc = "Bleap Earn Vault"
            amt_val = abs(raw_amt) if (amt_orig == 0 and amt_stmt == 0) else (amt_orig if amt_orig > 0 else amt_stmt)

            if "deposit" in tx_type or raw_amt < 0:
                # Earn Deposit : Sortie de Bleap Wallet -> Entrée sur Bleap Earn Vault
                movements.append({"Portefeuille": wallet_acc, "Token": token, "Entree": 0.0, "Sortie": amt_val})
                movements.append({"Portefeuille": earn_acc, "Token": token, "Entree": amt_val, "Sortie": 0.0})
            else:
                # Earn Withdrawal : Sortie de Bleap Earn Vault -> Entrée sur Bleap Wallet
                movements.append({"Portefeuille": earn_acc, "Token": token, "Entree": 0.0, "Sortie": amt_val})
                movements.append({"Portefeuille": wallet_acc, "Token": token, "Entree": amt_val, "Sortie": 0.0})
            continue

        # Si l'opération Earn est un transfert interne hors-Bleap
        if is_earn_vault and not is_interest:
            if raw_amt < 0:
                movements.append({"Portefeuille": acc, "Token": token, "Entree": abs(raw_amt), "Sortie": abs(raw_amt)})
            else:
                movements.append({"Portefeuille": acc, "Token": token, "Entree": abs(raw_amt), "Sortie": abs(raw_amt)})
            continue

        # Prise en compte prioritaire du signe négatif si fourni dans le CSV
        if raw_amt < 0:
            movements.append({"Portefeuille": acc, "Token": token, "Entree": 0.0, "Sortie": abs(raw_amt)})
        elif any(t in tx_type for t in outflow_types):
            movements.append({"Portefeuille": acc, "Token": token, "Entree": 0.0, "Sortie": abs(raw_amt)})
        elif is_interest or any(t in tx_type or t in notes for t in inflow_types):
            movements.append({"Portefeuille": acc, "Token": token, "Entree": abs(raw_amt), "Sortie": 0.0})
        else:
            movements.append({"Portefeuille": acc, "Token": token, "Entree": abs(raw_amt), "Sortie": 0.0})

    if not movements:
        return pd.DataFrame(columns=["Portefeuille", "Token", "Total_Entrees", "Total_Sorties", "Solde_Net", "Nombre_TX"])

    mov_df = pd.DataFrame(movements)
    summary = mov_df.groupby(["Portefeuille", "Token"]).agg(
        Total_Entrees=("Entree", "sum"),
        Total_Sorties=("Sortie", "sum"),
        Nombre_TX=("Entree", "count")
    ).reset_index()

    summary["Solde_Net"] = summary["Total_Entrees"] - summary["Total_Sorties"]
    return summary.sort_values(["Portefeuille", "Solde_Net"], ascending=[True, False])

def get_price_csv_path(trait_dir: Path, year: int) -> Path:
    """Retourne le chemin d'accès au fichier CSV de sanctuarisation des prix d'une année."""
    folder = trait_dir / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"prices_valuation_{year}.csv"

def load_persistent_prices(trait_dir: Path, year: int) -> pd.DataFrame:
    """Charge le fichier CSV des prix sanctuarisés d'une année."""
    path = get_price_csv_path(trait_dir, year)
    if not path.exists():
        return pd.DataFrame(columns=["Date_Consultation", "Token", "Prix_Unitaire_EUR", "Source_Prix", "Date_Evaluation"])
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        df["Token"] = df["Token"].astype(str).str.upper().str.strip()
        df["Prix_Unitaire_EUR"] = pd.to_numeric(df["Prix_Unitaire_EUR"], errors="coerce").fillna(0.0)
        return df
    except Exception:
        return pd.DataFrame(columns=["Date_Consultation", "Token", "Prix_Unitaire_EUR", "Source_Prix", "Date_Evaluation"])

def save_persistent_price(trait_dir: Path, year: int, token: str, price_eur: float, source_prix: str = "Surcharge Manuelle", eval_date: date = None):
    """Saisit ou met à jour le prix unitaire d'un jeton pour une DATE D'ÉVALUATION donnée dans la table CSV sanctuarisée de l'année."""
    batch_save_persistent_prices(
        trait_dir=trait_dir,
        year=year,
        eval_date=eval_date,
        price_records=[{"Token": token, "Prix_Unitaire_EUR": price_eur, "Source_Prix": source_prix}]
    )

def batch_save_persistent_prices(trait_dir: Path, year: int, eval_date: date, price_records: list):
    """
    Sanctuarise EN BLOC l'intégralité des prix unitaires de TOUS les jetons pour une Date_Evaluation donnée.
    Chaque prix est enregistré dans prices_valuation_{YEAR}.csv avec horodatage de consultation.
    """
    if not trait_dir or not price_records:
        return

    path = get_price_csv_path(trait_dir, year)
    existing_df = load_persistent_prices(trait_dir, year)

    now_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    eval_str = eval_date.strftime("%d-%m-%Y") if eval_date else datetime.now().strftime("%d-%m-%Y")

    new_rows = []
    for rec in price_records:
        tok_clean = str(rec["Token"]).upper().strip()
        p_val = float(rec["Prix_Unitaire_EUR"])
        src_lbl = rec.get("Source_Prix", "Calculé")
        new_rows.append({
            "Date_Consultation": now_str,
            "Token": tok_clean,
            "Prix_Unitaire_EUR": p_val,
            "Source_Prix": src_lbl,
            "Date_Evaluation": eval_str
        })

    new_df = pd.DataFrame(new_rows)

    if not existing_df.empty:
        # Remplacement atomique de l'ensemble des jetons ré-évalués à cette Date_Evaluation exacte
        tokens_to_update = set(new_df["Token"].unique())
        mask = (existing_df["Date_Evaluation"] == eval_str) & (existing_df["Token"].isin(tokens_to_update))
        existing_df = existing_df[~mask]
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_csv(path, index=False, encoding="utf-8-sig")

def evaluate_balances_at_date(balance_df: pd.DataFrame, eval_date: date, trait_dir: Path = None) -> pd.DataFrame:
    """
    Valorise les soldes nets en Euros au cours exact de la date d'évaluation eval_date,
    en traçant et sanctuarisant L'ENSEMBLE des prix de TOUS les jetons par (Date_Evaluation, Token) dans prices_valuation_{YEAR}.csv.
    """
    if balance_df is None or balance_df.empty:
        return pd.DataFrame(columns=["Portefeuille", "Token", "Solde_Net", "Prix_Unitaire_EUR", "Valeur_Totale_EUR", "Source_Prix"])

    res_df = balance_df.copy()
    yr = eval_date.year
    eval_str = eval_date.strftime("%d-%m-%Y")

    # Chargement du registre sanctuarisé des prix filtré STRICTEMENT par Date_Evaluation == eval_str
    persistent_prices = {}
    if trait_dir:
        p_df = load_persistent_prices(trait_dir, yr)
        if not p_df.empty and "Date_Evaluation" in p_df.columns:
            p_df_date = p_df[p_df["Date_Evaluation"] == eval_str]
            if not p_df_date.empty:
                persistent_prices = p_df_date.set_index("Token")["Prix_Unitaire_EUR"].to_dict()

    ecb_rate_usd_eur = get_ecb_eur_rate("USD", eval_date)

    unit_prices = []
    total_values = []
    sources = []
    records_to_sanctuary = []

    for idx, row in res_df.iterrows():
        token = str(row["Token"]).upper().strip()
        solde = float(row["Solde_Net"])

        price_eur = 0.0
        source_lbl = "Calculé"

        # 1. Vérification si un prix a DÉJÀ été sanctuarisé spécifiquement pour CETTE Date_Evaluation
        if token in persistent_prices and persistent_prices[token] >= 0:
            price_eur = persistent_prices[token]
            source_lbl = "Sanctuarisé (Date T_eval)"
        elif token in ["EUR", "EURC"]:
            price_eur = 1.0
            source_lbl = "Parité EUR 1:1"
        else:
            # 2. Recherche en ligne à la date T_eval (DefiLlama / CoinGecko + BCE)
            price_usd = get_crypto_usd_price_defillama(token, eval_date)
            if price_usd and ecb_rate_usd_eur:
                price_eur = price_usd * ecb_rate_usd_eur
                source_lbl = "API DefiLlama / BCE"
            elif price_usd:
                price_eur = price_usd * 0.92
                source_lbl = "API DefiLlama"
            else:
                price_eur = 0.0
                source_lbl = "Non Renseigné (À saisir)"

        records_to_sanctuary.append({
            "Token": token,
            "Prix_Unitaire_EUR": price_eur,
            "Source_Prix": source_lbl
        })

        unit_prices.append(round(price_eur, 8))
        total_values.append(round(solde * price_eur, 2))
        sources.append(source_lbl)

    # Sanctuarisation automatique EN BLOC de TOUS les jetons du portefeuille pour cette Date_Evaluation
    if trait_dir and records_to_sanctuary:
        batch_save_persistent_prices(trait_dir, yr, eval_date, records_to_sanctuary)

    res_df["Prix_Unitaire_EUR"] = unit_prices
    res_df["Valeur_Totale_EUR"] = total_values
    res_df["Source_Prix"] = sources

    return res_df
