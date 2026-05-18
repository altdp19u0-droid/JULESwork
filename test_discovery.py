import pandas as pd
import app2
import shared_logic as sl

# V4 file
df = pd.DataFrame({
    'Date': ['2025-01-01'],
    'Account': ['0x123'],
    'Asset': ['ETH'],
    'Amount': [1.0],
    'Tx_Hash': ['0xH1']
})
df.to_csv("sanctuarisation/2025/raw_v4.csv", index=False)

res = app2.merge_raw_data(2025)
print(f"Rows found: {len(res)}")
for _, r in res.iterrows():
    print(f"Date: {r['Date']}, Asset: {r['Asset']}, Amt: {r['Amount']}")
