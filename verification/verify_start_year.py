
import shared_logic as sl
import os
import json
from datetime import datetime
import pandas as pd

def test_start_year_logic():
    # Setup global config
    config = {"start_year": 2022, "processing_year": 2022}
    sl.save_global_config(config)

    # Create a dummy inventory for 2021 (which should be ignored)
    os.makedirs("sanctuarisation/2021", exist_ok=True)
    with open("sanctuarisation/2021/inventory_EOY_2021.csv", "w") as f:
        f.write("Location,Asset,Solde\nAccount: 0x123,BTC,1.0\n")

    # Get snapshot for 2022
    target_date = datetime(2022, 1, 1)
    df, total = sl.get_portfolio_snapshot(2022, target_date=target_date)

    print(f"Snapshot for 2022 (Start Year): {len(df)} rows, total {total}")

    # Should be empty because 2022 is the start year, so it ignores 2021 inventory
    assert len(df) == 0
    assert total == 0.0

    # Change processing year to 2023
    config["processing_year"] = 2023
    sl.save_global_config(config)

    # Create a dummy inventory for 2022
    os.makedirs("sanctuarisation/2022", exist_ok=True)
    with open("sanctuarisation/2022/inventory_EOY_2022.csv", "w") as f:
        f.write("Location,Asset,Solde\nAccount: 0x123,BTC,2.0\n")

    # Get snapshot for 2023
    target_date = datetime(2023, 1, 1)
    df, total = sl.get_portfolio_snapshot(2023, target_date=target_date)

    print(f"Snapshot for 2023 (Normal Year): {len(df)} rows")
    # Should NOT be empty because 2023 is not the start year (2022 is)
    assert len(df) > 0

    print("Start year logic test passed!")

if __name__ == "__main__":
    test_start_year_logic()
