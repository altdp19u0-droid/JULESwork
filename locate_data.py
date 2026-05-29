import shared_logic as sl
import os

years = [2021, 2022, 2023, 2024, 2025, 2026]
categories = ['fiat', 'swaps', 'qualified', 'qualified_full', 'qualified_clean']

for y in years:
    print(f"--- Year {y} ---")
    for cat in categories:
        p = sl.get_file_path(y, cat)
        exists = os.path.exists(p)
        print(f"{cat}: {p} (Exists: {exists})")
        if exists:
             try:
                 df = sl.pd_read_csv_safe(p)
                 print(f"  Rows: {len(df)}")
             except:
                 print("  Error reading")
