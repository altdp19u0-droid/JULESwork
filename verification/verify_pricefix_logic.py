
import pandas as pd
import shared_logic as sl
import os
import json
from datetime import datetime

def test_price_fix_scan():
    # Setup mock data for 2023
    year = 2023
    os.makedirs(f"sanctuarisation/{year}", exist_ok=True)

    # 1. Qualified journal with one valid and one spam
    qual_data = [
        {"Date": "2023-06-01", "Asset": "BTC", "Amount": 1.0, "Status": "Valide", "Imposable": True, "Counterparty": "Binance", "Category": "Vente"},
        {"Date": "2023-06-02", "Asset": "SPAM_COIN", "Amount": 1000.0, "Status": "Spam", "Imposable": False, "Counterparty": "0xspam", "Category": "A vérifier"}
    ]
    pd.DataFrame(qual_data).to_csv(f"sanctuarisation/{year}/qualified_journal_{year}.csv", index=False)

    # 2. Manual position with another valid asset
    pos_data = [
        {"Date": "2023-01-01", "Account": "Ledger", "Asset": "ETH", "Quantité": 2.0}
    ]
    pd.DataFrame(pos_data).to_csv(f"sanctuarisation/{year}/manual_positions_{year}.csv", index=False)

    # 3. Add SPAM_COIN to blacklist for extra safety
    sl.save_spam_list({"spam_coin", "0xspam"})

    # Run scan from appPriceFix (simulated)
    from appPriceFix import scan_needed_prices

    needed = scan_needed_prices([str(year)], exclude_spams=True)

    print("Needed prices:")
    print(needed)

    # Expectations:
    # - BTC at 2023-06-01 (Cession)
    # - BTC at 2023-12-31 (EOY)
    # - ETH at 2023-12-31 (EOY)
    # - SPAM_COIN should be ABSENT

    assets = set(needed["Asset"].unique())
    print(f"Assets found: {assets}")

    assert "BTC" in assets
    assert "ETH" in assets
    assert "SPAM_COIN" not in assets

    dates_btc = set(needed[needed["Asset"] == "BTC"]["Date"])
    assert datetime(2023, 6, 1).date() in dates_btc
    assert datetime(2023, 12, 31).date() in dates_btc

    print("PriceFix scan logic test passed!")

if __name__ == "__main__":
    test_price_fix_scan()
