
import pandas as pd
import streamlit as st

def test_counterparty_filter():
    # Mock data
    data = [
        {"Counterparty": "Binance", "Asset": "BTC"},
        {"Counterparty": "Kraken", "Asset": "ETH"},
        {"Counterparty": "Binance", "Asset": "SOL"}
    ]
    df = pd.DataFrame(data)

    # Filter for Binance
    fcp = ["Binance"]
    df_filtered = df[df["Counterparty"].isin(fcp)]

    print("Filtered DataFrame:")
    print(df_filtered)

    assert len(df_filtered) == 2
    assert (df_filtered["Counterparty"] == "Binance").all()
    print("Counterparty filter test passed!")

if __name__ == "__main__":
    test_counterparty_filter()
