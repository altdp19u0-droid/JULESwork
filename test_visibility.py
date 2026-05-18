import pandas as pd
import shared_logic as sl
import os

def discover_col(df, candidates):
    cols = {str(c).lower().strip().replace(" ","").replace("_","").replace("(","").replace(")",""): c for c in df.columns}
    for cand in candidates:
        c_norm = cand.lower().replace(" ","").replace("_","")
        if c_norm in cols: return cols[c_norm]
        for k in cols:
            if c_norm in k: return cols[k]
    return None

# Simulate a RAW V4 file from app.py
data = {
    'Date': ['2025-05-01 10:00:00', '2025-05-02 11:00:00'],
    'Account': ['0x123', '0x123'],
    'Asset': ['ETH', 'USDC'],
    'Amount': [-1.0, 100.0],
    'Tx_Hash': ['0xH1', '0xH2'],
    'Chain': ['ETH', 'ETH']
}
df = pd.DataFrame(data)
df.to_csv("sanctuarisation/2025/raw_transactions_test_v4.csv", index=False)

# Test Discovery
d_col = discover_col(df, ["date"])
print(f"Discovered Date Col: {d_col}")

acc_col = discover_col(df, ["account"])
print(f"Discovered Account Col: {acc_col}")

# Simulation of the loop
rows = []
for _, r in df.iterrows():
    dt_val = r.get(d_col)
    acc = str(r.get(acc_col, "fallback")).lower()
    print(f"Row: Date={dt_val}, Acc={acc}")
    rows.append({"Date": dt_val, "Account": acc})

print(f"Total rows processed: {len(rows)}")
