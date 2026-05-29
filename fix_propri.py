import shared_logic as sl
import pandas as pd

filepath = 'appPropri.py'
with open(filepath, 'r') as f:
    content = f.read()

# Fix get_cessions_summary to filter by year
old_func = """@st.cache_data
def get_cessions_summary(year, df_j):
    \"\"\"Calculates VGP for all unique cession transactions found in the journal.\"\"\"
    if df_j.empty: return pd.DataFrame()

    # Identify Cessions: STRICT Logic (Must be imposable)
    mask_cess = df_j.apply(sl.is_cession_imposable_robust, axis=1)
    cess_entries = df_j[mask_cess].sort_values("Date", ascending=False)

    # Add EOY
    eoy_d = datetime(year, 12, 31, 23, 59, 59, tzinfo=df_j["Date"].dt.tzinfo)
    snap_res_eoy = sl.get_portfolio_snapshot(year, eoy_d, df_override=df_j)
    vgp_eoy = snap_res_eoy[1] if isinstance(snap_res_eoy, tuple) else 0.0

    summary_data = [{
        "Date": eoy_d.date(),
        "Asset": "---",
        "Quantité": 0.0,
        "Événement": "🏁 Fin d'année",
        "VGP (€)": vgp_eoy
    }]

    for _, row in cess_entries.iterrows():
        # VGP at the moment of cession
        snap_res = sl.get_portfolio_snapshot(year, row["Date"], df_override=df_j)
        vgp_val = snap_res[1] if isinstance(snap_res, tuple) else 0.0

        summary_data.append({
            "Date": row["Date"].date(),
            "Asset": row["Asset"],
            "Quantité": abs(row["Amount"]),
            "Événement": "📉 Cession Imposable",
            "VGP (€)": vgp_val
        })
    return pd.DataFrame(summary_data)"""

new_func = """@st.cache_data
def get_cessions_summary(year, df_j):
    \"\"\"Calculates VGP for all unique cession transactions found in the journal for the target year.\"\"\"
    if df_j.empty: return pd.DataFrame()

    # Identify Cessions: STRICT Logic (Must be imposable AND in target year)
    # We load history to have correct balances, but we only show cessions of the year.
    mask_cess = df_j.apply(sl.is_cession_imposable_robust, axis=1) & (df_j["Date"].dt.year == year)
    cess_entries = df_j[mask_cess].sort_values("Date", ascending=False)

    # Add EOY
    eoy_d = datetime(year, 12, 31, 23, 59, 59, tzinfo=df_j["Date"].dt.tzinfo)
    snap_res_eoy = sl.get_portfolio_snapshot(year, eoy_d, df_override=df_j)
    vgp_eoy = snap_res_eoy[1] if isinstance(snap_res_eoy, tuple) else 0.0

    summary_data = [{
        "Date": eoy_d.date(),
        "Asset": "---",
        "Quantité": 0.0,
        "Événement": "🏁 Bilan Fin d'année",
        "VGP (€)": vgp_eoy
    }]

    for _, row in cess_entries.iterrows():
        # VGP at the moment of cession
        snap_res = sl.get_portfolio_snapshot(year, row["Date"], df_override=df_j)
        vgp_val = snap_res[1] if isinstance(snap_res, tuple) else 0.0

        summary_data.append({
            "Date": row["Date"].date(),
            "Asset": row["Asset"],
            "Quantité": abs(row["Amount"]),
            "Événement": "📉 Cession Imposable",
            "VGP (€)": vgp_val
        })
    return pd.DataFrame(summary_data)"""

if old_func in content:
    content = content.replace(old_func, new_func)
else:
    print("Function not found exactly, trying partial match")
    # Partial match for the summary_data part
    old_part = '\"Événement\": \"🏁 Fin d\'année\"'
    new_part = '\"Événement\": \"🏁 Bilan Fin d\'année\"'
    content = content.replace(old_part, new_part)

with open(filepath, 'w') as f:
    f.write(content)
