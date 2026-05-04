import shared_logic
names = [
    "resolve_raw_addr", "get_portfolio_snapshot", "get_price_eur",
    "pd_read_csv_safe", "get_file_path", "validate_spam_exclusion",
    "load_owner_accounts", "get_total_acquisition_value", "standardize_df_addresses",
    "load_manual_notes", "save_manual_notes", "get_note_key"
]
for n in names:
    try:
        getattr(shared_logic, n)
        print(f"{n}: OK")
    except AttributeError:
        print(f"{n}: MISSING")
