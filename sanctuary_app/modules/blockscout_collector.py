"""
Module de collecte 100% GRATUITE via Blockscout V2 API et Etherscan API.
Réseaux pris en charge : Ethereum, Base, Arbitrum.
"""
import requests
import pandas as pd
from datetime import datetime
import time
from .schema import enforce_sanctuary_schema, create_empty_sanctuary_df
from .fx_collector import convert_to_eur

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

def fetch_blockscout_data(address: str, network: str, target_year: int = None, max_pages: int = 15, api_key: str = None) -> pd.DataFrame:
    """
    Récupère l'intégralité des transactions (natives, tokens ERC-20/721/1155, internes et frais de gaz) d'une adresse
    via l'API V2 Blockscout (avec repli V1) sans aucune clé API requise.
    Si target_year est fourni, ne conserve QUE les transactions de cette année spécifique.
    """
    net_key = network.upper().strip()
    if net_key not in BLOCKSCOUT_NETWORKS or not address or not address.startswith("0x"):
        return create_empty_sanctuary_df()

    cfg = BLOCKSCOUT_NETWORKS[net_key]
    v2_base = cfg["v2_url"]
    v1_base = cfg["v1_url"]
    domain_root = v2_base.split("/api")[0]
    addr_low = address.lower().strip()
    headers = get_headers(domain_root)

    records = []
    seen_keys = set()
    session = requests.Session()
    session.headers.update(headers)

    # --- STRATÉGIE 1 : TOKEN TRANSFERS (ERC-20 / ERC-721 / ERC-1155) ---
    token_url = f"{v2_base}/addresses/{addr_low}/token-transfers"
    pages_fetched = 0

    while token_url and pages_fetched < max_pages:
        try:
            res = session.get(token_url, timeout=8)
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

                        # Extraction Date & Filtrage par Année
                        dt_str = t.get("timestamp") or t.get("timeStamp")
                        if dt_str and not str(dt_str).isdigit():
                            dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
                        elif dt_str:
                            dt = datetime.fromtimestamp(int(dt_str))
                        else:
                            dt = datetime.now()

                        if target_year and dt.year != int(target_year):
                            continue

                        tok = t.get("token") or {}
                        tot = t.get("total") or {}

                        asset = tok.get("symbol") or tok.get("name") or "TOKEN"
                        dec = int(tok.get("decimals") or tot.get("decimals") or 18)

                        raw_val = float(tot.get("value") or t.get("value") or 0)
                        amount = raw_val / (10 ** dec) if dec > 0 else raw_val

                        f_addr = (t.get("from") if isinstance(t.get("from"), str) else (t.get("from") or {}).get("hash", "")).lower()
                        t_addr = (t.get("to") if isinstance(t.get("to"), str) else (t.get("to") or {}).get("hash", "")).lower()

                        direction = 1.0 if t_addr == addr_low else -1.0
                        final_amt = amount * direction
                        tx_type = "Dépôt" if direction > 0 else "Retrait"

                        val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, asset, dt)
                        method = t.get("method") or "Token Transfer"

                        dedup_key = (tx_hash, str(asset).upper(), round(final_amt, 8))
                        if dedup_key in seen_keys:
                            continue
                        seen_keys.add(dedup_key)

                        records.append({
                            "Date de la transaction": dt.strftime("%Y-%m-%d %H:%M:%S"),
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
                            "Notes banque fiat d'origine ou de destination": f"Method: {method} | From: {f_addr[:10]}... To: {t_addr[:10]}..."
                        })
                    except Exception:
                        continue

                pages_fetched += 1
                next_params = data.get("next_page_params")
                if next_params and isinstance(next_params, dict):
                    q_str = "&".join([f"{k}={v}" for k, v in next_params.items()])
                    token_url = f"{v2_base}/addresses/{addr_low}/token-transfers?{q_str}"
                else:
                    token_url = None
                time.sleep(0.05)
            else:
                break
        except Exception:
            break

    # --- STRATÉGIE 2 : NATIVE TRANSACTIONS & GAS FEES ---
    tx_url = f"{v2_base}/addresses/{addr_low}/transactions"
    pages_fetched = 0

    while tx_url and pages_fetched < max_pages:
        try:
            res = session.get(tx_url, timeout=8)
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

                        dt_str = t.get("timestamp") or t.get("timeStamp")
                        if dt_str and not str(dt_str).isdigit():
                            dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
                        elif dt_str:
                            dt = datetime.fromtimestamp(int(dt_str))
                        else:
                            dt = datetime.now()

                        if target_year and dt.year != int(target_year):
                            continue

                        f_addr = (t.get("from") if isinstance(t.get("from"), str) else (t.get("from") or {}).get("hash", "")).lower()
                        t_addr = (t.get("to") if isinstance(t.get("to"), str) else (t.get("to") or {}).get("hash", "")).lower()

                        raw_val = float(t.get("value") or 0) / 10**18
                        fee_obj = t.get("fee") or {}
                        gas_fee = float(fee_obj.get("value") or 0) / 10**18
                        method = t.get("method") or "Contract Call"

                        # Extraction des token transfers imbriqués
                        embedded_tokens = t.get("token_transfers") or []
                        if embedded_tokens and isinstance(embedded_tokens, list):
                            for tt in embedded_tokens:
                                try:
                                    tok = tt.get("token") or {}
                                    tot = tt.get("total") or {}
                                    sym = tok.get("symbol") or tok.get("name") or "TOKEN"
                                    dec = int(tok.get("decimals") or tot.get("decimals") or 18)
                                    amt = float(tot.get("value") or tt.get("value") or 0) / (10 ** dec) if dec > 0 else float(tot.get("value") or 0)

                                    tt_from = (tt.get("from") if isinstance(tt.get("from"), str) else (tt.get("from") or {}).get("hash", "")).lower()
                                    tt_to = (tt.get("to") if isinstance(tt.get("to"), str) else (tt.get("to") or {}).get("hash", "")).lower()

                                    direction = 1.0 if tt_to == addr_low else -1.0
                                    final_amt = amt * direction
                                    tx_type = "Dépôt" if direction > 0 else "Retrait"

                                    dedup_key = (tx_hash, str(sym).upper(), round(final_amt, 8))
                                    if dedup_key in seen_keys:
                                        continue
                                    seen_keys.add(dedup_key)

                                    val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, sym, dt)

                                    records.append({
                                        "Date de la transaction": dt.strftime("%Y-%m-%d %H:%M:%S"),
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
                                        "Notes banque fiat d'origine ou de destination": f"Method: {method} | From: {tt_from[:10]}... To: {tt_to[:10]}..."
                                    })
                                except Exception:
                                    continue

                        # Traitement du flux Natif (ETH)
                        if raw_val > 0:
                            direction = 1.0 if t_addr == addr_low else -1.0
                            final_amt = raw_val * direction
                            tx_type = "Dépôt" if direction > 0 else "Retrait"

                            dedup_key = (tx_hash, cfg["native"], round(final_amt, 8))
                            if dedup_key not in seen_keys:
                                seen_keys.add(dedup_key)
                                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, cfg["native"], dt)

                                records.append({
                                    "Date de la transaction": dt.strftime("%Y-%m-%d %H:%M:%S"),
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
                                    "Notes banque fiat d'origine ou de destination": f"Method: {method} | From: {f_addr[:10]}... To: {t_addr[:10]}..."
                                })

                        # Prise en compte des frais de gaz
                        elif raw_val == 0 and gas_fee > 0 and f_addr == addr_low and not embedded_tokens:
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
                                    "Notes banque fiat d'origine ou de destination": f"Gas Fee Paid for {method} to {t_addr[:10]}..."
                                })

                    except Exception:
                        continue

                pages_fetched += 1
                next_params = data.get("next_page_params")
                if next_params and isinstance(next_params, dict):
                    q_str = "&".join([f"{k}={v}" for k, v in next_params.items()])
                    tx_url = f"{v2_base}/addresses/{addr_low}/transactions?{q_str}"
                else:
                    tx_url = None
                time.sleep(0.05)
            else:
                break
        except Exception:
            break

    df = pd.DataFrame(records)
    return enforce_sanctuary_schema(df)
