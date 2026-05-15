
import pandas as pd
import shared_logic as sl
import os
import json

def test_whitelist_logic():
    # Setup
    test_whitelist = {"BTC", "ETH", "USDC"}
    sl.save_valid_assets(test_whitelist)

    loaded = sl.load_valid_assets()
    print(f"Loaded whitelist: {loaded}")
    assert "BTC" in loaded
    assert "ETH" in loaded
    assert "USDC" in loaded

    # Mock data
    data = [
        {"Asset": "BTC", "Status": "A vérifier"},
        {"Asset": "ETH", "Status": "A vérifier"},
        {"Asset": "SPAM_TOKEN", "Status": "A vérifier"},
        {"Asset": "usdc", "Status": "A vérifier"}
    ]
    df = pd.DataFrame(data)

    # Simulate "Valide Auto" logic
    v_list = sl.load_valid_assets()
    mask = df["Asset"].fillna("").str.upper().str.strip().isin(v_list)
    df.loc[mask, "Status"] = "Valide"

    print("Resulting DataFrame:")
    print(df)

    assert df.loc[0, "Status"] == "Valide"
    assert df.loc[1, "Status"] == "Valide"
    assert df.loc[2, "Status"] == "A vérifier"
    assert df.loc[3, "Status"] == "Valide"

    print("Whitelist test passed!")

if __name__ == "__main__":
    test_whitelist_logic()
