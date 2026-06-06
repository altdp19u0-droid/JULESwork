import pandas as pd
import os
import json
from datetime import datetime

# Mock shared_logic functions to avoid dependency issues in script
def is_imposable_robust(val):
    if isinstance(val, bool): return val
    s = str(val).upper().strip()
    return s in ["TRUE", "1", "1.0", "VRAI", "YES", "OUI"]

# Minimal mock for test
class MockSL:
    def __init__(self):
        self.acquisitions = []

    def get_total_acquisition_value(self, year, until_date=None):
        total = 0.0
        for date, val in self.acquisitions:
            if until_date is None or date <= until_date:
                total += val
        return total

sl = MockSL()
sl.acquisitions = [
    (pd.to_datetime("2024-01-01", utc=True), 1000.0), # Fiat Purchase
    (pd.to_datetime("2024-02-01", utc=True), 50.0),   # Staking Interest
]

def calculate_fiscal_gains_mock(cessions_df, year):
    df = cessions_df.sort_values("Date", ascending=True).copy()
    df["Plus-Value Brute"] = 0.0
    df["Fraction du Capital Consommé"] = 0.0
    cumulative_consumed = 0.0

    for idx, row in df.iterrows():
        p_vent = float(row["Prix de Cession (EUR)"])
        vgp = float(row["VGP (EUR)"])
        d_date = row["Date"]

        raw_acq_total = sl.get_total_acquisition_value(year, until_date=d_date)
        current_acq_base = max(0.0, raw_acq_total - cumulative_consumed)

        if vgp > 0:
            fraction = p_vent / vgp
            abattement = current_acq_base * fraction
            gain = p_vent - abattement
            df.at[idx, "Plus-Value Brute"] = gain
            df.at[idx, "Fraction du Capital Consommé"] = abattement
            cumulative_consumed += abattement

    return df, cumulative_consumed

# Test Scenario
cessions = pd.DataFrame([
    {"Date": pd.to_datetime("2024-03-01", utc=True), "Prix de Cession (EUR)": 200.0, "VGP (EUR)": 2000.0},
    {"Date": pd.to_datetime("2024-04-01", utc=True), "Prix de Cession (EUR)": 300.0, "VGP (EUR)": 1500.0}
])

results, consumed = calculate_fiscal_gains_mock(cessions, 2024)

print("--- Fiscal Calculation Verification ---")
for idx, r in results.iterrows():
    print(f"Date: {r['Date'].date()} | Cession: {r['Prix de Cession (EUR)']} | VGP: {r['VGP (EUR)']} | PV: {r['Plus-Value Brute']:.2f} | Abattement: {r['Fraction du Capital Consommé']:.2f}")

# Manual verification:
# Cession 1: Base = 1050. Fraction = 200/2000 = 0.1. Abat = 1050 * 0.1 = 105. Gain = 200 - 105 = 95.
# Cession 2: Base = 1050 - 105 = 945. Fraction = 300/1500 = 0.2. Abat = 945 * 0.2 = 189. Gain = 300 - 189 = 111.
# Consumed = 105 + 189 = 294.

expected_pv1 = 95.0
expected_pv2 = 111.0

assert abs(results.iloc[0]["Plus-Value Brute"] - expected_pv1) < 1e-6
assert abs(results.iloc[1]["Plus-Value Brute"] - expected_pv2) < 1e-6
print("SUCCESS: Fiscal Formula is correct and sequential.")
