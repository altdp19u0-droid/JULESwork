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

def fetch_blockscout_data(address: str, network: str, max_pages: int = 20, api_key: str = None) -> pd.DataFrame:
    """
    Récupère l'intégralité des transactions (natives, tokens ERC-20, internes) d'une adresse
    via l'API V2 Blockscout (avec repli V1 / Etherscan-compatible) sans clé API obligatoire.
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

    # --- STRATÉGIE 1 : BLOCKSCOUT V2 REST API ---
    endpoints_v2 = [
        ("transactions", "Native"),
        ("token-transfers", "Token"),
        ("internal-transactions", "Interne")
    ]

    session = requests.Session()
    session.headers.update(headers)

    for ep_path, label in endpoints_v2:
        url = f"{v2_base}/addresses/{addr_low}/{ep_path}"
        pages_fetched = 0

        while url and pages_fetched < max_pages:
            success = False
            for attempt in range(3):
                try:
                    res = session.get(url, timeout=12)
                    if res.status_code == 200:
                        data = res.json()
                        items = data.get("items", [])
                        if not isinstance(items, list) or not items:
                            url = None
                            break

                        for t in items:
                            try:
                                tx_hash = t.get("hash") or t.get("tx_hash") or ""
                                if not tx_hash:
                                    continue

                                # Extraction Asset & Montant
                                if label == "Token":
                                    tok = t.get("token") or {}
                                    asset = tok.get("symbol") or tok.get("name") or "TOKEN"
                                    dec = int(tok.get("decimals") or 18)
                                    raw_val = float(t.get("value") or 0)
                                    amount = raw_val / (10 ** dec)
                                else:
                                    asset = cfg["native"]
                                    raw_val = float(t.get("value") or 0)
                                    amount = raw_val / 10**18

                                # Extraction Date
                                dt_str = t.get("timestamp") or t.get("timeStamp")
                                if dt_str and not str(dt_str).isdigit():
                                    dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
                                elif dt_str:
                                    dt = datetime.fromtimestamp(int(dt_str))
                                else:
                                    dt = datetime.now()

                                # Orientation Flux
                                f_addr = (t.get("from") if isinstance(t.get("from"), str) else (t.get("from") or {}).get("hash", "")).lower()
                                t_addr = (t.get("to") if isinstance(t.get("to"), str) else (t.get("to") or {}).get("hash", "")).lower()

                                direction = 1.0 if t_addr == addr_low else -1.0
                                final_amt = amount * direction
                                tx_type = "Dépôt" if direction > 0 else "Retrait"

                                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, asset, dt)

                                record = {
                                    "Date de la transaction": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Type de transaction": tx_type,
                                    "ID du projet": f"BLOCKSCOUT_{net_key}",
                                    "Nom du projet": f"Explorer {net_key}",
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
                                    "Notes banque fiat d'origine ou de destination": f"From: {f_addr[:10]}... To: {t_addr[:10]}..."
                                }
                                records.append(record)
                            except Exception:
                                continue

                        pages_fetched += 1
                        next_params = data.get("next_page_params")
                        if next_params and isinstance(next_params, dict):
                            q_str = "&".join([f"{k}={v}" for k, v in next_params.items()])
                            url = f"{v2_base}/addresses/{addr_low}/{ep_path}?{q_str}"
                        else:
                            url = None

                        success = True
                        time.sleep(0.15)
                        break
                    elif res.status_code in [429, 503]:
                        time.sleep(1.5 * (attempt + 1))
                    else:
                        break
                except Exception:
                    time.sleep(1.0)

            if not success and attempt == 2:
                break

    # --- STRATÉGIE 2 (REPLI) : BLOCKSCOUT V1 API ---
    if not records:
        endpoints_v1 = [
            ("txlist", "Native"),
            ("tokentx", "Token"),
            ("txlistinternal", "Interne")
        ]
        for action, label in endpoints_v1:
            try:
                key_param = f"&apikey={api_key}" if api_key else ""
                v1_url = f"{v1_base}?module=account&action={action}&address={addr_low}&sort=asc{key_param}"
                res = session.get(v1_url, timeout=12)
                if res.status_code == 200:
                    d = res.json()
                    items = d.get("result", [])
                    if isinstance(items, list):
                        for t in items:
                            try:
                                tx_hash = t.get("hash") or ""
                                if not tx_hash:
                                    continue

                                dec = int(t.get("tokenDecimal") or 18) if label == "Token" else 18
                                asset = t.get("tokenSymbol") or cfg["native"] if label == "Token" else cfg["native"]
                                amount = float(t.get("value") or 0) / (10 ** dec)

                                ts = int(t.get("timeStamp") or time.time())
                                dt = datetime.fromtimestamp(ts)

                                f_addr = str(t.get("from") or "").lower()
                                t_addr = str(t.get("to") or "").lower()

                                direction = 1.0 if t_addr == addr_low else -1.0
                                final_amt = amount * direction
                                tx_type = "Dépôt" if direction > 0 else "Retrait"

                                val_eur, rate, r_date, r_src, fx_pair = convert_to_eur(final_amt, asset, dt)

                                records.append({
                                    "Date de la transaction": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Type de transaction": tx_type,
                                    "ID du projet": f"BLOCKSCOUT_{net_key}_V1",
                                    "Nom du projet": f"Explorer {net_key}",
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
                                    "Notes banque fiat d'origine ou de destination": f"From: {f_addr[:10]}... To: {t_addr[:10]}..."
                                })
                            except Exception:
                                continue
            except Exception:
                continue

    df = pd.DataFrame(records)
    return enforce_sanctuary_schema(df)
