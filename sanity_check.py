import pandas as pd
import shared_logic as sl
import os

def test_spam_filter():
    print("Testing Spam Filter...")
    sl.save_spam_list({"spamtoken", "0x666"})
    sl.save_valid_assets({"ETH", "USDT"})

    df = pd.DataFrame([
        {"Asset": "ETH", "Counterparty": "0x123", "Status": "Valide"},
        {"Asset": "SPAMTOKEN", "Counterparty": "0x456", "Status": "A vérifier"},
        {"Asset": "DOGE", "Counterparty": "0x666", "Status": "A vérifier"},
        {"Asset": "SPAMTOKEN", "Counterparty": "0x789", "Status": "Valide"} # Should be caught by name
    ])

    filtered = sl.apply_spam_filter(df, drop=True)
    print(f"Filtered count (drop=True): {len(filtered)} (Expected: 1)")

    marked = sl.apply_spam_filter(df, drop=False)
    print(f"Marked Spam count: {len(marked[marked['Status'] == 'Spam'])} (Expected: 3)")

def test_address_standardization():
    print("\nTesting Address Standardization...")
    sl.save_owner_accounts({"0x123": "MyWallet"})

    addr = "0x123"
    std = sl.standardize_address_string(addr)
    print(f"Standardized {addr} -> {std} (Expected: 0x123 (MyWallet))")

    label = "MyWallet"
    std2 = sl.standardize_address_string(label)
    print(f"Standardized {label} -> {std2} (Expected: 0x123 (MyWallet))")

def test_csv_row_removal():
    print("\nTesting CSV Row Removal...")
    test_file = "test_removal.csv"
    df = pd.DataFrame([
        {"Date": "2023-01-01", "Account": "0x1", "Asset": "ETH", "Amount": 1.0, "Tx Hash": "H1"},
        {"Date": "2023-01-02", "Account": "0x2", "Asset": "BTC", "Amount": 0.5, "Tx Hash": "H2"}
    ])
    df.to_csv(test_file, index=False)

    row_to_del = {"Date": "2023-01-01", "Account": "0x1", "Asset": "ETH", "Amount": 1.0, "Tx Hash": "H1"}
    success = sl.remove_row_from_csv(test_file, row_to_del)

    df_after = pd.read_csv(test_file)
    print(f"Removal success: {success}, Remaining rows: {len(df_after)} (Expected: True, 1)")

    if os.path.exists(test_file): os.remove(test_file)

if __name__ == "__main__":
    test_spam_filter()
    test_address_standardization()
    test_csv_row_removal()
