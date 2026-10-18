"""
Module de collecte 100% GRATUITE via Blockscout V2 API et Etherscan API.
Réseaux pris en charge : Ethereum, Base, Arbitrum.
"""
import requests
import pandas as pd
from datetime import datetime, timezone
import time
from .schema import enforce_sanctuary_schema, create_empty_sanctuary_df
from .fx_collector import convert_to_eur
from .sanctuary_manager import load_sanctuary_account

BLOCKSCOUT_NETWORKS = {
    "ETHEREUM": {
        "v2_url": "https://eth.blockscout.com/api/v2",
        "v1_url": "https://eth.blockscout.com/api",
        "native": "ETH"
    },
    "BASE": {
        "v2_url": "https://base.blockscout.com/api/v2",
        "v1_url": "https://base.blockscout.com/api",
        "native": "ETH"
    },
    "ARBITRUM": {
        "v2_url": "https://arbitrum.blockscout.com/api/v2",
        "v1_url": "https://arbitrum.blockscout.com/api",
        "native": "ETH"
    }
}

def get_headers(domain_url: str) -> dict:
    """Génère les en-têtes HTTP requis pour contourner les filtres anti-bot Cloudflare."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": domain_url,
        "Referer": f"{domain_url}/"
    }

def _parse_utc_datetime(dt_str) -> datetime:
    """Convertit une chaîne ou timestamp Blockscout en datetime UTC strict."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        s = str(dt_str)
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)

def fetch_blockscout_data(address: str, network: str, target_year: int = None, account_label: str = None, max_pages: int = 200, api_key: str = None) -> pd.DataFrame:
    """
    Récupère de manière ciblée les transactions (natives, tokens ERC-20/721/1155, internes et frais de gaz)
    d'une adresse via l'API V2 Blockscout.
    Si target_year est spécifié, ne retient STRICTEMENT que les transactions de cette année.
    """
    net_key = network.upper().strip()
    if net_key not in BLOCKSCOUT_NETWORKS or not address or not address.startswith("0x"):
        return create_empty_sanctuary_df()

    cfg = BLOCKSCOUT_NETWORKS[net_key]
    v2_base = cfg["v2_url"]
    domain_root = v2_base.split("/api")[0]
    addr_low = address.lower().strip()
    headers = get_headers(domain_root)

    target_year_int = int(target_year) if target_year else None

    records = []
    seen_keys = set()
    session = requests.Session()
    session.headers.update(headers)

    # --- STRATÉGIE 1 : TOKEN TRANSFERS ---
    token_url = f"{v2_base}/addresses/{addr_low}/token-transfers"
    pages_fetched = 0

    while token_url and pages_fetched < max_pages:
        try:
            res = session.get(token_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                if not items:
                    break

                for t in items:
                    try:
                        tx_hash = t.get("transaction_hash") or t.get("hash") or ""
                        if not tx_hash:
                            continue

                        dt = _parse_utc_datetime(t.get("timestamp") or t.get("timeStamp"))

                        # S'arrêter si on descend en dessous de l'année cible
                        if target_year_int and dt.year < target_year_int:
                            token_url = None
                            break

                        # Ignorer les transactions plus récentes (ex: 2026 quand target_year=2025)
                        if target_year_int and dt.year != target_year_int:
                            continue

                        tok = t.get("token") or {}
                        tot = t.get("total") or {}

                        asset = tok.get("symbol") or tok.get("name") or "TOKEN"
                        dec = int(tok.get("decimals") or tot.get("decimals") or 18)

                        raw_val = float(tot.get("value") or t.get("value") or 0)
                        amount = raw_val / (10 ** dec) if dec > 0 else raw_val

                        f_addr = (t.get("from") if isinstance(t.get("from"), str) else (t.get("from") or {}).get("hash", "")).strip()
                        t_addr = (t.get("to") if isinstance(t.get("to"), str) else (t.get("to") or {}).get("hash", "")).strip()

                        direction = 1.0 if t_addr.lower() == addr_low else -1.0
                        final_amt = amount * direction
                        tx_type = "Dépôt" if direction > 0 else "Retrait"

                        dedup_key = (tx_hash, str(asset).upper(), round(final_amt, 8))
                        if dedup_key in seen_keys:
                            continue
                        seen_keys.add(dedup_key)

                        val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, asset, dt)
                        method = t.get("method") or "Token Transfer"

                        records.append({
                            "Date de la transaction": dt.strftime("%d-%m-%Y %H:%M:%S"),
                            "Type de transaction": tx_type,
                            "ID du projet": f"BLOCKSCOUT_{net_key}",
                            "Nom du projet": f"Token Transfer ({asset})",
                            "APR %": 0.0,
                            "Montant d'origine": final_amt,
                            "Devise d'origine": str(asset).upper(),
                            "Montant du relevé": val_eur,
                            "Devise du relevé": "EUR",
                            "Paire FX": fx_pair,
                            "Taux de change appliqué": rate,
                            "Date du taux de change appliqué": r_date,
                            "Source du taux de change": r_src,
                            "Statut de la transaction": "Validé",
                            "Réseau": net_key,
                            "Hash de la transaction blockchain": tx_hash,
                            "Notes": f"Method: {method}",
                            "Nom et numéro [Banque fiat ou compte] d'origine": f_addr,
                            "Nom et numéro [Banque fiat ou compte] de destination": t_addr
                        })
                    except Exception:
                        continue

                if token_url is None:
                    break

                pages_fetched += 1
                next_params = data.get("next_page_params")
                if next_params and isinstance(next_params, dict):
                    q_str = "&".join([f"{k}={v}" for k, v in next_params.items()])
                    token_url = f"{v2_base}/addresses/{addr_low}/token-transfers?{q_str}"
                else:
                    token_url = None
                time.sleep(0.01)
            else:
                break
        except Exception:
            break

    # --- STRATÉGIE 2 : NATIVE TRANSACTIONS & GAS FEES ---
    tx_url = f"{v2_base}/addresses/{addr_low}/transactions"
    pages_fetched = 0

    while tx_url and pages_fetched < max_pages:
        try:
            res = session.get(tx_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                if not items:
                    break

                for t in items:
                    try:
                        tx_hash = t.get("hash") or ""
                        if not tx_hash:
                            continue

                        dt = _parse_utc_datetime(t.get("timestamp") or t.get("timeStamp"))

                        if target_year_int and dt.year < target_year_int:
                            tx_url = None
                            break

                        if target_year_int and dt.year != target_year_int:
                            continue

                        f_addr = (t.get("from") if isinstance(t.get("from"), str) else (t.get("from") or {}).get("hash", "")).strip()
                        t_addr = (t.get("to") if isinstance(t.get("to"), str) else (t.get("to") or {}).get("hash", "")).strip()

                        raw_val = float(t.get("value") or 0) / 10**18
                        fee_obj = t.get("fee") or {}
                        gas_fee = float(fee_obj.get("value") or 0) / 10**18
                        method = t.get("method") or "Contract Call"

                        # Embedded token transfers
                        embedded_tokens = t.get("token_transfers") or []
                        if embedded_tokens and isinstance(embedded_tokens, list):
                            for tt in embedded_tokens:
                                try:
                                    tok = tt.get("token") or {}
                                    tot = tt.get("total") or {}
                                    sym = tok.get("symbol") or tok.get("name") or "TOKEN"
                                    dec = int(tok.get("decimals") or tot.get("decimals") or 18)
                                    amt = float(tot.get("value") or tt.get("value") or 0) / (10 ** dec) if dec > 0 else float(tot.get("value") or 0)

                                    tt_from = (tt.get("from") if isinstance(tt.get("from"), str) else (tt.get("from") or {}).get("hash", "")).strip()
                                    tt_to = (tt.get("to") if isinstance(tt.get("to"), str) else (tt.get("to") or {}).get("hash", "")).strip()

                                    direction = 1.0 if tt_to.lower() == addr_low else -1.0
                                    final_amt = amt * direction
                                    tx_type = "Dépôt" if direction > 0 else "Retrait"

                                    dedup_key = (tx_hash, str(sym).upper(), round(final_amt, 8))
                                    if dedup_key in seen_keys:
                                        continue
                                    seen_keys.add(dedup_key)

                                    val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, sym, dt)

                                    records.append({
                                        "Date de la transaction": dt.strftime("%d-%m-%Y %H:%M:%S"),
                                        "Type de transaction": tx_type,
                                        "ID du projet": f"BLOCKSCOUT_{net_key}",
                                        "Nom du projet": f"Token Transfer ({sym})",
                                        "APR %": 0.0,
                                        "Montant d'origine": final_amt,
                                        "Devise d'origine": str(sym).upper(),
                                        "Montant du relevé": val_eur,
                                        "Devise du relevé": "EUR",
                                        "Paire FX": fx_pair,
                                        "Taux de change appliqué": rate,
                                        "Date du taux de change appliqué": r_date,
                                        "Source du taux de change": r_src,
                                        "Statut de la transaction": "Validé",
                                        "Réseau": net_key,
                                        "Hash de la transaction blockchain": tx_hash,
                                        "Notes": f"Method: {method}",
                                        "Nom et numéro [Banque fiat ou compte] d'origine": tt_from,
                                        "Nom et numéro [Banque fiat ou compte] de destination": tt_to
                                    })
                                except Exception:
                                    continue

                        # Traitement du flux Natif (ETH)
                        if raw_val > 0:
                            direction = 1.0 if t_addr.lower() == addr_low else -1.0
                            final_amt = raw_val * direction
                            tx_type = "Dépôt" if direction > 0 else "Retrait"

                            dedup_key = (tx_hash, cfg["native"], round(final_amt, 8))
                            if dedup_key not in seen_keys:
                                seen_keys.add(dedup_key)
                                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, cfg["native"], dt)

                                records.append({
                                    "Date de la transaction": dt.strftime("%d-%m-%Y %H:%M:%S"),
                                    "Type de transaction": tx_type,
                                    "ID du projet": f"BLOCKSCOUT_{net_key}",
                                    "Nom du projet": f"Mouvement Natif {cfg['native']}",
                                    "APR %": 0.0,
                                    "Montant d'origine": final_amt,
                                    "Devise d'origine": cfg["native"],
                                    "Montant du relevé": val_eur,
                                    "Devise du relevé": "EUR",
                                    "Paire FX": fx_pair,
                                    "Taux de change appliqué": rate,
                                    "Date du taux de change appliqué": r_date,
                                    "Source du taux de change": r_src,
                                    "Statut de la transaction": "Validé",
                                    "Réseau": net_key,
                                    "Hash de la transaction blockchain": tx_hash,
                                    "Notes": f"Method: {method}",
                                    "Nom et numéro [Banque fiat ou compte] d'origine": f_addr,
                                    "Nom et numéro [Banque fiat ou compte] de destination": t_addr
                                })

                        # Prise en compte des frais de gaz
                        elif raw_val == 0 and gas_fee > 0 and f_addr.lower() == addr_low and not embedded_tokens:
                            final_amt = -gas_fee
                            dedup_key = (tx_hash, "FEE", round(final_amt, 8))
                            if dedup_key not in seen_keys:
                                seen_keys.add(dedup_key)
                                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, cfg["native"], dt)

                                records.append({
                                    "Date de la transaction": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Type de transaction": "Fee",
                                    "ID du projet": f"BLOCKSCOUT_{net_key}",
                                    "Nom du projet": f"Frais de Réseau ({method})",
                                    "APR %": 0.0,
                                    "Montant d'origine": final_amt,
                                    "Devise d'origine": cfg["native"],
                                    "Montant du relevé": val_eur,
                                    "Devise du relevé": "EUR",
                                    "Paire FX": fx_pair,
                                    "Taux de change appliqué": rate,
                                    "Date du taux de change appliqué": r_date,
                                    "Source du taux de change": r_src,
                                    "Statut de la transaction": "Validé",
                                    "Réseau": net_key,
                                    "Hash de la transaction blockchain": tx_hash,
                                    "Notes": f"Gas Fee Paid for {method}",
                                    "Nom et numéro [Banque fiat ou compte] d'origine": f_addr,
                                    "Nom et numéro [Banque fiat ou compte] de destination": t_addr
                                })

                    except Exception:
                        continue

                if tx_url is None:
                    break

                pages_fetched += 1
                next_params = data.get("next_page_params")
                if next_params and isinstance(next_params, dict):
                    q_str = "&".join([f"{k}={v}" for k, v in next_params.items()])
                    tx_url = f"{v2_base}/addresses/{addr_low}/transactions?{q_str}"
                else:
                    tx_url = None
                time.sleep(0.01)
            else:
                break
        except Exception:
            break

    df = pd.DataFrame(records)
    df_enforced = enforce_sanctuary_schema(df)

    # Filtrage strict final garanti si target_year est spécifié
    if target_year_int and not df_enforced.empty:
        df_enforced["_yr_check"] = smart_parse_dates(df_enforced["Date de la transaction"]).dt.year
        df_enforced = df_enforced[df_enforced["_yr_check"] == target_year_int].drop(columns=["_yr_check"])

    return df_enforced
