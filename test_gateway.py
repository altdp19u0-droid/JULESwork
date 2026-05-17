import pandas as pd
import shared_logic as sl
import os
from datetime import datetime

def test_gateway_loading():
    print("Testing Gateway Loading (load_clean_history)...")
    year = 2023
    # 1. Create a dummy qualified file
    qual_path = sl.get_file_path(year, 'qualified')
    df_qual = pd.DataFrame([
        {"Date": "2023-01-01", "Account": "0x1", "Asset": "ETH", "Amount": 1.0, "Status": "Valide"},
        {"Date": "2023-01-02", "Account": "0x2", "Asset": "SPAM", "Amount": 100.0, "Status": "Spam"}
    ])
    df_qual.to_csv(qual_path, index=False)

    # 2. Load (should filter spam)
    df_loaded = sl.load_clean_history(year)
    print(f"Loaded from Qual (filtered): {len(df_loaded)} (Expected: 1)")

    # 3. Create a dummy CLEAN file
    clean_path = sl.get_file_path(year, 'qualified_clean')
    df_clean = pd.DataFrame([
        {"Date": "2023-01-01", "Account": "0x1", "Asset": "ETH", "Amount": 1.0, "Status": "Valide"},
        {"Date": "2023-01-03", "Account": "0x1", "Asset": "BTC", "Amount": 0.5, "Status": "Valide"}
    ])
    df_clean.to_csv(clean_path, index=False)

    # 4. Load (should prefer clean)
    df_loaded_clean = sl.load_clean_history(year)
    print(f"Loaded from CLEAN: {len(df_loaded_clean)} (Expected: 2)")

    # Cleanup
    if os.path.exists(qual_path): os.remove(qual_path)
    if os.path.exists(clean_path): os.remove(clean_path)

if __name__ == "__main__":
    test_gateway_loading()
