import pandas as pd
import shared_logic as sl
from datetime import datetime

# Load the mock data we created
df = sl.pd_read_csv_safe("sanctuarisation/2024/qualified_journal_CLEAN_2024.csv")
df["Date"] = pd.to_datetime(df["Date"])
df["Imposable"] = df["Imposable"].apply(sl.is_imposable_robust)

print(f"Total rows: {len(df)}")
mask = df.apply(sl.is_cession_imposable_robust, axis=1)
print(f"Imposable cessions detected by robust logic: {mask.sum()}")
print(df[mask][["Date", "Asset", "Amount", "Imposable"]])

# Mock appPropri logic
cess_dates = sorted(df[mask]["Date"].dt.date.unique(), reverse=True)
print(f"Unique cession dates: {len(cess_dates)}")
