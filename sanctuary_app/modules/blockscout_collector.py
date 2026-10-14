"""
Module de collecte 100% GRATUITE via Blockscout V2 API sans aucune clé API requise.
Réseaux pris en charge : Ethereum, Base, Arbitrum.
"""
import requests
import pandas as pd
from datetime import datetime
import time
from .schema import enforce_sanctuary_schema, create_empty_sanctuary_df
from .fx_collector import convert_to_eur

BLOCKSCOUT_NETWORKS = {
    "ETHEREUM": {"url": "https://eth.blockscout.com/api/v2", "native": "ETH"},
    "BASE": {"url": "https://base.blockscout.com/api/v2", "native": "ETH"},
    "ARBITRUM": {"url": "https://arbitrum.blockscout.com/api/v2", "native": "ETH"}
}

def fetch_blockscout_data(address: str, network: str, max_pages: int = 10) -> pd.DataFrame:
    """
    Récupère l'intégralité des transactions (natives, tokens ERC-20, internes) d'une adresse
    via l'API V2 Blockscout sans aucune clé API.
    """
    net_key = network.upper().strip()
    if net_key not in BLOCKSCOUT_NETWORKS or not address or not address.startswith("0x"):
        return create_empty_sanctuary_df()

    cfg = BLOCKSCOUT_NETWORKS[net_key]
    base_api = cfg["url"]
    addr_low = address.lower()

    endpoints = [
        ("transactions", "Native"),
        ("token-transfers", "Token"),
        ("internal-transactions", "Interne")
    ]

    records = []

    for ep_path, label in endpoints:
        url = f"{base_api}/addresses/{address}/{ep_path}"
        pages_fetched = 0

        while url and pages_fetched < max_pages:
            try:
                res = requests.get(url, timeout=15)
                if res.status_code != 200:
                    break

                data = res.json()
                items = data.get("items", [])
                if not isinstance(items, list) or not items:
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

                        # Orientation Flux (Entrée / Sortie)
                        f_addr = (t.get("from") if isinstance(t.get("from"), str) else t.get("from", {}).get("hash", "")).lower()
                        t_addr = (t.get("to") if isinstance(t.get("to"), str) else t.get("to", {}).get("hash", "")).lower()

                        direction = 1.0 if t_addr == addr_low else -1.0
                        final_amt = amount * direction
                        tx_type = "Dépôt" if direction > 0 else "Retrait"

                        # Valuation en EUR
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
                    url = f"{base_api}/addresses/{address}/{ep_path}?{q_str}"
                else:
                    url = None

                time.sleep(0.1) # Courtoisie Rate Limit
            except Exception:
                break

    df = pd.DataFrame(records)
    return enforce_sanctuary_schema(df)
