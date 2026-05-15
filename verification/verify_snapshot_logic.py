
import pandas as pd
import shared_logic as sl
import os
import json
from datetime import datetime

def test_manual_positions_and_spam():
    # Setup
    year = 2024
    os.makedirs(f"sanctuarisation/{year}", exist_ok=True)
    os.makedirs(f"sanctuarisation/{year-1}", exist_ok=True)

    # 1. Previous year inventory
    # Standardize Location: "Account: ledger" (lowercased)
    inv_prev = [
        {"Location": "Account: ledger", "Asset": "BTC", "Solde": 1.0}
    ]
    pd.DataFrame(inv_prev).to_csv(f"sanctuarisation/{year-1}/inventory_EOY_{year-1}.csv", index=False)

    # 2. Manual position in current year
    pos_data = [
        {"Date": "2024-01-01", "Account": "binance", "Asset": "ETH", "Quantité": 5.0}
    ]
    pd.DataFrame(pos_data).to_csv(f"sanctuarisation/{year}/manual_positions_{year}.csv", index=False)

    # 3. Journal with valid and spam
    qual_data = [
        {"Date": "2024-02-01", "Account": "ledger", "Asset": "BTC", "Amount": -0.5, "Status": "Valide", "Category": "Vente", "Counterparty": "exchange", "Imposable": True},
        {"Date": "2024-02-01", "Account": "ledger", "Asset": "SPAM", "Amount": 1000.0, "Status": "Spam", "Category": "A vérifier", "Counterparty": "0xspam", "Imposable": False}
    ]
    pd.DataFrame(qual_data).to_csv(f"sanctuarisation/{year}/qualified_journal_{year}.csv", index=False)

    # 4. Global config: start year 2023 (so it picks up 2023 inventory)
    sl.save_global_config({"start_year": 2023, "processing_year": 2024})

    # Run snapshot
    target_date = datetime(2024, 12, 31)
    df, total = sl.get_portfolio_snapshot(year, target_date)

    print("Snapshot results:")
    print(df)

    # EXPECTATIONS:
    # - BTC on Ledger: 1.0 (from EOY 2023) - 0.5 (Valid Tx) = 0.5
    # - ETH on Binance: 5.0 (from Manual Position)
    # - SPAM: should be ABSENT

    # Check BTC (Locations are standardized to "Account: ledger")
    btc_row = df[(df["Asset"] == "BTC") & (df["Location"] == "Account: ledger")]
    assert not btc_row.empty
    assert btc_row.iloc[0]["Solde"] == 0.5

    # Check ETH (Locations are standardized to "Manual Position: binance")
    eth_row = df[(df["Asset"] == "ETH") & (df["Location"] == "Manual Position: binance")]
    assert not eth_row.empty
    assert eth_row.iloc[0]["Solde"] == 5.0

    # Check SPAM
    spam_row = df[df["Asset"] == "SPAM"]
    assert spam_row.empty

    print("Manual positions and Zero Spam test passed!")

if __name__ == "__main__":
    test_manual_positions_and_spam()
