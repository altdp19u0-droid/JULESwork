"""
Module de collecte 100% GRATUITE des taux de change (ECB / BCE) et prix Crypto (DefiLlama / CoinGecko).
"""
import requests
from datetime import datetime, date
import time

# Cache mémoire avec TTL pour éviter les requêtes HTTP répétitives
FX_CACHE = {}

def get_ecb_eur_rate(target_currency: str, date_obj) -> float:
    """
    Récupère le taux de change EUR pour une devise Fiat à une date donnée.
    Source : API officielle Banque Centrale Européenne (via API Frankfurter - 100% Gratuit).
    Exemple: Si USD, retourne la valeur de 1 USD en EUR.
    """
    if not target_currency or target_currency.upper() == "EUR":
        return 1.0

    curr = target_currency.upper().strip()
    if isinstance(date_obj, datetime):
        d_str = date_obj.strftime("%Y-%m-%d")
    elif isinstance(date_obj, date):
        d_str = date_obj.strftime("%Y-%m-%d")
    else:
        d_str = str(date_obj)[:10]

    cache_key = f"ECB_{curr}_{d_str}"
    if cache_key in FX_CACHE:
        return FX_CACHE[cache_key]

    # Defaults de sécurité immédiats si échec HTTP
    defaults = {"USD": 0.92, "GBP": 1.17, "CHF": 1.05, "CAD": 0.68, "JPY": 0.006}

    try:
        url = f"https://api.frankfurter.app/{d_str}?from={curr}&to=EUR"
        res = requests.get(url, timeout=1.0)
        if res.status_code == 200:
            val = float(res.json()["rates"]["EUR"])
            FX_CACHE[cache_key] = val
            return val
    except Exception:
        pass

    fallback = defaults.get(curr, 0.92)
    FX_CACHE[cache_key] = fallback
    return fallback

def get_crypto_usd_price_defillama(asset: str, date_obj) -> float:
    """
    Récupère le prix USD historique d'un crypto-actif via DefiLlama LlamaCoins API (100% Gratuit sans clé API).
    """
    if not asset or not isinstance(asset, str):
        return 0.0

    asset_clean = asset.upper().strip()

    # Stablecoins pegged
    if asset_clean in ["USDC", "USDT", "DAI", "FDUSD", "USDE"]:
        return 1.0
    if asset_clean in ["EURA", "AGEUR", "STEUR", "EURE"]:
        return 1.08

    symbol_map = {
        "ETH": "coingecko:ethereum",
        "WETH": "coingecko:ethereum",
        "BTC": "coingecko:bitcoin",
        "WBTC": "coingecko:wrapped-bitcoin",
        "BCH": "coingecko:bitcoin-cash",
        "BNB": "coingecko:binancecoin",
        "POL": "coingecko:polygon-ecosystem-token",
        "MATIC": "coingecko:matic-network",
        "ARB": "coingecko:arbitrum",
        "OP": "coingecko:optimism",
        "SOL": "coingecko:solana",
        "AAVE": "coingecko:aave",
        "TWT": "coingecko:trust-wallet-token",
        "MERL": "coingecko:merlin-chain",
        "SUN": "coingecko:sun-token",
        "THE": "coingecko:thena",
        "ORDER": "coingecko:orderly-network",
        "ME": "coingecko:magic-eden",
        "ZBCN": "coingecko:zebec-network",
        "AVNT": "coingecko:avantis",
        "BOOPA": "coingecko:boopa"
    }

    cg_id = symbol_map.get(asset_clean, f"coingecko:{asset_clean.lower()}")

    if isinstance(date_obj, (datetime, date)):
        ts = int(time.mktime(date_obj.timetuple()))
    else:
        ts = int(time.time())

    cache_key = f"DEFLLAMA_{cg_id}_{ts}"
    if cache_key in FX_CACHE:
        return FX_CACHE[cache_key]

    try:
        url = f"https://coins.llama.fi/prices/historical/{ts}/{cg_id}"
        res = requests.get(url, timeout=1.0)
        if res.status_code == 200:
            data = res.json().get("coins", {})
            if cg_id in data:
                price = float(data[cg_id]["price"])
                FX_CACHE[cache_key] = price
                return price
    except Exception:
        pass

    # Secondary CoinGecko Simple Price API lookup
    try:
        raw_id = cg_id.replace("coingecko:", "")
        cg_url = f"https://api.coingecko.com/api/v3/simple/price?ids={raw_id}&vs_currencies=usd"
        res_cg = requests.get(cg_url, timeout=1.0)
        if res_cg.status_code == 200:
            cg_data = res_cg.json()
            if raw_id in cg_data and "usd" in cg_data[raw_id]:
                price = float(cg_data[raw_id]["usd"])
                FX_CACHE[cache_key] = price
                return price
    except Exception:
        pass

    FX_CACHE[cache_key] = 0.0
    return 0.0

def convert_to_eur(amount: float, asset_or_currency: str, date_obj) -> tuple:
    """
    Convertit un montant en EUR et renvoie (montant_eur, taux_applique, date_taux, source, paire_fx).
    """
    if amount == 0.0 or not asset_or_currency:
        return (0.0, 1.0, str(date_obj)[:10], "N/A", "EUR/EUR")

    curr = str(asset_or_currency).upper().strip()
    d_str = str(date_obj)[:10]

    fiats = ["USD", "GBP", "CHF", "CAD", "JPY", "AUD", "CNY"]

    if curr == "EUR":
        return (amount, 1.0, d_str, "BCE (ECB)", "EUR/EUR")

    if curr in fiats:
        taux_eur = get_ecb_eur_rate(curr, date_obj)
        montant_eur = amount * taux_eur
        return (montant_eur, taux_eur, d_str, "BCE (ECB)", f"{curr}/EUR")

    # Moteur Crypto -> USD -> EUR
    usd_price = get_crypto_usd_price_defillama(curr, date_obj)
    if usd_price > 0:
        usd_eur = get_ecb_eur_rate("USD", date_obj)
        taux_combine = usd_price * usd_eur
        montant_eur = amount * taux_combine
        return (montant_eur, taux_combine, d_str, "DefiLlama / BCE", f"{curr}/EUR")

    return (0.0, 0.0, d_str, "Indisponible", f"{curr}/EUR")
